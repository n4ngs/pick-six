#!/usr/bin/env python3
"""
A2: provenance of games.csv home_qb_id/away_qb_id.
Is it (a) the announced PRE-GAME starter, or (b) something nflverse derived
FROM THE GAME ITSELF (the QB with the most dropbacks / the first snap)?
If (b), a "starter change" flag can be CAUSED by the outcome of the game --
a QB knocked out or benched in Q1 makes the backup the 'starter of record'.
That would make the response variable endogenous to the feature.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "data", "nflverse"))
pd.set_option("display.width", 220)

g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
g = g.dropna(subset=["result"])

SEASONS = [2005, 2010, 2015, 2019, 2023, 2025]   # spread of eras, fixed up front
rows = []
for s in SEASONS:
    pbp = pd.read_parquet(os.path.join(DATA, "play_by_play_%d.parquet" % s),
                          columns=["game_id","posteam","qb_dropback","passer_player_id",
                                   "rusher_player_id","play_id","epa"])
    d = pbp[pbp.qb_dropback.eq(1)].copy()
    d["qb"] = d.passer_player_id.fillna(d.rusher_player_id)
    d = d[d.qb.notna()].sort_values(["game_id","play_id"])
    first = d.groupby(["game_id","posteam"]).qb.first().rename("first_qb")
    cnt = d.groupby(["game_id","posteam","qb"]).size().rename("n").reset_index()
    most = cnt.sort_values("n").groupby(["game_id","posteam"]).tail(1)\
             .set_index(["game_id","posteam"])[["qb","n"]].rename(columns={"qb":"most_qb","n":"most_n"})
    tot = d.groupby(["game_id","posteam"]).size().rename("tot_db")
    j = pd.concat([first, most, tot], axis=1).reset_index()
    gg = g[g.season == s]
    for side in ("home","away"):
        sub = gg[["game_id","%s_team"%side,"%s_qb_id"%side,"season","week"]].rename(
            columns={"%s_team"%side:"posteam","%s_qb_id"%side:"listed_qb"})
        m = sub.merge(j, on=["game_id","posteam"], how="inner")
        m["side"] = side
        rows.append(m)
A = pd.concat(rows, ignore_index=True)
A["match_first"] = A.listed_qb == A.first_qb
A["match_most"]  = A.listed_qb == A.most_qb
A["share"] = A.most_n / A.tot_db
print("team-games audited: %d (seasons %s)" % (len(A), SEASONS))
print("\nlisted qb_id == FIRST dropback QB of the game : %.4f" % A.match_first.mean())
print("listed qb_id == MOST-dropbacks QB of the game : %.4f" % A.match_most.mean())
print("\nby season:")
print(A.groupby("season").apply(lambda d: pd.Series({
    "n": len(d), "==first": d.match_first.mean(), "==most": d.match_most.mean()}),
    include_groups=False).round(4).to_string())

print("\n--- the decisive subset: games where FIRST != MOST (a QB was replaced mid-game) ---")
sp = A[A.first_qb != A.most_qb]
print("team-games where the first-snap QB was NOT the most-used QB: %d (%.3f%%)"
      % (len(sp), 100*len(sp)/len(A)))
print("  of those, games.csv lists the FIRST-snap QB : %d (%.3f)" % (int(sp.match_first.sum()), sp.match_first.mean()))
print("  of those, games.csv lists the MOST-used QB  : %d (%.3f)" % (int(sp.match_most.sum()), sp.match_most.mean()))
print("  neither: %d" % int((~sp.match_first & ~sp.match_most).sum()))
print("\nVERDICT: games.csv qb_id follows %s"
      % ("the FIRST SNAP (a pre-game starter proxy, not outcome-driven)"
         if sp.match_first.mean() > 0.9 else
         "the MOST-USED QB (DERIVED FROM THE GAME -> endogenous)" if sp.match_most.mean() > 0.9
         else "NEITHER cleanly -- inspect"))
