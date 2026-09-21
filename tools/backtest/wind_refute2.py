#!/usr/bin/env python3
"""
wind_refute2.py -- continuation. Pre-registered BEFORE running.

R9  THE PRACTICAL TEST the agent did with arithmetic instead of data.
    Their T15 attenuation was done as "multiply the edge by r". That is wrong
    for a SELECTION rule: if you select on a noisy FORECAST rather than on the
    realised reading, the selected games' realised wind shrinks toward the
    mean, so the edge falls faster than linearly. Do it properly by
    simulation: build f = w + u with var(u) set so corr(f,w) = r exactly,
    select on f (both the >=15 tail rule and the frozen-regression rule),
    and read the REALISED under rate of the selected games. Held-out seasons
    2013-2026 only. 400 noise draws per r. r grid fixed here: 1.0 .. 0.4.
    Threshold: the rule must clear 52.381% at p<0.05 to be an edge.
R10 REAL PRICES on the held-out tail, plus the multiple-comparison charge for
    having looked at 5 bins.
R11 Placebo: the same pipeline on an outcome wind cannot cause -- the SPREAD
    residual (|result - spread_line| has no directional wind story; I use the
    home-margin residual). A significant wind slope there would indicate the
    residual construction is picking up something generic.
R12 Does the effect concentrate where the market is WORST informed? Split by
    whether under_odds exists (post-2006 pricing era). Already partly in R5.
    Here: slope by decade, with the MDE for each, to say "unknown" vs "no".
"""
import os, sys, warnings
sys.path.insert(0, "/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore"); pd.set_option("display.width", 200)
R = "=" * 92
def head(s): print("\n" + R); print(s); print(R)
d = pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_wind_totals.parquet")
MDE_Z = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)

# ----------------------------------------------------------------- R9
head("R9  FORECAST-SKILL SIMULATION -- select on a NOISY forecast, not the reading")
te = d[d.season >= 2013].dropna(subset=["under"]).copy()
w = te.wind.to_numpy(float); u = te["under"].to_numpy(float)
sdw = w.std()
rng = np.random.default_rng(99)
print("held-out sample 2013-2026: n=%d, sd(wind)=%.2f" % (len(te), sdw))
print("\nRULE A: bet UNDER when the FORECAST >= 15 mph (their pre-registered tail)")
print("  r     bets/season   under rate    ROI@-110    p vs 52.381%")
for r in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
    sd_u = sdw*np.sqrt(1-r*r)/r if r < 1 else 0.0
    rates, ns = [], []
    for _ in range(400):
        f = w + rng.normal(0, sd_u, len(w)) if sd_u > 0 else w
        sel = f >= 15
        if sel.sum() < 10: continue
        rates.append(u[sel].mean()); ns.append(sel.sum())
    rate = float(np.mean(rates)); n = float(np.mean(ns))
    roi = rate*(100/110.) - (1-rate)
    p = stats.binomtest(int(round(rate*n)), int(round(n)), 0.52381).pvalue
    print("  %.1f     %6.1f       %.4f      %+.4f     %.4f  %s"
          % (r, n/14, rate, roi, p, "clears" if p < .05 and rate > .52381 else "no"))
print("\nRULE B: frozen regression trained 1999-2012 on REALISED wind, applied to")
print("        the FORECAST at bet time; bet under when pred<0. Both legs.")
tr = d[d.season <= 2012]
rt = sm.OLS(tr.resid, sm.add_constant(tr[["wind"]].astype(float))).fit()
a0, b0 = rt.params["const"], rt.params["wind"]
print("  r     bets    win rate    ROI@-110    p vs 52.381%")
for r in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
    sd_u = sdw*np.sqrt(1-r*r)/r if r < 1 else 0.0
    wins, ns = [], []
    for _ in range(400):
        f = w + rng.normal(0, sd_u, len(w)) if sd_u > 0 else w
        side_under = (a0 + b0*f) < 0
        win = np.where(side_under, u == 1, u == 0)
        wins.append(win.mean()); ns.append(len(win))
    rate = float(np.mean(wins)); n = int(np.mean(ns))
    roi = rate*(100/110.) - (1-rate)
    p = stats.binomtest(int(round(rate*n)), n, 0.52381).pvalue
    print("  %.1f    %5d    %.4f      %+.4f     %.4f  %s"
          % (r, n, rate, roi, p, "clears" if p < .05 and rate > .52381 else "no"))

# ----------------------------------------------------------------- R10
head("R10  REAL CLOSING PRICES + THE MULTIPLICITY CHARGE")
sub = te[te.wind >= 15]
print("held-out wind>=15: n=%d  under rate %.4f" % (len(sub), sub["under"].mean()))
print("  binomial p vs 52.381%% break-even = %.4f"
      % stats.binomtest(int(sub["under"].sum()), len(sub), 0.52381).pvalue)
print("  Bonferroni over the 5 pre-registered bins -> threshold p<0.01. %s"
      % ("still clears" if stats.binomtest(int(sub["under"].sum()), len(sub), 0.52381).pvalue < .01
         else "DOES NOT CLEAR"))
uo = sub["under_odds"]
print("\nunder_odds present on held-out tail: %d/%d, median %.0f" % (uo.notna().sum(), len(sub), uo.median()))
s2 = sub[uo.notna()]
pay = np.where(s2["under"] == 1, 100/np.abs(s2["under_odds"].astype(float)), -1.0)
print("  real-price ROI %+.4f on n=%d  (se %.4f) -> t %.2f, p %.4f"
      % (pay.mean(), len(pay), pay.std()/np.sqrt(len(pay)),
         pay.mean()/(pay.std()/np.sqrt(len(pay))),
         2*(1-stats.norm.cdf(abs(pay.mean()/(pay.std()/np.sqrt(len(pay))))))))
print("  NOTE: this still uses the REALISED reading to pick the bet.")

# ----------------------------------------------------------------- R11
head("R11  PLACEBO -- does wind 'predict' an outcome it has no directional story for?")
d2 = d.copy()
d2["margin_resid"] = (d2.home_score - d2.away_score) - d2.spread_line
for y, lab in [("margin_resid", "home-margin residual vs spread (PLACEBO)"),
               ("resid", "total residual (the real test)")]:
    f = d2.dropna(subset=[y])
    r = sm.OLS(f[y].astype(float), sm.add_constant(f[["wind"]].astype(float))).fit(
        cov_type="cluster", cov_kwds={"groups": f.season})
    print("  %-42s wind %+.4f (SE %.4f, p %.4f)"
          % (lab, r.params["wind"], r.bse["wind"], r.pvalues["wind"]))
print("  -> a null placebo means the residual construction is not generically noisy.")

# ----------------------------------------------------------------- R12
head("R12  SLOPE BY DECADE WITH POWER -- 'unknown' vs 'no'")
rows = []
for lo, hi in [(1999, 2005), (2006, 2012), (2013, 2019), (2020, 2026)]:
    s = d[d.season.between(lo, hi)]
    r = sm.OLS(s.resid, sm.add_constant(s[["wind"]].astype(float))).fit(
        cov_type="cluster", cov_kwds={"groups": s.season})
    mde = MDE_Z*s.resid.std()/(s.wind.std()*np.sqrt(len(s)))
    rows.append({"era": "%d-%d" % (lo, hi), "n": len(s), "slope": r.params["wind"],
                 "SE": r.bse["wind"], "p": r.pvalues["wind"], "MDE80": mde,
                 "verdict": "SIG" if r.pvalues["wind"] < .05 else
                            ("null" if abs(r.params["wind"]) < mde else "unknown")})
print(pd.DataFrame(rows).set_index("era").round(4).to_string())
