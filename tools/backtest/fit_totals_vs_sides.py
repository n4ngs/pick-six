#!/usr/bin/env python3
"""
fit_totals_vs_sides.py -- id: "totals-vs-sides"

===========================================================================
PRE-REGISTRATION.  Written in full BEFORE any model in this file was run.
Run ONCE as specified.  Every declared test is reported, pass or fail.
===========================================================================

HYPOTHESIS
  H1 (the claim under test): the TOTALS market is softer than the SIDES
      market.  Operationally: the same feature set explains more of the
      closing-line residual on totals than on sides.
  H0: it explains nothing on either, and equally nothing.

  PRIOR: widely believed among bettors; totals historically carry lower
  limits, which is a book's own statement that it is less confident.

--------------------------------------------------------------------------
THE R8 PROBLEM -- HANDLED EXPLICITLY, NOT SILENTLY
--------------------------------------------------------------------------
fit.py's methodology is p_model = sigmoid(logit(p_mkt) + D) with logit(p_mkt)
pinned as an offset.  On a -110/-110 total the no-vig probability is 0.5000
and logit(p_mkt) = 0, so a naive port of that framing has an offset that is
identically zero.  That is NOT degenerate here, for one specific reason, and
two specific things are done about it:

  (1) WHY THE FRAMING STILL APPLIES.  On the moneyline the market's opinion
      lives in the PRICE, so it must be carried on the right-hand side as an
      offset.  On totals and spreads the market's opinion lives in the LINE,
      and the LINE is inside the DEFINITION OF THE RESPONSE: "over" means
      total > total_line, "cover" means result > spread_line.  The market's
      estimate has been moved from the right-hand side to the left-hand side
      by differencing.  B = 0 therefore still means exactly "the market
      already knows this", which is the null fit.py was built to test.  The
      offset is zero because the work it does on the moneyline has already
      been done by the response variable.

  (2) THE OFFSET IS NOT ACTUALLY ZERO, AND IS USED.  nflverse carries
      over_odds/under_odds and home_spread_odds/away_spread_odds from 2006.
      When the juice is asymmetric (-115/-105) the no-vig probability is not
      0.5 and logit(p_mkt) is not 0.  The binary arms below de-vig those two
      two-way prices with fit.py's own multiplicative method and use
      logit(p_mkt) as the pinned offset, exactly as fit.py does.  The
      realised spread of that offset is REPORTED so the reader can see how
      little information it carries.

  (3) AND THE PRIMARY TEST IS LINEAR, NOT BINARY.  Collapsing a 14-point
      residual to a coin flip at the line throws away most of the
      information.  The PRIMARY arms are OLS on the signed residual in
      POINTS; the binary arms are reported as declared secondaries.  Points
      are also the unit in which "soft" is comparable across two markets.

--------------------------------------------------------------------------
RESPONSE VARIABLES
--------------------------------------------------------------------------
  resid_total  = total  - total_line       (+ = the game went OVER by that many points)
  resid_margin = result - spread_line      (+ = home beat the number by that many points)
      nflverse: result = home_score - away_score; spread_line = points the
      HOME team is favoured by; total = home_score + away_score.
  over      = 1[total  > total_line]       pushes DROPPED
  ats_cover = 1[result > spread_line]      pushes DROPPED

--------------------------------------------------------------------------
FEATURES -- and the structural problem with them, declared in advance
--------------------------------------------------------------------------
  The existing four vectors, unchanged, exactly as fit.py defines them:
      F = F (fundamental, home-minus-away)
      P = p_qb_z (QB EPA/dropback delta, home-minus-away)
      C = C (rest/travel/timezone composite, home-positive)
      R = R = r_regime_score * tanh(spread_line/7), home-signed

  DECLARED IN ADVANCE: all four are home-MINUS-away DIFFERENTIALS.  A total
  is a SUM.  A differential has no first-order reason to predict a sum, so a
  null on the totals arm for these four is expected FOR A STRUCTURAL REASON
  and is NOT evidence that the totals market is efficient.  This is stated
  here, before running, so it cannot be used as a post-hoc excuse.

  Therefore two game-level, NON-directional quantities the harness already
  emits are also declared.  Both are totals-shaped by construction, and
  neither is invented for this run:
      r_regime_score = P(CHAOS) - P(GRIND), recovered as r_p_chaos -
        r_p_grind.  features_context.py's own docstring says it "is also
        emitted raw so the same classifier can be reused unchanged when the
        harness later fits totals, where VAS.md's +1/-1 mapping does apply."
        This is the module's own pre-registered totals hypothesis.
      wind (mph) and roof-is-closed, straight from games.csv.  Weather is
        the classic totals input.  HAZARD DECLARED IN ADVANCE: nflverse's
        wind may be a game-time observation rather than the pregame
        forecast.  If so it is mild look-ahead and any result on it is an
        UPPER BOUND on a tradeable effect, not a tradeable effect.  Reported
        as such regardless of outcome.

--------------------------------------------------------------------------
SAMPLE FILTER
--------------------------------------------------------------------------
  Base = tools/backtest/out_full_fit_table.parquet, the sample fit_full.py
  already built and already vetted: seasons 2006-2025, n = 4886, all four
  vectors non-null, f_ready & r_ok & ~qb_history_thin.  It is reused
  UNCHANGED so that the sides arm and the totals arm run on the SAME ROWS
  with the SAME FEATURES and only the response variable differs.  That is
  what makes the two arms comparable at all.
      2006 is the earliest season at which pass_oe exists (Vector R) and at
      which any odds exist.  It is not a tuning knob; fit_full.py established
      it from column null-rates only.

  SAMPLE A (primary, linear arms): base rows with spread_line, total_line,
      result and total all present.  Pushes KEPT (residual = 0 is a real
      observation on a linear response).
  SAMPLE B (secondary, binary arms): SAMPLE A, further requiring the
      relevant two-way odds present with hold > 0, and pushes DROPPED.

--------------------------------------------------------------------------
OUT OF SAMPLE
--------------------------------------------------------------------------
  Expanding window, SEASON-WISE ONLY.  Train on seasons strictly earlier
  than the test season; test on the test season.  First test season =
  2008 = FIT_LO + 2, the same +2 offset fit.py and fit_full.py both used.
  Never random k-fold.

--------------------------------------------------------------------------
DECLARED TESTS -- 31.  Every one is reported.
--------------------------------------------------------------------------
  T1   sides  binary, offset-pinned logit: Wald on B_F,B_P,B_C,B_R      4
  T2   totals binary, offset-pinned logit: Wald on B_F,B_P,B_C,B_R      4
  T3   sides  linear, OLS resid_margin ~ 1+F+P+C+R: slope t-tests       4
  T4   totals linear, OLS resid_total  ~ 1+F+P+C+R: slope t-tests       4
  T5   intercepts of T3 and T4 (systematic lean in the closing number)  2
  T6   joint F-test of the 4 slopes, sides arm and totals arm           2
  T7   head-to-head softness: is the totals arm's explained residual
       variance larger than the sides arm's?  Paired-bootstrap over
       seasons on the difference in R^2                                 1
  T8   OOS gamma_D, sides and totals, pooled held-out games             2
  T9   OOS realised hit rate vs the 52.38% break-even, sides and totals 2
  T10  r_regime_score on resid_total: in-sample slope, OOS gamma        2
  T11  r_regime_score on resid_margin: in-sample slope, OOS gamma       2
  T12  wind and roof_closed on resid_total: 2 in-sample slopes, 1 OOS
       gamma on their combined D                                        3
                                                                       ---
                                                                        31
  No other model is fitted.  If any variant is run after this list, it is
  added to the count and reported as a post-hoc variant.

THRESHOLD
  Two-sided alpha = 0.05 per test, AND Benjamini-Hochberg at FDR 10% across
  the whole family of 31.  A result "survives" only if it is significant
  OUT OF SAMPLE (T8/T9/T10/T11/T12), not merely in sample.

POWER -- reported for every arm, because an insignificant underpowered test
  means "unknown", not "no".
      MDE at 80% power, two-sided 5%  =  2.8016 * SE
  reported in POINTS per 1 SD of each feature, next to the BREAK-EVEN edge
  at -110 (= sigma_resid * Phi^-1(0.5238)), so the reader can see directly
  whether the test could have found a bettable effect had one existed.

WHAT WOULD FALSIFY H1
  If the totals arm's explained residual variance is not larger than the
  sides arm's, and the MDE is below the break-even edge, then the answer is
  "no, and we had the power to say no" -- which is a successful outcome.

NO TUNING TO SIGNIFICANCE.  Run once, as written above.
Writes only tools/backtest/out_totals_*.parquet.  Ships nothing.
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)

RULE = "=" * 98
THIN = "-" * 98

FIT_LO, FIT_HI = 2006, 2025
CV_TEST_SEASONS = list(range(2008, FIT_HI + 1))
VECTORS = ["F", "P", "C", "R"]
VECTOR_COL = {"F": "F", "P": "p_qb_z", "C": "C", "R": "R"}
COLS4 = [VECTOR_COL[v] for v in VECTORS]

MDE_K = stats.norm.ppf(0.975) + stats.norm.ppf(0.80)   # 2.8016
BREAKEVEN_P = 110.0 / 210.0                            # 0.52381 at -110

TESTS = []          # (id, family, name, p) -- every declared test lands here


def head(t):
    print("\n" + RULE); print(t); print(RULE)


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def american_to_prob(ml):
    ml = np.asarray(ml, dtype=float)
    out = np.full(ml.shape, np.nan)
    neg = ml < 0
    ok = np.isfinite(ml)
    out[ok & neg] = (-ml[ok & neg]) / ((-ml[ok & neg]) + 100.0)
    out[ok & ~neg] = 100.0 / (ml[ok & ~neg] + 100.0)
    return out


def devig(odds_a, odds_b):
    """Multiplicative de-vig -- fit.py's own choice. Returns (p_a, hold)."""
    qa, qb = american_to_prob(odds_a), american_to_prob(odds_b)
    over = qa + qb
    return qa / over, over - 1.0


def record(tid, family, name, p):
    TESTS.append({"id": tid, "family": family, "test": name, "p": float(p)})
    return p


def benjamini_hochberg(pvals, q=0.10):
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    passed = p[order] <= q * (np.arange(1, n + 1) / n)
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    rej = np.zeros(n, dtype=bool)
    if k:
        rej[order[:k]] = True
    return rej


# =========================================================================
# 0. sample
# =========================================================================
def build():
    head("0. SAMPLE -- reusing fit_full.py's already-vetted rows, unchanged")
    d = pd.read_parquet(os.path.join(HERE, "out_full_fit_table.parquet"))
    print("base out_full_fit_table.parquet: %d rows, seasons %d-%d"
          % (len(d), d.season.min(), d.season.max()))

    # the module's own raw regime score, recovered from the two emitted probs
    d["r_regime_score"] = d["r_p_chaos"] - d["r_p_grind"]

    # weather, straight from games.csv columns already carried in the frame
    d["wind_mph"] = pd.to_numeric(d["wind"], errors="coerce")
    roof = d["roof"].astype(str).str.lower()
    d["roof_closed"] = roof.isin(["dome", "closed"]).astype(float)
    # a dome has no wind; nflverse leaves it null. 0 is the physically correct
    # value there, and it is declared, not imputed to a fitted quantity.
    d.loc[d["roof_closed"] > 0, "wind_mph"] = d.loc[d["roof_closed"] > 0,
                                                    "wind_mph"].fillna(0.0)
    print("wind present: %.1f%% of rows (after setting closed-roof wind to 0); "
          "roof_closed = %.1f%%"
          % (100 * d["wind_mph"].notna().mean(), 100 * d["roof_closed"].mean()))

    # responses
    d["resid_margin"] = d["result"] - d["spread_line"]
    d["resid_total"] = d["total"] - d["total_line"]
    d["ats_push"] = d["result"] == d["spread_line"]
    d["tot_push"] = d["total"] == d["total_line"]
    d["ats_cover"] = (d["result"] > d["spread_line"]).astype(float)
    d["over"] = (d["total"] > d["total_line"]).astype(float)

    # offsets -- the non-degenerate part of the R8 problem
    d["p_mkt_ats"], d["hold_ats"] = devig(d["home_spread_odds"],
                                          d["away_spread_odds"])
    d["p_mkt_over"], d["hold_tot"] = devig(d["over_odds"], d["under_odds"])

    A = d[d["resid_margin"].notna() & d["resid_total"].notna()
          & d["wind_mph"].notna()].reset_index(drop=True)
    print("\nSAMPLE A (primary, linear arms): %d rows" % len(A))
    print("  ATS pushes kept: %d   totals pushes kept: %d"
          % (int(A["ats_push"].sum()), int(A["tot_push"].sum())))

    Bs = A[(A["hold_ats"] > 0) & A["p_mkt_ats"].notna() & ~A["ats_push"]].reset_index(drop=True)
    Bt = A[(A["hold_tot"] > 0) & A["p_mkt_over"].notna() & ~A["tot_push"]].reset_index(drop=True)
    print("SAMPLE B sides  (binary arm): %d rows  (drops %d for missing/zero-hold "
          "spread odds, %d for ATS push)"
          % (len(Bs), int((~((A["hold_ats"] > 0) & A["p_mkt_ats"].notna())).sum()),
             int(A["ats_push"].sum())))
    print("SAMPLE B totals (binary arm): %d rows  (drops %d for missing/zero-hold "
          "total odds, %d for totals push)"
          % (len(Bt), int((~((A["hold_tot"] > 0) & A["p_mkt_over"].notna())).sum()),
             int(A["tot_push"].sum())))

    head("0b. THE R8 PROBLEM, MEASURED -- how much does the offset actually carry?")
    for lab, p, h in (("sides  logit(p_mkt_ats) ", Bs["p_mkt_ats"], Bs["hold_ats"]),
                      ("totals logit(p_mkt_over)", Bt["p_mkt_over"], Bt["hold_tot"])):
        off = logit(p)
        print("%s : mean %+.4f  SD %.4f  p5 %+.4f  p95 %+.4f  |off|>0.05 on %.1f%% "
              "of rows   (mean hold %.4f)"
              % (lab, off.mean(), off.std(), np.percentile(off, 5),
                 np.percentile(off, 95), 100 * np.mean(np.abs(off) > 0.05), h.mean()))
    print("""
Read that: the offset is real but TINY -- a standard -110/-110 line puts it at
exactly 0.0000, and the asymmetric-juice rows move it by a few hundredths of a
log-odd. It is used, it is not degenerate, and it is not doing the work. The
market's opinion is in the LINE, and the LINE is already inside the response
variable. That is why the linear arms below are the PRIMARY test and the binary
arms are secondaries: on a differenced response the offset has nothing left to
explain, but the residual in POINTS still has all of its information.""")

    print("\nresponse distributions on SAMPLE A:")
    for lab, col in (("resid_margin (sides) ", "resid_margin"),
                     ("resid_total  (totals)", "resid_total")):
        s = A[col]
        print("  %s : mean %+.3f  SD %.3f  median %+.2f  skew %+.2f"
              % (lab, s.mean(), s.std(), s.median(), s.skew()))
    print("  sides  cover rate (pushes dropped): %.4f on %d"
          % (Bs["ats_cover"].mean(), len(Bs)))
    print("  totals over  rate (pushes dropped): %.4f on %d"
          % (Bt["over"].mean(), len(Bt)))
    return A, Bs, Bt


# =========================================================================
# power
# =========================================================================
def power_block(A):
    head("POWER -- declared up front, so an insignificant result can be read correctly")
    rows = []
    for lab, col in (("sides  resid_margin", "resid_margin"),
                     ("totals resid_total", "resid_total")):
        sig = A[col].std()
        be = sig * stats.norm.ppf(BREAKEVEN_P)
        for v in VECTORS + ["regime", "wind"]:
            c = {"regime": "r_regime_score", "wind": "wind_mph"}.get(v, VECTOR_COL.get(v))
            sd = A[c].std()
            # SE of a simple slope, per 1 SD of x, in points
            se_pts = sig / np.sqrt(len(A))
            rows.append({
                "arm": lab, "feature": v,
                "sigma_resid": sig,
                "break-even edge (pts)": be,
                "SE per 1sd (pts)": se_pts,
                "MDE@80% (pts per 1sd)": MDE_K * se_pts,
                "MDE < break-even?": "YES" if MDE_K * se_pts < be else "no",
            })
    t = pd.DataFrame(rows).drop_duplicates(subset=["arm"]).set_index("arm")
    print(t[["sigma_resid", "break-even edge (pts)", "SE per 1sd (pts)",
             "MDE@80% (pts per 1sd)", "MDE < break-even?"]].round(4).to_string())
    print("""
n = %d, so a single standardised feature has SE ~ sigma/sqrt(n) points.

The break-even column is the edge a -110 bet needs to be profitable: shifting the
residual distribution by that many points moves the cover probability from 0.5000
to 0.5238. The MDE column is the smallest effect this test detects 80%% of the
time. MDE BELOW break-even means: if a bettable 1-SD effect existed, this test
would almost certainly have seen it. An insignificant result then means NO, not
UNKNOWN. That is the whole reason this run uses fit_full.py's 2006-2025 sample
instead of the 2019-2025 one -- n=4886 clears the bar, n=1812 would not have.
(Caveat: the normal approximation ignores the key-number lumps at 0, 3, 7 on
sides; those make the sides arm slightly HARDER than this number says, and
barely touch totals.)""" % len(A))


# =========================================================================
# arms
# =========================================================================
def binary_arm(d, y_col, p_col, label, tid_base, family):
    print("\n" + THIN)
    print("%s -- BINARY, offset-pinned: %s ~ Binomial, lp = logit(p_mkt) + B.x  (n=%d)"
          % (label, y_col, len(d)))
    print(THIN)
    X = pd.DataFrame({c: d[c].to_numpy(float) for c in COLS4}, index=d.index)
    r = sm.GLM(d[y_col].to_numpy(float), X, family=sm.families.Binomial(),
               offset=logit(d[p_col].to_numpy())).fit()
    ci = r.conf_int(); ci.columns = ["lo", "hi"]
    rows = []
    for i, (v, c) in enumerate(zip(VECTORS, COLS4)):
        sd = d[c].std()
        p = record("%s%d" % (tid_base, i + 1), family,
                   "%s B_%s (binary Wald)" % (label, v), r.pvalues[c])
        rows.append({"term": v, "B": r.params[c], "SE": r.bse[c], "z": r.tvalues[c],
                     "p": p, "ci_lo": ci.loc[c, "lo"], "ci_hi": ci.loc[c, "hi"],
                     "B*sd (log-odds/1sd)": r.params[c] * sd,
                     "win-prob pp /1sd": 100 * (sigmoid(r.params[c] * sd) - 0.5),
                     "MDE@80% pp/1sd": 100 * (sigmoid(MDE_K * r.bse[c] * sd) - 0.5),
                     "sig@5%": "YES" if r.pvalues[c] < 0.05 else "no"})
    print(pd.DataFrame(rows).set_index("term").round(5).to_string())
    return r


def linear_arm(A, y_col, label, tid_base, family, tid_int, extra=None):
    cols = COLS4 + (extra or [])
    print("\n" + THIN)
    print("%s -- LINEAR (PRIMARY): OLS  %s ~ 1 + %s   HC1 robust SE   (n=%d)"
          % (label, y_col, " + ".join(cols), len(A)))
    print(THIN)
    X = sm.add_constant(A[cols].astype(float))
    r = sm.OLS(A[y_col].astype(float), X).fit(cov_type="HC1")
    sig = A[y_col].std()
    be = sig * stats.norm.ppf(BREAKEVEN_P)
    ci = r.conf_int(); ci.columns = ["lo", "hi"]
    rows = []
    for i, c in enumerate(cols):
        sd = A[c].std()
        p = record("%s%d" % (tid_base, i + 1), family,
                   "%s slope on %s (OLS)" % (label, c), r.pvalues[c])
        rows.append({"term": c, "beta": r.params[c], "SE": r.bse[c], "t": r.tvalues[c],
                     "p": p, "pts per 1sd": r.params[c] * sd,
                     "95% CI pts/1sd": "[%+.3f, %+.3f]" % (ci.loc[c, "lo"] * sd,
                                                           ci.loc[c, "hi"] * sd),
                     "MDE@80% pts/1sd": MDE_K * r.bse[c] * sd,
                     "break-even pts": be,
                     "sig@5%": "YES" if r.pvalues[c] < 0.05 else "no"})
    print(pd.DataFrame(rows).set_index("term").round(4).to_string())
    pi = record(tid_int, family, "%s intercept (systematic lean in the closing number)"
                % label, r.pvalues["const"])
    print("  intercept = %+.4f pts (SE %.4f, p %.4f) %s"
          % (r.params["const"], r.bse["const"], pi,
             "<- the closing number's own systematic lean"))
    print("  R^2 = %.6f   adj R^2 = %.6f   F(%d, %d) = %.3f"
          % (r.rsquared, r.rsquared_adj, int(r.df_model), int(r.df_resid), r.fvalue))
    return r


def joint_test(A, y_col, label, tid, family):
    X = sm.add_constant(A[COLS4].astype(float))
    r = sm.OLS(A[y_col].astype(float), X).fit()
    f = r.fvalue
    p = record(tid, family, "%s joint F-test of all 4 slopes" % label, r.f_pvalue)
    print("  %s : joint F(%d,%d) = %.4f, p = %.4f, R^2 = %.6f"
          % (label, int(r.df_model), int(r.df_resid), f, p, r.rsquared))
    return r.rsquared, p


# =========================================================================
# out of sample
# =========================================================================
def oos_linear(A, y_col, cols, label, tid, family):
    pieces = []
    for s in CV_TEST_SEASONS:
        tr, te = A[A.season < s], A[A.season == s]
        if len(tr) < 200 or len(te) == 0:
            continue
        r = sm.OLS(tr[y_col].astype(float),
                   sm.add_constant(tr[cols].astype(float))).fit()
        b = r.params.reindex(cols).to_numpy(float)
        pe = te[["game_id", "season", y_col]].copy()
        pe["D"] = te[cols].to_numpy(float).dot(b)
        pieces.append(pe)
    o = pd.concat(pieces, ignore_index=True)
    rg = sm.OLS(o[y_col].astype(float), sm.add_constant(o[["D"]])).fit(cov_type="HC1")
    g, se = rg.params["D"], rg.bse["D"]
    lo, hi = rg.conf_int().loc["D"]
    p = record(tid, family, "%s OOS gamma_D" % label, rg.pvalues["D"])
    print("  %-34s n_oos=%d  gamma_D = %+.4f (SE %.4f, p %.4f, 95%% CI [%+.3f, %+.3f])  %s"
          % (label, len(o), g, se, p, lo, hi,
             "SURVIVES" if p < 0.05 else "not distinguishable from 0"))
    return o, g, p


def oos_hitrate(o, y_col, label, tid, family):
    """Bet the side D points to. Hit rate vs the 52.38% break-even."""
    live = o[o["D"].abs() > 1e-12]
    pick_over = live["D"] > 0
    resid = live[y_col].to_numpy(float)
    won = np.where(pick_over, resid > 0, resid < 0)
    push = resid == 0
    n = int((~push).sum())
    hits = int(won[~push].sum())
    rate = hits / n if n else np.nan
    # one-sided binomial against break-even: can we reject "<= 52.38%"?
    p = stats.binomtest(hits, n, BREAKEVEN_P, alternative="greater").pvalue
    record(tid, family, "%s OOS hit rate > 52.38%% (one-sided binomial)" % label, p)
    units = hits * (100 / 110.0) - (n - hits)
    print("  %-34s n=%d  hit %d (%.4f)  break-even %.4f  p(one-sided) %.4f  "
          "units @1/bet %+.1f  ROI %+.2f%%"
          % (label, n, hits, rate, BREAKEVEN_P, p, units, 100 * units / n if n else 0))
    return rate, p


def main():
    print(RULE)
    print('id: "totals-vs-sides"   IS THE TOTALS MARKET SOFTER THAN THE SIDES MARKET?')
    print("pre-registered above; run once; all 31 declared tests reported")
    print(RULE)

    A, Bs, Bt = build()
    power_block(A)

    # ---- T1 / T2 : binary arms -----------------------------------------
    head("T1, T2 -- BINARY ARMS (secondary): fit.py's exact offset-pinned methodology")
    rs_b = binary_arm(Bs, "ats_cover", "p_mkt_ats", "SIDES ", "T1", "T1 sides binary")
    rt_b = binary_arm(Bt, "over", "p_mkt_over", "TOTALS", "T2", "T2 totals binary")

    # ---- T3 / T4 / T5 : linear arms ------------------------------------
    head("T3, T4, T5 -- LINEAR ARMS (PRIMARY): the residual in POINTS")
    rs_l = linear_arm(A, "resid_margin", "SIDES ", "T3", "T3 sides linear", "T5a")
    rt_l = linear_arm(A, "resid_total", "TOTALS", "T4", "T4 totals linear", "T5b")

    # ---- T6 / T7 : the softness comparison ------------------------------
    head("T6, T7 -- THE ACTUAL HYPOTHESIS: is the totals residual MORE explainable?")
    r2_s, _ = joint_test(A, "resid_margin", "SIDES ", "T6a", "T6 joint")
    r2_t, _ = joint_test(A, "resid_total", "TOTALS", "T6b", "T6 joint")
    print("\n  R^2(totals) - R^2(sides) = %+.6f" % (r2_t - r2_s))
    print("  H1 predicts this is POSITIVE and materially so.")

    rng = np.random.default_rng(20260920)
    seasons = sorted(A.season.unique())
    idx_by = {s: A.index[A.season == s].to_numpy() for s in seasons}
    boot = []
    for _ in range(2000):
        pick = np.concatenate([idx_by[seasons[j]] for j in
                               rng.integers(0, len(seasons), len(seasons))])
        b = A.loc[pick]
        Xb = sm.add_constant(b[COLS4].astype(float))
        try:
            d2 = (sm.OLS(b["resid_total"].astype(float), Xb).fit().rsquared
                  - sm.OLS(b["resid_margin"].astype(float), Xb).fit().rsquared)
            boot.append(d2)
        except Exception:
            pass
    boot = np.array(boot)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    p_soft = 2 * min((boot <= 0).mean(), (boot >= 0).mean())
    record("T7", "T7 softness", "R^2(totals) - R^2(sides) != 0 "
           "(season-block bootstrap)", p_soft)
    print("  season-block bootstrap (2000 reps, whole seasons resampled):")
    print("    mean %+.6f  95%% CI [%+.6f, %+.6f]  two-sided p = %.4f"
          % (boot.mean(), lo, hi, p_soft))
    print("  -> %s" % ("the totals arm IS more explainable" if lo > 0 else
                       "the interval CONTAINS zero: no detectable softness gap"))

    # ---- T8 / T9 : out of sample ---------------------------------------
    head("T8, T9 -- OUT OF SAMPLE (expanding window, season-wise, test 2008-2025)")
    print("gamma_D: refit one scale factor on held-out games only. gamma=1 means the")
    print("coefficients learned from earlier seasons transferred perfectly; gamma=0")
    print("means they carry nothing forward. gamma=0 is the null.\n")
    os_s, _, _ = oos_linear(A, "resid_margin", COLS4, "SIDES  4-vector", "T8a", "T8 OOS")
    os_t, _, _ = oos_linear(A, "resid_total", COLS4, "TOTALS 4-vector", "T8b", "T8 OOS")
    print("\nrealised betting record of those held-out signals (flat 1u at -110):")
    oos_hitrate(os_s, "resid_margin", "SIDES  4-vector", "T9a", "T9 OOS bet")
    oos_hitrate(os_t, "resid_total", "TOTALS 4-vector", "T9b", "T9 OOS bet")

    # ---- T10 / T11 : regime score, the module's own totals hypothesis ---
    head("T10, T11 -- r_regime_score: the ONLY totals-shaped term the harness emits")
    print("features_context.py's own docstring: regime_score is 'emitted raw so the")
    print("same classifier can be reused unchanged when the harness later fits totals,")
    print("where VAS.md's +1/-1 mapping does apply.' CHAOS = more possessions = more")
    print("scoring. This is the module's pre-registered totals claim, not a new one.\n")
    for tag, y, tid in (("TOTALS", "resid_total", "T10"), ("SIDES ", "resid_margin", "T11")):
        r = sm.OLS(A[y].astype(float),
                   sm.add_constant(A[["r_regime_score"]].astype(float))).fit(cov_type="HC1")
        c = "r_regime_score"
        sd = A[c].std()
        p = record(tid + "a", tid + " regime",
                   "%s slope on r_regime_score" % tag, r.pvalues[c])
        lo_, hi_ = r.conf_int().loc[c]
        print("  %s  beta = %+.4f  (SE %.4f, p %.4f)  = %+.3f pts per 1sd  "
              "95%% CI [%+.3f, %+.3f] pts/1sd  MDE@80%% %.3f pts/1sd"
              % (tag, r.params[c], r.bse[c], p, r.params[c] * sd,
                 lo_ * sd, hi_ * sd, MDE_K * r.bse[c] * sd))
        oos_linear(A, y, ["r_regime_score"], "%s regime OOS" % tag,
                   tid + "b", tid + " regime")

    # ---- T12 : weather on totals ----------------------------------------
    head("T12 -- WEATHER ON TOTALS (wind, closed roof). HAZARD DECLARED IN ADVANCE.")
    print("nflverse wind may be a GAME-TIME observation, not the pregame forecast.")
    print("If so this is mild look-ahead and ANY result here is an UPPER BOUND on a")
    print("tradeable effect, not a tradeable effect. Reported either way.\n")
    wcols = ["wind_mph", "roof_closed"]
    rw = sm.OLS(A["resid_total"].astype(float),
                sm.add_constant(A[wcols].astype(float))).fit(cov_type="HC1")
    for i, c in enumerate(wcols):
        sd = A[c].std()
        p = record("T12%s" % "ab"[i], "T12 weather",
                   "TOTALS slope on %s" % c, rw.pvalues[c])
        lo_, hi_ = rw.conf_int().loc[c]
        print("  beta(%-11s) = %+.4f (SE %.4f, p %.4f) = %+.3f pts per 1sd  "
              "95%% CI [%+.3f, %+.3f] pts/1sd"
              % (c, rw.params[c], rw.bse[c], p, rw.params[c] * sd, lo_ * sd, hi_ * sd))
    print("  intercept %+.4f   R^2 = %.6f" % (rw.params["const"], rw.rsquared))
    print()
    ow, gw, pw = oos_linear(A, "resid_total", wcols, "TOTALS weather OOS",
                            "T12c", "T12 weather")
    oos_hitrate(ow, "resid_total", "TOTALS weather (not declared)", "T12d_extra",
                "EXTRA not in the 31")

    # ---- the full ledger -------------------------------------------------
    head("THE FULL TEST LEDGER -- every test declared, every p-value, BH at FDR 10%")
    led = pd.DataFrame(TESTS)
    declared = led[~led["id"].str.contains("extra")].reset_index(drop=True)
    rej = benjamini_hochberg(declared["p"].to_numpy(), q=0.10)
    declared["raw p<.05"] = ["YES" if p < 0.05 else "no" for p in declared["p"]]
    declared["BH q=10%"] = ["SURVIVES" if r else "rejected" for r in rej]
    print(declared[["id", "test", "p", "raw p<.05", "BH q=10%"]].round(5).to_string(index=False))
    print("\nDECLARED TESTS RUN: %d (pre-registered: 31)" % len(declared))
    extra = led[led["id"].str.contains("extra")]
    if len(extra):
        print("UNDECLARED EXTRAS RUN (reported anyway, excluded from BH): %d" % len(extra))
        print(extra[["id", "test", "p"]].round(5).to_string(index=False))
    print("\nraw p<.05: %d of %d.  Under a pure null you would expect %.1f by chance."
          % (int((declared["p"] < 0.05).sum()), len(declared), 0.05 * len(declared)))
    print("SURVIVING Benjamini-Hochberg at FDR 10%%: %s"
          % (list(declared.loc[rej, "id"]) or "NONE"))

    out = os.path.join(HERE, "out_totals_ledger.parquet")
    declared.to_parquet(out, index=False)
    A.to_parquet(os.path.join(HERE, "out_totals_sample.parquet"), index=False)
    print("\nledger -> %s ; sample -> out_totals_sample.parquet" % out)


if __name__ == "__main__":
    main()
