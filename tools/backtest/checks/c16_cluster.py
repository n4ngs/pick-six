import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from fit import glm_fit, logit, VECTORS, VECTOR_COL
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(H+"/out_full_fit_table.parquet")
cols=[VECTOR_COL[v] for v in VECTORS]
off=logit(d.p_mkt_mult.to_numpy()); y=d.home_win.to_numpy(float)
X=pd.DataFrame({c:d[c].to_numpy(float) for c in cols},index=d.index)
base=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit()
print("naive (iid) SEs:")
for c in cols: print("   %-8s B=%+.5f SE=%.5f p=%.5f"%(c,base.params[c],base.bse[c],base.pvalues[c]))
for key,lab in (("season","season"),("home_team","home team"),("home_qb_id","home QB")):
    if key not in d.columns: print("  (no %s column)"%key); continue
    grp=d[key].astype(str).to_numpy()
    r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit(cov_type="cluster",
        cov_kwds={"groups":pd.factorize(grp)[0],"use_correction":True})
    print("\ncluster-robust by %s (%d clusters):"%(lab,len(set(grp))))
    for c in cols: print("   %-8s B=%+.5f SE=%.5f p=%.5f"%(c,r.params[c],r.bse[c],r.pvalues[c]))
# team-season cluster
d["ts"]=d.season.astype(str)+"|"+d.home_team.astype(str)
r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit(cov_type="cluster",
    cov_kwds={"groups":pd.factorize(d.ts)[0],"use_correction":True})
print("\ncluster-robust by home team-season (%d clusters):"%d.ts.nunique())
for c in cols: print("   %-8s B=%+.5f SE=%.5f p=%.5f"%(c,r.params[c],r.bse[c],r.pvalues[c]))
# season-block bootstrap on B_P
rng=np.random.default_rng(11); seasons=sorted(d.season.unique()); bs=[]
for _ in range(600):
    pick=rng.choice(seasons,len(seasons),replace=True)
    s=pd.concat([d[d.season==p] for p in pick],ignore_index=True)
    try:
        rr=glm_fit(s,cols,intercept=False,label="b"); bs.append(rr.params["p_qb_z"])
    except Exception: pass
bs=np.array(bs)
print("\nseason-block bootstrap of B_P: mean %+.4f  95%% CI [%+.4f, %+.4f]  P(B<=0)=%.3f"%(
    bs.mean(),*np.percentile(bs,[2.5,97.5]),(bs<=0).mean()))
