import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
import fit as FIT
from fit import glm_fit, logit, sigmoid, logloss, brier, VECTORS, VECTOR_COL
FIT.FIT_LO,FIT.FIT_HI=2006,2025; FIT.CV_TEST_SEASONS=list(range(2008,2026))
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(H+"/out_full_fit_table.parquet")
cols=[VECTOR_COL[v] for v in VECTORS]
print("n=%d seasons %d-%d"%(len(d),d.season.min(),d.season.max()))
print(d.groupby("season").size().to_string())
off=logit(d.p_mkt_mult.to_numpy()); y=d.home_win.to_numpy(float)
r=glm_fit(d,cols,intercept=False,label="full")
print("\nT1 full-sample:")
print(r.summary().tables[1])
print("\ncorr with offset:", {v: round(float(np.corrcoef(d[VECTOR_COL[v]],off)[0,1]),3) for v in VECTORS})
# free offset
Xf=pd.DataFrame({"logit_p_mkt":off},index=d.index)
for c in cols: Xf[c]=d[c].to_numpy(float)
fr=sm.GLM(y,Xf,family=sm.families.Binomial()).fit()
print("\nfree-offset refit:"); print(fr.summary().tables[1])
# OOS
pieces=[]
for s in range(2008,2026):
    tr=d[d.season<s]; te=d[d.season==s]
    if len(tr)<200 or len(te)==0: continue
    rr=glm_fit(tr,cols,intercept=False,label="t")
    b=rr.params.reindex(cols).to_numpy(float)
    D=te[cols].to_numpy(float).dot(b)
    p=te[["game_id","season","home_win","p_mkt_mult","p_qb_z","spread_line","result"]].copy()
    p["D"]=D; p["p_model"]=sigmoid(logit(te.p_mkt_mult.to_numpy())+D)
    p["contrib_P"]=rr.params["p_qb_z"]*te["p_qb_z"].to_numpy()
    pieces.append(p)
o=pd.concat(pieces,ignore_index=True)
yy=o.home_win.to_numpy()
print("\nOOS n=%d  d_ll=%+.6f  d_brier=%+.6f"%(len(o),
    logloss(yy,o.p_mkt_mult)-logloss(yy,o.p_model), brier(yy,o.p_mkt_mult)-brier(yy,o.p_model)))
X=pd.DataFrame({"gamma_P":o.contrib_P.to_numpy()},index=o.index)
g=sm.GLM(yy,X,family=sm.families.Binomial(),offset=logit(o.p_mkt_mult.to_numpy())).fit()
print("gamma_P = %+.4f SE %.4f p %.5f CI %s"%(g.params.iloc[0],g.bse.iloc[0],g.pvalues.iloc[0],np.round(g.conf_int().iloc[0].values,3)))
