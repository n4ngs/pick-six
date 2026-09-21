"""How big is the SELF-fallback leak in realistic conditions (no corruption)?
Build F with pbp 2018-2020 only -- the SELF constants for 2018/2019 then see
only 2018-2020 -- and compare the 2019/2020 features to the 2018-2025 build
the harness actually uses."""
import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
import features_fundamental as FF
from load import load_games, load_pbp
games=load_games(seasons=(2018,2025),require_lines=True,played_only=True)
full=FF.build(games,load_pbp(list(range(2018,2026)),columns=FF.PBP_COLUMNS),verbose=False)
g3=games[games.season<=2020]
small=FF.build(g3,load_pbp([2018,2019,2020],columns=FF.PBP_COLUMNS),verbose=False)
for yr in (2019,2020):
    a=full[full.season==yr].set_index("game_id"); b=small[small.season==yr].set_index("game_id").reindex(a.index)
    print("season %d (n=%d)"%(yr,len(a)))
    for col in ["f_eff","f_finish","f_success","F","f_finish_resid"]:
        x=a[col].to_numpy(float); y=b[col].to_numpy(float)
        print("   %-16s max|d|=%.4f  mean|d|=%.4f  sd(feature)=%.4f  corr=%.5f"%(
            col,np.nanmax(np.abs(x-y)),np.nanmean(np.abs(x-y)),np.nanstd(x),
            np.corrcoef(x[np.isfinite(x)&np.isfinite(y)],y[np.isfinite(x)&np.isfinite(y)])[0,1]))
