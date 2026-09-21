#!/usr/bin/env python3
"""
qb_change_robustness.py -- POST-HOC. These are NOT pre-registered.

They were written AFTER seeing that T5 (spread ~ qb_change_delta_diff) cleared
both pre-registered bars. They are adversarial by design: every one is an
attempt to KILL T5, not to confirm it. They still COUNT as tests and every one
is reported, whichever way it lands. Running these raises the total test count
from 12 to 17 (R1 contributes two coefficients) and the multiplicity correction is recomputed over all 17.

R1  CONTROL. ats_home ~ 1 + chg + qb_change_delta_diff. T1 found a -0.70 pt
    penalty on ANY changed-QB team. If T5 is just that penalty leaking through
    a correlated regressor, T5's coefficient collapses when the binary term is
    in the model. H0: the delta coefficient goes to zero.
R2  TAILS. Refit T5 after dropping games whose |qb_change_delta_diff| is above
    the 99th percentile of the non-zero values. If a handful of extreme QB
    swaps carry the whole thing, it is not a tradable regularity.
R3  ECONOMIC, OUT OF SAMPLE, THRESHOLD-FREE. Take the T7b expanding-window
    model exactly as pre-registered. On each held-out game with a QB change,
    bet the side the model favours -- no confidence threshold, no filter, so
    nothing can be tuned. Test the ATS win rate against the -110 breakeven
    0.5238 (one-sided binomial is what a bettor cares about; the two-sided p
    is reported too).
R4  IS IT ABOUT THE *CHANGE* AT ALL? Swap qb_change_delta_diff for
    qb_delta_diff -- the LEVEL of QB quality (fit.py's p_qb), which the market
    unambiguously prices. Same response, same sample. If the level shows the
    same effect, then T5 is a QB-quality finding, not a QB-CHANGE finding, and
    the hypothesis under test was never the thing being measured.
"""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, statsmodels.api as sm
from scipy import stats
from qb_change import build, ols_c, glm_o, POW80, RULE, THIN, head
from fit import benjamini_hochberg

warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)
HERE = os.path.dirname(os.path.abspath(__file__))
R = []


def rec(tid, term, b, se, p, n, units, note=""):
    R.append({"test": tid, "family": "post-hoc", "term": term, "coef": b,
              "SE": se, "p": p, "n_eff": n, "80%-power floor": POW80 * se,
              "units": units, "sig@5%": "YES" if p < 0.05 else "no", "note": note})


def main():
    print(RULE); print("POST-HOC ROBUSTNESS -- adversarial checks on T5"); print(RULE)
    t, ml, cont, cont_ml = build()
    D = "qb_change_delta_diff"

    head("R1  CONTROL -- does T5 survive the binary change penalty?")
    print("corr(chg, %s) on the continuous sample = %.4f"
          % (D, np.corrcoef(cont["chg"], cont[D])[0, 1]))
    r = ols_c(cont, ["chg", D])
    for tm in ["chg", D]:
        print("  %-22s B %+8.4f  SE %.4f  t %+.2f  p %.4f  80%%-floor %.4f"
              % (tm, r.params[tm], r.bse[tm], r.tvalues[tm], r.pvalues[tm],
                 POW80 * r.bse[tm]))
        rec("R1", tm, r.params[tm], r.bse[tm], r.pvalues[tm],
            int((cont[tm] != 0).sum()), "points", "joint model")
    print("  T5 alone was B=+7.7174 (p .0085). Joint: B=%+.4f (p %.4f) -> %s"
          % (r.params[D], r.pvalues[D],
             "SURVIVES the control" if r.pvalues[D] < 0.05 else "COLLAPSES"))

    head("R2  TAILS -- is it a handful of extreme QB swaps?")
    nz = cont.loc[cont[D] != 0, D].abs()
    cut = nz.quantile(0.99)
    trim = cont[cont[D].abs() <= cut]
    print("  99th pct of |delta| among change games = %.4f; dropping %d games"
          % (cut, len(cont) - len(trim)))
    r2 = ols_c(trim, [D])
    print("  trimmed B %+8.4f  SE %.4f  t %+.2f  p %.4f  (untrimmed +7.7174, p .0085)"
          % (r2.params[D], r2.bse[D], r2.tvalues[D], r2.pvalues[D]))
    rec("R2", D + " (99% trim)", r2.params[D], r2.bse[D], r2.pvalues[D],
        int((trim[D] != 0).sum()), "points", "top 1% |delta| dropped")

    head("R3  ECONOMIC, OUT OF SAMPLE, THRESHOLD-FREE")
    print("T7b model, expanding season window, bet EVERY held-out change game "
          "on the side the model favours. No threshold, so nothing is tunable.")
    picks = []
    for s in range(2005, 2026):
        tr, te = cont[cont.season < s], cont[cont.season == s]
        if len(tr) < 500 or len(te) == 0:
            continue
        b = ols_c(tr, [D]).params[D]
        te = te[te[D] != 0].copy()
        te["contrib"] = b * te[D].to_numpy()
        te = te[te["contrib"] != 0]
        # side the model favours: home if contrib > 0
        te["won"] = np.where(te["contrib"] > 0, te["ats_home"] > 0,
                             te["ats_home"] < 0)
        te["push"] = te["ats_home"] == 0
        picks.append(te[["season", "won", "push", "contrib", "ats_home"]])
    P = pd.concat(picks, ignore_index=True)
    dec = P[~P.push]
    w, n = int(dec.won.sum()), len(dec)
    rate = w / n
    pv2 = stats.binomtest(w, n, 0.5238).pvalue
    pv1 = stats.binomtest(w, n, 0.5238, alternative="greater").pvalue
    se = np.sqrt(0.5238 * (1 - 0.5238) / n)
    print("  held-out change games bet: %d (%d pushes excluded), seasons %d-%d"
          % (n, int(P.push.sum()), P.season.min(), P.season.max()))
    print("  ATS record %d-%d = %.4f   vs -110 breakeven 0.5238"
          % (w, n - w, rate))
    print("  edge %+.4f  (SE %.4f)  two-sided p %.4f  one-sided p %.4f"
          % (rate - 0.5238, se, pv2, pv1))
    roi = rate * (100 / 110.0) - (1 - rate)
    print("  flat -110 ROI %+.4f u/bet over %d bets" % (roi, n))
    print("  80%% power floor on the win rate: %+.4f (i.e. %.4f)"
          % (POW80 * se, 0.5238 + POW80 * se))
    print("  mean held-out cover margin on the picked side: %+.3f pts"
          % np.where(dec.contrib > 0, dec.ats_home, -dec.ats_home).mean())
    rec("R3", "OOS ATS win rate vs 0.5238", rate - 0.5238, se, pv2, n,
        "win-rate", "threshold-free, expanding window")

    head("R4  IS IT THE CHANGE, OR JUST QB QUALITY?")
    print("Same response, same sample, LEVEL instead of CHANGE.")
    cont = cont.assign(qb_delta_diff=cont["qb_delta_home"] - cont["qb_delta_away"])
    r4 = ols_c(cont, ["qb_delta_diff"])
    print("  qb_delta_diff (LEVEL) B %+8.4f  SE %.4f  t %+.2f  p %.4f  "
          "sd %.4f -> %+.4f pts per sd"
          % (r4.params["qb_delta_diff"], r4.bse["qb_delta_diff"],
             r4.tvalues["qb_delta_diff"], r4.pvalues["qb_delta_diff"],
             cont.qb_delta_diff.std(),
             r4.params["qb_delta_diff"] * cont.qb_delta_diff.std()))
    rec("R4", "qb_delta_diff (LEVEL)", r4.params["qb_delta_diff"],
        r4.bse["qb_delta_diff"], r4.pvalues["qb_delta_diff"],
        int((cont.qb_delta_diff != 0).sum()), "pts per EPA/db", "level not change")
    print("  -> %s" % ("the LEVEL is also significant: T5 is not specific to a "
                       "CHANGE, and the hypothesis is not what was measured"
                       if r4.pvalues["qb_delta_diff"] < 0.05 else
                       "the LEVEL is NOT significant while the CHANGE is: the "
                       "effect is specific to the change, which is the "
                       "hypothesis under test"))

    head("R5/R6  THE LEVEL, OUT OF SAMPLE -- because R4 made it the live question")
    print("R4 is post-hoc and in-sample. Reporting it without an out-of-sample")
    print("check would be exactly the half-reporting these rules forbid. Same")
    print("expanding season window as T7, same threshold-free bet rule as R3.")
    L = "qb_delta_diff"
    pieces, rows, picks = [], [], []
    for s_ in range(2005, 2026):
        tr, te = cont[cont.season < s_], cont[cont.season == s_]
        if len(tr) < 500 or len(te) == 0:
            continue
        b = ols_c(tr, [L]).params[L]
        rows.append({"test": s_, "n_train": len(tr), "n_test": len(te), "B_train": b})
        pc = te[["game_id", "season", "ats_home"]].copy()
        pc["contrib"] = b * te[L].to_numpy()
        pieces.append(pc)
    fl = pd.DataFrame(rows).set_index("test")
    print("\n  per-fold trained coefficient: min %+.3f max %+.3f, sign %s (%d folds)"
          % (fl.B_train.min(), fl.B_train.max(),
             "all +" if fl.B_train.gt(0).all() else
             ("all -" if fl.B_train.lt(0).all() else "FLIPS"), len(fl)))
    o = pd.concat(pieces, ignore_index=True)
    X = sm.add_constant(pd.DataFrame({"gamma": o["contrib"].to_numpy()}))
    rg = sm.OLS(o["ats_home"].astype(float), X).fit(
        cov_type="cluster", cov_kwds={"groups": o["season"]})
    lo, hi = rg.conf_int().loc["gamma"]
    print("  R5  pooled held-out n=%d (%d-%d)  gamma %+.4f (SE %.4f, t %+.2f, "
          "p %.4f, CI [%+.3f, %+.3f])"
          % (len(o), o.season.min(), o.season.max(), rg.params["gamma"],
             rg.bse["gamma"], rg.tvalues["gamma"], rg.pvalues["gamma"], lo, hi))
    rec("R5", "gamma(qb_delta_diff LEVEL)", rg.params["gamma"], rg.bse["gamma"],
        rg.pvalues["gamma"], len(o), "scale", "OOS, post-hoc")
    d2 = o[o.ats_home != 0].copy()
    d2["won"] = np.where(d2.contrib > 0, d2.ats_home > 0, d2.ats_home < 0)
    w2, n2 = int(d2.won.sum()), len(d2)
    rate2 = w2 / n2
    se2 = np.sqrt(0.5238 * (1 - 0.5238) / n2)
    pv = stats.binomtest(w2, n2, 0.5238).pvalue
    roi2 = rate2 * (100 / 110.0) - (1 - rate2)
    print("  R6  threshold-free OOS bet on the level: %d-%d = %.4f vs 0.5238, "
          "ROI %+.4f u/bet over %d bets, two-sided p %.4f"
          % (w2, n2 - w2, rate2, roi2, n2, pv))
    print("      mean held-out cover margin on the picked side: %+.3f pts "
          "(need about +1.1 to clear -110)"
          % np.where(d2.contrib > 0, d2.ats_home, -d2.ats_home).mean())
    print("      80%% power floor on this win rate: %.4f" % (0.5238 + POW80 * se2))
    rec("R6", "OOS ATS win rate, LEVEL vs 0.5238", rate2 - 0.5238, se2, pv, n2,
        "win-rate", "threshold-free, post-hoc")

    head("FULL LEDGER -- every test run, pre-registered + post-hoc")
    pre = pd.read_csv(os.path.join(HERE, "out_qb_change_tests.csv"))
    pre = pre.rename(columns={"80%%-power floor": "80%-power floor"})
    allT = pd.concat([pre, pd.DataFrame(R)], ignore_index=True)
    print(allT.round(5).to_string(index=False))
    rej = benjamini_hochberg(allT["p"].to_numpy(), q=0.10)
    allT["BH_q10_all"] = ["SURVIVES" if x else "rejected" for x in rej]
    print("\nBenjamini-Hochberg at FDR 10%% over ALL %d tests run:" % len(allT))
    print(allT[["test", "term", "p", "BH_q10_all"]]
          .sort_values("p").round(5).to_string(index=False))
    allT.to_csv(os.path.join(HERE, "out_qb_change_tests_all.csv"), index=False)
    print("\nfull ledger -> tools/backtest/out_qb_change_tests_all.csv")


if __name__ == "__main__":
    main()
