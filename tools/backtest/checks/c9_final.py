import pandas as pd, numpy as np, os
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(os.path.join(H,"out_fit_table.parquet"))
print("p_qb identical to qb_delta_diff:", bool((d.p_qb.values==d.qb_delta_diff.values).all()))
print("max abs diff:", float(np.abs(d.p_qb-d.qb_delta_diff).max()))
# C reconstruction: how much does short_week move C?
print("\nshare of |C| attributable to short_week: max contribution =",
      float((0.5*d.c_short_week.abs()).max()), " (C sd = %.3f)"%d.C.std())
print("nonzero short_week rows:",int((d.c_short_week!=0).sum()),"of",len(d))
print("seasons with ANY nonzero short_week:",sorted(d.loc[d.c_short_week!=0,'season'].unique().tolist()))
# candidates file
e=pd.read_parquet(os.path.join(H,"out_eval_candidates.parquet"))
print("\ncandidates cols:",list(e.columns))
print("tier counts:"); print(e.tier.value_counts().to_string() if 'tier' in e else "n/a")
