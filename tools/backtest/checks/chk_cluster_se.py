import sys
sys.path.insert(0,"/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from fit import logit, VECTOR_COL, VECTORS, COMP_COLS, glm_fit, CV_TEST_SEASONS, sigmoid

d=pd.read_parquet("/Users/cmanlongat/Projects/pick-six/tools/backtest/out_fit_table.parquet")
off=logit(d["p_mkt_mult"].to_numpy())
y=d["home_win"].to_numpy(float)

def show(cols,label):
    X=d[cols]
    base=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit()
    out={"B":base.params,"SE_naive":base.bse,"p_naive":base.pvalues}
    # cluster by season
    for cname,grp in (("season",d["season"]),("home_team",d["home_team"]),("week_of_season",d["season"].astype(str)+"_"+d["week"].astype(str))):
        try:
            rc=sm.GLM(y,X,family=sm.families.Binomial(),offset=off).fit(cov_type="cluster",
                 cov_kwds={"groups":grp.to_numpy(),"use_correction":True})
            out["SE_cl_"+cname]=rc.bse; out["p_cl_"+cname]=rc.pvalues
        except Exception as e:
            print("  cluster %s failed: %s"%(cname,e))
    print("\n=== %s (n=%d) ==="%(label,len(d)))
    print(pd.DataFrame(out).round(4).to_string())

show([VECTOR_COL[v] for v in VECTORS],"4-vector spec")
show(COMP_COLS,"component spec (the one with f_eff p=0.008)")

# two-way-ish: cluster on the game's two teams is not directly possible; use a
# team-level bootstrap instead for the component spec.
print("\n=== team-cluster bootstrap for f_eff (resample TEAMS, both sides) ===")
rng=np.random.default_rng(11)
teams=sorted(set(d.home_team)|set(d.away_team))
bs=[]
for _ in range(600):
    pick=rng.choice(teams,len(teams),replace=True)
    idx=[]
    for t in pick:
        idx.append(d.index[(d.home_team==t)|(d.away_team==t)].to_numpy())
    idx=np.concatenate(idx)
    dd=d.loc[idx]
    try:
        r=sm.GLM(dd.home_win.to_numpy(float),dd[COMP_COLS],family=sm.families.Binomial(),
                 offset=logit(dd["p_mkt_mult"].to_numpy())).fit()
        bs.append(r.params["f_eff"])
    except Exception: pass
bs=np.array(bs)
print("f_eff point est -0.3765 ; team-bootstrap SD %.4f ; 95%% CI [%.4f, %.4f] ; frac<0 %.3f"
      %(bs.std(),np.percentile(bs,2.5),np.percentile(bs,97.5),(bs<0).mean()))
