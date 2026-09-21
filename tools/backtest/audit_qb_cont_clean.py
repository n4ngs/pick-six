#!/usr/bin/env python3
"""
A2c: rerun the CONTINUOUS arm (T5) and the R4 LEVEL comparison with the
starter defined as the pbp FIRST-SNAP QB instead of the games.csv listed
qb_id, so no label can be set by what happened inside the game.
Same shrinkage K=400 fixed a priori as in audit_qb_recompute.py.
"""
import os, sys
import numpy as np, pandas as pd, statsmodels.api as sm
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.abspath(os.path.join(HERE,"..","..","data","nflverse"))
pd.set_option("display.width",220)
K = 400.0
ABBR = {"STL":"LA","SD":"LAC","OAK":"LV"}

rows=[]
for s in range(1999,2026):
    d = pd.read_parquet(os.path.join(DATA,"play_by_play_%d.parquet"%s),
        columns=["game_id","posteam","qb_dropback","passer_player_id","rusher_player_id","play_id"])
    d = d[d.qb_dropback.eq(1)].copy()
    d["qb"] = d.passer_player_id.fillna(d.rusher_player_id)
    d = d[d.qb.notna()].sort_values(["game_id","play_id"])
    rows.append(d.groupby(["game_id","posteam"]).qb.first().rename("first_qb").reset_index())
FS = pd.concat(rows, ignore_index=True)

cum_n = pd.read_parquet(os.path.join(HERE,"out_audit_cumn.parquet"))
cum_s = pd.read_parquet(os.path.join(HERE,"out_audit_cums.parquet"))
cum_n.index = cum_n.index.astype(int); cum_s.index = cum_s.index.astype(int)
mu = (cum_s.sum(axis=1) / cum_n.sum(axis=1).replace(0,np.nan)).fillna(0.0)
def q_of(ti, qb):
    if not isinstance(qb,str) or ti not in cum_n.index or qb not in cum_n.columns:
        return np.nan, 0.0
    n=float(cum_n.at[ti,qb]); s=float(cum_s.at[ti,qb]); m=float(mu.loc[ti])
    return (s+K*m)/(n+K), n

g = pd.read_csv(os.path.join(DATA,"games.csv"), low_memory=False).dropna(subset=["result"])
g = g[g.season.between(1999,2025)].copy()
long = pd.concat([
  g[["game_id","season","week","home_team"]].rename(columns={"home_team":"posteam"}).assign(side="home"),
  g[["game_id","season","week","away_team"]].rename(columns={"away_team":"posteam"}).assign(side="away")])
long["posteam"]=long.posteam.replace(ABBR)
long = long.merge(FS, on=["game_id","posteam"], how="left")
long["ti"]=long.season*100+long.week
long = long.sort_values(["posteam","ti","game_id"])
long["prev"]=long.groupby("posteam").first_qb.shift(1)
long["known"]=long.prev.notna()&long.first_qb.notna()
long["changed"]=long.known&(long.first_qb!=long.prev)
qs,ns,ps=[],[],[]
for ti,q,pq in zip(long.ti,long.first_qb,long.prev):
    a,b=q_of(ti,q); qs.append(a); ns.append(b); ps.append(q_of(ti,pq)[0])
long["q"]=qs; long["prior_db"]=ns; long["prev_q"]=ps
long["cd"]=np.where(long.changed, long.q-long.prev_q, 0.0)

w = long.pivot_table(index="game_id", columns="side", values=["changed","q","cd","prior_db","known"], aggfunc="first")
w.columns=["%s_%s"%(a,b) for a,b in w.columns]; w=w.reset_index()
t = g.merge(w,on="game_id",how="inner",validate="1:1")
t = t[t.spread_line.notna()&t.known_home.astype(bool)&t.known_away.astype(bool)].copy()
h=t.changed_home.astype(bool).to_numpy(); a=t.changed_away.astype(bool).to_numpy()
t["chg"]=np.where(h&~a,1,np.where(a&~h,-1,0))
t["ats_home"]=t.result-t.spread_line
t["cd_diff"]=t.cd_home-t.cd_away; t["q_diff"]=t.q_home-t.q_away
c = t[(t.prior_db_home>=100)&(t.prior_db_away>=100)].copy()

def ols(d,cols):
    X=sm.add_constant(d[cols].astype(float))
    return sm.OLS(d.ats_home.astype(float),X).fit(cov_type="cluster",cov_kwds={"groups":d.season})
def rep(n_,r,tm,sd=None,theirs=None):
    b,se,p=r.params[tm],r.bse[tm],r.pvalues[tm]
    s="%-40s B=%+.4f SE=%.4f p=%.4f 80%%-floor %.4f"%(n_,b,se,p,2.802*se)
    if sd is not None: s+=" | per sd %+.4f pts (floor %.4f)"%(b*sd,2.802*se*sd)
    if theirs: s+="  [listed-QB: %s]"%theirs
    print(s)

print("FIRST-SNAP starter definition. sample n=%d, continuous n=%d (non-zero cd %d)"
      %(len(t),len(c),int((c.cd_diff!=0).sum())))
rep("T5 change-delta (first-snap)", ols(c,["cd_diff"]),"cd_diff",
    sd=c.cd_diff.std(), theirs="+7.717 p=.0085, +0.422/sd")
rep("R4 LEVEL (first-snap)", ols(c,["q_diff"]),"q_diff",
    sd=c.q_diff.std(), theirs="+4.019 p=.0013, +0.483/sd")
r=ols(c,["cd_diff","q_diff"])
print("  joint:")
rep("    change | level", r,"cd_diff", sd=c.cd_diff.std())
rep("    level | change", r,"q_diff", sd=c.q_diff.std())
print("\nOOS (expanding season window, train<S test S, 2005-2025):")
for lab,col in (("change",'cd_diff'),("level",'q_diff')):
    pieces=[]
    for s_ in range(2005,2026):
        tr,te=c[c.season<s_],c[c.season==s_]
        if len(tr)<500 or len(te)==0: continue
        b=ols(tr,[col]).params[col]
        pc=te[["season","ats_home"]].copy(); pc["contrib"]=b*te[col].to_numpy()
        pieces.append(pc)
    o=pd.concat(pieces,ignore_index=True)
    X=sm.add_constant(pd.DataFrame({"gamma":o.contrib.to_numpy()}))
    rg=sm.OLS(o.ats_home.astype(float),X).fit(cov_type="cluster",cov_kwds={"groups":o.season})
    d2=o[o.ats_home!=0].copy(); d2["won"]=np.where(d2.contrib>0,d2.ats_home>0,d2.ats_home<0)
    d2=d2[d2.contrib!=0]
    rate=d2.won.mean(); roi=rate*(100/110.)-(1-rate)
    print("  %-7s gamma %+.4f (SE %.4f, p %.4f) n=%d | OOS ATS %d-%d = %.4f vs .5238, ROI %+.4f u/bet"
          %(lab,rg.params.gamma,rg.bse.gamma,rg.pvalues.gamma,len(o),
            int(d2.won.sum()),int((~d2.won).sum()),rate,roi))
