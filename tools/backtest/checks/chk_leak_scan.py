import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
pass
d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_fit_table.parquet")
resid = d["home_win"].to_numpy(float) - d["p_mkt_mult"].to_numpy()
num = d.select_dtypes(include=[np.number])
drop = {"home_win","result","total","home_score","away_score","p_mkt_mult","p_mkt_shift",
        "q_home_raw","q_away_raw","overround","hold","is_tie"}
rows=[]
n=len(d)
for c in num.columns:
    if c in drop: continue
    v=num[c].to_numpy(float)
    if not np.isfinite(v).any(): continue
    m=np.isfinite(v)
    if m.sum()<200 or np.nanstd(v[m])==0: continue
    r=float(np.corrcoef(v[m],resid[m])[0,1])
    if not np.isfinite(r): continue
    rows.append({"col":c,"r_with_resid":r,"|z|":abs(r)*np.sqrt(m.sum()-2)/np.sqrt(max(1e-12,1-r*r)),"n":int(m.sum())})
t=pd.DataFrame(rows).sort_values("|z|",ascending=False)
print("correlation of every numeric column with (home_win - p_mkt). A genuine")
print("pregame feature should be ~0; a leaked outcome column would be large.\n")
print(t.head(18).round(4).to_string(index=False))
print("\ncolumns with |z| > 2.58 (p<.01, uncorrected): %d of %d"%((t["|z|"]>2.58).sum(),len(t)))
print("expected by chance at p<.01: %.1f"%(0.01*len(t)))
print("\nsanity: the outcome itself ->")
for c in ["result","home_score","away_score","total"]:
    if c in d.columns:
        v=pd.to_numeric(d[c],errors="coerce").to_numpy(float); m=np.isfinite(v)
        print("  %-12s r=%.3f"%(c,float(np.corrcoef(v[m],resid[m])[0,1])))
