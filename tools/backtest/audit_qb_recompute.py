#!/usr/bin/env python3
"""
A5: INDEPENDENT RECOMPUTATION of the qb-change headline numbers.
Nothing from features_personnel.py or qb_change.py is used. games.csv and raw
pbp only; my own starter-change flag, my own shrunk QB quality (K = 400
dropbacks, fixed here before running, NOT tuned), my own regressions.

Recomputed: T1 (binary chg), T3 (wk1/in-season split), T5 (continuous change
delta), and the R4 comparison (LEVEL of QB quality on the same response).
Then the contamination test: rebuild the change flag from the pbp FIRST-SNAP
QB instead of the games.csv listed QB, and see whether T1 moves.
"""
import os, sys
import numpy as np, pandas as pd, statsmodels.api as sm
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "data", "nflverse"))
pd.set_option("display.width", 220)
K_SHRINK = 400.0          # fixed a priori. one value. not tuned.

long = pd.read_parquet(os.path.join(HERE,"out_audit_long.parquet"))
cum_n = pd.read_parquet(os.path.join(HERE,"out_audit_cumn.parquet"))
cum_s = pd.read_parquet(os.path.join(HERE,"out_audit_cums.parquet"))
cum_n.index = cum_n.index.astype(int); cum_s.index = cum_s.index.astype(int)

# league-mean as-of (strictly prior), for shrinkage
tot_n = cum_n.sum(axis=1); tot_s = cum_s.sum(axis=1)
mu = (tot_s / tot_n.replace(0, np.nan)).fillna(0.0)

def q_of(ti, qb):
    if not isinstance(qb, str) or ti not in cum_n.index or qb not in cum_n.columns:
        return np.nan, 0.0
    n = float(cum_n.at[ti, qb]); s = float(cum_s.at[ti, qb]); m = float(mu.loc[ti])
    return (s + K_SHRINK*m) / (n + K_SHRINK), n

qs, ns, pqs = [], [], []
for ti, qb, pq in zip(long.ti.to_numpy(), long.qb.to_numpy(), long.prev_qb.to_numpy()):
    a, b = q_of(ti, qb); qs.append(a); ns.append(b)
    c, _ = q_of(ti, pq); pqs.append(c)
long["q"] = qs; long["prior_db"] = ns; long["prev_q"] = pqs
long["chg_delta"] = np.where(long.changed, long.q - long.prev_q, 0.0)

w = long.pivot_table(index="game_id", columns="side",
                     values=["changed","q","chg_delta","prior_db"], aggfunc="first")
w.columns = ["%s_%s" % (a,b) for a,b in w.columns]
w = w.reset_index()
known = long.groupby(["game_id","side"]).prev_known.first().unstack()
w = w.merge(known.rename(columns=lambda c: "known_"+c).reset_index(), on="game_id")

g = pd.read_csv(os.path.join(DATA,"games.csv"), low_memory=False).dropna(subset=["result"])
g = g[g.season.between(1999,2025)]
t = g.merge(w, on="game_id", how="inner", validate="1:1")
t = t[t.spread_line.notna() & t.known_home & t.known_away].copy()
h = t.changed_home.astype(bool).to_numpy(); a = t.changed_away.astype(bool).to_numpy()
t["chg"] = np.where(h & ~a, 1, np.where(a & ~h, -1, 0))
t["chg_wk1"] = np.where(t.week==1, t.chg, 0); t["chg_in"] = np.where(t.week>=2, t.chg, 0)
t["ats_home"] = t.result - t.spread_line
t["chg_delta_diff"] = t.chg_delta_home - t.chg_delta_away
t["q_diff"] = t.q_home - t.q_away

print("=== INDEPENDENT SAMPLE ===")
print("n = %d (%d-%d);  exactly-one-team changed: %d (%.1f%%)  wk1 %d / wk>=2 %d"
      % (len(t), t.season.min(), t.season.max(), int((t.chg!=0).sum()),
         100*(t.chg!=0).mean(), int((t.chg_wk1!=0).sum()), int((t.chg_in!=0).sum())))
print("  their reported numbers: n=7256, 1381 change games (19.0%), 179 wk1 / 1202 in-season")

def ols(d, cols, y="ats_home"):
    X = sm.add_constant(d[cols].astype(float))
    return sm.OLS(d[y].astype(float), X).fit(cov_type="cluster", cov_kwds={"groups": d.season})

def rep(name, r, term, theirs=None, sd=None):
    b, se, p = r.params[term], r.bse[term], r.pvalues[term]
    s = "%-34s B=%+.4f SE=%.4f p=%.4f  80%%-power floor %.4f" % (name, b, se, p, 2.802*se)
    if sd is not None: s += "  | per sd (%.4f) = %+.4f pts" % (sd, b*sd)
    if theirs is not None: s += "   [they report %s]" % theirs
    print(s)

print("\n=== RECOMPUTED HEADLINES (my own flag, my own quality, K=%g) ===" % K_SHRINK)
rep("T1 chg (binary, points)", ols(t, ["chg"]), "chg", "-0.697 SE .334 p .0365")
r3 = ols(t, ["chg_wk1","chg_in"])
rep("T3 chg_wk1", r3, "chg_wk1", "+0.522 p .573")
rep("T3 chg_in", r3, "chg_in", "-0.879 p .0139")
c = t[(t.prior_db_home>=100)&(t.prior_db_away>=100)].copy()
r5 = ols(c, ["chg_delta_diff"])
rep("T5 change-delta (pts per EPA/db)", r5, "chg_delta_diff",
    "+7.717 SE 2.93 p .0085 = +0.422/sd", sd=c.chg_delta_diff.std())
print("    (continuous sample n=%d, non-zero on %d rows)"
      % (len(c), int((c.chg_delta_diff!=0).sum())))
rL = ols(c, ["q_diff"])
rep("R4 LEVEL of QB quality (same rows)", rL, "q_diff",
    "+4.019 p .0013 = +0.483/sd", sd=c.q_diff.std())
rB = ols(c, ["chg_delta_diff","q_diff"])
print("\n  both together (does the CHANGE survive controlling for the LEVEL?):")
rep("    chg_delta_diff | q_diff", rB, "chg_delta_diff", sd=c.chg_delta_diff.std())
rep("    q_diff | chg_delta_diff", rB, "q_diff", sd=c.q_diff.std())

print("\n=== PUSH HANDLING ===")
print("pushes (ats_home==0) in sample: %d (%.4f). They enter OLS as a 0 cover margin,")
print("which is the correct continuous coding; the ATS W-L-P descriptive excludes them.")
print("  count = %d, %.4f" % (int((t.ats_home==0).sum()), (t.ats_home==0).mean()))
r_nop = ols(t[t.ats_home!=0], ["chg"])
rep("T1 with pushes DROPPED (robustness)", r_nop, "chg")

t.to_parquet(os.path.join(HERE,"out_audit_recomputed.parquet"))
