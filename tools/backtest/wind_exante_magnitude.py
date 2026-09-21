#!/usr/bin/env python3
"""
wind_exante_magnitude.py -- ADDENDUM to wind_data_validity.py.

These are ADDITIONAL TESTS (D10, D11, D12) written AFTER seeing D1-D9. They are
counted as tests and reported whatever they say. Nothing below moves a window,
cutoff or filter that was already fixed: the climatology construction, the
2004+ start and the 1999-2012 / 2013-2026 split are carried over UNCHANGED
from the pre-registration in wind_data_validity.py.

D10 ARITHMETIC, not a fit. Convert the ex-ante-knowable wind mispricing into
    (a) points of total and (b) win probability on a -110 total, and compare
    with the 52.381% break-even. Uses the D7a coefficient as given, including
    its insignificance, and also its upper confidence bound as a best case.
D11 SHAPE, the ex-ante mirror of the original T4. The original showed the
    under rate rising monotonically across bins of REALISED wind. Does it rise
    across bins of EX-ANTE climatological wind -- the only version a bettor can
    act on? Pre-registered here: quartiles of w_hat (fixed, not tuned),
    Cochran-Armitage trend test, threshold p < 0.05.
D12 OUT-OF-SAMPLE version of D11: test seasons 2013-2026 only, quartile edges
    frozen from the 2004-2012 train half.
"""
import os, sys, warnings
sys.path.insert(0, "/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore"); pd.set_option("display.width", 200)
R = "=" * 92
def head(s): print("\n" + R); print(s); print(R)
MDE_Z = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)
DATA = "/Users/cmanlongat/Projects/pick-six/data/nflverse"

g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
d = g[g.roof.eq("outdoors") & g.total_line.notna() & g.total.notna()
      & g.wind.notna() & g.wind.lt(50)].copy()
d["resid"] = (d.home_score + d.away_score) - d.total_line
d["under"] = np.where(d.home_score + d.away_score < d.total_line, 1.0,
              np.where(d.home_score + d.away_score > d.total_line, 0.0, np.nan))
d["month"] = pd.to_datetime(d.gameday).dt.month
d = d.sort_values(["season", "week"]).reset_index(drop=True)
hist = d[["season", "stadium_id", "month", "wind"]]
wh = []
for _, r0 in d.iterrows():
    h = hist[(hist.season < r0.season) & (hist.stadium_id == r0.stadium_id)]
    hm = h[h.month == r0.month]
    wh.append(hm.wind.mean() if len(hm) >= 5 else (h.wind.mean() if len(h) >= 10 else np.nan))
d["w_hat"] = wh
s7 = d[(d.season >= 2004) & d.w_hat.notna()].copy()
s7["dev"] = s7.wind - s7.w_hat

head("D10  WHAT IS THE EX-ANTE-KNOWABLE WIND MISPRICING ACTUALLY WORTH?")
r = sm.OLS(s7.resid.astype(float), sm.add_constant(s7[["w_hat", "dev"]].astype(float))).fit(
    cov_type="cluster", cov_kwds={"groups": s7.season})
b, se = r.params["w_hat"], r.bse["w_hat"]
lo, hi = r.conf_int().loc["w_hat"]
sd_wh, sd_res = s7.w_hat.std(), s7.resid.std()
print("residual slope on EX-ANTE wind      : %+.4f pts/mph (SE %.4f, p %.4f, CI [%+.3f, %+.3f])"
      % (b, se, r.pvalues["w_hat"], lo, hi))
print("sd of ex-ante wind across games     : %.2f mph   (sd of REALISED wind: %.2f mph)"
      % (sd_wh, s7.wind.std()))
print("sd of the total residual            : %.2f points" % sd_res)
print("full ex-ante spread, p5 to p95      : %.2f mph (%.2f .. %.2f)"
      % (s7.w_hat.quantile(.95) - s7.w_hat.quantile(.05),
         s7.w_hat.quantile(.05), s7.w_hat.quantile(.95)))
print("\nedge in POINTS of total:")
for lab, coef in [("point estimate", b), ("95%% CI best case", lo), ("95%% CI worst case", hi)]:
    print("  %-20s 1-sd swing in ex-ante wind = %+.3f pts | p5->p95 swing = %+.3f pts"
          % (lab, coef*sd_wh, coef*(s7.w_hat.quantile(.95)-s7.w_hat.quantile(.05))))
print("\nedge in WIN PROBABILITY on a -110 total (normal approx, phi(0)*edge/sd_resid):")
print("  break-even at -110 = 52.381%%, i.e. you must move the under rate +2.381pp")
for lab, coef in [("point estimate", b), ("95% CI best case", lo)]:
    for k, swing in [("1 sd", sd_wh), ("p5->p95", s7.w_hat.quantile(.95)-s7.w_hat.quantile(.05))]:
        pp = 100*stats.norm.pdf(0)*abs(coef)*swing/sd_res
        print("  %-18s %-8s -> %+.2f pp of win rate  %s"
              % (lab, k, pp, "CLEARS VIG" if pp > 2.381 else "does NOT clear vig"))
print("\ncompare: the SAME arithmetic on the REALISED-wind slope the claim headlines")
rr = sm.OLS(d.resid.astype(float), sm.add_constant(d[["wind"]].astype(float))).fit()
pp = 100*stats.norm.pdf(0)*abs(rr.params["wind"])*(d.wind.quantile(.95)-d.wind.quantile(.05))/d.resid.std()
print("  realised slope %+.4f over a p5->p95 swing of %.1f mph -> %+.2f pp  (but %.0f%% of that"
      % (rr.params["wind"], d.wind.quantile(.95)-d.wind.quantile(.05), pp,
         100*(1-s7.w_hat.var()/s7.wind.var())))
print("   wind variance was NOT knowable when the bet had to be placed)")

head("D11  EX-ANTE SHAPE -- does the under rate rise with KNOWABLE wind? (mirror of T4)")
q = s7.dropna(subset=["under"]).copy()
q["qt"] = pd.qcut(q.w_hat, 4, labels=["Q1 calmest", "Q2", "Q3", "Q4 windiest"])
tab = q.groupby("qt").agg(n=("under", "size"), under_rate=("under", "mean"),
                          mean_w_hat=("w_hat", "mean"), mean_wind=("wind", "mean"),
                          mean_resid=("resid", "mean"), mean_total_line=("total_line", "mean"))
tab["se_under"] = 0.5/np.sqrt(tab.n)
print(tab.round(4).to_string())
codes = q.qt.cat.codes.to_numpy(float); ub = q.under.to_numpy()
pbar = ub.mean()
z = np.sum((codes-codes.mean())*(ub-pbar))/np.sqrt(pbar*(1-pbar)*np.sum((codes-codes.mean())**2))
pval = 2*(1-stats.norm.cdf(abs(z)))
print("\nCochran-Armitage trend across EX-ANTE quartiles: z = %+.3f, p = %.4f -> %s"
      % (z, pval, "TREND" if pval < .05 else "NO TREND"))
print("  (the original T4 on REALISED wind: z = +3.66, p = 0.0003)")
print("  80%%-power MDE on a quartile's under rate: %.4f (n=%d per quartile)"
      % (MDE_Z*0.5/np.sqrt(tab.n.mean()), int(tab.n.mean())))
print("  Q4-minus-Q1 under rate: %+.4f (SE %.4f) -> %s"
      % (tab.under_rate.iloc[-1]-tab.under_rate.iloc[0],
         np.sqrt(tab.se_under.iloc[-1]**2+tab.se_under.iloc[0]**2),
         "break-even needs +0.0238 over 50%"))

head("D12  D11 OUT OF SAMPLE -- quartile edges frozen on 2004-2012, scored on 2013-2026")
tr = s7[s7.season <= 2012]; te = s7[s7.season >= 2013].dropna(subset=["under"]).copy()
edges = np.quantile(tr.w_hat, [0, .25, .5, .75, 1.0]); edges[0] -= 1e-9; edges[-1] += 1e9
print("frozen edges from TRAIN: %s" % np.round(edges[1:-1], 3))
te["qt"] = pd.cut(te.w_hat, bins=edges, labels=["Q1", "Q2", "Q3", "Q4"])
t2 = te.groupby("qt").agg(n=("under", "size"), under_rate=("under", "mean"),
                          mean_w_hat=("w_hat", "mean"), mean_resid=("resid", "mean"))
t2["se"] = 0.5/np.sqrt(t2.n)
print(t2.round(4).to_string())
c2 = te.qt.cat.codes.to_numpy(float); u2 = te.under.to_numpy(); pb2 = u2.mean()
z2 = np.sum((c2-c2.mean())*(u2-pb2))/np.sqrt(pb2*(1-pb2)*np.sum((c2-c2.mean())**2))
p2 = 2*(1-stats.norm.cdf(abs(z2)))
print("\nOOS Cochran-Armitage: z = %+.3f, p = %.4f -> %s" % (z2, p2, "TREND" if p2 < .05 else "NO TREND"))
bt = stats.binomtest(int(te[te.qt.eq("Q4")].under.sum()), len(te[te.qt.eq("Q4")]), 0.52381)
n4 = len(te[te.qt.eq("Q4")])
print("OOS windiest-quartile under rate %.4f on %d bets; vs -110 break-even p=%.4f -> %s"
      % (te[te.qt.eq("Q4")].under.mean(), n4, bt.pvalue,
         "beats vig" if te[te.qt.eq('Q4')].under.mean() > 0.52381 and bt.pvalue < .05 else "does NOT beat vig"))
print("80%%-power MDE on that rate: %.4f (detectable from %.2f%%)"
      % (MDE_Z*0.5/np.sqrt(n4), 100*(0.5+MDE_Z*0.5/np.sqrt(n4))))
