import pandas as pd, numpy as np, os
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(os.path.join(H,"out_fit_table.parquet"))
print("fit table rows",len(d),"cols",len(d.columns))
print("seasons",sorted(d.season.unique()))
print(list(d.columns))
