#!/usr/bin/env python3
"""
fit_full_checks.py -- POST-HOC robustness checks on the ONE result that changed
when the sample grew from 1812 to 4886 games: Vector P (p_qb_z).

THESE ARE POST-HOC. They were NOT pre-registered. They are run because the
pre-registered run produced a survivor, and a survivor has to be attacked
before it is believed. Every one of them is reported, pass or fail.

  V1  OFFSET-MISSCALING ARTIFACT. corr(P, logit(p_mkt)) = +0.699 and the free
      coefficient on logit(p_mkt) is 0.963, not 1. Pinning a mis-scaled offset
      to 1 can manufacture a coefficient on anything correlated with it.
      Test: refit the 4 vectors with logit(p_mkt) as a FREE regressor.
      Kill criterion: B_P loses significance.

  V2  IS IT P, OR IS IT THE OTHER THREE? The 4-term model LOSES to the closing
      line out of sample (d_ll = -0.00116). Test P alone, same offset spec,
      same expanding-window CV. Reports in-sample B_P, out-of-sample gamma_P,
      and whether a P-only model beats the closing price.

  V3  ERA STABILITY. 2006-2012 moneylines are thinner and softer than 2019+.
      Test: gamma_P on held-out games split into 2008-2015 and 2016-2025.
      Kill criterion: the effect lives only in the old, soft era.

  V4  LEAKAGE RE-CHECK on the widened sample: does p_qb_z correlate with the
      ATS residual (result - spread_line), and is the sign consistent with a
      real unpriced effect rather than a look-ahead?

Writes nothing outside tools/backtest/.
"""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, statsmodels.api as sm
import fit as FIT
from fit import glm_fit, logit, sigmoid, logloss, brier, season_cv, \
    oos_significance, head, RULE, THIN, VECTORS, VECTOR_COL

warnings.filterwarnings("ignore")
pd.set_option("display.width", 190)
HERE = os.path.dirname(os.path.abspath(__file__))

FIT.FIT_LO, FIT.FIT_HI = 2006, 2025
FIT.CV_TEST_SEASONS = list(range(2008, 2026))

d = pd.read_parquet(os.path.join(HERE, "out_full_fit_table.parquet"))
cols = [VECTOR_COL[v] for v in VECTORS]
off = logit(d["p_mkt_mult"].to_numpy())
y = d["home_win"].to_numpy(float)
print(RULE); print("POST-HOC CHECKS ON VECTOR P   n=%d  seasons %d-%d"
                   % (len(d), d.season.min(), d.season.max())); print(RULE)

# ---------------- V1 ----------------
head("V1 -- IS B_P AN OFFSET-MISSCALING ARTIFACT?")
print("corr(p_qb_z, logit(p_mkt)) = %+.3f  <- the reason to worry\n"
      % np.corrcoef(d["p_qb_z"], off)[0, 1])
Xf = pd.DataFrame({"logit_p_mkt": off}, index=d.index)
for c in cols:
    Xf[c] = d[c].to_numpy(float)
free = sm.GLM(y, Xf, family=sm.families.Binomial()).fit()
print(free.summary().as_text())
pin = glm_fit(d, cols, intercept=False, label="pinned")
print("\n%-12s %12s %12s %10s | %12s %12s %10s"
      % ("term", "B pinned", "SE", "p", "B free-off", "SE", "p"))
for c in cols:
    print("%-12s %+12.5f %12.5f %10.4f | %+12.5f %12.5f %10.4f"
          % (c, pin.params[c], pin.bse[c], pin.pvalues[c],
             free.params[c], free.bse[c], free.pvalues[c]))
print("\nlogit_p_mkt free coefficient = %.4f (SE %.4f)"
      % (free.params["logit_p_mkt"], free.bse["logit_p_mkt"]))
print("RESULT: B_P %s when the offset is freed."
      % ("SURVIVES" if free.pvalues["p_qb_z"] < 0.05 else "DIES"))

# ---------------- V2 ----------------
head("V2 -- P ALONE (1-term offset model), same expanding-window CV")
solo = glm_fit(d, ["p_qb_z"], intercept=False, label="P only")
lo, hi = solo.conf_int().iloc[0]
print("IN SAMPLE: B_P = %+.5f  SE %.5f  z %+.2f  p %.5f  95%% CI [%+.4f, %+.4f]"
      % (solo.params["p_qb_z"], solo.bse["p_qb_z"], solo.tvalues["p_qb_z"],
         solo.pvalues["p_qb_z"], lo, hi))
fl1, oos1 = season_cv(d, cols=["p_qb_z"], names=["P"], banner=False)
g1, gD1 = oos_significance(oos1, names=["P"], banner=False)

# ---------------- V3 ----------------
head("V3 -- ERA STABILITY of gamma_P (held-out games only)")
for lo_s, hi_s, lab in ((2008, 2015, "old/soft era"), (2016, 2025, "modern era")):
    sub = oos1[oos1["season"].between(lo_s, hi_s)]
    X = pd.DataFrame({"gamma_P": sub["contrib_P"].to_numpy()}, index=sub.index)
    r = sm.GLM(sub["home_win"].to_numpy(float), X, family=sm.families.Binomial(),
               offset=logit(sub["p_mkt_mult"].to_numpy())).fit()
    l, h = r.conf_int().iloc[0]
    yy = sub["home_win"].to_numpy()
    dll = logloss(yy, sub["p_mkt_mult"].to_numpy()) - logloss(yy, sub["p_model_oos"].to_numpy())
    print("  %-14s %d-%d  n=%4d  gamma_P %+.4f (SE %.4f, p %.4f, CI [%+.3f, %+.3f])"
          "  d_ll %+0.6f"
          % (lab, lo_s, hi_s, len(sub), r.params.iloc[0], r.bse.iloc[0],
             r.pvalues.iloc[0], l, h, dll))

# ---------------- V4 ----------------
head("V4 -- ATS-RESIDUAL / LEAKAGE RE-CHECK on the widened sample")
dd = d.dropna(subset=["spread_line", "result"]).copy()
resid = dd["result"] - dd["spread_line"]
for lab, a, b in (("p_qb_z vs spread_line (what the market priced)",
                   dd["p_qb_z"], dd["spread_line"]),
                  ("p_qb_z vs result", dd["p_qb_z"], dd["result"]),
                  ("p_qb_z vs (result - spread_line)  <- the unpriced part",
                   dd["p_qb_z"], resid)):
    r = np.corrcoef(a, b)[0, 1]
    n = len(dd); se = 1/np.sqrt(n-3); z = 0.5*np.log((1+r)/(1-r))
    print("  %-52s %+0.4f  95%% CI [%+0.4f, %+0.4f]  n=%d"
          % (lab, r, np.tanh(z-1.96*se), np.tanh(z+1.96*se), n))
print("\n  A correlation with the ATS residual that is small but POSITIVE and")
print("  whose CI excludes zero is what a genuine unpriced effect looks like.")
print("  A large one would be evidence of LEAKAGE, not of an edge.")
