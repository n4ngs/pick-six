import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_fit_table.parquet")
d=d.dropna(subset=["result","spread_line"])
resid=d["result"]-d["spread_line"]
print("n=%d"%len(d))
print("%-18s %10s %10s %10s"%("feature","corr(res)","corr(sprd)","corr(resid)"))
for c in ["F","f_eff","f_finish","f_finish_resid","f_success","p_qb_z","C","R",
          "c_rest_diff_z","c_travel_diff_z","c_tz_pen_diff","c_wind_z"]:
    x=d[c].to_numpy(float)
    print("%-18s %+10.4f %+10.4f %+10.4f"%(c,np.corrcoef(x,d["result"])[0,1],
        np.corrcoef(x,d["spread_line"])[0,1],np.corrcoef(x,resid)[0,1]))
print("\nA feature that beat the market would show a large corr(resid). The market")
print("residual has SD %.2f pts; |corr| above ~0.15 is the leakage alarm the module names."%resid.std())
# ATS record if you bet the side F likes
print("\nATS: bet home when F>0, away when F<0 (closing spread):")
pick=np.sign(d["F"].to_numpy()); ats=np.sign(resid.to_numpy())
ok=(pick!=0)&(ats!=0)
print("   %d bets, %.4f cover rate (breakeven 0.524)"%(ok.sum(),(pick[ok]==ats[ok]).mean()))
