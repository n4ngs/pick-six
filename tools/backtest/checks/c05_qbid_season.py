import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
from load import load_games, load_pbp
g=load_games(seasons=(2018,2025), played_only=True)
pbp=load_pbp(list(range(2018,2026)), columns=["posteam","qb_dropback","passer_player_id","rusher_player_id","play_id"])
d=pbp[pbp.qb_dropback.eq(1)].copy(); d["qb"]=d.passer_player_id.fillna(d.rusher_player_id); d=d[d.qb.notna()]
d=d.sort_values(["game_id","play_id"])
first=d.groupby(["game_id","posteam"])["qb"].first().rename("first_qb").reset_index()
cnt=d.groupby(["game_id","posteam","qb"]).size().rename("n").reset_index()
most=cnt.sort_values("n",ascending=False).groupby(["game_id","posteam"]).first().reset_index().rename(columns={"qb":"most_qb","n":"most_n"})
tot=d.groupby(["game_id","posteam"]).size().rename("tot").reset_index()
m=first.merge(most,on=["game_id","posteam"]).merge(tot,on=["game_id","posteam"])
rows=[]
for side in ("home","away"):
    gg=g[["game_id","season","%s_team"%side,"%s_qb_id"%side]].rename(columns={"%s_team"%side:"posteam","%s_qb_id"%side:"rec_qb"})
    rows.append(gg.merge(m,on=["game_id","posteam"],how="inner"))
j=pd.concat(rows,ignore_index=True)
j["played_any"]=[ (r in set(cnt[(cnt.game_id==gid)&(cnt.posteam==t)].qb)) for gid,t,r in zip(j.game_id,j.posteam,j.rec_qb)] if False else None
j["m_first"]=(j.rec_qb==j.first_qb)
j["m_most"]=(j.rec_qb==j.most_qb)
print(j.groupby("season").agg(n=("m_first","size"),pct_first=("m_first","mean"),pct_most=("m_most","mean")).round(4).to_string())
# how often recorded qb = the RELIEVER (played most but not first) -> look-ahead
relief=j[(~j.m_first)&(j.m_most)]
print("\nrecorded == reliever (not first dropback, but most dropbacks): %d rows"%len(relief))
print(relief.groupby("season").size().to_string())
# recorded qb played zero dropbacks?
key=set(zip(cnt.game_id,cnt.posteam,cnt.qb))
j["rec_played"]=[(a,b,c) in key for a,b,c in zip(j.game_id,j.posteam,j.rec_qb)]
print("\nrecorded QB took ZERO dropbacks in that team-game: %d rows"%int((~j.rec_played).sum()))
print(j[~j.rec_played].groupby("season").size().to_string())
