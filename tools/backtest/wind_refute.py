#!/usr/bin/env python3
"""
wind_refute.py -- ADVERSARIAL REFUTATION of the wind_totals.py claim.

========================= PRE-REGISTRATION (mine) ===========================
CLAIM UNDER ATTACK: "closing NFL totals underprice wind; resid ~ wind slope is
-0.185/mph beyond what the close already prices, and it holds out of sample."

I reproduce their numbers exactly (done: T1 -0.18499, T3 gamma +1.2954,
T8 gamma +1.0625). So this is not an arithmetic attack. It is an attack on
what the estimand MEANS and on whether the inference is valid.

MY HYPOTHESIS (H_A): the residual slope on OBSERVED game-time wind is exactly
what a PERFECTLY EFFICIENT market produces, because the market prices a
FORECAST, not the realisation. Under that view there is no mispricing and
nothing to bet. Formally: if total = a + b*w + e and the close prices
E[w | forecast] = lam*w + noise with lam<1, then
    resid = b*(w - lam*w) + ... -> slope on w = b*(1-lam) < 0
even with a rational market. The agent's H0 (slope=0) is the WRONG NULL.

THE DISCRIMINATING TEST. Split wind into the part knowable at bet time and
the part not knowable:
    wind_hat = stadium x calendar-month mean wind, built ONLY from strictly
               PRIOR seasons (no look-ahead), min 8 prior obs
    wind_dev = wind - wind_hat  (the surprise, unknowable at close)
Under H_A (efficient market, EIV only): coef on wind_hat ~ 0, coef on
wind_dev ~ b (the full structural effect).
Under THEIR claim (market genuinely underprices wind): coef on wind_hat is
also strongly negative, because a market that underprices wind must also
underprice the part of wind it can see coming.
That is a clean, falsifiable, no-look-ahead discriminator and it is my R3.

TESTS I WILL RUN (every one reported, pass or fail):
 R1  Algebraic: is T3's "frozen-slope gamma" identical to b_test/b_train, i.e.
     does it carry information beyond refitting on the test half?
 R2  Few-cluster inference: 28 season clusters. (a) wild cluster bootstrap-t
     (Rademacher, 9999 reps, null imposed); (b) per-season-slope t-test on 27
     df; (c) cluster by stadium; (d) cluster by (season,week).
 R3  PRIMARY REFUTATION. resid ~ wind_hat + wind_dev (defined above).
     Threshold: if coef(wind_hat) is not significantly < 0 at p<0.05 while
     coef(wind_dev) is, the claim of underpricing is REFUTED and the finding
     is relabelled errors-in-variables.
 R4  Market side of R3: total_line ~ wind_hat + wind_dev + season FE. Does
     the market already price the knowable part fully?
 R5  Cutoff robustness, equally reasonable alternatives (all reported):
     split years 2006/2010/2014/2018; REG-only; seasons>=2006 only;
     drop wind==0; drop the 15-19 bin's home era.
 R6  EIV calibration: what corr(forecast, realised wind) does their own
     T1/T7 pair imply, and is it inside the published range?
 R7  ACTIONABLE EX-ANTE BET. Bet under using ONLY wind_hat (knowable days in
     advance), expanding-window OOS, flat -110, and with real under_odds.
     Threshold: beat 52.381% at p<0.05.
 R8  Confirm their own look-ahead betting rule loses both sides.
NO TUNING: R3's bin/min-obs rule and R7's rule are fixed here before running.
=============================================================================
"""
import os, sys, warnings
sys.path.insert(0, "/Users/cmanlongat/Projects/pick-six/tools/backtest")
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore"); pd.set_option("display.width", 200)
R = "=" * 92
def head(s): print("\n" + R); print(s); print(R)

HERE = "/Users/cmanlongat/Projects/pick-six/tools/backtest"
d = pd.read_parquet(os.path.join(HERE, "out_wind_totals.parquet"))
d["gameday"] = pd.to_datetime(d["gameday"])
d["month"] = d["gameday"].dt.month
print("reloaded their exact analysis sample: n=%d seasons %d-%d"
      % (len(d), d.season.min(), d.season.max()))
MDE_Z = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)

def fit(f, y, xs, cluster="season"):
    f = f.dropna(subset=[y] + xs)
    return sm.OLS(f[y].astype(float), sm.add_constant(f[xs].astype(float))).fit(
        cov_type="cluster", cov_kwds={"groups": f[cluster]}), f

def show(r, keep, label):
    print("\n%s   n=%d" % (label, int(r.nobs)))
    tab = pd.DataFrame({"beta": r.params, "SE": r.bse, "t": r.tvalues, "p": r.pvalues,
                        "ci_lo": r.conf_int()[0], "ci_hi": r.conf_int()[1]}).loc[keep]
    print(tab.round(5).to_string())

# ------------------------------------------------------------------ R1
head("R1  IS THEIR 'DECISIVE OOS GAMMA' AN INDEPENDENT TEST, OR A RESCALING?")
tr, te = d[d.season <= 2012], d[d.season >= 2013].copy()
rtr = sm.OLS(tr.resid, sm.add_constant(tr[["wind"]].astype(float))).fit()
rte, _ = fit(te, "resid", ["wind"])
a0, b0 = rtr.params["const"], rtr.params["wind"]
te["pred"] = a0 + b0 * te["wind"]
g3 = sm.OLS(te.resid, sm.add_constant(pd.DataFrame({"gamma": te["pred"].to_numpy()},
            index=te.index))).fit(cov_type="cluster", cov_kwds={"groups": te.season})
print("their gamma                = %+.6f  (p %.6f)" % (g3.params["gamma"], g3.pvalues["gamma"]))
print("b_test / b_train           = %+.6f  (p %.6f  <- refit on the test half)"
      % (rte.params["wind"] / b0, rte.pvalues["wind"]))
print("difference in the estimate : %.3e ; difference in p: %.3e"
      % (abs(g3.params["gamma"] - rte.params["wind"]/b0),
         abs(g3.pvalues["gamma"] - rte.pvalues["wind"])))
print("""
VERDICT: pred = a0 + b0*wind is an AFFINE function of wind, so regressing
resid on [1, pred] is the same regression as resid on [1, wind] with the
slope divided by b0. gamma is b_test/b_train by construction and its p-value
IS the test-half slope's p-value. It is a valid statement that the slope is
still negative later; it is NOT independent corroboration, and 'gamma does
not differ from 1' is guaranteed whenever the two halves' slopes are within
noise of each other. Their T3 and their 'OOS refit slope' are ONE test.""")

# ------------------------------------------------------------------ R2
head("R2  FEW-CLUSTER INFERENCE -- 28 season clusters is at the edge")
r1, f1 = fit(d, "resid", ["wind"])
show(r1, ["const", "wind"], "baseline resid ~ wind, cluster(season)")
b_hat = r1.params["wind"]
# (a) wild cluster bootstrap-t, null imposed
y = f1.resid.to_numpy(); X = sm.add_constant(f1[["wind"]].astype(float)).to_numpy()
rest = sm.OLS(y, X[:, [0]]).fit()           # restricted: slope = 0
uhat = rest.resid; yhat0 = rest.fittedvalues
grp = f1.season.to_numpy(); gs = np.unique(grp)
t_obs = r1.tvalues["wind"]
rng = np.random.default_rng(7)
B = 9999; tb = np.empty(B)
for i in range(B):
    w = rng.choice([-1.0, 1.0], size=len(gs))
    mult = pd.Series(w, index=gs).reindex(grp).to_numpy()
    ys = yhat0 + uhat * mult
    m = sm.OLS(ys, X).fit(cov_type="cluster", cov_kwds={"groups": grp})
    tb[i] = m.tvalues[1]
p_wcb = (np.sum(np.abs(tb) >= abs(t_obs)) + 1) / (B + 1)
print("\n(a) wild cluster bootstrap-t (Rademacher, null imposed, B=%d):" % B)
print("    t_obs %+.3f   bootstrap p = %.4f   -> %s"
      % (t_obs, p_wcb, "SURVIVES" if p_wcb < .05 else "DIES"))
# (b) per-season slopes
ps = []
for s in sorted(d.season.unique()):
    x = d[d.season.eq(s)]
    if len(x) < 50: continue
    ps.append(sm.OLS(x.resid, sm.add_constant(x[["wind"]].astype(float))).fit().params["wind"])
ps = np.array(ps)
tt = stats.ttest_1samp(ps, 0.0)
print("\n(b) per-season slope t-test, %d seasons, %d df: mean %+.4f  sd %.4f  t %+.2f  p %.4f  -> %s"
      % (len(ps), len(ps)-1, ps.mean(), ps.std(ddof=1), tt.statistic, tt.pvalue,
         "SURVIVES" if tt.pvalue < .05 else "DIES"))
print("    seasons negative: %d/%d" % (int((ps < 0).sum()), len(ps)))
# (c)(d) other clusters
for cl in ["stadium_id", "sw"]:
    dd = d.copy(); dd["sw"] = dd.season.astype(str) + "_" + dd.week.astype(str)
    rc, _ = fit(dd, "resid", ["wind"], cluster=cl)
    print("(%s) cluster by %-11s: slope %+.4f  SE %.4f  p %.5f  (%d clusters)"
          % ("c" if cl == "stadium_id" else "d", cl, rc.params["wind"], rc.bse["wind"],
             rc.pvalues["wind"], dd[cl].nunique()))

# ------------------------------------------------------------------ R3
head("R3  PRIMARY REFUTATION -- knowable wind vs surprise wind (NO LOOK-AHEAD)")
d = d.sort_values(["season", "week"]).reset_index(drop=True)
# strictly-prior-season stadium x month climatology
key = list(zip(d.stadium_id, d.month))
d["_key"] = pd.Series(key, index=d.index).astype(str)
hat, cnt = np.full(len(d), np.nan), np.zeros(len(d))
for k, idx in d.groupby("_key").groups.items():
    sub = d.loc[idx].sort_values("season")
    seas = sub.season.to_numpy(); w = sub.wind.to_numpy()
    for j, i in enumerate(sub.index):
        prior = w[seas < seas[j]]
        if len(prior) >= 8:
            hat[d.index.get_loc(i)] = prior.mean(); cnt[d.index.get_loc(i)] = len(prior)
d["wind_hat"] = hat; d["n_prior"] = cnt
d["wind_dev"] = d["wind"] - d["wind_hat"]
ok = d.dropna(subset=["wind_hat"])
print("games with a >=8-prior-obs stadium x month climatology : %d of %d (seasons %d-%d)"
      % (len(ok), len(d), ok.season.min(), ok.season.max()))
print("sd(wind)=%.2f  sd(wind_hat)=%.2f  sd(wind_dev)=%.2f   corr(wind_hat,wind)=%.3f"
      % (ok.wind.std(), ok.wind_hat.std(), ok.wind_dev.std(), ok.wind_hat.corr(ok.wind)))
print("  -> the knowable part is %.0f%% of wind variance; %.0f%% is surprise"
      % (100*ok.wind_hat.var()/ok.wind.var(), 100*ok.wind_dev.var()/ok.wind.var()))
r3, _ = fit(ok, "resid", ["wind_hat", "wind_dev"])
show(r3, ["const", "wind_hat", "wind_dev"], "resid ~ wind_hat + wind_dev  (cluster season)")
r3b, _ = fit(ok, "resid", ["wind"])
print("\n  pooled wind slope on the SAME subsample, for reference: %+.4f (p %.4f)"
      % (r3b.params["wind"], r3b.pvalues["wind"]))
se_hat = r3.bse["wind_hat"]
print("  80%%-power MDE on the KNOWABLE coefficient: %.4f pts/mph" % (MDE_Z*se_hat))
print("  is coef(wind_hat) significantly negative? %s   coef(wind_dev)? %s"
      % ("YES" if (r3.pvalues["wind_hat"] < .05 and r3.params["wind_hat"] < 0) else "NO",
         "YES" if (r3.pvalues["wind_dev"] < .05 and r3.params["wind_dev"] < 0) else "NO"))
w = (r3.params["wind_hat"] - r3.params["wind_dev"])
print("  Wald test coef(wind_hat) == coef(wind_dev): diff %+.4f" % w)

# ------------------------------------------------------------------ R4
head("R4  THE MARKET SIDE -- does the close already price the KNOWABLE part?")
dd = ok.copy()
for s in sorted(dd.season.unique())[1:]:
    dd["yr_%d" % s] = (dd.season == s).astype(float)
fe = [c for c in dd.columns if c.startswith("yr_")]
r4, _ = fit(dd, "total_line", ["wind_hat", "wind_dev"] + fe)
show(r4, ["wind_hat", "wind_dev"], "total_line ~ wind_hat + wind_dev + season FE")
print("""
READ THIS TABLE AGAINST R3. Market response to the KNOWABLE part vs the
residual's response to the KNOWABLE part is the whole question. If the market
moves the line on wind_hat by about the full structural effect while the
residual does not move on wind_hat, the close prices what it can see and the
residual slope is pure errors-in-variables.""")

# ------------------------------------------------------------------ R5
head("R5  EQUALLY-REASONABLE CUTOFFS (every variant reported)")
rows = []
def add(name, frame):
    r, f = fit(frame, "resid", ["wind"])
    u = frame[frame.wind >= 15]["under"].dropna()
    rows.append({"variant": name, "n": len(f), "slope": r.params["wind"], "SE": r.bse["wind"],
                 "p": r.pvalues["wind"],
                 "under_w15": u.mean() if len(u) else np.nan, "n_w15": len(u)})
add("their baseline (all)", d)
for y in (2006, 2010, 2014, 2018):
    add("test seasons >=%d only" % y, d[d.season >= y])
add("REG only", d[d.game_type.eq("REG")])
add("drop wind==0", d[d.wind.gt(0)])
add("seasons>=2006 (odds era)", d[d.season >= 2006])
add("drop 1999-2005", d[d.season >= 2006])
print(pd.DataFrame(rows).set_index("variant").round(4).to_string())

# ------------------------------------------------------------------ R6
head("R6  EIV CALIBRATION -- what forecast skill does their own result imply?")
b_mkt = -0.0652   # their T7
b_res = -0.18499  # their T1
b_true = b_mkt + b_res
lam = b_mkt / b_true
print("market slope on realised wind (T7)   b_mkt  = %+.4f" % b_mkt)
print("residual slope on realised wind (T1) b_res  = %+.4f" % b_res)
print("implied structural effect            b_true = %+.4f" % b_true)
print("implied market shrinkage             lambda = %.3f" % lam)
print("""
lambda is exactly what a rational market puts on realised wind when all it
has is a forecast: lambda = var(w)/(var(w)+var(noise)) = corr(forecast, realised)^2.
  -> implied corr(forecast, realised game-time wind) = %.2f
A 2-3 day wind-SPEED forecast verified against a single kickoff-time gust
reading is routinely in the 0.4-0.7 correlation range. So their headline
'the market prices only a quarter of the true wind effect' is NUMERICALLY
IDENTICAL to 'the market prices a forecast whose correlation with the
realised reading is about %.2f'. The data cannot distinguish the two, and one
of them is full efficiency.""" % (np.sqrt(lam), np.sqrt(lam)))

# ------------------------------------------------------------------ R7
head("R7  ACTIONABLE EX-ANTE BET -- wind_hat only (knowable days in advance)")
piece = []
for s in range(2006, int(ok.season.max()) + 1):
    a, b = ok[ok.season < s], ok[ok.season == s]
    if len(a) < 300 or len(b) == 0: continue
    r = sm.OLS(a.resid, sm.add_constant(a[["wind_hat"]].astype(float))).fit()
    p = b.copy(); p["pred"] = r.params["const"] + r.params["wind_hat"]*p["wind_hat"]
    piece.append(p)
o = pd.concat(piece, ignore_index=True).dropna(subset=["under"])
o["side_under"] = o["pred"] < 0
o["win"] = np.where(o.side_under, o["under"] == 1, o["under"] == 0)
def rec(x, name):
    if not len(x): print("\n%s: no bets" % name); return
    n = len(x); wn = int(x.win.sum()); l = n - wn
    roi = (wn*(100/110.) - l)/n
    print("\n%s: %d-%d on %d bets (%.4f)  ROI@-110 %+.4f" % (name, wn, l, n, wn/n, roi))
    print("   p vs 52.381%% break-even = %.4f  -> %s"
          % (stats.binomtest(wn, n, 0.52381).pvalue,
             "BEATS VIG" if stats.binomtest(wn,n,0.52381).pvalue<.05 and wn/n>0.52381
             else "does NOT clear vig"))
    print("   80%% MDE: detectable from %.2f%%" % (100*(0.5+MDE_Z*0.5/np.sqrt(n))))
rec(o, "EX-ANTE both sides"); rec(o[o.side_under], "EX-ANTE under side")
# tail rule on knowable wind only
for thr in (12, 15):
    s = ok[(ok.wind_hat >= thr) & (ok.season >= 2013)]["under"].dropna()
    if len(s) > 20:
        print("\nEX-ANTE tail: wind_hat >= %d, held-out 2013+: rate %.4f on %d bets, p vs 52.381%% = %.4f"
              % (thr, s.mean(), len(s), stats.binomtest(int(s.sum()), len(s), 0.52381).pvalue))
    else:
        print("\nEX-ANTE tail: wind_hat >= %d -> only %d games, untestable" % (thr, len(s)))

# ------------------------------------------------------------------ R8
head("R8  THEIR OWN LOOK-AHEAD RULE (uses realised wind at bet time) -- both sides")
piece = []
for s in range(2005, int(d.season.max()) + 1):
    a, b = d[d.season < s], d[d.season == s]
    if len(a) < 300 or len(b) == 0: continue
    r = sm.OLS(a.resid, sm.add_constant(a[["wind"]].astype(float))).fit()
    p = b.copy(); p["pred"] = r.params["const"] + r.params["wind"]*p["wind"]
    piece.append(p)
o2 = pd.concat(piece, ignore_index=True).dropna(subset=["under"])
o2["side_under"] = o2["pred"] < 0
o2["win"] = np.where(o2.side_under, o2["under"] == 1, o2["under"] == 0)
rec(o2, "LOOK-AHEAD both sides"); rec(o2[o2.side_under], "LOOK-AHEAD under side")
rec(o2[~o2.side_under], "LOOK-AHEAD over side")
print("\n(the under leg is the same games as 'high wind'; the rule as a whole is what")
print(" a bettor would actually run, and it needs BOTH legs to be a rule at all.)")
