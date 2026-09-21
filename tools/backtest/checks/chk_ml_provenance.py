import numpy as np, pandas as pd
g=pd.read_csv("/Users/cmanlongat/Projects/pick-six/data/nflverse/games.csv",low_memory=False)
g=g.dropna(subset=["home_moneyline","away_moneyline","spread_line","result"])
def ap(ml):
    ml=np.asarray(ml,float); out=np.empty_like(ml); n=ml<0
    out[n]=(-ml[n])/((-ml[n])+100.0); out[~n]=100.0/(ml[~n]+100.0); return out
g["hold"]=ap(g.home_moneyline)+ap(g.away_moneyline)-1.0
print("=== two-way moneyline HOLD by season (a real book runs 3-5%%) ===")
t=g.groupby("season").agg(n=("hold","size"),hold=("hold","mean"),
    uniq_ml=("home_moneyline","nunique"),
    ml_per_spread=("home_moneyline", lambda s: np.nan))
tt=g.groupby("season").apply(lambda d: pd.Series({
   "n":len(d),"hold":d.hold.mean(),"hold_sd":d.hold.std(),
   "uniq_home_ml":d.home_moneyline.nunique(),
   "mean_ml_per_spread": d.groupby("spread_line").home_moneyline.nunique().mean(),
   "frac_spread_groups_with_1_ml": (d.groupby("spread_line").home_moneyline.nunique()==1).mean(),
}),include_groups=False)
print(tt.round(3).to_string())
print("""
mean_ml_per_spread = for a given closing spread, how many DISTINCT home moneylines
appear that season. A real book prices the ML independently of the spread, so this
should be well above 1. Close to 1 means the moneyline was DERIVED from the spread.""")
print("\n=== R^2 of logit(no-vig p_mkt) on a smooth function of the spread ===")
g["p"]=ap(g.home_moneyline)/(1+g.hold)
g=g[(g.hold>0)&(g.p>0)&(g.p<1)]
g["u"]=np.log(g.p/(1-g.p))
for lo,hi in [(2006,2012),(2013,2018),(2019,2022),(2023,2025)]:
    d=g[(g.season>=lo)&(g.season<=hi)]
    if not len(d): continue
    X=np.column_stack([np.ones(len(d)),d.spread_line,d.spread_line**2,d.spread_line**3])
    b,*_=np.linalg.lstsq(X,d.u,rcond=None)
    r2=1-((d.u-X@b)**2).sum()/((d.u-d.u.mean())**2).sum()
    resid_sd=float(np.std(d.u-X@b))
    print("  %d-%d  n=%5d  R^2(u ~ cubic in spread) = %.5f   residual SD %.4f  mean hold %.4f"%(lo,hi,len(d),r2,resid_sd,d.hold.mean()))
print("""
R^2 ~= 1.000 and residual SD ~ 0 means the moneyline carries NO information the
spread does not already carry -- i.e. it was generated from the spread, not quoted.""")
