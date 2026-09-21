#!/usr/bin/env python3
"""
price_extremes.py -- PRE-REGISTERED test of the favourite-longshot bias in the
nflverse NFL closing moneyline.

id: price-extremes

================================================================================
PRE-REGISTRATION.  Written before any of the code below was executed.
Everything in this block was fixed in advance; nothing in it is chosen after
seeing a result.  Any departure is flagged in the output as POST-HOC.
================================================================================

HYPOTHESIS
  Favourite-longshot bias: big underdogs are systematically OVERPRICED.  Their
  no-vig implied win probability exceeds their realised win rate; equivalently
  the market's probability scale is COMPRESSED -- it is too close to 50% at the
  extremes relative to reality.

WHY THIS IS THE RIGHT FIRST TEST
  It is one of the most replicated findings in betting-market research (horse
  racing, and to a weaker degree the major US team sports).  It needs no
  features, no model, no look-ahead: only prices and outcomes.  It is therefore
  ALSO a validity check on this whole data pipeline.  If a well-documented
  market-structure effect cannot even be recovered here, the pipeline, not the
  hypothesis, is the thing under suspicion.

SAMPLE FILTER  (fixed in advance)
  nflverse games.csv, rows with:
    - a played result (result / home_score / away_score all present)
    - BOTH closing moneylines present          -> first available season is 2006
    - two-way overround > 0 (a no-vig price is undefined otherwise)
    - result != 0.  A tie is a moneyline PUSH, not a loss.  Excluded, counted.
    - season <= 2025.  The 17 games of 2026 played to date are an in-progress
      season and are excluded.
  DISCOVERY period : seasons 2006-2015
  HOLDOUT  period  : seasons 2016-2025
  The split is season-wise and chronological.  No random k-fold anywhere.

DE-VIG  (fixed in advance)
  Multiplicative / proportional: p = q_side / (q_home + q_away).  This is the
  method fit.py already documents and uses, so it is inherited, not chosen.
  CAVEAT, stated in advance: proportional de-vig ASSUMES vig is loaded in equal
  proportion on both sides.  If books instead load extra margin onto longshots
  -- which is one mechanism by which the bias is thought to exist -- proportional
  de-vig will absorb part of the effect and BIAS THIS TEST TOWARD THE NULL.
  Test T6 below re-runs the primary test under additive/shift de-vig for this
  reason.

RESPONSE VARIABLE
  home_win = 1[result > 0], one row per game.  The away side is the exact
  mirror (p_away = 1 - p_home, logit(p_away) = -logit(p_home)), so fitting the
  home side alone is complete and avoids double-counting two perfectly
  dependent observations.

THE SIX PRE-REGISTERED TESTS
  T1 (PRIMARY, discovery).  Logistic calibration regression on 2006-2015:
         logit P(home win) = a + b * logit(p_mkt_home)
     Null: b = 1 (market probabilities correctly scaled).
     H1  : b > 1  (compression at the extremes = longshots overpriced).
     One-sided, threshold p < 0.05.
  T2 (PRIMARY, OUT OF SAMPLE).  The identical regression on 2016-2025.
     The hypothesis is only supported if b > 1 one-sided p < 0.05 HERE.  T1
     alone does not count for anything.
  T3 (discovery, bucket family).  Bucket every game by the closing American
     price of its UNDERDOG side, with these edges fixed in advance:
         PK    : dog price < +110
         B1    : +110 .. +174
         B2    : +175 .. +249
         B3    : +250 .. +349
         B4    : +350 .. +499
         B5    : +500 .. +699
         B6    : +700 and longer
     In each bucket compare realised dog win rate to mean no-vig dog implied
     probability.  Two-sided exact binomial per bucket, Benjamini-Hochberg at
     FDR 10% across the 7 buckets as one family.
  T4 (holdout, bucket family).  Identical, on 2016-2025.
  T5 (ECONOMIC / DOES IT SURVIVE THE VIG, holdout).  In holdout games whose dog
     price is +250 or longer (buckets B3-B6), flat-bet 1 unit on the FAVOURITE
     at its ACTUAL QUOTED price.  ROI vs zero, one-sided t-test, p < 0.05.
     The +250 cut is fixed here in advance.  The full per-bucket ROI table is
     printed as DESCRIPTIVE ONLY; any other cut that happens to look good in it
     is post-hoc and will be labelled as such.
  T6 (robustness, holdout).  T2 re-run with additive/shift de-vig
     (p = q_side - hold/2) instead of multiplicative.

DECISION RULE  (fixed in advance)
  "A real, tradeable longshot-bias edge exists in this data" requires ALL of:
    (i)   T2 significant at one-sided 5% in the predicted direction (b > 1), and
    (ii)  T5 ROI significantly > 0 at one-sided 5%.
  T1/T3 failing while T2/T5 pass would itself be suspicious and is reported.
  If (i) holds but (ii) fails, the correct statement is "the bias is visible in
  probabilities but is smaller than the vig", which is NOT an edge.

POWER
  Reported for every test: effective n and the smallest effect detectable with
  80% power at the stated one- or two-sided alpha.  An insignificant result on
  an underpowered test means UNKNOWN, not NO.

WHAT WOULD FALSIFY THE PIPELINE
  If b is materially BELOW 1 out of sample, or the bucket table shows big dogs
  winning MORE often than their implied price, that is the opposite of a
  century of published results and points at a data defect -- most likely
  stale/mismatched prices or a home/away column swap.  A home/away orientation
  check is run first, before anything else, for exactly this reason.
================================================================================

Run:
    cd /Users/cmanlongat/Projects/pick-six && /opt/homebrew/bin/uv run \
      --with pandas --with pyarrow --with numpy --with scipy --with statsmodels \
      --with scikit-learn python tools/backtest/price_extremes.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from load import load_games

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)

RULE = "=" * 98
THIN = "-" * 98

DISC = (2006, 2015)
HOLD = (2016, 2025)

# bucket edges on the UNDERDOG side's American price -- fixed in advance
BUCKETS = [
    ("PK  <+110", -10_000, 110),
    ("B1 +110..174", 110, 175),
    ("B2 +175..249", 175, 250),
    ("B3 +250..349", 250, 350),
    ("B4 +350..499", 350, 500),
    ("B5 +500..699", 500, 700),
    ("B6 +700+", 700, 10_000_000),
]
ECON_CUT = 250          # T5 pre-registered cut: dog price >= +250

TEST_LOG = []


def log_test(tid, what, result):
    TEST_LOG.append({"test": tid, "what": what, "result": result})


def head(t):
    print("\n" + RULE)
    print(t)
    print(RULE)


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def american_to_prob(ml):
    ml = np.asarray(ml, dtype=float)
    neg = ml < 0
    out = np.empty_like(ml)
    out[neg] = (-ml[neg]) / ((-ml[neg]) + 100.0)
    out[~neg] = 100.0 / (ml[~neg] + 100.0)
    return out


def profit_per_unit(ml):
    """Profit on a winning 1-unit bet at American price ml."""
    ml = np.asarray(ml, dtype=float)
    return np.where(ml < 0, 100.0 / np.abs(ml), ml / 100.0)


def bh(pvals, q=0.10):
    p = np.asarray(pvals, float)
    n = len(p)
    order = np.argsort(p)
    passed = p[order] <= q * (np.arange(1, n + 1) / n)
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    rej = np.zeros(n, bool)
    if k:
        rej[order[:k]] = True
    return rej


# ==========================================================================
# 0. build the sample
# ==========================================================================
def build():
    head("0. SAMPLE  (filter fixed in the pre-registration, not after looking)")
    g = load_games(require_lines=False, played_only=True)
    print("nflverse games.csv, played games, all seasons        : %5d" % len(g))

    g = g.dropna(subset=["home_moneyline", "away_moneyline"]).copy()
    print("  with BOTH closing moneylines                       : %5d"
          " (first season %d)" % (len(g), int(g["season"].min())))

    n_2026 = int((g["season"] > 2025).sum())
    g = g[g["season"] <= 2025].copy()
    print("  drop in-progress 2026                              : -%4d -> %d"
          % (n_2026, len(g)))

    g["q_home"] = american_to_prob(g["home_moneyline"])
    g["q_away"] = american_to_prob(g["away_moneyline"])
    g["overround"] = g["q_home"] + g["q_away"]
    g["hold"] = g["overround"] - 1.0
    n_bad = int((g["hold"] <= 0).sum())
    g = g[g["hold"] > 0].copy()
    print("  drop overround <= 0 (no-vig price undefined)       : -%4d -> %d"
          % (n_bad, len(g)))

    n_tie = int((g["result"] == 0).sum())
    g = g[g["result"] != 0].copy()
    print("  drop ties (moneyline PUSH, not a loss)             : -%4d -> %d"
          % (n_tie, len(g)))

    g["home_win"] = (g["result"] > 0).astype(int)
    g["p_home"] = g["q_home"] / g["overround"]            # multiplicative
    g["p_away"] = g["q_away"] / g["overround"]
    g["p_home_shift"] = g["q_home"] - g["hold"] / 2.0     # additive (T6)

    # underdog side = lower raw implied probability
    home_is_dog = g["q_home"] < g["q_away"]
    g["dog_is_home"] = home_is_dog
    g["dog_price"] = np.where(home_is_dog, g["home_moneyline"],
                              g["away_moneyline"])
    g["fav_price"] = np.where(home_is_dog, g["away_moneyline"],
                              g["home_moneyline"])
    g["p_dog"] = np.where(home_is_dog, g["p_home"], g["p_away"])
    g["dog_win"] = np.where(home_is_dog, g["home_win"], 1 - g["home_win"])

    print("\nFINAL ANALYSIS SAMPLE: %d games, seasons %d-%d"
          % (len(g), int(g["season"].min()), int(g["season"].max())))
    print("  mean two-way overround (the vig) : %.4f  (hold %.2f%%)"
          % (g["overround"].mean(), 100 * g["hold"].mean()))
    print("  median overround                 : %.4f" % g["overround"].median())

    d = g[g["season"].between(*DISC)]
    h = g[g["season"].between(*HOLD)]
    print("  DISCOVERY %d-%d : %d games" % (DISC[0], DISC[1], len(d)))
    print("  HOLDOUT   %d-%d : %d games" % (HOLD[0], HOLD[1], len(h)))
    print("\nper season:")
    print(g.groupby("season").agg(n=("game_id", "size"),
                                  home_win=("home_win", "mean"),
                                  p_home=("p_home", "mean"),
                                  overround=("overround", "mean"))
          .round(4).to_string())
    return g


# ==========================================================================
# V. orientation / validity checks -- run BEFORE the hypothesis tests
# ==========================================================================
def validity(g):
    head("V. ORIENTATION CHECKS  (not hypothesis tests -- pipeline sanity)")
    print("If the home/away columns were swapped or the prices were stale, the")
    print("longshot test would return garbage and we would not know why.\n")

    print("V1. Does the favourite win more than the dog?  "
          "(if not, the price column is broken)")
    print("    favourite win rate : %.4f  over %d games"
          % (1 - g["dog_win"].mean(), len(g)))

    print("\nV2. Home-field: realised home win rate vs mean no-vig home price")
    print("    realised %.4f   priced %.4f   gap %+.4f"
          % (g["home_win"].mean(), g["p_home"].mean(),
             g["home_win"].mean() - g["p_home"].mean()))

    print("\nV3. Does the price actually rank outcomes?  Spearman corr of")
    print("    p_home with home_win, and AUC:")
    rho = stats.spearmanr(g["p_home"], g["home_win"]).statistic
    auc = ((g.loc[g.home_win == 1, "p_home"].values[:, None]
            > g.loc[g.home_win == 0, "p_home"].values[None, :]).mean()
           + 0.5 * (g.loc[g.home_win == 1, "p_home"].values[:, None]
                    == g.loc[g.home_win == 0, "p_home"].values[None, :]).mean())
    print("    spearman %.4f    AUC %.4f   (AUC ~0.5 would mean the price is "
          "noise; <0.5 would mean the columns are swapped)" % (rho, auc))

    print("\nV4. Cross-check against spread_line (nflverse: points the HOME team")
    print("    is favoured by).  The moneyline and the spread must agree on who")
    print("    the favourite is:")
    sub = g.dropna(subset=["spread_line"])
    agree = ((sub["spread_line"] > 0) == (sub["q_home"] > sub["q_away"]))
    nz = sub["spread_line"] != 0
    print("    agree on favourite : %d / %d non-pickem games (%.2f%%)"
          % (int(agree[nz].sum()), int(nz.sum()),
             100 * agree[nz].mean()))
    print("    -> a low number here would mean a sign or orientation bug.")
    return auc


# ==========================================================================
# T1 / T2 / T6 -- the calibration slope
# ==========================================================================
def calib(sub, pcol, label, tid):
    y = sub["home_win"].to_numpy(float)
    x = logit(sub[pcol].to_numpy())
    X = sm.add_constant(pd.DataFrame({"logit_p": x}))
    r = sm.GLM(y, X, family=sm.families.Binomial()).fit()
    b, se = r.params["logit_p"], r.bse["logit_p"]
    a, a_se = r.params["const"], r.bse["const"]
    z = (b - 1.0) / se
    p_one = 1 - stats.norm.cdf(z)          # H1: b > 1
    lo, hi = r.conf_int().loc["logit_p"]
    mde = 2.486 * se                       # 80% power, one-sided alpha=.05
    print("%s   n = %d" % (label, len(sub)))
    print("    intercept a = %+.4f (SE %.4f)   [a=0 means no residual home tilt]"
          % (a, a_se))
    print("    slope     b = %+.4f (SE %.4f)   95%% CI [%+.4f, %+.4f]"
          % (b, se, lo, hi))
    print("    H0: b = 1   vs   H1: b > 1 (longshot bias / compression)")
    print("    z = %+.3f   one-sided p = %.4f   -> %s"
          % (z, p_one, "SIGNIFICANT" if p_one < 0.05 else "not significant"))
    print("    POWER: smallest b-1 detectable at 80%% power here = %+.4f "
          "(i.e. b >= %.4f). Observed b-1 = %+.4f" % (mde, 1 + mde, b - 1))
    log_test(tid, label,
             "b=%+.4f (SE %.4f), one-sided p=%.4f, %s; MDE b-1=%.4f, obs b-1=%+.4f"
             % (b, se, p_one, "SIG" if p_one < 0.05 else "ns", mde, b - 1))
    return b, se, p_one, mde


# ==========================================================================
# T3 / T4 -- the bucket table
# ==========================================================================
def bucket_table(sub, label, tid):
    rows, pvals = [], []
    for name, lo, hi in BUCKETS:
        m = (sub["dog_price"] >= lo) & (sub["dog_price"] < hi)
        s = sub[m]
        n = len(s)
        if n == 0:
            rows.append({"bucket": name, "n": 0})
            pvals.append(1.0)
            continue
        implied = s["p_dog"].mean()
        actual = s["dog_win"].mean()
        wins = int(s["dog_win"].sum())
        bt = stats.binomtest(wins, n, implied) if n else None
        pv = bt.pvalue if bt else 1.0
        se = np.sqrt(max(implied * (1 - implied), 1e-9) / n)
        # ROI of backing the DOG at the quoted price, and of backing the FAV
        ret_dog = np.where(s["dog_win"] == 1, profit_per_unit(s["dog_price"]), -1.0)
        ret_fav = np.where(s["dog_win"] == 0, profit_per_unit(s["fav_price"]), -1.0)
        rows.append({
            "bucket": name, "n": n,
            "dog_implied": implied, "dog_actual": actual,
            "gap(act-imp)": actual - implied,
            "binom_p": pv,
            "MDE_80pct": 2.8 * se,
            "ROI_dog": ret_dog.mean(), "ROI_fav": ret_fav.mean(),
        })
        pvals.append(pv)
    tab = pd.DataFrame(rows).set_index("bucket")
    rej = bh(pvals, q=0.10)
    tab["BH q=10%"] = ["SURVIVES" if r else "-" for r in rej]
    print("%s" % label)
    print(tab.round(4).to_string())
    print("  gap < 0  => dogs win LESS than priced  => longshot bias as predicted")
    print("  gap > 0  => dogs win MORE than priced  => the OPPOSITE of the prior")
    print("  MDE_80pct = smallest |gap| this bucket has 80%% power to detect "
          "(two-sided 5%%).")
    surv = [i for i, r in zip(tab.index, rej) if r]
    log_test(tid, label,
             "7 buckets, BH FDR 10%%: %s" % (", ".join(surv) if surv else "NONE survive"))
    return tab


# ==========================================================================
# T5 -- does it survive the vig
# ==========================================================================
def econ(sub, label, tid, cut=ECON_CUT, preregistered=True):
    s = sub[sub["dog_price"] >= cut]
    n = len(s)
    if n < 2:
        print("%s: n=%d, not testable" % (label, n))
        return None
    ret = np.where(s["dog_win"] == 0, profit_per_unit(s["fav_price"]), -1.0)
    roi, sd = ret.mean(), ret.std(ddof=1)
    se = sd / np.sqrt(n)
    t = roi / se
    p_one = 1 - stats.t.cdf(t, n - 1)
    mde = 2.486 * se
    tag = "PRE-REGISTERED" if preregistered else "POST-HOC (not pre-registered)"
    print("%s   [%s]" % (label, tag))
    print("    flat 1u on the FAVOURITE, dog price >= +%d, at the QUOTED price"
          % cut)
    print("    n = %d bets   fav win rate %.4f   mean price %.1f"
          % (n, 1 - s["dog_win"].mean(), s["fav_price"].mean()))
    print("    ROI = %+.4f  (%.2f%%)  SE %.4f   one-sided t = %+.3f  p = %.4f "
          "-> %s" % (roi, 100 * roi, se, t, p_one,
                     "SIGNIFICANT" if p_one < 0.05 else "not significant"))
    print("    POWER: smallest ROI detectable at 80%% power = %+.4f (%.2f%%)"
          % (mde, 100 * mde))
    # bootstrap for honesty about the fat-tailed return distribution
    rng = np.random.default_rng(20260920)
    boot = ret[rng.integers(0, n, size=(10000, n))].mean(axis=1)
    blo, bhi = np.percentile(boot, [2.5, 97.5])
    print("    bootstrap 95%% CI on ROI: [%+.4f, %+.4f]" % (blo, bhi))
    log_test(tid, label,
             "n=%d ROI=%+.4f one-sided p=%.4f %s; MDE ROI=%.4f; boot CI [%+.4f,%+.4f]"
             % (n, roi, p_one, "SIG" if p_one < 0.05 else "ns", mde, blo, bhi))
    return roi, p_one, mde


def main():
    print(RULE)
    print("price-extremes  |  PRE-REGISTERED favourite-longshot-bias test")
    print("offline. reads the nflverse cache. writes nothing outside tools/backtest/.")
    print(RULE)
    print(__doc__[__doc__.index("PRE-REGISTRATION"):__doc__.index("Run:")])

    g = build()
    validity(g)

    disc = g[g["season"].between(*DISC)]
    hold = g[g["season"].between(*HOLD)]

    head("T1 (PRIMARY, DISCOVERY 2006-2015).  CALIBRATION SLOPE")
    print("""logit P(home win) = a + b * logit(p_mkt_home),  multiplicative de-vig.
b = 1 is a perfectly scaled market.  b > 1 means the market's probabilities are
COMPRESSED toward 50% -- longshots priced too short, favourites too long -- which
is the favourite-longshot bias.  b < 1 means the opposite (over-extended prices).
""")
    calib(disc, "p_home", "DISCOVERY 2006-2015", "T1")

    head("T2 (PRIMARY, OUT OF SAMPLE, HOLDOUT 2016-2025).  SAME REGRESSION")
    print("Chronological holdout. The specification is byte-identical to T1.\n")
    b2, se2, p2, mde2 = calib(hold, "p_home", "HOLDOUT 2016-2025", "T2")

    head("T3 (DISCOVERY).  BUCKETS BY CLOSING UNDERDOG PRICE")
    bucket_table(disc, "DISCOVERY 2006-2015", "T3")

    head("T4 (HOLDOUT).  BUCKETS BY CLOSING UNDERDOG PRICE")
    t4 = bucket_table(hold, "HOLDOUT 2016-2025", "T4")

    head("T5 (HOLDOUT, ECONOMIC).  DOES ANY OF IT SURVIVE THE VIG?")
    print("""A probability tilt is only an edge if you can bet it at the quoted price.
If big dogs are overpriced then backing the FAVOURITE in those games should make
money at the actual price, vig included.
""")
    r5 = econ(hold, "HOLDOUT 2016-2025", "T5")

    head("T6 (ROBUSTNESS, HOLDOUT).  ADDITIVE / SHIFT DE-VIG")
    print("""Pre-registered because proportional de-vig can itself hide the effect:
if books load extra margin onto longshots, proportional de-vig spreads that margin
evenly and biases T2 toward the null. Shift de-vig makes the opposite assumption.
""")
    calib(hold, "p_home_shift", "HOLDOUT 2016-2025, shift de-vig", "T6")

    head("FULL-SAMPLE REFERENCE (2006-2025, descriptive -- NOT a test)")
    print("Printed so the pooled numbers are on the record. It is not counted as")
    print("a test because it contains the holdout and cannot be out of sample.\n")
    full = bucket_table(g, "FULL 2006-2025 (descriptive)", "REF")
    TEST_LOG.pop()   # not a test; keep it out of the count

    head("EVERY TEST RUN, IN ORDER")
    print("Pre-registered: T1, T2, T3, T4, T5, T6. Nothing else was run.\n")
    for i, r in enumerate(TEST_LOG, 1):
        print("%2d. [%s] %s" % (i, r["test"], r["what"]))
        print("      %s" % r["result"])
    print("\nTOTAL TESTS RUN: %d" % len(TEST_LOG))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "out_price_extremes.parquet")
    g.to_parquet(out, index=False)
    print("\nanalysis sample written to %s (%d rows)" % (out, len(g)))


if __name__ == "__main__":
    main()
