import os,sys,warnings
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore"); pd.set_option("display.width",200)
d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_wind_totals.parquet")
MDE_Z=stats.norm.ppf(0.975)+stats.norm.ppf(0.80)

print("="*92);print("T17  STADIUM FIXED EFFECTS -- is 'wind' just a few windy stadiums?");print("="*92)
print("distinct stadiums: %d ; distinct home_team: %d"%(d.stadium_id.nunique(),d.home_team.nunique()))
dd=d.copy()
for s in sorted(dd.stadium_id.dropna().unique())[1:]:
    dd["st_%s"%s]=(dd.stadium_id==s).astype(float)
for y in sorted(dd.season.unique())[1:]:
    dd["yr_%d"%y]=(dd.season==y).astype(float)
stf=[c for c in dd.columns if c.startswith("st_")]; yrf=[c for c in dd.columns if c.startswith("yr_")]
for lbl,X in [("stadium FE only",["wind"]+stf),("stadium FE + season FE",["wind"]+stf+yrf)]:
    r=sm.OLS(dd.resid.astype(float),sm.add_constant(dd[X].astype(float))).fit(
        cov_type="cluster",cov_kwds={"groups":dd.season})
    print("  %-24s wind %+.4f (SE %.4f, p %.4f)  n=%d, %d params"
          %(lbl,r.params["wind"],r.bse["wind"],r.pvalues["wind"],len(dd),len(X)+1))
print("\nWITHIN-STADIUM only (demean wind and resid by stadium -- pure within variation):")
w=dd.groupby("stadium_id")["wind"].transform("mean"); rr=dd.groupby("stadium_id")["resid"].transform("mean")
dw=dd.wind-w; dr=dd.resid-rr
r=sm.OLS(dr,sm.add_constant(pd.DataFrame({"dwind":dw}))).fit(cov_type="cluster",cov_kwds={"groups":dd.season})
print("  within-stadium wind slope %+.4f (SE %.4f, p %.4f)"%(r.params["dwind"],r.bse["dwind"],r.pvalues["dwind"]))
print("  sd of within-stadium wind: %.2f mph (of %.2f total) -> %.0f%% of wind variation is WITHIN a stadium"
      %(dw.std(),dd.wind.std(),100*dw.var()/dd.wind.var()))

print("\n"+"="*92);print("T18  REAL PRICES -- under_odds coverage and ROI at actual closing juice");print("="*92)
g=pd.read_csv("/Users/cmanlongat/Projects/pick-six/data/nflverse/games.csv",low_memory=False)
d2=d.merge(g[["game_id","under_odds","over_odds"]],on="game_id",how="left",suffixes=("","_g"))
uo=d2["under_odds"] if "under_odds" in d2 else d2["under_odds_g"]
print("under_odds non-null: %d / %d (%.1f%%)"%(uo.notna().sum(),len(d2),100*uo.notna().mean()))
print("by season:"); print(d2.groupby("season").apply(lambda x:pd.Series({"n":len(x),"has_odds":x["under_odds"].notna().sum()})).T.to_string())
haveo=d2[uo.notna()]
print("\nunder_odds when present: mean %.1f median %.1f  (-110 => %.0f)"
      %(haveo["under_odds"].mean(),haveo["under_odds"].median(),-110))
def payout(o): o=float(o); return 100/abs(o) if o<0 else o/100.
sub=haveo[(haveo.wind>=15)].dropna(subset=["under"])
if len(sub):
    pnl=np.where(sub["under"]==1, sub["under_odds"].map(payout), -1.0)
    print("wind>=15 with real prices: n=%d  under rate %.4f  ROI %+.4f (vs %+.4f at flat -110)"
          %(len(sub),sub["under"].mean(),pnl.mean(),(sub["under"].mean()*(100/110.)-(1-sub["under"].mean()))))
    ho=sub[sub.season>=2013]
    if len(ho):
        p2=np.where(ho["under"]==1,ho["under_odds"].map(payout),-1.0)
        print("  held-out 2013+ only: n=%d  rate %.4f  ROI %+.4f"%(len(ho),ho["under"].mean(),p2.mean()))
