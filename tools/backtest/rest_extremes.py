#!/usr/bin/env python3
"""
rest_extremes.py -- PRE-REGISTERED test of the hypothesis that EXTREME REST
situations are mispriced by the NFL closing line.

id: rest-extremes

======================================================================
PRE-REGISTRATION -- written and frozen BEFORE any outcome was inspected
======================================================================

HYPOTHESIS
  The closing spread and closing total under-adjust for genuine rest extremes.
  Prior: in the 4-term moneyline fit, C (the rest/travel/timezone composite)
  was insignificant overall (B = -0.085, SE 0.052). An average over all games
  can hide an effect that lives only in the tails. This script goes to the
  tails.

WHAT COUNTS AS "EXTREME" -- cutoffs fixed from the NFL CALENDAR, not from data
  A structural audit of games.csv (row COUNTS of home_rest/away_rest only, no
  outcome ever touched) established the calendar shape of NFL rest:
      rest =  4   playing on Thursday (short week).  BOTH teams are on 4 days
                  in 291 of 292 such REG games -- Thursday games are
                  short-week for BOTH sides, so there is NO directional
                  "short-week team" to bet.  n = 1 game in 27 seasons has
                  exactly one team on <= 4.  A directional short-week SIDE
                  test is therefore impossible and is NOT attempted; the
                  short week is tested on TOTALS instead.
      rest =  7   the normal Sunday-to-Sunday week (4,741 of 6,984 REG games
                  are 7 vs 7).
      rest = 10   the week AFTER playing Thursday.
      rest = 13/14 returning from a bye.
  The only meaningful calendar gaps are therefore 10-vs-7 (= 3 days) and
  13/14-vs-7 (= 6/7 days).  |rest_diff| >= 3 is the smallest cutoff that
  captures both and excludes the trivial 6-vs-7 Monday-to-Sunday case.
  CUTOFF = 3 DAYS. Fixed here, before running. It is not moved later.

SAMPLE FILTER (identical for every test)
  nflverse games.csv, game_type == 'REG' only (playoff byes are seeded by
  team quality, a different animal, and are excluded by pre-registration),
  non-null home_rest, away_rest, spread_line, total_line, result, scores.
  Seasons 1999-2025.  2026 rows have no result and drop out automatically.

RESPONSE VARIABLES
  rest_diff   = home_rest - away_rest
  home_ats    = result - spread_line          (nflverse spread_line = points
                                               the HOME team is favoured by,
                                               so >0 means home beat the close)
  rested_ats  = sign(rest_diff) * home_ats    (>0 = the RESTED side beat the
                                               closing spread)
  tot_resid   = (home_score + away_score) - total_line

THE FIVE PRE-REGISTERED TESTS
  T1 PRIMARY  SIDE,   |rest_diff| >= 3        H0: mean(rested_ats) = 0
  T2          SIDE,   exactly one team rest >= 13 (post-bye vs non-bye)
                                              H0: mean(rested_ats) = 0
  T3          TOTALS, both teams rest <= 4 (Thursday)
                                              H0: mean(tot_resid) = 0
  T4          TOTALS, |rest_diff| >= 3        H0: mean(tot_resid) = 0
  T5          MONEYLINE, |rest_diff| >= 3     H0: rested side's realised win
                                              rate = its no-vig closing
                                              probability (ROI at the posted
                                              price = 0 after vig)
  Each is a two-sided test at alpha = 0.05, SEs CLUSTERED BY SEASON (games in
  one season share a line-setting regime; naive iid SEs would be too small).
  Across the five HOLDOUT p-values: Benjamini-Hochberg at FDR 10%.

OUT-OF-SAMPLE RULE (season-wise, never random k-fold)
  DISCOVERY / TRAIN : seasons 1999-2014
  HOLDOUT  / TEST   : seasons 2015-2025
  A test only COUNTS if the HOLDOUT is significant AND carries the SAME SIGN
  as the discovery sample. Discovery significance on its own is not a finding.

PRE-REGISTERED ROBUSTNESS (declared here so it cannot be a post-hoc rescue)
  R1 For T1 and T2, also fit  home_ats ~ 1 + rest_diff  on the same subsample.
     The intercept absorbs any residual home-ATS bias; the slope is the rest
     effect. If the sign-flipped mean and this slope DISAGREE, the result is
     called FRAGILE, not an edge.
  R2 Per-season holdout sign-stability table is printed for T1.

THRESHOLD FOR DECLARING AN EDGE (fixed in advance)
  All of: (a) holdout p < 0.05 two-sided, season-clustered;
          (b) same sign as discovery;
          (c) survives BH at FDR 10% across the five holdout tests;
          (d) holdout effect large enough to clear -110 vig, i.e. mean
              |rested_ats| >= 0.82 points (the ATS margin that corresponds to
              a 52.38% cover rate at an ATS margin SD of ~13.8).
  Anything less is reported as NO EDGE or as UNDERPOWERED/UNKNOWN.

NOTHING HERE IS TUNED. If a result appears only after a cutoff moves, it is
not an edge and the report says so explicitly.
"""

import os
import sys

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import load_games  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

CUTOFF_DAYS = 3          # frozen, calendar-derived
TRAIN_HI = 2014          # discovery: 1999-2014
TEST_LO = 2015           # holdout:   2015-2025
RULE = "=" * 96
THIN = "-" * 96

TESTS = []               # every test that is RUN gets appended here


def head(t):
    print("\n" + RULE)
    print(t)
    print(RULE)


def american_to_prob(ml):
    ml = np.asarray(ml, dtype=float)
    out = np.empty_like(ml)
    neg = ml < 0
    out[neg] = (-ml[neg]) / ((-ml[neg]) + 100.0)
    out[~neg] = 100.0 / (ml[~neg] + 100.0)
    return out


def american_profit(ml):
    """Profit on a 1-unit WINNING bet at this American price."""
    ml = np.asarray(ml, dtype=float)
    return np.where(ml < 0, 100.0 / (-ml), ml / 100.0)


def clustered_mean_test(y, cluster, label):
    """
    Mean of y, H0: mean = 0, with SEs clustered on `cluster` (season).
    Implemented as an intercept-only OLS with cluster-robust covariance --
    the standard way to get a mean test that respects within-season
    correlation.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 10:
        return dict(label=label, n=n, mean=np.nan, se=np.nan, t=np.nan,
                    p=np.nan, lo=np.nan, hi=np.nan, iid_se=np.nan)
    X = np.ones((n, 1))
    res = sm.OLS(y, X).fit(cov_type="cluster",
                           cov_kwds={"groups": np.asarray(cluster)})
    lo, hi = res.conf_int()[0]
    return dict(label=label, n=n, mean=float(res.params[0]),
                se=float(res.bse[0]), t=float(res.tvalues[0]),
                p=float(res.pvalues[0]), lo=float(lo), hi=float(hi),
                iid_se=float(np.std(y, ddof=1) / np.sqrt(n)),
                sd=float(np.std(y, ddof=1)))


def mde(sd, n, alpha=0.05, power=0.80):
    """Smallest true mean detectable with `power` at `alpha`, two-sided."""
    if n <= 1 or not np.isfinite(sd):
        return np.nan
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    return (z_a + z_b) * sd / np.sqrt(n)


def cover_rate(ats):
    """Win / loss / push rate against the close."""
    ats = np.asarray(ats, dtype=float)
    w = int((ats > 0).sum())
    l = int((ats < 0).sum())
    p = int((ats == 0).sum())
    dec = w + l
    return w, l, p, (w / dec if dec else np.nan)


def roi_110(ats):
    """ROI of a 1-unit bet at -110 on that side; pushes refunded."""
    ats = np.asarray(ats, dtype=float)
    w = (ats > 0).sum()
    l = (ats < 0).sum()
    n = w + l
    if n == 0:
        return np.nan
    return (w * (100.0 / 110.0) - l) / n


def report(r, extra=""):
    print("  n = %-5d  mean = %+7.4f   clustered SE %6.4f  (iid SE %6.4f)   "
          "t = %+6.3f   p = %.4f   95%% CI [%+.3f, %+.3f]%s"
          % (r["n"], r["mean"], r["se"], r["iid_se"], r["t"], r["p"],
             r["lo"], r["hi"], extra))


def run_split_test(df, yname, label, kind):
    """Run one pre-registered test on discovery then holdout. Returns dict."""
    tr = df[df["season"] <= TRAIN_HI]
    te = df[df["season"] >= TEST_LO]
    print("\n%s" % THIN)
    print("%s" % label)
    print(THIN)
    out = {}
    for tag, dd in (("DISCOVERY 1999-%d" % TRAIN_HI, tr),
                    ("HOLDOUT   %d-2025" % TEST_LO, te),
                    ("(full sample, reference only)", df)):
        r = clustered_mean_test(dd[yname], dd["season"], tag)
        extra = ""
        if kind == "ats":
            w, l, p, cr = cover_rate(dd[yname])
            extra = "   |  %d-%d-%d  cover %.4f  ROI@-110 %+.4f" % (
                w, l, p, cr, roi_110(dd[yname]))
        elif kind == "tot":
            w, l, p, cr = cover_rate(dd[yname])
            extra = "   |  over %d / under %d / push %d  over-rate %.4f" % (
                w, l, p, cr)
        print("  %-30s" % tag, end="")
        print("n = %-5d mean %+7.4f  cSE %6.4f  t %+6.3f  p %.4f  "
              "CI [%+.3f,%+.3f]%s"
              % (r["n"], r["mean"], r["se"], r["t"], r["p"], r["lo"], r["hi"],
                 extra))
        out[tag.split()[0]] = r
    d_sd = out["HOLDOUT"].get("sd", np.nan)
    m = mde(d_sd, out["HOLDOUT"]["n"])
    print("  POWER: holdout SD %.3f, n %d -> 80%%-power MDE = %.3f %s"
          % (d_sd, out["HOLDOUT"]["n"], m,
             "points" if kind in ("ats", "tot") else "units"))
    out["mde"] = m
    return out


def main():
    print(RULE)
    print("REST EXTREMES -- pre-registered mispricing test   id: rest-extremes")
    print(RULE)
    print(__doc__)

    head("0. SAMPLE CONSTRUCTION")
    g = load_games(require_lines=False, played_only=True, season_type="REG")
    g = g.dropna(subset=["home_rest", "away_rest", "spread_line", "total_line",
                         "result", "home_score", "away_score"]).copy()
    g = g[g["season"] <= 2025]
    g["rest_diff"] = g["home_rest"] - g["away_rest"]
    g["home_ats"] = g["result"] - g["spread_line"]
    g["rested_ats"] = np.sign(g["rest_diff"]) * g["home_ats"]
    g["tot_pts"] = g["home_score"] + g["away_score"]
    g["tot_resid"] = g["tot_pts"] - g["total_line"]
    print("REG games 1999-2025 with rest + closing spread + closing total + "
          "result: %d" % len(g))
    print("ATS margin SD (all REG games): %.3f" % g["home_ats"].std())
    print("total residual SD (all REG games): %.3f" % g["tot_resid"].std())

    ext = g[g["rest_diff"].abs() >= CUTOFF_DAYS].copy()
    bye = g[((g["home_rest"] >= 13).astype(int)
             + (g["away_rest"] >= 13).astype(int)) == 1].copy()
    thu = g[(g["home_rest"] <= 4) & (g["away_rest"] <= 4)].copy()

    print("\nBUCKET SIZES (cutoff frozen at |rest_diff| >= %d days):"
          % CUTOFF_DAYS)
    for nm, dd in (("T1/T4/T5  |rest_diff| >= 3", ext),
                   ("T2        one side rest >= 13 (post-bye)", bye),
                   ("T3        both sides rest <= 4 (Thursday)", thu)):
        tr = int((dd["season"] <= TRAIN_HI).sum())
        te = int((dd["season"] >= TEST_LO).sum())
        print("  %-42s total %5d   discovery %4d   holdout %4d"
              % (nm, len(dd), tr, te))

    print("\ncomposition of the |rest_diff| >= 3 bucket (rest_diff -> n):")
    print(ext["rest_diff"].value_counts().sort_index().to_string())
    print("\nhome-rested vs away-rested balance in that bucket: home %d / "
          "away %d  (a lopsided split would let a residual home-ATS bias "
          "leak into the sign-flipped mean -- robustness R1 checks this)"
          % (int((ext["rest_diff"] > 0).sum()),
             int((ext["rest_diff"] < 0).sum())))

    # ------------------------------------------------------------------
    head("1. THE FIVE PRE-REGISTERED TESTS")

    t1 = run_split_test(ext, "rested_ats",
                        "T1 (PRIMARY)  SIDE -- does the RESTED side beat the "
                        "closing spread?   |rest_diff| >= 3, REG", "ats")
    TESTS.append(("T1 side |rd|>=3", t1["HOLDOUT"]["p"], t1))

    t2 = run_split_test(bye, "rested_ats",
                        "T2  SIDE -- post-bye team (rest >= 13) vs non-bye "
                        "opponent, ATS", "ats")
    TESTS.append(("T2 side post-bye", t2["HOLDOUT"]["p"], t2))

    t3 = run_split_test(thu, "tot_resid",
                        "T3  TOTALS -- Thursday games (BOTH teams rest <= 4): "
                        "points minus closing total", "tot")
    TESTS.append(("T3 totals Thursday", t3["HOLDOUT"]["p"], t3))

    t4 = run_split_test(ext, "tot_resid",
                        "T4  TOTALS -- |rest_diff| >= 3: points minus closing "
                        "total", "tot")
    TESTS.append(("T4 totals |rd|>=3", t4["HOLDOUT"]["p"], t4))

    # ---- T5 moneyline -------------------------------------------------
    print("\n%s" % THIN)
    print("T5  MONEYLINE -- rested side vs the no-vig closing price, "
          "|rest_diff| >= 3")
    print(THIN)
    ml = ext.dropna(subset=["home_moneyline", "away_moneyline"]).copy()
    ml = ml[ml["result"] != 0]                      # ties push the ML
    qh = american_to_prob(ml["home_moneyline"])
    qa = american_to_prob(ml["away_moneyline"])
    ovr = qh + qa
    keep = ovr > 0
    ml = ml[keep].copy()
    qh, qa, ovr = qh[keep], qa[keep], ovr[keep]
    p_home = qh / ovr
    home_rested = (ml["rest_diff"] > 0).to_numpy()
    ml["p_rested_novig"] = np.where(home_rested, p_home, 1.0 - p_home)
    ml["rested_won"] = np.where(home_rested,
                                (ml["result"] > 0).to_numpy(),
                                (ml["result"] < 0).to_numpy()).astype(float)
    ml["rested_ml"] = np.where(home_rested, ml["home_moneyline"],
                               ml["away_moneyline"])
    ml["ml_pnl"] = np.where(ml["rested_won"] > 0,
                            american_profit(ml["rested_ml"]), -1.0)
    # calibration residual: realised win minus the no-vig closing probability
    ml["ml_resid"] = ml["rested_won"] - ml["p_rested_novig"]
    print("  moneyline rows available (ties dropped): %d "
          "(discovery %d / holdout %d)"
          % (len(ml), int((ml["season"] <= TRAIN_HI).sum()),
             int((ml["season"] >= TEST_LO).sum())))
    t5 = {}
    for tag, dd in (("DISCOVERY 1999-%d" % TRAIN_HI,
                     ml[ml["season"] <= TRAIN_HI]),
                    ("HOLDOUT   %d-2025" % TEST_LO,
                     ml[ml["season"] >= TEST_LO]),
                    ("(full sample, reference only)", ml)):
        r = clustered_mean_test(dd["ml_resid"], dd["season"], tag)
        roi = clustered_mean_test(dd["ml_pnl"], dd["season"], tag + " roi")
        print("  %-30s" % tag, end="")
        print("n = %-5d  calib resid %+7.4f  cSE %6.4f  p %.4f   |  "
              "flat-stake ROI %+7.4f (cSE %6.4f, p %.4f)"
              % (r["n"], r["mean"], r["se"], r["p"],
                 roi["mean"], roi["se"], roi["p"]))
        t5[tag.split()[0]] = r
        t5[tag.split()[0] + "_roi"] = roi
    m5 = mde(t5["HOLDOUT"].get("sd", np.nan), t5["HOLDOUT"]["n"])
    print("  POWER: holdout SD %.3f, n %d -> 80%%-power MDE = %.4f probability "
          "points" % (t5["HOLDOUT"].get("sd", np.nan), t5["HOLDOUT"]["n"], m5))
    t5["mde"] = m5
    TESTS.append(("T5 moneyline |rd|>=3", t5["HOLDOUT"]["p"], t5))

    # ------------------------------------------------------------------
    head("2. PRE-REGISTERED ROBUSTNESS R1 -- home-bias-adjusted slope")
    print("""Fit  home_ats ~ 1 + rest_diff  on the same subsample, season-clustered.
The intercept absorbs any constant home-ATS tilt; the slope IS the rest effect,
in ATS points per extra day of rest for the home side. If this disagrees in sign
with the sign-flipped mean above, the finding is FRAGILE by pre-registration.""")
    for nm, dd in (("T1 subsample |rest_diff| >= 3", ext),
                   ("T2 subsample post-bye", bye)):
        print("\n  %s" % nm)
        for tag, sub in (("DISCOVERY", dd[dd["season"] <= TRAIN_HI]),
                         ("HOLDOUT  ", dd[dd["season"] >= TEST_LO])):
            X = sm.add_constant(sub["rest_diff"].to_numpy(dtype=float))
            r = sm.OLS(sub["home_ats"].to_numpy(dtype=float), X).fit(
                cov_type="cluster",
                cov_kwds={"groups": sub["season"].to_numpy()})
            print("    %s n=%-5d  intercept %+7.4f (p %.3f)   "
                  "slope_rest_diff %+7.4f (cSE %6.4f, p %.4f)"
                  % (tag, len(sub), r.params[0], r.pvalues[0],
                     r.params[1], r.bse[1], r.pvalues[1]))

    head("3. PRE-REGISTERED ROBUSTNESS R2 -- per-season holdout stability (T1)")
    te = ext[ext["season"] >= TEST_LO]
    s = te.groupby("season").agg(n=("rested_ats", "size"),
                                 mean_ats=("rested_ats", "mean"),
                                 cover=("rested_ats", lambda x: (x > 0).sum()
                                        / max(1, (x != 0).sum())))
    print(s.round(4).to_string())
    print("\nseasons with a POSITIVE holdout mean: %d of %d"
          % (int((s["mean_ats"] > 0).sum()), len(s)))

    # ------------------------------------------------------------------
    head("4. MULTIPLE TESTING -- BH at FDR 10% over the five HOLDOUT p-values")
    names = [t[0] for t in TESTS]
    pv = np.array([t[1] for t in TESTS], dtype=float)
    order = np.argsort(pv)
    ranked = pv[order]
    thresh = 0.10 * (np.arange(1, len(pv) + 1) / len(pv))
    passed = ranked <= thresh
    k = int(np.max(np.nonzero(passed)[0]) + 1) if passed.any() else 0
    rej = np.zeros(len(pv), dtype=bool)
    if k:
        rej[order[:k]] = True
    print(pd.DataFrame({"holdout_p": pv,
                        "raw p<.05": ["YES" if p < 0.05 else "no" for p in pv],
                        "BH q=10%": ["SURVIVES" if r else "rejected"
                                     for r in rej]},
                       index=names).round(5).to_string())

    # ------------------------------------------------------------------
    head("5. VERDICT AGAINST THE PRE-REGISTERED THRESHOLD")
    print("Threshold (fixed in advance): holdout p<.05 AND same sign as "
          "discovery AND survives BH@10%% AND |effect| >= 0.82 ATS points "
          "(the margin needed to clear -110).\n")
    for (nm, p, obj), r in zip(TESTS, rej):
        d = obj["DISCOVERY"]["mean"]
        h = obj["HOLDOUT"]["mean"]
        same = (np.sign(d) == np.sign(h)) and d != 0
        big = abs(h) >= 0.82 if nm.startswith(("T1", "T2", "T3", "T4")) else \
            abs(h) >= 0.0238
        verdict = ("EDGE" if (p < 0.05 and same and r and big)
                   else "no edge")
        print("  %-24s discovery %+7.4f  holdout %+7.4f  p %.4f  "
              "same-sign %-5s  BH %-9s  clears-vig %-5s  -> %s"
              % (nm, d, h, p, same, "SURVIVES" if r else "rejected",
                 big, verdict))
    print("\nMDE at 80%% power on each holdout (the smallest TRUE effect this "
          "test could have found):")
    for nm, p, obj in TESTS:
        print("    %-24s %.4f" % (nm, obj["mde"]))


if __name__ == "__main__":
    main()
