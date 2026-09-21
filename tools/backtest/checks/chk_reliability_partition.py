import os, sys
sys.path.insert(0, "/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
from fit import glm_fit, logit, sigmoid, VECTOR_COL, VECTORS, CV_TEST_SEASONS, logloss, brier

d = pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_fit_table.parquet")
COLS=[VECTOR_COL[v] for v in VECTORS]
pieces=[]
for s in CV_TEST_SEASONS:
    tr=d[d.season<s]; te=d[d.season==s]
    if len(tr)<200 or len(te)==0: continue
    r=glm_fit(tr,COLS,intercept=False,label="x")
    b=r.params.reindex(COLS).to_numpy(float)
    off=logit(te["p_mkt_mult"].to_numpy())
    p=te[["game_id","season","home_win","p_mkt_mult","home_team","away_team"]].copy()
    p["p_model"]=sigmoid(off+te[COLS].to_numpy(float).dot(b))
    pieces.append(p)
oos=pd.concat(pieces,ignore_index=True)

def dec_table(o, bycol, evalcols):
    o=o.copy(); o["dec"]=pd.qcut(o[bycol],10,labels=False,duplicates="drop")
    rows=[]
    for dcl,g in o.groupby("dec"):
        row={"dec":int(dcl)+1,"n":len(g),"actual":g.home_win.mean()}
        for c in evalcols: row["err_"+c]=g[c].mean()-g.home_win.mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("dec")

print("=== A. evaluate.py's method: SEPARATE partitions (what evaluate.py prints) ===")
tm=dec_table(oos,"p_model",["p_model"]); tk=dec_table(oos,"p_mkt_mult",["p_mkt_mult"])
print("model  mean|err| (deciles of p_model)  = %.5f"%tm["err_p_model"].abs().mean())
print("market mean|err| (deciles of p_mkt)    = %.5f"%tk["err_p_mkt_mult"].abs().mean())
print("  -> evaluate.py reads this as 'model better calibrated'")

print("\n=== B. SAME partition (deciles of p_model, both scored on those rows) ===")
t=dec_table(oos,"p_model",["p_model","p_mkt_mult"])
print(t.round(4).to_string())
print("model  mean|err| = %.5f"%t["err_p_model"].abs().mean())
print("market mean|err| = %.5f"%t["err_p_mkt_mult"].abs().mean())

print("\n=== C. SAME partition (deciles of p_mkt) ===")
t2=dec_table(oos,"p_mkt_mult",["p_model","p_mkt_mult"])
print("model  mean|err| = %.5f"%t2["err_p_model"].abs().mean())
print("market mean|err| = %.5f"%t2["err_p_mkt_mult"].abs().mean())

print("\n=== D. same-rows scalar scores (the only apples-to-apples) ===")
y=oos.home_win.to_numpy()
print("logloss  market %.6f  model %.6f  (model better? %s)"%(logloss(y,oos.p_mkt_mult),logloss(y,oos.p_model),logloss(y,oos.p_model)<logloss(y,oos.p_mkt_mult)))
print("brier    market %.6f  model %.6f  (model better? %s)"%(brier(y,oos.p_mkt_mult),brier(y,oos.p_model),brier(y,oos.p_model)<brier(y,oos.p_mkt_mult)))
print("\ndecile bucket sizes: model %s"%list(dec_table(oos,'p_model',['p_model'])['n']))
print("decile bucket sizes: market %s"%list(dec_table(oos,'p_mkt_mult',['p_mkt_mult'])['n']))
