import pandas as pd, numpy as np, os
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
p=pd.read_parquet(os.path.join(H,"out_personnel.parquet"))
f=pd.read_parquet(os.path.join(H,"out_fundamental.parquet"))
c=pd.read_parquet(os.path.join(H,"out_context.parquet"))
print("personnel cols:",[x for x in p.columns][:40])
print("\nqb_history_thin by season:"); print(p.groupby("season").qb_history_thin.mean().round(4).to_string())
print("\nf_ready by season/week<=2:")
print(f[f.week<=2].groupby(["season","week"]).f_ready.mean().round(3).to_string())
print("\nF at week1 (should be 0/unready):", f[(f.week==1)].F.abs().max())
print("\nr_ok by season:"); print(c.groupby("season").r_ok.mean().round(3).to_string())
print("c_ok by season:"); print(c.groupby("season").c_ok.mean().round(3).to_string())
print("\nqb_fallback rates:", p.qb_fallback_home.mean().round(4), p.qb_fallback_away.mean().round(4))
