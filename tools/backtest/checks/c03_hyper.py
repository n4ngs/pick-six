import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
import features_fundamental as FF
from load import load_games, load_pbp
seasons=list(range(2018,2026))
pbp=load_pbp(seasons, columns=FF.PBP_COLUMNS)
p=pbp.copy()
for c in ("posteam","defteam","home_team"): p[c]=FF._canon(p[c])
drives=FF._drive_table(p)
tg=FF._team_game_table(p,drives)
hyper,ts=FF._hyper_by_season(tg,verbose=True)
for s in sorted(hyper):
    print("season %d  source=%-45s  eff_sb=%.4f  off_epa k_flat=%.1f league=%.4f rho=%.3f"%(
        s,hyper[s]["source"],hyper[s]["ratings"]["eff"]["sigma_between"],
        hyper[s]["components"]["off_epa"]["k_flat"],hyper[s]["components"]["off_epa"]["league"],
        hyper[s]["components"]["off_epa"]["rho"]))
print()
print("seasons contributing to the SELF estimate:", hyper[2018]["seasons"])
print("2019 seasons used:", hyper[2019]["seasons"])
print("2020 seasons used:", hyper[2020]["seasons"])
