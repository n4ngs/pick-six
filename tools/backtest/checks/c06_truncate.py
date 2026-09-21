"""Decisive no-look-ahead test: rebuild each feature module with pbp+games
TRUNCATED to strictly-before a cut week, and compare the features it emits for
that week against the full-data build. Any difference is look-ahead."""
import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
import features_fundamental as FF, features_personnel as FP, features_context as FC
from load import load_games, load_pbp

CUT_S, CUT_W = 2023, 10
CUT = CUT_S*100 + CUT_W
seasons=list(range(2018,2026))

games_all = load_games(seasons=(2018,2025), require_lines=True, played_only=True)
games_all_np = load_games(seasons=(2018,2025), played_only=True)
pbp_f = load_pbp(seasons, columns=FF.PBP_COLUMNS)
pbp_p = load_pbp(seasons, columns=FP.PBP_COLUMNS)

target_ids = set(games_all[games_all.time_index==CUT].game_id)
print("cut = %d, target games in that week: %d"%(CUT,len(target_ids)))

def cmp(name, full, trunc, cols, key="game_id"):
    a=full[full[key].isin(target_ids)].set_index(key)[cols].sort_index()
    b=trunc[trunc[key].isin(target_ids)].set_index(key)[cols].sort_index()
    b=b.reindex(a.index)
    bad={}
    for c in cols:
        x=pd.to_numeric(a[c],errors="coerce").to_numpy(float); y=pd.to_numeric(b[c],errors="coerce").to_numpy(float)
        d=np.nanmax(np.abs(np.nan_to_num(x)-np.nan_to_num(y))) if len(x) else 0.0
        if d>1e-9: bad[c]=float(d)
    print("%-14s rows=%d  MISMATCHED COLS: %s"%(name,len(a),bad if bad else "none (identical)"))

# ---- F ----
full_f = FF.build(games_all, pbp_f, verbose=False)
# truncated: keep only plays and games strictly before the cut, plus the target week's GAMES (rows to predict)
pbp_t = pbp_f[pbp_f.time_index < CUT]
games_t = games_all[games_all.time_index <= CUT]
tr_f = FF.build(games_t, pd.concat([pbp_t], ignore_index=True), verbose=False)
cmp("F", full_f, tr_f, ["f_eff","f_finish","f_success","F","f_finish_resid"])

# ---- P ----
full_p = FP.build(games_all_np, pbp_p)
pbp_pt = pbp_p[FP.time_index(pbp_p) < CUT] if "time_index" not in pbp_p else pbp_p[pbp_p.time_index<CUT]
games_pt = games_all_np[games_all_np.time_index <= CUT]
tr_p = FP.build(games_pt, pbp_pt)
cmp("P", full_p, tr_p, ["p_qb","p_qb_z","qb_delta_diff","qb_quality_home","qb_quality_away"])

# ---- C/R ----
games_c = load_games(seasons=(2010,2025), played_only=True)
pbp_c = load_pbp(seasons, columns=["posteam","pass_oe","play_type"], offense_only=True)
full_c = FC.build(games_c, pbp_c, verbose=False).reset_index(drop=True)
pbp_ct = pbp_c[pbp_c.time_index < CUT]
games_ct = games_c[games_c.time_index <= CUT]
tr_c = FC.build(games_ct, pbp_ct, verbose=False).reset_index(drop=True)
cmp("C/R", full_c, tr_c, ["C","R","c_rest_diff_z","c_travel_diff_z","c_tz_pen_diff","r_regime_score","r_form_z","c_wind_z","c_temp_shock"])
