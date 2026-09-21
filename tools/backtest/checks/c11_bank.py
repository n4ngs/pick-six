import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd
from scipy import stats
c=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_eval_candidates.parquet")
print("candidates:",len(c),"games:",c.game_id.nunique())
print(c.tier.value_counts().to_string())
def sim(p,lam=.25,cap=.05,flat=None,b0=10000.):
    bank=b0;peak=b0;dd=0;st=0;pnl=0;w=0;n=0
    for _,r in p.iterrows():
        s=flat*b0 if flat is not None else min(lam*r.kelly,cap)*bank
        if s<=0 or bank<=0: continue
        n+=1;st+=s
        g=s*(r.dec-1) if r.won else -s
        if r.won: w+=1
        pnl+=g;bank+=g;peak=max(peak,bank);dd=max(dd,(peak-bank)/peak)
    return dict(bets=n,won=w,hit=w/n if n else np.nan,staked=st,pnl=pnl,ROI=pnl/st if st else np.nan,final=bank,dd=dd)
c=c.sort_values(["gameday","gametime","game_id","side"])
for lbl,sel in [("A EV_lo>0",c.EV_lo>0),("B EV_lo>=1%",c.EV_lo>=.01),("C EV_lo>=3%",c.EV_lo>=.03),
                ("D BH",c.bh_survives.astype(bool)),("E EV>0",c.EV>0),("G EV>2%",c.EV>0.02)]:
    p=c[sel]
    r=sim(p); 
    flat=np.where(p.won==1,p.dec-1,-1.0)
    ci=np.percentile(np.random.default_rng(7).choice(flat,size=(4000,len(flat))).mean(axis=1),[2.5,97.5]) if len(flat)>=10 else (np.nan,np.nan)
    print("%-12s n=%4d kellyROI=%+.4f growth=%+.4f | flatROI=%+.4f CI[%+.4f,%+.4f]"%(
        lbl,r["bets"],r["ROI"],r["final"]/10000-1,flat.mean() if len(flat) else np.nan,ci[0],ci[1]))
print("\nEV_lo>0 plays per season:")
print(c[c.EV_lo>0].groupby("season").agg(n=("won","size"),won=("won","sum")).to_string())
# both sides of same game flagged?
g=c[c.EV>0].groupby("game_id").size()
print("\ngames where BOTH moneyline sides cleared EV>0: %d"%int((g>1).sum()))
