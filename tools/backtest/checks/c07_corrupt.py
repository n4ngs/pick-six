"""Sharper no-look-ahead test. Truncating pbp also deletes the target week's
row-carriers, so instead CORRUPT everything at or after the cut: keep the rows
(same games, same teams, same play counts) but randomise every outcome-bearing
value. A feature that is honestly as-of cannot move."""
import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
import features_fundamental as FF, features_personnel as FP, features_context as FC
from load import load_games, load_pbp

CUT_S, CUT_W = 2023, 10
CUT = CUT_S*100 + CUT_W
seasons=list(range(2018,2026))
rng=np.random.default_rng(1)

games_all = load_games(seasons=(2018,2025), require_lines=True, played_only=True)
games_np  = load_games(seasons=(2018,2025), played_only=True)
target_ids=set(games_all[games_all.time_index==CUT].game_id)
print("cut=%d target games=%d"%(CUT,len(target_ids)))

def cmp(name, full, trunc, cols):
    a=full[full.game_id.isin(target_ids)].set_index("game_id")[cols].sort_index()
    b=trunc[trunc.game_id.isin(target_ids)].set_index("game_id")[cols].sort_index().reindex(a.index)
    bad={}
    for c in cols:
        x=pd.to_numeric(a[c],errors="coerce").to_numpy(float); y=pd.to_numeric(b[c],errors="coerce").to_numpy(float)
        d=float(np.nanmax(np.abs(x-y))) if len(x) else 0.0
        if not np.isfinite(d): d=999.0
        if d>1e-9: bad[c]=round(d,6)
    print("%-6s rows=%d  MOVED: %s"%(name,len(a),bad if bad else "NONE -> as-of holds"))

# ---------- F ----------
pbp=load_pbp(seasons, columns=FF.PBP_COLUMNS)
full=FF.build(games_all,pbp,verbose=False)
c=pbp.copy(); m=(c.time_index>=CUT).to_numpy()
c.loc[m,"epa"]=rng.normal(0,1,m.sum())
c.loc[m,"ep"]=rng.normal(0,2,m.sum())
c.loc[m,"success"]=rng.integers(0,2,m.sum())
c.loc[m,"total_home_score"]=rng.integers(0,50,m.sum())
c.loc[m,"total_away_score"]=rng.integers(0,50,m.sum())
cor=FF.build(games_all,c,verbose=False)
cmp("F",full,cor,["f_eff","f_finish","f_success","F","f_finish_resid","home_eff_z","away_eff_z"])
del pbp,c

# ---------- P ----------
pbp=load_pbp(seasons, columns=FP.PBP_COLUMNS)
full=FP.build(games_np,pbp)
c=pbp.copy(); m=(c.time_index>=CUT).to_numpy()
c.loc[m,"epa"]=rng.normal(0,1,m.sum())
cor=FP.build(games_np,c)
cmp("P",full,cor,["p_qb","p_qb_z","qb_quality_home","qb_quality_away"])
del pbp,c

# ---------- C/R ----------
games_c=load_games(seasons=(2010,2025),played_only=True)
pbp=load_pbp(seasons, columns=["posteam","pass_oe","play_type"], offense_only=True)
full=FC.build(games_c,pbp,verbose=False).reset_index(drop=True)
c=pbp.copy(); m=(c.time_index>=CUT).to_numpy()
c.loc[m,"pass_oe"]=rng.normal(0,20,m.sum())
cor=FC.build(games_c,c,verbose=False).reset_index(drop=True)
cmp("R",full,cor,["R","r_regime_score","r_form_z","r_pace_z","r_proe_z"])
# and corrupt the GAMES-side future too (weather/rest/etc of later games)
g2=games_c.copy(); mg=(g2.time_index>=CUT).to_numpy()
g2.loc[mg,"temp"]=rng.integers(-10,110,mg.sum()); g2.loc[mg,"wind"]=rng.integers(0,40,mg.sum())
g2.loc[mg,"home_rest"]=rng.integers(3,15,mg.sum()); g2.loc[mg,"away_rest"]=rng.integers(3,15,mg.sum())
cor2=FC.build(g2,pbp,verbose=False).reset_index(drop=True)
tgt=[g for g in target_ids]
a=full[full.game_id.isin(tgt)].set_index("game_id"); b=cor2[cor2.game_id.isin(tgt)].set_index("game_id").reindex(a.index)
print("  (future GAMES rows corrupted too -- target week's own temp/wind/rest are themselves corrupted, so")
print("   only columns that should depend on OTHER games' values are meaningful here)")
for col in ["c_rest_diff_z","c_travel_diff_z","C","c_wind_z"]:
    print("    %-16s max|delta| = %.6f"%(col,float(np.nanmax(np.abs(a[col].to_numpy(float)-b[col].to_numpy(float))))))
