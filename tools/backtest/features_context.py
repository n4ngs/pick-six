#!/usr/bin/env python3
"""
features_context.py -- VAS Vector 3: Context (C) and Regime (R).

OFFLINE BACKTEST ONLY. Nothing here ships. It writes no files and reads only the
nflverse cache via load.py.

    from features_context import build
    feats = build(games_df, pbp_df)     # one row per game_id

--------------------------------------------------------------------------------
WHAT C IS
--------------------------------------------------------------------------------
VAS.md:  C = a1*z(restDiff) + a2*shortWeek + a3*byeReturn - a4*z(travelMiles)
             - a5*tzPenalty

Every component here is expressed **home-positive**: a positive value means the
context favours the HOME team, which is the side whose win probability is being
fitted (offset = logit(p_mkt_home)). VAS.md's minus signs on travel and tz are
folded into the differencing -- `travel_diff = away_miles - home_miles`, so a
long away trip is a positive number, and the coefficient stays positive.

`C` is emitted as a single as-of-standardised composite with unit weights on
unit-scale pieces, because the regression has exactly one `B_C` to give it. The
five components are ALSO emitted individually (`c_rest_diff_z`, `c_short_week`,
`c_bye_return`, `c_travel_diff_z`, `c_tz_pen_diff`) so the fit can re-weight
them instead, and can measure how much of the composite is just rest. They are
collinear by construction -- rest_diff already contains most of the short-week
and bye-return signal; the printout shows the correlation matrix so that is
visible rather than hidden.

--------------------------------------------------------------------------------
WHAT R IS, AND THE HONEST CAVEAT FOR A MONEYLINE FIT
--------------------------------------------------------------------------------
VAS.md defines R as `+1 bet type matches regime, -1 opposed, 0 orthogonal`. That
mapping is written for a TOTAL: GRIND matches an under, CHAOS matches an over.

**For a straight home-win bet there is no such mapping, and pretending there is
would be inventing a relationship.** Pace and pass rate do not tell you who wins.
Said plainly: on the moneyline, the VAS.md formulation of R is undefined, and the
correct default expectation for B_R on this fit is ZERO.

There is exactly one mechanism by which regime can touch a win probability, and
it is not about scoring, it is about sample size. A football game is a sequence of
possessions. Fewer possessions means the stronger team gets fewer draws from its
own edge, so the margin distribution widens relative to its mean and the
underdog's win probability rises. More possessions means the favourite converts
its edge more reliably. That is a variance claim, not a scoring claim, and it is
a real one.

So R is emitted as that interaction, signed toward the home team:

    regime_score = P(CHAOS) - P(GRIND)        in [-1, +1], + = more possessions
    fav          = tanh(spread_line / 7)      in (-1, +1), + = home favoured
    R = r_ml     = regime_score * fav

    home favourite + CHAOS  -> R > 0  (favourite converts)
    home favourite + GRIND  -> R < 0  (grind protects the dog)
    home underdog  + GRIND  -> R > 0  (home dog benefits)
    home underdog  + CHAOS  -> R < 0

If B_R comes back indistinguishable from zero, that is the expected result and the
vector should be DELETED per VAS.md's own rule, not rescued. `r_regime_score` is
also emitted raw so the same classifier can be reused unchanged when the harness
later fits totals, where VAS.md's +1/-1 mapping does apply.

Note that `fav` is built from the closing spread, so R is market-conditioned by
construction. That is deliberate: it makes B_R a statement about the market
mispricing possession count for favourites, and it is not look-ahead, because the
closing line is precisely the anchor point the model is priced from.

--------------------------------------------------------------------------------
THE CARDINAL RULE -- WHAT IS AND IS NOT KNOWN PREGAME
--------------------------------------------------------------------------------
Computed strictly as-of (only rows with time_index STRICTLY LESS than the target
game's, and never the target game_id itself):

  * team pace (scrimmage plays/game) and PROE, empirical-Bayes shrunk, with the
    shrinkage constant k = sigma_within^2 / sigma_between^2 itself re-estimated
    as-of at every (season, week);
  * the league mean and between-team spread used to standardise them;
  * the mean/SD used to standardise rest, travel and the C composite;
  * missing outdoor temp/wind imputation (venue-month -> month -> global);
  * each team's acclimatised temperature for `c_temp_shock`.

Known pregame from the published schedule, and therefore used directly:

  * away_rest / home_rest, div_game, weekday, gametime, stadium_id, location;
  * each team's home venue for the season (the schedule is published in May, so
    which building a team calls home is not a future fact).

DECLARED RESIDUAL RISKS -- read before trusting a coefficient:

  1. `temp` / `wind` in games.csv are game-time observations, not the FORECAST
     that was actually available when the line closed. The market prices the
     forecast. The gap is forecast error, which is small for wind at 24h but not
     zero. Anything fitted on `c_wind_z` or `c_temp_shock` carries that asterisk.
  2. `roof` for a retractable stadium (open vs closed) is a game-day decision. It
     is normally announced ~90 minutes out, i.e. around the close, so it is
     treated as known. 358 games 2018-2025 are retractable.
  3. games.csv has NO gust column. VAS.md says "gusts >= 20mph force GRIND"; this
     module forces on sustained wind instead and the threshold is documented
     below. It is not the same variable.
  4. pbp is cached from 2018 only, so 2018 weeks 1-4 have thin or no prior pace
     history. Those rows get a league-neutral regime and `r_ok == False`. They are
     NOT dropped -- the fit should either exclude them or trust `r_ok`.

--------------------------------------------------------------------------------
GEO
--------------------------------------------------------------------------------
data/geo.json was read. It is the live app's weather lookup: 18 entries keyed by
CITY STRING ("Chicago, IL"), with no timezone and no stadium key, and games.csv
has no city column to join on. It covers neither the 40+ venues in the fitting
window nor any timezone, so it cannot carry C. STADIUMS below is a static table
written into this module instead, keyed by nflverse `stadium_id`, covering all 67
venues 1999-2026 (including London, Munich, Frankfurt, Mexico City, Sao Paulo,
Rio, Madrid, Melbourne and every relocated/temporary US site). Where a venue's
city appears in geo.json, build() cross-checks the coordinates and prints any
disagreement over 25 miles.
"""

import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
GEO_JSON = os.path.join(REPO, "data", "geo.json")

# Columns that nflfastR stamps on EVERY play row with the GAME'S FINAL OUTCOME or
# the closing line. They are constant across all ~150 plays of a game, so any
# aggregate built over pbp that does not exclude them leaks the answer. Dropped
# from the working frame on entry, unconditionally.
PBP_FORBIDDEN = [
    "result", "total", "home_score", "away_score", "spread_line", "total_line",
    "vegas_wp", "vegas_home_wp", "vegas_wpa", "vegas_home_wpa",
]

# stadium_id -> (lat, lon, utc_standard_offset_hours, label)
# Offsets are STANDARD (non-DST). US DST is uniform across the four continental
# zones, so differences between US venues are exact year-round; Arizona (PHO00,
# PHO99) does not observe DST, which makes it ~1h off relative to Denver during
# September and October only. Foreign venues use their own standard offset.
STADIUMS = {
    "ATL00": (33.7576, -84.4009, -5.0, "Georgia Dome"),
    "ATL97": (33.7554, -84.4008, -5.0, "Mercedes-Benz Stadium"),
    "BAL00": (39.2780, -76.6227, -5.0, "M&T Bank Stadium"),
    "BOS00": (42.0909, -71.2643, -5.0, "Gillette Stadium"),
    "BOS99": (42.0918, -71.2643, -5.0, "Foxboro Stadium"),
    "BRG00": (30.4118, -91.1836, -6.0, "Tiger Stadium (LSU)"),
    "BUF00": (42.7738, -78.7870, -5.0, "Highmark Stadium"),
    "BUF01": (43.6414, -79.3894, -5.0, "Rogers Centre"),
    "CAR00": (35.2258, -80.8528, -5.0, "Bank of America Stadium"),
    "CHI98": (41.8623, -87.6167, -6.0, "Soldier Field"),
    "CHI99": (40.0995, -88.2358, -6.0, "Memorial Stadium (Champaign)"),
    "CIN00": (39.0955, -84.5161, -5.0, "Paycor Stadium"),
    "CIN99": (39.0975, -84.5083, -5.0, "Cinergy Field"),
    "CLE00": (41.5061, -81.6995, -5.0, "Huntington Bank Field"),
    "DAL00": (32.7473, -97.0945, -6.0, "AT&T Stadium"),
    "DAL99": (32.8410, -96.9147, -6.0, "Texas Stadium"),
    "DEN00": (39.7439, -105.0201, -7.0, "Empower Field at Mile High"),
    "DEN99": (39.7466, -105.0217, -7.0, "Mile High Stadium"),
    "DET00": (42.3400, -83.0456, -5.0, "Ford Field"),
    "DET99": (42.6459, -83.2550, -5.0, "Pontiac Silverdome"),
    "FRA00": (50.0686, 8.6455, 1.0, "Deutsche Bank Park"),
    "GER00": (48.2188, 11.6247, 1.0, "Allianz Arena"),
    "GNB00": (44.5013, -88.0622, -6.0, "Lambeau Field"),
    "HOU00": (29.6847, -95.4107, -6.0, "NRG Stadium"),
    "IND00": (39.7601, -86.1639, -5.0, "Lucas Oil Stadium"),
    "IND99": (39.7639, -86.1638, -5.0, "RCA Dome"),
    "JAX00": (30.3239, -81.6373, -5.0, "EverBank Stadium"),
    "KAN00": (39.0489, -94.4839, -6.0, "GEHA Field at Arrowhead"),
    "LAX01": (33.9535, -118.3387, -8.0, "SoFi Stadium"),
    "LAX97": (33.8644, -118.2611, -8.0, "Dignity Health Sports Park"),
    "LAX99": (34.0141, -118.2879, -8.0, "LA Memorial Coliseum"),
    "LON00": (51.5560, -0.2795, 0.0, "Wembley Stadium"),
    "LON01": (51.4560, -0.3417, 0.0, "Twickenham Stadium"),
    "LON02": (51.6043, -0.0665, 0.0, "Tottenham Hotspur Stadium"),
    "MAD01": (40.4531, -3.6883, 1.0, "Santiago Bernabeu"),
    "MEL00": (-37.8200, 144.9834, 10.0, "Melbourne Cricket Ground"),
    "MEX00": (19.3029, -99.1505, -6.0, "Estadio Azteca / Banorte"),
    "MIA00": (25.9580, -80.2389, -5.0, "Hard Rock Stadium"),
    "MIN00": (44.9738, -93.2578, -6.0, "Metrodome"),
    "MIN01": (44.9737, -93.2575, -6.0, "U.S. Bank Stadium"),
    "MIN98": (44.9765, -93.2247, -6.0, "TCF Bank Stadium"),
    "MUN01": (48.2188, 11.6247, 1.0, "Allianz Arena (Munich)"),
    "NAS00": (36.1665, -86.7713, -6.0, "Nissan Stadium"),
    "NOR00": (29.9511, -90.0812, -6.0, "Caesars Superdome"),
    "NYC00": (40.8128, -74.0764, -5.0, "Giants Stadium"),
    "NYC01": (40.8135, -74.0745, -5.0, "MetLife Stadium"),
    "OAK00": (37.7516, -122.2005, -8.0, "Oakland Coliseum"),
    "PAR00": (48.9245, 2.3601, 1.0, "Stade de France"),
    "PHI00": (39.9008, -75.1675, -5.0, "Lincoln Financial Field"),
    "PHI99": (39.9060, -75.1717, -5.0, "Veterans Stadium"),
    "PHO00": (33.5276, -112.2626, -7.0, "State Farm Stadium"),
    "PHO99": (33.4263, -111.9325, -7.0, "Sun Devil Stadium"),
    "PIT00": (40.4468, -80.0158, -5.0, "Acrisure Stadium"),
    "PIT99": (40.4468, -80.0122, -5.0, "Three Rivers Stadium"),
    "RIO00": (-22.9121, -43.2302, -3.0, "Maracana"),
    "SAN00": (29.4169, -98.4791, -6.0, "Alamodome"),
    "SAO00": (-23.5453, -46.4742, -3.0, "Arena Corinthians"),
    "SDG00": (32.7831, -117.1196, -8.0, "Qualcomm Stadium"),
    "SEA00": (47.5952, -122.3316, -8.0, "Lumen Field"),
    "SEA98": (47.5952, -122.3325, -8.0, "Kingdome"),
    "SEA99": (47.6503, -122.3016, -8.0, "Husky Stadium"),
    "SFO00": (37.7136, -122.3862, -8.0, "Candlestick Park"),
    "SFO01": (37.4030, -121.9700, -8.0, "Levi's Stadium"),
    "STL00": (38.6328, -90.1885, -6.0, "Edward Jones Dome"),
    "TAM00": (27.9759, -82.5033, -5.0, "Raymond James Stadium"),
    "VEG00": (36.0909, -115.1833, -8.0, "Allegiant Stadium"),
    "WAS00": (38.9076, -76.8645, -5.0, "Northwest Stadium"),
}

# nflverse PBP normalises relocated franchises to their CURRENT abbreviation on
# every historical row, while games.csv keeps the abbreviation of the day. Joining
# the two without this map silently drops every 2018-2019 Raiders game out of R --
# the hats come back NaN, r_ok goes False, and nothing complains. Both sides are
# normalised before the join, and the join is then asserted to be total.
TEAM_ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "WSH": "WAS"}


def _norm_team(s):
    return pd.Series(s).astype(str).replace(TEAM_ALIASES).to_numpy()


ET_OFFSET = -5.0           # gametime in games.csv is Eastern for every game
INDOOR_ROOFS = ("dome", "closed")
TEMP_INDOOR = 70.0         # neutralised indoor temperature (degF)
WIND_INDOOR = 0.0          # neutralised indoor wind (mph)
TEMP_FALLBACK = 60.0       # used only if there is no prior outdoor history at all
WIND_FALLBACK = 8.0

# regime classifier constants -- see _regime_probs
REGIME_CUT_GRIND = -0.62   # latent cut below which GRIND dominates (~z28)
REGIME_CUT_CHAOS = 0.62    # latent cut above which CHAOS dominates (~z72)
REGIME_TAU = 0.55          # softness; larger = more probability mass in STANDARD
REGIME_INDOOR_BUMP = 0.25  # VAS.md lists "dome or calm" as a CHAOS input
WIND_DRAG_ZERO = 8.0       # mph at which wind starts dragging toward GRIND
WIND_DRAG_SCALE = 10.0     # mph per 1.0 of latent drag
WIND_DRAG_CAP = 2.0
WIND_FORCE_LO = 15.0       # VAS.md: >= 15mph pushes GRIND
WIND_FORCE_HI = 22.0       # >= 22mph sustained collapses the distribution to GRIND
MIN_PRIOR_GAMES_R = 2      # per team, before r_ok
MIN_PRIOR_TEAMGAMES_R = 96 # league-wide, before r_ok
MIN_N_ASOF_Z = 96          # rows of prior history before an as-of z is trusted


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in statute miles. Scalar or numpy arrays."""
    r = 3958.7613
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _gametime_hour_et(s):
    """'13:00' -> 13.0. Blank/NaN -> NaN (caller substitutes 13.0 and flags)."""
    def one(v):
        if not isinstance(v, str) or ":" not in v:
            return np.nan
        try:
            hh, mm = v.split(":")[:2]
            return float(hh) + float(mm) / 60.0
        except (ValueError, TypeError):
            return np.nan
    return s.map(one)


def _circadian_penalty(body_hour):
    """
    Hours by which a team's BODY CLOCK sits outside the 13:00-21:00 window in
    which NFL games are normally played. A Pacific team in a 13:00 ET kick has a
    10:00 body clock -> penalty 3.0, which is VAS.md's "west-coast teams in 1pm
    ET kicks" recovered as a continuous quantity rather than an indicator. A
    09:30 ET London kick penalises BOTH teams, correctly.
    """
    h = np.asarray(body_hour, dtype=float)
    return np.maximum(0.0, 13.0 - h) + np.maximum(0.0, h - 21.0)


def _short_week(rest):
    """1.0 at 4 days rest (Thu after Sun), 0.5 at 5, 0 otherwise."""
    r = np.asarray(rest, dtype=float)
    return np.where(r <= 4, 1.0, np.where(r <= 5, 0.5, 0.0))


def _bye_return(rest):
    """1.0 off a true bye (>=13 days), 0.5 for a long-but-not-bye week."""
    r = np.asarray(rest, dtype=float)
    return np.where(r >= 13, 1.0, np.where(r >= 10, 0.5, 0.0))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def _asof_z(values, tix, min_n=MIN_N_ASOF_Z, sd_floor=1e-9):
    """
    Expanding z-score: each row is standardised against the mean/SD of every row
    with a STRICTLY SMALLER time_index. No row can see its own week, let alone
    its own value. Returns (z, ok) where ok is False when fewer than `min_n`
    prior rows exist (z is then 0.0, i.e. league-neutral, never NaN).
    """
    v = pd.Series(np.asarray(values, dtype=float))
    t = pd.Series(np.asarray(tix))
    ok_val = v.notna()

    idx = pd.Index(sorted(t.unique()))
    grp = v[ok_val].groupby(t[ok_val].values)
    agg = pd.DataFrame({
        "n": grp.size(),
        "s": grp.sum(),
        "ss": grp.apply(lambda x: float((x.astype(float) ** 2).sum())),
    }).reindex(idx).fillna(0.0)

    cn = agg["n"].cumsum().shift(1).fillna(0.0)
    cs = agg["s"].cumsum().shift(1).fillna(0.0)
    css = agg["ss"].cumsum().shift(1).fillna(0.0)

    with np.errstate(invalid="ignore", divide="ignore"):
        mean = cs / cn
        var = (css - cn * mean ** 2) / np.maximum(cn - 1.0, 1.0)
    sd = np.sqrt(np.maximum(var, 0.0))

    m = t.map(pd.Series(mean.values, index=idx)).astype(float)
    d = t.map(pd.Series(sd.values, index=idx)).astype(float)
    n = t.map(pd.Series(cn.values, index=idx)).astype(float)

    ok = ok_val.values & (n.values >= min_n) & (d.values > sd_floor)
    z = np.where(ok, (v.values - m.values) / np.where(d.values > sd_floor, d.values, 1.0), 0.0)
    return z, ok


# ---------------------------------------------------------------------------
# as-of empirical-Bayes team rates from pbp
# ---------------------------------------------------------------------------
def _team_game_frame(pbp):
    """
    pbp -> one row per (game_id, posteam): scrimmage plays run, mean PROE.

    Leaky columns are dropped on entry. `plays` counts play_type in {pass, run};
    if the caller already passed offense_only=True the filter is a no-op. PROE is
    the mean of nflfastR `pass_oe` over those plays (percentage points, team-game
    SD about 7.6) -- 99.6%+ non-null on pass/run rows in every season 2018-2025.
    """
    df = pbp.drop(columns=[c for c in PBP_FORBIDDEN if c in pbp.columns],
                  errors="ignore")
    if "play_type" in df.columns:
        df = df[df["play_type"].isin(["pass", "run"])]
    df = df[df["posteam"].notna()]

    if "time_index" not in df.columns:
        df = df.assign(time_index=df["season"].astype(int) * 100
                       + df["week"].astype(int))

    agg = {"plays": ("posteam", "size"), "time_index": ("time_index", "first")}
    if "pass_oe" in df.columns:
        agg["proe"] = ("pass_oe", "mean")
    tg = df.groupby(["game_id", "posteam"], sort=False).agg(**agg).reset_index()
    if "proe" not in tg.columns:
        tg["proe"] = np.nan
    tg = tg.rename(columns={"posteam": "team"})
    tg["team"] = _norm_team(tg["team"])
    return tg


SEASON_CARRY = 0.35        # weight a prior season keeps when a new one starts


def _asof_eb_rates(tg, cols=("plays", "proe"), season_carry=SEASON_CARRY):
    """
    Empirical-Bayes shrunk team rates, computed as-of, one pass in time order.

        theta_hat = (n*theta_obs + k*theta_league) / (n + k)
        k         = sigma_within^2 / sigma_between^2          (VAS.md)

    Both variances AND the league mean are re-estimated at every distinct
    time_index from team-games that are STRICTLY EARLIER. A team plays at most
    once per week, so "earlier time_index" and "earlier game" coincide; the
    target game is therefore excluded automatically and the target WEEK is
    excluded too, which is conservative in the right direction.

    k is in units of GAMES (the observation unit), not drives, so it is not
    directly comparable to VAS.md's k=33 drives for points-per-drive.

    ACROSS SEASONS the accumulated state is discounted by `season_carry` at each
    season boundary (scaling [n, sum, sumsq] together leaves the mean and the
    variance untouched and only cuts the effective sample size). Rosters and
    coordinators turn over, so last year's pace is evidence but weak evidence.
    At 0.35 a full 17-game season carries in as ~6 games, which is about an
    eighth of k for pace: a Week 1 team is therefore still mostly the league
    prior, matching VAS.md's "Week 2 sits ~80% on the league prior", while Week 1
    is not thrown away entirely. Set season_carry=0.0 for a hard seasonal reset.

    Returns (tg_with_hats, per_time_index_diagnostics).
    """
    tg = tg.sort_values(["time_index", "game_id", "team"]).reset_index(drop=True)
    cols = [c for c in cols if c in tg.columns]

    state = {c: {} for c in cols}            # team -> [n, sum, sumsq]
    hats = {c: np.full(len(tg), np.nan) for c in cols}
    prior_n = np.zeros(len(tg))
    diag_rows = []

    cur_season = None
    for tix, block in tg.groupby("time_index", sort=True):
        rows = block.index.to_numpy()
        diag = {"time_index": int(tix)}

        season = int(tix) // 100
        if cur_season is not None and season != cur_season:
            for c in cols:
                for team, acc in state[c].items():
                    state[c][team] = [acc[0] * season_carry,
                                      acc[1] * season_carry,
                                      acc[2] * season_carry]
        cur_season = season

        for c in cols:
            st = state[c]
            teams = list(st.keys())
            n_i = np.array([st[t][0] for t in teams], dtype=float)
            s_i = np.array([st[t][1] for t in teams], dtype=float)
            ss_i = np.array([st[t][2] for t in teams], dtype=float)

            tot_n = float(n_i.sum()) if len(teams) else 0.0
            league = float(s_i.sum() / tot_n) if tot_n > 0 else np.nan

            k = np.nan
            sw2 = sb2 = np.nan
            multi = n_i >= 2
            if tot_n > 0 and multi.sum() >= 8:
                mean_i = s_i / np.maximum(n_i, 1.0)
                var_i = (ss_i - n_i * mean_i ** 2) / np.maximum(n_i - 1.0, 1.0)
                sw2 = float(np.sum((n_i[multi] - 1.0) * var_i[multi])
                            / np.sum(n_i[multi] - 1.0))
                sb2 = float(np.var(mean_i[multi], ddof=1)
                            - sw2 * float(np.mean(1.0 / n_i[multi])))
                if sb2 > 1e-9 and sw2 > 0:
                    k = float(np.clip(sw2 / sb2, 1.0, 200.0))
            if not np.isfinite(k):
                k = 200.0                     # no spread measurable yet -> shrink hard

            for i in rows:
                team = tg.at[i, "team"]
                n, s, _ = st.get(team, (0.0, 0.0, 0.0))
                if not np.isfinite(league):
                    continue
                hats[c][i] = (s + k * league) / (n + k)
                if c == cols[0]:
                    prior_n[i] = n

            diag["%s_league" % c] = league
            diag["%s_sw2" % c] = sw2
            diag["%s_sb2" % c] = sb2
            diag["%s_k" % c] = k
            diag["%s_n_prior" % c] = tot_n

        diag_rows.append(diag)

        # only now does this week enter the state
        for c in cols:
            st = state[c]
            for i in rows:
                v = tg.at[i, c]
                if pd.isna(v):
                    continue
                team = tg.at[i, "team"]
                cur = st.get(team, [0.0, 0.0, 0.0])
                st[team] = [cur[0] + 1.0, cur[1] + float(v),
                            cur[2] + float(v) ** 2]

    out = tg.copy()
    for c in cols:
        out["%s_hat" % c] = hats[c]
    out["prior_games"] = prior_n
    return out, pd.DataFrame(diag_rows)


# ---------------------------------------------------------------------------
# weather neutralisation + as-of imputation
# ---------------------------------------------------------------------------
def _neutralise_weather(g):
    """
    roof dome/closed  -> temp 70F, wind 0mph, indoor=1. NOT NaN and NOT 0degF:
                         treating a dome's missing temp as missing-at-random
                         silently drops every dome game out of the classifier,
                         and treating it as 0 freezes the Superdome.
    roof outdoors/open-> observed value; if missing, imputed AS-OF from prior
                         games at (stadium_id, month) -> (month) -> global,
                         outdoor games only. `open` is weather-exposed but is
                         0% populated in nflverse, so it is always imputed.

    Returns a frame with temp_n, wind_n, indoor, weather_imputed.
    """
    g = g.sort_values(["time_index", "game_id"]).reset_index(drop=True)
    roof = g["roof"].fillna("outdoors").astype(str).str.lower()
    indoor = roof.isin(INDOOR_ROOFS).to_numpy()
    month = pd.to_datetime(g["gameday"], errors="coerce").dt.month.fillna(9).astype(int).to_numpy()
    sid = g["stadium_id"].fillna("???").astype(str).to_numpy()
    temp = pd.to_numeric(g.get("temp"), errors="coerce").to_numpy(dtype=float)
    wind = pd.to_numeric(g.get("wind"), errors="coerce").to_numpy(dtype=float)
    tix = g["time_index"].to_numpy()

    n = len(g)
    temp_n = np.empty(n); wind_n = np.empty(n)
    imputed = np.zeros(n, dtype=bool)

    sm = {}; mo = {}; gl = [0.0, 0.0, 0.0]   # [n, sum_temp, sum_wind]
    pending = []

    def _mean(acc, j):
        return acc[j] / acc[0] if acc[0] > 0 else np.nan

    order = np.argsort(tix, kind="stable")
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and tix[order[j]] == tix[order[i]]:
            j += 1
        week_rows = order[i:j]

        for r in week_rows:
            if indoor[r]:
                temp_n[r], wind_n[r] = TEMP_INDOOR, WIND_INDOOR
                continue
            t, w = temp[r], wind[r]
            if not np.isfinite(t) or not np.isfinite(w):
                imputed[r] = True
                for acc in (sm.get((sid[r], month[r])), mo.get(month[r]), gl):
                    if acc is None or acc[0] < 5:
                        continue
                    if not np.isfinite(t):
                        t = _mean(acc, 1)
                    if not np.isfinite(w):
                        w = _mean(acc, 2)
                    if np.isfinite(t) and np.isfinite(w):
                        break
                if not np.isfinite(t):
                    t = TEMP_FALLBACK
                if not np.isfinite(w):
                    w = WIND_FALLBACK
            temp_n[r], wind_n[r] = t, w

        for r in week_rows:                  # week enters history only afterwards
            if indoor[r] or not (np.isfinite(temp[r]) and np.isfinite(wind[r])):
                continue
            for key, d in (((sid[r], month[r]), sm), (month[r], mo)):
                acc = d.setdefault(key, [0.0, 0.0, 0.0])
                acc[0] += 1; acc[1] += temp[r]; acc[2] += wind[r]
            gl[0] += 1; gl[1] += temp[r]; gl[2] += wind[r]
        i = j

    g = g.copy()
    g["indoor"] = indoor.astype(int)
    g["temp_n"] = temp_n
    g["wind_n"] = wind_n
    g["weather_imputed"] = imputed.astype(int)
    return g


def _asof_team_climate(g):
    """
    Each team's acclimatised temperature: the running mean of the neutralised
    temperature of its OWN HOME games, strictly before the current week. A
    dome team accumulates 70F, which is the right answer for "what this roster
    is used to playing in". Returns dict-of-arrays aligned to g's row order.
    """
    g = g.sort_values(["time_index", "game_id"]).reset_index(drop=True)
    acc = {}
    home_clim = np.full(len(g), np.nan)
    away_clim = np.full(len(g), np.nan)
    for _, block in g.groupby("time_index", sort=True):
        rows = block.index.to_numpy()
        for r in rows:
            for side, out in (("home_team", home_clim), ("away_team", away_clim)):
                a = acc.get(g.at[r, side])
                out[r] = (a[1] / a[0]) if a and a[0] > 0 else np.nan
        for r in rows:
            ht = g.at[r, "home_team"]
            a = acc.setdefault(ht, [0.0, 0.0])
            a[0] += 1.0; a[1] += float(g.at[r, "temp_n"])
    return home_clim, away_clim


# ---------------------------------------------------------------------------
# regime classifier
# ---------------------------------------------------------------------------
def _regime_probs(latent, wind_mph):
    """
    A PROBABILITY over GRIND / STANDARD / CHAOS, never a hard label, so a
    borderline game contributes a small R instead of flipping discontinuously
    (VAS.md is explicit about this).

    Structure is an ordered logit on one latent `s`:

        P(GRIND)    = sigmoid((c_grind - s) / tau)
        P(!CHAOS)   = sigmoid((c_chaos - s) / tau)
        P(STANDARD) = P(!CHAOS) - P(GRIND)
        P(CHAOS)    = 1 - P(!CHAOS)

    `s` rises with as-of pace and as-of pass-rate-over-expected and falls with
    wind. Wind enters twice, matching VAS.md's two statements:
      * a smooth DRAG from 8mph up, so a breezy day leans GRIND;
      * a hard FORCE ramp from 15mph to 22mph sustained, which blends the entire
        distribution toward a GRIND point mass. VAS.md says gusts >= 20mph force
        it; games.csv has no gust column, so sustained wind stands in and the
        substitution is declared rather than buried.
    """
    s = np.asarray(latent, dtype=float).copy()
    w = np.asarray(wind_mph, dtype=float)

    drag = np.clip((w - WIND_DRAG_ZERO) / WIND_DRAG_SCALE, 0.0, WIND_DRAG_CAP)
    s = s - 1.2 * drag

    p_grind = _sigmoid((REGIME_CUT_GRIND - s) / REGIME_TAU)
    p_not_chaos = _sigmoid((REGIME_CUT_CHAOS - s) / REGIME_TAU)
    p_chaos = 1.0 - p_not_chaos
    p_std = np.clip(p_not_chaos - p_grind, 0.0, 1.0)

    force = np.clip((w - WIND_FORCE_LO) / (WIND_FORCE_HI - WIND_FORCE_LO), 0.0, 1.0)
    p_grind = force + (1.0 - force) * p_grind
    p_std = (1.0 - force) * p_std
    p_chaos = (1.0 - force) * p_chaos

    tot = p_grind + p_std + p_chaos
    return p_grind / tot, p_std / tot, p_chaos / tot


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build(games_df, pbp_df=None, verbose=False):
    """
    Build the Context (C) and Regime (R) vectors.

    games_df  nflverse games.csv as returned by load.load_games(). Needs
              game_id, season, week, home_team, away_team, home_rest, away_rest,
              div_game, roof, surface, temp, wind, gameday, gametime, location,
              stadium_id, spread_line. Pass a WIDER season range than you intend
              to fit (e.g. 2015-2025) to warm up the as-of standardisers; only
              the seasons you then join on are used.
    pbp_df    nflfastR play-by-play from load.load_pbp() with at least
              game_id, season, week, posteam, pass_oe (play_type if unfiltered).
              None is allowed: R then falls back to wind-only regime with
              r_ok == False everywhere.

    Returns one row per game_id. All C and R columns are home-positive and free
    of NaN; `c_ok` / `r_ok` mark rows with insufficient prior history rather than
    dropping them.
    """
    need = ["game_id", "season", "week", "home_team", "away_team"]
    missing = [c for c in need if c not in games_df.columns]
    if missing:
        raise ValueError("games_df missing required columns: %s" % missing)

    g = games_df.copy()
    if "time_index" not in g.columns:
        g["time_index"] = g["season"].astype(int) * 100 + g["week"].astype(int)
    g = g.sort_values(["time_index", "game_id"]).reset_index(drop=True)

    # ---- venue geometry ---------------------------------------------------
    sid = g["stadium_id"].fillna("???").astype(str)
    unknown = sorted(set(sid) - set(STADIUMS))
    if unknown:
        raise ValueError(
            "stadium_id(s) not in the STADIUMS table: %s -- add them, do not "
            "silently drop the games" % unknown)
    ven = np.array([STADIUMS[s][:3] for s in sid], dtype=float)
    ven_lat, ven_lon, ven_tz = ven[:, 0], ven[:, 1], ven[:, 2]

    # A team's home venue for a season = the modal stadium_id of its
    # location=='Home' games that season. Derived from the SCHEDULE, which is
    # published in May, so it is not a future fact. This is what makes LA/LAC
    # 2018-2019, OAK->LV 2020 and every temporary venue come out right.
    hm = g[g["location"].fillna("Home").astype(str).eq("Home")]
    base = (hm.groupby(["season", "home_team"])["stadium_id"]
              .agg(lambda s: s.value_counts().idxmax()).to_dict())

    def _base_venue(seasons, teams):
        out = []
        for s, t in zip(seasons, teams):
            v = base.get((s, t))
            if v is None:                    # team with no home game in range
                v = base.get((s - 1, t)) or base.get((s + 1, t))
            out.append(STADIUMS[v][:3] if v in STADIUMS else (np.nan,) * 3)
        return np.array(out, dtype=float)

    hb = _base_venue(g["season"].to_numpy(), g["home_team"].to_numpy())
    ab = _base_venue(g["season"].to_numpy(), g["away_team"].to_numpy())

    home_mi = _haversine_miles(hb[:, 0], hb[:, 1], ven_lat, ven_lon)
    away_mi = _haversine_miles(ab[:, 0], ab[:, 1], ven_lat, ven_lon)
    home_mi = np.nan_to_num(home_mi, nan=0.0)
    away_mi = np.nan_to_num(away_mi, nan=0.0)

    # ---- body clock -------------------------------------------------------
    hour = _gametime_hour_et(g["gametime"] if "gametime" in g else pd.Series([np.nan] * len(g)))
    hour_missing = hour.isna().to_numpy()
    hour = hour.fillna(13.0).to_numpy()

    home_pen = _circadian_penalty(hour + (np.nan_to_num(hb[:, 2], nan=ven_tz) - ET_OFFSET))
    away_pen = _circadian_penalty(hour + (np.nan_to_num(ab[:, 2], nan=ven_tz) - ET_OFFSET))
    home_shift = np.abs(ven_tz - np.nan_to_num(hb[:, 2], nan=ven_tz))
    away_shift = np.abs(ven_tz - np.nan_to_num(ab[:, 2], nan=ven_tz))

    # ---- weather ----------------------------------------------------------
    g = _neutralise_weather(g)
    home_clim, away_clim = _asof_team_climate(g)

    # ---- C components (all home-positive) ---------------------------------
    rest_diff = (pd.to_numeric(g["home_rest"], errors="coerce")
                 - pd.to_numeric(g["away_rest"], errors="coerce")).fillna(0.0).to_numpy()
    short_diff = _short_week(g["away_rest"]) - _short_week(g["home_rest"])
    bye_diff = _bye_return(g["home_rest"]) - _bye_return(g["away_rest"])
    travel_diff = away_mi - home_mi
    tz_pen_diff = away_pen - home_pen
    tz_shift_diff = away_shift - home_shift

    tix = g["time_index"].to_numpy()
    z_rest, ok_rest = _asof_z(rest_diff, tix)
    z_travel, ok_travel = _asof_z(travel_diff, tix)
    z_wind, _ = _asof_z(np.where(g["indoor"].to_numpy() == 1, np.nan, g["wind_n"].to_numpy()), tix)
    z_wind = np.where(g["indoor"].to_numpy() == 1, 0.0, z_wind)

    # Unit weights on unit-scale pieces; B_C absorbs the overall scale and the
    # components are emitted separately so the fit can re-weight them.
    c_raw = (z_rest
             + 0.5 * short_diff
             + 0.5 * bye_diff
             + z_travel
             + tz_pen_diff / 3.0)
    # Standardised by the same strictly-prior-weeks rule as everything else --
    # NOT by an expanding() over row order, which would let a game see other
    # games in its own week. Rows still inside the warm-up (where z_rest /
    # z_travel are forced to 0) are masked OUT of the scaler's own statistics:
    # leaving them in shrinks the early SD toward the SD of the kink terms alone
    # and then divides every later game by it, which manufactured a C of +20.
    warm = ok_rest & ok_travel
    C, ok_c = _asof_z(np.where(warm, c_raw, np.nan), tix)
    ok_c = ok_c & warm

    temp_shock = np.where(g["indoor"].to_numpy() == 1, 0.0,
                          np.maximum(0.0, np.nan_to_num(away_clim, nan=g["temp_n"].to_numpy())
                                     - g["temp_n"].to_numpy()) / 10.0)

    # ---- R ----------------------------------------------------------------
    pace_hat_h = np.full(len(g), np.nan); pace_hat_a = np.full(len(g), np.nan)
    proe_hat_h = np.full(len(g), np.nan); proe_hat_a = np.full(len(g), np.nan)
    prior_h = np.zeros(len(g)); prior_a = np.zeros(len(g))
    pace_z = np.zeros(len(g)); proe_z = np.zeros(len(g))
    have_pbp = np.zeros(len(g), dtype=bool)
    eb_diag = pd.DataFrame()

    if pbp_df is not None and len(pbp_df):
        tg = _team_game_frame(pbp_df)
        tg, eb_diag = _asof_eb_rates(tg)
        key = tg.set_index(["game_id", "team"])

        d = eb_diag.set_index("time_index")
        pbp_games = set(tg["game_id"])
        in_pbp = g["game_id"].isin(pbp_games).to_numpy()
        for side, ph, pr, pn in (("home_team", pace_hat_h, proe_hat_h, prior_h),
                                 ("away_team", pace_hat_a, proe_hat_a, prior_a)):
            look = pd.MultiIndex.from_arrays([g["game_id"].to_numpy(),
                                              _norm_team(g[side])])
            sub = key.reindex(look)
            ph[:] = sub["plays_hat"].to_numpy()
            pr[:] = sub["proe_hat"].to_numpy()
            pn[:] = np.nan_to_num(sub["prior_games"].to_numpy(), nan=0.0)
            # If a game HAS pbp, both of its teams must have matched. A miss here
            # is an abbreviation drift, not a missing season, and it must be loud.
            miss = in_pbp & ~sub.index.isin(key.index)
            if miss.any():
                bad = [(gid, t) for gid, t in
                       zip(g.loc[miss, "game_id"], _norm_team(g.loc[miss, side]))][:10]
                raise ValueError(
                    "%d game(s) have pbp but their %s did not join -- team "
                    "abbreviation drift, add it to TEAM_ALIASES. Examples: %s"
                    % (int(miss.sum()), side, bad))

        have_pbp = np.isfinite(pace_hat_h) & np.isfinite(pace_hat_a)

        lg_pace = g["time_index"].map(d["plays_league"]).to_numpy(dtype=float)
        lg_proe = g["time_index"].map(d["proe_league"]).to_numpy(dtype=float)
        lg_n = g["time_index"].map(d["plays_n_prior"]).to_numpy(dtype=float)

        # Scale each by the as-of SD of the RAW team-game value,
        # sqrt(sw2 + sb2) -- the observable spread, which is always well defined.
        #
        # Emphatically NOT by sqrt(sb2) alone, and NOT by re-standardising each
        # component to unit variance. Two reasons:
        #   * sb2 is a small difference of two large numbers and goes to ~0 in
        #     early weeks, so dividing by it detonated pace_z (SD 2.6, pinned at
        #     the +/-4 clip);
        #   * re-standardising each component undoes the shrinkage. A heavily
        #     shrunk estimate SHOULD have a small spread and therefore a small
        #     say in the blend. Forcing it back to unit variance re-inflates pure
        #     noise, which matters enormously here: the EB decomposition says
        #     plays/game is almost entirely game script (sw2 ~72 vs sb2 ~1, so
        #     k ~ 75 games) while PROE is nearly all real talent (sw2 ~53 vs
        #     sb2 ~11, k ~ 5 games). Dividing by the common raw scale lets pace
        #     contribute in proportion to how much of it is real, which is not
        #     very much. That is the honest weighting and it is not a tuned knob.
        sd_pace = np.sqrt(np.maximum(
            g["time_index"].map(d["plays_sw2"]).to_numpy(dtype=float)
            + g["time_index"].map(d["plays_sb2"]).to_numpy(dtype=float), 1e-6))
        sd_proe = np.sqrt(np.maximum(
            g["time_index"].map(d["proe_sw2"]).to_numpy(dtype=float)
            + g["time_index"].map(d["proe_sb2"]).to_numpy(dtype=float), 1e-6))

        # Sum of the two offences' deviations; two roughly independent deviations
        # summed have SD sqrt(2)*sd, divided back out (VAS.md's differencing rule
        # applied to a sum).
        with np.errstate(invalid="ignore"):
            pace_z = ((pace_hat_h - lg_pace) + (pace_hat_a - lg_pace)) / (np.sqrt(2.0) * sd_pace)
            proe_z = ((proe_hat_h - lg_proe) + (proe_hat_a - lg_proe)) / (np.sqrt(2.0) * sd_proe)
        pace_z = np.nan_to_num(pace_z, nan=0.0)
        proe_z = np.nan_to_num(proe_z, nan=0.0)

        r_ok = (have_pbp
                & (prior_h >= MIN_PRIOR_GAMES_R) & (prior_a >= MIN_PRIOR_GAMES_R)
                & np.isfinite(lg_n) & (lg_n >= MIN_PRIOR_TEAMGAMES_R))
    else:
        r_ok = np.zeros(len(g), dtype=bool)
        ok_form = np.zeros(len(g), dtype=bool)

    # pace_z and proe_z are on a common raw scale but are both well under unit
    # variance (that is the shrinkage doing its job). The BLEND is standardised
    # once, as-of, so that REGIME_CUT_* sit at the quantiles they are named for.
    # Standardising the blend preserves the relative weight of its two parts;
    # standardising the parts would not.
    form_raw = 0.5 * np.where(r_ok, pace_z, 0.0) + 0.5 * np.where(r_ok, proe_z, 0.0)
    form_z, ok_form = _asof_z(np.where(r_ok, form_raw, np.nan), tix)
    form_z = np.clip(np.where(ok_form, form_z, 0.0), -4.0, 4.0)

    latent = form_z + REGIME_INDOOR_BUMP * g["indoor"].to_numpy()
    p_grind, p_std, p_chaos = _regime_probs(latent, g["wind_n"].to_numpy())
    regime_score = p_chaos - p_grind

    r_ok = r_ok & ok_form

    spread = pd.to_numeric(g.get("spread_line"), errors="coerce").to_numpy(dtype=float)
    fav = np.tanh(np.nan_to_num(spread, nan=0.0) / 7.0)
    r_ml = regime_score * fav

    lab = np.array(["GRIND", "STANDARD", "CHAOS"])
    regime = lab[np.argmax(np.vstack([p_grind, p_std, p_chaos]), axis=0)]

    out = pd.DataFrame({
        "game_id": g["game_id"].to_numpy(),
        "season": g["season"].to_numpy(),
        "week": g["week"].to_numpy(),
        "time_index": tix,
        "home_team": g["home_team"].to_numpy(),
        "away_team": g["away_team"].to_numpy(),

        # --- Context -------------------------------------------------------
        "C": C,
        "c_rest_diff": rest_diff,
        "c_rest_diff_z": z_rest,
        "c_short_week": short_diff,
        "c_bye_return": bye_diff,
        "c_travel_diff_mi": travel_diff,
        "c_travel_diff_z": z_travel,
        "c_home_travel_mi": home_mi,
        "c_away_travel_mi": away_mi,
        "c_tz_pen_diff": tz_pen_diff,
        "c_tz_shift_diff": tz_shift_diff,
        "c_kick_hour_et": hour,
        "c_kick_hour_missing": hour_missing.astype(int),
        "c_ok": ok_c,

        # --- context extras, deliberately OUTSIDE the composite ------------
        # div_game has no a-priori home-positive sign (familiarity compresses
        # home edge, if anything), and the weather terms are regime inputs that
        # may also carry a direct effect. Emitted for the fit to judge.
        "c_div_game": pd.to_numeric(g.get("div_game"), errors="coerce").fillna(0).astype(int).to_numpy(),
        "c_neutral_site": g["location"].fillna("Home").astype(str).ne("Home").astype(int).to_numpy(),
        "c_indoor": g["indoor"].to_numpy(),
        "c_temp": g["temp_n"].to_numpy(),
        "c_wind": g["wind_n"].to_numpy(),
        "c_wind_z": z_wind,
        "c_weather_imputed": g["weather_imputed"].to_numpy(),
        "c_temp_shock": temp_shock,
        "c_surface_turf": (~g["surface"].fillna("grass").astype(str)
                           .str.lower().str.contains("grass")).astype(int).to_numpy(),

        # --- Regime --------------------------------------------------------
        "R": r_ml,
        "r_ml": r_ml,
        "r_regime_score": regime_score,
        "r_p_grind": p_grind,
        "r_p_standard": p_std,
        "r_p_chaos": p_chaos,
        "r_regime": regime,
        "r_fav": fav,
        "r_form_z": form_z,
        "r_latent": latent,
        "r_pace_z": pace_z,
        "r_proe_z": proe_z,
        "r_pace_hat_home": pace_hat_h,
        "r_pace_hat_away": pace_hat_a,
        "r_proe_hat_home": proe_hat_h,
        "r_proe_hat_away": proe_hat_a,
        "r_prior_games_home": prior_h,
        "r_prior_games_away": prior_a,
        "r_ok": r_ok,
    })

    for c in out.columns:
        if out[c].dtype.kind == "f":
            out[c] = out[c].fillna(0.0)
    return out.set_index("game_id", drop=False)


# ---------------------------------------------------------------------------
# sanity / self-test
# ---------------------------------------------------------------------------
def _novig_home(g):
    """Two-way no-vig home probability. Guards hold <= 0 (one stale/arbed quote
    exists 2018-2025) rather than dividing blindly."""
    def imp(ml):
        ml = pd.to_numeric(ml, errors="coerce")
        return np.where(ml < 0, -ml / (-ml + 100.0), 100.0 / (ml + 100.0))
    ih, ia = imp(g["home_moneyline"]), imp(g["away_moneyline"])
    tot = ih + ia
    return np.where(tot > 0, ih / tot, np.nan)


def _geo_crosscheck():
    """geo.json is city-keyed with no tz; cross-check the venues it does cover."""
    if not os.path.exists(GEO_JSON):
        return "geo.json not found at %s" % GEO_JSON
    with open(GEO_JSON) as fh:
        geo = json.load(fh)
    pairs = {
        "Chicago, IL": "CHI98", "Nashville, TN": "NAS00", "Foxborough, MA": "BOS00",
        "East Rutherford, NJ": "NYC01", "Tampa, FL": "TAM00", "Baltimore, MD": "BAL00",
        "Denver, CO": "DEN00", "Inglewood, CA": "LAX01", "Santa Clara, CA": "SFO01",
        "Kansas City, MO": "KAN00", "Green Bay, WI": "GNB00", "Orchard Park, NY": "BUF00",
        "Cleveland, OH": "CLE00", "Miami Gardens, FL": "MIA00", "Pittsburgh, PA": "PIT00",
        "Landover, MD": "WAS00", "Jacksonville, FL": "JAX00",
        "Rio De Janeiro, undefined": "RIO00",
    }
    bad = []
    for city, sid in pairs.items():
        if city not in geo or sid not in STADIUMS:
            continue
        la, lo = geo[city]
        d = float(_haversine_miles(la, lo, STADIUMS[sid][0], STADIUMS[sid][1]))
        if d > 25.0:
            bad.append("%s vs %s: %.1f mi" % (city, sid, d))
    return ("geo.json cross-check: %d/%d venues agree within 25 mi%s"
            % (len(pairs) - len(bad), len(pairs),
               "" if not bad else " -- DISAGREE: " + "; ".join(bad)))


if __name__ == "__main__":
    from load import load_games, load_pbp, cached_pbp_seasons

    pd.set_option("display.width", 160)
    seas = cached_pbp_seasons()
    lo, hi = min(seas), max(seas)

    print("=" * 78)
    print("features_context.py -- Context (C) + Regime (R)")
    print("=" * 78)
    print(_geo_crosscheck())

    WARM_FROM = 2010
    games = load_games(seasons=(WARM_FROM, hi), played_only=True)
    print("\ngames loaded: %d rows, %d..%d -- the fit window is 2018-2025; the "
          "earlier seasons exist only to WARM the as-of standardisers (rest, "
          "travel, the C composite, weather imputation, team climate). They are "
          "strictly before every fitted row, so warming cannot leak into it. C "
          "needs no pbp, so it warms all the way back; R cannot, because pbp is "
          "cached from %d." % (len(games), WARM_FROM, hi, lo))

    pbp = load_pbp((lo, hi), columns=["posteam", "pass_oe", "play_type"],
                   offense_only=True)
    print("pbp loaded: %d scrimmage plays, %d seasons" % (len(pbp), len(seas)))
    leaked = [c for c in PBP_FORBIDDEN if c in pbp.columns]
    print("forbidden pbp columns present in the working frame: %s"
          % (leaked if leaked else "none"))

    feats = build(games, pbp)
    print("\nfeatures: %d rows x %d cols, keyed by game_id (unique: %s)"
          % (len(feats), feats.shape[1], feats["game_id"].is_unique))

    fit = load_games(seasons=(2018, 2025), require_lines=True, played_only=True)
    f = feats.reindex(fit["game_id"].to_numpy())
    fit = fit.set_index("game_id", drop=False).loc[f.index]
    print("joined onto the 2018-2025 fittable set: %d rows, NaN after join: %d"
          % (len(f), int(f.isna().sum().sum())))

    print("\n--- COVERAGE ---")
    print("c_ok  : %d/%d (%.1f%%)  first c_ok game: %s"
          % (f["c_ok"].sum(), len(f), 100.0 * f["c_ok"].mean(),
             f.loc[f["c_ok"], "game_id"].iloc[0] if f["c_ok"].any() else "-"))
    print("r_ok  : %d/%d (%.1f%%)  first r_ok game: %s"
          % (f["r_ok"].sum(), len(f), 100.0 * f["r_ok"].mean(),
             f.loc[f["r_ok"], "game_id"].iloc[0] if f["r_ok"].any() else "-"))
    print("by season, r_ok rate:")
    print(f.groupby("season")["r_ok"].mean().round(3).to_string())
    print("(2018-2019 are short because pbp is only cached from 2018, so the "
          "as-of pace/PROE history and its standardiser both start cold. nflverse "
          "pbp goes back to 1999 -- `fetch.py --seasons 2014-2025` pushes r_ok to "
          "~100%% across the fit window. Until then, either drop !r_ok rows or "
          "let the fit use r_ok as a mask; do NOT treat R==0 there as a signal.)")
    print("weather imputed on outdoor games: %d; indoor (neutralised): %d"
          % (int(f["c_weather_imputed"].sum()), int(f["c_indoor"].sum())))

    print("\n--- C COMPONENTS (home-positive; describe) ---")
    ccols = ["C", "c_rest_diff", "c_rest_diff_z", "c_short_week", "c_bye_return",
             "c_travel_diff_mi", "c_travel_diff_z", "c_tz_pen_diff",
             "c_tz_shift_diff", "c_temp_shock", "c_wind", "c_wind_z"]
    print(f[ccols].describe().T[["mean", "std", "min", "25%", "50%", "75%", "max"]].round(3).to_string())

    print("\n--- C COMPONENT CORRELATIONS (collinear by construction) ---")
    print(f[["C", "c_rest_diff_z", "c_short_week", "c_bye_return",
             "c_travel_diff_z", "c_tz_pen_diff"]].corr().round(3).to_string())

    print("\n--- travel sanity ---")
    print("home_travel_mi > 50 (neutral sites only): %d rows; neutral flagged: %d"
          % (int((f["c_home_travel_mi"] > 50).sum()), int(f["c_neutral_site"].sum())))
    print("longest away trips:")
    print(f.nlargest(5, "c_away_travel_mi")[
        ["game_id", "away_team", "home_team", "c_away_travel_mi",
         "c_home_travel_mi", "c_tz_pen_diff"]].to_string(index=False))
    print("worst home body-clock (away team advantaged):")
    print(f.nsmallest(5, "c_tz_pen_diff")[
        ["game_id", "away_team", "home_team", "c_kick_hour_et",
         "c_tz_pen_diff"]].to_string(index=False))

    print("\n--- REGIME DISTRIBUTION ---")
    print("mean probabilities : GRIND %.3f  STANDARD %.3f  CHAOS %.3f"
          % (f["r_p_grind"].mean(), f["r_p_standard"].mean(), f["r_p_chaos"].mean()))
    print("argmax label counts:")
    print(f["r_regime"].value_counts().to_string())
    print("\nr_ok rows only (%d):" % int(f["r_ok"].sum()))
    fo = f[f["r_ok"]]
    print("mean probabilities : GRIND %.3f  STANDARD %.3f  CHAOS %.3f"
          % (fo["r_p_grind"].mean(), fo["r_p_standard"].mean(), fo["r_p_chaos"].mean()))
    print(fo["r_regime"].value_counts().to_string())

    print("\nregime by wind bucket (outdoor only):")
    od = fo[fo["c_indoor"] == 0].copy()
    od["wind_bucket"] = pd.cut(od["c_wind"], [-0.1, 5, 10, 15, 20, 99],
                               labels=["0-5", "5-10", "10-15", "15-20", "20+"])
    print(od.groupby("wind_bucket", observed=True)[
        ["r_p_grind", "r_p_standard", "r_p_chaos"]].mean().round(3).to_string())
    print("n by bucket:", od["wind_bucket"].value_counts().sort_index().to_dict())
    print("\nregime by roof:")
    print(fo.groupby(fo["c_indoor"].map({0: "outdoor", 1: "indoor"}))[
        ["r_p_grind", "r_p_standard", "r_p_chaos"]].mean().round(3).to_string())
    print("\npre-blend component scales (small SD = heavily shrunk = little say, "
          "which is the point):")
    print(fo[["r_pace_z", "r_proe_z"]].describe().T[["mean", "std", "min", "max"]].round(3).to_string())
    print("\nlatent scales (these must sit near SD 1.0 for the cutpoints at "
          "+/-%.2f to mean the quantiles they are named for):" % REGIME_CUT_CHAOS)
    print(fo[["r_pace_z", "r_proe_z", "r_form_z", "r_latent"]]
          .describe().T[["mean", "std", "min", "50%", "max"]].round(3).to_string())
    print("corr(pace_z, proe_z) = %.3f" % fo[["r_pace_z", "r_proe_z"]].corr().iloc[0, 1])

    print("\nR (= r_ml) describe:")
    print(fo[["R", "r_regime_score", "r_fav"]].describe().T.round(3).to_string())

    print("\n--- EB SHRINKAGE, as-of (k in GAMES, recomputed every week) ---")
    tg = _team_game_frame(pbp)
    _, diag = _asof_eb_rates(tg)
    d = diag[diag["plays_n_prior"] >= MIN_PRIOR_TEAMGAMES_R]
    print("plays: k median %.1f  (p10 %.1f, p90 %.1f)   sw2 %.1f  sb2 %.2f"
          % (d["plays_k"].median(), d["plays_k"].quantile(.1),
             d["plays_k"].quantile(.9), d["plays_sw2"].median(),
             d["plays_sb2"].median()))
    print("proe : k median %.1f  (p10 %.1f, p90 %.1f)   sw2 %.1f  sb2 %.2f"
          % (d["proe_k"].median(), d["proe_k"].quantile(.1),
             d["proe_k"].quantile(.9), d["proe_sw2"].median(),
             d["proe_sb2"].median()))
    print("(k ~ the number of games at which a team's own record outweighs the "
          "league prior -- pace stabilises fast, PROE faster)")

    print("\n--- NO-LOOK-AHEAD SELF-CHECKS ---")
    wk1 = f[(f["week"] == 1) & (f["season"] == 2018)]
    print("2018 wk1 rows: %d | r_ok any: %s | pace_z all zero: %s | proe_z all zero: %s"
          % (len(wk1), bool(wk1["r_ok"].any()),
             bool((wk1["r_pace_z"] == 0).all()), bool((wk1["r_proe_z"] == 0).all())))
    wk1a = f[f["week"] == 1]
    print("all week-1 rows (%d): mean effective prior games home %.2f away %.2f"
          % (len(wk1a), wk1a["r_prior_games_home"].mean(),
             wk1a["r_prior_games_away"].mean()))
    print("  (> 0 after 2018 is the SEASON_CARRY=%.2f discounted carry-in, not a "
          "leak: a 17-game season carries in as ~%.1f games)"
          % (SEASON_CARRY, 17 * SEASON_CARRY))
    # a team can never have more effective prior games than games actually played
    # before that week
    played = {}
    viol = 0
    for _, r in feats.sort_values("time_index").iterrows():
        h = TEAM_ALIASES.get(r["home_team"], r["home_team"])
        a = TEAM_ALIASES.get(r["away_team"], r["away_team"])
        for t, col in ((h, "r_prior_games_home"), (a, "r_prior_games_away")):
            if r[col] > played.get(t, 0) + 1e-9:
                viol += 1
        for t in (h, a):
            played[t] = played.get(t, 0) + 1
    print("rows whose prior-game count exceeds games actually played before it: "
          "%d (must be 0)" % viol)

    # shuffle test: a feature that leaks the outcome will correlate with it far
    # more than with the market's own view of it.
    p_mkt = _novig_home(fit)
    home_win = (fit["result"] > 0).astype(float).to_numpy()
    tie = (fit["result"] == 0).to_numpy()
    m = np.isfinite(p_mkt) & ~tie
    logit_mkt = np.log(np.clip(p_mkt, 1e-6, 1 - 1e-6) / (1 - np.clip(p_mkt, 1e-6, 1 - 1e-6)))
    print("\nfit rows usable (no tie, p_mkt finite): %d of %d (%d ties dropped)"
          % (m.sum(), len(m), int(tie.sum())))
    print("baseline: mean p_mkt %.4f vs actual home win rate %.4f"
          % (p_mkt[m].mean(), home_win[m].mean()))
    print("\ncorr(feature, home_win) vs corr(feature, logit p_mkt) -- a feature "
          "that tracks the OUTCOME much harder than it tracks the MARKET is the "
          "leak signature:")
    rows = []
    for c in ["C", "c_rest_diff_z", "c_short_week", "c_bye_return",
              "c_travel_diff_z", "c_tz_pen_diff", "c_div_game", "c_indoor",
              "c_wind_z", "c_temp_shock", "c_surface_turf", "c_neutral_site",
              "R", "r_regime_score", "r_pace_z", "r_proe_z", "r_fav"]:
        v = f[c].to_numpy(dtype=float)[m]
        if np.std(v) < 1e-12:
            rows.append((c, np.nan, np.nan, np.nan))
            continue
        rows.append((c,
                     float(np.corrcoef(v, home_win[m])[0, 1]),
                     float(np.corrcoef(v, logit_mkt[m])[0, 1]),
                     float(np.corrcoef(v, home_win[m] - p_mkt[m])[0, 1])))
    print(pd.DataFrame(rows, columns=["feature", "corr_outcome", "corr_logit_mkt",
                                      "corr_mkt_residual"]).round(4).to_string(index=False))
    print("\nNOTE: r_fav is built FROM the closing spread, so its ~0.45 "
          "correlation with the outcome is the market, not a leak. R inherits "
          "that scale; only corr_mkt_residual is evidence of anything.")
