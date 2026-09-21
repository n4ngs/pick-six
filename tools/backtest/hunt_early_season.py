#!/usr/bin/env python3
"""
hunt_early_season.py -- id "early-season"

===========================================================================
PRE-REGISTRATION.  Written in full BEFORE any number below was computed.
Run ONCE, exactly as specified. Every test listed here is reported, pass or
fail. Any test run beyond this list is reported as an EXTRA and labelled.
===========================================================================

HYPOTHESIS
  H_market: the closing NFL moneyline is measurably WORSE CALIBRATED in
            early-season weeks (1-4) than in later weeks (5+), because
            everyone -- market and modeller alike -- has little current-season
            data.
  H_model:  the four VAS vectors (F, P, C, R) carry MORE out-of-sample signal
            in early weeks than in later weeks.

  These two are in tension by construction, and that tension is the point.
  Early weeks are exactly when team features are least reliable (F is a
  current-season aggregate; in Week 2 it rests on one game). So H_market can
  be true while H_model is false: the line can be sloppier without these
  particular features being the thing that exploits it. The report must say
  which effect dominates, and must not confuse the two.

  H0 for everything below: no week-bucket difference. Calibration is the same
  early and late; the vectors carry the same (namely zero) out-of-sample
  signal early and late.

--------------------------------------------------------------------------
PART A -- MARKET CALIBRATION BY WEEK BUCKET
--------------------------------------------------------------------------
RESPONSE VARIABLE
  home_win = 1[result > 0].  Ties are moneyline PUSHES and are excluded.

PREDICTOR
  p_mkt = multiplicative (proportional) de-vig of the closing two-way
          moneyline, home side.  Identical construction to fit.py.
  L     = logit(p_mkt).

SAMPLE FILTER  (fixed before running; not a tuning knob)
  * seasons 2006-2025 inclusive.
      - 2006 is the first season games.csv carries a moneyline at all, so
        p_mkt does not exist before it. Same bound fit_full.py established.
      - 2025 is the last COMPLETE season. 2026 is in progress with only
        early weeks played; including it would load the EARLY bucket with a
        single season's noise and nothing into LATE. Excluded for that
        structural reason, decided before looking at any 2026 outcome.
  * game_type == 'REG' only. The early/late contrast is a claim about the
    regular season. Postseason (weeks 19-22) would otherwise land entirely
    in the LATE bucket and contaminate it with a structurally different,
    far more heavily bet market.
  * a played result, both moneylines present, hold > 0, not a tie.

BUCKET
  EARLY = 1[week <= 4].  LATE = 1[week >= 5].
  The 1-4 cutoff is taken from the hypothesis as stated, before any fit.
  It is NOT selected from the data. No other cutoff is tested. If a
  different cutoff were tried it would be reported as an EXTRA test.

TESTS
  T1 (PRIMARY).  Calibration-interaction logistic regression on the pooled
      sample:
          logit P(home win) = a0 + a1*EARLY + (b0 + b1*EARLY) * L
      Joint 2-df Wald test of H0: a1 = 0 AND b1 = 0.
      "Is the closing line's calibration measurably different in weeks 1-4?"
      This is the pre-registered primary test of H_market.

  T2.  Early bucket alone: logit P = a + b*L. Joint 2-df Wald test of
      H0: a = 0 AND b = 1 (perfect calibration).

  T3.  Late bucket alone, same 2-df test of H0: a = 0 AND b = 1.

  T4.  EXCESS LOG LOSS by bucket. For each game,
          xll = -[y*log p + (1-y)*log(1-p)]  -  H(p),
          H(p) = -[p*log p + (1-p)*log(1-p)]
      H(p) is the log loss a PERFECTLY calibrated forecaster with that same
      p would expect, so E[xll] = 0 under perfect calibration and the
      statistic is free of the mechanical dependence on how spread out the
      week's prices happen to be. Raw log loss is NOT comparable across week
      buckets (early lines sit closer to pick'em, which raises log loss even
      for a perfect book); excess log loss is. Statistic: mean(xll | EARLY)
      - mean(xll | LATE). 95% CI and p by SEASON-BLOCK bootstrap (2000
      resamples of whole seasons), because games within a season are the
      correlated unit.

--------------------------------------------------------------------------
PART B -- DO THE MODEL'S FEATURES CARRY MORE SIGNAL EARLY?
--------------------------------------------------------------------------
MODEL (unchanged from fit.py / fit_full.py -- nothing added or reweighted)
      home_win ~ Binomial, logit link
      linear predictor = logit(p_mkt) + B_F*F + B_P*p_qb_z + B_C*C + B_R*R
      logit(p_mkt) is a FIXED OFFSET pinned to 1, never estimated.

SAMPLE
      the cached out_full_fit_table.parquet (2006-2025, n=4886), REG only,
      i.e. fit_full.py's eligible() sample. NOTE AND LIMITATION, stated
      before running: that sample has NO Week 1 at all, because Vector F is
      not ready in Week 1 (no prior game exists that season). So the EARLY
      bucket in Part B is weeks 2-4, not 1-4. Week 1 -- the single week where
      H_market is most likely to be true -- is untestable with these features
      by construction. This is reported as a limitation, not patched.

CROSS-VALIDATION
      Expanding window, SEASON-WISE ONLY. Train on seasons strictly earlier
      than the test season; test on the test season; first test season 2008.
      Never random k-fold. Identical to fit.py's season_cv.
      D_oos = B(trained on earlier seasons only) . x  on each held-out game.

TESTS
  T5 (PRIMARY for H_model).  On the held-out games only:
          logit P = offset(L) + gE * D_oos * EARLY + gL * D_oos * LATE
      1-df Wald test of H0: gE - gL = 0.
      "Does the model's signal transfer BETTER in early weeks?"

  T6.  gE vs 0 (does D carry anything out of sample in weeks 2-4 at all).
  T7.  gL vs 0 (same, weeks 5+).

--------------------------------------------------------------------------
THRESHOLD
      Two-sided alpha = 0.05 per test, AND Benjamini-Hochberg at FDR 10%
      across all seven pre-registered tests (VAS.md's own multiplicity rule).
      A claim of an early-season edge requires BOTH:
        (i)  T1 significant (the line really is differently calibrated), AND
        (ii) T5 or T6 significant (something we can actually compute
             exploits it).
      T1 alone is a fact about the market, not an edge -- it says the price
      is sloppy without saying we can tell which way.

POWER
      Reported for every test as the minimum detectable effect at 80% power,
      two-sided 5%:  MDE = (z_.975 + z_.80) * SE = 2.8016 * SE, and for the
      2-df tests as the non-centrality needed (ncp = 9.634 at 80% power,
      2 df, alpha .05). Converted to win-probability points where that is
      meaningful. An insignificant result on an underpowered test means
      UNKNOWN, not NO.

WHAT WOULD FALSIFY H_market
      T1 insignificant with an MDE small enough to exclude a distortion of
      roughly 2 percentage points of win probability -- about the size a
      bettor needs to clear a typical ~3% two-way moneyline hold.

NO TUNING TO SIGNIFICANCE. The season bounds, the week cutoff, the bucket
definition, the sample filters and the estimator are all fixed above and are
not revisited after seeing a result. If any result below required a change
to any of them it would be reported as such and NOT counted as an edge.
===========================================================================
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from load import load_games
from fit import american_to_prob, logit, sigmoid, logloss, benjamini_hochberg

HERE = os.path.dirname(os.path.abspath(__file__))
warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("display.width", 180)
pd.set_option("display.max_columns", 60)

RULE = "=" * 100
THIN = "-" * 100

Z80 = 2.8015519  # z_.975 + z_.80, the two-sided 80%-power multiplier
NCP80_2DF = 9.6341  # non-centrality for 80% power, chi2 2 df, alpha .05

SEASON_LO, SEASON_HI = 2006, 2025
EARLY_MAX_WEEK = 4

TESTS = []  # (id, description, p-value) -- every pre-registered test lands here


def head(t):
    print("\n" + RULE)
    print(t)
    print(RULE)


def record(tid, desc, p):
    TESTS.append((tid, desc, float(p)))
    return p


# ==========================================================================
# PART A -- market calibration
# ==========================================================================
def build_market_sample():
    head("PART A.0  SAMPLE CONSTRUCTION (market calibration)")
    g = load_games(seasons=(SEASON_LO, SEASON_HI), require_lines=False,
                   played_only=True, season_type="REG")
    print("REG games %d-%d with a played result            : %6d"
          % (SEASON_LO, SEASON_HI, len(g)))

    g = g.dropna(subset=["home_moneyline", "away_moneyline"]).copy()
    print("  ... with both closing moneylines present      : %6d" % len(g))

    qh = american_to_prob(g["home_moneyline"])
    qa = american_to_prob(g["away_moneyline"])
    g["overround"] = qh + qa
    g["hold"] = g["overround"] - 1.0
    g = g[g["hold"] > 0].copy()
    print("  ... with hold > 0 (no-vig price defined)      : %6d" % len(g))

    g["p_mkt"] = american_to_prob(g["home_moneyline"]) / g["overround"]
    g = g[g["result"] != 0].copy()
    print("  ... non-ties (a ML tie is a PUSH)             : %6d" % len(g))

    g["home_win"] = (g["result"] > 0).astype(int)
    g["L"] = logit(g["p_mkt"].to_numpy())
    g["EARLY"] = (g["week"] <= EARLY_MAX_WEEK).astype(int)

    print("\nFINAL PART-A SAMPLE: %d games, seasons %d-%d, weeks %d-%d"
          % (len(g), g["season"].min(), g["season"].max(),
             g["week"].min(), g["week"].max()))
    print("  EARLY (weeks 1-%d): %d games   LATE (weeks %d+): %d games"
          % (EARLY_MAX_WEEK, int(g["EARLY"].sum()), EARLY_MAX_WEEK + 1,
             int((1 - g["EARLY"]).sum())))
    print("  per-season EARLY count: min %d  max %d"
          % (g[g.EARLY == 1].groupby("season").size().min(),
             g[g.EARLY == 1].groupby("season").size().max()))
    return g


def descriptives(g):
    head("PART A.1  DESCRIPTIVES (no test is performed on this block)")
    g = g.copy()
    p = g["p_mkt"].to_numpy()
    y = g["home_win"].to_numpy()
    g["H"] = -(p * np.log(p) + (1 - p) * np.log(1 - p))
    g["ll"] = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    g["xll"] = g["ll"] - g["H"]
    g["conf"] = np.abs(p - 0.5)

    by = g.groupby("EARLY").agg(
        n=("home_win", "size"),
        mean_p_mkt=("p_mkt", "mean"),
        home_win_rate=("home_win", "mean"),
        mean_abs_p_minus_half=("conf", "mean"),
        raw_logloss=("ll", "mean"),
        entropy_of_p=("H", "mean"),
        excess_logloss=("xll", "mean"),
        brier=("home_win", "size"))
    br = g.groupby("EARLY").apply(
        lambda d: float(np.mean((d["p_mkt"] - d["home_win"]) ** 2)))
    by["brier"] = br
    by.index = ["LATE (w%d+)" % (EARLY_MAX_WEEK + 1), "EARLY (w1-%d)" % EARLY_MAX_WEEK]
    print(by.round(5).to_string())
    print("""
Read the two log-loss columns together. Raw log loss IS higher early -- but the
entropy column shows why: early lines sit closer to pick'em (mean |p-0.5| is
smaller), and a perfectly calibrated book facing more uncertain games has a
higher log loss by arithmetic alone. The excess column is the one that carries
information, and it is what T4 tests.""")

    print("\nPER-WEEK, DESCRIPTIVE ONLY -- no test is run on this table and no "
          "cutoff is chosen from it (the 1-4 cutoff was fixed in the "
          "pre-registration above):")
    pw = g.groupby("week").agg(
        n=("home_win", "size"),
        mean_p=("p_mkt", "mean"),
        win_rate=("home_win", "mean"),
        raw_ll=("ll", "mean"),
        excess_ll=("xll", "mean"))
    pw["se_excess"] = g.groupby("week")["xll"].sem()
    print(pw.round(4).to_string())
    return g


def wald_joint(res, R, q, label):
    """Joint Wald test of R*beta = q. Returns (stat, df, p)."""
    R = np.asarray(R, dtype=float)
    q = np.asarray(q, dtype=float)
    b = res.params.to_numpy(dtype=float)
    V = res.cov_params().to_numpy(dtype=float)
    d = R.dot(b) - q
    M = R.dot(V).dot(R.T)
    stat = float(d.dot(np.linalg.solve(M, d)))
    df = R.shape[0]
    p = float(stats.chi2.sf(stat, df))
    return stat, df, p


def part_a_tests(g):
    head("PART A.2  T1 (PRIMARY) -- IS THE CLOSING LINE CALIBRATED DIFFERENTLY "
         "IN WEEKS 1-4?")
    X = pd.DataFrame({
        "const": 1.0,
        "EARLY": g["EARLY"].to_numpy(dtype=float),
        "L": g["L"].to_numpy(dtype=float),
        "EARLY_x_L": (g["EARLY"] * g["L"]).to_numpy(dtype=float),
    }, index=g.index)
    y = g["home_win"].to_numpy(dtype=float)
    res = sm.GLM(y, X, family=sm.families.Binomial()).fit()
    print("    logit P(home win) = a0 + a1*EARLY + (b0 + b1*EARLY) * logit(p_mkt)")
    print("    a0 = const,  a1 = EARLY,  b0 = L,  b1 = EARLY_x_L\n")
    print(res.summary().as_text())

    ci = res.conf_int()
    ci.columns = ["lo", "hi"]
    tab = pd.DataFrame({
        "estimate": res.params, "SE": res.bse, "z": res.tvalues,
        "p": res.pvalues, "ci_lo": ci["lo"], "ci_hi": ci["hi"],
        "null value": [0.0, 0.0, 1.0, 0.0],
        "MDE@80% power": Z80 * res.bse,
    })
    print()
    print(tab.round(5).to_string())

    R = [[0, 1, 0, 0], [0, 0, 0, 1]]
    stat, df, p = wald_joint(res, R, [0, 0], "T1")
    record("T1", "joint (a1,b1)=0 : early-vs-late calibration differs", p)
    print("\nT1  JOINT WALD, H0: a1 = 0 and b1 = 0   (2 df)")
    print("    chi2 = %.4f,  df = %d,  p = %.4f  -> %s"
          % (stat, df, p,
             "REJECT: calibration differs by week bucket" if p < 0.05 else
             "FAIL TO REJECT: no detectable calibration difference"))
    print("    non-centrality needed for 80%% power at 2 df, alpha .05: %.3f; "
          "observed chi2 (a biased ncp estimate): %.3f" % (NCP80_2DF, stat))

    # --- interpretable size of what T1 could have detected ---------------
    print("\n    WHAT T1 COULD HAVE SEEN. Translating the MDEs into win-"
          "probability points of mispricing on an early-week game:")
    a1_mde = Z80 * res.bse["EARLY"]
    b1_mde = Z80 * res.bse["EARLY_x_L"]
    b0 = res.params["L"]
    a0 = res.params["const"]
    for Lv, tag in ((0.0, "p_mkt = 0.50 (pick'em)"),
                    (1.0986, "p_mkt = 0.75 (-300 fav)"),
                    (-1.0986, "p_mkt = 0.25 (+300 dog)")):
        base = sigmoid(a0 + b0 * Lv)
        shifted = sigmoid(a0 + a1_mde + (b0 + b1_mde) * Lv)
        print("      %-26s  base %.4f -> %.4f   distortion %+.2f pp"
              % (tag, base, shifted, 100 * (shifted - base)))
    print("    (a bettor needs roughly 1.5-2.5 pp to clear a ~3%% two-way "
          "moneyline hold, so an MDE in that range means the test is "
          "adequately powered for a tradeable effect)")

    # --- T2 / T3: each bucket against PERFECT calibration -----------------
    head("PART A.3  T2 / T3 -- IS EACH BUCKET CALIBRATED AT ALL? (H0: a=0, b=1)")
    out = {}
    for tid, tag, mask in (("T2", "EARLY (weeks 1-%d)" % EARLY_MAX_WEEK,
                            g["EARLY"] == 1),
                           ("T3", "LATE (weeks %d+)" % (EARLY_MAX_WEEK + 1),
                            g["EARLY"] == 0)):
        d = g[mask]
        Xb = pd.DataFrame({"const": 1.0, "L": d["L"].to_numpy(dtype=float)},
                          index=d.index)
        rb = sm.GLM(d["home_win"].to_numpy(dtype=float), Xb,
                    family=sm.families.Binomial()).fit()
        stat, df, p = wald_joint(rb, [[1, 0], [0, 1]], [0, 1], tid)
        record(tid, "%s calibrated: a=0 and b=1" % tag, p)
        cib = rb.conf_int()
        cib.columns = ["lo", "hi"]
        print("\n%s  %s   n = %d" % (tid, tag, len(d)))
        print("    a (intercept) = %+.4f  (SE %.4f, 95%% CI [%+.3f, %+.3f])  "
              "null 0   MDE@80%% = %.3f"
              % (rb.params["const"], rb.bse["const"], cib.loc["const", "lo"],
                 cib.loc["const", "hi"], Z80 * rb.bse["const"]))
        print("    b (slope)     = %+.4f  (SE %.4f, 95%% CI [%+.3f, %+.3f])  "
              "null 1   MDE@80%% = %.3f"
              % (rb.params["L"], rb.bse["L"], cib.loc["L", "lo"],
                 cib.loc["L", "hi"], Z80 * rb.bse["L"]))
        print("    joint chi2 = %.4f, df %d, p = %.4f -> %s"
              % (stat, df, p,
                 "REJECT perfect calibration" if p < 0.05 else
                 "consistent with a perfectly calibrated closing price"))
        print("    slope b < 1 would mean the line is OVERCONFIDENT (favourites "
              "priced too short); b > 1 UNDERCONFIDENT.")
        out[tid] = rb
    return res, out


def part_a_t4(g):
    head("PART A.4  T4 -- EXCESS LOG LOSS, EARLY MINUS LATE "
         "(season-block bootstrap)")
    e = g.loc[g["EARLY"] == 1, "xll"].to_numpy()
    l = g.loc[g["EARLY"] == 0, "xll"].to_numpy()
    diff = e.mean() - l.mean()
    print("mean excess log loss  EARLY %.6f  (n %d)" % (e.mean(), len(e)))
    print("mean excess log loss  LATE  %.6f  (n %d)" % (l.mean(), len(l)))
    print("difference (EARLY - LATE) = %+.6f   (positive = the line is WORSE "
          "than its own price implies in early weeks)" % diff)

    rng = np.random.default_rng(20260920)
    seasons = sorted(g["season"].unique())
    parts = {s: (g.loc[(g.season == s) & (g.EARLY == 1), "xll"].to_numpy(),
                 g.loc[(g.season == s) & (g.EARLY == 0), "xll"].to_numpy())
             for s in seasons}
    boots = np.empty(2000)
    for i in range(2000):
        pick = rng.integers(0, len(seasons), len(seasons))
        ee = np.concatenate([parts[seasons[j]][0] for j in pick])
        ll = np.concatenate([parts[seasons[j]][1] for j in pick])
        boots[i] = ee.mean() - ll.mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    se = float(boots.std(ddof=1))
    z = diff / se
    p = 2 * stats.norm.sf(abs(z))
    record("T4", "excess log loss EARLY - LATE = 0", p)
    print("\nseason-block bootstrap (2000 resamples of whole seasons):")
    print("  SE %.6f   95%% CI [%+.6f, %+.6f]   z %+.3f   p %.4f"
          % (se, lo, hi, z, p))
    print("  -> %s" % ("the interval EXCLUDES zero: early-week calibration "
                       "really is different"
                       if (lo > 0 or hi < 0) else
                       "the interval CONTAINS zero: no detectable difference "
                       "in early-week calibration"))
    print("  MDE @80%% power: %.6f nats of excess log loss per game."
          % (Z80 * se))
    print("     For scale: a book that is systematically 2 pp wrong on every "
          "pick'em game carries about %.6f nats of excess log loss."
          % (0.5 * (-np.log(0.52) - np.log(0.48)) + np.log(0.5)))
    return diff, se, p


# ==========================================================================
# PART B -- do the features carry more signal early?
# ==========================================================================
VEC_COLS = ["F", "p_qb_z", "C", "R"]
VEC_NAMES = ["F", "P", "C", "R"]


def build_model_sample():
    head("PART B.0  SAMPLE CONSTRUCTION (model features)")
    path = os.path.join(HERE, "out_full_fit_table.parquet")
    d = pd.read_parquet(path)
    print("cached fit_full eligible sample            : %6d rows, seasons "
          "%d-%d, weeks %d-%d"
          % (len(d), d["season"].min(), d["season"].max(),
             d["week"].min(), d["week"].max()))
    d = d[d["game_type"].eq("REG")].copy()
    print("  ... REG only (match Part A)              : %6d" % len(d))
    d = d[d["season"].between(SEASON_LO, SEASON_HI)].copy()
    print("  ... seasons %d-%d                      : %6d"
          % (SEASON_LO, SEASON_HI, len(d)))
    d["EARLY"] = (d["week"] <= EARLY_MAX_WEEK).astype(int)
    print("\nLIMITATION, PRE-REGISTERED: this sample contains NO Week 1 "
          "(min week = %d)." % int(d["week"].min()))
    print("  Vector F is a current-season aggregate and is not ready in Week 1,")
    print("  so the EARLY bucket here is weeks 2-%d. The single week where the"
          % EARLY_MAX_WEEK)
    print("  market has least information is structurally untestable with these")
    print("  features. That is a fact about the features, not a choice made here.")
    print("\n  EARLY (weeks 2-%d): %d games   LATE (weeks %d+): %d games"
          % (EARLY_MAX_WEEK, int(d["EARLY"].sum()), EARLY_MAX_WEEK + 1,
             int((1 - d["EARLY"]).sum())))
    print(d.groupby(["season", "EARLY"]).size().unstack(fill_value=0)
          .rename(columns={0: "LATE", 1: "EARLY"}).T.to_string())
    return d


def expanding_oos(d):
    head("PART B.1  EXPANDING-WINDOW SEASON CV (train on earlier seasons only)")
    print("Identical to fit.py's season_cv: for each test season s, fit the "
          "4-term offset model on\nevery eligible game with season < s, then "
          "score season s. Never random k-fold.\n")
    pieces = []
    rows = []
    for s in range(SEASON_LO + 2, SEASON_HI + 1):
        tr = d[d["season"] < s]
        te = d[d["season"] == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        X = tr[VEC_COLS].to_numpy(dtype=float)
        r = sm.GLM(tr["home_win"].to_numpy(dtype=float),
                   pd.DataFrame(X, columns=VEC_COLS, index=tr.index),
                   family=sm.families.Binomial(),
                   offset=logit(tr["p_mkt_mult"].to_numpy())).fit()
        b = r.params.reindex(VEC_COLS).to_numpy(dtype=float)
        D = te[VEC_COLS].to_numpy(dtype=float).dot(b)
        piece = te[["game_id", "season", "week", "EARLY", "home_win",
                    "p_mkt_mult"]].copy()
        piece["D_oos"] = D
        pieces.append(piece)
        rows.append({"test": s, "n_train": len(tr), "n_test": len(te),
                     **{"B_" + n: r.params[c] for n, c in
                        zip(VEC_NAMES, VEC_COLS)}})
    fl = pd.DataFrame(rows).set_index("test")
    print(fl.round(4).to_string())
    signs = {n: ("all +" if fl["B_" + n].gt(0).all() else
                 "all -" if fl["B_" + n].lt(0).all() else "FLIPS")
             for n in VEC_NAMES}
    print("\nsign across folds: %s"
          % "  ".join("%s=%s" % (k, v) for k, v in signs.items()))
    oos = pd.concat(pieces, ignore_index=True)
    print("\npooled held-out games: %d  (%d EARLY, %d LATE), seasons %d-%d"
          % (len(oos), int(oos["EARLY"].sum()),
             int((1 - oos["EARLY"]).sum()),
             oos["season"].min(), oos["season"].max()))
    return oos


def part_b_tests(oos):
    head("PART B.2  T5 (PRIMARY) / T6 / T7 -- DOES D TRANSFER BETTER EARLY?")
    y = oos["home_win"].to_numpy(dtype=float)
    off = logit(oos["p_mkt_mult"].to_numpy())
    X = pd.DataFrame({
        "gE": (oos["D_oos"] * oos["EARLY"]).to_numpy(dtype=float),
        "gL": (oos["D_oos"] * (1 - oos["EARLY"])).to_numpy(dtype=float),
    }, index=oos.index)
    r = sm.GLM(y, X, family=sm.families.Binomial(), offset=off).fit()
    print("    logit P = offset(logit p_mkt) + gE * D_oos * EARLY "
          "+ gL * D_oos * LATE")
    print("    gamma = 1 : the past coefficients transferred perfectly")
    print("    gamma = 0 : the vectors carry nothing out of sample  <- the null\n")
    print(r.summary().as_text())

    ci = r.conf_int()
    ci.columns = ["lo", "hi"]
    tab = pd.DataFrame({
        "gamma": r.params, "SE": r.bse, "z": r.tvalues, "p": r.pvalues,
        "ci_lo": ci["lo"], "ci_hi": ci["hi"],
        "MDE@80% power": Z80 * r.bse,
        "differs from 0?": ["YES" if p < 0.05 else "no" for p in r.pvalues],
    })
    tab.index = ["gE (weeks 2-%d)" % EARLY_MAX_WEEK,
                 "gL (weeks %d+)" % (EARLY_MAX_WEEK + 1)]
    print()
    print(tab.round(4).to_string())

    # T5: difference
    c = np.array([1.0, -1.0])
    V = r.cov_params().to_numpy(dtype=float)
    dvar = float(c.dot(V).dot(c))
    dse = np.sqrt(dvar)
    dval = float(r.params["gE"] - r.params["gL"])
    z = dval / dse
    p5 = 2 * stats.norm.sf(abs(z))
    record("T5", "gamma_E - gamma_L = 0 (signal transfers better early)", p5)
    print("\nT5  gE - gL = %+.4f  (SE %.4f, z %+.3f, p %.4f, 95%% CI "
          "[%+.3f, %+.3f])"
          % (dval, dse, z, p5, dval - 1.96 * dse, dval + 1.96 * dse))
    print("    -> %s" % ("REJECT: the vectors transfer differently by week "
                         "bucket" if p5 < 0.05 else
                         "FAIL TO REJECT: no detectable difference between "
                         "early and late weeks"))
    print("    MDE @80%% power on the difference: %.4f gamma units." % (Z80 * dse))

    record("T6", "gamma_E = 0 (D carries signal in weeks 2-4)", r.pvalues["gE"])
    record("T7", "gamma_L = 0 (D carries signal in weeks 5+)", r.pvalues["gL"])
    print("\nT6  gE = %+.4f (SE %.4f, p %.4f)   T7  gL = %+.4f (SE %.4f, p %.4f)"
          % (r.params["gE"], r.bse["gE"], r.pvalues["gE"],
             r.params["gL"], r.bse["gL"], r.pvalues["gL"]))

    # descriptive: pooled OOS log loss by bucket (NO test)
    print("\nDESCRIPTIVE (no test): pooled out-of-sample log loss vs the "
          "closing price, by bucket.")
    pm = oos["p_mkt_mult"].to_numpy()
    # score the model at gamma = 1, i.e. exactly as the model would ship
    pmod = sigmoid(off + oos["D_oos"].to_numpy())
    rowsd = []
    for tag, mask in (("EARLY w2-%d" % EARLY_MAX_WEEK, oos["EARLY"] == 1),
                      ("LATE w%d+" % (EARLY_MAX_WEEK + 1), oos["EARLY"] == 0)):
        m = mask.to_numpy()
        rowsd.append({"bucket": tag, "n": int(m.sum()),
                      "ll_mkt": logloss(y[m], pm[m]),
                      "ll_model": logloss(y[m], pmod[m]),
                      "delta (+ = model better)":
                          logloss(y[m], pm[m]) - logloss(y[m], pmod[m])})
    print(pd.DataFrame(rowsd).set_index("bucket").round(6).to_string())
    return r, dval, dse, p5


# ==========================================================================
def power_and_verdict(a_res, t4, b_res, oos, g):
    head("POWER SUMMARY -- THE SMALLEST EFFECT EACH TEST COULD HAVE SEEN")
    diff, se4, p4 = t4
    n_e = int((g["EARLY"] == 1).sum())
    n_l = int((g["EARLY"] == 0).sum())
    n_oe = int((oos["EARLY"] == 1).sum())
    n_ol = int((oos["EARLY"] == 0).sum())
    print("PART A effective n: %d early / %d late games (2006-2025 REG, "
          "complete closing ML, non-tie)." % (n_e, n_l))
    print("PART B effective n: %d early / %d late HELD-OUT games "
          "(2008-2025 test seasons)." % (n_oe, n_ol))
    print("""
The MDE is the smallest TRUE effect this design would have caught 80% of the
time at a two-sided 5% level. Anything smaller than the MDE is simply not
resolved by this sample -- "unknown", not "no".""")
    print("\n  T1  a1 (early intercept shift)  MDE %.4f log-odds  "
          "= %.2f pp at a pick'em price"
          % (Z80 * a_res.bse["EARLY"],
             100 * (sigmoid(a_res.params["const"] + Z80 * a_res.bse["EARLY"])
                    - sigmoid(a_res.params["const"]))))
    print("  T1  b1 (early slope shift)     MDE %.4f slope units"
          % (Z80 * a_res.bse["EARLY_x_L"]))
    print("  T4  excess log loss difference MDE %.5f nats/game" % (Z80 * se4))
    print("  T5  gamma_E - gamma_L          MDE %.4f gamma units"
          % (Z80 * float(np.sqrt(
              np.array([1.0, -1.0]).dot(b_res.cov_params().to_numpy())
              .dot(np.array([1.0, -1.0]))))))
    print("  T6  gamma_E                    MDE %.4f gamma units"
          % (Z80 * b_res.bse["gE"]))
    print("  T7  gamma_L                    MDE %.4f gamma units"
          % (Z80 * b_res.bse["gL"]))

    head("EVERY TEST RUN, AND MULTIPLICITY")
    tab = pd.DataFrame(TESTS, columns=["id", "hypothesis tested", "p"])
    rej = benjamini_hochberg(tab["p"].to_numpy(), q=0.10)
    tab["raw p<.05"] = ["YES" if p < 0.05 else "no" for p in tab["p"]]
    tab["BH q=10%"] = ["SURVIVES" if r else "rejected" for r in rej]
    print(tab.set_index("id").round(5).to_string())
    print("\nTOTAL PRE-REGISTERED TESTS RUN: %d. No others were run. No filter, "
          "window or cutoff\nwas changed after seeing any result above."
          % len(TESTS))

    head("VERDICT")
    p1 = dict((t[0], t[2]) for t in TESTS)
    print("H_market (the closing line is worse calibrated in weeks 1-4):")
    print("    T1 joint calibration difference        p = %.4f  %s"
          % (p1["T1"], "SIGNIFICANT" if p1["T1"] < .05 else "not significant"))
    print("    T2 early bucket vs perfect calibration p = %.4f  %s"
          % (p1["T2"], "SIGNIFICANT" if p1["T2"] < .05 else "not significant"))
    print("    T3 late  bucket vs perfect calibration p = %.4f  %s"
          % (p1["T3"], "SIGNIFICANT" if p1["T3"] < .05 else "not significant"))
    print("    T4 excess log loss early - late        p = %.4f  %s"
          % (p1["T4"], "SIGNIFICANT" if p1["T4"] < .05 else "not significant"))
    print("\nH_model (the vectors carry more signal in weeks 2-4):")
    print("    T5 gamma_E - gamma_L                   p = %.4f  %s"
          % (p1["T5"], "SIGNIFICANT" if p1["T5"] < .05 else "not significant"))
    print("    T6 gamma_E vs 0                        p = %.4f  %s"
          % (p1["T6"], "SIGNIFICANT" if p1["T6"] < .05 else "not significant"))
    print("    T7 gamma_L vs 0                        p = %.4f  %s"
          % (p1["T7"], "SIGNIFICANT" if p1["T7"] < .05 else "not significant"))
    print("\nThe pre-registered bar for claiming an early-season edge was: T1 "
          "significant AND\n(T5 or T6) significant. Met? %s"
          % ("YES" if (p1["T1"] < .05 and (p1["T5"] < .05 or p1["T6"] < .05))
             else "NO"))


def main():
    print(RULE)
    print("EARLY-SEASON EDGE HUNT  --  id 'early-season'")
    print("pre-registered above; run once; offline; writes nothing outside "
          "tools/backtest/")
    print(RULE)

    g = build_market_sample()
    g = descriptives(g)
    a_res, buckets = part_a_tests(g)
    t4 = part_a_t4(g)

    d = build_model_sample()
    oos = expanding_oos(d)
    b_res, dval, dse, p5 = part_b_tests(oos)

    power_and_verdict(a_res, t4, b_res, oos, g)


if __name__ == "__main__":
    main()
