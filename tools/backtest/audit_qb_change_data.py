#!/usr/bin/env python3
"""
audit_qb_change_data.py -- ADVERSARIAL DATA AUDIT of the qb-change claim.
Attacks DATA VALIDITY only. Nothing here is a new hypothesis test of the market.

A1 response variable: is ats_home = result - spread_line the right thing, with
   the right sign, and are pushes handled?
A2 provenance of home_qb_id/away_qb_id: is it the PRE-GAME announced starter,
   or something nflverse derived FROM THE GAME (most dropbacks / first snap)?
   If the latter, a "QB change" can be caused by the outcome.
A3 silent imputation inside qb_change_delta.
A4 lines that post-date the outcome / missingness pattern.
A5 independent recomputation of T1 and T5 from raw games.csv + raw pbp.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "data", "nflverse"))
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 60)

g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
print("games.csv rows:", len(g), "seasons", g.season.min(), "-", g.season.max())

print("\n=== A1  RESPONSE VARIABLE / SIGN CONVENTION ===")
p = g.dropna(subset=["result","home_score","away_score"]).copy()
print("played rows:", len(p))
print("result == home_score - away_score on all played rows:",
      bool((p.result == p.home_score - p.away_score).all()))
s = p.dropna(subset=["spread_line"]).copy()
s["ats_home"] = s.result - s.spread_line
print("rows with spread_line:", len(s))
# sign test 1: if spread_line is HOME-favoured-by, home should be the ML favourite when >0
ml = s.dropna(subset=["home_moneyline","away_moneyline"])
fav_agree = ((ml.spread_line > 0) == (ml.home_moneyline < ml.away_moneyline))
print("spread_line>0  <->  home is the moneyline favourite: %.4f agreement (n=%d)"
      % (fav_agree.mean(), len(ml)))
print("  disagreements: %d  (near-pickem?)" % int((~fav_agree).sum()))
print("  of disagreements, |spread_line| <= 1: %d"
      % int((~fav_agree & (ml.spread_line.abs()<=1)).sum()))
# sign test 2: home win rate by spread bucket -- must be monotone increasing
b = s.assign(bucket=pd.cut(s.spread_line, [-99,-10,-6.5,-3,-0.5,0.5,3,6.5,10,99]))
print("\n home win rate by spread_line bucket (must rise if + = home favoured):")
print(b.groupby("bucket", observed=True).apply(
    lambda d: pd.Series({"n": len(d), "home_win_rate": (d.result>0).mean(),
                         "mean_margin": d.result.mean()}), include_groups=False).round(3).to_string())
print("\n corr(spread_line, result) = %+.4f   (must be POSITIVE)"
      % np.corrcoef(s.spread_line, s.result)[0,1])
print(" mean ats_home = %+.4f  (market bias, should be ~0)" % s.ats_home.mean())
print(" PUSHES: ats_home == 0 on %d / %d = %.4f of spread rows"
      % (int((s.ats_home==0).sum()), len(s), (s.ats_home==0).mean()))
t = p.dropna(subset=["total_line"]).copy()
print(" total pushes: %.4f" % ((t.home_score+t.away_score - t.total_line)==0).mean())
print(" ML ties (result==0): %d = %.4f" % (int((p.result==0).sum()), (p.result==0).mean()))

print("\n=== A4  MISSINGNESS / LINE AVAILABILITY BY ERA ===")
cov = p.groupby("season").apply(lambda d: pd.Series({
    "games": len(d),
    "spread": d.spread_line.notna().mean(),
    "total": d.total_line.notna().mean(),
    "ml": (d.home_moneyline.notna() & d.away_moneyline.notna()).mean(),
    "qb_ids": (d.home_qb_id.notna() & d.away_qb_id.notna()).mean(),
}), include_groups=False)
print(cov.round(3).to_string())
print("\n spread_line half-point granularity check (fraction on .0 / .5 / other):")
fr = (s.spread_line*2) % 1
print("  on a half point: %.5f   on a whole point: %.5f   other: %.5f"
      % ((fr==0).mean(), (s.spread_line%1==0).mean(), (fr!=0).mean()))
print(" any |spread_line| > 30: %d ; any spread_line exactly == result: %d (%.4f)"
      % (int((s.spread_line.abs()>30).sum()), int((s.spread_line==s.result).sum()),
         (s.spread_line==s.result).mean()))
