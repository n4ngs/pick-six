import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
import features_fundamental as FF, features_context as FC
from load import load_games, load_pbp
rng=np.random.default_rng(3)
seasons=list(range(2018,2026))
games_all=load_games(seasons=(2018,2025),require_lines=True,played_only=True)

# ---- A: does corrupting 2020-2025 move 2018/2019 features? ----
pbp=load_pbp(seasons,columns=FF.PBP_COLUMNS)
full=FF.build(games_all,pbp,verbose=False)
c=pbp.copy(); m=(c.season>=2020).to_numpy()
c.loc[m,"epa"]=rng.normal(0,1,m.sum()); c.loc[m,"ep"]=rng.normal(0,2,m.sum())
c.loc[m,"success"]=rng.integers(0,2,m.sum())
c.loc[m,"total_home_score"]=rng.integers(0,50,m.sum()); c.loc[m,"total_away_score"]=rng.integers(0,50,m.sum())
cor=FF.build(games_all,c,verbose=False)
for yr in (2018,2019,2020):
    a=full[full.season==yr].set_index("game_id"); b=cor[cor.season==yr].set_index("game_id").reindex(a.index)
    d={col: round(float(np.nanmax(np.abs(a[col].to_numpy(float)-b[col].to_numpy(float)))),6)
       for col in ["f_eff","f_finish","f_success","F","f_finish_resid"]}
    print("F  season %d  max|delta| when 2020-2025 plays are randomised: %s"%(yr,d))
print("  (2020 is expected to move: its own plays were corrupted. 2018/2019 moving is LOOK-AHEAD.)")
del pbp,c,full,cor

# ---- B: context, corrupt STRICTLY LATER games only ----
games_c=load_games(seasons=(2010,2025),played_only=True)
pbp=load_pbp(seasons,columns=["posteam","pass_oe","play_type"],offense_only=True)
full=FC.build(games_c,pbp,verbose=False).reset_index(drop=True)
CUT=202310
tgt=set(games_all[games_all.time_index==CUT].game_id)
g2=games_c.copy(); mg=(g2.time_index>CUT).to_numpy()
g2.loc[mg,"temp"]=rng.integers(-10,110,mg.sum()); g2.loc[mg,"wind"]=rng.integers(0,40,mg.sum())
g2.loc[mg,"home_rest"]=rng.integers(3,15,mg.sum()); g2.loc[mg,"away_rest"]=rng.integers(3,15,mg.sum())
g2.loc[mg,"result"]=rng.integers(-40,40,mg.sum())
cor=FC.build(g2,pbp,verbose=False).reset_index(drop=True)
a=full[full.game_id.isin(tgt)].set_index("game_id"); b=cor[cor.game_id.isin(tgt)].set_index("game_id").reindex(a.index)
print("\nC/R at week %d, only STRICTLY LATER games corrupted:"%CUT)
for col in ["C","c_rest_diff_z","c_travel_diff_z","c_wind_z","c_temp_shock","R","r_form_z"]:
    print("   %-16s max|delta| = %.9f"%(col,float(np.nanmax(np.abs(a[col].to_numpy(float)-b[col].to_numpy(float))))))
