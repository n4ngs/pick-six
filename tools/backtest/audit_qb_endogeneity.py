#!/usr/bin/env python3
"""
A2b: ENDOGENEITY. games.csv qb_id is the first-snap QB ~99.4% of the time, but
in the rest it is the QB who took the MOST snaps -- i.e. the mid-game
replacement. Where that happens, the 'starter' of record is determined by what
happened IN the game (starter hurt / benched), and a team whose QB got knocked
out plays worse -> the change flag is caused by the outcome.

Test: rebuild the ENTIRE change flag from the pbp FIRST-SNAP QB (the cleanest
available pre-outcome starter proxy) for all 1999-2025, and refit T1/T3.
Also: how many 'changes' are pure metadata (listed QB took zero dropbacks)?
Also: era split, because qb_id sourcing quality differs across the archive.
"""
import os, sys
import numpy as np, pandas as pd, statsmodels.api as sm
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "data", "nflverse"))
pd.set_option("display.width", 220)

# ---- first-snap QB per team-game, all seasons ----
rows = []
for s in range(1999, 2026):
    d = pd.read_parquet(os.path.join(DATA, "play_by_play_%d.parquet" % s),
                        columns=["game_id","posteam","qb_dropback","passer_player_id",
                                 "rusher_player_id","play_id"])
    d = d[d.qb_dropback.eq(1)].copy()
    d["qb"] = d.passer_player_id.fillna(d.rusher_player_id)
    d = d[d.qb.notna()].sort_values(["game_id","play_id"])
    f = d.groupby(["game_id","posteam"]).qb.first().rename("first_qb").reset_index()
    c = d.groupby(["game_id","posteam","qb"]).size().rename("n").reset_index()
    m = c.sort_values("n").groupby(["game_id","posteam"]).tail(1)[["game_id","posteam","qb"]]\
         .rename(columns={"qb":"most_qb"})
    tot = d.groupby(["game_id","posteam"]).size().rename("tot_db").reset_index()
    rows.append(f.merge(m, on=["game_id","posteam"]).merge(tot, on=["game_id","posteam"]))
FS = pd.concat(rows, ignore_index=True)
print("team-games with pbp dropbacks: %d" % len(FS))

g = pd.read_csv(os.path.join(DATA,"games.csv"), low_memory=False).dropna(subset=["result"])
g = g[g.season.between(1999,2025)].copy()
long = pd.concat([
    g[["game_id","season","week","home_team","home_qb_id"]].rename(
        columns={"home_team":"posteam","home_qb_id":"listed"}).assign(side="home"),
    g[["game_id","season","week","away_team","away_qb_id"]].rename(
        columns={"away_team":"posteam","away_qb_id":"listed"}).assign(side="away")])
# nflverse pbp uses MODERN franchise abbreviations (LA/LAC/LV) while games.csv
# keeps the historical ones (STL/SD/OAK). Joining without this map silently
# drops ~900 team-games. (The harness itself joins on game_id, so it is immune.)
ABBR = {"STL":"LA", "SD":"LAC", "OAK":"LV"}
long["posteam"] = long.posteam.replace(ABBR)
long = long.merge(FS, on=["game_id","posteam"], how="left")
print("\n=== HOW OFTEN IS THE LISTED 'STARTER' THE IN-GAME REPLACEMENT? (all 1999-2025) ===")
ok = long[long.first_qb.notna()]
print("listed == first-snap QB: %.5f   listed == most-used QB: %.5f (n=%d)"
      % ((ok.listed==ok.first_qb).mean(), (ok.listed==ok.most_qb).mean(), len(ok)))
bad = ok[(ok.listed!=ok.first_qb)]
print("listed != first-snap QB: %d team-games (%.3f%%)" % (len(bad), 100*len(bad)/len(ok)))
print("  of those, listed == the MOST-USED QB (the mid-game replacement): %d"
      % int((bad.listed==bad.most_qb).sum()))
print("  of those, listed is NEITHER (pure metadata / never took a snap): %d"
      % int(((bad.listed!=bad.most_qb)).sum()))

# ---- rebuild the change flag off the FIRST-SNAP QB ----
long["ti"] = long.season*100 + long.week
L = long.sort_values(["posteam","ti","game_id"]).copy()
L["prev_first"] = L.groupby("posteam").first_qb.shift(1)
L["chg_fs"] = L.prev_first.notna() & L.first_qb.notna() & (L.first_qb != L.prev_first)
L["known_fs"] = L.prev_first.notna() & L.first_qb.notna()
w = L.pivot_table(index="game_id", columns="side", values=["chg_fs","known_fs"], aggfunc="first")
w.columns = ["%s_%s" % (a,b) for a,b in w.columns]; w = w.reset_index()
t = g.merge(w, on="game_id", how="inner", validate="1:1")
t = t[t.spread_line.notna() & t.known_fs_home.astype(bool) & t.known_fs_away.astype(bool)].copy()
h = t.chg_fs_home.astype(bool).to_numpy(); a = t.chg_fs_away.astype(bool).to_numpy()
t["chg"] = np.where(h & ~a, 1, np.where(a & ~h, -1, 0))
t["chg_wk1"] = np.where(t.week==1, t.chg, 0); t["chg_in"] = np.where(t.week>=2, t.chg, 0)
t["ats_home"] = t.result - t.spread_line

def ols(d, cols, y="ats_home"):
    X = sm.add_constant(d[cols].astype(float))
    return sm.OLS(d[y].astype(float), X).fit(cov_type="cluster", cov_kwds={"groups": d.season})
def rep(name, r, term):
    b,se,p = r.params[term], r.bse[term], r.pvalues[term]
    print("%-42s B=%+.4f SE=%.4f p=%.4f  80%%-power floor %.4f" % (name,b,se,p,2.802*se))

print("\n=== T1/T3 REBUILT ON THE FIRST-SNAP QB (pre-outcome starter proxy) ===")
print("sample n=%d, change games %d (%.1f%%)  [listed-QB version: 7256 / 1381 / 19.0%%]"
      % (len(t), int((t.chg!=0).sum()), 100*(t.chg!=0).mean()))
rep("T1 chg  (first-snap flag)", ols(t,["chg"]), "chg")
r3 = ols(t,["chg_wk1","chg_in"]); rep("T3 chg_wk1 (first-snap)", r3,"chg_wk1"); rep("T3 chg_in (first-snap)", r3,"chg_in")

# ---- what the contaminated rows alone do ----
R = pd.read_parquet(os.path.join(HERE,"out_audit_recomputed.parquet"))
badg = set(bad.game_id)
R["contam"] = R.game_id.isin(badg)
print("\n=== THE CONTAMINATED ROWS ALONE ===")
print("games where at least one side's listed QB != first-snap QB: %d of %d (%.2f%%)"
      % (int(R.contam.sum()), len(R), 100*R.contam.mean()))
sub = R[R.contam & (R.chg!=0)]
print("  of those, flagged as a change: %d ; their mean cover margin for the changed team: %+.3f pts"
      % (len(sub), (sub.chg*sub.ats_home).mean()))
cln = R[~R.contam & (R.chg!=0)]
print("  clean change games: %d ; mean cover margin for the changed team: %+.3f pts"
      % (len(cln), (cln.chg*cln.ats_home).mean()))
rep("T1 with contaminated games DROPPED", ols(R[~R.contam],["chg"]), "chg")

print("\n=== ERA SPLIT (data-sourcing robustness, both halves reported) ===")
for lo,hi in [(1999,2012),(2013,2025)]:
    d = R[R.season.between(lo,hi)]
    rep("T1 chg %d-%d (n=%d, chg=%d)" % (lo,hi,len(d),int((d.chg!=0).sum())), ols(d,["chg"]), "chg")
