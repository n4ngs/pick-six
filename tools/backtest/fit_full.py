#!/usr/bin/env python3
"""
fit_full.py -- PRE-REGISTERED re-run of the EXISTING 4-term VAS model on the
               MAXIMUM honest sample, to answer one question and only one:

                   WAS THE 2019-2025 RUN (n=1812) SIMPLY UNDERPOWERED?

===========================================================================
PRE-REGISTRATION  (written before any fit was run; run ONCE as specified)
===========================================================================

HYPOTHESIS
  H0 (the null, and what the 2019-2025 run failed to reject):
      B_F = B_P = B_C = B_R = 0.
      The closing no-vig moneyline already contains everything the four
      vectors know.
  H1: at least one B differs from zero.
  The SAME model, the SAME features, the SAME estimator as the prior run.
  Nothing is added, removed, reweighted or reparameterised. The ONLY change
  is the number of seasons in the sample.

MODEL (unchanged from fit.py)
      home_win ~ Binomial, logit link
      linear predictor = logit(p_mkt)  +  B_F*F + B_P*p_qb_z + B_C*C + B_R*R
      logit(p_mkt) enters via offset= : its coefficient is PINNED to 1 and is
      NOT estimated. B = 0 is exactly "the market already knows this".
      p_mkt = multiplicative (proportional) de-vig of the closing two-way
      moneyline, home side. Identical to fit.py's choice.

RESPONSE VARIABLE
      home_win = 1[result > 0]. Ties excluded (a moneyline tie is a PUSH,
      not a loss). Identical to fit.py.

SAMPLE FILTER (byte-identical to fit.py's eligible(), only the season bounds move)
      season in [FIT_LO, FIT_HI]
      & hold > 0                        (a no-vig price must be defined)
      & not a tie
      & F, p_qb_z, C, R all non-null
      & f_ready & r_ok & ~qb_history_thin

SEASON BOUNDS -- DECIDED BEFORE FITTING, FROM DATA AVAILABILITY ONLY
      Established in the availability audit below (section 0), which was run
      BEFORE this fit and looked only at column null-rates and line coverage,
      never at an outcome. Two independent constraints both bind at 2006:
        * games.csv carries NO moneyline before 2006 -> p_mkt, the offset the
          whole model is defined against, does not exist. 1999-2005 are not
          "dropped", they are unfittable.
        * nflfastR `pass_oe` is 0.0% populated before 2006 -> Vector R's PROE
          half does not exist.
      So: FIT_LO = 2006, FIT_HI = 2025.  WARM_FROM = 1999 for F and P (seven
      free warm-up seasons the prior run did not have), 2006 for C/R.
      This bound is NOT a tuning knob. It is the first season at which all
      four vectors AND the offset are simultaneously constructible.

CROSS-VALIDATION
      Expanding window, SEASON-WISE ONLY. Train on seasons strictly earlier
      than the test season; test on the test season. Never random k-fold.
      First test season = FIT_LO + 2 = 2008, exactly the +2 offset the prior
      run used (FIT_LO 2019 -> first test 2021).

DECLARED TESTS (every one of these is reported, pass or fail)
      T1  full-sample Wald test on each of B_F, B_P, B_C, B_R   (4 tests)
      T2  out-of-sample gamma_v per vector on held-out games    (4 tests)
      T3  out-of-sample gamma_D on the pooled D                 (1 test)
      T4  pooled OOS log-loss vs the closing line, paired bootstrap (1 test)
      That is the whole list. 10 tests. No others are run.

THRESHOLD
      Two-sided alpha = 0.05 per coefficient, and Benjamini-Hochberg at
      FDR 10% across the four T1 coefficients (VAS.md's own multiplicity rule).
      A vector "survives" only if it is significant OUT of sample (T2/T3).

POWER  (the actual point of this run)
      Reported as the minimum detectable effect at 80% power, two-sided 5%:
          MDE(log-odds) = (z_.975 + z_.80) * SE = 2.8016 * SE
      reported per unit and per 1 SD of each vector, and converted to
      win-probability points. Also reported: the n that WOULD be needed for a
      3.0pp-per-SD effect, to check the prior critic's ~2,504-game claim.

WHAT WOULD FALSIFY THE "IT WAS UNDERPOWERED" STORY
      If the intervals tighten around zero and still contain it, the answer is
      not "underpowered" -- it is a STRONGER null. That is a successful result
      and is reported as such.

NO TUNING TO SIGNIFICANCE. This script is run once, as written above.
Writes only tools/backtest/out_full_*.parquet. Ships nothing.
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

import fit as FIT
from load import load_games, load_pbp
from fit import sigmoid, logit, american_to_prob, glm_fit, coef_table, \
    season_cv, oos_significance, logloss, brier, benjamini_hochberg, \
    head, RULE, THIN, VECTORS, VECTOR_COL, VECTOR_DESC

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
pd.set_option("display.width", 190)
pd.set_option("display.max_columns", 60)

HERE = os.path.dirname(os.path.abspath(__file__))

# --- the pre-registered window --------------------------------------------
WARM_FROM = 1999          # F and P warm from here
R_FROM = 2006             # pass_oe's first populated season
FIT_LO, FIT_HI = 2006, 2025
CV_TEST_SEASONS = list(range(FIT_LO + 2, FIT_HI + 1))

# push them into fit.py's globals so its own functions use this window
FIT.WARM_FROM = WARM_FROM
FIT.FIT_LO, FIT.FIT_HI = FIT_LO, FIT_HI
FIT.CV_TEST_SEASONS = CV_TEST_SEASONS

Z_A = stats.norm.ppf(0.975)       # 1.95996
Z_B = stats.norm.ppf(0.80)        # 0.84162
MDE_MULT = Z_A + Z_B              # 2.80158


# ==========================================================================
# 0. availability audit -- how far back does EACH feature actually go?
# ==========================================================================
def availability_audit():
    head("0. FEATURE AVAILABILITY AUDIT -- the earliest honest season, PER FEATURE")
    print("Ran BEFORE the fit. Looks only at column null-rates and line coverage.\n")

    g = pd.read_csv(os.path.join(FIT.__dict__.get("HERE", HERE), "..", "..",
                                 "data", "nflverse", "games.csv"),
                    low_memory=False)
    ml = g.groupby("season").apply(
        lambda d: pd.Series({
            "games": len(d),
            "spread": int(d["spread_line"].notna().sum()),
            "both_ML": int((d["home_moneyline"].notna()
                            & d["away_moneyline"].notna()).sum()),
            "qb_ids": int((d["home_qb_id"].notna()
                           & d["away_qb_id"].notna()).sum()),
            "rest": int((d["home_rest"].notna()
                         & d["away_rest"].notna()).sum()),
        }), include_groups=False)
    print("games.csv coverage by season (1999-2010 shown; the binding edge):")
    print(ml.loc[1999:2010].astype(int).to_string())
    print("\n  -> home+away MONEYLINE first appears in 2006 (220/267). It is")
    print("     ZERO for 1999-2005. p_mkt -- the OFFSET the entire model is")
    print("     defined against -- cannot be constructed before 2006.")
    print("     spread_line, QB ids and rest are all complete from 1999.")

    print("\nnflfastR pbp non-null rate on pass/run plays, by season "
          "(measured, not assumed):")
    print("  %-8s %-9s %-9s %-9s %-9s %-9s %-9s" %
          ("season", "epa", "success", "fixdrive", "qb_drop", "pass_oe", "xpass"))
    import pyarrow.parquet as pq
    dd = os.path.join(HERE, "..", "..", "data", "nflverse")
    for y in list(range(1999, 2009)) + [2025]:
        p = os.path.join(dd, "play_by_play_%d.parquet" % y)
        if not os.path.exists(p):
            continue
        df = pd.read_parquet(p, columns=["play_type", "epa", "success",
                                         "fixed_drive", "qb_dropback",
                                         "pass_oe", "xpass"])
        off = df[df["play_type"].isin(["pass", "run"])]
        print("  %-8d %-9s %-9s %-9s %-9s %-9s %-9s" % (
            y,
            "%.1f%%" % (100 * off["epa"].notna().mean()),
            "%.1f%%" % (100 * off["success"].notna().mean()),
            "%.1f%%" % (100 * off["fixed_drive"].notna().mean()),
            "%.1f%%" % (100 * df["qb_dropback"].notna().mean()),
            "%.1f%%" % (100 * off["pass_oe"].notna().mean()),
            "%.1f%%" % (100 * off["xpass"].notna().mean())))

    print("""
EARLIEST HONEST SEASON, PER FEATURE (nothing is silently dropped):

  p_mkt  (the OFFSET)  2006   games.csv has no moneyline at all before 2006.
                              HARD BOUND on the whole model.
  F      fundamental   1999   epa / ep / success / yardline_100 / fixed_drive /
                              running score are 100%% populated from 1999.
                              Needs one prior season to regress from -> usable
                              as a FEATURE from 2000, warm from 1999.
  P      personnel     1999   qb_dropback populated 91.9%% (1999) rising to 97%%;
                              passer_player_id OR rusher_player_id attributes
                              100.00%% of dropbacks in EVERY season 1999-2025.
                              home_qb_id/away_qb_id 100%% from 1999.
                              MIN_Z_GAMES=200 prior games -> p_qb_z live in 1999.
  C      context       1999   rest / travel / timezone come from games.csv only,
                              no pbp needed. Complete from 1999.
  R      regime        2006   pace is computable from 1999, but PROE is the mean
                              of `pass_oe`, which is 0.0%% populated 1999-2005
                              (nflfastR's xpass model is only trained from 2006).
                              HARD BOUND, and it lands on the same season as the
                              moneyline bound by coincidence, not construction.

  => FIT WINDOW 2006-2025. F and P get SEVEN warm-up seasons (1999-2005) that
     the 2019-2025 run did not have; R warms inside 2006 and its early rows are
     removed by the module's own r_ok flag, not by hand.""")


# ==========================================================================
# 1. build the table on the full window
# ==========================================================================
def build_full(rebuild=False):
    head("1. BUILD -- features over 1999-2025")
    import features_fundamental as FF
    import features_personnel as FP
    import features_context as FC

    paths = {k: os.path.join(HERE, "out_full_%s.parquet" % k)
             for k in ("fund", "pers", "ctx")}
    if all(os.path.exists(p) for p in paths.values()) and not rebuild:
        print("  reusing out_full_*.parquet")
        fund = pd.read_parquet(paths["fund"])
        pers = pd.read_parquet(paths["pers"])
        ctx = pd.read_parquet(paths["ctx"])
    else:
        seasons = list(range(WARM_FROM, FIT_HI + 1))
        print("  F: pbp %d-%d" % (WARM_FROM, FIT_HI))
        games_f = load_games(seasons=(WARM_FROM, FIT_HI), require_lines=False,
                             played_only=True)
        pbp_full = load_pbp(seasons, columns=FF.PBP_COLUMNS)
        fund = FF.build(games_f, pbp_full, verbose=False)
        print("     %d rows x %d cols" % fund.shape)
        del pbp_full

        print("  P: pbp %d-%d" % (WARM_FROM, FIT_HI))
        games_p = load_games(seasons=(WARM_FROM, FIT_HI), played_only=True)
        pbp_p = load_pbp(seasons, columns=FP.PBP_COLUMNS)
        pers = FP.build(games_p, pbp_p)
        print("     %d rows x %d cols" % pers.shape)
        del pbp_p

        print("  C/R: games %d-%d, pbp %d-%d (pass_oe's first populated season)"
              % (WARM_FROM, FIT_HI, R_FROM, FIT_HI))
        games_c = load_games(seasons=(WARM_FROM, FIT_HI), played_only=True)
        pbp_c = load_pbp(list(range(R_FROM, FIT_HI + 1)),
                         columns=["posteam", "pass_oe", "play_type"],
                         offense_only=True)
        ctx = FC.build(games_c, pbp_c, verbose=False).reset_index(drop=True)
        print("     %d rows x %d cols" % ctx.shape)
        del pbp_c

        for name, frame in (("fund", fund), ("pers", pers), ("ctx", ctx)):
            flat = frame.copy()
            flat.attrs = {}
            flat.to_parquet(paths[name], index=False)
        print("  cached to out_full_*.parquet")

    games = load_games(seasons=(FIT_LO, FIT_HI), require_lines=True,
                       played_only=True)
    print("\ngames %d-%d with complete closing spread+total+both MLs and a "
          "result: %d" % (FIT_LO, FIT_HI, len(games)))

    keep_f = ["game_id", "F", "f_eff", "f_finish", "f_finish_resid",
              "f_success", "f_ready", "home_prior_games", "away_prior_games"]
    keep_p = ["game_id", "p_qb", "p_qb_z", "qb_delta_diff", "qb_history_thin",
              "qb_fallback_home", "qb_fallback_away", "qb_new_starter_diff"]
    keep_c = ["game_id", "C", "R", "c_ok", "r_ok", "c_rest_diff_z",
              "c_travel_diff_z", "c_tz_pen_diff", "r_p_grind", "r_p_chaos"]

    t = games.merge(fund[keep_f], on="game_id", how="left", validate="1:1")
    t = t.merge(pers[keep_p], on="game_id", how="left", validate="1:1")
    t = t.merge(ctx[keep_c], on="game_id", how="left", validate="1:1")

    t["home_win"] = (t["result"] > 0).astype(int)
    t["is_tie"] = (t["result"] == 0)
    qh = american_to_prob(t["home_moneyline"])
    qa = american_to_prob(t["away_moneyline"])
    t["overround"] = qh + qa
    t["hold"] = t["overround"] - 1.0
    t["p_mkt_mult"] = qh / t["overround"]
    t["p_mkt_shift"] = qh - t["hold"] / 2.0
    return t


# ==========================================================================
# 2. power
# ==========================================================================
def power_report(res, d, n_prior=1812):
    head("POWER -- THE SMALLEST EFFECT THIS n COULD HAVE SEEN")
    print("""MDE at 80%% power, two-sided alpha=0.05, is (z_.975 + z_.80)*SE = %.4f*SE.
Win-probability points use the AVERAGE MARGINAL EFFECT on this sample,
mean[p(1-p)] over the fitted p_mkt, which is the honest conversion for a
logit offset model (the p=0.5 figure, 0.25, is the best case and is shown too).
""" % MDE_MULT)
    p = d["p_mkt_mult"].to_numpy()
    ame = float(np.mean(p * (1 - p)))
    print("  mean[p_mkt*(1-p_mkt)] on the fitted sample = %.4f  "
          "(vs 0.2500 at p=0.5)" % ame)
    print("  n = %d\n" % len(d))

    rows = []
    for v in VECTORS:
        c = VECTOR_COL[v]
        se = res.bse[c]
        sd = float(np.std(d[c]))
        mde_u = MDE_MULT * se                 # log-odds per 1 unit of x
        mde_sd = mde_u * sd                   # log-odds per 1 SD of x
        rows.append({
            "vector": v, "B": res.params[c], "SE": se, "sd(x)": sd,
            "MDE log-odds /unit": mde_u,
            "MDE log-odds /1sd": mde_sd,
            "MDE pp /1sd (AME)": 100 * ame * mde_sd,
            "MDE pp /1sd (p=.5)": 100 * 0.25 * mde_sd,
        })
    pw = pd.DataFrame(rows).set_index("vector")
    print(pw.round(5).to_string())

    print("\n" + THIN)
    print("CHECKING THE PRIOR CRITIC'S CLAIM: '~2,504 games were needed for a "
          "3.0pp effect'")
    print(THIN)
    print("SE scales as 1/sqrt(n), so n_needed = n * (MDE_here / target)^2.")
    print("Target = 3.0 win-probability points per 1 SD of the vector.\n")
    for conv, label in ((ame, "AME conversion (mean p(1-p) = %.4f)" % ame),
                        (0.25, "p=0.5 conversion (0.2500, best case)")):
        target_lo = 0.03 / conv               # log-odds per SD for 3.0pp
        print("  %s -> a 3.0pp/SD effect is %.4f log-odds per SD"
              % (label, target_lo))
        for v in VECTORS:
            c = VECTOR_COL[v]
            mde_sd = MDE_MULT * res.bse[c] * float(np.std(d[c]))
            n_need = len(d) * (mde_sd / target_lo) ** 2
            print("      %-3s  MDE here %.4f log-odds/SD  ->  n needed for "
                  "3.0pp = %8.0f games" % (v, mde_sd, n_need))
    print("""
VERDICT ON THAT CLAIM: see the numbers above. ~2,500 games is the right ORDER
OF MAGNITUDE for a 3.0pp-per-SD effect under the generous p=0.5 conversion, but
it is only achievable for the vectors whose SE*sd product is small. The honest
AME conversion (mean p(1-p) = %.3f, well below 0.25, because NFL moneylines are
often lopsided and p(1-p) collapses on heavy favourites) makes every requirement
LARGER than the p=0.5 arithmetic suggests.""" % ame)

    print("\n" + THIN)
    print("SHRINKAGE VS THE PRIOR RUN (n=%d -> n=%d)" % (n_prior, len(d)))
    print(THIN)
    ratio = np.sqrt(n_prior / len(d))
    print("  sqrt(%d/%d) = %.3f -- intervals should be ~%.0f%% narrower if the "
          "sample is the only thing that changed."
          % (n_prior, len(d), ratio, 100 * (1 - ratio)))
    prior = {"F": 0.171, "P": 0.055, "C": 0.052, "R": 0.175}
    print("\n  %-3s %12s %12s %10s" % ("vec", "SE prior", "SE now", "ratio"))
    for v in VECTORS:
        se = res.bse[VECTOR_COL[v]]
        print("  %-3s %12.4f %12.4f %10.3f"
              % (v, prior[v], se, se / prior[v]))
    return ame, pw


# ==========================================================================
def main():
    rebuild = "--rebuild" in sys.argv
    print(RULE)
    print("fit_full.py -- PRE-REGISTERED full-sample re-run of the 4-term VAS "
          "model")
    print("one question: was 2019-2025 (n=1812) simply UNDERPOWERED?")
    print(RULE)

    availability_audit()
    t = build_full(rebuild=rebuild)

    m = FIT.eligible(t)
    head("2. FITTED SAMPLE")
    scope = t["season"].between(FIT_LO, FIT_HI)
    print("rows %d-%d with complete lines and a result: %d"
          % (FIT_LO, FIT_HI, int(scope.sum())))
    for label, bad in [
            ("ties (moneyline PUSH)", t["is_tie"]),
            ("hold <= 0 (no-vig price undefined)", ~(t["hold"] > 0)),
            ("F not ready (week 1, no prior game this season)",
             ~t["f_ready"].fillna(False).astype(bool)),
            ("R not ready (thin pace/PROE history) -- r_ok",
             ~t["r_ok"].fillna(False).astype(bool)),
            ("P burn-in (qb_history_thin)",
             t["qb_history_thin"].fillna(1).astype(bool)),
            ("p_qb_z undefined", t["p_qb_z"].isna()),
            ("C null", t["C"].isna()),
            ("R null", t["R"].isna())]:
        print("  drops %4d  %s" % (int((scope & bad).sum()), label))
    d = t[m].reset_index(drop=True)
    print("\nFITTED SAMPLE: n = %d, seasons %d-%d"
          % (len(d), int(d["season"].min()), int(d["season"].max())))
    print("\nper season:")
    print(d.groupby("season").agg(games=("game_id", "size"),
                                  home_win=("home_win", "mean"),
                                  p_mkt=("p_mkt_mult", "mean"),
                                  hold=("hold", "mean")).round(4).to_string())
    print("\nvector scale on the fitted sample:")
    X = d[[VECTOR_COL[v] for v in VECTORS]]
    desc = X.describe().T[["mean", "std", "min", "max"]]
    desc.index = VECTORS
    print(desc.round(4).to_string())
    print("\ncorrelation between vectors:")
    cc = X.corr(); cc.index = VECTORS; cc.columns = VECTORS
    print(cc.round(3).to_string())
    off = logit(d["p_mkt_mult"])
    print("\ncorrelation with the OFFSET logit(p_mkt):")
    for v in VECTORS:
        print("  %-3s %+0.3f" % (v, np.corrcoef(d[VECTOR_COL[v]], off)[0, 1]))

    # ---------------- T1 ----------------
    head("3. T1 -- FULL-SAMPLE FIT (the pre-registered spec, 4 terms, offset pinned)")
    cols = [VECTOR_COL[v] for v in VECTORS]
    res = glm_fit(d, cols, intercept=False, label="full")
    print(res.summary().as_text())
    print("\n" + THIN)
    print("COEFFICIENTS, n = %d, seasons %d-%d" % (len(d), FIT_LO, FIT_HI))
    print(THIN)
    print(coef_table(res, d).round(5).to_string())

    pvals = np.array([res.pvalues[c] for c in cols])
    rej = benjamini_hochberg(pvals, q=0.10)
    print("\nBenjamini-Hochberg at FDR 10%% across the 4 coefficients: %s"
          % ({v: ("SURVIVES" if r else "rejected")
              for v, r in zip(VECTORS, rej)}))

    # side diagnostic: is the offset mis-scaled over 20 seasons?
    print("\n" + THIN)
    print("DIAGNOSTIC (not one of the 10 declared tests): free coefficient on "
          "logit(p_mkt) instead of pinning it to 1")
    print(THIN)
    Xf = pd.DataFrame({"logit_p_mkt": np.asarray(off)}, index=d.index)
    for c in cols:
        Xf[c] = d[c].to_numpy(dtype=float)
    free = sm.GLM(d["home_win"].to_numpy(float), Xf,
                  family=sm.families.Binomial()).fit()
    lo, hi = free.conf_int().loc["logit_p_mkt"]
    print("  free B = %.4f (SE %.4f, 95%% CI [%.3f, %.3f]); is 1.0 inside? %s"
          % (free.params["logit_p_mkt"], free.bse["logit_p_mkt"], lo, hi,
             "YES" if lo <= 1.0 <= hi else "NO"))

    # ---------------- POWER ----------------
    ame, pw = power_report(res, d)

    # ---------------- T2/T3/T4 ----------------
    fl, oos = season_cv(d)
    r_gamma, r_D = oos_significance(oos)

    # ---------------- verdict ----------------
    head("VERDICT")
    sig_in = [v for v in VECTORS if res.pvalues[VECTOR_COL[v]] < 0.05]
    sig_out = [v for v in VECTORS if r_gamma.pvalues["gamma_" + v] < 0.05]
    print("n = %d, seasons %d-%d (prior run: n = 1812, 2019-2025)"
          % (len(d), FIT_LO, FIT_HI))
    print("T1 in-sample significant at 5%%: %s" % (sig_in or "NONE"))
    print("T1 surviving BH at FDR 10%%:     %s"
          % ([v for v, r in zip(VECTORS, rej) if r] or "NONE"))
    print("T2 out-of-sample significant:    %s" % (sig_out or "NONE"))
    print("T3 gamma_D p = %.4f" % r_D.pvalues.iloc[0])

    prior_b = {"F": -0.237, "P": 0.093, "C": -0.085, "R": 0.124}
    prior_se = {"F": 0.171, "P": 0.055, "C": 0.052, "R": 0.175}
    print("\n%-3s %10s %10s | %10s %10s | %9s %9s"
          % ("vec", "B prior", "B now", "SE prior", "SE now", "p prior", "p now"))
    pp = {"F": 0.166, "P": 0.087, "C": 0.102, "R": 0.478}
    for v in VECTORS:
        c = VECTOR_COL[v]
        print("%-3s %+10.4f %+10.4f | %10.4f %10.4f | %9s %9.4f"
              % (v, prior_b[v], res.params[c], prior_se[v], res.bse[c],
                 "~%.3f" % pp[v], res.pvalues[c]))

    out = os.path.join(HERE, "out_full_fit_table.parquet")
    d.to_parquet(out, index=False)
    print("\nfitted sample written to %s (%d x %d)" % (out, *d.shape))


if __name__ == "__main__":
    main()
