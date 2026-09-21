import pandas as pd, numpy as np, os, statsmodels.api as sm
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(os.path.join(H,"out_fit_table.parquet"))
print("corr f_eff vs f_success:", round(d.f_eff.corr(d.f_success),4))
print("corr f_eff vs F:", round(d.f_eff.corr(d.F),4))
off=np.log(d.p_mkt_mult/(1-d.p_mkt_mult)); y=d.home_win.values.astype(float)
def fit(cols):
    X=pd.DataFrame({c:d[c].values for c in cols})
    r=sm.GLM(y,X,family=sm.families.Binomial(),offset=off.values).fit()
    return {c:(round(r.params[c],4),round(r.pvalues[c],4)) for c in cols}
print("f_eff alone        :",fit(["f_eff"]))
print("f_success alone    :",fit(["f_success"]))
print("f_eff+f_success    :",fit(["f_eff","f_success"]))
print("F alone            :",fit(["F"]))
# VIF-ish
from numpy.linalg import lstsq
for a,b in [("f_eff","f_success"),("f_success","f_eff")]:
    r2=np.corrcoef(d[a],d[b])[0,1]**2
    print("  VIF(%s | %s) = %.2f"%(a,b,1/(1-r2)))
# out-of-sample sign of f_eff alone
for s in range(2021,2026):
    tr=d[d.season<s]; te=d[d.season==s]
    X=pd.DataFrame({"f_eff":tr.f_eff.values})
    o=np.log(tr.p_mkt_mult/(1-tr.p_mkt_mult)).values
    r=sm.GLM(tr.home_win.values.astype(float),X,family=sm.families.Binomial(),offset=o).fit()
    b=r.params["f_eff"]
    ote=np.log(te.p_mkt_mult/(1-te.p_mkt_mult)).values
    pm=1/(1+np.exp(-(ote+b*te.f_eff.values)))
    yt=te.home_win.values
    ll=lambda p: -np.mean(yt*np.log(p)+(1-yt)*np.log(1-p))
    print("  %d B_f_eff=%+.3f  d_ll=%+0.5f"%(s,b,ll(1/(1+np.exp(-ote)))-ll(pm)))
