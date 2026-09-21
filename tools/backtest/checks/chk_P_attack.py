import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_full_fit_table.parquet")
print("cols with qb:",[c for c in d.columns if "qb" in c.lower()][:20])
print("n=%d seasons %d-%d"%(len(d),d.season.min(),d.season.max()))
def lg(p): p=np.clip(p,1e-9,1-1e-9); return np.log(p/(1-p))
off=lg(d.p_mkt_mult.to_numpy()); y=d.home_win.to_numpy(float)

print("\n=== A1. B_P with CLUSTERED standard errors (p_qb_z is a QB-level covariate) ===")
X=d[["F","p_qb_z","C","R"]]
base=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit()
rows={"B":base.params,"SE_naive":base.bse,"p_naive":base.pvalues}
grps={"season":d.season.astype(str),
      "home_qb_id":d.home_qb_id.astype(str),
      "away_qb_id":d.away_qb_id.astype(str),
      "qb_pair":d.home_qb_id.astype(str)+"|"+d.away_qb_id.astype(str),
      "home_team_season":d.home_team.astype(str)+"_"+d.season.astype(str)}
for k,v in grps.items():
    r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit(cov_type="cluster",
        cov_kwds={"groups":v.to_numpy(),"use_correction":True})
    rows["SE_"+k]=r.bse; rows["p_"+k]=r.pvalues
print(pd.DataFrame(rows).round(4).to_string())
print("n clusters: "+", ".join("%s=%d"%(k,v.nunique()) for k,v in grps.items()))

print("\n=== A2. QB-BLOCK bootstrap on B_P (resample distinct STARTING QBs, dedup games) ===")
rng=np.random.default_rng(3)
qbs=sorted(set(d.home_qb_id.astype(str))|set(d.away_qb_id.astype(str)))
hq=d.home_qb_id.astype(str).to_numpy(); aq=d.away_qb_id.astype(str).to_numpy()
bs=[]
for _ in range(400):
    keep=set(rng.choice(qbs,len(qbs),replace=True).tolist())
    m=np.array([ (a in keep) or (b in keep) for a,b in zip(hq,aq) ])
    dd=d[m]
    if len(dd)<500: continue
    try:
        r=sm.GLM(dd.home_win.to_numpy(float),dd[["F","p_qb_z","C","R"]],
                 family=sm.families.Binomial(),offset=lg(dd.p_mkt_mult.to_numpy())).fit()
        bs.append(r.params["p_qb_z"])
    except Exception: pass
bs=np.array(bs)
print("  B_P=%.4f ; QB-block bootstrap SD %.4f (naive SE %.4f) ; pct<=0 %.3f ; CI [%.4f,%.4f]"
      %(base.params["p_qb_z"],bs.std(),base.bse["p_qb_z"],(bs<=0).mean(),np.percentile(bs,2.5),np.percentile(bs,97.5)))

print("\n=== A3. IS IT REALLY UNPRICED, OR IS THE SPREAD->PRICE MAP MIS-SHAPED? ===")
print("Add flexible spread terms to the offset model. If p_qb_z is unpriced QB")
print("information it survives; if it was proxying for curvature in the market's")
print("own spread->moneyline map, it dies.")
d["s"]=d.spread_line.astype(float)
for label,cols in [("p_qb_z only",["p_qb_z"]),
                   ("p_qb_z + spread",["p_qb_z","s"]),
                   ("p_qb_z + spread + spread^2 + |spread|",["p_qb_z","s","s2","sabs"]),
                   ("p_qb_z + logit(p_mkt) FREE",["p_qb_z","u_free"])]:
    dd=d.copy(); dd["s2"]=dd.s**2; dd["sabs"]=dd.s.abs(); dd["u_free"]=off
    if "u_free" in cols:
        r=sm.GLM(y,dd[cols],family=sm.families.Binomial()).fit()
    else:
        r=sm.GLM(y,dd[cols],family=sm.families.Binomial(),offset=off).fit()
    rc=sm.GLM(y,dd[cols],family=sm.families.Binomial(),offset=None if "u_free" in cols else off).fit(
        cov_type="cluster",cov_kwds={"groups":grps["qb_pair"].to_numpy(),"use_correction":True})
    print("  %-42s B_P %+0.4f  p_naive %.4f  p_qbclust %.4f"%(label,r.params["p_qb_z"],r.pvalues["p_qb_z"],rc.pvalues["p_qb_z"]))

print("\n=== A4. ATS-residual correlation, clustered + by era ===")
ats=(d.result.astype(float)-d.spread_line.astype(float)).to_numpy()
for label,m in [("ALL 2006-2025",np.ones(len(d),bool)),
                ("2006-2015",(d.season<=2015).to_numpy()),
                ("2016-2025",(d.season>=2016).to_numpy()),
                ("2019-2025 (the modern, shippable window)",(d.season>=2019).to_numpy())]:
    v=d.p_qb_z.to_numpy()[m]; a=ats[m]
    r=np.corrcoef(v,a)[0,1]
    X=sm.add_constant(v)
    ols=sm.OLS(a,X).fit()
    olc=sm.OLS(a,X).fit(cov_type="cluster",cov_kwds={"groups":grps["qb_pair"].to_numpy()[m]})
    print("  %-42s n=%4d  r=%+0.4f  slope %+0.4f pts/SD  p_naive %.4f  p_qbclust %.4f"
          %(label,m.sum(),r,ols.params[1],ols.pvalues[1],olc.pvalues[1]))

print("\n=== A5. B_P by era, offset model (where does the significance live?) ===")
for lo,hi in [(2006,2012),(2013,2018),(2019,2025),(2006,2018),(2019,2025)]:
    dd=d[(d.season>=lo)&(d.season<=hi)]
    r=sm.GLM(dd.home_win.to_numpy(float),dd[["F","p_qb_z","C","R"]],
             family=sm.families.Binomial(),offset=lg(dd.p_mkt_mult.to_numpy())).fit()
    rc=sm.GLM(dd.home_win.to_numpy(float),dd[["F","p_qb_z","C","R"]],
             family=sm.families.Binomial(),offset=lg(dd.p_mkt_mult.to_numpy())).fit(
             cov_type="cluster",cov_kwds={"groups":(dd.home_qb_id.astype(str)+"|"+dd.away_qb_id.astype(str)).to_numpy()})
    print("  %d-%d n=%4d  B_P %+0.4f  SE %.4f  p %.4f | clustered p %.4f  (mean hold %.4f)"
          %(lo,hi,len(dd),r.params["p_qb_z"],r.bse["p_qb_z"],r.pvalues["p_qb_z"],rc.pvalues["p_qb_z"],dd.hold.mean()))
