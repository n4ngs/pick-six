import os,sys,warnings
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore"); pd.set_option("display.width",200)
d = pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_wind_totals.parquet")
MDE_Z = stats.norm.ppf(0.975)+stats.norm.ppf(0.80)

print("="*92); print("T9 (rerun, header only)  resid ~ wind + week + season FE"); print("="*92)
dd=d.copy()
for s in sorted(dd.season.unique())[1:]: dd["yr_%d"%s]=(dd.season==s).astype(float)
fe=[c for c in dd.columns if c.startswith("yr_")]
r9=sm.OLS(dd.resid.astype(float), sm.add_constant(dd[["wind","week"]+fe].astype(float))).fit(
    cov_type="cluster",cov_kwds={"groups":dd.season})
print(pd.DataFrame({"beta":r9.params,"SE":r9.bse,"t":r9.tvalues,"p":r9.pvalues}).loc[["const","wind","week"]].round(5).to_string())

print("\n"+"="*92); print("T15 (CORRECTED ARITHMETIC) forecast attenuation"); print("="*92)
raw = 0.5685-0.50
print("observed-wind under rate at wind>=15 (full sample) = 0.5685 -> %.2fpp over 50%%"%(100*raw))
print("break-even at -110 = 52.381%% (need +2.381pp over 50%%)")
for r in (1.0,0.9,0.8,0.7,0.6,0.5,0.4,0.35):
    rate=0.50+raw*r
    roi=(rate*(100/110.)-(1-rate))
    print("  corr(forecast,observed)=%.2f -> rate %.4f  ROI@-110 %+.3f%%  %s"
          %(r,rate,100*roi,"profitable" if rate>0.52381 else "UNPROFITABLE"))
print("break-even attenuation r = 2.381/%.2f = %.2f"%(100*raw, 0.02381/raw))

print("\n"+"="*92)
print("T16  THE POWERFUL ACTIONABLE TEST -- expanding-window OOS, no threshold knob")
print("="*92)
print("""Rule fixed by the TRAINING data alone, no tuning: fit resid ~ a + b*wind on
all seasons strictly before season s; in season s bet UNDER when the frozen
prediction is < 0 and OVER when it is > 0. Flat stake, -110 both sides.""")
pieces=[]
for s in range(2005,int(d.season.max())+1):
    tr=d[d.season<s]; te=d[d.season==s]
    if len(tr)<300 or len(te)==0: continue
    r=sm.OLS(tr.resid.astype(float),sm.add_constant(tr[["wind"]].astype(float))).fit()
    p=te.copy(); p["pred"]=r.params["const"]+r.params["wind"]*p["wind"]
    p["cross"]=-r.params["const"]/r.params["wind"]
    pieces.append(p)
o=pd.concat(pieces,ignore_index=True).dropna(subset=["under"])
print("\nthe learned crossover wind (where the frozen model flips over->under), by fold:")
print("  min %.2f mph  max %.2f mph  median %.2f mph"%(o.cross.min(),o.cross.max(),o.cross.median()))
o["side_under"]=o["pred"]<0
o["win"]=np.where(o.side_under, o["under"]==1, o["under"]==0)
def rec(x,name):
    n=len(x); w=int(x.win.sum()); l=n-w
    rate=w/n; roi=(w*(100/110.)-l)/n
    p=stats.binomtest(w,n,0.52381).pvalue
    p50=stats.binomtest(w,n,0.5).pvalue
    print("\n%s: %d-%d on %d bets (%.4f)  ROI@-110 %+.4f"%(name,w,l,n,rate,roi))
    print("   p vs 50%%    = %.4f"%p50)
    print("   p vs 52.381%% (break-even) = %.4f  -> %s"%(p,"BEATS VIG" if p<.05 and rate>0.52381 else "does NOT clear vig significantly"))
    print("   80%% MDE: %.4f (detectable from %.2f%%)"%(MDE_Z*0.5/np.sqrt(n),100*(0.5+MDE_Z*0.5/np.sqrt(n))))
    return rate,roi,n
rec(o,"BOTH SIDES (over+under)")
rec(o[o.side_under],"UNDER side only")
rec(o[~o.side_under],"OVER side only")
print("\nper-season, both sides:")
g=o.groupby("season").agg(n=("win","size"),wins=("win","sum"))
g["rate"]=g.wins/g.n; g["ROI"]=(g.wins*(100/110.)-(g.n-g.wins))/g.n
print(g.round(3).to_string())
print("profitable seasons: %d of %d"%(int((g.ROI>0).sum()),len(g)))
diff=(o.win.astype(float)*(100/110.)-(1-o.win.astype(float))).to_numpy()
rng=np.random.default_rng(20260920); seasons=sorted(o.season.unique())
by=[diff[o.season.to_numpy()==s] for s in seasons]
bs=np.array([np.concatenate([by[j] for j in rng.integers(0,len(seasons),len(seasons))]).mean() for _ in range(4000)])
print("season-block bootstrap on per-bet ROI: mean %+.4f  95%% CI [%+.4f, %+.4f] -> %s"
      %(diff.mean(),*np.percentile(bs,[2.5,97.5]),
        "excludes 0" if np.percentile(bs,2.5)>0 else "CONTAINS 0"))
