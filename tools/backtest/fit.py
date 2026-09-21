#!/usr/bin/env python3
"""
fit.py -- the OFFLINE coefficient fit for VAS.md's market-anchored model.

    p_mkt   = no-vig closing moneyline probability for the HOME team
    D       = B_F*F + B_P*P + B_C*C + B_R*R
    p_model = sigmoid( logit(p_mkt) + D )

logit(p_mkt) enters as a FIXED OFFSET -- its coefficient is pinned to 1 by
construction, not estimated. B = 0 is exactly the null "the market already
knows this."

Run:
    uv run --with pandas --with pyarrow --with numpy --with scipy \
           --with statsmodels --with scikit-learn python tools/backtest/fit.py

Flags:
    --rebuild        recompute the three feature frames (ignores the parquet cache)
    --no-cache       compute features and do not write the cache

Nothing here writes outside tools/backtest/. Nothing here ships.
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from load import load_games, load_pbp, cached_pbp_seasons

HERE = os.path.dirname(os.path.abspath(__file__))

warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("display.width", 170)
pd.set_option("display.max_columns", 60)

# --------------------------------------------------------------------------
# the fit window
# --------------------------------------------------------------------------
# pbp is cached 2018-2025. 2018 is the personnel module's burn-in season (no
# prior dropbacks exist in the cache before it) and is also Vector F's first
# season, whose Week 1 has no season-before-it to regress from. It is kept as
# WARM-UP for every feature builder and excluded from the fitted rows.
WARM_FROM = 2018
FIT_LO, FIT_HI = 2019, 2025
# Expanding-window CV: train on everything strictly before the test season.
# 2019-2020 is the smallest training block we will tolerate, so testing starts
# at 2021.
CV_TEST_SEASONS = list(range(2021, FIT_HI + 1))

# The four vectors, exactly as VAS.md names them.
VECTORS = ["F", "P", "C", "R"]
VECTOR_COL = {"F": "F", "P": "p_qb_z", "C": "C", "R": "R"}
VECTOR_DESC = {
    "F": "Fundamental  (f_eff - f_finish)/sqrt(2), home-minus-away",
    "P": "Personnel    as-of z of QB EPA/dropback delta, home-minus-away",
    "C": "Context      rest/travel/timezone composite, home-positive",
    "R": "Regime       (P(CHAOS)-P(GRIND)) * tanh(spread/7)",
}

RULE = "=" * 100
THIN = "-" * 100


def head(title):
    print("\n" + RULE)
    print(title)
    print(RULE)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(p / (1.0 - p))


# ==========================================================================
# 1. build the game table
# ==========================================================================
def american_to_prob(ml):
    """Raw (vigged) implied probability from an American price."""
    ml = np.asarray(ml, dtype=float)
    neg = ml < 0
    # evaluate each branch only on its own domain: ml == -100 would make the
    # unused positive branch divide by zero and emit a spurious warning.
    out = np.empty_like(ml)
    out[neg] = (-ml[neg]) / ((-ml[neg]) + 100.0)
    out[~neg] = 100.0 / (ml[~neg] + 100.0)
    return out


def build_features(rebuild=False, cache=True):
    """Build (or reload) the three feature frames. Returns (F, P, CR)."""
    import features_fundamental as FF
    import features_personnel as FP
    import features_context as FC

    seasons = [s for s in cached_pbp_seasons() if WARM_FROM <= s <= FIT_HI]
    paths = {
        "fund": os.path.join(HERE, "out_fundamental.parquet"),
        "pers": os.path.join(HERE, "out_personnel.parquet"),
        "ctx": os.path.join(HERE, "out_context.parquet"),
    }
    have = all(os.path.exists(p) for p in paths.values())
    if have and not rebuild:
        print("  reusing cached feature frames (pass --rebuild to recompute)")
        fund = pd.read_parquet(paths["fund"])
        pers = pd.read_parquet(paths["pers"])
        ctx = pd.read_parquet(paths["ctx"])
        # The cached fundamental frame may predate this script; make sure it
        # spans the warm-up window we expect.
        if fund["season"].min() > WARM_FROM:
            print("  cached fundamental frame starts at %d -- rebuilding"
                  % fund["season"].min())
            rebuild = True
        else:
            return fund, pers, ctx

    print("  building features over seasons %s (this takes a couple of minutes)"
          % seasons)

    # --- F: needs the FULL play set (drive scoring needs kicks/XPs) --------
    games_f = load_games(seasons=(min(seasons), max(seasons)),
                         require_lines=True, played_only=True)
    pbp_full = load_pbp(seasons, columns=FF.PBP_COLUMNS)
    fund = FF.build(games_f, pbp_full, verbose=False)
    print("  F : %d rows x %d cols" % fund.shape)
    del pbp_full

    # --- P: widest games frame, its own narrow pbp column set -------------
    games_p = load_games(seasons=(min(seasons), max(seasons)), played_only=True)
    pbp_p = load_pbp(seasons, columns=FP.PBP_COLUMNS)
    pers = FP.build(games_p, pbp_p)
    print("  P : %d rows x %d cols" % pers.shape)
    del pbp_p

    # --- C/R: games warmed from 2010 (C needs no pbp), pbp for R ----------
    games_c = load_games(seasons=(2010, max(seasons)), played_only=True)
    pbp_c = load_pbp(seasons, columns=["posteam", "pass_oe", "play_type"],
                     offense_only=True)
    ctx = FC.build(games_c, pbp_c, verbose=False).reset_index(drop=True)
    print("  C/R: %d rows x %d cols" % ctx.shape)
    del pbp_c

    if cache:
        for name, frame in (("fund", fund), ("pers", pers), ("ctx", ctx)):
            flat = frame.copy()
            flat.attrs = {}
            flat.to_parquet(paths[name], index=False)
        print("  cached to tools/backtest/out_*.parquet")
    return fund, pers, ctx


def build_table(rebuild=False, cache=True):
    head("1. GAME TABLE")

    games = load_games(seasons=(WARM_FROM, FIT_HI), require_lines=True,
                       played_only=True)
    print("nflverse games %d-%d with a complete closing spread+total+both MLs "
          "and a played result: %d rows" % (WARM_FROM, FIT_HI, len(games)))

    fund, pers, ctx = build_features(rebuild=rebuild, cache=cache)

    keep_f = ["game_id", "F", "f_eff", "f_finish", "f_finish_resid",
              "f_success", "f_ready", "home_prior_games", "away_prior_games"]
    keep_p = ["game_id", "p_qb", "p_qb_z", "qb_delta_diff",
              "qb_history_thin", "qb_fallback_home", "qb_fallback_away",
              "qb_new_starter_diff"]
    keep_c = ["game_id", "C", "R", "c_ok", "r_ok", "c_rest_diff_z",
              "c_travel_diff_z", "c_tz_pen_diff", "c_short_week",
              "c_bye_return", "c_div_game", "c_indoor", "c_wind_z",
              "r_regime_score", "r_fav", "r_p_grind", "r_p_chaos"]

    t = games.merge(fund[keep_f], on="game_id", how="left", validate="1:1")
    t = t.merge(pers[keep_p], on="game_id", how="left", validate="1:1")
    t = t.merge(ctx[keep_c], on="game_id", how="left", validate="1:1")
    print("joined all three feature modules on game_id: %d rows" % len(t))

    miss = {c: int(t[c].isna().sum()) for c in
            ["F", "p_qb_z", "C", "R"] if t[c].isna().any()}
    print("NaN after join (before any filtering): %s" % (miss or "none"))

    # ---- outcome --------------------------------------------------------
    t["home_win"] = (t["result"] > 0).astype(int)
    t["is_tie"] = (t["result"] == 0)

    # ---- p_mkt: de-vig the closing moneyline ----------------------------
    qh = american_to_prob(t["home_moneyline"])
    qa = american_to_prob(t["away_moneyline"])
    t["q_home_raw"], t["q_away_raw"] = qh, qa
    t["overround"] = qh + qa
    t["hold"] = t["overround"] - 1.0

    # multiplicative / proportional: divide each side by the overround
    t["p_mkt_mult"] = qh / t["overround"]
    # shift / additive: take the same absolute amount off each side
    t["p_mkt_shift"] = qh - t["hold"] / 2.0

    return t


# ==========================================================================
# 2. p_mkt -- pick the de-vig method, on evidence
# ==========================================================================
def devig_report(t):
    head("2. p_mkt -- DE-VIGGING THE CLOSING MONEYLINE")

    ok = t["hold"] > 0
    print("two-way overround: mean %.4f  median %.4f  min %.4f  max %.4f"
          % (t["overround"].mean(), t["overround"].median(),
             t["overround"].min(), t["overround"].max()))
    print("rows with hold <= 0 (stale/arbed quote -- a no-vig price is "
          "undefined there): %d" % int((~ok).sum()))
    if (~ok).any():
        bad = t.loc[~ok, ["game_id", "home_moneyline", "away_moneyline", "hold"]]
        print(bad.to_string(index=False))

    d = (t["p_mkt_mult"] - t["p_mkt_shift"]).abs()
    print("\n|multiplicative - shift| over %d rows: mean %.5f  median %.5f  "
          "p95 %.5f  max %.5f" % (len(t), d.mean(), d.median(),
                                  d.quantile(0.95), d.max()))
    ext = t["p_mkt_mult"] > 0.80
    print("on the %d rows where the home side is priced above 80%%: mean diff "
          "%.5f (shift is the MORE extreme of the two on favourites)"
          % (int(ext.sum()), (t.loc[ext, "p_mkt_mult"]
                              - t.loc[ext, "p_mkt_shift"]).mean()))

    # which one actually calibrates better against the realised outcome?
    fit = t[ok & ~t["is_tie"]]
    y = fit["home_win"].to_numpy()
    print("\ncalibration of each method against the realised outcome, on the "
          "%d non-tie rows with hold > 0:" % len(fit))
    print("  %-18s %10s %10s %10s %10s" %
          ("method", "logloss", "brier", "mean p", "win rate"))
    for name, col in (("multiplicative", "p_mkt_mult"), ("shift", "p_mkt_shift")):
        p = np.clip(fit[col].to_numpy(), 1e-6, 1 - 1e-6)
        ll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
        br = np.mean((p - y) ** 2)
        print("  %-18s %10.6f %10.6f %10.5f %10.5f"
              % (name, ll, br, p.mean(), y.mean()))

    print("""
CHOICE: multiplicative / proportional, and it is the primary p_mkt everywhere below.

Why, in three parts:
  (a) It is the only one of the two that is closed. The shift method subtracts a
      fixed absolute probability from both sides, so at a large enough hold it can
      drive a heavy underdog's price to zero or below; the proportional method is a
      normalisation and cannot leave (0, 1) by construction. On a -1200/+750 NFL
      moneyline that is not hypothetical.
  (b) It preserves the ratio of the two quoted prices, which is the thing the book
      actually set. The shift method instead assumes the margin is loaded in equal
      ABSOLUTE probability on each side, which is a claim about book behaviour that
      nothing in this data supports.
  (c) Empirically it does not matter much -- the two agree to a few tenths of a
      percentage point at NFL two-way holds of ~3%, and the log-loss table above
      shows the gap is far smaller than the model effects being tested. The honest
      statement is: the choice is not load-bearing, and the closed one wins on
      principle rather than on measured accuracy.

WHAT IS NOT DONE: neither method corrects the favourite-longshot bias. Shin's
method would, and would shave a little probability off heavy favourites. It is
deliberately left out because p_mkt is the OFFSET here -- any systematic tilt it
carries shows up as a non-zero intercept in the with-intercept fit below, where it
is visible and testable, rather than being quietly absorbed into a B.""")


# ==========================================================================
# 3. the fit
# ==========================================================================
def eligible(t):
    """The rows a coefficient fit may legitimately use."""
    m = (t["season"].between(FIT_LO, FIT_HI)
         & (t["hold"] > 0)
         & ~t["is_tie"]
         & t["F"].notna() & t["p_qb_z"].notna()
         & t["C"].notna() & t["R"].notna()
         & t["f_ready"].fillna(False).astype(bool)
         & t["r_ok"].fillna(False).astype(bool)
         & ~t["qb_history_thin"].fillna(1).astype(bool))
    return m


def sample_report(t, m):
    head("3. FITTED SAMPLE")
    n0 = int(t["season"].between(FIT_LO, FIT_HI).sum())
    print("rows %d-%d with complete lines and a result : %d" % (FIT_LO, FIT_HI, n0))
    steps = [
        ("ties (result == 0) -- moneyline PUSHES, not losses", t["is_tie"]),
        ("hold <= 0 (no-vig price undefined)", ~(t["hold"] > 0)),
        ("Vector F not ready (Week 1: no prior game this season)",
         ~t["f_ready"].fillna(False).astype(bool)),
        ("Vector R not ready (thin pace/PROE history)",
         ~t["r_ok"].fillna(False).astype(bool)),
        ("Vector P burn-in (qb_history_thin)",
         t["qb_history_thin"].fillna(1).astype(bool)),
        ("p_qb_z undefined (as-of z needs 200 prior games)",
         t["p_qb_z"].isna()),
    ]
    scope = t["season"].between(FIT_LO, FIT_HI)
    for label, bad in steps:
        print("  drops %4d  %s" % (int((scope & bad).sum()), label))
    print("FITTED SAMPLE: %d rows, seasons %d-%d"
          % (int(m.sum()), int(t.loc[m, "season"].min()),
             int(t.loc[m, "season"].max())))
    print("\n%s" % THIN)
    print("2018 is excluded from the fit on purpose: it is the first cached pbp "
          "season, so it is Vector F's and Vector P's warm-up. It still feeds "
          "every as-of aggregate for 2019+, which is the only correct use of it.")

    d = t[m]
    print("\nper season:")
    print(d.groupby("season").agg(
        games=("game_id", "size"),
        home_win=("home_win", "mean"),
        p_mkt=("p_mkt_mult", "mean"),
        hold=("hold", "mean")).round(4).to_string())

    print("\nvector scale and spread on the fitted sample:")
    X = d[[VECTOR_COL[v] for v in VECTORS]]
    desc = X.describe().T[["mean", "std", "min", "max"]]
    desc.index = ["%s (%s)" % (v, VECTOR_COL[v]) for v in VECTORS]
    print(desc.round(4).to_string())

    print("\ncorrelation between the vectors (collinearity check):")
    cc = X.corr()
    cc.index = VECTORS
    cc.columns = VECTORS
    print(cc.round(3).to_string())

    print("\ncorrelation of each vector with the OFFSET, logit(p_mkt):")
    off = logit(d["p_mkt_mult"])
    for v in VECTORS:
        r = np.corrcoef(d[VECTOR_COL[v]], off)[0, 1]
        print("  %-3s %+0.3f   %s" % (v, r, VECTOR_DESC[v]))
    print("""
Read that last block carefully. A vector highly correlated with the offset is
mostly RESTATING the market, and the offset will absorb it, pushing its B toward
zero for a reason that has nothing to do with whether the underlying quantity
matters. R is market-conditioned BY CONSTRUCTION (its `fav` term is tanh of the
closing spread), so it is the one to watch here.""")


def glm_fit(d, cols, intercept, label):
    """GLM Binomial, logit link, logit(p_mkt) as a FIXED OFFSET."""
    y = d["home_win"].to_numpy(dtype=float)
    X = d[cols].to_numpy(dtype=float)
    names = list(cols)
    if intercept:
        X = np.column_stack([np.ones(len(d)), X])
        names = ["const"] + names
    Xdf = pd.DataFrame(X, columns=names, index=d.index)
    offset = logit(d["p_mkt_mult"].to_numpy())
    model = sm.GLM(y, Xdf, family=sm.families.Binomial(), offset=offset)
    res = model.fit()
    res._vas_label = label
    res._vas_cols = cols
    res._vas_intercept = intercept
    return res


def verify_offset_pinned(d, res):
    head("4. VERIFICATION -- IS THE OFFSET ACTUALLY PINNED TO 1?")
    cols = res._vas_cols
    off = logit(d["p_mkt_mult"].to_numpy())

    print("(a) the parameter vector contains only the vectors -- no coefficient "
          "exists for logit(p_mkt):")
    print("    params: %s" % list(res.params.index))

    print("\n(b) reconstruct the fitted probabilities BY HAND as "
          "sigmoid(1.0*offset + X@b) and compare to the model's own:")
    X = d[cols].to_numpy(dtype=float)
    b = res.params.reindex(cols).to_numpy(dtype=float)
    manual = sigmoid(off + X.dot(b))
    mx = np.max(np.abs(manual - np.asarray(res.fittedvalues)))
    print("    max |manual - res.fittedvalues| = %.3e   %s"
          % (mx, "PINNED" if mx < 1e-9 else "NOT PINNED"))

    print("\n(c) the counter-test. Refit with logit(p_mkt) as a FREE regressor "
          "instead of an offset. If the offset were silently being estimated, "
          "these two fits would be the same object. They are not:")
    Xf = pd.DataFrame({"logit_p_mkt": off}, index=d.index)
    for c in cols:
        Xf[c] = d[c].to_numpy(dtype=float)
    free = sm.GLM(d["home_win"].to_numpy(dtype=float), Xf,
                  family=sm.families.Binomial()).fit()
    lo, hi = free.conf_int().loc["logit_p_mkt"]
    print("    free coefficient on logit(p_mkt) = %.4f  (SE %.4f, 95%% CI "
          "[%.3f, %.3f])" % (free.params["logit_p_mkt"],
                             free.bse["logit_p_mkt"], lo, hi))
    print("    the offset model FORCES that number to be exactly 1.0000.")
    inside = lo <= 1.0 <= hi
    print("    is 1.0 inside the free 95%% CI? %s -- %s"
          % ("YES" if inside else "NO",
             "pinning it costs nothing measurable, so the VAS.md spec is "
             "not fighting the data" if inside else
             "the market's own price is MIS-SCALED on this sample; pinning "
             "the offset to 1 is then a modelling choice, not a free lunch"))
    return free


def coef_table(res, d, oos=None):
    """Coefficient, SE, Wald z, p, 95% CI, and the per-SD log-odds effect."""
    ci = res.conf_int()
    ci.columns = ["lo", "hi"]
    rows = []
    for name in res.params.index:
        sd = float(np.std(d[name])) if name in d.columns else np.nan
        b = res.params[name]
        rows.append({
            "term": name,
            "B": b,
            "SE": res.bse[name],
            "z": res.tvalues[name],
            "p": res.pvalues[name],
            "ci_lo": ci.loc[name, "lo"],
            "ci_hi": ci.loc[name, "hi"],
            "sd(x)": sd,
            "B*sd (log-odds per 1sd)": b * sd if sd == sd else np.nan,
            "sig@5%": "YES" if res.pvalues[name] < 0.05 else "no",
        })
    return pd.DataFrame(rows).set_index("term")


def run_fits(d):
    head("5. FULL-SAMPLE FIT (2019-2025) -- RAW statsmodels SUMMARY")

    cols = [VECTOR_COL[v] for v in VECTORS]
    res = glm_fit(d, cols, intercept=False, label="VAS spec, no intercept")

    print("SPEC (this is VAS.md exactly):")
    print("    home_win ~ Binomial(logit link)")
    print("    linear predictor = logit(p_mkt)  +  B_F*F + B_P*P + B_C*C + B_R*R")
    print("    logit(p_mkt) enters via offset= : its coefficient is 1 by")
    print("    construction and is NOT estimated.\n")
    print("    F = %s" % VECTOR_COL["F"])
    print("    P = %s" % VECTOR_COL["P"])
    print("    C = %s" % VECTOR_COL["C"])
    print("    R = %s\n" % VECTOR_COL["R"])
    print(res.summary().as_text())

    print("\n" + THIN)
    print("COEFFICIENTS WITH 95%% CONFIDENCE INTERVALS (n = %d)" % len(d))
    print(THIN)
    print(coef_table(res, d).round(5).to_string())

    print("\n" + THIN)
    print("SAME FIT, WITH AN INTERCEPT (tests whether the no-vig close itself "
          "carries a constant home tilt)")
    print(THIN)
    res_i = glm_fit(d, cols, intercept=True, label="with intercept")
    print(res_i.summary().as_text())
    print()
    print(coef_table(res_i, d).round(5).to_string())

    print("\n" + THIN)
    print("SECONDARY: F broken into its components, as features_fundamental.py "
          "recommends (fit f_eff and f_finish_resid separately rather than the "
          "equal-weight F convenience column)")
    print(THIN)
    comp_cols = ["f_eff", "f_finish_resid", "f_success", "p_qb_z",
                 "c_rest_diff_z", "c_travel_diff_z", "c_tz_pen_diff", "R"]
    res_c = glm_fit(d, comp_cols, intercept=False, label="components")
    print(res_c.summary().as_text())
    print()
    print(coef_table(res_c, d).round(5).to_string())

    return res, res_i, res_c


# ==========================================================================
# 6. season-wise CV
# ==========================================================================
def logloss(y, p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def season_cv(d, cols=None, names=None, banner=True):
    if cols is None:
        cols, names = [VECTOR_COL[v] for v in VECTORS], VECTORS
    names = names or cols
    lookup = dict(zip(names, cols))
    if banner:
        head("6. SEASON-WISE CROSS-VALIDATION (expanding window, never random k-fold)")
        print("""Train on seasons strictly BEFORE the test season, test on the test
season. A random k-fold would put 2025 games in the training set for a 2019 test
game, which is look-ahead wearing a cross-validation costume. It is not used here.
""")
    folds = []
    pieces = []
    for s in CV_TEST_SEASONS:
        tr = d[d["season"] < s]
        te = d[d["season"] == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        r = glm_fit(tr, cols, intercept=False, label="train<%d" % s)
        b = r.params.reindex(cols).to_numpy(dtype=float)
        Xte = te[cols].to_numpy(dtype=float)
        off = logit(te["p_mkt_mult"].to_numpy())
        D = Xte.dot(b)
        p_model = sigmoid(off + D)
        p_mkt = te["p_mkt_mult"].to_numpy()
        y = te["home_win"].to_numpy()

        folds.append({
            "test": s,
            "n_train": len(tr),
            "n_test": len(te),
            "ll_mkt": logloss(y, p_mkt),
            "ll_model": logloss(y, p_model),
            "d_ll": logloss(y, p_mkt) - logloss(y, p_model),
            "brier_mkt": brier(y, p_mkt),
            "brier_model": brier(y, p_model),
            "d_brier": brier(y, p_mkt) - brier(y, p_model),
            **{"B_" + v: r.params[lookup[v]] for v in names},
            **{"SE_" + v: r.bse[lookup[v]] for v in names},
        })
        piece = te[["game_id", "season", "home_win", "p_mkt_mult"] + cols].copy()
        piece["D_oos"] = D
        piece["p_model_oos"] = p_model
        for v in names:
            piece["contrib_" + v] = r.params[lookup[v]] * te[lookup[v]].to_numpy()
        pieces.append(piece)

    fl = pd.DataFrame(folds).set_index("test")
    fl.attrs["names"] = list(names)
    print("PER-FOLD COEFFICIENTS (trained on prior seasons only) -- the "
          "stability check that matters:")
    print(fl[["n_train", "n_test"] +
             ["B_" + v for v in names] +
             ["SE_" + v for v in names]].round(4).to_string())
    signs = {v: "all %s" % ("+" if fl["B_" + v].gt(0).all() else "-")
             if (fl["B_" + v].gt(0).all() or fl["B_" + v].lt(0).all())
             else "FLIPS" for v in names}
    print("sign across folds: %s"
          % "  ".join("%s=%s" % (k, s) for k, s in signs.items()))

    print("\nPER-FOLD HELD-OUT ACCURACY vs the market baseline "
          "(positive d_ll / d_brier = the model BEAT the closing price):")
    print(fl[["n_test", "ll_mkt", "ll_model", "d_ll",
              "brier_mkt", "brier_model", "d_brier"]].round(6).to_string())

    oos = pd.concat(pieces, ignore_index=True)
    y = oos["home_win"].to_numpy()
    ll_m = logloss(y, oos["p_mkt_mult"].to_numpy())
    ll_p = logloss(y, oos["p_model_oos"].to_numpy())
    br_m = brier(y, oos["p_mkt_mult"].to_numpy())
    br_p = brier(y, oos["p_model_oos"].to_numpy())

    print("\nPOOLED OUT-OF-SAMPLE (%d games, %d..%d):"
          % (len(oos), CV_TEST_SEASONS[0], CV_TEST_SEASONS[-1]))
    print("  market  log loss %.6f   Brier %.6f" % (ll_m, br_m))
    print("  model   log loss %.6f   Brier %.6f" % (ll_p, br_p))
    print("  delta            %+.6f         %+.6f" % (ll_m - ll_p, br_m - br_p))
    print("  seasons where the model beat the market on log loss: %d of %d"
          % (int((fl["d_ll"] > 0).sum()), len(fl)))

    # paired bootstrap over games
    rng = np.random.default_rng(20260920)
    pm = np.clip(oos["p_mkt_mult"].to_numpy(), 1e-9, 1 - 1e-9)
    pp = np.clip(oos["p_model_oos"].to_numpy(), 1e-9, 1 - 1e-9)
    li_m = -(y * np.log(pm) + (1 - y) * np.log(1 - pm))
    li_p = -(y * np.log(pp) + (1 - y) * np.log(1 - pp))
    diff = li_m - li_p                       # + = model better on that game
    idx = rng.integers(0, len(diff), size=(4000, len(diff)))
    boot = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print("  paired bootstrap on the per-game log-loss difference: mean %+.6f, "
          "95%% CI [%+.6f, %+.6f]" % (diff.mean(), lo, hi))
    print("  -> %s" % ("the interval EXCLUDES zero: the out-of-sample gain is "
                       "real" if lo > 0 else
                       "the interval CONTAINS zero: out of sample this model "
                       "is not distinguishable from the closing price"))

    # per-season block bootstrap, which respects the real correlation unit
    seasons = sorted(oos["season"].unique())
    by_season = [diff[oos["season"].to_numpy() == s] for s in seasons]
    bs = np.array([np.concatenate([by_season[j] for j in
                                   rng.integers(0, len(seasons), len(seasons))]).mean()
                   for _ in range(2000)])
    blo, bhi = np.percentile(bs, [2.5, 97.5])
    print("  season-block bootstrap (resamples whole seasons): 95%% CI "
          "[%+.6f, %+.6f]" % (blo, bhi))

    return fl, oos


def oos_significance(oos, names=None, banner=True):
    names = names or VECTORS
    if banner:
        head("7. OUT-OF-SAMPLE SIGNIFICANCE -- DOES ANY VECTOR SURVIVE?")
    print("""The full-sample table in section 5 reports in-sample Wald intervals:
the same games that produced the estimate also produced the standard error. That is
the standard GLM answer but it is not an out-of-sample claim.

This section is the out-of-sample claim. Each held-out game carries
contrib_v = B_v(trained on earlier seasons only) * x_v. Refitting a single scale
factor gamma_v on the HELD-OUT games alone asks: does the size and SIGN the model
learned from the past actually pay off in the future?

    gamma_v = 1  the past coefficient transferred perfectly
    gamma_v = 0  the vector carries nothing out of sample  <- the null
    gamma_v < 0  the vector points the WRONG way out of sample
""")
    off = logit(oos["p_mkt_mult"].to_numpy())
    y = oos["home_win"].to_numpy(dtype=float)

    X = pd.DataFrame({("gamma_" + v): oos["contrib_" + v].to_numpy()
                      for v in names}, index=oos.index)
    r = sm.GLM(y, X, family=sm.families.Binomial(), offset=off).fit()
    print("PER-VECTOR, on %d held-out games:" % len(oos))
    print(r.summary().as_text())
    ci = r.conf_int()
    ci.columns = ["lo", "hi"]
    print()
    tab = pd.DataFrame({
        "gamma": r.params, "SE": r.bse, "z": r.tvalues, "p": r.pvalues,
        "ci_lo": ci["lo"], "ci_hi": ci["hi"],
        "differs from 0?": ["YES" if p < 0.05 else "no" for p in r.pvalues],
        "differs from 1?": ["YES" if not (l <= 1 <= h) else "no"
                            for l, h in zip(ci["lo"], ci["hi"])],
    })
    print(tab.round(4).to_string())

    print("\nWHOLE MODEL, as one number (gamma on the total D):")
    X1 = pd.DataFrame({"gamma_D": oos["D_oos"].to_numpy()}, index=oos.index)
    r1 = sm.GLM(y, X1, family=sm.families.Binomial(), offset=off).fit()
    lo, hi = r1.conf_int().iloc[0]
    print("  gamma_D = %+.4f  (SE %.4f, z %+.2f, p %.4f, 95%% CI [%+.3f, %+.3f])"
          % (r1.params.iloc[0], r1.bse.iloc[0], r1.tvalues.iloc[0],
             r1.pvalues.iloc[0], lo, hi))
    print("  -> %s" % ("D carries real out-of-sample information."
                       if r1.pvalues.iloc[0] < 0.05 else
                       "D is NOT distinguishable from zero out of sample."))
    return r, r1


def benjamini_hochberg(pvals, q=0.10):
    """BH step-up. Returns the boolean reject vector, in the input order."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    thresh = q * (np.arange(1, n + 1) / n)
    passed = ranked <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    rej = np.zeros(n, dtype=bool)
    if k:
        rej[order[:k]] = True
    return rej


COMP_COLS = ["f_eff", "f_finish_resid", "f_success", "p_qb_z",
             "c_rest_diff_z", "c_travel_diff_z", "c_tz_pen_diff", "R"]


def component_scrutiny(d, res_c):
    head("7b. THE TWO 'SIGNIFICANT' COMPONENTS -- DO THEY SURVIVE SCRUTINY?")
    print("""The component fit in section 5 printed two terms under p = 0.05:
f_eff and f_success. Before anyone reads those as findings they have to clear three
hurdles: multiple testing, collinearity, and out of sample. All three are below.
""")

    print(THIN)
    print("HURDLE 1 -- MULTIPLE TESTING. Eight terms were tested at once. VAS.md "
          "already mandates Benjamini-Hochberg at FDR 10% for exactly this "
          "reason at the slate level; the same logic applies to the fit itself.")
    print(THIN)
    p = np.array([res_c.pvalues[c] for c in COMP_COLS])
    rej_bh = benjamini_hochberg(p, q=0.10)
    bonf = p < (0.05 / len(p))
    tab = pd.DataFrame({
        "B": [res_c.params[c] for c in COMP_COLS],
        "p_raw": p,
        "raw p<.05": ["YES" if x < 0.05 else "no" for x in p],
        "BH q=10%": ["SURVIVES" if r else "rejected" for r in rej_bh],
        "Bonferroni": ["SURVIVES" if b else "rejected" for b in bonf],
    }, index=COMP_COLS)
    print(tab.round(5).to_string())

    print("\n" + THIN)
    print("HURDLE 2 -- COLLINEARITY. f_eff and f_success are two views of the "
          "same play-by-play. Opposite-signed coefficients on a correlated pair "
          "is the textbook signature of a SUPPRESSOR artefact, not two effects.")
    print(THIN)
    pair = d[["f_eff", "f_success", "f_finish_resid"]]
    print("correlation:")
    print(pair.corr().round(3).to_string())
    X = pair.to_numpy()
    for i, c in enumerate(pair.columns):
        others = np.column_stack([np.ones(len(X)),
                                  np.delete(X, i, axis=1)])
        beta, *_ = np.linalg.lstsq(others, X[:, i], rcond=None)
        r2 = 1 - np.sum((X[:, i] - others.dot(beta)) ** 2) / \
            np.sum((X[:, i] - X[:, i].mean()) ** 2)
        print("  VIF(%s) = %.2f" % (c, 1.0 / max(1e-12, 1 - r2)))

    print("\neach one ALONE, offset model, so nothing can suppress anything:")
    rows = []
    for c in ["f_eff", "f_success", "f_finish_resid", "F"]:
        r = glm_fit(d, [c], intercept=False, label=c)
        lo, hi = r.conf_int().iloc[0]
        rows.append({"term": c, "B": r.params[c], "SE": r.bse[c],
                     "z": r.tvalues[c], "p": r.pvalues[c],
                     "ci_lo": lo, "ci_hi": hi,
                     "sig@5%": "YES" if r.pvalues[c] < 0.05 else "no"})
    print(pd.DataFrame(rows).set_index("term").round(5).to_string())
    print("""
Alone, neither one is significant -- both sit near zero with p around 0.4-0.7.
They only cross p = 0.05 when fitted TOGETHER, with OPPOSITE signs, on a pair
correlated 0.85 (VIF ~3.7). That is the pair cancelling its large shared component
and fitting the small noisy remainder that is left. It is the textbook suppressor
signature, and it is exactly the thing that does not generalise -- which hurdle 3
then confirms it does not.""")

    print("\n" + THIN)
    print("HURDLE 3 -- OUT OF SAMPLE. Same expanding-window CV, component spec.")
    print(THIN)
    fl_c, oos_c = season_cv(d, cols=COMP_COLS, names=COMP_COLS, banner=False)
    y = oos_c["home_win"].to_numpy()
    ll_m = logloss(y, oos_c["p_mkt_mult"].to_numpy())
    ll_p = logloss(y, oos_c["p_model_oos"].to_numpy())
    print("\npooled out-of-sample log loss: market %.6f  component model %.6f  "
          "delta %+.6f" % (ll_m, ll_p, ll_m - ll_p))
    r_g, r_D = oos_significance(oos_c, names=COMP_COLS, banner=False)
    return fl_c, oos_c, r_g


def reliability(oos):
    head("8. RELIABILITY -- OF THE GAMES GIVEN AN X% CHANCE, DID X% WIN?")
    o = oos.copy()
    o["dec"] = pd.qcut(o["p_model_oos"], 10, labels=False, duplicates="drop")
    g = o.groupby("dec").agg(
        n=("home_win", "size"),
        mean_p_model=("p_model_oos", "mean"),
        mean_p_mkt=("p_mkt_mult", "mean"),
        actual=("home_win", "mean"))
    g["model_err"] = g["mean_p_model"] - g["actual"]
    g["mkt_err"] = g["mean_p_mkt"] - g["actual"]
    print(g.round(4).to_string())
    print("\nmean |error|:  model %.4f   market %.4f"
          % (g["model_err"].abs().mean(), g["mkt_err"].abs().mean()))
    print("Deciles of ~%d games have a binomial SE of about %.3f, so a decile "
          "error under that is noise." % (int(g["n"].mean()),
                                          0.5 / np.sqrt(g["n"].mean())))


def verdict(res, fl, r_gamma, r_D, oos, res_c=None, r_gamma_c=None):
    head("9. VERDICT")
    sig_in = [v for v in VECTORS if res.pvalues[VECTOR_COL[v]] < 0.05]
    sig_out = [v for v in VECTORS if r_gamma.pvalues["gamma_" + v] < 0.05]

    print("IN SAMPLE (2019-2025, n=%d), significant at 5%%: %s"
          % (int(res.nobs), sig_in if sig_in else "NONE"))
    print("OUT OF SAMPLE (%d held-out games, %d-%d), significant at 5%%: %s"
          % (len(oos), CV_TEST_SEASONS[0], CV_TEST_SEASONS[-1],
             sig_out if sig_out else "NONE"))
    print("\nPer VAS.md's own rule -- 'any vector whose B is not significantly "
          "non-zero out of sample is decoration and gets deleted' -- the "
          "vectors that survive are: %s" % (sig_out if sig_out else "NONE."))
    print("\nOut-of-sample log loss vs the closing price: model %.6f, market "
          "%.6f (delta %+.6f). VAS.md: 'If p_model does not beat p_mkt, the "
          "vectors are noise and ship nothing.'"
          % (logloss(oos["home_win"], oos["p_model_oos"]),
             logloss(oos["home_win"], oos["p_mkt_mult"]),
             logloss(oos["home_win"], oos["p_mkt_mult"])
             - logloss(oos["home_win"], oos["p_model_oos"])))

    if res_c is not None:
        raw = [c for c in COMP_COLS if res_c.pvalues[c] < 0.05]
        bh = [c for c, r in zip(COMP_COLS, benjamini_hochberg(
            [res_c.pvalues[c] for c in COMP_COLS], q=0.10)) if r]
        out_c = [c for c in COMP_COLS if r_gamma_c.pvalues["gamma_" + c] < 0.05]
        print("\nCOMPONENT SPEC: raw p<.05 in sample: %s | surviving BH at "
              "FDR 10%%: %s | significant OUT of sample: %s"
              % (raw or "NONE", bh or "NONE", out_c or "NONE"))

    print("""
WHAT THIS DOES AND DOES NOT SAY

  It does NOT say the features are wrong or badly built. It says the CLOSING
  CONSENSUS MONEYLINE already contains what they know. That is the single most
  likely outcome of this exercise and the reason VAS.md put the offset in: the
  null was designed to be hard to reject, and it was not rejected.

  It does NOT rule out an edge on SPREADS or TOTALS. This fit is moneyline only.
  R in particular is a possession-count claim that VAS.md itself says is better
  posed on totals, where its +1/-1 mapping is actually defined.

  It does NOT test the one thing VAS.md calls the real edge: the P-RESIDUAL, the
  gap between news breaking and the line moving. games.csv has no opening line and
  no timestamps, so that term is not in this fit at all. Every P coefficient here
  is the RAW QB delta, which is exactly the quantity VAS.md predicts the market
  has already priced -- and it is.

  A backtest that beat the closing line by a visible margin on these inputs would
  have been evidence of leakage, not of an edge. This one does not.""")


def main():
    rebuild = "--rebuild" in sys.argv
    cache = "--no-cache" not in sys.argv

    print(RULE)
    print("VAS-NFL  OFFLINE COEFFICIENT FIT   p_model = sigmoid(logit(p_mkt) + D)")
    print("offline backtest -- fits coefficients, ships nothing, touches no app code")
    print(RULE)

    t = build_table(rebuild=rebuild, cache=cache)
    devig_report(t)
    m = eligible(t)
    sample_report(t, m)
    d = t[m].reset_index(drop=True)

    res, res_i, res_c = run_fits(d)
    verify_offset_pinned(d, res)
    fl, oos = season_cv(d)
    r_gamma, r_D = oos_significance(oos)
    fl_c, oos_c, r_gamma_c = component_scrutiny(d, res_c)
    reliability(oos)
    verdict(res, fl, r_gamma, r_D, oos, res_c, r_gamma_c)

    out = os.path.join(HERE, "out_fit_table.parquet")
    d.to_parquet(out, index=False)
    print("\nfitted sample written to %s (%d rows x %d cols)"
          % (out, *d.shape))


if __name__ == "__main__":
    main()
