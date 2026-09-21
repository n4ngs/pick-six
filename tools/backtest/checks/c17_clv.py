import pandas as pd, numpy as np
p="/Users/cmanlongat/Projects/pick-six/data/nflverse/initial_lines.csv"
i=pd.read_csv(p)
print("initial_lines cols:",list(i.columns))
print("rows",len(i),"types",i.type.unique(),"books",i.sportsbook.unique())
print("seasons:",sorted(i.season.unique()))
sp=i[i.type.eq("SPREAD")]
print("SPREAD rows by season:"); print(sp.groupby("season").size().to_string())
print("\nsample 'about' values:",sp.about.head(3).tolist())
cand=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_eval_candidates.parquet")
print("\nheld-out game_ids:",cand.game_id.nunique(),"seasons",sorted(cand.season.unique()))
ov=set(sp.about)&set(cand.game_id)
print("overlap with held-out games:",len(ov))
