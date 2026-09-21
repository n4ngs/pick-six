import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
from load import load_games, load_pbp
seasons=list(range(2018,2026))
g=load_games(seasons=(2018,2025), played_only=True)
pbp=load_pbp(seasons, columns=["posteam","home_team","away_team","qb_dropback","passer_player_id","rusher_player_id","play_id","qtr"])
d=pbp[pbp.qb_dropback.eq(1)].copy()
d["qb"]=d.passer_player_id.fillna(d.rusher_player_id)
d=d[d.qb.notna()]
d=d.sort_values(["game_id","play_id"])
first=d.groupby(["game_id","posteam"])["qb"].first().rename("first_qb").reset_index()
cnt=d.groupby(["game_id","posteam","qb"]).size().rename("n").reset_index()
most=cnt.sort_values("n",ascending=False).groupby(["game_id","posteam"]).first().reset_index()[["game_id","posteam","qb","n"]].rename(columns={"qb":"most_qb","n":"most_n"})
tot=d.groupby(["game_id","posteam"]).size().rename("tot").reset_index()
m=first.merge(most,on=["game_id","posteam"]).merge(tot,on=["game_id","posteam"])
rows=[]
for side in ("home","away"):
    gg=g[["game_id","%s_team"%side,"%s_qb_id"%side]].rename(columns={"%s_team"%side:"posteam","%s_qb_id"%side:"rec_qb"})
    j=gg.merge(m,on=["game_id","posteam"],how="inner")
    j["side"]=side
    rows.append(j)
j=pd.concat(rows,ignore_index=True)
print("team-games joined:",len(j))
print("recorded == first dropback QB : %.4f"%(j.rec_qb==j.first_qb).mean())
print("recorded == most dropbacks QB : %.4f"%(j.rec_qb==j.most_qb).mean())
mismatch=j[(j.rec_qb!=j.first_qb)]
print("\nrows where recorded != first-dropback QB: %d (%.2f%%)"%(len(mismatch),100*len(mismatch)/len(j)))
print(" of those, recorded == most-dropback QB: %d"%int((mismatch.rec_qb==mismatch.most_qb).sum()))
# how many of those games did the "first" QB throw very few passes (i.e. early injury)?
sub=mismatch.copy()
f=d.groupby(["game_id","posteam","qb"]).size().rename("n").reset_index()
sub=sub.merge(f,left_on=["game_id","posteam","first_qb"],right_on=["game_id","posteam","qb"],how="left").rename(columns={"n":"first_qb_db"})
print(sub[["game_id","posteam","rec_qb","first_qb","first_qb_db","most_qb","most_n","tot"]].head(20).to_string(index=False))
print("\nmedian dropbacks by the first (unrecorded) QB in mismatch games:",sub.first_qb_db.median())
