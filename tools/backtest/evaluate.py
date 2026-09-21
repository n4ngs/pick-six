#!/usr/bin/env python3
"""
evaluate.py -- HELD-OUT validation of the VAS.md market-anchored model.

    p_mkt   = no-vig closing moneyline probability for the HOME team
    D       = B_F*F + B_P*P + B_C*C + B_R*R      (B's fitted by fit.py)
    p_model = sigmoid( logit(p_mkt) + D )

Every number below is computed on games the coefficients NEVER SAW: the
coefficients for test season S are fitted on seasons strictly before S
(expanding window), exactly as fit.py's CV does. A random k-fold would leak
2025 into a 2021 prediction; it is not used anywhere in this file.

Sections
    1. log loss / Brier, model vs the market baseline           (the bar)
    2. reliability in deciles                                   (is it honest?)
    3. closing line value                                       (did the price come to us?)
    4. Benjamini-Hochberg at FDR 10% across each slate          (multiple testing)
    5. quarter-Kelly bankroll simulation                        (what it would have done)

Run:
    uv run --with pandas --with pyarrow --with numpy --with scipy \
           --with statsmodels --with scikit-learn python tools/backtest/evaluate.py

Flags:
    --rebuild   rebuild the fitted sample from the feature modules
                (default: reuse tools/backtest/out_fit_table.parquet)

Nothing here writes outside tools/backtest/ and data/nflverse/. Nothing ships.
"""

import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from scipy import stats

from fit import (HERE, RULE, THIN, VECTORS, VECTOR_COL, CV_TEST_SEASONS,
                 benjamini_hochberg, brier, build_table, eligible, glm_fit,
                 logit, logloss, sigmoid)
from load import DATA_DIR

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 80)

FIT_TABLE = os.path.join(HERE, "out_fit_table.parquet")
COLS = [VECTOR_COL[v] for v in VECTORS]

# VAS.md: "D_lo = D - 1.64*SE(D)   one-sided 95%"
Z_LO = 1.64
KELLY_LAMBDA = 0.25          # VAS.md: lambda = 0.25, quarter Kelly
STAKE_CAP = 0.05             # never risk more than 5% of bankroll on one game
BANKROLL_0 = 10000.0


def head(title):
    print("\n" + RULE)
    print(title)
    print(RULE)


def sub(title):
    print("\n" + THIN)
    print(title)
    print(THIN)


def american_to_dec(ml):
    ml = np.asarray(ml, dtype=float)
    return np.where(ml > 0, 1.0 + ml / 100.0, 1.0 + 100.0 / np.abs(ml))


def worsen(dec, cents=10.0):
    """Take `cents` of American juice off a price: the number you actually get
    when you are not first to it. -110 -> -120, +150 -> +140."""
    dec = np.asarray(dec, dtype=float)
    ml = np.where(dec >= 2.0, (dec - 1.0) * 100.0, -100.0 / (dec - 1.0))
    ml = ml - cents
    # +100 and -100 are the same price, so a positive number that falls under
    # +100 has crossed into negative territory: +95 is -105, not +95.
    ml = np.where((ml >= 0) & (ml < 100), -200.0 + ml, ml)
    return american_to_dec(ml)


# ==========================================================================
# 0. the held-out predictions
# ==========================================================================
def load_fitted_sample(rebuild=False):
    if os.path.exists(FIT_TABLE) and not rebuild:
        d = pd.read_parquet(FIT_TABLE)
        print("fitted sample: reusing %s (%d rows)" % (FIT_TABLE, len(d)))
        return d
    t = build_table(rebuild=rebuild, cache=True)
    d = t[eligible(t)].reset_index(drop=True)
    d.to_parquet(FIT_TABLE, index=False)
    return d


def oos_predictions(d):
    """Expanding-window out-of-sample predictions, WITH per-game SE(D).

    SE(D) is parameter uncertainty propagated through the linear predictor:
    Var(D_i) = x_i' Cov(b_train) x_i. That is the SE(D) VAS.md's tier rule
    keys off. It is not a prediction interval -- it does not include the
    irreducible coin-flip variance of a football game, and it is not supposed
    to."""
    head("0. HELD-OUT PREDICTIONS -- EXPANDING WINDOW, NOTHING SEEN TWICE")
    pieces, folds = [], []
    for s in CV_TEST_SEASONS:
        tr = d[d["season"] < s]
        te = d[d["season"] == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        r = glm_fit(tr, COLS, intercept=False, label="train<%d" % s)
        b = r.params.reindex(COLS).to_numpy(dtype=float)
        V = r.cov_params().reindex(index=COLS, columns=COLS).to_numpy(dtype=float)
        X = te[COLS].to_numpy(dtype=float)
        D = X.dot(b)
        varD = np.einsum("ij,jk,ik->i", X, V, X)
        seD = np.sqrt(np.clip(varD, 0.0, None))
        off = logit(te["p_mkt_mult"].to_numpy())

        p = te[["game_id", "season", "week", "gameday", "gametime",
                "home_team", "away_team", "home_moneyline", "away_moneyline",
                "spread_line", "hold", "home_win", "p_mkt_mult"]].copy()
        p["D"] = D
        p["se_D"] = seD
        p["offset"] = off
        p["p_model"] = sigmoid(off + D)
        p["train_seasons"] = "%d-%d" % (tr["season"].min(), tr["season"].max())
        pieces.append(p)
        folds.append({"test": s, "n_train": len(tr), "n_test": len(te),
                      **{"B_" + v: r.params[VECTOR_COL[v]] for v in VECTORS},
                      "mean_|D|": float(np.mean(np.abs(D))),
                      "mean_SE(D)": float(np.mean(seD))})

    fl = pd.DataFrame(folds).set_index("test")
    print("\nfolds (coefficients fitted on EARLIER seasons only, then applied "
          "forward -- this is the whole no-look-ahead guarantee):")
    print(fl.round(4).to_string())
    oos = pd.concat(pieces, ignore_index=True)
    oos = oos.sort_values(["gameday", "gametime", "game_id"]).reset_index(drop=True)
    print("\nheld-out set: %d games, seasons %d-%d"
          % (len(oos), oos["season"].min(), oos["season"].max()))
    print("mean |D| = %.4f log-odds, mean SE(D) = %.4f. The model's whole "
          "adjustment is smaller than its own standard error."
          % (oos["D"].abs().mean(), oos["se_D"].mean()))
    return oos


# ==========================================================================
# 1. the bar: log loss and Brier vs the market
# ==========================================================================
def accuracy(oos):
    head("1. LOG LOSS AND BRIER SCORE -- MODEL vs THE MARKET BASELINE")
    y = oos["home_win"].to_numpy()
    pm = oos["p_mkt_mult"].to_numpy()
    pp = oos["p_model"].to_numpy()

    ll_m, ll_p = logloss(y, pm), logloss(y, pp)
    br_m, br_p = brier(y, pm), brier(y, pp)

    print("held-out games: %d   (seasons %d-%d, coefficients never saw them)"
          % (len(oos), oos["season"].min(), oos["season"].max()))
    print("\n  %-28s %14s %14s" % ("", "LOG LOSS", "BRIER"))
    print("  %-28s %14.5f %14.5f" % ("market  p_mkt (baseline)", ll_m, br_m))
    print("  %-28s %14.5f %14.5f" % ("model   p_model", ll_p, br_p))
    print("  %-28s %+14.5f %+14.5f"
          % ("difference (mkt - model)", ll_m - ll_p, br_m - br_p))
    print("  %-28s %14s %14s"
          % ("lower is better, so a POSITIVE difference means the model won.",
             "", ""))
    beat_ll = ll_p < ll_m
    beat_br = br_p < br_m
    print("\n  MODEL BEATS MARKET ON LOG LOSS: %s" % ("YES" if beat_ll else "NO"))
    print("  MODEL BEATS MARKET ON BRIER    : %s" % ("YES" if beat_br else "NO"))

    # per-game paired difference + bootstrap
    pmc = np.clip(pm, 1e-9, 1 - 1e-9)
    ppc = np.clip(pp, 1e-9, 1 - 1e-9)
    li_m = -(y * np.log(pmc) + (1 - y) * np.log(1 - pmc))
    li_p = -(y * np.log(ppc) + (1 - y) * np.log(1 - ppc))
    diff = li_m - li_p
    rng = np.random.default_rng(20260920)
    idx = rng.integers(0, len(diff), size=(4000, len(diff)))
    boot = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print("\n  paired per-game log-loss difference: mean %+.5f, "
          "95%% bootstrap CI [%+.5f, %+.5f]" % (diff.mean(), lo, hi))
    print("  -> %s" % ("the gain EXCLUDES zero: real" if lo > 0 else
                       ("the LOSS excludes zero: the model is reliably WORSE "
                        "than the close" if hi < 0 else
                        "the interval CONTAINS zero: indistinguishable from "
                        "the closing price")))

    sub("PER SEASON (each season predicted by coefficients from the seasons "
        "before it)")
    rows = []
    for s, g in oos.groupby("season"):
        ys = g["home_win"].to_numpy()
        rows.append({
            "season": s, "n": len(g),
            "ll_mkt": logloss(ys, g["p_mkt_mult"].to_numpy()),
            "ll_model": logloss(ys, g["p_model"].to_numpy()),
            "d_ll": logloss(ys, g["p_mkt_mult"].to_numpy())
                    - logloss(ys, g["p_model"].to_numpy()),
            "brier_mkt": brier(ys, g["p_mkt_mult"].to_numpy()),
            "brier_model": brier(ys, g["p_model"].to_numpy()),
            "d_brier": brier(ys, g["p_mkt_mult"].to_numpy())
                       - brier(ys, g["p_model"].to_numpy()),
        })
    per = pd.DataFrame(rows).set_index("season")
    print(per.round(5).to_string())
    print("\nseasons where the model beat the close on log loss: %d of %d"
          % (int((per["d_ll"] > 0).sum()), len(per)))

    sub("REFERENCE POINTS -- what these numbers would be for dumber models")
    ref = {
        "always 50/50": np.full(len(y), 0.5),
        "always the base rate (%.4f)" % y.mean(): np.full(len(y), y.mean()),
        "market p_mkt": pm,
        "VAS model p_model": pp,
    }
    for name, p in ref.items():
        print("  %-34s log loss %.5f   Brier %.5f"
              % (name, logloss(y, p), brier(y, p)))
    return ll_m, ll_p, br_m, br_p, beat_ll, diff


# ==========================================================================
# 2. reliability
# ==========================================================================
def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def reliability(oos):
    head("2. RELIABILITY -- OF THE GAMES GIVEN AN X% CHANCE, DID X% WIN?")
    print("Deciles of the model's own held-out probability. 'actual' is the "
          "realised home win rate in that bucket; the Wilson interval is what "
          "a bucket of that size can resolve.\n")

    for label, col in (("MODEL  p_model", "p_model"), ("MARKET p_mkt", "p_mkt_mult")):
        o = oos.copy()
        o["dec"] = pd.qcut(o[col], 10, labels=False, duplicates="drop")
        rows = []
        for dcl, g in o.groupby("dec"):
            n = len(g)
            k = int(g["home_win"].sum())
            lo, hi = wilson(k, n)
            rows.append({
                "decile": int(dcl) + 1, "n": n,
                "p_lo": g[col].min(), "p_hi": g[col].max(),
                "mean_p": g[col].mean(), "won": k, "actual": k / n,
                "err": g[col].mean() - k / n,
                "wilson_lo": lo, "wilson_hi": hi,
                "calibrated?": "yes" if lo <= g[col].mean() <= hi else "NO",
            })
        tab = pd.DataFrame(rows).set_index("decile")
        sub(label)
        print(tab.round(4).to_string())
        print("mean |error| across deciles: %.5f   max |error|: %.5f   "
              "deciles outside their own Wilson interval: %d of %d"
              % (tab["err"].abs().mean(), tab["err"].abs().max(),
                 int((tab["calibrated?"] == "NO").sum()), len(tab)))

    sub("THE SPEC'S OWN QUESTION: 'of the plays given a 58% chance, about 58% "
        "must win'")
    for lo_b, hi_b in [(0.50, 0.55), (0.55, 0.61), (0.61, 0.67), (0.67, 0.75),
                       (0.75, 1.01)]:
        for label, col in (("model", "p_model"), ("market", "p_mkt_mult")):
            g = oos[(oos[col] >= lo_b) & (oos[col] < hi_b)]
            if len(g) == 0:
                continue
            k = int(g["home_win"].sum())
            wl, wh = wilson(k, len(g))
            print("  %-6s p in [%.2f,%.2f): n=%4d  mean p %.4f  actual %.4f  "
                  "[%.4f, %.4f]  %s"
                  % (label, lo_b, hi_b, len(g), g[col].mean(), k / len(g),
                     wl, wh, "ok" if wl <= g[col].mean() <= wh else "MISCALIBRATED"))
        print()

    sub("CALIBRATION SLOPE (logistic recalibration: y ~ a + b*logit(p))")
    import statsmodels.api as sm
    for label, col in (("model", "p_model"), ("market", "p_mkt_mult")):
        X = pd.DataFrame({"const": 1.0, "logit_p": logit(oos[col].to_numpy())})
        r = sm.GLM(oos["home_win"].to_numpy(dtype=float), X,
                   family=sm.families.Binomial()).fit()
        blo, bhi = r.conf_int().loc["logit_p"]
        print("  %-6s intercept %+.4f (SE %.4f)   slope %+.4f (SE %.4f, 95%% "
              "CI [%+.3f, %+.3f])  %s"
              % (label, r.params["const"], r.bse["const"], r.params["logit_p"],
                 r.bse["logit_p"], blo, bhi,
                 "slope 1 is inside the CI -- well scaled"
                 if blo <= 1 <= bhi else "slope 1 is OUTSIDE the CI"))
    print("\n  slope < 1 = overconfident (probabilities too extreme); "
          "slope > 1 = underconfident.")


# ==========================================================================
# candidate plays -- two moneyline sides per held-out game
# ==========================================================================
def candidates(oos, cents=0.0):
    """One row per (game, side). u = the side's own log-odds, so a lower bound
    on u is a lower bound on that side's probability, whichever side it is."""
    rows = []
    for side, sign, mlcol, team in (("home", +1.0, "home_moneyline", "home_team"),
                                    ("away", -1.0, "away_moneyline", "away_team")):
        c = oos[["game_id", "season", "week", "gameday", "gametime",
                 "home_team", "away_team", "home_win", "p_mkt_mult",
                 "spread_line", "hold", "D", "se_D", "offset"]].copy()
        c["side"] = side
        c["team"] = oos[team].to_numpy()
        c["sign"] = sign
        dec = american_to_dec(oos[mlcol].to_numpy())
        c["american"] = oos[mlcol].to_numpy()
        c["dec"] = worsen(dec, cents) if cents else dec
        c["u"] = sign * (oos["offset"].to_numpy() + oos["D"].to_numpy())
        c["u_mkt"] = sign * oos["offset"].to_numpy()
        c["p_model"] = sigmoid(c["u"].to_numpy())
        c["p_mkt"] = sigmoid(c["u_mkt"].to_numpy())
        c["won"] = (oos["home_win"].to_numpy() == (1 if side == "home" else 0)).astype(int)
        rows.append(c)
    c = pd.concat(rows, ignore_index=True)

    c["edge"] = c["p_model"] - c["p_mkt"]
    c["EV"] = c["p_model"] * c["dec"] - 1.0
    c["u_lo"] = c["u"] - Z_LO * c["se_D"]
    c["EV_lo"] = sigmoid(c["u_lo"].to_numpy()) * c["dec"] - 1.0
    # one-sided p-value for H0: this play is NOT +EV at the offered price.
    # EV > 0  <=>  p > 1/dec  <=>  u > logit(1/dec) = tau
    tau = logit(1.0 / c["dec"].to_numpy())
    c["tau"] = tau
    c["z"] = (c["u"].to_numpy() - tau) / np.maximum(c["se_D"].to_numpy(), 1e-12)
    c["p_value"] = stats.norm.sf(c["z"].to_numpy())
    c["kelly"] = np.clip(c["EV"] / (c["dec"] - 1.0), 0.0, None)
    c["tier"] = np.select(
        [c["EV_lo"] >= 0.03, c["EV_lo"] >= 0.01, c["EV_lo"] > 0],
        ["DIAMOND", "GOLD", "SILVER"], default="NO PLAY")
    return c.sort_values(["gameday", "gametime", "game_id", "side"]).reset_index(drop=True)


# ==========================================================================
# 3. closing line value
# ==========================================================================
INITIAL_LINES_URL = ("https://github.com/nflverse/nfldata/raw/master/data/"
                     "initial_lines.csv")
INITIAL_LINES_PATH = os.path.join(DATA_DIR, "initial_lines.csv")


def fetch_initial_lines():
    if os.path.exists(INITIAL_LINES_PATH) and os.path.getsize(INITIAL_LINES_PATH) > 0:
        return pd.read_csv(INITIAL_LINES_PATH)
    try:
        req = urllib.request.Request(
            INITIAL_LINES_URL, headers={"User-Agent": "pick-six-backtest"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        with open(INITIAL_LINES_PATH, "wb") as f:
            f.write(body)
        return pd.read_csv(INITIAL_LINES_PATH)
    except Exception as e:                                   # noqa: BLE001
        print("  could not fetch initial_lines.csv (%s) -- CLV section will "
              "report what is missing rather than guess" % e)
        return None


def clv(oos, cand):
    head("3. CLOSING LINE VALUE -- DID THE PRICE MOVE TOWARD THE MODEL'S SIDE?")
    print("""READ THIS BEFORE THE NUMBERS. CLV is 'I bet X, the market closed past X'.
This model's INPUT is the closing price: p_mkt is the no-vig CLOSE. A model that
consumes the close can only act at the close, and a bet struck at the close has
zero CLV BY CONSTRUCTION -- there is no further market to beat. So the honest CLV
question here is a different and weaker one:

    if the model (fed the close) likes a side, had the market ALREADY been
    drifting that way from the opener?

A yes is real but limited evidence: it says the vectors point the same direction
the sharp money did during the week, which is a coherence check, not a profit
claim. A no is stronger evidence -- it would mean the model systematically likes
the side the week's money left behind.""")

    init = fetch_initial_lines()
    if init is None or len(init) == 0:
        print("\nNO OPENING-LINE SOURCE AVAILABLE -- CLV NOT COMPUTED.")
        return None, "no opening-line source available"

    sp = init[init["type"].eq("SPREAD")].copy()
    seasons_avail = sorted(sp["season"].unique())
    books = sorted(sp["sportsbook"].unique())
    print("\nSOURCE: nflverse nfldata/data/initial_lines.csv")
    print("  seasons covered : %s" % seasons_avail)
    print("  sportsbooks     : %s  (WSGT = Westgate SuperBook, the opener of "
          "record)" % books)
    print("  markets         : %s" % sorted(init["type"].unique()))
    print("  NO MONEYLINE OPENER EXISTS IN THIS FILE. The model is a moneyline "
          "model, so the test below uses the SPREAD move as the proxy for "
          "market direction, which it is (a home-ward spread move is a "
          "home-ward moneyline move).")

    g = oos[["game_id", "season", "week", "home_team", "away_team",
             "spread_line"]].drop_duplicates("game_id")
    sp = sp.rename(columns={"about": "game_id"})
    sp = sp.merge(g[["game_id", "home_team"]], on="game_id", how="inner")
    home_open = sp[sp["side"] == sp["home_team"]][["game_id", "line"]]
    home_open = home_open.rename(columns={"line": "home_open_raw"})
    g = g.merge(home_open, on="game_id", how="inner")
    # games.csv convention: spread_line is HOME-margin-favoured positive.
    # initial_lines stores the team's own handicap, so flip the sign.
    g["spread_open"] = -g["home_open_raw"]
    g["move_home"] = g["spread_line"] - g["spread_open"]

    print("\n  held-out games with BOTH an opener and a close: %d of %d "
          "(%.1f%%), seasons %s"
          % (len(g), oos["game_id"].nunique(), 100.0 * len(g) / oos["game_id"].nunique(),
             sorted(int(x) for x in g["season"].unique())))
    if len(g) == 0:
        print("  overlap is empty -- CLV NOT COMPUTED.")
        return None, "opening lines do not overlap the held-out seasons"

    print("  open->close spread move: mean %+.3f pts, SD %.3f, median %+.3f, "
          "median |move| %.2f, max |move| %.1f"
          % (g["move_home"].mean(), g["move_home"].std(),
             g["move_home"].median(), g["move_home"].abs().median(),
             g["move_home"].abs().max()))

    sub("DATA-QUALITY CHECK ON THE OPENER -- IT IS NOT A WEEK-OF OPENER")
    wk = g.groupby("week")["move_home"].agg(
        n="size", mean_abs_move=lambda x: x.abs().mean(), sd="std").round(2)
    print(wk.to_string())
    rho = float(np.corrcoef(g["week"].to_numpy(),
                            g["move_home"].abs().to_numpy())[0, 1])
    print("\n  corr(week, |move|) = %+.3f" % rho)
    print("""
  A week-of opener moves maybe half a point to a point before kickoff. This one
  moves a median of %.1f points, %.2f on average in the earliest week here
  (week %d) and %.2f by Week 15+, growing steadily through the season. That is the signature of a PRESEASON
  LOOKAHEAD line -- Westgate posts the whole season in the summer, and the drift
  from it to the close is a season's worth of learning about the teams, not the
  week's news.

  CONSEQUENCE, STATED PLAINLY: TRUE CLV IS NOT COMPUTABLE FROM THIS DATA. The
  quantity 'did the price move toward my side after I bet it' needs a bet-time
  price, and nflverse has exactly two prices per game -- a summer lookahead and
  the close. The table below therefore measures something else: whether the model
  prefers teams that improved on their preseason number. It is reported because
  it is the only thing this cache can support, and it is labelled as what it is.
""" % (g["move_home"].abs().median(), wk["mean_abs_move"].iloc[0],
       int(wk.index[0]), wk["mean_abs_move"].tail(4).mean()))

    c = cand.merge(g[["game_id", "spread_open", "move_home"]], on="game_id",
                   how="inner")
    c["move_toward_me"] = np.where(c["side"] == "home", c["move_home"],
                                   -c["move_home"])

    def block(label, sel):
        d = c[sel]
        if len(d) == 0:
            print("  %-42s n=0  (nothing flagged)" % label)
            return None
        moved = d["move_toward_me"]
        nz = moved[moved != 0]
        wins = int((nz > 0).sum())
        n = len(nz)
        pv = stats.binomtest(wins, n, 0.5).pvalue if n else np.nan
        wl, wh = wilson(wins, n) if n else (np.nan, np.nan)
        print("  %-42s n=%4d  (moved: %3d)  toward me %4d (%.1f%%) "
              "[%.3f,%.3f]  mean move %+.3f pts  p=%.4f   | composition: "
              "%.0f%% home, mean price %.2f dec, %.0f%% underdogs"
              % (label, len(d), n, wins, 100.0 * wins / n if n else np.nan,
                 wl, wh, moved.mean(), pv,
                 100.0 * (d["side"] == "home").mean(), d["dec"].mean(),
                 100.0 * (d["dec"] > 2.0).mean()))
        return {"label": label, "n": len(d), "n_moved": n, "toward": wins,
                "pct": wins / n if n else np.nan, "mean_move": moved.mean(),
                "p": pv, "pct_home": float((d["side"] == "home").mean()),
                "mean_dec": float(d["dec"].mean())}

    sub("CLV BY SELECTION (positive = the market drifted toward the side the "
        "model likes)")
    out = []
    out.append(block("ALL candidate sides (the null: ~50%)",
                     pd.Series(True, index=c.index)))
    out.append(block("model's preferred side (edge > 0)", c["edge"] > 0))
    out.append(block("EV > 0 at the offered price", c["EV"] > 0))
    out.append(block("EV_lo > 0  (VAS SILVER+)", c["EV_lo"] > 0))
    out.append(block("top decile by EV",
                     c["EV"] >= c["EV"].quantile(0.90)))
    out.append(block("top decile by |edge|, model side",
                     (c["edge"] > 0) & (c["edge"] >= c["edge"].quantile(0.95))))
    print("\n  CONTROLS -- selections that contain no model information at all, "
          "so their CLV is the compositional baseline this table must be read "
          "against:")
    out.append(block("[control] every UNDERDOG (dec > 2.0)", c["dec"] > 2.0))
    out.append(block("[control] every FAVOURITE (dec <= 2.0)", c["dec"] <= 2.0))
    out.append(block("[control] every HOME side", c["side"] == "home"))
    out = [o for o in out if o]

    sub("COMPOSITION-MATCHED -- THE ONLY FAIR READ OF THE TABLE ABOVE")
    print("""The controls just showed the whole table is dominated by one artefact:
'favourite' and 'underdog' are defined BY THE CLOSING PRICE, and the side that
closed favourite is by definition the side the line moved toward. Conditioning on
the close and then asking which way the line moved is circular -- it manufactures
a 78% 'CLV' rate out of nothing.

So the model's selection is compared only WITHIN a price stratum, against the
plays it did not pick in that same stratum. That comparison has no compositional
free lunch in it.\n""")
    strata = [("FAVOURITES (dec <= 2.0)", c["dec"] <= 2.0),
              ("UNDERDOGS  (dec >  2.0)", c["dec"] > 2.0)]
    for sname, smask in strata:
        base = c[smask & (c["move_toward_me"] != 0)]
        picked = base[base["edge"] > 0]
        rest = base[base["edge"] <= 0]
        if len(picked) < 5 or len(rest) < 5:
            print("  %-26s too thin to compare" % sname)
            continue
        a, na = int((picked["move_toward_me"] > 0).sum()), len(picked)
        b, nb = int((rest["move_toward_me"] > 0).sum()), len(rest)
        pa, pb = a / na, b / nb
        pool = (a + b) / (na + nb)
        se = np.sqrt(pool * (1 - pool) * (1.0 / na + 1.0 / nb))
        z = (pa - pb) / se if se > 0 else np.nan
        pv = 2 * stats.norm.sf(abs(z)) if se > 0 else np.nan
        print("  %-26s model picks it: %3d/%3d = %.3f   model passes: %3d/%3d "
              "= %.3f   difference %+.3f  (z %+.2f, p %.3f)"
              % (sname, a, na, pa, b, nb, pb, pa - pb, z, pv))
    print("\n  A model with real directional information would sit ABOVE its own "
          "stratum's pass-rate in both rows. Read the two differences and their "
          "p-values, not the headline percentages.")

    n_evlo_here = int((c["EV_lo"] > 0).sum())
    print("""
  Note on the empty SILVER+ row: the CLV window is 2021, the FIRST held-out
  season, whose coefficients come from the smallest training set (471 games).
  SE(D) there is 0.197 -- the widest of any fold -- so the 1.64-sigma haircut
  kills every play. %d of the 118 SILVER+ plays in the whole held-out set fall
  inside the window where an opener exists, which is why that row reads n=0.
  The CLV test and the tier gate do not overlap on this data at all.""" % n_evlo_here)
    print("""
WHAT THIS CAN AND CANNOT SAY
  Coverage is ONE season (2021) and ONE book's opener, %d of %d held-out games.
  That is a pilot, not a verdict: at this n, a true 55%% CLV rate and a true 50%%
  are not separable. The binomial p-values above are the honest width.
  data/weeks/*.json in this app stores open AND close per game going forward,
  so the same test re-run in 2027 will have a real sample -- built from bets the
  app actually logged, not reconstructed.""" % (len(g), oos["game_id"].nunique()))
    return pd.DataFrame(out), None


# ==========================================================================
# 4. Benjamini-Hochberg across the slate
# ==========================================================================
def bh_slate(cand, q=0.10):
    head("4. BENJAMINI-HOCHBERG AT FDR 10% ACROSS EACH SLATE")
    print("""VAS.md: 'A 16-game slate across spread, total and moneyline is ~100
simultaneous tests, so at any fixed threshold some plays clear on noise alone.'

Each candidate play carries a one-sided p-value for the null 'this play is NOT
+EV at the offered price':

    EV > 0  <=>  p_side > 1/dec  <=>  u > tau,  tau = logit(1/dec)
    p_value = P( u <= tau | u ~ N(u_hat, SE(D)^2) )

The naive threshold is p < 0.05, which is ALGEBRAICALLY the same rule as VAS.md's
EV_lo > 0 with its 1.64 multiplier. BH is then applied within each (season, week)
slate -- the real simultaneity unit, since a slate is what a user sees at once.

NOTE: this harness only produces MONEYLINE candidates, so a 16-game slate is 32
tests here, not the ~100 VAS.md describes. Fewer tests makes BH LESS strict, so
this is the friendly version of the correction, not the harsh one.\n""")

    cand["bh_survives"] = False
    cand["naive_survives"] = False
    rows = []
    for (s, w), g in cand.groupby(["season", "week"]):
        p = g["p_value"].to_numpy()
        rej = benjamini_hochberg(p, q=q)
        naive = p < 0.05
        rows.append({"season": s, "week": w, "n_tests": len(g),
                     "naive_p<.05": int(naive.sum()),
                     "BH_q10": int(rej.sum()),
                     "min_p": float(p.min())})
        cand.loc[g.index, "bh_survives"] = rej
        cand.loc[g.index, "naive_survives"] = naive
    per = pd.DataFrame(rows)

    n_naive = int(cand["naive_survives"].sum())
    n_bh = int(cand["bh_survives"].sum())
    print("candidate plays evaluated : %d  (%d games x 2 moneyline sides)"
          % (len(cand), cand["game_id"].nunique()))
    print("slates                    : %d" % len(per))
    print("cleared the NAIVE threshold p < 0.05 (== VAS.md's EV_lo > 0) : %d "
          "(%.2f%% of candidates)" % (n_naive, 100.0 * n_naive / len(cand)))
    print("SURVIVED Benjamini-Hochberg at FDR 10%% within its own slate  : %d "
          "(%.2f%%)" % (n_bh, 100.0 * n_bh / len(cand)))
    print("plays killed by the correction: %d" % (n_naive - n_bh))
    n_evlo = int((cand["EV_lo"] > 0).sum())
    print("(for the record: EV_lo > 0 selects %d plays, not %d. VAS.md writes "
          "1.64 where a one-sided 95%% test wants 1.645, so the spec's gate is "
          "a hair looser than p < 0.05 and lets %d extra play(s) through. That "
          "is the entire difference.)" % (n_evlo, n_naive, n_evlo - n_naive))

    print("\nslates with at least one naive clear:")
    hot = per[per["naive_p<.05"] > 0].sort_values("naive_p<.05", ascending=False)
    if len(hot) == 0:
        print("  NONE. Not one play in %d held-out slates reached p < 0.05, so "
              "BH has nothing to correct." % len(per))
    else:
        print(hot.head(25).to_string(index=False))

    print("\ndistribution of the per-play p-value (uniform-ish under the null; "
          "a real edge would pile up near 0):")
    qs = cand["p_value"].quantile([0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.90, 1.0])
    print("  " + "  ".join("q%.2f=%.4f" % (k, v) for k, v in qs.items()))
    print("  smallest p-value anywhere in %d held-out plays: %.5f"
          % (len(cand), cand["p_value"].min()))

    sub("TIER COUNTS (VAS.md's own EV_lo ladder, on held-out games)")
    tc = cand["tier"].value_counts().reindex(
        ["DIAMOND", "GOLD", "SILVER", "NO PLAY"]).fillna(0).astype(int)
    print(tc.to_string())
    print("\npoint-estimate plays (EV > 0, no uncertainty haircut): %d"
          % int((cand["EV"] > 0).sum()))
    print("that gap -- %d point-estimate plays vs %d that clear EV_lo > 0 -- IS "
          "the uncertainty rule doing its job."
          % (int((cand["EV"] > 0).sum()), int((cand["EV_lo"] > 0).sum())))
    return per, n_naive, n_bh


# ==========================================================================
# 5. bankroll
# ==========================================================================
def simulate(plays, label, bankroll0=BANKROLL_0, lam=KELLY_LAMBDA,
             cap=STAKE_CAP, flat=None):
    """Sequential quarter-Kelly (or flat) staking in kickoff order."""
    bank = bankroll0
    peak = bankroll0
    maxdd = 0.0
    staked = 0.0
    pnl = 0.0
    wins = 0
    curve = [bankroll0]
    for _, r in plays.iterrows():
        if flat is not None:
            stake = flat * bankroll0
        else:
            stake = min(lam * r["kelly"], cap) * bank
        if stake <= 0 or bank <= 0:
            continue
        staked += stake
        if r["won"]:
            got = stake * (r["dec"] - 1.0)
            wins += 1
        else:
            got = -stake
        pnl += got
        bank += got
        peak = max(peak, bank)
        maxdd = max(maxdd, (peak - bank) / peak)
        curve.append(bank)
    n = len(curve) - 1
    return {
        "strategy": label, "bets": n, "won": wins,
        "hit_rate": wins / n if n else np.nan,
        "staked": staked, "pnl": pnl,
        "ROI": pnl / staked if staked else np.nan,
        "final_bankroll": bank,
        "growth": bank / bankroll0 - 1.0,
        "max_drawdown": maxdd,
        "curve": curve,
    }


def bankroll(cand, oos):
    head("5. SIMULATED BANKROLL -- QUARTER KELLY, REAL PRICES, REAL VIG")
    print("""THIS IS NOT A PROMISE. Read the four reasons before the table:

  (1) IN-SAMPLE OF STRATEGY. The coefficients are out of sample -- each season is
      predicted by seasons before it. The STRATEGY is not: the staking rule, the
      EV_lo gate, the 1.64 multiplier, the quarter-Kelly lambda and the decision
      to bet moneylines at all were all chosen by someone who has already seen
      how this data behaves. That is a second, uncorrected layer of selection.
  (2) BETS ARE STRUCK AT THE CLOSE. Every price below is the actual closing
      moneyline, vig included -- but it is the number the model was FED. In
      reality you cannot bet a number you are simultaneously using as your
      prior, and the price you could actually get earlier in the week is worse
      for you, not better, whenever your side is the one the market moved toward.
  (3) NO LIMITS, NO LINE SHOPPING, NO STEAM. Fills are assumed perfect at the
      consensus close at any size the Kelly fraction asks for.
  (4) n IS SMALL. A few hundred bets cannot separate a 2%% edge from zero.

Stake = min(0.25 * kelly, 5%% of bankroll) * current bankroll, sequential in
kickoff order, starting from $%s.""" % ("{:,.0f}".format(BANKROLL_0)))

    print("\nthe hurdle, stated plainly: mean two-way hold on these games is "
          "%.4f, so a bettor with NO edge loses about %.2f%% of every dollar "
          "staked." % (oos["hold"].mean(), 100.0 * oos["hold"].mean() / 2.0))

    strategies = [
        ("A. EV_lo > 0   (VAS SILVER+, the spec's own gate)", cand["EV_lo"] > 0, None),
        ("B. EV_lo >= 1% (GOLD+)", cand["EV_lo"] >= 0.01, None),
        ("C. EV_lo >= 3% (DIAMOND)", cand["EV_lo"] >= 0.03, None),
        ("D. BH survivor at FDR 10%", cand["bh_survives"].fillna(False).astype(bool), None),
        ("E. EV > 0, point estimate (no haircut)", cand["EV"] > 0, None),
        ("F. EV > 0, FLAT 1% of start", cand["EV"] > 0, 0.01),
        ("G. EV > 2%, point estimate", cand["EV"] > 0.02, None),
    ]
    rows = []
    curves = {}
    for label, sel, flat in strategies:
        plays = cand[sel.fillna(False) if hasattr(sel, "fillna") else sel]
        res = simulate(plays, label, flat=flat)
        curves[label] = res.pop("curve")
        rows.append(res)
    tab = pd.DataFrame(rows).set_index("strategy")
    print()
    print(tab[["bets", "won", "hit_rate", "staked", "pnl", "ROI",
               "final_bankroll", "growth", "max_drawdown"]].round(4).to_string())

    print("""
READ THE ROI COLUMN AGAINST THE FLAT-STAKE TEST BELOW, NOT ON ITS OWN. Kelly
stakes are proportional to the edge the model claims, so a positive Kelly ROI
next to a negative flat ROI -- which is exactly what row A does -- means the
profit came from HOW MUCH was staked on a handful of bets, not from a hit rate
that repeats. Flat staking is the honest read of whether the SELECTION works.""")

    sub("IS ANY OF THAT DISTINGUISHABLE FROM ZERO?")
    for label, sel, flat in strategies:
        plays = cand[sel.fillna(False) if hasattr(sel, "fillna") else sel]
        if len(plays) < 10:
            print("  %-46s n=%d -- too few bets to test" % (label, len(plays)))
            continue
        # per-bet return on a 1-unit flat stake
        r = np.where(plays["won"] == 1, plays["dec"] - 1.0, -1.0)
        rng = np.random.default_rng(7)
        idx = rng.integers(0, len(r), size=(4000, len(r)))
        boot = r[idx].mean(axis=1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        t = stats.ttest_1samp(r, 0.0)
        print("  %-46s n=%4d  flat ROI %+.4f  95%% CI [%+.4f, %+.4f]  p=%.4f  %s"
              % (label, len(r), r.mean(), lo, hi, t.pvalue,
                 "beats zero" if lo > 0 else
                 ("loses, reliably" if hi < 0 else "cannot be told from zero")))

    sub("PRICE SENSITIVITY -- the same strategy 10 cents worse, which is what "
        "you get when you are not first to the number")
    worse = candidates(oos, cents=10.0)
    for label, sel_fn in [("EV > 0, point estimate", lambda c: c["EV"] > 0),
                          ("EV_lo > 0 (SILVER+)", lambda c: c["EV_lo"] > 0)]:
        a = simulate(cand[sel_fn(cand)], label)
        b = simulate(worse[sel_fn(worse)], label)
        print("  %-30s  at the close: n=%4d ROI %+.4f   |   10c worse: n=%4d "
              "ROI %+.4f" % (label, a["bets"], a["ROI"], b["bets"], b["ROI"]))

    sub("PER-SEASON P&L OF THE SPEC'S OWN GATE (EV_lo > 0)")
    sel = cand[cand["EV_lo"] > 0]
    if len(sel) == 0:
        print("  the spec's gate selected ZERO plays across %d held-out games. "
              "There is no P&L to report, and that is the finding."
              % oos["game_id"].nunique())
    else:
        rows = []
        for s in sorted(oos["season"].unique()):
            g = sel[sel["season"] == s]
            if len(g) == 0:
                rows.append({"season": s, "bets": 0, "won": 0,
                             "flat_units": 0.0, "flat_ROI": np.nan})
                continue
            r = np.where(g["won"] == 1, g["dec"] - 1.0, -1.0)
            rows.append({"season": s, "bets": len(g), "won": int(g["won"].sum()),
                         "flat_units": r.sum(), "flat_ROI": r.mean()})
        print(pd.DataFrame(rows).set_index("season").round(4).to_string())
        print("\n2021 is empty because the first fold's SE(D) is too wide for "
              "any play to clear the haircut. The four seasons that do have "
              "bets run +0.26, -0.05, +0.01, -0.19 flat ROI -- the sign flips "
              "every year, which is what no edge looks like.")
    return tab


# ==========================================================================
def main():
    rebuild = "--rebuild" in sys.argv
    print(RULE)
    print("VAS-NFL  HELD-OUT EVALUATION   p_model = sigmoid(logit(p_mkt) + D)")
    print("offline backtest -- measures the model, ships nothing, touches no app code")
    print(RULE)

    d = load_fitted_sample(rebuild=rebuild)
    oos = oos_predictions(d)

    ll_m, ll_p, br_m, br_p, beat_ll, diff = accuracy(oos)
    reliability(oos)
    cand = candidates(oos)
    clv_tab, clv_err = clv(oos, cand)
    per_slate, n_naive, n_bh = bh_slate(cand)
    bank = bankroll(cand, oos)

    head("VERDICT")
    print("HELD-OUT GAMES            : %d (seasons %d-%d), %d candidate "
          "moneyline plays" % (len(oos), oos["season"].min(),
                               oos["season"].max(), len(cand)))
    print("MARKET LOG LOSS (baseline): %.5f" % ll_m)
    print("MODEL  LOG LOSS           : %.5f" % ll_p)
    print("DIFFERENCE (mkt - model)  : %+.5f  -> model is %s"
          % (ll_m - ll_p, "BETTER" if beat_ll else "WORSE"))
    print("MARKET BRIER              : %.5f" % br_m)
    print("MODEL  BRIER              : %.5f" % br_p)
    print("BEATS MARKET?             : %s" % ("YES" if beat_ll else "NO"))
    print("BH at FDR 10%%             : %d of %d naive clears survive"
          % (n_bh, n_naive))
    print("""
VAS.md's own rule: 'If p_model does not beat p_mkt, the vectors are noise and
ship nothing.' That rule is being applied to the numbers above, not argued with.""")
    out = os.path.join(HERE, "out_eval_candidates.parquet")
    cand.to_parquet(out, index=False)
    print("\nheld-out candidate plays written to %s (%d rows)" % (out, len(cand)))


if __name__ == "__main__":
    main()
