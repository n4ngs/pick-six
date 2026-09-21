#!/usr/bin/env python3
"""
fetch_openers.py -- harvest ESPN BET open/close lines for the line-move test.

DATA NOTE (measured, not assumed):
  * nflverse games.csv carries CLOSING lines only. No opener column exists.
  * nflverse/nfldata initial_lines.csv (Westgate openers) exists upstream but
    covers ONLY 2021 -- 272 games, 1088 rows. It was never extended. One season
    cannot support a season-wise train/test split, so it is unusable here.
  * ESPN core odds endpoint: probed 14 random games/season. An `open` block is
    absent 2013-2022, present 9/14 in 2023, 14/14 in 2024 and 2025.
  * Provider id 58 = "ESPN BET" (pregame). Provider id 59 = "ESPN Bet - Live
    Odds" and carries IN-GAME numbers (observed spread 3.5 / total 63.5 on a
    game that closed -2.5 / 43.5). 59 is excluded. Only 58 is used.

Writes: data/nflverse/espn_open_close.csv  (one row per game)
Touches nothing else.
"""
import concurrent.futures as cf
import json
import os
import sys
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data", "nflverse")
OUT = os.path.join(DATA, "espn_open_close.csv")

ESPN_BET_PROVIDER_ID = "58"
SEASONS = [2023, 2024, 2025, 2026]


def _num(d, *path):
    """Walk a nested dict, return float of the 'american' string, else None."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if isinstance(cur, dict):
        # The LINE lives in alternateDisplayValue. `american` sometimes holds
        # the PRICE (-110) or, on records with no opener, a moneyline (+130),
        # so it is only a fallback. Getting this backwards produced a close
        # series that disagreed with nflverse at sd=27 points.
        cur = cur.get("alternateDisplayValue", cur.get("american"))
    if cur is None:
        return None
    try:
        return float(str(cur).replace("+", "").replace(",", ""))
    except ValueError:
        return None


def fetch_one(ev):
    url = ("http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
           "events/%s/competitions/%s/odds" % (ev, ev))
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=25))
            break
        except Exception:
            d = None
    if d is None:
        return {"espn": ev, "ok": 0}

    item = None
    for it in d.get("items", []):
        pid = str((it.get("provider") or {}).get("id"))
        if pid == ESPN_BET_PROVIDER_ID:
            item = it
            break
    if item is None:
        return {"espn": ev, "ok": 0}

    ho = item.get("homeTeamOdds") or {}
    ao = item.get("awayTeamOdds") or {}
    r = {"espn": ev, "ok": 1}
    # ESPN states the point spread from each team's own view: "-2.5" = that
    # team laid 2.5. nflverse spread_line = points the HOME team is favoured
    # by, so it is the NEGATIVE of ESPN's home pointSpread.
    r["open_spread_home"] = _neg(_num(ho, "open", "pointSpread"))
    r["close_spread_home"] = _neg(_num(ho, "close", "pointSpread"))
    r["open_spread_away_raw"] = _num(ao, "open", "pointSpread")
    r["close_spread_away_raw"] = _num(ao, "close", "pointSpread")
    r["open_total"] = _num(item, "open", "total")
    r["close_total"] = _num(item, "close", "total")
    r["open_ml_home"] = _num(ho, "open", "moneyLine")
    r["close_ml_home"] = _num(ho, "close", "moneyLine")
    r["open_ml_away"] = _num(ao, "open", "moneyLine")
    r["close_ml_away"] = _num(ao, "close", "moneyLine")
    return r


def _neg(x):
    return None if x is None else -x


def main():
    g = pd.read_csv(os.path.join(DATA, "games.csv"), low_memory=False)
    g = g[g["season"].isin(SEASONS)].dropna(subset=["espn", "result"])
    evs = [str(int(e)) for e in g["espn"]]
    print("fetching %d games (%s)" % (len(evs), SEASONS))

    rows = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, r in enumerate(ex.map(fetch_one, evs), 1):
            rows.append(r)
            if i % 100 == 0:
                print("  %d/%d" % (i, len(evs)), flush=True)

    out = pd.DataFrame(rows)
    out["espn"] = out["espn"].astype("int64")
    out.to_csv(OUT, index=False)
    print("wrote %s  rows=%d  provider58_hit=%d"
          % (OUT, len(out), int(out["ok"].sum())))


if __name__ == "__main__":
    main()
