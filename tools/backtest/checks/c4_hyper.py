import sys,os
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import pandas as pd, numpy as np
import features_fundamental as FF
from load import load_games, load_pbp
pbp=load_pbp([2018,2019,2020], columns=FF.PBP_COLUMNS)
dr=FF._drive_table(pbp); tg=FF._team_game_table(pbp,dr)
hyper,ts=FF._hyper_by_season(tg,verbose=True)
for s in sorted(hyper): print(s, hyper[s]["source"])
