#!/usr/bin/env python3
"""
line_move.py -- id "line-move". PRE-REGISTERED, run once.

==========================================================================
HYPOTHESIS
==========================================================================
Line movement from open to close carries information the closing line has
not fully absorbed. (Reverse-line-movement / steam folklore.)

==========================================================================
DATA AVAILABILITY (settled BEFORE any hypothesis test was run)
==========================================================================
  * nflverse games.csv has NO opener column -- closing lines only.
  * nflverse/nfldata initial_lines.csv (Westgate openers) covers ONLY 2021
    (272 games). One season cannot support a season-wise split. Unusable.
  * ESPN core odds endpoint: `open` block absent 2013-2022, present 2023+.
    Provider 58 "ESPN BET" (pregame) 2023-mid2025; provider 100 "Draft Kings"
    mid2025-2026. Provider 59 is LIVE in-game odds -- EXCLUDED.
  * Where the opener is missing ESPN writes a moneyline PRICE into the
    pointSpread field (e.g. "+130"); requiring open AND close removes these.
  * VALIDATED on the clean subset: ESPN close vs nflverse close,
    spread mean diff +0.094 sd 0.553 (98.3% within 1pt); total +0.008 sd 0.588.
    The series is real, not a proxy.

==========================================================================
SAMPLE FILTER  (fixed before any outcome was looked at)
==========================================================================
Played NFL games, seasons 2023-2026, with BOTH an open and a close from
provider 58 (preferred) or 100 (fallback), |spread| <= 30.
  n = 778 total.  TRAIN = 2023-2024 (476).  TEST = 2025-2026 (302).
Split is season-wise and chronological. No random k-fold anywhere.

==========================================================================
RESPONSE VARIABLES
==========================================================================
  ats_resid = result - close_sp     result = home_score - away_score;
                                    close_sp = points HOME is favoured by.
                                    > 0  <=>  home covered.
  tot_resid = total_pts - close_tt  > 0  <=>  the game went over.
Under an efficient close both have mean 0 and are independent of anything
knowable before kickoff.

==========================================================================
PREDICTORS
==========================================================================
  move_sp = close_sp - open_sp   > 0 = line moved TOWARD the home team
  move_tt = close_tt - open_tt   > 0 = total moved UP

==========================================================================
THE PRE-REGISTERED TESTS (4). Threshold: two-sided p < 0.05.
Family of 4 -> Bonferroni-adjusted threshold p < 0.0125, also reported.
==========================================================================
  S1  PRIMARY.  OLS ats_resid ~ 1 + move_sp, HC3 robust SE, fitted on the
                HELD-OUT seasons 2025-2026. Statistic = slope beta.
  S2            Same for tot_resid ~ 1 + move_tt on 2025-2026.
  S3            ATS win rate from betting the side the line moved TOWARD,
                games with |move_sp| >= 1, test seasons only. Binomial
                vs 50%. (Fading the move is the exact complement.)
  S4            Same for totals: bet OVER if move_tt > 0, |move_tt| >= 1.
The 2023-2024 TRAIN slopes are fitted too, as direction-of-sign companions.
They are in-sample and can never BE the result, but they are counted and
reported as tests 5 and 6.

==========================================================================
KNOWN BIAS, declared in advance
==========================================================================
close_sp appears in BOTH ats_resid (negatively) and move_sp (positively).
Measurement noise in the close therefore induces a SPURIOUS NEGATIVE slope
of about -Var(eps)/Var(move) ~= -0.09. RLM folklore predicts a negative
slope (fade the move), so this bias runs IN FAVOUR of the folklore: any
negative beta must clear roughly -0.09 before it means anything. A positive
beta cannot be manufactured by it.

==========================================================================
DECISION RULE
==========================================================================
If the pre-registered statistics do not clear the threshold, the answer is
"no detectable edge", qualified by the minimum detectable effect below.
No window, filter or cutoff will be adjusted to chase significance.
==========================================================================
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data", "nflverse")
RAW = sys.argv[1] if len(sys.argv) > 1 else None

TRAIN = [2023, 2024]
TEST = [2025, 2026]
RULE = "=" * 88


def line(d, *path):
    """The LINE lives in alternateDisplayValue; `american` may hold a price."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if not isinstance(cur, dict):
        return None
    for key in ("alternateDisplayValue", "american"):
        v = cur.get(key)
        if v is None:
            continue
        try:
            return float(str(v).replace("+", ""))
        except ValueError:
            continue
    return None


def build():
    g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
    g = g[g["season"].isin(TRAIN + TEST)].dropna(subset=["espn", "result"])
    g["espn"] = g["espn"].astype("int64")
    rows = []
    for _, r in g.iterrows():
        p = os.path.join(RAW, "%d.json" % r["espn"])
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        for pid in ("58", "100"):
            it = next((x for x in d.get("items", [])
                       if str((x.get("provider") or {}).get("id")) == pid), None)
            if it is None:
                continue
            ho = it.get("homeTeamOdds") or {}
            o, c = line(ho, "open", "pointSpread"), line(ho, "close", "pointSpread")
            ot, ct = line(it, "open", "total"), line(it, "close", "total")
            if o is None or c is None:
                continue
            o, c = -o, -c                      # ESPN home view -> home favoured by
            if max(abs(o), abs(c)) > 30:
                continue
            rows.append(dict(game_id=r["game_id"], season=int(r["season"]),
                             week=int(r["week"]), pid=pid, result=float(r["result"]),
                             total_pts=float(r["total"]), open_sp=o, close_sp=c,
                             open_tt=ot, close_tt=ct))
    df = pd.DataFrame(rows)
    df["pri"] = df["pid"].map({"58": 0, "100": 1})
    df = df.sort_values("pri").drop_duplicates("game_id", keep="first")
    df["move_sp"] = df["close_sp"] - df["open_sp"]
    df["ats_resid"] = df["result"] - df["close_sp"]
    df["move_tt"] = df["close_tt"] - df["open_tt"]
    df["tot_resid"] = df["total_pts"] - df["close_tt"]
    return df.sort_values(["season", "week", "game_id"]).reset_index(drop=True)


def ols(df, y, x, label):
    d = df.dropna(subset=[y, x])
    m = sm.OLS(d[y], sm.add_constant(d[x])).fit(cov_type="HC3")
    b, se, p = m.params[x], m.bse[x], m.pvalues[x]
    lo, hi = b - 1.96 * se, b + 1.96 * se
    print("  %-34s n=%3d  beta=%+.4f  SE=%.4f  [%+.3f,%+.3f]  p=%.4f"
          % (label, len(d), b, se, lo, hi, p))
    return dict(label=label, n=len(d), beta=b, se=se, p=p, lo=lo, hi=hi)


def winrate(df, mv, resid, label, thresh=1.0):
    d = df.dropna(subset=[mv, resid])
    d = d[d[mv].abs() >= thresh]
    d = d[d[resid] != 0]                       # pushes excluded
    win = ((d[mv] > 0) == (d[resid] > 0)).sum()
    n = len(d)
    p = stats.binomtest(int(win), n, 0.5).pvalue
    print("  %-34s n=%3d  wins=%3d  rate=%.3f  p=%.4f  (break-even .5238)"
          % (label, n, int(win), win / n, p))
    return dict(label=label, n=n, rate=win / n, p=p)


def main():
    print(__doc__)
    df = build()
    tr = df[df.season.isin(TRAIN)]
    te = df[df.season.isin(TEST)]
    print(RULE)
    print("SAMPLE")
    print(RULE)
    for s, sub in df.groupby("season"):
        print("  %d: n=%3d" % (s, len(sub)))
    print("  TRAIN 2023-2024 n=%d   TEST 2025-2026 n=%d   TOTAL n=%d"
          % (len(tr), len(te), len(df)))
    print("  move_sp: sd=%.2f zero=%.1f%%   move_tt: sd=%.2f zero=%.1f%%"
          % (df.move_sp.std(), 100 * (df.move_sp == 0).mean(),
             df.move_tt.std(), 100 * (df.move_tt == 0).mean()))

    print("\n" + RULE)
    print("POWER -- smallest effect detectable at 80% power, alpha=.05 two-sided")
    print(RULE)
    for y, x, nm in [("ats_resid", "move_sp", "SPREAD"), ("tot_resid", "move_tt", "TOTAL")]:
        d = te.dropna(subset=[y, x])
        se = d[y].std() / (d[x].std() * np.sqrt(len(d)))
        print("  %-7s TEST n=%d  sd(resid)=%.2f sd(move)=%.2f -> SE(beta)~%.3f"
              "  MDE=%.3f pts of margin per pt of move"
              % (nm, len(d), d[y].std(), d[x].std(), se, 2.802 * se))
    n3 = len(te.dropna(subset=["move_sp", "ats_resid"]).query("abs(move_sp)>=1"))
    print("  WIN-RATE TEST n=%d -> MDE = %.1f%% ATS (break-even is 52.4%%)"
          % (n3, 100 * (0.5 + 2.802 * 0.5 / np.sqrt(n3))))

    print("\n" + RULE)
    print("PRE-REGISTERED RESULTS")
    print(RULE)
    res = []
    print(" [5,6] TRAIN 2023-2024 (in-sample, direction companions):")
    res.append(ols(tr, "ats_resid", "move_sp", "T5 train spread"))
    res.append(ols(tr, "tot_resid", "move_tt", "T6 train total"))
    print("\n [S1 PRIMARY / S2] TEST 2025-2026 (out of sample):")
    res.append(ols(te, "ats_resid", "move_sp", "S1 PRIMARY oos spread"))
    res.append(ols(te, "tot_resid", "move_tt", "S2 oos total"))
    print("\n [S3/S4] TEST 2025-2026 win rate, betting WITH the move, |move|>=1:")
    res.append(winrate(te, "move_sp", "ats_resid", "S3 oos spread win rate"))
    res.append(winrate(te, "move_tt", "tot_resid", "S4 oos total win rate"))

    print("\n" + RULE)
    print("VERDICT vs pre-registered thresholds (raw .05 / Bonferroni .0125)")
    print(RULE)
    for r in res:
        print("  %-34s p=%.4f  %s" % (r["label"], r["p"],
              "SIGNIFICANT" if r["p"] < 0.05 else "not significant"))
    print("\n  tests run this script: %d" % len(res))
    df.to_csv(os.path.join(DATA, "line_move_sample.csv"), index=False)


if __name__ == "__main__":
    main()
