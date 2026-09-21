#!/usr/bin/env python3
"""
qb_change.py -- id "qb-change". PRE-REGISTERED test of ONE hypothesis.

===========================================================================
PRE-REGISTRATION -- written and saved BEFORE any of these numbers were run.
Run ONCE as specified. Every test in the battery below is reported, pass or
fail. No test is added after seeing a result; no window, filter or cutoff is
moved after seeing a result.
===========================================================================

HYPOTHESIS
  H1: the market is SLOW to price a quarterback change. The closing line on a
      game where a team starts a different quarterback than it most recently
      started is systematically wrong about that team.
  H0: it is not. The closing spread and the no-vig closing moneyline already
      contain the starter change. (This is the null the 4-term run failed to
      reject: B_P = +0.093, SE .055, p = .087 -- the closest thing to a signal
      in that run, which is why QB is the thing being pushed on here.)

WHY THIS DATA CAN TEST IT, AND THE ONE THING IT CANNOT
  games.csv carries home_qb_id / away_qb_id = the QB who actually started.
  A starter change is therefore observable with NO play-by-play at all, on
  every played game 1999-2025 (100% non-null both columns, verified).
  features_personnel.py already emits, under a strict no-look-ahead contract:
      qb_new_starter_{home,away}   1 if this team's starter differs from the
                                   starter in that team's most recent PRIOR
                                   game (carries across the offseason)
      qb_change_delta_{home,away}  shrunk EPA/dropback of the new starter
                                   minus shrunk EPA/dropback of the QB that
                                   team most recently started, both as-of,
                                   both from prior plays only
  out_full_pers.parquet holds these for 1999-2025 (7,276 games). REUSED, not
  rebuilt.

  WHAT CANNOT BE DONE, STATED UP FRONT: this data has no line timestamps and
  no opening line (initial_lines.csv exists but is 2021 only, 272 games,
  spread/total only -- too narrow to carry a season-split OOS test, so it is
  not used). Therefore I CANNOT cleanly separate "the change was known well in
  advance" from "the change broke late". The ONE split the data does support
  is announcement HORIZON by calendar:
      (a) WEEK 1 change  = the change happened over the OFFSEASON. Known for
          weeks to months. The market has had maximal time.
      (b) WEEK >=2 change = an in-season change. Known days at most.
  Within (b) I cannot tell a Wednesday depth-chart move from a Sunday-morning
  inactive. I am not going to guess. (b) is the upper bound on how much
  surprise the data can isolate, and it is reported as such.

ORIENTATION / SIGN CONVENTION
  nflverse spread_line = points the HOME team is favoured by.
  chg = +1 if ONLY the home team changed starter
        -1 if ONLY the away team changed starter
         0 if neither changed, or BOTH changed (ambiguous direction)
  A POSITIVE coefficient on chg means the team with the changed QB beats its
  own closing number -> BACK it. NEGATIVE -> FADE it. Two-sided throughout;
  no direction is pre-specified, because the prior does not give one.

RESPONSE VARIABLES (two, tested separately, as instructed)
  SPREAD : ats_home = result - spread_line   (home margin against the close;
           >0 = home covered). Mean-zero under H0 after an intercept.
  MONEYLINE : home_win = 1[result > 0], ties dropped (a ML tie is a PUSH).
           Offset = logit(p_mkt), p_mkt = multiplicative de-vig of the closing
           two-way moneyline, home side -- byte-identical to fit.py's choice.
           B = 0 is exactly "the market already knows this".

SAMPLE FILTERS (fixed here, before running)
  SPREAD sample  : played games 1999-2025, spread_line non-null, both
                   qb_prior_starter_known (so week 1 of 1999 is excluded --
                   no prior start exists).
  MONEYLINE sample: the above AND both moneylines non-null AND hold > 0 AND
                   not a tie. (ML coverage starts 2006/2007 in games.csv; the
                   bound is set by availability, not by result.)
  CONTINUOUS tests additionally require ~qb_history_thin and no QB-quality
                   fallback on either side (no prior dropbacks = the delta is
                   a made-up number).

THE BATTERY -- exactly these, run once, all reported
  T1  spread, binary   : ats_home ~ 1 + chg                    (OLS, SE clustered by season)
  T2  moneyline, binary: home_win ~ 1 + chg, offset logit(p_mkt)   (GLM binomial)
  T3  spread, split    : ats_home ~ 1 + chg_wk1 + chg_in         (2 coefficients)
  T4  moneyline, split : same split, offset GLM                  (2 coefficients)
  T5  spread, continuous   : ats_home ~ 1 + qb_change_delta_diff
  T6  moneyline, continuous: home_win ~ 1 + qb_change_delta_diff, offset GLM
  T7  OOS spread    : expanding season window, train seasons < S, test S,
                      S in 2005..2025. Pool held-out games, refit ONE scale
                      gamma on the held-out contribution. H0: gamma = 0.
  T8  OOS moneyline : same, S in 2012..2025 (ML starts 2006/07; 2007-2011 is
                      the smallest training block tolerated).
  Multiplicity: Benjamini-Hochberg at FDR 10% across the in-sample family,
  matching what the existing harness already does to itself.

THRESHOLD
  Two-sided p < 0.05 on the pre-registered coefficient, AND the out-of-sample
  gamma significantly > 0. Both, or there is no edge. An in-sample p alone is
  not a finding.

POWER -- reported, not assumed
  The script prints, for every test, the smallest |effect| it had 80% power to
  detect at alpha = .05 two-sided (= 2.802 * SE). An insignificant result on a
  test whose 80%-power floor is above any economically useful effect is
  reported as UNKNOWN, not as "no".

WHAT WOULD MAKE ME SAY "NO EDGE"
  Coefficients consistent with zero AND an 80%-power floor below ~1.0 point of
  spread (roughly the 3% ATS win-rate swing that clears the -110 breakeven).
  That is a real null, not an underpowered shrug, and it is a complete answer.
===========================================================================
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from load import load_games
from fit import american_to_prob, logit, sigmoid, benjamini_hochberg

HERE = os.path.dirname(os.path.abspath(__file__))
warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)

RULE = "=" * 98
THIN = "-" * 98
POW80 = 2.802          # z_{.975} + z_{.80}

TESTS = []             # every test run, appended as it happens


def head(t):
    print("\n" + RULE); print(t); print(RULE)


def record(tid, family, name, b, se, p, n_eff, units, extra=""):
    TESTS.append({"test": tid, "family": family, "term": name, "coef": b,
                  "SE": se, "p": p, "n_eff": n_eff,
                  "80%%-power floor": POW80 * se, "units": units,
                  "sig@5%": "YES" if p < 0.05 else "no", "note": extra})


# ==========================================================================
# 1. sample
# ==========================================================================
def build():
    head("1. SAMPLE (reusing out_full_pers.parquet -- nothing rebuilt)")
    P = pd.read_parquet(os.path.join(HERE, "out_full_pers.parquet"))
    g = load_games(played_only=True)
    g = g[g["season"].between(1999, 2025)]

    keep = ["game_id", "qb_new_starter_home", "qb_new_starter_away",
            "qb_change_delta_home", "qb_change_delta_away",
            "qb_change_delta_diff", "qb_prior_starter_known_home",
            "qb_prior_starter_known_away", "qb_history_thin",
            "qb_fallback_home", "qb_fallback_away",
            "qb_delta_home", "qb_delta_away"]
    t = g.merge(P[keep], on="game_id", how="inner", validate="1:1")
    print("played games 1999-2025 joined to the personnel frame: %d" % len(t))

    t = t[t["spread_line"].notna()
          & (t["qb_prior_starter_known_home"] == 1)
          & (t["qb_prior_starter_known_away"] == 1)].copy()
    print("with a closing spread and BOTH prior starters known: %d "
          "(seasons %d-%d)" % (len(t), t.season.min(), t.season.max()))

    h, a = t["qb_new_starter_home"].astype(int), t["qb_new_starter_away"].astype(int)
    t["chg"] = np.where(h & ~a.astype(bool), 1,
                        np.where(a & ~h.astype(bool), -1, 0))
    t["both_changed"] = ((h == 1) & (a == 1)).astype(int)
    t["chg_wk1"] = np.where(t["week"] == 1, t["chg"], 0)
    t["chg_in"] = np.where(t["week"] >= 2, t["chg"], 0)

    t["ats_home"] = t["result"] - t["spread_line"]
    t["home_win"] = (t["result"] > 0).astype(int)
    qh, qa = american_to_prob(t["home_moneyline"]), american_to_prob(t["away_moneyline"])
    t["hold"] = qh + qa - 1.0
    t["p_mkt"] = qh / (qh + qa)

    print("\nSPREAD sample  n = %d" % len(t))
    print("  exactly-one-team changed : %d  (%.1f%% of games)"
          % (int((t.chg != 0).sum()), 100 * (t.chg != 0).mean()))
    print("    of which week 1 (offseason change, known months ahead) : %d"
          % int((t.chg_wk1 != 0).sum()))
    print("    of which week >=2 (in-season change, days at most)     : %d"
          % int((t.chg_in != 0).sum()))
    print("  BOTH teams changed (direction ambiguous -> coded 0)      : %d"
          % int(t.both_changed.sum()))

    ml = t[t["home_moneyline"].notna() & t["away_moneyline"].notna()
           & (t["hold"] > 0) & (t["result"] != 0)].copy()
    print("\nMONEYLINE sample n = %d (seasons %d-%d; ties and hold<=0 dropped)"
          % (len(ml), ml.season.min(), ml.season.max()))
    print("  exactly-one changed: %d   (wk1 %d / wk>=2 %d)"
          % (int((ml.chg != 0).sum()), int((ml.chg_wk1 != 0).sum()),
             int((ml.chg_in != 0).sum())))

    ok = (t["qb_history_thin"] == 0) & (t["qb_fallback_home"] == 0) \
        & (t["qb_fallback_away"] == 0)
    cont = t[ok].copy()
    cont_ml = ml[(ml["qb_history_thin"] == 0) & (ml["qb_fallback_home"] == 0)
                 & (ml["qb_fallback_away"] == 0)].copy()
    print("\nCONTINUOUS sample (quality estimates real, no fallback): "
          "spread n = %d (%d-%d), moneyline n = %d"
          % (len(cont), cont.season.min(), cont.season.max(), len(cont_ml)))
    print("  qb_change_delta_diff  sd = %.4f EPA/dropback, non-zero on %d rows"
          % (cont.qb_change_delta_diff.std(),
             int((cont.qb_change_delta_diff != 0).sum())))
    return t, ml, cont, cont_ml


# ==========================================================================
# 2. descriptives -- NOT tests, no p-value is read off these
# ==========================================================================
def descriptives(t, ml):
    head("2. DESCRIPTIVE -- what backing the changed-QB team actually did")
    print("(these are counts, not tests; the tests are section 3)")
    c = t[t.chg != 0].copy()
    c["ats_chg"] = c["chg"] * c["ats_home"]          # changed team vs its own close
    for lab, sub in (("ALL change games", c),
                     ("week 1 (offseason)", c[c.week == 1]),
                     ("week >=2 (in-season)", c[c.week >= 2])):
        w = (sub.ats_chg > 0).sum(); l = (sub.ats_chg < 0).sum()
        p = (sub.ats_chg == 0).sum()
        rate = w / max(w + l, 1)
        print("  %-22s n=%4d  ATS %4d-%-4d-%-2d = %.3f   mean cover margin "
              "%+.3f pts" % (lab, len(sub), w, l, p, rate, sub.ats_chg.mean()))
    print("  breakeven at -110 is 0.5238. A 1.0-point spread edge is roughly a "
          "0.03 swing in that rate.")

    m = ml[ml.chg != 0].copy()
    m["won"] = np.where(m.chg == 1, m.home_win, 1 - m.home_win)
    m["price"] = np.where(m.chg == 1, m.home_moneyline, m.away_moneyline)
    ret = np.where(m.won == 1,
                   np.where(m.price > 0, m.price / 100.0, 100.0 / -m.price), -1.0)
    print("\n  MONEYLINE, flat 1u on every changed-QB team: n=%d  record %d-%d  "
          "ROI %+.3f u/bet" % (len(m), int(m.won.sum()), int((1 - m.won).sum()),
                               ret.mean()))
    print("  (ROI is descriptive only -- its SE is %.3f, so it is not a test.)"
          % (ret.std() / np.sqrt(len(ret))))


# ==========================================================================
# 3. the pre-registered in-sample battery
# ==========================================================================
def ols_c(d, cols, y="ats_home"):
    X = sm.add_constant(d[cols].astype(float))
    return sm.OLS(d[y].astype(float), X).fit(
        cov_type="cluster", cov_kwds={"groups": d["season"]})


def glm_o(d, cols):
    X = sm.add_constant(d[cols].astype(float))
    return sm.GLM(d["home_win"].astype(float), X,
                  family=sm.families.Binomial(),
                  offset=logit(d["p_mkt"].to_numpy())).fit()


def show(res, terms, tid, family, units, n_eff_map):
    ci = res.conf_int(); ci.columns = ["lo", "hi"]
    rows = []
    for tm in terms:
        b, se, p = res.params[tm], res.bse[tm], res.pvalues[tm]
        rows.append({"term": tm, "B": b, "SE": se, "z/t": res.tvalues[tm],
                     "p": p, "ci_lo": ci.loc[tm, "lo"], "ci_hi": ci.loc[tm, "hi"],
                     "n_eff": n_eff_map[tm], "80%-power floor": POW80 * se,
                     "sig@5%": "YES" if p < 0.05 else "no"})
        record(tid, family, tm, b, se, p, n_eff_map[tm], units)
    print(pd.DataFrame(rows).set_index("term").round(5).to_string())
    print("  intercept (nuisance, absorbs the constant home ATS/ML tilt): "
          "%+.4f (SE %.4f, p %.3f)"
          % (res.params["const"], res.bse["const"], res.pvalues["const"]))


def battery(t, ml, cont, cont_ml):
    head("3. THE PRE-REGISTERED IN-SAMPLE BATTERY")

    print(THIN); print("T1  SPREAD, BINARY   ats_home ~ 1 + chg   "
                       "(OLS, SE clustered by season)"); print(THIN)
    print("  B is in POINTS. B>0 = the changed-QB team beats its own closing "
          "spread by B points.")
    r1 = ols_c(t, ["chg"])
    show(r1, ["chg"], "T1", "spread", "points",
         {"chg": int((t.chg != 0).sum())})

    print("\n" + THIN); print("T2  MONEYLINE, BINARY   home_win ~ 1 + chg, "
                              "offset = logit(p_mkt)"); print(THIN)
    print("  B is in LOG-ODDS on the changed team. B=0 is exactly 'the no-vig "
          "close already knows'.")
    r2 = glm_o(ml, ["chg"])
    show(r2, ["chg"], "T2", "moneyline", "log-odds",
         {"chg": int((ml.chg != 0).sum())})

    print("\n" + THIN)
    print("T3  SPREAD, SPLIT BY ANNOUNCEMENT HORIZON  "
          "ats_home ~ 1 + chg_wk1 + chg_in")
    print(THIN)
    print("  chg_wk1 = offseason change (market had months). chg_in = in-season "
          "change (days).")
    print("  If the market is SLOW, the effect lives in chg_in and not in "
          "chg_wk1. That is the whole point of the split.")
    r3 = ols_c(t, ["chg_wk1", "chg_in"])
    show(r3, ["chg_wk1", "chg_in"], "T3", "spread", "points",
         {"chg_wk1": int((t.chg_wk1 != 0).sum()),
          "chg_in": int((t.chg_in != 0).sum())})

    print("\n" + THIN); print("T4  MONEYLINE, SPLIT BY HORIZON"); print(THIN)
    r4 = glm_o(ml, ["chg_wk1", "chg_in"])
    show(r4, ["chg_wk1", "chg_in"], "T4", "moneyline", "log-odds",
         {"chg_wk1": int((ml.chg_wk1 != 0).sum()),
          "chg_in": int((ml.chg_in != 0).sum())})

    print("\n" + THIN)
    print("T5  SPREAD, CONTINUOUS   ats_home ~ 1 + qb_change_delta_diff")
    print(THIN)
    print("  The regressor is (new starter's as-of EPA/dropback) minus (the QB "
          "the team most recently started), home minus away. 0 when nobody "
          "changed. B is POINTS per 1.0 EPA/dropback of QB upgrade -- an "
          "enormous unit, so B*sd is the readable number.")
    r5 = ols_c(cont, ["qb_change_delta_diff"])
    show(r5, ["qb_change_delta_diff"], "T5", "spread", "pts per EPA/db",
         {"qb_change_delta_diff": int((cont.qb_change_delta_diff != 0).sum())})
    sd = cont.qb_change_delta_diff.std()
    print("  per 1 sd (%.4f EPA/db): %+.4f pts, 80%%-power floor %.4f pts"
          % (sd, r5.params["qb_change_delta_diff"] * sd,
             POW80 * r5.bse["qb_change_delta_diff"] * sd))

    print("\n" + THIN); print("T6  MONEYLINE, CONTINUOUS   offset GLM on "
                              "qb_change_delta_diff"); print(THIN)
    r6 = glm_o(cont_ml, ["qb_change_delta_diff"])
    show(r6, ["qb_change_delta_diff"], "T6", "moneyline", "log-odds per EPA/db",
         {"qb_change_delta_diff": int((cont_ml.qb_change_delta_diff != 0).sum())})
    sd2 = cont_ml.qb_change_delta_diff.std()
    print("  per 1 sd (%.4f EPA/db): %+.4f log-odds, 80%%-power floor %.4f"
          % (sd2, r6.params["qb_change_delta_diff"] * sd2,
             POW80 * r6.bse["qb_change_delta_diff"] * sd2))
    return r1, r2, r3, r4, r5, r6


# ==========================================================================
# 4. out of sample -- season-wise expanding window ONLY
# ==========================================================================
def oos_spread(t, cont):
    head("4. OUT OF SAMPLE -- SPREAD (expanding season window; never k-fold)")
    print("Train on every season STRICTLY BEFORE the test season, predict the "
          "test season, pool the held-out games, then refit ONE scale gamma on "
          "the pooled held-out contribution.\n"
          "  gamma = 1  the past coefficient transferred perfectly\n"
          "  gamma = 0  it carries nothing out of sample   <- the null\n"
          "  gamma < 0  it points the WRONG way in the future\n")
    out = {}
    for lab, frame, col in (("T7a binary  chg", t, "chg"),
                            ("T7b continuous delta", cont, "qb_change_delta_diff")):
        pieces = []
        rows = []
        for s in range(2005, 2026):
            tr, te = frame[frame.season < s], frame[frame.season == s]
            if len(tr) < 500 or len(te) == 0:
                continue
            r = ols_c(tr, [col])
            b = r.params[col]
            piece = te[["game_id", "season", "ats_home"]].copy()
            piece["contrib"] = b * te[col].to_numpy()
            pieces.append(piece)
            rows.append({"test": s, "n_train": len(tr), "n_test": len(te),
                         "B_train": b, "SE_train": r.bse[col]})
        fl = pd.DataFrame(rows).set_index("test")
        print("\n%s -- per-fold coefficient trained on prior seasons only:" % lab)
        print(fl.round(4).to_string())
        pos = fl.B_train.gt(0).all(); neg = fl.B_train.lt(0).all()
        print("  sign across %d folds: %s" % (len(fl), "all +" if pos else
                                              ("all -" if neg else "FLIPS")))
        o = pd.concat(pieces, ignore_index=True)
        X = sm.add_constant(pd.DataFrame({"gamma": o["contrib"].to_numpy()}))
        rg = sm.OLS(o["ats_home"].astype(float), X).fit(
            cov_type="cluster", cov_kwds={"groups": o["season"]})
        lo, hi = rg.conf_int().loc["gamma"]
        print("  POOLED HELD-OUT n = %d (%d-%d)"
              % (len(o), o.season.min(), o.season.max()))
        print("  gamma = %+.4f  (SE %.4f, t %+.2f, p %.4f, 95%% CI "
              "[%+.3f, %+.3f])" % (rg.params["gamma"], rg.bse["gamma"],
                                   rg.tvalues["gamma"], rg.pvalues["gamma"], lo, hi))
        print("  -> %s" % ("carries real out-of-sample information"
                           if rg.pvalues["gamma"] < 0.05 else
                           "NOT distinguishable from zero out of sample"))
        record("T7", "spread-OOS", "gamma(%s)" % col, rg.params["gamma"],
               rg.bse["gamma"], rg.pvalues["gamma"], len(o), "scale")
        out[lab] = rg
    return out


def oos_ml(ml, cont_ml):
    head("5. OUT OF SAMPLE -- MONEYLINE (expanding season window)")
    out = {}
    for lab, frame, col in (("T8a binary  chg", ml, "chg"),
                            ("T8b continuous delta", cont_ml, "qb_change_delta_diff")):
        pieces, rows = [], []
        for s in range(2012, 2026):
            tr, te = frame[frame.season < s], frame[frame.season == s]
            if len(tr) < 500 or len(te) == 0:
                continue
            r = glm_o(tr, [col])
            b = r.params[col]
            piece = te[["game_id", "season", "home_win", "p_mkt"]].copy()
            piece["contrib"] = b * te[col].to_numpy()
            pieces.append(piece)
            rows.append({"test": s, "n_train": len(tr), "n_test": len(te),
                         "B_train": b, "SE_train": r.bse[col]})
        fl = pd.DataFrame(rows).set_index("test")
        print("\n%s -- per-fold coefficient trained on prior seasons only:" % lab)
        print(fl.round(4).to_string())
        pos = fl.B_train.gt(0).all(); neg = fl.B_train.lt(0).all()
        print("  sign across %d folds: %s" % (len(fl), "all +" if pos else
                                              ("all -" if neg else "FLIPS")))
        o = pd.concat(pieces, ignore_index=True)
        X = pd.DataFrame({"gamma": o["contrib"].to_numpy()})
        rg = sm.GLM(o["home_win"].astype(float), X,
                    family=sm.families.Binomial(),
                    offset=logit(o["p_mkt"].to_numpy())).fit()
        lo, hi = rg.conf_int().iloc[0]
        print("  POOLED HELD-OUT n = %d (%d-%d)"
              % (len(o), o.season.min(), o.season.max()))
        print("  gamma = %+.4f  (SE %.4f, z %+.2f, p %.4f, 95%% CI "
              "[%+.3f, %+.3f])" % (rg.params.iloc[0], rg.bse.iloc[0],
                                   rg.tvalues.iloc[0], rg.pvalues.iloc[0], lo, hi))
        print("  -> %s" % ("carries real out-of-sample information"
                           if rg.pvalues.iloc[0] < 0.05 else
                           "NOT distinguishable from zero out of sample"))
        record("T8", "ml-OOS", "gamma(%s)" % col, rg.params.iloc[0],
               rg.bse.iloc[0], rg.pvalues.iloc[0], len(o), "scale")
        out[lab] = rg
    return out


# ==========================================================================
# 6. accounting
# ==========================================================================
def accounting():
    head("6. EVERY TEST RUN -- COMPLETE, INCLUDING THE FAILURES")
    T = pd.DataFrame(TESTS)
    print(T.round(5).to_string(index=False))
    print("\nTOTAL COEFFICIENT TESTS RUN: %d. That is the whole count; nothing "
          "below was run and dropped." % len(T))

    ins = T[~T.family.str.contains("OOS")]
    rej = benjamini_hochberg(ins["p"].to_numpy(), q=0.10)
    print("\nBenjamini-Hochberg at FDR 10%% across the %d in-sample tests "
          "(the harness already holds itself to this):" % len(ins))
    bh = ins[["test", "term", "p"]].copy()
    bh["BH q=10%"] = ["SURVIVES" if r else "rejected" for r in rej]
    bh["Bonferroni"] = ["SURVIVES" if p < 0.05 / len(ins) else "rejected"
                        for p in ins["p"]]
    print(bh.round(5).to_string(index=False))
    return T


def main():
    print(RULE)
    print('qb-change  |  PRE-REGISTERED, RUN ONCE  |  "the market is slow to '
          'price a QB change"')
    print(RULE)
    print(__doc__[__doc__.index("HYPOTHESIS"):__doc__.index("THE BATTERY")])

    t, ml, cont, cont_ml = build()
    descriptives(t, ml)
    battery(t, ml, cont, cont_ml)
    oos_spread(t, cont)
    oos_ml(ml, cont_ml)
    T = accounting()
    T.to_csv(os.path.join(HERE, "out_qb_change_tests.csv"), index=False)
    print("\ntest ledger written to tools/backtest/out_qb_change_tests.csv")


if __name__ == "__main__":
    main()
