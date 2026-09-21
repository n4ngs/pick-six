import numpy as np, pandas as pd, statsmodels.api as sm
d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_full_fit_table.parquet").reset_index(drop=True)
def lg(p): p=np.clip(np.asarray(p,float),1e-9,1-1e-9); return np.log(p/(1-p))
off=lg(d.p_mkt_mult); y=d.home_win.to_numpy(float)
print("qb_new_starter_diff value counts:"); print(d.qb_new_starter_diff.value_counts().head(8).to_string())
print("\n=== does B_P live in games where the recorded starter CHANGED from last week? ===")
print("(games.csv home_qb_id is the QB nflverse records as having started. If that")
print(" is ever inferred from the game itself, a surprise scratch is look-ahead.)")
chg=d.qb_new_starter_diff.fillna(0).ne(0).to_numpy()
for label,m in [("ALL",np.ones(len(d),bool)),("same starter as last week",~chg),("starter CHANGED",chg)]:
    dd=d[m]
    if len(dd)<150: print("  %-28s n=%d too thin"%(label,len(dd))); continue
    r=sm.GLM(dd.home_win.to_numpy(float),dd[["p_qb_z"]],family=sm.families.Binomial(),
             offset=lg(dd.p_mkt_mult)).fit()
    print("  %-28s n=%4d  B_P %+0.4f  SE %.4f  p %.4f"%(label,len(dd),r.params.iloc[0],r.bse.iloc[0],r.pvalues.iloc[0]))
print("\n=== is the pregame-unknowable part isolated? qb_fallback flags ===")
for c in ["qb_fallback_home","qb_fallback_away","qb_history_thin"]:
    if c in d.columns: print("  %-20s nonzero: %d of %d"%(c,int(pd.Series(d[c]).fillna(0).astype(bool).sum()),len(d)))
