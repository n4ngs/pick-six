#!/usr/bin/env python3
"""
hunt_early_season_extras.py -- POST-HOC EXTRAS to hunt_early_season.py.

These are NOT pre-registered. They were written AFTER seeing that T7
(gamma_L = +0.423, p = .0145 on 3,534 held-out weeks-5+ games) was the one
pre-registered test to cross raw p < .05. They exist to try to KILL it, not
to dress it up, and each one is counted and reported whichever way it lands.

EXTRA TESTS (E1-E3), all reported:

  E1  Is T7 a WEEK-BUCKET finding at all, or just the whole-sample effect
      wearing a week label? Refit a single pooled gamma_D on ALL held-out
      games (every week), same CV. If the pooled gamma is significant too,
      T7 says nothing about weeks 5+ specifically -- it is the overall model
      effect, restricted to 82% of the sample. That matters enormously for
      how the result is described.

  E2  Does T7 survive the correct correlation unit? Every held-out game in
      test season s was scored with the SAME trained coefficient vector, so
      games within a season are NOT independent and the GLM's nonrobust SE
      is too small. Refit gE/gL with season-CLUSTER-robust SEs, and add a
      season-block bootstrap of gamma_L.

  E3  Is it an EDGE or just a correlation? The gamma in T7 was estimated on
      the same held-out games it was scored on -- that is out-of-sample for
      the four B coefficients but IN-sample for gamma. Nested test: for each
      test season, estimate gamma on the held-out games of EARLIER test
      seasons only, then apply it to this season and score the resulting
      probability against the closing price by log loss. Expanding window,
      no chosen start point (it begins at the second available test season).
      This is the only number here that answers "would betting this have
      made money against the close".

Nothing here changes any pre-registered filter, window or cutoff.
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from fit import logit, sigmoid, logloss

HERE = os.path.dirname(os.path.abspath(__file__))
warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("display.width", 180)

RULE = "=" * 100
Z80 = 2.8015519
SEASON_LO, SEASON_HI = 2006, 2025
EARLY_MAX_WEEK = 4
VEC_COLS = ["F", "p_qb_z", "C", "R"]


def head(t):
    print("\n" + RULE)
    print(t)
    print(RULE)


def build_oos():
    d = pd.read_parquet(os.path.join(HERE, "out_full_fit_table.parquet"))
    d = d[d["game_type"].eq("REG")
          & d["season"].between(SEASON_LO, SEASON_HI)].copy()
    d["EARLY"] = (d["week"] <= EARLY_MAX_WEEK).astype(int)
    pieces = []
    for s in range(SEASON_LO + 2, SEASON_HI + 1):
        tr, te = d[d["season"] < s], d[d["season"] == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        r = sm.GLM(tr["home_win"].to_numpy(dtype=float),
                   tr[VEC_COLS].astype(float),
                   family=sm.families.Binomial(),
                   offset=logit(tr["p_mkt_mult"].to_numpy())).fit()
        b = r.params.reindex(VEC_COLS).to_numpy(dtype=float)
        p = te[["game_id", "season", "week", "EARLY", "home_win",
                "p_mkt_mult"]].copy()
        p["D_oos"] = te[VEC_COLS].to_numpy(dtype=float).dot(b)
        pieces.append(p)
    return pd.concat(pieces, ignore_index=True)


def e1_pooled(oos):
    head("E1 -- IS T7 A WEEK FINDING, OR JUST THE WHOLE-SAMPLE EFFECT?")
    y = oos["home_win"].to_numpy(dtype=float)
    off = logit(oos["p_mkt_mult"].to_numpy())
    X = pd.DataFrame({"gamma_D": oos["D_oos"].to_numpy()}, index=oos.index)
    r = sm.GLM(y, X, family=sm.families.Binomial(), offset=off).fit()
    lo, hi = r.conf_int().iloc[0]
    print("pooled gamma_D on ALL %d held-out games (every week, 2008-2025):"
          % len(oos))
    print("  gamma_D = %+.4f  (SE %.4f, z %+.2f, p %.4f, 95%% CI [%+.3f, %+.3f])"
          % (r.params.iloc[0], r.bse.iloc[0], r.tvalues.iloc[0],
             r.pvalues.iloc[0], lo, hi))
    print("  prior 2019-2025 run reported gamma_D = +0.373 (SE 0.242, p .123) "
          "on its smaller OOS set.")
    print("\n  -> %s" % (
        "The POOLED gamma is significant too. T7 is therefore NOT a weeks-5+ "
        "discovery;\n     it is the overall model effect measured on 82%% of "
        "the sample. The week split\n     added nothing and must not be "
        "described as if it had."
        if r.pvalues.iloc[0] < 0.05 else
        "The pooled gamma is NOT significant while the weeks-5+ slice is. A "
        "result that\n     exists only inside a subgroup and vanishes in the "
        "whole is the classic signature\n     of a partition artefact, and "
        "should be treated as one."))
    return r


def e2_cluster(oos):
    head("E2 -- SEASON-CLUSTERED SEs (games in a test season share one "
         "trained coefficient vector)")
    y = oos["home_win"].to_numpy(dtype=float)
    off = logit(oos["p_mkt_mult"].to_numpy())
    X = pd.DataFrame({
        "gE": (oos["D_oos"] * oos["EARLY"]).to_numpy(dtype=float),
        "gL": (oos["D_oos"] * (1 - oos["EARLY"])).to_numpy(dtype=float),
    }, index=oos.index)
    g = oos["season"].to_numpy()

    naive = sm.GLM(y, X, family=sm.families.Binomial(), offset=off).fit()
    clus = sm.GLM(y, X, family=sm.families.Binomial(), offset=off).fit(
        cov_type="cluster", cov_kwds={"groups": g, "use_correction": True})
    Xd = pd.DataFrame({"gamma_D": oos["D_oos"].to_numpy()}, index=oos.index)
    clus_d = sm.GLM(y, Xd, family=sm.families.Binomial(), offset=off).fit(
        cov_type="cluster", cov_kwds={"groups": g, "use_correction": True})

    tab = pd.DataFrame({
        "gamma": [naive.params["gE"], naive.params["gL"]],
        "SE naive": [naive.bse["gE"], naive.bse["gL"]],
        "p naive": [naive.pvalues["gE"], naive.pvalues["gL"]],
        "SE clustered": [clus.bse["gE"], clus.bse["gL"]],
        "p clustered": [clus.pvalues["gE"], clus.pvalues["gL"]],
    }, index=["gE (w2-4)", "gL (w5+)"])
    print(tab.round(4).to_string())
    print("\npooled gamma_D with clustered SE: %+.4f (SE %.4f, p %.4f)"
          % (clus_d.params.iloc[0], clus_d.bse.iloc[0], clus_d.pvalues.iloc[0]))

    rng = np.random.default_rng(20260920)
    seasons = sorted(oos["season"].unique())
    parts = {s: oos[oos.season == s] for s in seasons}
    boots = []
    for _ in range(1000):
        pick = rng.integers(0, len(seasons), len(seasons))
        b = pd.concat([parts[seasons[j]] for j in pick], ignore_index=True)
        late = b[b["EARLY"] == 0]
        if len(late) < 100:
            continue
        try:
            rr = sm.GLM(late["home_win"].to_numpy(dtype=float),
                        pd.DataFrame({"gL": late["D_oos"].to_numpy()}),
                        family=sm.families.Binomial(),
                        offset=logit(late["p_mkt_mult"].to_numpy())).fit()
            boots.append(float(rr.params.iloc[0]))
        except Exception:
            pass
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print("\nseason-block bootstrap of gamma_L (%d resamples of whole seasons):"
          % len(boots))
    print("  mean %+.4f   SE %.4f   95%% CI [%+.4f, %+.4f]   -> %s"
          % (boots.mean(), boots.std(ddof=1), lo, hi,
             "EXCLUDES zero" if lo > 0 else "CONTAINS zero"))
    return clus, boots


def e3_nested(oos):
    head("E3 -- THE ONLY QUESTION THAT PAYS: NESTED OOS. GAMMA FROM EARLIER "
         "TEST SEASONS, APPLIED FORWARD")
    print("""For each test season s, estimate a single scale gamma on the held-out
games of test seasons EARLIER than s only, then score season s with
p = sigmoid(logit(p_mkt) + gamma * D_oos) and compare to the closing price.
Nothing in this loop ever sees its own season. Expanding window, no chosen
start point: it begins at the second available test season.
""")
    seasons = sorted(oos["season"].unique())
    rows, kept = [], []
    for i, s in enumerate(seasons):
        if i == 0:
            continue
        prior = oos[oos["season"] < s]
        te = oos[oos["season"] == s]
        if len(prior) < 150:
            continue
        rr = sm.GLM(prior["home_win"].to_numpy(dtype=float),
                    pd.DataFrame({"g": prior["D_oos"].to_numpy()}),
                    family=sm.families.Binomial(),
                    offset=logit(prior["p_mkt_mult"].to_numpy())).fit()
        gam = float(rr.params.iloc[0])
        off = logit(te["p_mkt_mult"].to_numpy())
        y = te["home_win"].to_numpy()
        pmod = sigmoid(off + gam * te["D_oos"].to_numpy())
        pm = te["p_mkt_mult"].to_numpy()
        rows.append({"season": s, "n": len(te), "gamma_from_past": gam,
                     "ll_mkt": logloss(y, pm), "ll_model": logloss(y, pmod),
                     "d_ll": logloss(y, pm) - logloss(y, pmod)})
        t = te.copy()
        t["p_nested"] = pmod
        kept.append(t)
    fl = pd.DataFrame(rows).set_index("season")
    print(fl.round(5).to_string())
    print("\nseasons where the nested model beat the close on log loss: %d of %d"
          % (int((fl["d_ll"] > 0).sum()), len(fl)))

    k = pd.concat(kept, ignore_index=True)
    y = k["home_win"].to_numpy()
    pm = np.clip(k["p_mkt_mult"].to_numpy(), 1e-9, 1 - 1e-9)
    pp = np.clip(k["p_nested"].to_numpy(), 1e-9, 1 - 1e-9)
    li_m = -(y * np.log(pm) + (1 - y) * np.log(1 - pm))
    li_p = -(y * np.log(pp) + (1 - y) * np.log(1 - pp))
    diff = li_m - li_p
    print("\nPOOLED NESTED OOS (%d games, %d-%d):"
          % (len(k), k["season"].min(), k["season"].max()))
    print("  market log loss %.6f   nested model %.6f   delta %+.6f"
          % (li_m.mean(), li_p.mean(), diff.mean()))

    rng = np.random.default_rng(20260920)
    seas = sorted(k["season"].unique())
    by = [diff[k["season"].to_numpy() == s] for s in seas]
    bs = np.array([np.concatenate([by[j] for j in
                                   rng.integers(0, len(seas), len(seas))]).mean()
                   for _ in range(2000)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    se = bs.std(ddof=1)
    z = diff.mean() / se
    p = 2 * stats.norm.sf(abs(z))
    print("  season-block bootstrap: SE %.6f  95%% CI [%+.6f, %+.6f]  z %+.2f  "
          "p %.4f" % (se, lo, hi, z, p))
    print("  MDE @80%% power: %.6f nats/game" % (Z80 * se))
    print("  -> %s" % ("the nested model BEATS the closing price out of sample"
                       if lo > 0 else
                       "the nested model does NOT beat the closing price out "
                       "of sample"))

    # late-weeks-only slice of the same nested test
    kl = k[k["EARLY"] == 0]
    yl = kl["home_win"].to_numpy()
    pml = np.clip(kl["p_mkt_mult"].to_numpy(), 1e-9, 1 - 1e-9)
    ppl = np.clip(kl["p_nested"].to_numpy(), 1e-9, 1 - 1e-9)
    dl = (-(yl * np.log(pml) + (1 - yl) * np.log(1 - pml))
          - (-(yl * np.log(ppl) + (1 - yl) * np.log(1 - ppl))))
    seasl = sorted(kl["season"].unique())
    byl = [dl[kl["season"].to_numpy() == s] for s in seasl]
    bsl = np.array([np.concatenate([byl[j] for j in
                                    rng.integers(0, len(seasl), len(seasl))]).mean()
                    for _ in range(2000)])
    lol, hil = np.percentile(bsl, [2.5, 97.5])
    print("\n  weeks-5+ slice only (%d games): delta %+.6f, season-block 95%% "
          "CI [%+.6f, %+.6f] -> %s"
          % (len(kl), dl.mean(), lol, hil,
             "beats the close" if lol > 0 else "does NOT beat the close"))
    return fl, diff.mean(), p


def main():
    print(RULE)
    print("POST-HOC EXTRAS (E1-E3) -- written after seeing T7. Counted and "
          "reported either way.")
    print(RULE)
    oos = build_oos()
    print("\nheld-out set rebuilt identically to the pre-registered run: %d "
          "games, %d EARLY / %d LATE"
          % (len(oos), int(oos["EARLY"].sum()), int((1 - oos["EARLY"]).sum())))
    e1_pooled(oos)
    e2_cluster(oos)
    e3_nested(oos)
    print("\n" + RULE)
    print("EXTRA TESTS RUN: 3 (E1, E2, E3). Grand total for id 'early-season': "
          "7 pre-registered + 3 post-hoc = 10.")
    print(RULE)


if __name__ == "__main__":
    main()
