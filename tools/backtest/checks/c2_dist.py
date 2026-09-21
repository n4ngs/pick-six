import pandas as pd, numpy as np, os
pd.set_option("display.width",220); pd.set_option("display.max_columns",60)
H="/Users/cmanlongat/Projects/pick-six/tools/backtest"
d=pd.read_parquet(os.path.join(H,"out_fit_table.parquet"))
feat=['F','f_eff','f_finish','f_finish_resid','f_success','p_qb','p_qb_z','qb_delta_diff',
 'qb_new_starter_diff','C','R','c_rest_diff_z','c_travel_diff_z','c_tz_pen_diff','c_short_week',
 'c_bye_return','c_div_game','c_indoor','c_wind_z','r_regime_score','r_fav','r_p_grind','r_p_chaos']
off=np.log(d.p_mkt_mult/(1-d.p_mkt_mult))
rows=[]
for c in feat:
    x=d[c].astype(float)
    rows.append(dict(col=c,n=x.notna().sum(),nan=x.isna().sum(),
      mean=x.mean(),sd=x.std(),mn=x.min(),mx=x.max(),
      zero_frac=(x.fillna(0)==0).mean(),
      uniq=x.nunique(),
      r_offset=np.corrcoef(x.fillna(x.mean()),off)[0,1],
      r_spread=np.corrcoef(x.fillna(x.mean()),d.spread_line)[0,1]))
print(pd.DataFrame(rows).round(4).to_string(index=False))
print("\n--- per-season SD (constant-for-a-season check) ---")
print(d.groupby('season')[feat].std().round(4).T.to_string())
print("\n--- per-season MEAN ---")
print(d.groupby('season')[feat].mean().round(4).T.to_string())
print("\n--- pairwise |corr|>0.9 among features ---")
cc=d[feat].corr().abs()
import itertools
for a,b in itertools.combinations(feat,2):
    v=cc.loc[a,b]
    if v>0.85: print("  %-20s %-20s %.4f"%(a,b,v))
