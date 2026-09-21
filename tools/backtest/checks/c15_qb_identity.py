import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from fit import glm_fit, logit, VECTORS, VECTOR_COL
from load import load_games, load_pbp
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(H+"/out_full_fit_table.parquet")
cols=[VECTOR_COL[v] for v in VECTORS]

# --- reliever detection over the full window ---
yrs=list(range(2006,2026))
g=load_games(seasons=(2006,2025),played_only=True)
pbp=load_pbp(yrs,columns=["posteam","qb_dropback","passer_player_id","rusher_player_id","play_id"])
p=pbp[pbp.qb_dropback.eq(1)].copy(); p["qb"]=p.passer_player_id.fillna(p.rusher_player_id)
p=p[p.qb.notna()].sort_values(["game_id","play_id"])
first=p.groupby(["game_id","posteam"])["qb"].first().rename("first_qb").reset_index()
cnt=p.groupby(["game_id","posteam","qb"]).size().rename("n").reset_index()
most=cnt.sort_values("n",ascending=False).groupby(["game_id","posteam"]).first().reset_index().rename(columns={"qb":"most_qb"})
m=first.merge(most[["game_id","posteam","most_qb"]],on=["game_id","posteam"])
rows=[]
for side in ("home","away"):
    gg=g[["game_id","season","%s_team"%side,"%s_qb_id"%side]].rename(columns={"%s_team"%side:"posteam","%s_qb_id"%side:"rec"})
    rows.append(gg.merge(m,on=["game_id","posteam"],how="inner"))
j=pd.concat(rows,ignore_index=True)
j["reliever"]=(j.rec!=j.first_qb)&(j.rec==j.most_qb)
j["not_first"]=(j.rec!=j.first_qb)
print("team-games 2006-2025: %d"%len(j))
print("recorded == first-dropback QB: %.4f   recorded is the RELIEVER: %d (%.3f%%)"%(
    (~j.not_first).mean(), int(j.reliever.sum()), 100*j.reliever.mean()))
print("reliever cases by 5-yr block:")
j["blk"]=(j.season//5)*5
print(j.groupby("blk").agg(n=("reliever","size"),reliever=("reliever","sum"),pct_first=("not_first",lambda x:1-x.mean())).round(4).to_string())
bad=set(j[j.reliever].game_id) | set(j[j.not_first].game_id)
relief_only=set(j[j.reliever].game_id)
print("\ngames touched by a reliever attribution: %d"%len(relief_only))
print("games where either side's recorded QB != first-dropback QB: %d"%len(bad))

def refit(mask,label):
    s=d[mask]
    r=glm_fit(s,cols,intercept=False,label="x")
    print("  %-52s n=%4d  B_P=%+.5f SE %.5f p=%.5f"%(label,len(s),r.params["p_qb_z"],r.bse["p_qb_z"],r.pvalues["p_qb_z"]))
print("\n=== drop the look-ahead-suspect games ===")
refit(pd.Series(True,index=d.index),"all games")
refit(~d.game_id.isin(relief_only),"drop reliever-attributed games")
refit(~d.game_id.isin(bad),"drop ALL games whose QB != first-dropback QB")

print("\n=== split by whether the starter is the SAME as last week (fully pregame-knowable) ===")
if "qb_new_starter_diff" in d.columns:
    same=d.qb_new_starter_diff.fillna(0)==0
    refit(same,"both teams start the same QB as last game")
    refit(~same,"at least one team changed starter")
