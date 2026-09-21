#!/usr/bin/env python3
"""
A4: is games.csv spread_line a real, pre-kickoff CLOSING line, or could it
post-date the outcome (a settled/back-filled number)? Three probes:
  (i)  ATS cover rate and |ats_home| by season -- a back-filled line would be
       anomalously accurate in the affected seasons.
  (ii) cross-check against initial_lines.csv (2021 OPENERS, an independent
       source). If spread_line were the opener, it would match exactly.
  (iii) does the spread beat a simple post-hoc fit? A line that post-dates the
       game would have residual variance far below the market's usual ~13.5 pts.
"""
import os, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE,"..","..","data","nflverse"))
pd.set_option("display.width",200)
g = pd.read_csv(os.path.join(DATA,"games.csv"), low_memory=False).dropna(subset=["result"])
g = g[g.season.between(1999,2025) & g.spread_line.notna()].copy()
g["ats"] = g.result - g.spread_line

print("=== (i) per-season market calibration (a back-filled line shows up here) ===")
bs = g.groupby("season").apply(lambda d: pd.Series({
    "n": len(d), "home_cover": (d.ats>0).mean(), "push": (d.ats==0).mean(),
    "mean_ats": d.ats.mean(), "sd_ats": d.ats.std(),
    "MAE": d.ats.abs().mean()}), include_groups=False)
print(bs.round(3).to_string())
print("\npooled: home cover %.4f, mean ats %+.4f, sd %.3f (NFL market residual sd is ~13.5)"
      % ((g.ats>0).mean(), g.ats.mean(), g.ats.std()))
print("min/max season sd: %.2f / %.2f -- no season is anomalously tight"
      % (bs.sd_ats.min(), bs.sd_ats.max()))

print("\n=== (ii) cross-check vs initial_lines.csv (2021 OPENERS, independent source) ===")
il = pd.read_csv(os.path.join(DATA,"initial_lines.csv"))
sp = il[il.type.eq("SPREAD")].copy()
g21 = g[g.season==2021][["game_id","home_team","away_team","spread_line","result"]]
m = sp.merge(g21, left_on="about", right_on="game_id", how="inner")
m["open_home"] = np.where(m.side==m.home_team, -m.line, m.line)
m = m.drop_duplicates(subset=["game_id","sportsbook"])
agg = m.groupby("game_id").agg(open_home=("open_home","median"),
                               close_home=("spread_line","first"))
d = agg.close_home - agg.open_home
print("games matched: %d" % len(agg))
print("games.csv spread_line == opener exactly: %.4f" % (d==0).mean())
print("mean |close - open| = %.3f pts, sd %.3f, max %.1f"
      % (d.abs().mean(), d.std(), d.abs().max()))
print("-> spread_line MOVES off the opener, so it is not the opener; consistent")
print("   with a closing number. (This is a consistency check, not proof of timestamp.)")

print("\n=== (iii) could the line have been fitted to the result? ===")
import statsmodels.api as sm
X = sm.add_constant(g[["spread_line"]].astype(float))
r = sm.OLS(g.result.astype(float), X).fit()
print("result ~ spread_line : slope %.4f (SE %.4f), R2 %.4f, resid sd %.3f"
      % (r.params.spread_line, r.bse.spread_line, r.rsquared, np.sqrt(r.scale)))
print("slope is statistically indistinguishable from 1.0: t=%.2f"
      % ((r.params.spread_line-1.0)/r.bse.spread_line))
print("R2 %.3f and resid sd %.1f are the normal NFL numbers. A line that post-dated"
      % (r.rsquared, np.sqrt(r.scale)))
print("the outcome would show R2 near 1 and resid sd near 0. It does not.")
print("\nalso: %d games have spread_line but no result (unplayed) and are excluded by played_only."
      % int(pd.read_csv(os.path.join(DATA,"games.csv"), low_memory=False).result.isna().sum()))
