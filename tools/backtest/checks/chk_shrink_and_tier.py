import numpy as np, pandas as pd
from scipy import stats
c=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_eval_candidates.parquet")
def sig(x): return 1/(1+np.exp(-x))

print("=== what actually drives the EV_lo tier? ===")
sel=c[c.EV_lo>0]
print("corr(EV_lo, dec) over ALL candidates  : %+.3f"%np.corrcoef(c.EV_lo,c.dec)[0,1])
print("corr(EV_lo, |edge|) over ALL candidates: %+.3f"%np.corrcoef(c.EV_lo,c.edge.abs())[0,1])
print("among the 118 gated plays: corr(EV_lo, dec) %+.3f   corr(EV_lo, edge) %+.3f"
      %(np.corrcoef(sel.EV_lo,sel.dec)[0,1],np.corrcoef(sel.EV_lo,sel.edge)[0,1]))
print("mean decimal price by tier:")
print(c.groupby("tier").agg(n=("dec","size"),mean_dec=("dec","mean"),mean_edge=("edge","mean"),
                            mean_D=("D","mean"),mean_seD=("se_D","mean")).round(3).to_string())

print("\n=== apply the harness's OWN out-of-sample shrinkage gamma_D = 0.3818 ===")
print("(fit.py section 7: gamma_D=+0.38 means D is ~2.6x too big out of sample)")
for gam in (1.0,0.5,0.3818,0.0):
    u=c.sign*(c.offset+gam*c.D)
    ev=sig(u)*c.dec-1.0
    ulo=u-1.64*gam*c.se_D
    evlo=sig(ulo)*c.dec-1.0
    won=c.won.to_numpy()
    m=(evlo>0).to_numpy()
    r=np.where(won[m]==1,c.dec.to_numpy()[m]-1.0,-1.0)
    print("  gamma=%.4f :  EV>0 n=%4d   EV_lo>0 n=%4d   DIAMOND n=%3d   flat ROI of gate %s"
          %(gam,int((ev>0).sum()),int(m.sum()),int((evlo>=0.03).sum()),
            ("%+.4f"%r.mean()) if m.sum() else "n/a"))

print("\n=== the gate's own hit-rate vs the break-even it needs ===")
be=1.0/sel.dec
print("118 gated plays: actual win rate %.4f ; mean break-even needed %.4f ; shortfall %+.4f"
      %(sel.won.mean(),be.mean(),sel.won.mean()-be.mean()))
print("binomial p (one-sided, vs mean break-even): %.3f"
      %stats.binomtest(int(sel.won.sum()),len(sel),float(be.mean()),alternative='greater').pvalue)
