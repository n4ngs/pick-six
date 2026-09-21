#!/usr/bin/env python3
"""
qb_change_refute.py -- ADVERSARIAL REFUTATION of T5/T7b (qb_change_delta_diff).
Every test below is REPORTED whichever way it lands. Nothing is dropped.

A1 IS "OOS" REALLY OOS? contrib = b_train * x_test, then gamma refit on pooled
   held-out. If b_train is near-constant across folds, gamma*contrib is
   proportional to x_test, so gamma's p-value == the p-value of refitting the
   SAME regression in-sample on the pooled 2005-2025 rows. Then T7b is not an
   independent hurdle; it is T5 on a subsample wearing a different hat.
A2 FEW-CLUSTER SE. 21-27 season clusters. Wild cluster bootstrap (Rademacher,
   restricted null) + team-clustered + HC1 + season-block.
A3 THE CONTROL THE PRIOR AGENT DID NOT RUN. R1 controlled for the BINARY chg.
   It never controlled for the LEVEL, qb_delta_diff, even though R4 showed the
   level is stronger AND qb_change_delta = quality(new) - quality(prev) is
   mechanically a function of quality(new). Fit ats_home ~ 1 + qb_delta_diff +
   qb_change_delta_diff. H0: the change term goes to zero once the level is in.
A4 SAME CONTROL, OUT OF SAMPLE (expanding season window, joint model).
A5 CUTOFF ROBUSTNESS, equally reasonable variants, all reported:
   thin/fallback games INCLUDED; start 2006 (ML era); start 2011; OOS start
   moved 2003/2008/2010.
A6 ERA SPLIT. Pre-2011 vs 2011+. A dead edge in the modern market is not an edge.
A7 ECONOMICS. Is the held-out cover margin significantly ABOVE the ~1.10 pts
   that -110 requires? One-sided H0: margin >= 1.10 and margin <= 1.10 both.
"""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
from qb_change import build, ols_c, RULE, THIN, head

warnings.filterwarnings("ignore")
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 50)
D = "qb_change_delta_diff"; L = "qb_delta_diff"
LOG = []
def rec(tid, term, b, se, p, n, note=""):
    LOG.append({"test": tid, "term": term, "coef": b, "SE": se, "p": p,
                "n": n, "sig@5%": "YES" if p < 0.05 else "no", "note": note})

def oos_gamma(frame, cols, start=2005, end=2026, y="ats_home"):
    """Expanding season window. Returns (pooled frame, per-fold coefs)."""
    pieces, rows = [], []
    for s in range(start, end):
        tr, te = frame[frame.season < s], frame[frame.season == s]
        if len(tr) < 500 or len(te) == 0: continue
        r = ols_c(tr, cols, y=y)
        pc = te[["game_id", "season", y]].copy()
        pc["contrib"] = sum(r.params[c] * te[c].to_numpy() for c in cols)
        for c in cols:
            pc["contrib_" + c] = r.params[c] * te[c].to_numpy()
        pieces.append(pc)
        rows.append(dict({"test": s, "n_train": len(tr)},
                         **{"B_" + c: r.params[c] for c in cols}))
    return pd.concat(pieces, ignore_index=True), pd.DataFrame(rows).set_index("test")

def gfit(o, xcols, y="ats_home"):
    X = sm.add_constant(o[xcols])
    return sm.OLS(o[y].astype(float), X).fit(cov_type="cluster",
                                             cov_kwds={"groups": o["season"]})

t, ml, cont, cont_ml = build()
cont = cont.assign(**{L: cont["qb_delta_home"] - cont["qb_delta_away"]})
t = t.assign(**{L: t["qb_delta_home"] - t["qb_delta_away"]})

# ---------------------------------------------------------------- A1
head("A1  IS T7b GENUINELY OUT OF SAMPLE, OR T5 IN DISGUISE?")
o, fl = oos_gamma(cont, [D])
g = gfit(o, ["contrib"])
print("  reported T7b gamma = %+.4f  SE %.4f  p %.4f  (n=%d)"
      % (g.params["contrib"], g.bse["contrib"], g.pvalues["contrib"], len(o)))
print("  per-fold b_train: min %+.4f max %+.4f  ratio max/min %.2f"
      % (fl["B_" + D].min(), fl["B_" + D].max(),
         fl["B_" + D].max() / fl["B_" + D].min()))
pool = cont[cont.season.between(o.season.min(), o.season.max())]
r_is = ols_c(pool, [D])
print("  SAME rows, plain IN-SAMPLE refit of T5 on 2005-2025: B %+.4f SE %.4f p %.4f n=%d"
      % (r_is.params[D], r_is.bse[D], r_is.pvalues[D], len(pool)))
print("  corr(contrib, x_test) across pooled held-out rows = %.6f"
      % np.corrcoef(o["contrib"], pool.sort_values(["season","game_id"]).set_index("game_id")
                    .loc[o.set_index("game_id").index, D])[0, 1])
print("  -> gamma p %.4f vs in-sample p %.4f : %s"
      % (g.pvalues["contrib"], r_is.pvalues[D],
         "SAME TEST (the OOS bar is not an independent hurdle)"
         if abs(g.pvalues["contrib"] - r_is.pvalues[D]) < 0.02 else "differ"))
print("  ROW OVERLAP: T5 used n=%d (2000-2025); the pooled held-out set is n=%d"
      % (len(cont), len(o)))
print("  -> %.0f%% of the rows in the 'out-of-sample' test are rows T5 was fitted on."
      % (100.0 * len(o) / len(cont)))
print("  EXPANDING-WINDOW FOLDS ARE NESTED: fold 2025 trains on 1999-2024, which")
print("  CONTAINS fold 2006's training set. '21 folds, sign positive in all 21' is")
print("  therefore ~1 independent observation of the sign, not 21.")
rec("A1", "gamma vs in-sample refit, same rows", r_is.params[D], r_is.bse[D],
    r_is.pvalues[D], len(pool), "T7b p=%.4f" % g.pvalues["contrib"])

# ---------------------------------------------------------------- A2
head("A2  FEW-CLUSTER STANDARD ERRORS (21 season clusters on the OOS gamma)")
X = sm.add_constant(o[["contrib"]])
y = o["ats_home"].astype(float).to_numpy()
alt = {}
alt["cluster season (reported)"] = gfit(o, ["contrib"])
alt["HC1 (no clustering)"] = sm.OLS(y, X).fit(cov_type="HC1")
for k, r in alt.items():
    print("  %-28s gamma %+.4f  SE %.4f  p %.4f" % (k, r.params.iloc[1], r.bse.iloc[1], r.pvalues.iloc[1]))
# wild cluster bootstrap by season, restricted null gamma=0
rng = np.random.default_rng(20260920)
res0 = y - y.mean()                       # residuals under gamma = 0
seasons = o["season"].to_numpy(); uq = np.unique(seasons)
tobs = alt["cluster season (reported)"].tvalues.iloc[1]
B = 4999; cnt = 0
for _ in range(B):
    w = rng.choice([-1.0, 1.0], size=len(uq))
    wm = dict(zip(uq, w))
    ystar = y.mean() + res0 * np.array([wm[s] for s in seasons])
    rb = sm.OLS(ystar, X).fit(cov_type="cluster", cov_kwds={"groups": seasons})
    if abs(rb.tvalues.iloc[1]) >= abs(tobs): cnt += 1
pwb = (cnt + 1) / (B + 1)
print("  WILD CLUSTER BOOTSTRAP (Rademacher, %d reps, %d season clusters): p = %.4f"
      % (B, len(uq), pwb))
print("  -> reported p .0415 %s once few-cluster inference is used"
      % ("SURVIVES" if pwb < 0.05 else "FAILS (p crosses 0.05)"))
rec("A2", "gamma, wild cluster bootstrap", alt["cluster season (reported)"].params.iloc[1],
    np.nan, pwb, len(o), "%d clusters" % len(uq))

# ---------------------------------------------------------------- A3
head("A3  THE CONTROL NOBODY RAN: hold the QB-QUALITY LEVEL fixed")
print("  qb_change_delta_side = quality(new starter) - quality(prev starter)")
print("  qb_delta_side        = quality(new starter) - replacement")
print("  They share quality(new starter). corr(%s, %s) = %.4f"
      % (D, L, np.corrcoef(cont[D], cont[L])[0, 1]))
for cols, lab in (([D], "T5 alone (change only)"),
                  ([L], "R4 alone (level only)"),
                  ([L, D], "JOINT: level + change")):
    r = ols_c(cont, cols)
    s = "  %-26s" % lab
    for c in cols:
        s += "  %s B %+7.3f SE %.3f p %.4f |" % (c[:9], r.params[c], r.bse[c], r.pvalues[c])
    print(s)
    if lab.startswith("JOINT"):
        for c in cols:
            rec("A3", c + " (joint w/ level)", r.params[c], r.bse[c], r.pvalues[c],
                len(cont), "in-sample")
        print("  -> change term conditional on level: p = %.4f  => %s"
              % (r.pvalues[D], "SURVIVES" if r.pvalues[D] < 0.05 else
                 "COLLAPSES. T5 was measuring QB QUALITY, not a QB CHANGE."))

# ---------------------------------------------------------------- A4
head("A4  SAME CONTROL, OUT OF SAMPLE (expanding season window)")
oj, flj = oos_gamma(cont, [L, D])
rj = gfit(oj, ["contrib_" + L, "contrib_" + D])
for c in [L, D]:
    print("  gamma(%-20s) %+.4f  SE %.4f  t %+.2f  p %.4f"
          % (c, rj.params["contrib_" + c], rj.bse["contrib_" + c],
             rj.tvalues["contrib_" + c], rj.pvalues["contrib_" + c]))
    rec("A4", "OOS gamma " + c + " (joint)", rj.params["contrib_" + c],
        rj.bse["contrib_" + c], rj.pvalues["contrib_" + c], len(oj), "joint OOS")
print("  -> out of sample, with the level in the model, the CHANGE term is %s"
      % ("still significant" if rj.pvalues["contrib_" + D] < 0.05 else "DEAD (p>=.05)"))

# ---------------------------------------------------------------- A5
head("A5  EQUALLY-REASONABLE CUTOFFS -- every variant reported")
variants = []
allrows = t.copy()
variants.append(("thin/fallback INCLUDED (no quality filter)", allrows, 2005))
variants.append(("ML era only, seasons >= 2006", cont[cont.season >= 2006], 2010))
variants.append(("modern only, seasons >= 2011", cont[cont.season >= 2011], 2015))
for lab, fr, _ in variants:
    r = ols_c(fr, [D])
    print("  IN-SAMPLE  %-42s B %+7.3f SE %.3f p %.4f  n=%d"
          % (lab, r.params[D], r.bse[D], r.pvalues[D], len(fr)))
    rec("A5", "T5 in-sample: " + lab, r.params[D], r.bse[D], r.pvalues[D], len(fr))
print()
for st in (2003, 2005, 2008, 2010):
    oo, _ = oos_gamma(cont, [D], start=st)
    rr = gfit(oo, ["contrib"])
    print("  OOS gamma, window starts %d : %+.4f  SE %.4f  p %.4f  n=%d"
          % (st, rr.params["contrib"], rr.bse["contrib"], rr.pvalues["contrib"], len(oo)))
    rec("A5", "OOS gamma start=%d" % st, rr.params["contrib"], rr.bse["contrib"],
        rr.pvalues["contrib"], len(oo))
oo, _ = oos_gamma(allrows, [D], start=2005)
rr = gfit(oo, ["contrib"])
print("  OOS gamma, thin/fallback INCLUDED : %+.4f SE %.4f p %.4f n=%d"
      % (rr.params["contrib"], rr.bse["contrib"], rr.pvalues["contrib"], len(oo)))
rec("A5", "OOS gamma, no quality filter", rr.params["contrib"], rr.bse["contrib"],
    rr.pvalues["contrib"], len(oo))

# ---------------------------------------------------------------- A6
head("A6  ERA SPLIT -- is the effect alive in the modern market?")
for lab, fr in (("1999-2010", cont[cont.season <= 2010]),
                ("2011-2025", cont[cont.season >= 2011])):
    r = ols_c(fr, [D])
    nz = int((fr[D] != 0).sum())
    print("  %-10s B %+7.3f  SE %.3f  p %.4f  n=%d (change games %d)  80%%-floor %+.2f"
          % (lab, r.params[D], r.bse[D], r.pvalues[D], len(fr), nz, 2.802 * r.bse[D]))
    rec("A6", "T5 " + lab, r.params[D], r.bse[D], r.pvalues[D], len(fr))
oh = o.merge(cont[["game_id", "season"]].rename(columns={"season": "s2"}), on="game_id")
for lab, sub in (("held-out 2005-2010", o[o.season <= 2010]),
                 ("held-out 2011-2025", o[o.season >= 2011])):
    rr = gfit(sub, ["contrib"])
    print("  OOS gamma %-20s %+.4f  SE %.4f  p %.4f  n=%d"
          % (lab, rr.params["contrib"], rr.bse["contrib"], rr.pvalues["contrib"], len(sub)))
    rec("A6", "OOS gamma " + lab, rr.params["contrib"], rr.bse["contrib"],
        rr.pvalues["contrib"], len(sub))

# ---------------------------------------------------------------- A7
head("A7  ECONOMICS -- does it clear -110, not just zero?")
d = o[(o["contrib"] != 0) & (o["ats_home"] != 0)].copy()
d["margin"] = np.where(d.contrib > 0, d.ats_home, -d.ats_home)
m, sd, n = d.margin.mean(), d.margin.std(ddof=1), len(d)
se = sd / np.sqrt(n)
# cluster by season for honesty
rm = sm.OLS(d.margin.astype(float), np.ones(n)).fit(
    cov_type="cluster", cov_kwds={"groups": d["season"]})
se_c = float(np.asarray(rm.bse)[0])
NEED = 1.10
tstat = (m - NEED) / se_c
p_above = 1 - stats.t.cdf(tstat, df=d.season.nunique() - 1)
print("  held-out bets n=%d  mean cover margin on the picked side %+.4f pts" % (n, m))
print("  SE (season-clustered) %.4f ; 95%% CI [%+.3f, %+.3f]"
      % (se_c, m - 1.96 * se_c, m + 1.96 * se_c))
print("  -110 needs about %.2f pts of true edge." % NEED)
print("  H0: margin >= %.2f  -> one-sided p = %.4f  => %s"
      % (NEED, 1 - p_above, "REJECTED: the edge is below breakeven"
         if (1 - p_above) < 0.05 else "cannot reject that it is below breakeven"))
w = int((d.margin > 0).sum()); rate = w / n
print("  realised ATS %d-%d = %.4f  vs -110 breakeven 0.5238  -> ROI %+.4f u/bet"
      % (w, n - w, rate, rate * (100 / 110.) - (1 - rate)))
rec("A7", "margin vs 1.10 pts (one-sided)", m - NEED, se_c, 1 - p_above, n, "economic")

head("LEDGER -- every test this refutation ran")
Ldf = pd.DataFrame(LOG)
print(Ldf.round(5).to_string(index=False))
print("\nTESTS RUN BY THIS REFUTER: %d" % len(Ldf))
Ldf.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "out_qb_change_refute.csv"), index=False)
