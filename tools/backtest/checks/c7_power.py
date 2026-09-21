"""Positive control: can this harness DETECT an edge if one existed?"""
import sys,os; sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import pandas as pd, numpy as np, statsmodels.api as sm
from fit import logit, sigmoid, logloss, CV_TEST_SEASONS
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(os.path.join(H,"out_fit_table.parquet")).copy()
rng=np.random.default_rng(7)

def run(col,label):
    tot_m=[];tot_p=[]
    for s in CV_TEST_SEASONS:
        tr=d[d.season<s]; te=d[d.season==s]
        X=pd.DataFrame({col:tr[col].values})
        r=sm.GLM(tr.home_win.values.astype(float),X,family=sm.families.Binomial(),
                 offset=logit(tr.p_mkt_mult.values)).fit()
        b=r.params[col]
        pm=sigmoid(logit(te.p_mkt_mult.values)+b*te[col].values)
        tot_m.append(pd.DataFrame({"y":te.home_win.values,"pmkt":te.p_mkt_mult.values,"pmod":pm}))
    o=pd.concat(tot_m)
    dll=logloss(o.y.values,o.pmkt.values)-logloss(o.y.values,o.pmod.values)
    print("  %-34s pooled d_ll = %+0.5f  (%s)"%(label,dll,"DETECTED" if dll>0.002 else "not detected"))

# 1. pure noise
d["noise"]=rng.normal(size=len(d))
run("noise","pure noise (null)")
# 2. a genuinely known 1-pt-of-spread edge: tiny true signal
#    simulate: feature = sign of a real 1.5pp probability edge
true_edge=0.015
u=logit(d.p_mkt_mult.values)
d["planted_small"]=np.where(rng.normal(size=len(d))>0,1.0,-1.0)
# re-draw outcomes with the planted edge so we KNOW the truth
p_true=sigmoid(u + 0.06*d.planted_small.values)   # ~1.5pp shift
d_save=d.home_win.copy()
d["home_win"]=(rng.random(len(d))<p_true).astype(int)
run("planted_small","planted +1.5pp edge (synthetic y)")
d["home_win"]=d_save
# 3. an OBVIOUS leak: the actual result
d["leak_result"]=np.clip(d.result.values/14.0,-3,3)
run("leak_result","LEAK: actual margin/14")
