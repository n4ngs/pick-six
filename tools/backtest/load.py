#!/usr/bin/env python3
"""
load.py -- the ONE loader every later backtest script imports.

Nothing here computes a feature. It reads the cache written by fetch.py and
hands back tidy frames, plus the two helpers that keep the cardinal rule
(no look-ahead) enforceable: a canonical game key and a strict season/week
ordering column.

    from load import load_games, load_pbp

    games = load_games(seasons=(2018, 2025), require_lines=True)
    pbp   = load_pbp(range(2018, 2026), columns=["game_id", "posteam", "epa"])

Run directly for a self-test:
    uv run --with pandas --with pyarrow python tools/backtest/load.py
"""

import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(REPO, "data", "nflverse")

GAMES_PATH = os.path.join(DATA_DIR, "games.csv")


def pbp_path(season):
    return os.path.join(DATA_DIR, "play_by_play_%d.parquet" % season)


def cached_pbp_seasons():
    """Seasons whose parquet is actually on disk."""
    out = []
    if not os.path.isdir(DATA_DIR):
        return out
    for fn in os.listdir(DATA_DIR):
        if fn.startswith("play_by_play_") and fn.endswith(".parquet"):
            try:
                out.append(int(fn[len("play_by_play_"):-len(".parquet")]))
            except ValueError:
                pass
    return sorted(out)


def _missing(path, what):
    raise FileNotFoundError(
        "%s not cached at %s -- run:\n"
        "  uv run --with pandas --with pyarrow python %s/fetch.py"
        % (what, path, HERE))


# --- ordering ------------------------------------------------------------
# REG weeks are 1..18; POST weeks continue from there in games.csv/pbp
# (nflverse numbers the postseason 19,20,21,22), so (season, week) is already
# a total order within a season. time_index makes it a total order across
# seasons, which is what every as-of / expanding-window feature must sort by.
def time_index(df):
    return df["season"].astype(int) * 100 + df["week"].astype(int)


def load_games(seasons=None, require_lines=False, played_only=False,
               season_type=None, path=None):
    """
    nflverse games.csv -- one row per game, schedule + CLOSING lines + starting QBs.

    seasons        (lo, hi) tuple, an iterable of seasons, or None for all.
    require_lines  drop rows without a complete closing spread + total + both
                   moneylines (these are the only rows a p_mkt fit can use).
    played_only    drop rows with no final result (future / unplayed games).
    season_type    'REG', 'POST', or None for both.

    Adds: time_index. Everything else is nflverse's own column, untouched --
    no derived feature is computed here, on purpose.
    """
    p = path or GAMES_PATH
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        _missing(p, "games.csv")
    g = pd.read_csv(p, low_memory=False)

    if seasons is not None:
        if isinstance(seasons, tuple) and len(seasons) == 2 and \
                all(isinstance(x, int) for x in seasons):
            lo, hi = seasons
            g = g[(g["season"] >= lo) & (g["season"] <= hi)]
        else:
            g = g[g["season"].isin(list(seasons))]

    if season_type is not None:
        g = g[g["game_type"].eq("REG") if season_type == "REG"
              else g["game_type"].ne("REG")]

    if played_only:
        g = g.dropna(subset=["result", "home_score", "away_score"])

    if require_lines:
        g = g.dropna(subset=["spread_line", "total_line",
                             "home_moneyline", "away_moneyline"])

    g = g.copy()
    g["time_index"] = time_index(g)
    return g.sort_values(["time_index", "game_id"]).reset_index(drop=True)


def load_pbp(seasons, columns=None, regular_only=False, offense_only=False):
    """
    nflfastR play-by-play for the given seasons, concatenated.

    seasons       iterable of ints, or a (lo, hi) tuple.
    columns       subset to read (huge speedup; the file has 372 columns).
                  season / week / game_id are always included.
    regular_only  season_type == 'REG' only.
    offense_only  play_type in {pass, run} only -- i.e. scrimmage plays with
                  a valid epa/success/xpass.

    Adds: time_index. Missing seasons raise, so a silent short backtest is
    impossible.
    """
    if isinstance(seasons, tuple) and len(seasons) == 2 and \
            all(isinstance(x, int) for x in seasons):
        seasons = range(seasons[0], seasons[1] + 1)
    seasons = sorted(set(int(s) for s in seasons))

    cols = None
    if columns is not None:
        cols = list(dict.fromkeys(
            list(columns) + ["season", "week", "game_id"]
            + (["season_type"] if regular_only else [])
            + (["play_type"] if offense_only else [])))

    frames = []
    for s in seasons:
        p = pbp_path(s)
        if not (os.path.exists(p) and os.path.getsize(p) > 0):
            _missing(p, "play_by_play_%d.parquet" % s)
        df = pd.read_parquet(p, columns=cols)
        if regular_only:
            df = df[df["season_type"].eq("REG")]
        if offense_only:
            df = df[df["play_type"].isin(["pass", "run"])]
        frames.append(df)

    pbp = pd.concat(frames, ignore_index=True, sort=False)
    pbp["time_index"] = time_index(pbp)
    return pbp


if __name__ == "__main__":
    print("cache dir: %s" % DATA_DIR)
    print("pbp seasons cached: %s" % cached_pbp_seasons())

    g = load_games()
    print("games: %d rows, seasons %d..%d"
          % (len(g), g["season"].min(), g["season"].max()))
    fit = load_games(seasons=(2018, 2025), require_lines=True,
                     played_only=True, season_type=None)
    print("fittable 2018-2025 (lines + result): %d rows" % len(fit))

    seas = cached_pbp_seasons()
    if seas:
        p = load_pbp([seas[-1]], columns=["posteam", "epa", "xpass", "pass_oe",
                                          "success", "yardline_100",
                                          "fixed_drive", "fixed_drive_result"],
                     offense_only=True)
        print("pbp %d scrimmage plays: %d rows, %d cols"
              % (seas[-1], len(p), p.shape[1]))
        print("join check: %d/%d pbp game_ids found in games.csv"
              % (p["game_id"].isin(set(g["game_id"])).sum(), len(p)))
