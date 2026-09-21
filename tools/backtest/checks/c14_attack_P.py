import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
import fit as FIT
from fit import glm_fit, logit, sigmoid, logloss, VECTORS, VECTOR_COL
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(H+"/out_full_fit_table.parquet")
cols=[VECTOR_COL[v] for v in VECTORS]
off=logit(d.p_mkt_mult.to_numpy()); y=d.home_win.to_numpy(float)

def fit_with(extra_cols, label):
    X=pd.DataFrame(index=d.index)
    for c in cols: X[c]=d[c].to_numpy(float)
    for nm,v in extra_cols.items(): X[nm]=v
    r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit()
    print("%-42s B_P=%+.5f SE %.5f p=%.5f"%(label,r.params["p_qb_z"],r.bse["p_qb_z"],r.pvalues["p_qb_z"]))
    return r

print("=== ATTACK 1: is B_P absorbing a NONLINEARITY in the market price? ===")
fit_with({}, "baseline (offset pinned)")
fit_with({"off2":off**2}, "+ logit(p_mkt)^2")
fit_with({"off2":off**2,"off3":off**3}, "+ logit^2 + logit^3")
fit_with({"absoff":np.abs(off)}, "+ |logit(p_mkt)|")
fit_with({"fav":(off>0).astype(float)}, "+ home-favourite indicator")
fit_with({"off2":off**2,"off3":off**3,"absoff":np.abs(off)}, "+ all price shape terms")
print()
print("=== ATTACK 2: era split (in-sample B_P by era) ===")
for lo,hi in ((2006,2012),(2013,2018),(2019,2025)):
    s=d[d.season.between(lo,hi)]
    r=glm_fit(s,cols,intercept=False,label="e")
    print("  %d-%d n=%4d  B_P=%+.5f SE %.5f p=%.4f"%(lo,hi,len(s),r.params["p_qb_z"],r.bse["p_qb_z"],r.pvalues["p_qb_z"]))
print()
print("=== ATTACK 3: P alone vs P + price-shape, full sample ===")
for extra,lab in (({} ,"P alone"),({"off2":off**2,"off3":off**3},"P + price shape")):
    X=pd.DataFrame({"p_qb_z":d.p_qb_z.to_numpy(float)},index=d.index)
    for nm,v in extra.items(): X[nm]=v
    r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit()
    print("  %-22s B_P=%+.5f SE %.5f p=%.5f"%(lab,r.params["p_qb_z"],r.bse["p_qb_z"],r.pvalues["p_qb_z"]))
print()
print("=== ATTACK 4: ATS residual correlation (leakage tell) ===")
dd=d.dropna(subset=["spread_line","result"])
res=dd.result-dd.spread_line
for lab,a,b in (("p_qb_z vs spread_line",dd.p_qb_z,dd.spread_line),
                ("p_qb_z vs result",dd.p_qb_z,dd.result),
                ("p_qb_z vs ATS residual",dd.p_qb_z,res)):
    r=np.corrcoef(a,b)[0,1]; n=len(dd); se=1/np.sqrt(n-3); z=.5*np.log((1+r)/(1-r))
    print("  %-26s %+0.4f CI [%+0.4f,%+0.4f]"%(lab,r,np.tanh(z-1.96*se),np.tanh(z+1.96*se)))
print()
print("=== ATTACK 5: does the home-field constant explain it? (intercept) ===")
X=pd.DataFrame({"const":1.0},index=d.index)
for c in cols: X[c]=d[c].to_numpy(float)
r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit()
print(r.summary().tables[1])
