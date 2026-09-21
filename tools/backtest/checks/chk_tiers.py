import numpy as np, pandas as pd
c=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_eval_candidates.parquet")
print("candidates %d, games %d"%(len(c),c.game_id.nunique()))
for tier in ["DIAMOND","GOLD","SILVER"]:
    g=c[c.tier==tier]
    if not len(g): continue
    r=np.where(g.won==1,g.dec-1.0,-1.0)
    print("\n--- %s  n=%d ---"%(tier,len(g)))
    print("  side: %d home / %d away ; dec mean %.2f median %.2f max %.2f"%((g.side=='home').sum(),(g.side=='away').sum(),g.dec.mean(),g.dec.median(),g.dec.max()))
    print("  underdogs (dec>2): %d (%.0f%%) ; won %d (%.1f%%)"%((g.dec>2).sum(),100*(g.dec>2).mean(),g.won.sum(),100*g.won.mean()))
    print("  flat units %+.2f  ROI %+.4f"%(r.sum(),r.mean()))
    top=g.assign(ret=r).nlargest(3,"ret")[["season","week","team","side","american","dec","won","ret","EV_lo"]]
    print("  three biggest single-bet returns:"); print(top.round(3).to_string(index=False))
    print("  flat units EXCLUDING the single best bet: %+.2f  ROI %+.4f"%(r.sum()-r.max(),(r.sum()-r.max())/(len(r)-1)))
    print("  flat units EXCLUDING the 3 best bets   : %+.2f  ROI %+.4f"%(r.sum()-np.sort(r)[-3:].sum(),(r.sum()-np.sort(r)[-3:].sum())/(len(r)-3)))
    print("  by season:"); print(g.assign(ret=r).groupby("season").agg(n=("ret","size"),won=("won","sum"),units=("ret","sum")).round(2).to_string())

print("\n=== price sensitivity on a FIXED play set (the honest version) ===")
sel=c[c.EV_lo>0]
r0=np.where(sel.won==1,sel.dec-1.0,-1.0)
def worsen(dec,cents=10.0):
    dec=np.asarray(dec,float)
    ml=np.where(dec>=2.0,(dec-1.0)*100.0,-100.0/(dec-1.0))-cents
    ml=np.where((ml>=0)&(ml<100),-200.0+ml,ml)
    return np.where(ml>0,1+ml/100.0,1+100.0/np.abs(ml))
dw=worsen(sel.dec.to_numpy())
r1=np.where(sel.won==1,dw-1.0,-1.0)
print("same 118 plays: flat ROI at close %+.4f -> 10c worse %+.4f"%(r0.mean(),r1.mean()))
print("evaluate.py instead RE-SELECTS at the worse price (n 118 -> 35) and prints a HIGHER ROI.")
