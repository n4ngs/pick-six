import sys, os
sys.path.insert(0, "/Users/cmanlongat/Projects/pick-six/tools/backtest")
import pandas as pd, numpy as np
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
for f in ["out_fit_table","out_fundamental","out_personnel","out_context","out_eval_candidates"]:
    p=os.path.join(H,f+".parquet")
    d=pd.read_parquet(p)
    print("==",f,d.shape)
    if "season" in d: print("   seasons:", sorted(d.season.unique())[:12])
    print("   cols:", list(d.columns)[:40])
