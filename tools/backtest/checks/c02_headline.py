import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
from fit import (VECTORS, VECTOR_COL, CV_TEST_SEASONS, glm_fit, logit, sigmoid, logloss, brier)
d = pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_fit_table.parquet")
COLS=[VECTOR_COL[v] for v in VECTORS]
print("fit table:", d.shape, "seasons", sorted(d.season.unique()))
pieces=[]
for s in CV_TEST_SEASONS:
    tr=d[d.season<s]; te=d[d.season==s]
    if len(tr)<200 or len(te)==0: continue
    r=glm_fit(tr,COLS,intercept=False,label="t")
    b=r.params.reindex(COLS).to_numpy(float)
    D=te[COLS].to_numpy(float).dot(b)
    off=logit(te["p_mkt_mult"].to_numpy())
    p=te[["game_id","season","home_win","p_mkt_mult"]].copy()
    p["D"]=D; p["p_model"]=sigmoid(off+D)
    pieces.append(p)
    print(" test %d n_tr=%d n_te=%d B=%s"%(s,len(tr),len(te),np.round(b,4)))
o=pd.concat(pieces,ignore_index=True)
y=o.home_win.to_numpy()
print("OOS n=%d  ll_mkt=%.6f ll_model=%.6f delta=%+.6f"%(len(o),logloss(y,o.p_mkt_mult),logloss(y,o.p_model),logloss(y,o.p_mkt_mult)-logloss(y,o.p_model)))
print("    brier mkt=%.6f model=%.6f delta=%+.6f"%(brier(y,o.p_mkt_mult),brier(y,o.p_model),brier(y,o.p_mkt_mult)-brier(y,o.p_model)))
print("mean|D|=%.4f"%np.abs(o.D).mean())
# full-sample fit
r=glm_fit(d,COLS,intercept=False,label="full")
print(r.summary().tables[1])
