#!/usr/bin/env python3
"""
wind_data_validity.py -- ADVERSARIAL DATA-VALIDITY ATTACK on the wind/totals claim.

======================== PRE-REGISTRATION (written first) =====================
I am not re-testing the statistics. I am attacking whether the DATA MEAN WHAT
THE CLAIM SAYS THEY MEAN. Everything below was written before any regression in
this file was run. Every test is reported whatever it says. No cutoff, window or
filter is moved afterwards; where one is, it is labelled TUNED and discounted.

CLAIM UNDER ATTACK
  T1: resid = total - total_line regressed on wind gives -0.185 pts/mph
      (SE .039 season-clustered), n=5213.
  T7: total_line ~ wind + season FE gives -0.065 pts/mph.
  Interpretation asserted: "the market prices about a quarter of the true wind
  effect", implied true effect -0.25 pts/mph.

SAMPLE (identical to the original, so the attack is like-for-like)
  games.csv, roof == 'outdoors', total_line notna, total notna, wind notna,
  wind < 50. No imputation anywhere. Seasons 1999-2026.

TESTS, FIXED IN ADVANCE
  D1  RESPONSE INTEGRITY. Is `total` really home_score+away_score? Is `result`
      really home_score-away_score? Is spread_line really "home favoured by"
      (OLS result ~ spread_line must give slope ~ +1, intercept ~ 0; a sign flip
      gives -1). Threshold: |slope-1| < 0.15 and home-favourite ATS rate in
      [0.45,0.55]. Reported for the spread even though the claim is a total,
      because the brief asks and because a flipped sign would indict the file.
  D2  INDEPENDENT RECOMPUTATION. Rebuild resid from home_score+away_score
      (NOT from nflverse's `total` column), re-run T1 and T7 with my own code.
      Threshold: reproduce means within 0.01 pts/mph of the stated numbers.
  D3  INDEPENDENT WIND SOURCE. Parse wind mph out of the pbp free-text `weather`
      gamebook string and re-run T1 on THAT wind. If the headline only exists in
      the games.csv wind column it is a data artefact.
  D4  THE ZERO / INDOORS AUDIT. For games.csv wind==0 outdoor rows, does the
      gamebook string say "N/A" or "Indoors" (i.e. 0 is a masked missing or a
      roofed game mislabelled 'outdoors')? Re-run T1 dropping every row whose
      gamebook text shows a masked/indoor wind.
  D5  MISSINGNESS / SELECTION. Are dropped rows (wind null) different in resid
      and total_line from kept rows? Is any value silently imputed anywhere in
      the loader? Threshold: mean resid of dropped vs kept, two-sample t.
  D6  IS total_line THE CLOSE? Compare nflverse total_line to an independent
      open and close (line_move_sample.csv, 2023-2026, ESPN/DK). If total_line
      tracks the OPENER, the "residual beyond the close" is not beyond a close.
      Also: pushes and line granularity.
  D7  THE IDENTIFICATION TEST (PRIMARY ATTACK). `wind` in games.csv is the
      REALISED gamebook wind, which is NOT in a bettor's information set at
      close. Split realised wind into
         w_hat = ex-ante climatology, stadium x calendar month, computed from
                 STRICTLY PRIOR SEASONS ONLY (no leakage), and
         dev   = wind - w_hat  (the same-day surprise).
      Regress resid ~ w_hat + dev, season-clustered. And total_line ~ w_hat +
      dev + season FE.
      An UNDERPRICING edge lives in w_hat: it is knowable before kickoff.
      An EFFICIENT market facing a noisy forecast produces a negative slope on
      dev and ZERO on w_hat.
      THRESHOLD, fixed here: the claim survives only if the w_hat coefficient in
      the resid regression is negative with p < 0.05. Anything else refutes the
      tradeable reading of the claim.
      D7a primary: stadium x month, requires >=5 prior-season games in that
          cell; else fall back to stadium-only prior mean with >=10; else drop.
          Seasons 2004+ (five seasons of history) -- fixed here, not tuned.
      D7b sensitivity: stadium-only prior-season climatology.
  D8  ALGEBRA, not a fit. Under an efficient market pricing an unbiased forecast
      w* of realised w, slope(resid on w) = beta_true*(1-R2f) and
      slope(line on w) = beta_true*R2f, where R2f is the share of realised-wind
      variance the market's forecast explains. Compute the R2f implied by my own
      D2 numbers and state what forecast skill would be needed to reconcile the
      data with a perfectly efficient market.
  D9  OUT-OF-SAMPLE on D7. Season split, train 1999-2012 / test 2013-2026 (the
      SAME split the original used, not a new one). Freeze w_hat and dev slopes
      on train, estimate gamma on test for each component separately.

POWER. Every coefficient is reported with its 80%-power MDE.
===============================================================================
"""
import os, sys, re, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
warnings.filterwarnings("ignore")
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 60)
R = "=" * 92
def head(s): print("\n" + R); print(s); print(R)
MDE_Z = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)
DATA = "/Users/cmanlongat/Projects/pick-six/data/nflverse"
NTEST = [0]
def test(name):
    NTEST[0] += 1
    head("TEST %d -- %s" % (NTEST[0], name))

def clus(f, y, xs, label, cluster="season", show=None):
    f = f.dropna(subset=[y] + xs)
    r = sm.OLS(f[y].astype(float), sm.add_constant(f[xs].astype(float))).fit(
        cov_type="cluster", cov_kwds={"groups": f[cluster]})
    keep = show or [c for c in r.params.index if not c.startswith(("yr_", "st_"))]
    ci = r.conf_int()
    tab = pd.DataFrame({"beta": r.params, "SE": r.bse, "t": r.tvalues, "p": r.pvalues,
                        "ci_lo": ci[0], "ci_hi": ci[1]}).loc[keep]
    print("\n%s   n=%d" % (label, len(f)))
    print(tab.round(5).to_string())
    for c in keep:
        if c != "const":
            print("   80%%-power MDE on %-8s = %.4f  (|beta| = %.4f -> %s)"
                  % (c, MDE_Z * r.bse[c], abs(r.params[c]),
                     "detectable" if abs(r.params[c]) > MDE_Z*r.bse[c] else "UNDERPOWERED"))
    return r, f

# ----------------------------------------------------------------- raw load
head("0. RAW LOAD -- pandas read_csv straight off disk, no project loader")
g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
print("rows %d  seasons %d-%d  duplicate game_id: %d"
      % (len(g), g.season.min(), g.season.max(), int(g.game_id.duplicated().sum())))
print("roof values: %s" % g.roof.value_counts(dropna=False).to_dict())

# ================================================================== D1
test("D1 RESPONSE INTEGRITY: is the response what they think it is?")
p = g.dropna(subset=["home_score", "away_score"]).copy()
p["my_total"] = p.home_score + p.away_score
p["my_result"] = p.home_score - p.away_score
print("games with scores: %d" % len(p))
print("rows where nflverse `total` != home+away : %d" % int((p.my_total != p.total).sum()))
print("rows where nflverse `result` != home-away: %d" % int((p.my_result != p.result).sum()))
s = p.dropna(subset=["spread_line"])
print("\nSPREAD SIGN CONVENTION (brief: spread_line = points HOME is favoured by)")
print("  n with spread_line + result: %d" % len(s))
rs = sm.OLS(s.my_result.astype(float), sm.add_constant(s[["spread_line"]].astype(float))).fit()
print("  OLS result ~ spread_line : slope %+.4f (SE %.4f)  intercept %+.4f"
      % (rs.params["spread_line"], rs.bse["spread_line"], rs.params["const"]))
print("  corr(result, spread_line) = %+.4f" % s.my_result.corr(s.spread_line))
fav = s[s.spread_line > 0]
print("  home-favoured games (spread_line>0): n=%d, home win rate %.4f"
      % (len(fav), (fav.my_result > 0).mean()))
dog = s[s.spread_line < 0]
print("  home-dog games      (spread_line<0): n=%d, home win rate %.4f"
      % (len(dog), (dog.my_result > 0).mean()))
cov = s[s.my_result != s.spread_line]
print("  home ATS cover rate (pushes dropped): %.4f on %d games"
      % ((cov.my_result > cov.spread_line).mean(), len(cov)))
print("  spread pushes: %d (%.2f%%)   total pushes: %d (%.2f%%)"
      % (int((s.my_result == s.spread_line).sum()), 100*(s.my_result == s.spread_line).mean(),
         int((p.my_total == p.total_line).sum()), 100*(p.my_total == p.total_line).mean()))
print("  VERDICT: slope %s +1 -> sign convention %s"
      % ("~=" if abs(rs.params["spread_line"]-1) < .15 else "!=",
         "CORRECT (home favoured by)" if abs(rs.params["spread_line"]-1) < .15 else "FLIPPED"))

# ------------------------------------------------- build the analysis sample
head("SAMPLE -- rebuilt from raw, my own code, resid from SCORES not from `total`")
d = g[g.roof.eq("outdoors") & g.total_line.notna() & g.total.notna() & g.wind.notna()].copy()
print("after roof/total_line/total/wind filters: %d" % len(d))
d = d[d.wind < 50].copy()
print("after wind < 50: %d" % len(d))
d["resid"] = (d.home_score + d.away_score) - d.total_line
d["resid_nflv"] = d.total - d.total_line
print("my resid vs nflverse-total resid: max abs diff %.6f"
      % (d.resid - d.resid_nflv).abs().max())
d["under"] = np.where(d.home_score + d.away_score < d.total_line, 1.0,
              np.where(d.home_score + d.away_score > d.total_line, 0.0, np.nan))
d["month"] = pd.to_datetime(d.gameday).dt.month
N = len(d)
print("ANALYSIS n = %d  seasons %d-%d  pushes %d  under-rate %.4f"
      % (N, d.season.min(), d.season.max(), int(d.under.isna().sum()), d.under.mean()))

# ================================================================== D2
test("D2 INDEPENDENT RECOMPUTATION of T1 and T7")
r_t1, _ = clus(d, "resid", ["wind"], "T1 recomputed: resid ~ wind")
print("   claimed -0.185 (SE .039)  |  mine %+.4f (SE %.4f)  -> %s"
      % (r_t1.params["wind"], r_t1.bse["wind"],
         "REPRODUCED" if abs(r_t1.params["wind"] + 0.185) < 0.01 else "DOES NOT REPRODUCE"))
dd = d.copy()
for y in sorted(dd.season.unique())[1:]:
    dd["yr_%d" % y] = (dd.season == y).astype(float)
fe = [c for c in dd.columns if c.startswith("yr_")]
r_t7, _ = clus(dd, "total_line", ["wind"] + fe, "T7 recomputed: total_line ~ wind + season FE",
               show=["const", "wind"])
print("   claimed -0.065  |  mine %+.4f  -> %s"
      % (r_t7.params["wind"],
         "REPRODUCED" if abs(r_t7.params["wind"] + 0.065) < 0.01 else "DOES NOT REPRODUCE"))
B1, B7 = r_t1.params["wind"], r_t7.params["wind"]

# ================================================================== D3
test("D3 INDEPENDENT WIND SOURCE: parse the gamebook weather string from pbp")
WRE = re.compile(r"Wind:\s*([A-Za-z/\.]+)?\s*(\d+)\s*mph", re.I)
rows = []
for s_ in range(1999, 2027):
    fp = os.path.join(DATA, "play_by_play_%d.parquet" % s_)
    if not os.path.exists(fp):
        continue
    pb = pd.read_parquet(fp, columns=["game_id", "weather", "wind", "roof"])
    rows.append(pb.groupby("game_id").first().reset_index())
pw = pd.concat(rows, ignore_index=True)
print("pbp game rows: %d   weather text non-null: %d (%.1f%%)"
      % (len(pw), pw.weather.notna().sum(), 100*pw.weather.notna().mean()))
def parse_wind(t):
    if not isinstance(t, str):
        return np.nan
    m = WRE.search(t)
    return float(m.group(2)) if m else np.nan
def wind_flag(t):
    if not isinstance(t, str):
        return "no_text"
    tl = t.lower()
    if "indoor" in tl or "closed roof" in tl:
        return "indoors"
    if re.search(r"wind:\s*n/?a", tl):
        return "na"
    if "calm" in tl:
        return "calm"
    if WRE.search(t):
        return "ok"
    return "unparsed"
pw["gb_wind"] = pw.weather.map(parse_wind)
pw["gb_flag"] = pw.weather.map(wind_flag)
print("gamebook flag counts: %s" % pw.gb_flag.value_counts().to_dict())
m = d.merge(pw[["game_id", "gb_wind", "gb_flag", "weather"]], on="game_id", how="left")
both = m.dropna(subset=["gb_wind"])
print("\nmerged onto the analysis sample: %d of %d have a parsed gamebook wind" % (len(both), len(m)))
print("agreement games.csv wind vs gamebook-parsed wind: exact %.2f%%  corr %.4f  mean abs diff %.3f"
      % (100*(both.wind == both.gb_wind).mean(), both.wind.corr(both.gb_wind),
         (both.wind - both.gb_wind).abs().mean()))
r_d3, _ = clus(both, "resid", ["gb_wind"], "T1 on the INDEPENDENTLY PARSED wind")
print("   games.csv-wind slope %+.4f  vs gamebook-parsed-wind slope %+.4f"
      % (B1, r_d3.params["gb_wind"]))

# ================================================================== D4
test("D4 THE ZERO / MISLABELLED-ROOF AUDIT")
z = m[m.wind.eq(0)]
print("games.csv wind==0 on the analysis sample: n=%d (%.1f%%)" % (len(z), 100*len(z)/len(m)))
print("  their gamebook flags: %s" % z.gb_flag.value_counts(dropna=False).to_dict())
print("  gamebook flags for wind>0 rows: %s"
      % m[m.wind.gt(0)].gb_flag.value_counts(dropna=False).to_dict())
bad_flags = {"indoors", "na"}
mis = m[m.gb_flag.isin(bad_flags)]
print("\nrows the gamebook calls INDOORS or wind N/A but games.csv calls roof='outdoors': %d" % len(mis))
if len(mis):
    print("  their games.csv wind values: %s" % mis.wind.value_counts().head(8).to_dict())
    print("  mean resid of those rows %+.3f vs %+.3f elsewhere" % (mis.resid.mean(), m[~m.gb_flag.isin(bad_flags)].resid.mean()))
clean = m[~m.gb_flag.isin(bad_flags)]
r_d4, _ = clus(clean, "resid", ["wind"], "T1 with gamebook-indoor / wind-N/A rows DROPPED")
r_d4b, _ = clus(m[m.wind.gt(0)], "resid", ["wind"], "T1 with ALL wind==0 rows dropped (replicating T10)")

# ================================================================== D5
test("D5 MISSINGNESS AND SILENT IMPUTATION")
pool = g[g.roof.eq("outdoors") & g.total_line.notna() & g.total.notna()].copy()
pool["resid"] = (pool.home_score + pool.away_score) - pool.total_line
miss = pool[pool.wind.isna()]; kept = pool[pool.wind.notna()]
print("outdoor played games with a total line: %d ; wind missing %d (%.1f%%)"
      % (len(pool), len(miss), 100*len(miss)/len(pool)))
tt = stats.ttest_ind(miss.resid.dropna(), kept.resid.dropna(), equal_var=False)
print("mean resid  DROPPED %+.3f (n=%d)  vs KEPT %+.3f (n=%d)  Welch t=%+.2f p=%.4f -> %s"
      % (miss.resid.mean(), len(miss), kept.resid.mean(), len(kept), tt.statistic, tt.pvalue,
         "SELECTION" if tt.pvalue < .05 else "no detectable selection on the outcome"))
tl = stats.ttest_ind(miss.total_line.dropna(), kept.total_line.dropna(), equal_var=False)
print("mean total_line DROPPED %.2f vs KEPT %.2f  Welch p=%.4f" % (miss.total_line.mean(), kept.total_line.mean(), tl.pvalue))
byseason = pool.groupby("season").apply(lambda x: pd.Series(
    {"n": len(x), "pct_wind_missing": round(x.wind.isna().mean(), 3)}))
print("\nwind missingness by season:"); print(byseason.T.to_string())
print("\nimputation grep over the pipeline (fillna / interpolate / bfill / ffill):")
os.system("grep -nE 'fillna|interpolate|bfill|ffill|\\.replace\\(' "
          "/Users/cmanlongat/Projects/pick-six/tools/backtest/load.py "
          "/Users/cmanlongat/Projects/pick-six/tools/backtest/wind_totals.py || echo '  (none found)'")

# ================================================================== D6
test("D6 IS total_line ACTUALLY THE CLOSE?")
lm = pd.read_csv(os.path.join(DATA, "line_move_sample.csv"))
mm = lm.merge(g[["game_id", "total_line"]], on="game_id", how="inner").dropna(subset=["total_line"])
print("overlap with the independent open/close file: %d games, seasons %s"
      % (len(mm), sorted(mm.season.unique())))
print("  nflverse total_line vs independent CLOSE: mean diff %+.4f  sd %.4f  |diff|<=0.5 in %.1f%%"
      % ((mm.total_line - mm.close_tt).mean(), (mm.total_line - mm.close_tt).std(),
         100*((mm.total_line - mm.close_tt).abs() <= 0.5).mean()))
print("  nflverse total_line vs independent OPEN : mean diff %+.4f  sd %.4f  |diff|<=0.5 in %.1f%%"
      % ((mm.total_line - mm.open_tt).mean(), (mm.total_line - mm.open_tt).std(),
         100*((mm.total_line - mm.open_tt).abs() <= 0.5).mean()))
print("  -> total_line is the %s" % ("CLOSE" if (mm.total_line-mm.close_tt).abs().mean()
                                     < (mm.total_line-mm.open_tt).abs().mean() else "OPEN"))
mw = mm.merge(d[["game_id", "wind"]], on="game_id", how="inner")
print("\nDoes the market MOVE the total on wind between open and close? n=%d" % len(mw))
if len(mw) > 30:
    rmv = sm.OLS((mw.close_tt - mw.open_tt).astype(float),
                 sm.add_constant(mw[["wind"]].astype(float))).fit(cov_type="HC3")
    print("  OLS (close_tt - open_tt) ~ wind : %+.4f pts/mph (SE %.4f, p %.4f)"
          % (rmv.params["wind"], rmv.bse["wind"], rmv.pvalues["wind"]))
    print("  80%%-power MDE %.4f -> %s" % (MDE_Z*rmv.bse["wind"],
          "powered" if abs(rmv.params["wind"]) > MDE_Z*rmv.bse["wind"] else "UNDERPOWERED"))
print("\ntotal_line granularity: %s" % (d.total_line % 1).value_counts().to_dict())
print("gameday range %s .. %s ; rows with a total_line but no score: %d"
      % (g.gameday.min(), g.gameday.max(), int(g.total_line.notna().sum() - g.dropna(subset=['home_score']).total_line.notna().sum())))

# ================================================================== D7
test("D7 IDENTIFICATION: is the effect in the KNOWABLE wind or the SURPRISE wind?")
d = d.sort_values(["season", "week"]).reset_index(drop=True)
hist = d[["season", "stadium_id", "month", "wind"]].copy()
def prior_clim(row, keys, minn):
    pass
sm_stats = (hist.groupby(["stadium_id", "month", "season"])["wind"]
            .agg(["sum", "count"]).reset_index())
out = []
for _, r0 in d.iterrows():
    h = hist[(hist.season < r0.season) & (hist.stadium_id == r0.stadium_id)]
    hm = h[h.month == r0.month]
    if len(hm) >= 5:
        out.append((hm.wind.mean(), "stadium_month", len(hm)))
    elif len(h) >= 10:
        out.append((h.wind.mean(), "stadium", len(h)))
    else:
        out.append((np.nan, "none", len(h)))
d["w_hat"] = [o[0] for o in out]
d["clim_src"] = [o[1] for o in out]
d["w_hat_st"] = np.nan
for i, r0 in d.iterrows():
    h = hist[(hist.season < r0.season) & (hist.stadium_id == r0.stadium_id)]
    if len(h) >= 10:
        d.at[i, "w_hat_st"] = h.wind.mean()
d7 = d[(d.season >= 2004) & d.w_hat.notna()].copy()
d7["dev"] = d7.wind - d7.w_hat
print("D7 sample: n=%d seasons %d-%d ; climatology source %s"
      % (len(d7), d7.season.min(), d7.season.max(), d7.clim_src.value_counts().to_dict()))
print("sd(realised wind) %.2f ; sd(w_hat) %.2f ; sd(dev) %.2f ; "
      "share of realised-wind variance that is ex-ante climatology: %.1f%%"
      % (d7.wind.std(), d7.w_hat.std(), d7.dev.std(), 100*d7.w_hat.var()/d7.wind.var()))
print("corr(w_hat, realised wind) = %.4f" % d7.w_hat.corr(d7.wind))
r_a, _ = clus(d7, "resid", ["wind"], "D7 baseline on this sub-sample: resid ~ wind")
r_b, _ = clus(d7, "resid", ["w_hat", "dev"], "D7a PRIMARY: resid ~ w_hat + dev")
d7f = d7.copy()
for y in sorted(d7f.season.unique())[1:]:
    d7f["yr_%d" % y] = (d7f.season == y).astype(float)
fe7 = [c for c in d7f.columns if c.startswith("yr_")]
r_c, _ = clus(d7f, "total_line", ["w_hat", "dev"] + fe7,
              "D7a market side: total_line ~ w_hat + dev + season FE",
              show=["const", "w_hat", "dev"])
print("\n  MARKET prices the knowable part at %+.4f /mph and the surprise at %+.4f /mph."
      % (r_c.params["w_hat"], r_c.params["dev"]))
print("  RESIDUAL slope on the knowable part: %+.4f (p %.4f) -> %s"
      % (r_b.params["w_hat"], r_b.pvalues["w_hat"],
         "EDGE SURVIVES" if (r_b.pvalues["w_hat"] < .05 and r_b.params["w_hat"] < 0)
         else "PRE-REGISTERED THRESHOLD NOT MET -> tradeable reading REFUTED"))
d7b = d[(d.season >= 2004) & d.w_hat_st.notna()].copy()
d7b["dev_st"] = d7b.wind - d7b.w_hat_st
r_d, _ = clus(d7b, "resid", ["w_hat_st", "dev_st"],
              "D7b SENSITIVITY: resid ~ stadium-only climatology + dev")

# ================================================================== D8
test("D8 ALGEBRA: what forecast skill reconciles this with an EFFICIENT market?")
print("""Under an efficient close pricing an unbiased forecast w* of realised w:
    slope(resid  on w) = beta_true * (1 - R2f)
    slope(line   on w) = beta_true * R2f
  where R2f = share of realised-wind variance the market's forecast explains.""")
beta_true = B1 + B7
R2f = B7 / beta_true if beta_true else np.nan
print("\n  my D2 numbers: slope(resid) %+.4f , slope(line) %+.4f" % (B1, B7))
print("  => implied beta_true = %+.4f pts/mph" % beta_true)
print("  => an efficient market is consistent with this data iff its wind forecast")
print("     explains R2f = %.3f of the variance of the GAMEBOOK wind number." % R2f)
print("     i.e. corr(forecast, gamebook wind) = %.3f" % np.sqrt(max(R2f, 0)))
print("\n  The gamebook wind is ONE integer-rounded spot reading at kickoff. Rounding")
print("  alone (uniform +-0.5 mph on sd %.2f) costs %.3f of R2; any gust/siting noise"
      % (d.wind.std(), (1/12.)/d.wind.var()))
print("  costs more. A forecast correlating %.2f with such a reading is ordinary." % np.sqrt(max(R2f,0)))
print("  CONCLUSION: this data CANNOT distinguish 'market underprices wind' from")
print("  'market prices a noisy forecast correctly'. The two make the SAME prediction")
print("  for the sign and rough size of the T1 slope. D7 is the test that can.")

# ================================================================== D9
test("D9 OUT-OF-SAMPLE on the D7 decomposition (same 1999-2012 / 2013-2026 split)")
tr = d7[d7.season <= 2012]; te = d7[d7.season >= 2013].copy()
print("TRAIN n=%d (%d-%d)  TEST n=%d (%d-%d)"
      % (len(tr), tr.season.min(), tr.season.max(), len(te), te.season.min(), te.season.max()))
rtr = sm.OLS(tr.resid.astype(float), sm.add_constant(tr[["w_hat", "dev"]].astype(float))).fit()
print("TRAIN slopes: w_hat %+.4f  dev %+.4f" % (rtr.params["w_hat"], rtr.params["dev"]))
te["pred_hat"] = rtr.params["w_hat"] * te.w_hat
te["pred_dev"] = rtr.params["dev"] * te.dev
rg = sm.OLS(te.resid.astype(float),
            sm.add_constant(te[["pred_hat", "pred_dev"]].astype(float))).fit(
            cov_type="cluster", cov_kwds={"groups": te.season})
ci = rg.conf_int()
print(pd.DataFrame({"gamma": rg.params, "SE": rg.bse, "t": rg.tvalues, "p": rg.pvalues,
                    "lo": ci[0], "hi": ci[1]}).round(4).to_string())
print("  gamma on the KNOWABLE component: %+.3f (p %.4f) -> %s"
      % (rg.params["pred_hat"], rg.pvalues["pred_hat"],
         "carries forward" if rg.pvalues["pred_hat"] < .05 else "carries NOTHING forward"))
print("  gamma on the SURPRISE component: %+.3f (p %.4f)" % (rg.params["pred_dev"], rg.pvalues["pred_dev"]))
rte, _ = clus(te, "resid", ["w_hat", "dev"], "TEST-half refit: resid ~ w_hat + dev")

head("TESTS RUN IN THIS FILE: %d (D1-D9, every one reported above)" % NTEST[0])
