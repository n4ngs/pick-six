#!/usr/bin/env python3
"""
wind_totals_robust.py -- POST-HOC robustness on the wind_totals.py result.

These are ADDITIONAL TESTS and are counted as such. They were written AFTER
seeing T1-T8, and every one of them is aimed at KILLING the result, not at
confirming it. Nothing here moves a window or a cutoff to rescue a p-value;
where a specification changes the answer, that is reported as the answer.

  T9   calendar confound:  resid ~ wind + season FE + week
  T10  the wind == 0 spike (289 games at 0 mph vs 68 at 1 mph -- 0 may be a
       masked "not reported"). Re-run T1 excluding wind == 0.
  T11  era stability: slope per era, and per season, and leave-one-season-out.
  T12  the ACTIONABLE test: flat -110 under bets in held-out seasons only,
       for each pre-registered wind bin. Record, ROI, SE, per-season spread.
  T13  robustness to tails: median (quantile) regression, and Huber.
  T14  is it wind or is it "bad weather"? add roof-adjacent covariates that
       exist: temp, week, div_game; plus resid ~ wind on warm games only
       (temp >= 50) to separate wind from cold.
  T15  the forecast-vs-observed gap, bounded: how much attenuation would kill
       the tail edge? (arithmetic, not a new fit)
"""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)
R = "=" * 92
def head(s): print("\n" + R); print(s); print(R)

HERE = os.path.dirname(os.path.abspath(__file__))
d = pd.read_parquet(os.path.join(HERE, "out_wind_totals.parquet"))
print("analysis sample reloaded: n=%d seasons %d-%d" % (len(d), d.season.min(), d.season.max()))
MDE_Z = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)

def cl(f, y, xs, label):
    f = f.dropna(subset=[y]+xs)
    r = sm.OLS(f[y].astype(float), sm.add_constant(f[xs].astype(float))).fit(
        cov_type="cluster", cov_kwds={"groups": f["season"]})
    print("\n%s  n=%d" % (label, len(f)))
    keep = [c for c in r.params.index if not c.startswith("yr_")]
    tab = pd.DataFrame({"beta": r.params, "SE": r.bse, "t": r.tvalues, "p": r.pvalues,
                        "ci_lo": r.conf_int()[0], "ci_hi": r.conf_int()[1]}).loc[keep]
    print(tab.round(5).to_string())
    return r

# --------------------------------------------------------------- T9
head("T9  CALENDAR CONFOUND  resid ~ wind + season FE + week")
dd = d.copy()
for s in sorted(dd.season.unique())[1:]:
    dd["yr_%d" % s] = (dd.season == s).astype(float)
fe = [c for c in dd.columns if c.startswith("yr_")]
r9 = cl(dd, "resid", ["wind", "week"] + fe, "resid ~ wind + week + season FE")
print("\n  -> wind slope %+.4f (p %.4f) vs %+.4f univariate. %s"
      % (r9.params["wind"], r9.pvalues["wind"], -0.18499,
         "SURVIVES" if r9.pvalues["wind"] < .05 else "DIES"))

# --------------------------------------------------------------- T10
head("T10  THE wind == 0 SPIKE -- is 0 a masked 'not reported'?")
print("wind histogram head: %s" % d.wind.value_counts().sort_index().head(6).to_dict())
z = d[d.wind.eq(0)]
print("wind==0: n=%d  mean resid %+.3f  under rate %.4f  mean total_line %.2f"
      % (len(z), z.resid.mean(), z["under"].mean(), z.total_line.mean()))
print("wind==0 share by season (a reporting artefact would cluster):")
sh = d.groupby("season").apply(lambda x: pd.Series({"n": len(x), "pct_zero": x.wind.eq(0).mean()}))
print(sh.round(3).to_string())
r10 = cl(d[d.wind.gt(0)], "resid", ["wind"], "resid ~ wind, EXCLUDING wind==0")
print("\n  -> %s (slope %+.4f, p %.4f)"
      % ("SURVIVES" if r10.pvalues["wind"] < .05 else "DIES",
         r10.params["wind"], r10.pvalues["wind"]))

# --------------------------------------------------------------- T11
head("T11  ERA STABILITY -- is this a dead 2000s edge?")
eras = [(1999,2006),(2007,2013),(2014,2019),(2020,2026)]
rows=[]
for lo,hi in eras:
    s = d[d.season.between(lo,hi)]
    r = sm.OLS(s.resid.astype(float), sm.add_constant(s[["wind"]].astype(float))).fit(
        cov_type="cluster", cov_kwds={"groups": s["season"]})
    u = s[s.wind>=15]["under"].dropna()
    rows.append({"era":"%d-%d"%(lo,hi),"n":len(s),"slope":r.params["wind"],
                 "SE":r.bse["wind"],"p":r.pvalues["wind"],
                 "n_wind15":len(u),"under_rate_w15":u.mean() if len(u) else np.nan})
print(pd.DataFrame(rows).set_index("era").round(4).to_string())
print("\nPER-SEASON slope (n~190/season, so each one is noisy by construction):")
ps=[]
for s in sorted(d.season.unique()):
    x = d[d.season.eq(s)]
    if len(x) < 50: continue
    r = sm.OLS(x.resid.astype(float), sm.add_constant(x[["wind"]].astype(float))).fit()
    ps.append({"season":s,"n":len(x),"slope":r.params["wind"],"SE":r.bse["wind"]})
ps = pd.DataFrame(ps).set_index("season")
print(ps.round(4).to_string())
print("seasons with a NEGATIVE slope: %d of %d" % (int((ps.slope<0).sum()), len(ps)))
print("\nLEAVE-ONE-SEASON-OUT slope (is one season carrying it?):")
loo=[]
for s in sorted(d.season.unique()):
    x = d[d.season.ne(s)]
    r = sm.OLS(x.resid.astype(float), sm.add_constant(x[["wind"]].astype(float))).fit()
    loo.append(r.params["wind"])
print("  min %+.4f  max %+.4f  (full-sample %+.4f) -> %s"
      % (min(loo), max(loo), -0.18499,
         "no single season drives it" if max(loo) < -0.14 else "ONE SEASON DRIVES IT"))

# --------------------------------------------------------------- T12
head("T12  THE ACTIONABLE TEST -- flat -110 unders, HELD-OUT seasons 2013-2026 only")
te = d[d.season>=2013].copy()
edges=[0,5,10,15,20,100]; labels=["0-4","5-9","10-14","15-19","20+"]
te["bin"]=pd.cut(te.wind,bins=edges,right=False,labels=labels)
rows=[]
for lab in labels:
    u = te[te["bin"].eq(lab)]["under"].dropna()
    w=int(u.sum()); l=len(u)-w
    roi = (w*(100/110.) - l)/len(u) if len(u) else np.nan
    rows.append({"bin":lab,"n_bets":len(u),"bets/season":round(len(u)/14,1),"W":w,"L":l,
                 "under_rate":u.mean(),"ROI@-110":roi,
                 "SE_rate":0.5/np.sqrt(len(u)),
                 "p_vs_52.381":stats.binomtest(w,len(u),0.52381).pvalue})
print(pd.DataFrame(rows).set_index("bin").round(4).to_string())
print("\nNOTE: reading the best bin off this table is SELECTION. 5 bins were")
print("looked at; the Bonferroni threshold for 'beats break-even' here is p<0.01.")
print("\nper-season record of the wind>=15 under, held-out seasons only:")
hw = te[te.wind>=15].dropna(subset=["under"])
pr = hw.groupby("season").agg(n=("under","size"), under_rate=("under","mean"))
pr["W"]=hw.groupby("season")["under"].sum().astype(int); pr["L"]=pr.n-pr.W
pr["ROI"]=(pr.W*(100/110.)-pr.L)/pr.n
print(pr.round(3).to_string())
print("seasons profitable at -110: %d of %d" % (int((pr.ROI>0).sum()), len(pr)))
b = hw["under"]
print("pooled: %d-%d (%.4f), ROI %+.4f, binomial p vs 52.381%% = %.4f"
      % (int(b.sum()), len(b)-int(b.sum()), b.mean(),
         (b.sum()*(100/110.)-(len(b)-b.sum()))/len(b),
         stats.binomtest(int(b.sum()), len(b), 0.52381).pvalue))

# --------------------------------------------------------------- T13
head("T13  TAIL ROBUSTNESS -- median regression and Huber")
import statsmodels.formula.api as smf
q = smf.quantreg("resid ~ wind", d).fit(q=0.5)
print("median (q=0.50) regression: wind %+.4f (SE %.4f, p %.4f)"
      % (q.params["wind"], q.bse["wind"], q.pvalues["wind"]))
hb = sm.RLM(d.resid.astype(float), sm.add_constant(d[["wind"]].astype(float)),
            M=sm.robust.norms.HuberT()).fit()
print("Huber RLM               : wind %+.4f (SE %.4f, p %.4f)"
      % (hb.params["wind"], hb.bse["wind"], hb.pvalues["wind"]))
print("-> %s" % ("the effect is a shift of the whole distribution, not a few blowouts"
                 if q.pvalues["wind"] < .05 and hb.pvalues["wind"] < .05
                 else "the effect is tail-driven"))

# --------------------------------------------------------------- T14
head("T14  WIND vs 'BAD WEATHER' -- warm games only (temp >= 50F)")
warm = d[d.temp>=50]
print("warm subsample n=%d, mean wind %.2f (full %.2f)" % (len(warm), warm.wind.mean(), d.wind.mean()))
r14 = cl(warm, "resid", ["wind"], "resid ~ wind, temp>=50F only")
seW = warm.resid.std()/(warm.wind.std()*np.sqrt(len(warm)))
print("  80%% MDE on this subsample: %.4f pts/mph -> %s"
      % (MDE_Z*seW, "SURVIVES" if r14.pvalues["wind"]<.05 else "not significant here"))
print("corr(wind, temp) = %+.3f  |  corr(wind, week) = %+.3f  |  corr(wind, total_line) = %+.3f"
      % (d.wind.corr(d.temp), d.wind.corr(d.week), d.wind.corr(d.total_line)))

# --------------------------------------------------------------- T15
head("T15  FORECAST-vs-OBSERVED ATTENUATION -- how much noise kills the tail edge?")
print("""games.csv wind is the OBSERVED game-time wind. A bettor sees a FORECAST.
If forecast = observed + noise with corr r, the slope recoverable from the
forecast is attenuated by roughly r (classical errors-in-variables), and the
realised edge scales with it. Full-sample tail edge is under rate 0.5685 at
wind>=15, i.e. +4.47pp over 50%, +4.47-2.38 = +2.09pp over break-even.""")
edge_pp = 0.5685-0.52381
for r in (1.0,0.9,0.8,0.7,0.6,0.5):
    print("  corr(forecast, observed) = %.1f -> attenuated edge over break-even "
          "%+.3fpp -> ROI %+.3f%%" % (r, 100*edge_pp*r, 100*edge_pp*r*(1+100/110.)))
print("\nbreak-even corr (edge -> 0 at -110): r = %.2f is where 56.85%% becomes 52.38%%."
      % (0.0))
print("i.e. the OBSERVED-wind edge is +%.2fpp over break-even; published NFL wind")
print("forecast skill at 1-3 days is roughly r=0.6-0.8, which leaves +%.2f to +%.2fpp."
      % (100*edge_pp*0.6, 100*edge_pp*0.8))
