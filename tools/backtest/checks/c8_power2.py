import sys,os; sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import pandas as pd, numpy as np, statsmodels.api as sm
from fit import logit, sigmoid, logloss, CV_TEST_SEASONS
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
base=pd.read_parquet(os.path.join(H,"out_fit_table.parquet")).copy()
rng=np.random.default_rng(11)
u=logit(base.p_mkt_mult.values)

def trial(delta,seed):
    r2=np.random.default_rng(seed)
    d=base.copy()
    d["x"]=np.where(r2.normal(size=len(d))>0,1.0,-1.0)
    d["home_win"]=(r2.random(len(d))<sigmoid(u+delta*d.x.values)).astype(int)
    ys=[];pm=[];pp=[];bs=[]
    for s in CV_TEST_SEASONS:
        tr=d[d.season<s]; te=d[d.season==s]
        r=sm.GLM(tr.home_win.values.astype(float),pd.DataFrame({"x":tr.x.values}),
                 family=sm.families.Binomial(),offset=logit(tr.p_mkt_mult.values)).fit()
        b=r.params["x"]; bs.append(b)
        ys.append(te.home_win.values); pm.append(te.p_mkt_mult.values)
        pp.append(sigmoid(logit(te.p_mkt_mult.values)+b*te.x.values))
    y=np.concatenate(ys);a=np.concatenate(pm);c=np.concatenate(pp)
    return logloss(y,a)-logloss(y,c), float(np.mean(bs))

print("true delta | mean pp edge | recovered B | median d_ll over 25 sims | P(d_ll>0)")
for delta in [0.06,0.12,0.25,0.50,1.0]:
    res=[trial(delta,100+i) for i in range(25)]
    dlls=np.array([r[0] for r in res]); bb=np.mean([r[1] for r in res])
    pp_edge=np.mean(np.abs(sigmoid(u+delta)-sigmoid(u)))*100
    print("  %.2f      |   %5.2f pp   |   %+.3f     |   %+0.5f              |  %.0f%%"
          %(delta,pp_edge,bb,np.median(dlls),100*np.mean(dlls>0)))
print("\nreference: harness bootstrap 95%% CI half-width on d_ll = 0.0047")
