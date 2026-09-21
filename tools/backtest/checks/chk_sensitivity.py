import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from fit import logit, sigmoid, logloss, brier, VECTOR_COL, VECTORS

d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_fit_table.parquet")
d=d.reset_index(drop=True)
d["F_plus"]=(d["f_eff"]+d["f_finish"])/np.sqrt(2.0)
d["F_resid"]=(d["f_eff"]-d["f_finish_resid"])/np.sqrt(2.0)
d["F_flipsign"]=-d["F"]

def cv(dd,cols,pcol="p_mkt_mult",test_seasons=range(2021,2026)):
    pieces=[]
    for s in test_seasons:
        tr=dd[dd.season<s]; te=dd[dd.season==s]
        if len(tr)<200 or len(te)==0: continue
        r=sm.GLM(tr.home_win.to_numpy(float),tr[cols],family=sm.families.Binomial(),
                 offset=logit(tr[pcol].to_numpy())).fit()
        b=r.params.reindex(cols).to_numpy(float)
        off=logit(te[pcol].to_numpy())
        p=te[["season","home_win"]].copy()
        p["p_model"]=sigmoid(off+te[cols].to_numpy(float).dot(b))
        p["p_mkt"]=te[pcol].to_numpy()
        pieces.append(p)
    o=pd.concat(pieces,ignore_index=True)
    y=o.home_win.to_numpy()
    return logloss(y,o.p_mkt)-logloss(y,o.p_model), brier(y,o.p_mkt)-brier(y,o.p_model), len(o)

V=[VECTOR_COL[v] for v in VECTORS]
variants=[
 ("BASELINE  F,P,C,R  mult de-vig, CV 2021-25", V, "p_mkt_mult", range(2021,2026)),
 ("F built as eff+finish (sign of finish flipped)", ["F_plus","p_qb_z","C","R"], "p_mkt_mult", range(2021,2026)),
 ("F built with f_finish_resid", ["F_resid","p_qb_z","C","R"], "p_mkt_mult", range(2021,2026)),
 ("F itself sign-flipped (identical fit, sanity)", ["F_flipsign","p_qb_z","C","R"], "p_mkt_mult", range(2021,2026)),
 ("SHIFT de-vig instead of multiplicative", V, "p_mkt_shift", range(2021,2026)),
 ("CV starts 2020 (smaller first train block)", V, "p_mkt_mult", range(2020,2026)),
 ("CV starts 2022 (bigger first train block)", V, "p_mkt_mult", range(2022,2026)),
 ("component spec", ["f_eff","f_finish_resid","f_success","p_qb_z","c_rest_diff_z","c_travel_diff_z","c_tz_pen_diff","R"], "p_mkt_mult", range(2021,2026)),
 ("F alone", ["F"], "p_mkt_mult", range(2021,2026)),
 ("P alone", ["p_qb_z"], "p_mkt_mult", range(2021,2026)),
 ("C alone", ["C"], "p_mkt_mult", range(2021,2026)),
 ("R alone", ["R"], "p_mkt_mult", range(2021,2026)),
]
print("%-52s %10s %10s %6s"%("variant","d_logloss","d_brier","n"))
print("(positive d = model BEAT the closing price)")
for name,cols,pcol,ts in variants:
    try:
        a,b,n=cv(d,cols,pcol,ts)
        print("%-52s %+10.6f %+10.6f %6d  %s"%(name,a,b,n,"BEATS" if a>0 else "loses"))
    except Exception as e:
        print("%-52s FAILED %s"%(name,e))
