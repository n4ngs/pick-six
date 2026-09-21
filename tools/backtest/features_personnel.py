#!/usr/bin/env python3
"""
features_personnel.py -- the PERSONNEL vector (P) for the Pick Six VAS backtest.

    from features_personnel import build, PBP_COLUMNS
    P = build(games_df, pbp_df)          # one row per game_id

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
---------------------------------------------
VAS.md Vector 2 defines P as the *unpriced residual* of the personnel news:

    P_raw = z(qbDelta) + 0.5*z(posIndex)
    moved = logit(p_mkt_now) - logit(p_mkt_at_report)
    P     = P_raw - (moved / B_P)

That residual is NOT computable from nflverse and is not computed here. It needs
`p_mkt_at_report` -- a per-book price timestamped against the moment the injury
news broke -- and games.csv carries a single CLOSING number per game with no
opening line and no history (46 columns; verified, there is no open). That series
comes from OddsPapi history or the app's own data/weeks/*.json, exactly as
VAS.md Layer 2 says, and it only accumulates going forward.

So this module builds the RAW vector: qbDelta, as-of, from history. The fit's job
is then to MEASURE how much of it the market has already absorbed.

    ****  A B_P NEAR ZERO IS THE EXPECTED AND CORRECT RESULT.  ****

The market has read the injury report. It knows who is starting -- games.csv's
own home_qb_id/away_qb_id is pregame-knowable precisely because the starter is
public information before kickoff, and the same information is in the closing
line. A market-anchored model that finds a large, significant B_P on a raw QB
quality difference is almost certainly leaking, not discovering. Under VAS.md's
own framing (null B = 0 means "the market already knows this"), a B_P whose
confidence interval spans zero means the QB term is decoration and gets deleted
from the served model -- and that is a finding, not a failure.

Nothing here is tuned toward significance. No target-derived quantity enters any
feature. If the coefficient comes out at zero, report zero.

THE NO-LOOK-AHEAD CONTRACT
--------------------------
Every number emitted for a game at (season S, week W) is computed from a state
built ONLY from plays with time_index STRICTLY LESS THAN S*100 + W.

  * Strictly-less-than on time_index excludes the whole of the target week, so
    the target game is excluded by construction -- which matters more than it
    looks, because the pbp parquet carries the game's FINAL SCORE on every one
    of its play rows (result / total / home_score / away_score / spread_line /
    total_line are constant across all ~150 plays of a game). This module never
    reads those columns; PBP_COLUMNS does not name them and build() asserts they
    are absent from the frame it is handed.
  * The league mean, the replacement level and the shrinkage constant k are all
    recomputed as-of at each week boundary from the prior pool only. No
    season-long or full-sample aggregate is used as a feature input.
  * Starter identity comes from games.csv home_qb_id/away_qb_id, which is
    legitimately known pregame and is 100% non-null 1999-2025.
  * The one soft spot is disclosed rather than hidden: see BURN-IN below.

QB PLAY ATTRIBUTION
-------------------
A "QB play" is a DROPBACK: qb_dropback == 1. On those rows the quarterback is
    passer_player_id, falling back to rusher_player_id
which resolves 100% of dropbacks (verified 2018-2025: 169,639 dropbacks, zero
unattributed, zero null EPA). This is the specific trap the fetch stage flagged:
filtering `pass == 1 & passer_player_id.notna()` silently drops every scramble,
because nflfastR codes a scramble as pass==1 / play_type=='run' and fills
rusher_player_id instead. qb_dropback catches pass attempts, sacks AND scrambles,
and excludes kneels and spikes (verified: zero of each among dropbacks).

Designed QB runs are excluded. They are only 7,209 plays against 169,639
dropbacks (4%) and their EPA is as much a function of the run scheme as of the
quarterback. EPA-per-dropback is the standard, well-behaved QB rate.

SHRINKAGE, AND WHY THE PRIOR IS REPLACEMENT AND NOT THE LEAGUE MEAN
-------------------------------------------------------------------
Empirical Bayes per VAS.md's shrinkage section:

    quality_hat = (n*x_obs + k*prior) / (n + k)
    k           = sigma_within^2 / sigma_between^2

measured as-of, not chosen. Over 2018-2025 this lands at sigma_within = 1.58
EPA/dropback, sigma_between = 0.101, so k ~ 244 dropbacks ~ 7 starts -- which
matches the usual finding that QB EPA/play stabilises somewhere in the low
hundreds of dropbacks.

The task brief says "shrunk toward the league QB mean", and also that a QB with
no prior snaps "must fall back to the replacement prior, NOT to NaN and NOT to
zero". Those two cannot both hold: shrinking toward the league mean sends an
unproven arm to league-average, which is the opposite of replacement. The second
requirement wins, because it is the one that is actually true about football. The
prior is therefore centred at the replacement level, and the requirement is then
satisfied continuously rather than by a special case -- n = 0 lands exactly on
replacement, n = 1 lands a hair off it, with no cliff between them.

The experience gradient this encodes is real and monotone (2018-2025, measured):

    prior dropbacks       0 : -0.110 EPA/db   (debuts)
    prior dropbacks   1- 199: -0.044
    prior dropbacks 200- 499: -0.001
    prior dropbacks 500- 999: +0.056
    prior dropbacks 1000-2999: +0.067
    prior dropbacks   3000+ : +0.122
    league overall          : +0.042

Some of that is survivorship -- quarterbacks who are good accumulate snaps -- and
that is exactly what a prior over an unproven arm should encode.

    replacement_level = as-of play-weighted EPA/dropback of every QB-game thrown
                        by a QB with fewer than 500 career dropbacks ENTERING
                        that game (expanding window, prior weeks only).
    qbDelta           = quality_hat - replacement_level

so qbDelta reads directly as "points per dropback above a fill-in".

Note that the replacement level CANCELS out of the headline differenced feature:
qb_delta_diff = (q_home - rep) - (q_away - rep) = q_home - q_away. Its drift
across the burn-in seasons (+0.051 in 2018 down to -0.028 by 2025, converging on
the full-sample figure) therefore does not contaminate p_qb. Where it genuinely
does work is as the SHRINKAGE TARGET, which is the point.

RECENCY
-------
Career and recent are combined once, before shrinking, rather than shrunk twice
and averaged:

    n_eff = n_recent + LAMBDA_OLD*(n_career - n_recent)
    s_eff = s_recent + LAMBDA_OLD*(s_career - s_recent)

with "recent" = the trailing RECENT_DROPBACKS window and LAMBDA_OLD = 0.35, so
older snaps still count but at about a third weight. The pure-career and
pure-recent shrunk values are emitted alongside as qb_quality_career_* /
qb_quality_recent_* so the fit can test either without recomputing anything.

BURN-IN -- the one disclosed soft spot
--------------------------------------
Weeks at the very start of the cached history have no prior pool to compute a
league mean, a replacement level or k from. Those rows fall back to BOOTSTRAP_*
constants, which were measured over the full 2018-2025 pool and are therefore
the one place a full-sample quantity touches the pipeline. Every affected row is
flagged `qb_history_thin`; drop the first cached season from the fit, or extend
the cache backwards (fetch.py --seasons 2015-2026) so the burn-in falls outside
the fitting window. The flag exists so this cannot be forgotten silently.

WHAT IS MISSING FROM P, RELATIVE TO VAS.md
------------------------------------------
posIndex (the weighted non-QB injury index: LT .18 | C .12 | CB1 .10 | EDGE1 .10
| WR1 .08 | other .02, times severity) is NOT emitted. nflverse carries no
historical injury-report status, so it cannot be built here at all, and emitting
a column of zeros under that name would be a lie that a later fit would happily
regress on. It stays live-only, off this frame. P here is the QB term alone.

The QB1 hard abort (VAS.md: depth-chart QB1 Out/Doubtful, or unresolved inside
90 minutes of kickoff) is a data-quality veto that sits OUTSIDE the probability
model and is not a feature. It is not modelled here either.

Self-test:
    uv run --with pandas --with pyarrow --with numpy --with scipy \
        python tools/backtest/features_personnel.py
"""

import os
import sys
from collections import deque

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import load_games, load_pbp, time_index  # noqa: E402


# --- pbp columns this module needs ---------------------------------------
# Deliberately minimal. None of the six outcome-carrying columns
# (result, total, home_score, away_score, spread_line, total_line) appears here,
# and build() refuses a frame that contains them.
PBP_COLUMNS = ["posteam", "epa", "qb_dropback",
               "passer_player_id", "rusher_player_id"]

LEAKY_PBP_COLUMNS = ["result", "total", "home_score", "away_score",
                     "spread_line", "total_line",
                     "vegas_wp", "vegas_home_wp", "vegas_wpa",
                     "vegas_home_wpa"]

# --- tunables (all documented above; none fitted against the target) ------
RECENT_DROPBACKS = 600      # trailing window ~ one full season of starts
LAMBDA_OLD = 0.35           # weight on career snaps outside the recent window
REPLACEMENT_MAX_DB = 500    # career dropbacks below which a QB-game is "replacement"
MIN_DB_FOR_SIGMA_B = 300    # QBs this experienced anchor the between-QB variance
K_FLOOR, K_CEIL = 50.0, 2000.0

# Bootstrap constants for the cold start ONLY. Measured over the full 2018-2025
# dropback pool; every row that uses them is flagged qb_history_thin.
BOOTSTRAP_LEAGUE_MEAN = 0.042
BOOTSTRAP_REPLACEMENT = -0.028
BOOTSTRAP_SIGMA_W = 1.584
BOOTSTRAP_SIGMA_B = 0.101
BOOTSTRAP_K = (BOOTSTRAP_SIGMA_W ** 2) / (BOOTSTRAP_SIGMA_B ** 2)

MIN_POOL_DB = 4000          # prior dropbacks needed before the as-of pool is trusted
MIN_REP_DB = 1200           # prior replacement-pool dropbacks likewise
MIN_ESTABLISHED_QB = 24     # QBs past REPLACEMENT_MAX_DB before "replacement" means
                            # anything -- at the start of a cache EVERY career reads
                            # as zero, so the replacement pool is just the league and
                            # the level sits at (not below) the league mean
MIN_Z_GAMES = 200           # prior games needed before the as-of z-score is trusted


# =========================================================================
# QB-game aggregation
# =========================================================================
def qb_game_table(pbp_df):
    """
    Collapse play-by-play to one row per (game, quarterback).

    Returns columns: time_index, game_id, qb, posteam, n, s, ss
    where n = dropbacks, s = sum of EPA, ss = sum of EPA^2 (ss feeds the
    as-of within-QB variance, which is half of the shrinkage constant).
    """
    missing = [c for c in PBP_COLUMNS if c not in pbp_df.columns]
    if missing:
        raise KeyError("pbp_df is missing %s -- load it with "
                       "load_pbp(seasons, columns=features_personnel.PBP_COLUMNS)"
                       % missing)
    leaks = [c for c in LEAKY_PBP_COLUMNS if c in pbp_df.columns]
    if leaks:
        raise ValueError(
            "pbp_df carries outcome columns %s. These are CONSTANT across every "
            "play row of a game -- they are the final score, not a play feature. "
            "Drop them from the working frame; load with "
            "columns=features_personnel.PBP_COLUMNS." % leaks)

    d = pbp_df[pbp_df["qb_dropback"].eq(1)].copy()
    if "time_index" not in d.columns:
        d["time_index"] = time_index(d)

    # passer, falling back to rusher -- the latter is where nflfastR puts the
    # quarterback on a scramble (pass==1, play_type=='run').
    d["qb"] = d["passer_player_id"].fillna(d["rusher_player_id"])
    d = d[d["qb"].notna() & d["epa"].notna()]
    d["_ss"] = d["epa"] ** 2

    qg = (d.groupby(["time_index", "game_id", "qb"], as_index=False)
            .agg(posteam=("posteam", "first"),
                 n=("epa", "size"),
                 s=("epa", "sum"),
                 ss=("_ss", "sum")))
    return qg.sort_values(["time_index", "game_id", "qb"]).reset_index(drop=True)


# =========================================================================
# the as-of pool
# =========================================================================
class _QBPool:
    """
    Expanding-window state over quarterback dropbacks.

    Every read (league_mean, replacement_level, k, quality) reflects only what
    has been add()ed so far. The driver in build() adds a week's plays only
    AFTER emitting that week's features, which is what enforces the strict
    time_index < target rule.
    """

    def __init__(self):
        self.cn, self.cs, self.css = {}, {}, {}   # career n / sum / sumsq
        self.win = {}                             # qb -> deque[(n, s)]
        self.rn, self.rs = {}, {}                 # recent-window n / sum
        self.tot_n, self.tot_s, self.tot_ss = 0, 0.0, 0.0
        self.rep_n, self.rep_s = 0, 0.0           # replacement-population pool
        self._cache = None

    # -- writes ----------------------------------------------------------
    def add(self, qb, n, s, ss):
        prior = self.cn.get(qb, 0)
        if prior < REPLACEMENT_MAX_DB:            # classified on PRIOR experience
            self.rep_n += n
            self.rep_s += s

        self.cn[qb] = prior + n
        self.cs[qb] = self.cs.get(qb, 0.0) + s
        self.css[qb] = self.css.get(qb, 0.0) + ss

        w = self.win.setdefault(qb, deque())
        w.append((n, s))
        self.rn[qb] = self.rn.get(qb, 0) + n
        self.rs[qb] = self.rs.get(qb, 0.0) + s
        while len(w) > 1 and self.rn[qb] - w[0][0] >= RECENT_DROPBACKS:
            on, os_ = w.popleft()
            self.rn[qb] -= on
            self.rs[qb] -= os_

        self.tot_n += n
        self.tot_s += s
        self.tot_ss += ss
        self._cache = None

    # -- reads -----------------------------------------------------------
    def constants(self):
        """(league_mean, replacement_level, k, thin) as of right now."""
        if self._cache is not None:
            return self._cache

        established = sum(1 for q in self.cn if self.cn[q] >= REPLACEMENT_MAX_DB)
        thin = (self.tot_n < MIN_POOL_DB) or (self.rep_n < MIN_REP_DB) \
            or (established < MIN_ESTABLISHED_QB)

        if self.tot_n >= MIN_POOL_DB:
            league = self.tot_s / self.tot_n
            sw2 = max((self.tot_ss - self.tot_s ** 2 / self.tot_n)
                      / max(self.tot_n - 1, 1), 1e-6)
        else:
            league = BOOTSTRAP_LEAGUE_MEAN
            sw2 = BOOTSTRAP_SIGMA_W ** 2

        rep = (self.rep_s / self.rep_n) if self.rep_n >= MIN_REP_DB \
            else BOOTSTRAP_REPLACEMENT
        if rep >= league:
            # structurally impossible in a mature pool; only happens mid burn-in
            thin = True

        # between-QB variance by method of moments over established arms:
        # var(observed means) minus the mean sampling variance of those means.
        ns = np.array([self.cn[q] for q in self.cn
                       if self.cn[q] >= MIN_DB_FOR_SIGMA_B], dtype=float)
        if ns.size >= 12:
            ms = np.array([self.cs[q] / self.cn[q] for q in self.cn
                           if self.cn[q] >= MIN_DB_FOR_SIGMA_B], dtype=float)
            sb2 = float(np.var(ms, ddof=1) - np.mean(sw2 / ns))
            sb2 = max(sb2, sw2 / K_CEIL)
            k = float(np.clip(sw2 / sb2, K_FLOOR, K_CEIL))
        else:
            k = BOOTSTRAP_K
            thin = True

        self._cache = (league, rep, k, thin)
        return self._cache

    def quality(self, qb, league, rep, k):
        """
        Shrunk EPA/dropback for one quarterback, as of now.

        Returns (blend, career_only, recent_only, career_dropbacks). A QB with
        no prior dropbacks -- or a null id -- lands exactly on `rep`, which is
        the replacement prior, not NaN and not zero.
        """
        n_c = self.cn.get(qb, 0) if qb is not None else 0
        if n_c == 0:
            return rep, rep, rep, 0
        s_c = self.cs[qb]
        n_r, s_r = self.rn.get(qb, 0), self.rs.get(qb, 0.0)

        n_eff = n_r + LAMBDA_OLD * (n_c - n_r)
        s_eff = s_r + LAMBDA_OLD * (s_c - s_r)

        blend = (s_eff + k * rep) / (n_eff + k)
        career = (s_c + k * rep) / (n_c + k)
        recent = (s_r + k * rep) / (n_r + k) if n_r else rep
        return blend, career, recent, n_c


# =========================================================================
# build
# =========================================================================
def build(games_df, pbp_df):
    """
    Build the PERSONNEL (P) vector, one row per game_id.

    games_df  a frame from load.load_games(). Pass the WIDEST window you have,
              not just the rows you intend to fit: starter identity history and
              the "did the starter change" flag are built from this frame, so a
              narrow frame starves its own early weeks. Filter the OUTPUT to the
              fit rows instead. Unplayed rows (e.g. the live 2026 slate) are fine
              and are exactly how this serves a live week -- they contribute no
              plays, only target rows.
    pbp_df    a frame from load.load_pbp(seasons, columns=PBP_COLUMNS). Include
              the postseason: playoff snaps are prior experience. It must NOT
              contain the outcome columns; build() raises if it does.

    Returns a DataFrame keyed by game_id (unique), safe to merge on game_id.
    The headline feature is `p_qb` (== qb_delta_diff), home minus away, in units
    of EPA per dropback above replacement.
    """
    g = games_df.copy()
    if "time_index" not in g.columns:
        g["time_index"] = time_index(g)
    g = g.sort_values(["time_index", "game_id"]).reset_index(drop=True)

    qg = qb_game_table(pbp_df)
    by_week = {t: sub for t, sub in qg.groupby("time_index", sort=True)}

    pool = _QBPool()
    last_starter = {}          # team -> qb_id of its most recent PRIOR game
    z_n, z_s, z_ss = 0, 0.0, 0.0
    rows = []

    for t, week in g.groupby("time_index", sort=True):
        league, rep, k, thin = pool.constants()
        z_mu = (z_s / z_n) if z_n >= MIN_Z_GAMES else 0.0
        z_sd = None
        if z_n >= MIN_Z_GAMES:
            v = (z_ss - z_s ** 2 / z_n) / max(z_n - 1, 1)
            if v > 1e-12:
                z_sd = float(np.sqrt(v))

        pending_z, pending_starters = [], []

        for _, row in week.iterrows():
            out = {"game_id": row["game_id"],
                   "season": int(row["season"]),
                   "week": int(row["week"]),
                   "time_index": int(t),
                   "home_team": row.get("home_team"),
                   "away_team": row.get("away_team"),
                   "home_qb_id": row.get("home_qb_id"),
                   "away_qb_id": row.get("away_qb_id"),
                   "qb_league_mean": league,
                   "qb_replacement_level": rep,
                   "qb_shrink_k": k,
                   "qb_history_thin": int(thin)}

            for side in ("home", "away"):
                team = row.get("%s_team" % side)
                qb = row.get("%s_qb_id" % side)
                if isinstance(qb, float) and np.isnan(qb):
                    qb = None
                if qb is not None and pd.isna(qb):
                    qb = None

                blend, career, recent, n_c = pool.quality(qb, league, rep, k)
                out["qb_quality_%s" % side] = blend
                out["qb_quality_career_%s" % side] = career
                out["qb_quality_recent_%s" % side] = recent
                out["qb_prior_db_%s" % side] = n_c
                out["qb_delta_%s" % side] = blend - rep
                out["qb_delta_career_%s" % side] = career - rep
                out["qb_delta_recent_%s" % side] = recent - rep
                out["qb_fallback_%s" % side] = int(n_c == 0)
                out["qb_id_missing_%s" % side] = int(qb is None)

                prev = last_starter.get(team)
                out["qb_prior_starter_known_%s" % side] = int(prev is not None)
                if prev is None or qb is None:
                    out["qb_new_starter_%s" % side] = 0
                    out["qb_change_delta_%s" % side] = 0.0
                else:
                    out["qb_new_starter_%s" % side] = int(prev != qb)
                    pb, _, _, _ = pool.quality(prev, league, rep, k)
                    out["qb_change_delta_%s" % side] = blend - pb

                if team is not None and qb is not None:
                    pending_starters.append((team, qb))

            for base in ("qb_delta", "qb_delta_career", "qb_delta_recent",
                         "qb_new_starter", "qb_change_delta"):
                out["%s_diff" % base] = (out["%s_home" % base]
                                         - out["%s_away" % base])

            p = out["qb_delta_diff"]
            out["p_qb"] = p
            out["p_qb_z"] = ((p - z_mu) / z_sd) if z_sd else np.nan
            pending_z.append(p)
            rows.append(out)

        # ---- only NOW does this week's information enter the state ----
        for v in pending_z:
            z_n += 1
            z_s += v
            z_ss += v * v
        for team, qb in pending_starters:
            last_starter[team] = qb
        if t in by_week:
            sub = by_week[t]
            for qb, n, s, ss in zip(sub["qb"], sub["n"], sub["s"], sub["ss"]):
                pool.add(qb, int(n), float(s), float(ss))

    out = pd.DataFrame(rows)
    if out["game_id"].duplicated().any():
        raise ValueError("game_id is not unique in the output -- refusing to "
                         "return a frame that cannot be merged safely")
    return out.sort_values(["time_index", "game_id"]).reset_index(drop=True)


# =========================================================================
# self-test / sanity stats
# =========================================================================
def _pct(x):
    return "%.1f%%" % (100.0 * x)


def _main():
    print("=" * 74)
    print("PERSONNEL (P) -- build + sanity")
    print("=" * 74)

    games = load_games(seasons=(2018, 2025), played_only=True)
    pbp = load_pbp((2018, 2025), columns=PBP_COLUMNS)
    print("games in: %d   pbp rows in: %d" % (len(games), len(pbp)))

    qg = qb_game_table(pbp)
    print("qb-games: %d   dropbacks: %d   distinct QBs: %d"
          % (len(qg), int(qg["n"].sum()), qg["qb"].nunique()))

    P = build(games, pbp)
    print("built: %d rows x %d cols" % P.shape)

    fit = load_games(seasons=(2018, 2025), require_lines=True, played_only=True)
    m = P.merge(fit[["game_id", "spread_line", "result", "home_score",
                     "away_score", "home_moneyline", "away_moneyline"]],
                on="game_id", how="inner")
    print("merged onto the %d-row fittable set: %d rows" % (len(fit), len(m)))

    # ---- replacement-prior fallback: the number the brief asks for -------
    print("\n--- replacement-prior fallback -------------------------------")
    for label, frame in (("all games", P), ("fittable set", m)):
        fb = ((frame["qb_fallback_home"] == 1) |
              (frame["qb_fallback_away"] == 1)).mean()
        sides = pd.concat([frame["qb_fallback_home"],
                           frame["qb_fallback_away"]]).mean()
        miss = pd.concat([frame["qb_id_missing_home"],
                          frame["qb_id_missing_away"]]).mean()
        print("  %-14s  starters on the replacement prior: %s of sides, "
              "%s of games have >=1" % (label, _pct(sides), _pct(fb)))
        print("  %-14s  of which a MISSING qb id: %s of sides"
              % ("", _pct(miss)))
    burn = P["qb_history_thin"].mean()
    print("  burn-in rows (qb_history_thin=1): %s -- drop season %d from the fit"
          % (_pct(burn), int(P["season"].min())))
    print("  fallback by season:")
    bys = P.groupby("season").apply(
        lambda d: pd.Series({
            "games": len(d),
            "side_fallback": pd.concat([d.qb_fallback_home,
                                        d.qb_fallback_away]).mean(),
            "thin": d.qb_history_thin.mean()}), include_groups=False)
    for s, r in bys.iterrows():
        print("    %d  games %3d   fallback %-6s  thin %s"
              % (s, r["games"], _pct(r["side_fallback"]), _pct(r["thin"])))

    # ---- as-of constants -------------------------------------------------
    print("\n--- as-of constants (should drift, never jump) ---------------")
    c = P.groupby("season")[["qb_league_mean", "qb_replacement_level",
                             "qb_shrink_k"]].last()
    for s, r in c.iterrows():
        print("    %d  league %+.4f  replacement %+.4f  k %6.1f db (~%.1f starts)"
              % (s, r.qb_league_mean, r.qb_replacement_level,
                 r.qb_shrink_k, r.qb_shrink_k / 34.0))

    # ---- distributions ---------------------------------------------------
    print("\n--- distributions (EPA per dropback above replacement) -------")
    for col in ["qb_delta_home", "qb_delta_away", "qb_delta_diff",
                "qb_delta_career_diff", "qb_delta_recent_diff",
                "qb_change_delta_diff"]:
        v = P[col].astype(float)
        print("    %-24s mean %+.4f  sd %.4f  min %+.4f  max %+.4f  nan %d"
              % (col, v.mean(), v.std(), v.min(), v.max(), v.isna().sum()))
    print("    %-24s nan %d (by design: first %d games have no prior sample)"
          % ("p_qb_z", P["p_qb_z"].isna().sum(), MIN_Z_GAMES))

    # ---- starter-change signal -------------------------------------------
    print("\n--- starter change -------------------------------------------")
    ns = pd.concat([P["qb_new_starter_home"], P["qb_new_starter_away"]])
    print("    team-games with a different starter than last game: %s"
          % _pct(ns.mean()))
    chg = P[(P.qb_new_starter_home == 1) | (P.qb_new_starter_away == 1)]
    print("    games with >=1 starter change: %d (%s)"
          % (len(chg), _pct(len(chg) / len(P))))
    d = pd.concat([P.loc[P.qb_new_starter_home == 1, "qb_change_delta_home"],
                   P.loc[P.qb_new_starter_away == 1, "qb_change_delta_away"]])
    print("    on a change, quality vs the replaced starter: mean %+.4f  sd %.4f"
          % (d.mean(), d.std()))

    # ---- face validity ---------------------------------------------------
    print("\n--- face validity: end-state quality, most-used starters ------")
    side = pd.concat([
        P[["home_qb_id", "qb_quality_home", "qb_prior_db_home"]]
        .rename(columns={"home_qb_id": "qb", "qb_quality_home": "q",
                         "qb_prior_db_home": "n"}),
        P[["away_qb_id", "qb_quality_away", "qb_prior_db_away"]]
        .rename(columns={"away_qb_id": "qb", "qb_quality_away": "q",
                         "qb_prior_db_away": "n"})])
    last_q = (side.dropna(subset=["qb"]).sort_values("n")
              .groupby("qb").tail(1))
    last_q = last_q[last_q["n"] >= 1500].sort_values("q")
    names = {}
    try:
        gg = load_games(seasons=(2018, 2025), played_only=True)
        for a, b in [("home_qb_id", "home_qb_name"), ("away_qb_id", "away_qb_name")]:
            names.update(dict(zip(gg[a], gg[b])))
    except Exception:
        pass
    print("    top 8:")
    for _, r in last_q.tail(8)[::-1].iterrows():
        print("      %-22s %+.4f  (%d db)"
              % (names.get(r.qb, r.qb), r.q, int(r.n)))
    print("    bottom 5:")
    for _, r in last_q.head(5).iterrows():
        print("      %-22s %+.4f  (%d db)"
              % (names.get(r.qb, r.qb), r.q, int(r.n)))

    # ---- the honest test: how much does the market already know? ---------
    print("\n--- how much of P does the market already price? -------------")
    mm = m.dropna(subset=["spread_line", "result"]).copy()
    mm["home_win"] = (mm["result"] > 0).astype(float)
    mm = mm[mm["result"] != 0]
    print("    corr(p_qb, spread_line)  = %+.3f   <- the market's own view"
          % mm["p_qb"].corr(mm["spread_line"]))
    print("    corr(p_qb, result)       = %+.3f" % mm["p_qb"].corr(mm["result"]))
    resid = mm["result"] - mm["spread_line"]
    r_ats = mm["p_qb"].corr(resid)
    print("    corr(p_qb, result - spread_line) = %+.3f  <- what is LEFT after"
          % r_ats)
    print("       the close. This is the number B_P will be fitted on. If it is")
    print("       near zero, the market has already absorbed P and B_P ~ 0 is")
    print("       the CORRECT answer, not a bug.")
    n = len(mm)
    se = 1.0 / np.sqrt(max(n - 3, 1))
    zf = 0.5 * np.log((1 + r_ats) / (1 - r_ats))
    print("    n=%d  Fisher-z 95%% CI on that residual corr: [%+.3f, %+.3f]"
          % (n, np.tanh(zf - 1.96 * se), np.tanh(zf + 1.96 * se)))

    # ---- leakage guards --------------------------------------------------
    print("\n--- leakage guards -------------------------------------------")
    banned = [c for c in LEAKY_PBP_COLUMNS if c in P.columns]
    print("    outcome columns in output: %s" % (banned or "none"))
    w1 = P[(P.season == P.season.min()) & (P.week == 1)]
    z = (w1["qb_delta_home"].abs().max(), w1["qb_delta_away"].abs().max())
    print("    first cached week (%d w1, %d games): max |qb_delta| = %.4f/%.4f"
          % (P.season.min(), len(w1), z[0], z[1]))
    print("      (zero on both sides is the proof that week 1 of the first")
    print("       cached season sees no prior plays at all)")
    try:
        assert max(z) == 0.0
        print("    PASS: no prior-play information exists before the cache starts")
    except AssertionError:
        print("    FAIL: week 1 of the first season saw prior plays")

    # a starter's own game must not move their own number
    print("    prior-dropback counts are strictly non-decreasing per QB "
          "across time: %s" % _monotone_check(P))
    print("    every qb_prior_db equals that QB's dropbacks at time_index < "
          "the game's: %s" % _asof_check(P, qg))

    # ---- the live-serving path -------------------------------------------
    print("\n--- live slate (the same call, on unplayed rows) --------------")
    try:
        wide = load_games(seasons=(2018, 2026), played_only=False)
        LP = build(wide, pbp)
        live = LP[LP.season == 2026]
        print("    build() on games 2018-2026 (played_only=False): %d rows"
              % len(LP))
        print("    2026 rows produced: %d   with a known starter both sides: %d"
              % (len(live),
                 int(((live.qb_id_missing_home == 0) &
                      (live.qb_id_missing_away == 0)).sum())))
        print("    2026 rows on the replacement prior (no starter named yet): %s"
              % _pct(pd.concat([live.qb_id_missing_home,
                                live.qb_id_missing_away]).mean()))
        print("    p_qb on 2026: mean %+.4f  sd %.4f  nan %d"
              % (live.p_qb.mean(), live.p_qb.std(), live.p_qb.isna().sum()))
        same = LP[LP.season <= 2025].merge(
            P[["game_id", "p_qb"]], on="game_id", suffixes=("", "_narrow"))
        drift = (same.p_qb - same.p_qb_narrow).abs().max()
        print("    widening games_df changed no historical p_qb: max drift %.2e"
              % drift)
        print("    NOTE: play_by_play_2026.parquet is NOT cached, so 2026 QB")
        print("      quality is frozen at the end of 2025. Run")
        print("      fetch.py --seasons 2026 to make the live week self-updating.")
    except Exception as e:
        print("    skipped: %s" % e)

    print("\nwrote nothing. build(games_df, pbp_df) is the only entry point.")


def _asof_check(P, qg):
    """
    The hard one. For every emitted side, recompute that quarterback's prior
    dropbacks independently -- sum of his dropbacks over every game with a
    STRICTLY smaller time_index -- and demand an exact match. Any look-ahead of
    even one week, and any failure to exclude the target game itself, shows up
    here as a mismatch.
    """
    cum = (qg.groupby(["qb", "time_index"], as_index=False)["n"].sum()
             .sort_values(["qb", "time_index"]))
    cum["prior"] = cum.groupby("qb")["n"].cumsum() - cum["n"]
    truth = {(q, t): int(v) for q, t, v in
             zip(cum["qb"], cum["time_index"], cum["prior"])}
    totals = cum.groupby("qb")["n"].sum().to_dict()
    firsts = cum.groupby("qb")["time_index"].min().to_dict()
    lasts = cum.groupby("qb").apply(
        lambda d: int(d["n"].sum()), include_groups=False).to_dict()

    bad = 0
    checked = 0
    for side in ("home", "away"):
        idc, dbc = "%s_qb_id" % side, "qb_prior_db_%s" % side
        for qb, t, got in zip(P[idc], P["time_index"], P[dbc]):
            if qb is None or pd.isna(qb):
                continue
            checked += 1
            if (qb, t) in truth:
                want = truth[(qb, t)]
            elif qb not in firsts:
                want = 0
            elif t < firsts[qb]:
                want = 0
            else:
                # QB did not play in this week; prior = everything before it
                sub = cum[(cum["qb"] == qb) & (cum["time_index"] < t)]
                want = int(sub["n"].sum())
            if int(got) != want:
                bad += 1
    return "PASS (%d sides checked)" % checked if bad == 0 \
        else "FAIL (%d/%d mismatched)" % (bad, checked)


def _monotone_check(P):
    for side in ("home", "away"):
        s = P[["time_index", "%s_qb_id" % side, "qb_prior_db_%s" % side]].dropna()
        s = s.sort_values("time_index")
        bad = (s.groupby("%s_qb_id" % side)["qb_prior_db_%s" % side]
               .apply(lambda v: (v.diff().dropna() < 0).any()))
        if bad.any():
            return "FAIL (%s)" % side
    return "PASS"


if __name__ == "__main__":
    _main()
