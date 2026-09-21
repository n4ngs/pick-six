#!/usr/bin/env python3
"""
features_fundamental.py -- Vector F (Fundamental): "is the record earned?"

VAS.md, Vector 1. Everything here answers one question about a scheduled game:
given ONLY what was knowable before kickoff, how much better is the home team
than the away team, in units of true-talent standard deviations?

    build(games_df, pbp_df) -> DataFrame keyed by game_id

THE CARDINAL RULE
-----------------
Every number for a game in season S week W is built from plays with a strictly
smaller time_index, within season S, for that team. Mechanically this is a
per-(team, season) cumsum followed by .shift(1), so the target game's own plays
can never enter its own feature -- the shift removes them by construction, not
by a filter someone can forget to write.

The pbp parquet carries the game's FINAL SCORE on every play row (result, total,
home_score, away_score, spread_line, total_line, vegas_wp*). Those columns are
never requested (see PBP_COLUMNS) and _assert_no_leak() refuses to run if a
caller hands them in anyway.

Cross-season information enters in exactly one controlled place: the empirical
Bayes PRIOR MEAN for a team in season S is its season S-1 rating regressed to
the league mean by rho, the year-over-year autocorrelation estimated from
seasons strictly before S. The hyperparameters (k, sigma_between, rho, league
means) are themselves estimated on an expanding window of prior seasons only.
The earliest season in the frame has no prior and falls back to its own
estimates for SCALE CONSTANTS only; that is reported, not hidden.

THE THREE TERMS
---------------
eff      net EPA per play      = off EPA/play - def EPA/play allowed
finish   net finishing / drive = (points scored - peak EP the drive created),
                                 offense minus the same allowed on defense
success  net success rate      = off success rate - def success rate allowed

`finish` is the term VAS.md v0 got wrong. v0's luck term was algebraically zero
whenever both teams saw equal drives. This one is not derivable from `eff`:
`eff` sums per-play EP changes, `finish` compares points actually put on the
board against max(ep) -- the single best scoring position the drive ever
reached, a STATE and not a sum. A drive that reaches 1st-and-goal at the 3
(max_ep ~5.5) scores 7, 3 or 0, and that gap is finishing. _sanity() prints the
variance and the correlation with `eff`, so the degenerate case is loud.

Sign: a team that has been finishing ABOVE expectation has an inflated record,
and the market has already priced the record, so finishing enters F negatively.

SHRINKAGE
---------
    theta_hat = (n*theta_obs + k*theta_prior) / (n + k)
    k         = sigma_within^2 / sigma_between^2          (flat prior)
    k         = sigma_within^2 / (sigma_between^2 * (1-rho^2))   (carryover prior)

k is computed from the data, never hardcoded. With a carryover prior the prior
is tighter, so k is correctly larger -- that factor is derived, not tuned.

Z-SCORES
--------
Ratings are divided by sigma_between (the TRUE-TALENT spread), NOT by the
cross-sectional SD of the shrunk ratings. Dividing by the contemporaneous SD
would re-inflate a Week 2 rating back to unit variance and undo the shrinkage,
which is exactly the confident-garbage failure VAS.md is guarding against.
With a fixed scale, a Week 2 F is honestly small and a Week 14 F is honestly
large. Team z-scores are formed first, then differenced and divided by sqrt(2).

Run directly for the full sanity report:
    uv run --with pandas --with pyarrow --with numpy python \
        tools/backtest/features_fundamental.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import load_games, load_pbp, cached_pbp_seasons  # noqa: E402


# --- what this module reads, and what it refuses to read -----------------

PBP_COLUMNS = [
    "game_id", "season", "week", "play_id",
    "posteam", "defteam", "home_team",
    "play_type", "epa", "ep", "success", "yardline_100",
    "fixed_drive", "total_home_score", "total_away_score",
]

# Constant-across-the-game outcome columns. See the leakage finding: these sit
# on EVERY play row of a game, so any aggregate that touches them leaks.
LEAK_COLUMNS = [
    "result", "total", "home_score", "away_score", "spread_line", "total_line",
    "vegas_wp", "vegas_home_wp", "vegas_wpa", "vegas_home_wpa",
]

# Plays that carry a valid epa/success for offensive efficiency.
EFFICIENCY_PLAYS = ("pass", "run")
# Plays that establish where a drive actually got to (a punt/FG snap is the
# drive's deepest snap spot, so it counts toward field position).
SCRIMMAGE_PLAYS = ("pass", "run", "punt", "field_goal", "qb_kneel", "qb_spike")

# Franchise moves inside the nflverse era. pbp and games.csv both switch codes
# mid-file, which would silently break the season-to-season carryover prior.
TEAM_ALIAS = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

# Empirical-Bayes components: name -> (sum col, sum-of-squares col, count col)
COMPONENTS = {
    "off_epa":  ("off_epa_sum",  "off_epa_sq",  "off_plays"),
    "def_epa":  ("def_epa_sum",  "def_epa_sq",  "def_plays"),
    "off_succ": ("off_succ_sum", "off_succ_sq", "off_plays"),
    "def_succ": ("def_succ_sum", "def_succ_sq", "def_plays"),
    "off_fin":  ("off_fin_sum",  "off_fin_sq",  "off_drives"),
    "def_fin":  ("def_fin_sum",  "def_fin_sq",  "def_drives"),
}

# Rating -> (offensive component, defensive component). Rating = off - def, so
# higher is always better and the league mean is 0 by construction (every play
# is some team's offense and some other team's defense).
RATINGS = {
    "eff":     ("off_epa",  "def_epa"),
    "finish":  ("off_fin",  "def_fin"),
    "success": ("off_succ", "def_succ"),
}

TINY = 1e-9


def _assert_no_leak(pbp):
    bad = [c for c in LEAK_COLUMNS if c in pbp.columns]
    if bad:
        raise ValueError(
            "pbp frame carries final-outcome columns %s. These are constant "
            "across every play of a game and will leak the result into the "
            "feature. Load pbp with columns=PBP_COLUMNS." % bad)


def _canon(s):
    return s.replace(TEAM_ALIAS)


# --- drives ---------------------------------------------------------------

def _drive_table(pbp):
    """
    One row per drive: who had the ball, how many points the drive was worth to
    them (signed, so a pick-six is negative), and max(ep) -- the best scoring
    position the drive ever reached, which is what those points are judged
    against.

    Points come from the running scoreboard rather than fixed_drive_result, so
    extra points, two-point tries, safeties and defensive touchdowns all land
    on the right side automatically. fixed_drive includes the PAT and starts at
    the kickoff, both verified.
    """
    p = pbp.dropna(subset=["fixed_drive"]).copy()
    p["drive_key"] = (p["game_id"].astype(str) + "|"
                      + p["fixed_drive"].astype(int).astype(str))

    grp = p.groupby("drive_key", sort=False)
    d = pd.DataFrame({
        "game_id": grp["game_id"].first(),
        "season": grp["season"].first(),
        "week": grp["week"].first(),
        "home_team": grp["home_team"].first(),
        "play_id": grp["play_id"].first(),
        "home_end": grp["total_home_score"].last(),
        "away_end": grp["total_away_score"].last(),
    })
    d = d.sort_values(["game_id", "play_id"])

    prev = d.groupby("game_id")[["home_end", "away_end"]].shift(1).fillna(0.0)
    net_home = d["home_end"] - prev["home_end"]
    net_away = d["away_end"] - prev["away_end"]

    scrim = p[p["play_type"].isin(SCRIMMAGE_PLAYS)]
    sgrp = scrim.groupby("drive_key", sort=False)
    d["off"] = sgrp["posteam"].first()
    d["def"] = sgrp["defteam"].first()

    # Possession can change inside a fixed_drive (rare). Only the drive's own
    # offense may contribute to its peak expected points.
    s2 = scrim[["drive_key", "posteam", "ep"]].merge(
        d["off"].rename("drive_off"), left_on="drive_key", right_index=True,
        how="left")
    s2 = s2[(s2["posteam"] == s2["drive_off"]) & s2["ep"].notna()]
    d["max_ep"] = s2.groupby("drive_key", sort=False)["ep"].max()

    d["off_pts"] = np.where(d["off"].values == d["home_team"].values,
                            (net_home - net_away).values,
                            (net_away - net_home).values)
    d["finishing"] = d["off_pts"] - d["max_ep"]

    # Drives with no offensive snap at all (kickoff returned for a score, end
    # of half on a kneel-less clock run-out) have no field position to judge.
    return d.dropna(subset=["off", "def", "max_ep"]).reset_index(drop=True)


# --- per team per game ----------------------------------------------------

def _team_game_table(pbp, drives):
    """
    Long frame: one row per (game_id, team), holding the SUMS and COUNTS that
    an expanding window can add up. Sums of squares ride along so sigma_within
    is computable without a second pass over the plays.
    """
    eff = pbp[pbp["play_type"].isin(EFFICIENCY_PLAYS)]
    eff = eff[eff["epa"].notna() & eff["posteam"].notna()
              & eff["defteam"].notna()].copy()
    eff["epa_sq"] = eff["epa"] ** 2
    eff["succ_sq"] = eff["success"] ** 2

    o = eff.groupby(["game_id", "posteam"]).agg(
        off_epa_sum=("epa", "sum"), off_epa_sq=("epa_sq", "sum"),
        off_succ_sum=("success", "sum"), off_succ_sq=("succ_sq", "sum"),
        off_plays=("epa", "size")).reset_index().rename(
            columns={"posteam": "team"})
    dv = eff.groupby(["game_id", "defteam"]).agg(
        def_epa_sum=("epa", "sum"), def_epa_sq=("epa_sq", "sum"),
        def_succ_sum=("success", "sum"), def_succ_sq=("succ_sq", "sum"),
        def_plays=("epa", "size")).reset_index().rename(
            columns={"defteam": "team"})

    dr = drives.copy()
    dr["fin_sq"] = dr["finishing"] ** 2
    od = dr.groupby(["game_id", "off"]).agg(
        off_fin_sum=("finishing", "sum"), off_fin_sq=("fin_sq", "sum"),
        off_drives=("finishing", "size")).reset_index().rename(
            columns={"off": "team"})
    dd = dr.groupby(["game_id", "def"]).agg(
        def_fin_sum=("finishing", "sum"), def_fin_sq=("fin_sq", "sum"),
        def_drives=("finishing", "size")).reset_index().rename(
            columns={"def": "team"})

    tg = o.merge(dv, on=["game_id", "team"], how="outer")
    tg = tg.merge(od, on=["game_id", "team"], how="outer")
    tg = tg.merge(dd, on=["game_id", "team"], how="outer")

    meta = pbp.groupby("game_id").agg(season=("season", "first"),
                                      week=("week", "first")).reset_index()
    tg = tg.merge(meta, on="game_id", how="left")
    tg["time_index"] = tg["season"].astype(int) * 100 + tg["week"].astype(int)

    num = [c for c in tg.columns
           if c not in ("game_id", "team", "season", "week", "time_index")]
    tg[num] = tg[num].fillna(0.0)
    return tg.sort_values(["team", "time_index", "game_id"]).reset_index(
        drop=True)


# --- hyperparameters, estimated ------------------------------------------

def _season_totals(tg):
    """Team-season sums -- the unit sigma_between is measured across."""
    return tg.groupby(["season", "team"], as_index=False).sum(
        numeric_only=True).drop(columns=["week", "time_index"],
                                errors="ignore")


def _estimate_hyper(ts):
    """
    ts: team-season totals over the seasons allowed to inform this estimate.

    Per component:
        sigma_within^2  pooled play-to-play (or drive-to-drive) variance
        sigma_between^2 Var(team-season means) - sigma_within^2 * mean(1/n)
        k               sigma_within^2 / sigma_between^2
        rho             year-over-year correlation of team-season means
        league          grand mean
    Per rating (off - def), sigma_between is measured on the rating directly,
    with the sampling noise of both halves removed.
    """
    h = {"components": {}, "ratings": {}, "n_team_seasons": int(len(ts)),
         "seasons": sorted(ts["season"].unique().tolist())}

    for name, (csum, csq, cn) in COMPONENTS.items():
        n = ts[cn].astype(float)
        ok = n > 0
        n, s, sq = n[ok], ts[csum].astype(float)[ok], ts[csq].astype(float)[ok]
        mean_i = s / n

        dof = float(n.sum() - len(n))
        sw2 = float((sq.sum() - (n * mean_i ** 2).sum()) / max(dof, 1.0))
        sw2 = max(sw2, TINY)

        var_obs = float(mean_i.var(ddof=1)) if len(mean_i) > 1 else 0.0
        sb2 = max(var_obs - sw2 * float((1.0 / n).mean()), TINY)

        wide = pd.DataFrame({
            "season": ts["season"][ok], "team": ts["team"][ok],
            "m": mean_i}).pivot(index="team", columns="season", values="m")
        pairs_a, pairs_b = [], []
        for s0, s1 in zip(wide.columns[:-1], wide.columns[1:]):
            pair = wide[[s0, s1]].dropna()
            pairs_a.extend(pair[s0].tolist())
            pairs_b.extend(pair[s1].tolist())
        rho = (float(np.corrcoef(pairs_a, pairs_b)[0, 1])
               if len(pairs_a) > 3 else 0.0)
        if not np.isfinite(rho):
            rho = 0.0
        rho = float(np.clip(rho, 0.0, 0.95))

        h["components"][name] = {
            "sigma_within": float(np.sqrt(sw2)),
            "sigma_between": float(np.sqrt(sb2)),
            "k_flat": float(sw2 / sb2),
            "k_carry": float(sw2 / (sb2 * (1.0 - rho ** 2))),
            "rho": rho,
            "league": float(s.sum() / n.sum()),
            "n_obs": float(n.sum()),
        }

    for rname, (oc, dc) in RATINGS.items():
        osum, _, on = COMPONENTS[oc]
        dsum, _, dn = COMPONENTS[dc]
        ok = (ts[on] > 0) & (ts[dn] > 0)
        r = (ts[osum][ok] / ts[on][ok]) - (ts[dsum][ok] / ts[dn][ok])
        noise = (h["components"][oc]["sigma_within"] ** 2 / ts[on][ok]
                 + h["components"][dc]["sigma_within"] ** 2 / ts[dn][ok])
        sb2 = max(float(r.var(ddof=1)) - float(noise.mean()), TINY)
        h["ratings"][rname] = {
            "sigma_between": float(np.sqrt(sb2)),
            "raw_sd": float(r.std(ddof=1)),
            "league": float(r.mean()),
        }
    return h


def _hyper_by_season(tg, verbose=True):
    """
    Expanding window: season S is parameterised by seasons strictly before S.
    The first season has no prior and reuses its own -- scale constants only
    (k, sigma_between, rho, league mean), no game-level information, but it is
    self-referential and is reported as such.
    """
    ts = _season_totals(tg)
    seasons = sorted(ts["season"].unique().tolist())
    out, fallback = {}, []
    for s in seasons:
        prior = ts[ts["season"] < s]
        if prior["season"].nunique() >= 2:
            h = _estimate_hyper(prior)
            h["source"] = "prior seasons %s" % (
                sorted(prior["season"].unique().tolist()),)
        else:
            # <2 prior seasons means rho is not estimable; use the whole
            # available frame's scale constants and say so.
            h = _estimate_hyper(ts)
            h["source"] = "SELF (insufficient prior seasons)"
            fallback.append(s)
        out[s] = h
    if verbose and fallback:
        print("  note: seasons %s use self-estimated scale constants "
              "(no 2+ prior seasons in the frame)" % fallback)
    return out, ts


# --- as-of accumulation ---------------------------------------------------

def _asof(tg):
    """
    Prior-games-only running totals. cumsum then shift(1) inside
    (team, season): the shift is what makes the target game's own plays
    unreachable. Week 1 comes out as all-zero counts, which is correct -- there
    is no within-season evidence yet and the prior carries the whole rating.
    """
    cols = [c for c in tg.columns
            if c not in ("game_id", "team", "season", "week", "time_index")]
    tg = tg.sort_values(["team", "season", "time_index", "game_id"]).copy()
    g = tg.groupby(["team", "season"], sort=False)
    prior = g[cols].cumsum() - tg[cols]          # exclusive cumulative sum
    prior.columns = ["prior_" + c for c in cols]
    tg["prior_games"] = g.cumcount()
    return pd.concat([tg[["game_id", "team", "season", "week", "time_index",
                          "prior_games"]], prior], axis=1)


def _prev_season_means(ts):
    """Team's raw full-season component means, keyed to the FOLLOWING season."""
    rows = {}
    for name, (csum, _, cn) in COMPONENTS.items():
        m = np.where(ts[cn] > 0, ts[csum] / ts[cn].replace(0, np.nan), np.nan)
        rows["prev_" + name] = m
    prev = pd.DataFrame(rows)
    prev["team"] = ts["team"].values
    prev["season"] = ts["season"].values + 1      # available to the NEXT season
    return prev


def _shrink(asof, prev, hyper, carryover):
    """theta_hat per component, then ratings, then z against sigma_between."""
    df = asof.merge(prev, on=["team", "season"], how="left")

    for name, (csum, _, cn) in COMPONENTS.items():
        ksel = "k_carry" if carryover else "k_flat"
        k = df["season"].map(lambda s: hyper[s]["components"][name][ksel])
        league = df["season"].map(lambda s: hyper[s]["components"][name]["league"])
        rho = df["season"].map(lambda s: hyper[s]["components"][name]["rho"])
        kflat = df["season"].map(
            lambda s: hyper[s]["components"][name]["k_flat"])

        if carryover:
            prev_m = df["prev_" + name]
            has_prev = prev_m.notna()
            prior_mean = np.where(has_prev,
                                  league + rho * (prev_m.fillna(league) - league),
                                  league)
            k_used = np.where(has_prev, k, kflat)
        else:
            prior_mean = league.values
            k_used = kflat.values

        n = df["prior_" + cn].astype(float).values
        s = df["prior_" + csum].astype(float).values
        df[name + "_hat"] = (s + k_used * prior_mean) / (n + k_used)

    for rname, (oc, dc) in RATINGS.items():
        sb = df["season"].map(lambda s: hyper[s]["ratings"][rname]["sigma_between"])
        rating = df[oc + "_hat"] - df[dc + "_hat"]
        # Structural league mean is 0; the tiny residual from unequal n and
        # unequal priors is removed cross-sectionally, using only teams' own
        # prior-game states in that week (no future data).
        centre = rating.groupby([df["season"], df["week"]]).transform("mean")
        df[rname + "_rating"] = rating
        df[rname + "_z"] = (rating - centre) / sb
    return df


# --- public API -----------------------------------------------------------

def build(games_df, pbp_df, carryover=True, verbose=True):
    """
    games_df  rows to produce features for (load_games(...)).
    pbp_df    play-by-play covering those seasons, loaded with PBP_COLUMNS.
              Must be the FULL play set, not offense_only -- drive scoring
              needs kickoffs and extra points.

    Returns one row per game_id:

        f_eff       home-minus-away z of net EPA/play          (+ = home better)
        f_finish    home-minus-away z of net finishing/drive    (+ = home luckier)
        f_success   home-minus-away z of net success rate       (+ = home better)
        f_finish_resid  f_finish with the part f_eff explains removed --
                    prefer THIS over f_finish in a joint fit (see below)
        F           (f_eff - f_finish) / sqrt(2), equal-weight default
        *_nc        the same three with a flat league-mean prior (no carryover)
        F_nc        equal-weight default over the _nc terms
        home_*_z / away_*_z   the team-level z-scores before differencing
        home_prior_games / away_prior_games / *_prior_plays / *_prior_drives
        f_ready     both teams have at least one prior game this season

    Fit the three components separately -- VAS.md's w1/w2 are absorbed into the
    regression, so `F` is a convenience column, not the thing to fit. In a
    joint fit use f_finish_resid rather than f_finish (VIF 1.1 vs 2.8).

    Pass EVERY cached season, not just the ones you want rows for. The earliest
    season in pbp_df has no season-before-it to regress from, so its Week 1
    games fall back to the flat league prior and come out at exactly 0. Feed
    2018-2025 and slice the output; do not feed 2024-2025 and wonder why
    Week 1 2024 is empty.
    """
    _assert_no_leak(pbp_df)
    missing = [c for c in PBP_COLUMNS if c not in pbp_df.columns]
    if missing:
        raise ValueError("pbp frame is missing %s" % missing)
    if set(pbp_df["play_type"].dropna().unique()) <= set(EFFICIENCY_PLAYS):
        raise ValueError(
            "pbp frame looks like it was loaded with offense_only=True. Drive "
            "scoring needs kickoffs and extra points -- load the full play set.")

    p = pbp_df.copy()
    for c in ("posteam", "defteam", "home_team"):
        p[c] = _canon(p[c])

    if verbose:
        print("  plays in: %d over seasons %s"
              % (len(p), sorted(p["season"].unique().tolist())))

    drives = _drive_table(p)
    tg = _team_game_table(p, drives)
    hyper, ts = _hyper_by_season(tg, verbose=verbose)
    prev = _prev_season_means(ts)
    asof = _asof(tg)

    frames = {}
    for tag, carry in (("", carryover), ("_nc", False)):
        frames[tag] = _shrink(asof, prev, hyper, carry)

    g = games_df.copy()
    g["_home"] = _canon(g["home_team"])
    g["_away"] = _canon(g["away_team"])

    out = g[["game_id", "season", "week", "time_index",
             "home_team", "away_team"]].copy()

    for tag, df in frames.items():
        keep = ["game_id", "team", "prior_games", "prior_off_plays",
                "prior_def_plays", "prior_off_drives", "prior_def_drives"] + \
               [r + "_z" for r in RATINGS]
        slim = df[keep]
        for side, col in (("home", "_home"), ("away", "_away")):
            j = g[["game_id", col]].merge(
                slim, left_on=["game_id", col], right_on=["game_id", "team"],
                how="left")
            for r in RATINGS:
                out["%s_%s_z%s" % (side, r, tag)] = j[r + "_z"].values
            if tag == "":
                out[side + "_prior_games"] = j["prior_games"].values
                out[side + "_prior_plays"] = j["prior_off_plays"].values
                out[side + "_prior_drives"] = j["prior_off_drives"].values

        root2 = np.sqrt(2.0)
        for r, fname in (("eff", "f_eff"), ("finish", "f_finish"),
                         ("success", "f_success")):
            out[fname + tag] = (out["home_%s_z%s" % (r, tag)]
                                - out["away_%s_z%s" % (r, tag)]) / root2
        out["F" + tag] = (out["f_eff" + tag] - out["f_finish" + tag]) / root2

    out["f_ready"] = ((out["home_prior_games"].fillna(0) > 0)
                      & (out["away_prior_games"].fillna(0) > 0))

    # `finish` correlates ~0.8 with `eff` -- good offenses both advance and
    # convert -- which would make a joint logistic fit unstable. Strip the part
    # efficiency already explains, so what is left is the mean-reverting
    # remainder VAS.md actually wants. The slope is fitted on seasons strictly
    # BEFORE the target season, same discipline as everything else.
    ortho = {}
    for tag in ("", "_nc"):
        col, base = "f_finish" + tag, "f_eff" + tag
        out["f_finish_resid" + tag] = np.nan
        for s in sorted(out["season"].unique()):
            prior = out[out["season"] < s].dropna(subset=[col, base])
            if prior["season"].nunique() < 1:
                prior = out[out["season"] == out["season"].min()].dropna(
                    subset=[col, base])
                src = "SELF (earliest season)"
            else:
                src = "prior seasons"
            b, a = np.polyfit(prior[base], prior[col], 1)
            m = out["season"] == s
            out.loc[m, "f_finish_resid" + tag] = (
                out.loc[m, col] - (a + b * out.loc[m, base]))
            if tag == "":
                ortho[s] = (a, b, src, int(len(prior)))
    out.attrs["ortho"] = ortho

    out.attrs["hyper"] = hyper
    out.attrs["drives"] = drives
    out.attrs["team_game"] = tg
    return out.reset_index(drop=True)


# --- sanity ---------------------------------------------------------------

def _sanity(out, games_df):
    hyper = out.attrs["hyper"]
    drives = out.attrs["drives"]
    tg = out.attrs["team_game"]

    print("\n" + "=" * 78)
    print("ESTIMATED HYPERPARAMETERS (expanding window, prior seasons only)")
    print("=" * 78)
    rows = []
    for s in sorted(hyper):
        h = hyper[s]
        for name in COMPONENTS:
            c = h["components"][name]
            rows.append({"season": s, "component": name,
                         "sigma_within": c["sigma_within"],
                         "sigma_between": c["sigma_between"],
                         "k_flat": c["k_flat"], "k_carry": c["k_carry"],
                         "rho": c["rho"], "league_mean": c["league"]})
    hp = pd.DataFrame(rows)
    print(hp.to_string(index=False, float_format=lambda v: "%9.4f" % v))
    print("\nk is in PLAYS for epa/success components and in DRIVES for "
          "finishing.")
    fin = hp[hp.component.isin(["off_fin", "def_fin"])]
    print("  finishing k (drives): %.1f - %.1f   -> ~%.1f - %.1f games at "
          "11.2 drives/game" % (fin.k_flat.min(), fin.k_flat.max(),
                                fin.k_flat.min() / 11.2, fin.k_flat.max() / 11.2))
    epa = hp[hp.component.isin(["off_epa", "def_epa"])]
    print("  epa/play k (plays):   %.1f - %.1f   -> ~%.1f - %.1f games at "
          "32.5 off plays/game" % (epa.k_flat.min(), epa.k_flat.max(),
                                   epa.k_flat.min() / 32.5,
                                   epa.k_flat.max() / 32.5))
    print("\n  VAS.md guessed k=33 drives for points-per-drive. Measured "
          "finishing k lands at %.0f drives -- the spec's order of magnitude "
          "is right, the number is not hardcoded here." % fin.k_flat.mean())
    print("\nsigma_between per RATING (the z-score scale):")
    for s in sorted(hyper):
        r = hyper[s]["ratings"]
        print("  %d  eff %.4f  finish %.4f  success %.4f   [%s]"
              % (s, r["eff"]["sigma_between"], r["finish"]["sigma_between"],
                 r["success"]["sigma_between"], hyper[s]["source"]))

    print("\n" + "=" * 78)
    print("FINISHING TERM -- the v0 degeneracy check")
    print("=" * 78)
    print("per-drive finishing: n=%d mean=%.4f sd=%.4f min=%.2f max=%.2f"
          % (len(drives), drives.finishing.mean(), drives.finishing.std(),
             drives.finishing.min(), drives.finishing.max()))
    print("max_ep:             mean=%.4f sd=%.4f"
          % (drives.max_ep.mean(), drives.max_ep.std()))
    print("\nmean finishing by drive outcome (should separate cleanly):")
    dr = drives.copy()
    dr["pts_bucket"] = pd.cut(dr.off_pts, [-99, -0.5, 0.5, 3.5, 99],
                              labels=["negative", "none", "FG", "TD"])
    print(dr.groupby("pts_bucket", observed=True)["finishing"]
          .agg(["count", "mean", "std"]).to_string())

    tgf = tg[(tg.off_drives > 0) & (tg.def_drives > 0) & (tg.off_plays > 0)]
    fin_g = tgf.off_fin_sum / tgf.off_drives - tgf.def_fin_sum / tgf.def_drives
    eff_g = tgf.off_epa_sum / tgf.off_plays - tgf.def_epa_sum / tgf.def_plays
    c = float(np.corrcoef(fin_g, eff_g)[0, 1])
    print("\nteam-game net finishing vs net EPA/play: corr = %+.3f" % c)
    print("  variance of net finishing = %.4f" % float(fin_g.var()))
    verdict = ("FAIL - degenerate, this is the v0 bug" if fin_g.var() < 1e-6
               else "FAIL - collinear with efficiency, not a separate term"
               if abs(c) > 0.85 else "PASS - real variance, not a restatement "
               "of efficiency")
    print("  verdict: %s" % verdict)

    print("\n" + "=" * 78)
    print("NO-LOOK-AHEAD SELF-TESTS")
    print("=" * 78)
    w1 = out[out.week == 1]
    print("1. week-1 games have zero prior games: home %s away %s  (n=%d)"
          % (bool((w1.home_prior_games.fillna(0) == 0).all()),
             bool((w1.away_prior_games.fillna(0) == 0).all()), len(w1)))

    asof = _asof(tg)
    rng = np.random.default_rng(7)
    idx = rng.choice(len(asof), size=min(200, len(asof)), replace=False)
    bad = 0
    tg_i = tg.set_index(["team", "season"]).sort_index()
    for i in idx:
        row = asof.iloc[i]
        try:
            hist = tg_i.loc[(row["team"], row["season"])]
        except KeyError:
            continue
        if isinstance(hist, pd.Series):
            hist = hist.to_frame().T
        brute = hist[hist["time_index"] < row["time_index"]]
        if abs(float(brute["off_epa_sum"].sum())
               - float(row["prior_off_epa_sum"])) > 1e-6:
            bad += 1
        if row["game_id"] in set(brute["game_id"]):
            bad += 1
    print("2. brute-force recompute from strictly-earlier games only: "
          "%d/%d mismatches" % (bad, len(idx)))

    print("3. forbidden outcome columns present in output: %s"
          % [c for c in LEAK_COLUMNS if c in out.columns])

    print("\n" + "=" * 78)
    print("COVERAGE AND NaNs (%d games)" % len(out))
    print("=" * 78)
    fcols = ([f + t for t in ("", "_nc")
              for f in ("f_eff", "f_finish", "f_finish_resid",
                        "f_success", "F")])
    cov = pd.DataFrame({
        "non_null": [int(out[c].notna().sum()) for c in fcols],
        "nan": [int(out[c].isna().sum()) for c in fcols],
        "pct": [100.0 * out[c].notna().mean() for c in fcols],
    }, index=fcols)
    print(cov.to_string(float_format=lambda v: "%6.2f" % v))
    print("\nf_ready (both teams have >=1 prior game this season): %d / %d "
          "(%.1f%%)" % (int(out.f_ready.sum()), len(out),
                        100.0 * out.f_ready.mean()))
    print("games by week bucket:")
    print(out.assign(bucket=pd.cut(out.week, [0, 1, 4, 9, 18, 99],
                                   labels=["wk1", "wk2-4", "wk5-9",
                                           "wk10-18", "post"]))
          .groupby("bucket", observed=True)
          .agg(games=("game_id", "size"),
               ready=("f_ready", "sum"),
               f_eff_sd=("f_eff", "std")).to_string())

    print("\n" + "=" * 78)
    print("DISTRIBUTIONS")
    print("=" * 78)
    print(out[fcols].describe().T.to_string(
        float_format=lambda v: "%8.4f" % v))
    print("\nBy design the SD grows through the season -- shrinkage, not a bug:")
    print(out.groupby(pd.cut(out.week, [0, 1, 4, 9, 18, 99],
                             labels=["wk1", "wk2-4", "wk5-9", "wk10-18",
                                     "post"]), observed=True)[
        ["f_eff", "f_finish", "f_success"]].std().to_string(
        float_format=lambda v: "%7.4f" % v))

    print("\ncorrelations among the terms:")
    print(out[["f_eff", "f_finish", "f_finish_resid", "f_success"]].corr()
          .to_string(float_format=lambda v: "%6.3f" % v))

    print("\nmulticollinearity (R^2 of each term on the other two, and VIF):")
    for trio in (["f_eff", "f_finish", "f_success"],
                 ["f_eff", "f_finish_resid", "f_success"]):
        m = out[trio].dropna()
        line = []
        for c in trio:
            X = np.column_stack([np.ones(len(m))]
                                + [m[o].values for o in trio if o != c])
            beta, *_ = np.linalg.lstsq(X, m[c].values, rcond=None)
            r2 = 1.0 - (((m[c].values - X @ beta) ** 2).sum()
                        / ((m[c].values - m[c].mean()) ** 2).sum())
            line.append("%s R2=%.3f VIF=%.1f" % (c, r2, 1.0 / max(1 - r2, 1e-9)))
        print("   " + " | ".join(line))
    print("   -> use f_finish_resid in the joint fit; f_finish alone is fine"
          " on its own.")
    print("\northogonalisation slopes (f_finish ~ a + b*f_eff, prior seasons"
          " only):")
    for s_, (a, b, src, n) in sorted(out.attrs["ortho"].items()):
        print("   %d  a=%+.4f b=%+.4f  n=%d  [%s]" % (s_, a, b, n, src))
    print("\ncarryover vs flat prior:")
    for f in ("f_eff", "f_finish", "f_success"):
        m = out[[f, f + "_nc"]].dropna()
        print("  %-10s corr %.3f   sd %.3f vs %.3f"
              % (f, float(m.corr().iloc[0, 1]), m[f].std(), m[f + "_nc"].std()))

    print("\n" + "=" * 78)
    print("SMELL TEST vs the market (not a fit -- just direction)")
    print("=" * 78)
    j = out.merge(games_df[["game_id", "result", "spread_line"]],
                  on="game_id", how="inner").dropna(subset=["result"])
    j = j[j.f_ready]
    for f in ("f_eff", "f_finish", "f_finish_resid", "f_success"):
        k = j[[f, "result", "spread_line"]].dropna()
        resid = k["result"] - k["spread_line"]
        print("  %-10s corr(result) %+.3f | corr(spread_line) %+.3f | "
              "corr(result - spread) %+.3f"
              % (f, float(np.corrcoef(k[f], k["result"])[0, 1]),
                 float(np.corrcoef(k[f], k["spread_line"])[0, 1]),
                 float(np.corrcoef(k[f], resid)[0, 1])))
    print("\n  Column 2 is the one that matters. A strong corr with"
          " spread_line means the\n  market already prices it -- that is"
          " EXPECTED and healthy. Column 3 is what\n  is left over, and it"
          " should be SMALL. Anything above ~0.15 there deserves a\n"
          "  leakage hunt before it is believed.")


if __name__ == "__main__":
    seasons = cached_pbp_seasons()
    seasons = [s for s in seasons if 2018 <= s <= 2025]
    print("building Vector F over seasons %s" % seasons)

    games = load_games(seasons=(min(seasons), max(seasons)),
                       require_lines=True, played_only=True)
    print("  fittable games: %d" % len(games))

    pbp = load_pbp(seasons, columns=PBP_COLUMNS)
    out = build(games, pbp)
    print("  features built: %d rows, %d cols" % (out.shape[0], out.shape[1]))
    _sanity(out, games)

    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "out_fundamental.parquet")
    flat = out.copy()
    flat.attrs = {}            # attrs carry debug frames; parquet can't hold them
    flat.to_parquet(dest, index=False)
    print("\nwrote %s  (%d rows x %d cols)" % (dest, *flat.shape))
