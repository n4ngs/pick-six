#!/usr/bin/env python3
"""
fetch.py -- OFFLINE backtest data fetcher for the Pick Six VAS model.

Downloads and caches, under <repo>/data/nflverse/ (gitignored):
  - games.csv          nflverse/nfldata  (schedule + closing lines + QBs + rest + weather)
  - play_by_play_<Y>.parquet  nflverse-data release asset (nflfastR pbp)

Then reports the REAL schema it observed: row counts, the actual pbp column
list, and null rates for the columns the VAS spec depends on.

Run:
  uv run --with pandas --with pyarrow python tools/backtest/fetch.py
Optional:
  --seasons 2018-2025      seasons to fetch (default 2018-2025)
  --probe 2026             extra seasons to HEAD-probe but not download
  --force                  re-download even if cached
"""

import argparse
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(REPO, "data", "nflverse")

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{year}.parquet")

# Columns the VAS spec leans on. Verified, not assumed.
SPEC_COLS = ["epa", "ep", "wp", "yardline_100", "pass", "rush", "xpass",
             "pass_oe", "success", "posteam", "defteam", "passer_player_id"]

# Extra columns the F / regime vectors will need; checked the same way.
EXTRA_COLS = ["season", "week", "game_id", "drive", "fixed_drive",
              "fixed_drive_result", "drive_end_yard_line", "play_type",
              "series", "series_result", "qb_kneel", "qb_spike",
              "special_teams_play", "home_team", "away_team", "season_type"]

UA = {"User-Agent": "pick-six-backtest/1.0 (offline research; nflverse public data)"}


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout)


def download(url, dest, force=False, label=""):
    """Download url -> dest. Returns (status, bytes, note)."""
    if (not force) and os.path.exists(dest) and os.path.getsize(dest) > 0:
        return ("cached", os.path.getsize(dest), "")
    tmp = dest + ".part"
    t0 = time.time()
    try:
        with _get(url) as resp, open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    except urllib.error.HTTPError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return ("http_%s" % e.code, 0, str(e.reason))
    except Exception as e:  # network, timeout, DNS ...
        if os.path.exists(tmp):
            os.remove(tmp)
        return ("error", 0, "%s: %s" % (type(e).__name__, e))
    size = os.path.getsize(tmp)
    if size == 0:
        os.remove(tmp)
        return ("empty", 0, "server returned 0 bytes")
    os.replace(tmp, dest)
    return ("downloaded", size, "%.1fs" % (time.time() - t0))


def probe(url):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERR(%s)" % type(e).__name__


def mb(n):
    return "%.1f MB" % (n / 1024.0 / 1024.0)


def parse_seasons(s):
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2018-2025")
    ap.add_argument("--probe", default="2026")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    seasons = parse_seasons(args.seasons)
    os.makedirs(DATA_DIR, exist_ok=True)
    print("cache dir: %s" % DATA_DIR)
    print("")

    # ---------- 1. games.csv ----------
    print("=" * 78)
    print("1. games.csv")
    print("=" * 78)
    games_path = os.path.join(DATA_DIR, "games.csv")
    status, size, note = download(GAMES_URL, games_path, force=args.force)
    print("  %-11s %-12s %s" % (status, mb(size), note))

    # ---------- 2. play-by-play ----------
    print("")
    print("=" * 78)
    print("2. play_by_play_<year>.parquet")
    print("=" * 78)
    pbp_paths = {}
    failed = []
    for yr in seasons:
        dest = os.path.join(DATA_DIR, "play_by_play_%d.parquet" % yr)
        status, size, note = download(PBP_URL.format(year=yr), dest,
                                      force=args.force)
        print("  %d  %-11s %-12s %s" % (yr, status, mb(size), note))
        if status in ("cached", "downloaded"):
            pbp_paths[yr] = dest
        else:
            failed.append((yr, status, note))

    for yr in parse_seasons(args.probe) if args.probe else []:
        if yr in pbp_paths:
            continue
        print("  %d  probe only -> HTTP %s" % (yr, probe(PBP_URL.format(year=yr))))

    # ---------- 3/4. real schema ----------
    import pandas as pd

    print("")
    print("=" * 78)
    print("3. REAL schema -- games.csv")
    print("=" * 78)
    games = pd.read_csv(games_path, low_memory=False)
    print("  rows: %d   cols: %d" % (len(games), games.shape[1]))
    if "season" in games:
        print("  seasons: %s .. %s" % (games["season"].min(), games["season"].max()))
    print("  columns (%d):" % games.shape[1])
    cols = list(games.columns)
    for i in range(0, len(cols), 6):
        print("    " + "  ".join("%-20s" % c for c in cols[i:i + 6]))

    # lines coverage -- the thing the fit actually needs
    need = ["spread_line", "total_line", "away_moneyline", "home_moneyline", "result"]
    have = [c for c in need if c in games.columns]
    if len(have) == len(need):
        for lo, hi in ((1999, 2025), (2018, 2025)):
            sub = games[(games["season"] >= lo) & (games["season"] <= hi)]
            complete = sub.dropna(subset=need)
            print("  %d-%d: %d games, %d with complete spread+total+ML+result"
                  % (lo, hi, len(sub), len(complete)))
    missing_games_cols = [c for c in
                          ["game_id", "season", "week", "gameday", "away_team",
                           "home_team", "away_score", "home_score", "result",
                           "total", "spread_line", "total_line", "away_moneyline",
                           "home_moneyline", "away_spread_odds", "home_spread_odds",
                           "under_odds", "over_odds", "away_rest", "home_rest",
                           "div_game", "roof", "surface", "temp", "wind",
                           "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name"]
                          if c not in games.columns]
    print("  expected-but-MISSING: %s" % (missing_games_cols or "none"))

    print("")
    print("=" * 78)
    print("4. REAL schema -- play-by-play")
    print("=" * 78)
    if not pbp_paths:
        print("  no pbp cached; nothing to verify")
        return 1

    import pyarrow.parquet as pq

    # Per-season row counts + column sets straight from parquet metadata (cheap).
    schemas = {}
    total_rows = 0
    print("  per-season rows:")
    for yr in sorted(pbp_paths):
        pf = pq.ParquetFile(pbp_paths[yr])
        n = pf.metadata.num_rows
        total_rows += n
        schemas[yr] = list(pf.schema_arrow.names)
        print("    %d  rows=%-8d cols=%-5d file=%s"
              % (yr, n, len(schemas[yr]), mb(os.path.getsize(pbp_paths[yr]))))
    print("    TOTAL rows=%d" % total_rows)

    latest = max(schemas)
    base = schemas[latest]
    print("")
    print("  ACTUAL columns of play_by_play_%d.parquet (%d):" % (latest, len(base)))
    for i in range(0, len(base), 5):
        print("    " + "  ".join("%-26s" % c for c in base[i:i + 5]))

    # column drift across seasons
    print("")
    print("  column drift vs %d:" % latest)
    drift = False
    for yr in sorted(schemas):
        only_yr = [c for c in schemas[yr] if c not in base]
        only_base = [c for c in base if c not in schemas[yr]]
        if only_yr or only_base:
            drift = True
            print("    %d  missing_here=%s  extra_here=%s"
                  % (yr, only_base[:12], only_yr[:12]))
    if not drift:
        print("    none -- identical column sets %d..%d"
              % (min(schemas), max(schemas)))

    # ---------- null / usability check on the spec columns ----------
    print("")
    print("  spec-column existence + null rate (non-null %% of all rows;")
    print("  'on offense plays' = rows where play_type in pass/run):")
    check = [c for c in SPEC_COLS + EXTRA_COLS]
    present_all = [c for c in check if all(c in schemas[y] for y in schemas)]
    absent_any = [c for c in check if c not in present_all]

    hdr = "    %-22s %8s %10s %10s" % ("column", "exists", "nonnull%", "nonnull%off")
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))
    read_cols = [c for c in check if c in base]
    if "play_type" not in read_cols:
        read_cols.append("play_type")
    frames = []
    for yr in sorted(pbp_paths):
        cols_here = [c for c in read_cols if c in schemas[yr]]
        df = pd.read_parquet(pbp_paths[yr], columns=cols_here)
        df["__season__"] = yr
        frames.append(df)
    allp = pd.concat(frames, ignore_index=True, sort=False)
    off = allp[allp.get("play_type").isin(["pass", "run"])] if "play_type" in allp else allp

    for c in check:
        exists = c in allp.columns
        if not exists:
            print("    %-22s %8s %10s %10s" % (c, "NO", "-", "-"))
            continue
        nn = 100.0 * allp[c].notna().mean()
        nno = 100.0 * off[c].notna().mean() if len(off) else float("nan")
        print("    %-22s %8s %9.1f%% %9.1f%%" % (c, "yes", nn, nno))

    # per-season non-null for the columns that are known to arrive late
    watch = [c for c in ["xpass", "pass_oe", "success", "epa", "wp", "cp", "cpoe"]
             if c in allp.columns]
    if watch:
        print("")
        print("  per-season non-null%% on pass/run plays (late-arriving fields):")
        print("    %-6s %s" % ("season", " ".join("%-10s" % w for w in watch)))
        for yr in sorted(pbp_paths):
            sub = off[off["__season__"] == yr]
            row = " ".join("%-10s" % ("%.1f%%" % (100.0 * sub[w].notna().mean()))
                           for w in watch)
            print("    %-6d %s" % (yr, row))

    print("")
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print("  games.csv rows: %d" % len(games))
    print("  pbp seasons cached: %s" % sorted(pbp_paths))
    print("  pbp seasons FAILED: %s" % (failed or "none"))
    print("  spec cols absent from >=1 season: %s" % (absent_any or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
