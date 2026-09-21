#!/usr/bin/env python3
"""
wind_totals.py -- PRE-REGISTERED test: is wind underpriced in NFL totals?

=========================== PRE-REGISTRATION ================================
Written BEFORE any outcome variable was touched. The only thing inspected
first was DATA AVAILABILITY (roof/wind/temp missingness counts and the wind
value histogram) in order to set the sample filter and catch coding errors.
No relationship between wind and any outcome was examined before this file
was written.

HYPOTHESIS
  H1: Closing NFL totals do not fully price wind. Higher wind should push the
      realised total BELOW the closing total, i.e. a NEGATIVE slope of the
      total residual on wind, and an under-cover rate above 50% in wind.
  H0: the closing total already prices wind correctly -> slope = 0, under
      rate = 50%.

RESPONSE VARIABLES
  resid = total (actual points scored, both teams) - total_line (closing)
  under = 1 if total < total_line, 0 if total > total_line, pushes DROPPED

SAMPLE FILTER (fixed in advance)
  games.csv rows with:
    roof == 'outdoors'        (dome/closed/open are excluded: 'open' has wind
                               null in 128/128 rows, dome/closed in ~1198/1199
                               -- there is no wind data there to test)
    total_line non-null, total non-null (game played)
    wind non-null             (NO IMPUTATION. missing rows are dropped and
                               counted, never filled with a mean or a zero)
    wind < 50 mph             (data-quality rule: exactly 2 rows carry 70 and
                               71 mph, which no NFL game has been played in.
                               Sensitivity WITH them is reported as test T1b.)
  Seasons: ALL, 1999-2026 (the full range in games.csv).

PRE-REGISTERED TESTS  (every one below is run exactly once, and every one is
reported whatever it says)

  T1  PRIMARY. OLS  resid ~ 1 + wind, full sample.
      Statistic: the wind slope. Threshold: two-sided p < 0.05.
      SE: clustered by season (the season is the real correlation unit --
      scoring environment and rule changes move whole seasons together).
      HC3 SE reported alongside the SAME point estimate; that is one test
      reported two ways, not two tests.
  T1b SENSITIVITY. Same regression with the two 70/71 mph rows included.
  T2  PRIMARY. Logit  under ~ 1 + wind, full sample. Threshold p < 0.05.
  T3  OUT-OF-SAMPLE, THE ONE THAT COUNTS. Season split, earlier -> later:
      TRAIN 1999-2012, TEST 2013-2026. Freeze the T1 slope on TRAIN, apply
      to TEST, and estimate gamma, the single scale factor on the frozen
      prediction, using TEST games only.
        gamma = 1 -> the past slope transferred exactly
        gamma = 0 -> wind carried nothing forward   <- the null
      Also: refit the slope on TEST alone and report it.
      Threshold: gamma p < 0.05 AND gamma > 0.
  T4  SHAPE. Fixed bins 0-4, 5-9, 10-14, 15-19, 20+ mph. Mean resid, under
      rate, n per bin. Cochran-Armitage linear-trend test on the under rate
      across bins. Threshold p < 0.05. The bin edges are fixed HERE and are
      not moved afterwards.
  T5  TAIL. wind >= 15 mph, a cutoff fixed HERE before seeing any result.
      (a) one-sample t-test of mean resid vs 0, full sample.
      (b) binomial test of the under rate vs 0.5, full sample.
      (c) the same two on TEST seasons (2013-2026) only.
      Threshold p < 0.05.
  T6  CONTROLS. OLS resid ~ 1 + wind + total_line + temp. Does the wind slope
      survive conditioning on the level of the total and on temperature?
  T7  DESCRIPTIVE (not an edge test, reported for interpretation): OLS
      total_line ~ 1 + wind + season fixed effects -- how much does the market
      ALREADY move the total per mph of wind?
  T8  SECONDARY OOS. Expanding-window season-wise CV (train on all seasons
      strictly before season s, test on s, for s = 2005..2026). Pooled gamma
      on the held-out games.

WHAT WOULD COUNT AS AN EDGE
  T1 significant AND T3 gamma significantly > 0 AND the implied edge large
  enough to clear -110 vig in a bin with enough games per season to bet.
  Anything less is reported as no edge.

NO TUNING. If a result appears only after moving a window, a filter or a
cutoff, that is stated explicitly and the result is called not an edge.

KNOWN LIMITATION, STATED UP FRONT
  games.csv 'wind' is the OBSERVED game-time wind from the NFL game book, not
  the pre-game FORECAST a bettor would have had. Any effect found here is an
  upper bound on what is tradeable.
=============================================================================
"""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from load import load_games

warnings.filterwarnings("ignore")
pd.set_option("display.width", 180); pd.set_option("display.max_columns", 50)
R = "=" * 92; T = "-" * 92
def head(s): print("\n" + R); print(s); print(R)

MDE_Z = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)   # 2.8016

# ---------------------------------------------------------------- sample
head("0. SAMPLE CONSTRUCTION (filter fixed in the pre-registration above)")
g = load_games()
print("games.csv rows                                    : %d (%d-%d)"
      % (len(g), g.season.min(), g.season.max()))
step = g[g.roof.eq("outdoors")]
print("roof == 'outdoors'                                : %d" % len(step))
step = step[step.total_line.notna()]
print("  & closing total_line present                    : %d" % len(step))
step = step[step.total.notna()]
print("  & game played (total present)                   : %d" % len(step))
n_before_wind = len(step)
wind_null = step.wind.isna()
print("  & wind present  (DROPPED, not imputed: %4d)     : %d"
      % (int(wind_null.sum()), int((~wind_null).sum())))
print("\n  wind-null rows by season (the clustering the brief warned about):")
wn = step[wind_null].groupby("season").size()
print("   ", dict(wn) if len(wn) else "none")
step = step[~wind_null]
bad = step.wind >= 50
print("\n  & wind < 50 mph (data-quality, DROPPED: %d rows, values %s) : %d"
      % (int(bad.sum()), sorted(step.loc[bad, "wind"].tolist()), int((~bad).sum())))
d_all = step.copy()           # keeps the 70/71 rows, for T1b only
d = step[~bad].copy()

for f in (d, d_all):
    f["resid"] = f["total"] - f["total_line"]
    f["push"] = f["total"] == f["total_line"]
    f["under"] = np.where(f["total"] < f["total_line"], 1.0,
                  np.where(f["total"] > f["total_line"], 0.0, np.nan))

N = len(d)
print("\nANALYSIS SAMPLE n = %d  seasons %d-%d" % (N, d.season.min(), d.season.max()))
print("  pushes (total == total_line): %d  -> dropped from every under-rate "
      "test, kept in every resid test" % int(d["push"].sum()))
print("  resid: mean %+.3f  sd %.3f    wind: mean %.2f  sd %.2f  median %.0f"
      % (d.resid.mean(), d.resid.std(), d.wind.mean(), d.wind.std(), d.wind.median()))
print("  raw under rate (pushes excluded): %.4f on %d games"
      % (d["under"].mean(), int(d["under"].notna().sum())))

head("0b. POWER -- what is the smallest effect this sample can see at 80%?")
se_slope_approx = d.resid.std() / (d.wind.std() * np.sqrt(N))
print("OLS slope, n=%d: iid SE ~ sd(resid)/(sd(wind)*sqrt(n)) = %.4f" % (N, se_slope_approx))
print("  -> 80%%-power MDE = %.3f x SE = %.4f points of total per mph"
      % (MDE_Z, MDE_Z * se_slope_approx))
print("  -> i.e. %.2f points of total across a 0 -> 20 mph swing."
      % (MDE_Z * se_slope_approx * 20))
n_u = int(d["under"].notna().sum())
print("Under rate, n=%d: SE = 0.5/sqrt(n) = %.4f -> 80%%-power MDE = %.4f "
      "(i.e. detectable from %.2f%%)" % (n_u, 0.5/np.sqrt(n_u),
      MDE_Z*0.5/np.sqrt(n_u), 100*(0.5 + MDE_Z*0.5/np.sqrt(n_u))))
print("Break-even at -110 is 52.381%%. The sample can see a %.2f%% rate at 80%% power,"
      % (100*(0.5 + MDE_Z*0.5/np.sqrt(n_u))))
print("so a merely-break-even edge is INSIDE this test's reach on the full sample.")

def ols(frame, ycol, xcols, label, cluster="season"):
    f = frame.dropna(subset=[ycol] + xcols)
    X = sm.add_constant(f[xcols].astype(float))
    m = sm.OLS(f[ycol].astype(float), X)
    rc = m.fit(cov_type="cluster", cov_kwds={"groups": f[cluster]})
    rh = m.fit(cov_type="HC3")
    print("\n%s   n=%d" % (label, len(f)))
    tab = pd.DataFrame({"beta": rc.params, "SE_cluster": rc.bse, "t_cluster": rc.tvalues,
                        "p_cluster": rc.pvalues, "SE_HC3": rh.bse, "p_HC3": rh.pvalues,
                        "ci_lo": rc.conf_int()[0], "ci_hi": rc.conf_int()[1]})
    print(tab.round(5).to_string())
    return rc, rh, f

# ---------------------------------------------------------------- T1
head("T1 (PRIMARY)  resid ~ wind, full sample, seasons %d-%d" % (d.season.min(), d.season.max()))
t1c, t1h, _ = ols(d, "resid", ["wind"], "OLS resid ~ 1 + wind")
b1 = t1c.params["wind"]
print("\n  -> %.4f points of total per mph. Over a 0->20 mph swing: %+.2f points."
      % (b1, b1*20))
print("  -> significant at 5%%? cluster %s | HC3 %s"
      % ("YES" if t1c.pvalues["wind"] < .05 else "NO",
         "YES" if t1h.pvalues["wind"] < .05 else "NO"))

head("T1b (SENSITIVITY)  same regression WITH the 70/71 mph rows")
t1b, _, _ = ols(d_all, "resid", ["wind"], "OLS resid ~ 1 + wind  (n+2)")

# ---------------------------------------------------------------- T2
head("T2 (PRIMARY)  logit  under ~ wind, pushes excluded")
du = d.dropna(subset=["under"])
X = sm.add_constant(du[["wind"]].astype(float))
t2 = sm.GLM(du["under"].astype(float), X, family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": du["season"]})
print(t2.summary().as_text())
lo, hi = t2.conf_int().loc["wind"]
print("\n  wind slope %+.5f log-odds/mph (SE %.5f, p %.4f, 95%% CI [%+.5f, %+.5f])"
      % (t2.params["wind"], t2.bse["wind"], t2.pvalues["wind"], lo, hi))
for w in (5, 10, 15, 20, 25):
    p = 1/(1+np.exp(-(t2.params["const"] + t2.params["wind"]*w)))
    print("    implied P(under) at %2d mph = %.4f" % (w, p))
print("  -> significant at 5%%? %s" % ("YES" if t2.pvalues["wind"] < .05 else "NO"))

# ---------------------------------------------------------------- T3
head("T3 (OUT OF SAMPLE -- THE ONE THAT COUNTS)  train 1999-2012 -> test 2013-2026")
tr = d[d.season <= 2012]; te = d[d.season >= 2013]
print("TRAIN n=%d (%d-%d)   TEST n=%d (%d-%d)"
      % (len(tr), tr.season.min(), tr.season.max(), len(te), te.season.min(), te.season.max()))
trc, _, _ = ols(tr, "resid", ["wind"], "TRAIN  resid ~ 1 + wind")
tec, _, _ = ols(te, "resid", ["wind"], "TEST   resid ~ 1 + wind  (refit on held-out half)")
a0, b0 = trc.params["const"], trc.params["wind"]
te = te.copy(); te["pred"] = a0 + b0*te["wind"]
Xg = sm.add_constant(pd.DataFrame({"gamma": te["pred"].to_numpy()}, index=te.index))
g3 = sm.OLS(te["resid"].astype(float), Xg).fit(cov_type="cluster",
                                               cov_kwds={"groups": te["season"]})
glo, ghi = g3.conf_int().loc["gamma"]
print("\nGAMMA on the frozen TRAIN prediction, estimated on TEST games only:")
print("  gamma = %+.4f  (SE %.4f, t %+.2f, p %.4f, 95%% CI [%+.3f, %+.3f])  n=%d"
      % (g3.params["gamma"], g3.bse["gamma"], g3.tvalues["gamma"],
         g3.pvalues["gamma"], glo, ghi, len(te)))
print("  differs from 0? %s      differs from 1? %s"
      % ("YES" if g3.pvalues["gamma"] < .05 else "no",
         "YES" if not (glo <= 1 <= ghi) else "no"))
se_te = te.resid.std()/(te.wind.std()*np.sqrt(len(te)))
print("  TEST-half power: slope SE ~ %.4f -> 80%% MDE %.4f pts/mph" % (se_te, MDE_Z*se_te))

# ---------------------------------------------------------------- T4
head("T4 (SHAPE)  fixed bins -- monotone, or a tail-only effect?")
edges = [0, 5, 10, 15, 20, 100]
labels = ["0-4", "5-9", "10-14", "15-19", "20+"]
for f in (d, te):
    f["bin"] = pd.cut(f["wind"], bins=edges, right=False, labels=labels)
rows = []
for lab in labels:
    s = d[d["bin"].eq(lab)]
    u = s["under"].dropna()
    n_season = len(s)/d.season.nunique()
    rows.append({"bin": lab, "n": len(s), "games/season": round(n_season, 1),
                 "mean_resid": s.resid.mean(), "se_resid": s.resid.std()/np.sqrt(len(s)),
                 "under_rate": u.mean(), "n_under": len(u),
                 "se_under": 0.5/np.sqrt(len(u)),
                 "mean_total_line": s.total_line.mean()})
bt = pd.DataFrame(rows).set_index("bin")
print(bt.round(4).to_string())
print("\n(break-even under rate at -110 = 0.52381)")
u = d.dropna(subset=["under"])
codes = u["bin"].cat.codes.to_numpy(dtype=float)
ub = u["under"].to_numpy()
nn = len(ub); pbar = ub.mean()
num = np.sum((codes - codes.mean()) * (ub - pbar))
den = np.sqrt(pbar*(1-pbar)*np.sum((codes-codes.mean())**2))
z_ca = num/den
print("Cochran-Armitage linear trend in the under rate across the 5 bins: "
      "z = %+.3f, p = %.4f  -> %s" % (z_ca, 2*(1-stats.norm.cdf(abs(z_ca))),
      "trend" if 2*(1-stats.norm.cdf(abs(z_ca))) < .05 else "NO trend"))

# ---------------------------------------------------------------- T5
head("T5 (TAIL)  wind >= 15 mph -- cutoff fixed in the pre-registration")
def tail_report(frame, name):
    s = frame[frame.wind >= 15]
    u = s["under"].dropna()
    tt = stats.ttest_1samp(s.resid, 0.0)
    bn = stats.binomtest(int(u.sum()), len(u), 0.5)
    print("\n%s: n=%d (%.1f games/season over %d seasons)"
          % (name, len(s), len(s)/frame.season.nunique(), frame.season.nunique()))
    print("  mean resid %+.3f (SE %.3f)  t=%+.2f  p=%.4f  -> %s"
          % (s.resid.mean(), s.resid.std()/np.sqrt(len(s)), tt.statistic, tt.pvalue,
             "reject 0" if tt.pvalue < .05 else "cannot reject 0"))
    print("  under rate %.4f on %d games (%d pushes)  binomial p=%.4f  95%% CI [%.4f, %.4f]"
          % (u.mean(), len(u), int(s['push'].sum()), bn.pvalue, *bn.proportion_ci()))
    print("  80%%-power MDE on that under rate: %.4f (detectable from %.2f%%)"
          % (MDE_Z*0.5/np.sqrt(len(u)), 100*(0.5+MDE_Z*0.5/np.sqrt(len(u)))))
    print("  vs -110 break-even 52.381%%: %s"
          % ("ABOVE" if u.mean() > 0.52381 else "below"))
    return s, u
tail_report(d, "T5a/b FULL SAMPLE  wind>=15")
tail_report(te, "T5c  TEST SEASONS ONLY (2013-2026)  wind>=15")

# ---------------------------------------------------------------- T6
head("T6 (CONTROLS)  resid ~ wind + total_line + temp")
print("temp non-null on the analysis sample: %d / %d" % (int(d.temp.notna().sum()), N))
t6, _, f6 = ols(d, "resid", ["wind", "total_line", "temp"],
                "OLS resid ~ 1 + wind + total_line + temp")
print("\n  wind slope with controls %+.5f vs %+.5f univariate -> %s"
      % (t6.params["wind"], b1,
         "survives at 5%" if t6.pvalues["wind"] < .05 else "NOT significant at 5%"))

# ---------------------------------------------------------------- T7
head("T7 (DESCRIPTIVE)  how much does the market ALREADY move the total per mph?")
dd = d.copy()
for s in sorted(dd.season.unique())[1:]:
    dd["yr_%d" % s] = (dd.season == s).astype(float)
fe = [c for c in dd.columns if c.startswith("yr_")]
t7, _, _ = ols(dd, "total_line", ["wind"] + fe,
               "OLS total_line ~ 1 + wind + season FE (FE rows suppressed below)")
print("\n  market total moves %+.4f points per mph of wind (season FE absorbed)."
      % t7.params["wind"])
print("  0 -> 20 mph: the market already takes %+.2f points OFF the total."
      % (t7.params["wind"]*20))
print("  Compare to T1's residual slope %+.4f/mph: that is the amount the market "
      "MISSES, on top of what it already prices." % b1)

# ---------------------------------------------------------------- T8
head("T8 (SECONDARY OOS)  expanding-window season-wise CV, test seasons 2005-2026")
pieces = []
for s in range(2005, int(d.season.max()) + 1):
    trs = d[d.season < s]; tes = d[d.season == s]
    if len(trs) < 300 or len(tes) == 0: continue
    r = sm.OLS(trs["resid"].astype(float),
               sm.add_constant(trs[["wind"]].astype(float))).fit()
    p = tes.copy()
    p["pred"] = r.params["const"] + r.params["wind"]*p["wind"]
    p["b_train"] = r.params["wind"]
    pieces.append(p)
oos = pd.concat(pieces, ignore_index=True)
per = oos.groupby("season").agg(n=("resid", "size"), b_train=("b_train", "first"),
                                mean_resid=("resid", "mean"))
print(per.round(4).to_string())
print("\nsign of the trained wind slope across %d folds: %s"
      % (len(per), "all negative" if (per.b_train < 0).all()
         else ("all positive" if (per.b_train > 0).all() else "FLIPS")))
Xg = sm.add_constant(pd.DataFrame({"gamma": oos["pred"].to_numpy()}, index=oos.index))
g8 = sm.OLS(oos["resid"].astype(float), Xg).fit(cov_type="cluster",
                                                cov_kwds={"groups": oos["season"]})
glo8, ghi8 = g8.conf_int().loc["gamma"]
print("POOLED OOS gamma = %+.4f (SE %.4f, t %+.2f, p %.4f, 95%% CI [%+.3f, %+.3f]) n=%d"
      % (g8.params["gamma"], g8.bse["gamma"], g8.tvalues["gamma"], g8.pvalues["gamma"],
         glo8, ghi8, len(oos)))
o8, _, _ = ols(oos, "resid", ["wind"], "OOS pooled refit  resid ~ 1 + wind")

# ---------------------------------------------------------------- summary
head("SUMMARY OF EVERY PRE-REGISTERED TEST RUN (8 tests, all reported)")
def yn(p): return "SIG" if p < .05 else "null"
print("T1  full-sample slope        %+.4f /mph  p_cluster %.4f  %s" % (b1, t1c.pvalues["wind"], yn(t1c.pvalues["wind"])))
print("T1b with 70/71 rows          %+.4f /mph  p %.4f  %s" % (t1b.params["wind"], t1b.pvalues["wind"], yn(t1b.pvalues["wind"])))
print("T2  logit under ~ wind       %+.5f      p %.4f  %s" % (t2.params["wind"], t2.pvalues["wind"], yn(t2.pvalues["wind"])))
print("T3  OOS gamma (2013-2026)    %+.4f      p %.4f  %s" % (g3.params["gamma"], g3.pvalues["gamma"], yn(g3.pvalues["gamma"])))
print("    OOS refit slope          %+.4f /mph  p %.4f  %s" % (tec.params["wind"], tec.pvalues["wind"], yn(tec.pvalues["wind"])))
print("T4  Cochran-Armitage trend   z %+.3f     p %.4f  %s" % (z_ca, 2*(1-stats.norm.cdf(abs(z_ca))), yn(2*(1-stats.norm.cdf(abs(z_ca))))))
print("T6  slope w/ controls        %+.4f /mph  p %.4f  %s" % (t6.params["wind"], t6.pvalues["wind"], yn(t6.pvalues["wind"])))
print("T7  market's own wind slope  %+.4f /mph  p %.4f  (descriptive)" % (t7.params["wind"], t7.pvalues["wind"]))
print("T8  expanding-window gamma   %+.4f      p %.4f  %s" % (g8.params["gamma"], g8.pvalues["gamma"], yn(g8.pvalues["gamma"])))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_wind_totals.parquet")
d.drop(columns=[c for c in d.columns if c.startswith("yr_")], errors="ignore").to_parquet(out, index=False)
print("\nanalysis sample written to %s" % out)
