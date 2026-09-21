import pandas as pd, numpy as np, os
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(os.path.join(H,"out_fit_table.parquet"))
print("c_short_week value counts:"); print(d.c_short_week.value_counts(dropna=False))
nz=d[d.c_short_week!=0]
print(nz[['game_id','season','week','weekday','away_rest','home_rest','c_short_week']].to_string(index=False))
print("\nHow many games actually have a short week (rest<=4) for either side?")
print(" home_rest<=4:",(d.home_rest<=4).sum()," away_rest<=4:",(d.away_rest<=4).sum())
print(" exactly one side short:",((d.home_rest<=4)^(d.away_rest<=4)).sum())
print("\nrest distributions:")
print(pd.crosstab(d.home_rest, d.weekday).to_string())
print("\nc_bye_return value counts:"); print(d.c_bye_return.value_counts(dropna=False))
print("\nrest>=13 counts: home",(d.home_rest>=13).sum(),"away",(d.away_rest>=13).sum())
