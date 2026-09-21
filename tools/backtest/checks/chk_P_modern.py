import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_full_fit_table.parquet").reset_index(drop=True)
def lg(p): p=np.clip(np.asarray(p,float),1e-9,1-1e-9); return np.log(p/(1-p))
def sg(x): return 1/(1+np.exp(-x))
def ll(y,p): p=np.clip(p,1e-9,1-1e-9); return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

COLS=["p_qb_z"]
pieces=[]
for s in range(2008,2026):
    tr=d[d.season<s]; te=d[d.season==s]
    if len(tr)<200 or len(te)==0: continue
    r=sm.GLM(tr.home_win.to_numpy(float),tr[COLS],family=sm.families.Binomial(),offset=lg(tr.p_mkt_mult)).fit()
    b=r.params.reindex(COLS).to_numpy(float)
    off=lg(te.p_mkt_mult); D=te[COLS].to_numpy(float).dot(b)
    p=te[["season","home_win","p_mkt_mult","home_moneyline","away_moneyline","hold"]].copy()
    p["D"]=D; p["p_model"]=sg(off+D); p["contrib_p_qb_z"]=D
    pieces.append(p)
o=pd.concat(pieces,ignore_index=True)

print("=== P-ONLY model, out of sample, by WINDOW OF HELD-OUT SEASONS ===")
print("%-28s %6s %10s %10s %11s %26s"%("held-out window","n","ll_mkt","ll_model","d_ll","gamma_P (SE, p)"))
for lo,hi in [(2008,2025),(2008,2015),(2016,2025),(2019,2025),(2021,2025),(2023,2025)]:
    m=(o.season>=lo)&(o.season<=hi); g=o[m]
    y=g.home_win.to_numpy(float)
    off=lg(g.p_mkt_mult)
    r=sm.GLM(y,pd.DataFrame({"gamma_P":g.contrib_p_qb_z.to_numpy()}),family=sm.families.Binomial(),offset=off).fit()
    a=ll(y,g.p_mkt_mult.to_numpy()); b=ll(y,g.p_model.to_numpy())
    # paired bootstrap on d_ll
    pm=np.clip(g.p_mkt_mult.to_numpy(),1e-9,1-1e-9); pp=np.clip(g.p_model.to_numpy(),1e-9,1-1e-9)
    diff=(-(y*np.log(pm)+(1-y)*np.log(1-pm)))-(-(y*np.log(pp)+(1-y)*np.log(1-pp)))
    rng=np.random.default_rng(1); idx=rng.integers(0,len(diff),size=(3000,len(diff)))
    lo_ci,hi_ci=np.percentile(diff[idx].mean(axis=1),[2.5,97.5])
    print("%-28s %6d %10.6f %10.6f %+11.6f   %+0.3f (%.3f, p=%.4f)  d_ll CI [%+.5f,%+.5f]"
          %("%d-%d"%(lo,hi),len(g),a,b,a-b,r.params.iloc[0],r.bse.iloc[0],r.pvalues.iloc[0],lo_ci,hi_ci))

print("""
Read the 2019-2025 and 2021-2025 rows: those are the seasons whose moneyline
market resembles the one the live app would bet into (two-way hold 2.8-4.3%,
vs 1.7-2.5% in 2006-2015).""")

print("\n=== would a BETTOR have made money on P-only, modern window? ===")
def ad(ml):
    ml=np.asarray(ml,float); return np.where(ml>0,1+ml/100.0,1+100.0/np.abs(ml))
rows=[]
for side,sign,c in (("home",1.0,"home_moneyline"),("away",-1.0,"away_moneyline")):
    x=o.copy(); x["dec"]=ad(o[c]); x["u"]=sign*(lg(o.p_mkt_mult)+o.D)
    x["p"]=sg(x.u); x["won"]=(o.home_win==(1 if side=="home" else 0)).astype(int)
    x["EV"]=x.p*x.dec-1.0; rows.append(x)
cand=pd.concat(rows,ignore_index=True)
for lo,hi in [(2008,2025),(2019,2025),(2021,2025)]:
    g=cand[(cand.season>=lo)&(cand.season<=hi)&(cand.EV>0)]
    r=np.where(g.won==1,g.dec-1.0,-1.0)
    t=stats.ttest_1samp(r,0.0)
    print("  %s  EV>0 bets n=%4d  hit %.4f  flat ROI %+0.4f  units %+.1f  p=%.3f"
          %("%d-%d"%(lo,hi),len(r),g.won.mean(),r.mean(),r.sum(),t.pvalue))

print("\n=== multiplicity across fit_full.py's OWN 10 DECLARED TESTS ===")
p10=[0.13129,0.00210,0.86786,0.10982,  # T1 F,P,C,R
     0.1006,0.0249,0.6492,0.1393,      # T2 gamma F,P,C,R
     0.0972,                            # T3 gamma_D
     0.50]                              # T4 bootstrap CI contains 0 -> ns
p=np.array(sorted(p10)); n=len(p)
thr=0.10*np.arange(1,n+1)/n
k=np.max(np.nonzero(p<=thr)[0])+1 if (p<=thr).any() else 0
print("  sorted p: %s"%np.round(p,4).tolist())
print("  BH q=10%% thresholds: %s"%np.round(thr,4).tolist())
print("  -> BH rejects the smallest %d p-value(s): %s"%(k,p[:k].tolist()))
print("  fit_full.py applied BH to ONLY the 4 T1 coefficients, not to all 10 declared tests.")
print("  Across all 10, T1 B_P (p=0.0021) survives but T2 gamma_P (p=0.0249) does NOT.")
