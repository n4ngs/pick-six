#!/usr/bin/env python3
"""
A3 + leak test.
(1) Is qb_prior_db_{side} in out_full_pers.parquet EXACTLY the count of that
    QB's dropbacks in STRICTLY EARLIER games? If it includes the current game,
    every quality number is contaminated by the game being predicted.
(2) How often is qb_change_delta built on an IMPUTED previous starter
    (prev QB with zero prior dropbacks -> silently set to replacement level)?
    qb_fallback_* only flags the CURRENT starter, so the pre-registered
    'no fallback' filter does not catch this.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "data", "nflverse"))
pd.set_option("display.width", 220)

P = pd.read_parquet(os.path.join(HERE, "out_full_pers.parquet"))
print("out_full_pers.parquet: %d rows, seasons %d-%d" % (len(P), P.season.min(), P.season.max()))
print("qb_history_thin rows: %d ; qb_fallback either side: %d"
      % (int(P.qb_history_thin.sum()),
         int(((P.qb_fallback_home==1)|(P.qb_fallback_away==1)).sum())))

# ---- rebuild the dropback ledger from raw pbp, 1999-2025 ----
frames = []
for s in range(1999, 2026):
    d = pd.read_parquet(os.path.join(DATA, "play_by_play_%d.parquet" % s),
                        columns=["season","week","game_id","qb_dropback",
                                 "passer_player_id","rusher_player_id","epa","posteam"])
    d = d[d.qb_dropback.eq(1)].copy()
    d["qb"] = d.passer_player_id.fillna(d.rusher_player_id)
    d = d[d.qb.notna() & d.epa.notna()]
    d["ti"] = d.season.astype(int)*100 + d.week.astype(int)
    frames.append(d.groupby(["ti","game_id","qb"], as_index=False)
                   .agg(posteam=("posteam","first"), n=("epa","size"), s=("epa","sum")))
QG = pd.concat(frames, ignore_index=True).sort_values(["ti","game_id","qb"])
print("qb-game rows from raw pbp 1999-2025: %d, dropbacks %d" % (len(QG), int(QG.n.sum())))

# strictly-prior cumulative totals per QB, by week block (state advances AFTER the week)
QG = QG.sort_values(["ti","game_id"]).reset_index(drop=True)
wk = QG.groupby(["ti","qb"], as_index=False).agg(n=("n","sum"), s=("s","sum")).sort_values("ti")
wk["prior_n"] = wk.groupby("qb").n.cumsum() - wk.n
wk["prior_s"] = wk.groupby("qb").s.cumsum() - wk.s
prior = wk.set_index(["ti","qb"])[["prior_n","prior_s"]]

# also carry prior totals to weeks where the QB did NOT play: build an as-of lookup
allqb = sorted(wk.qb.unique()); tis = sorted(QG.ti.unique())
piv_n = wk.pivot_table(index="ti", columns="qb", values="n", aggfunc="sum").reindex(tis).fillna(0.0)
piv_s = wk.pivot_table(index="ti", columns="qb", values="s", aggfunc="sum").reindex(tis).fillna(0.0)
cum_n = piv_n.cumsum().shift(1).fillna(0.0)     # strictly prior
cum_s = piv_s.cumsum().shift(1).fillna(0.0)
print("as-of prior matrices: %s" % (cum_n.shape,))

# ---- (1) leak test against the harness's own qb_prior_db ----
chk = []
for side in ("home","away"):
    sub = P[["game_id","time_index","%s_qb_id"%side,"qb_prior_db_%s"%side]].rename(
        columns={"%s_qb_id"%side:"qb","qb_prior_db_%s"%side:"harness_n"})
    sub = sub[sub.qb.notna()]
    mine = []
    for ti, q in zip(sub.time_index.to_numpy(), sub.qb.to_numpy()):
        mine.append(cum_n.at[ti, q] if (ti in cum_n.index and q in cum_n.columns) else 0.0)
    sub["mine_n"] = mine; sub["side"] = side
    chk.append(sub)
C = pd.concat(chk, ignore_index=True)
C["diff"] = C.harness_n - C.mine_n
print("\n=== LEAK TEST: harness qb_prior_db vs independently recomputed STRICT-PRIOR dropbacks ===")
print("team-game rows checked: %d" % len(C))
print("exact match: %.5f" % (C["diff"]==0).mean())
print("harness > mine (would mean the CURRENT game's snaps are inside): %d rows, mean excess %.2f"
      % (int((C["diff"]>0).sum()), C.loc[C["diff"]>0,"diff"].mean() if (C["diff"]>0).any() else 0))
print("harness < mine: %d rows" % int((C["diff"]<0).sum()))
if (C["diff"]!=0).any():
    print(C[C["diff"]!=0].head(10).to_string(index=False))
# the decisive check: does the excess equal this game's own dropbacks?
own = QG.groupby(["game_id","qb"]).n.sum().rename("own_n")
D = C.merge(own.reset_index(), on=["game_id","qb"], how="left")
D["own_n"] = D.own_n.fillna(0)
print("rows where (harness - mine) == this game's OWN dropbacks (the smoking gun): %d"
      % int(((D["diff"]>0) & (D["diff"]==D.own_n)).sum()))

# ---- (2) imputed PREVIOUS starter inside qb_change_delta ----
print("\n=== IMPUTATION AUDIT: the PREVIOUS starter inside qb_change_delta ===")
g = pd.read_csv(os.path.join(DATA,"games.csv"), low_memory=False).dropna(subset=["result"])
g = g[g.season.between(1999,2025)].copy()
g["ti"] = g.season*100 + g.week
long = pd.concat([
    g[["game_id","ti","season","week","home_team","home_qb_id"]].rename(
        columns={"home_team":"team","home_qb_id":"qb"}).assign(side="home"),
    g[["game_id","ti","season","week","away_team","away_qb_id"]].rename(
        columns={"away_team":"team","away_qb_id":"qb"}).assign(side="away")])
long = long.sort_values(["team","ti","game_id"])
long["prev_qb"] = long.groupby("team").qb.shift(1)
long["prev_known"] = long.prev_qb.notna()
long["changed"] = long.prev_known & (long.qb != long.prev_qb)
pn = []
for ti, q in zip(long.ti.to_numpy(), long.prev_qb.to_numpy()):
    pn.append(cum_n.at[ti, q] if (isinstance(q,str) and ti in cum_n.index and q in cum_n.columns) else np.nan)
long["prev_prior_db"] = pn
ch = long[long.changed]
print("team-games with a starter change (my own flag): %d" % len(ch))
print("  of which the PREVIOUS starter had ZERO prior dropbacks (delta silently")
print("  imputed to replacement level, NOT flagged by qb_fallback): %d (%.3f%%)"
      % (int((ch.prev_prior_db==0).sum()), 100*(ch.prev_prior_db==0).mean()))
print("  previous starter with <100 prior dropbacks (delta near-meaningless): %d (%.2f%%)"
      % (int((ch.prev_prior_db<100).sum()), 100*(ch.prev_prior_db<100).mean()))
long.to_parquet(os.path.join(HERE,"out_audit_long.parquet"))
cum_n.to_parquet(os.path.join(HERE,"out_audit_cumn.parquet"))
cum_s.to_parquet(os.path.join(HERE,"out_audit_cums.parquet"))
print("\ncached: out_audit_long.parquet / out_audit_cumn.parquet / out_audit_cums.parquet")
