# VAS-NFL — canonical vector spec, v1

The NHL dashboards score a slate as three ✅/❌ judgement calls plus a tier badge. This is the NFL
version rebuilt as arithmetic: every vector is a continuous, signed number derived from a feed this
repo already calls. Nothing here is a narrative judgement, and no tier can outrun a measured edge.

**This file is the single source of truth.** If a future session's output disagrees with it, the
output is wrong, not this file. Diff against it; do not average with it.

## Two data layers — fitting and serving are different problems

v1 conflated them. The model is **fitted offline on history** and **served live from feeds**. These
need different sources, and the fitting problem is now solved outright.

### Layer 1 — fitting (nflverse, free, no key, no install)

`https://github.com/nflverse/nfldata/raw/master/data/games.csv` — 7,548 games, 1999-2025.
**5,327 carry a complete closing spread + total + moneyline. 2018-2025 alone is 2,227 games**,
which is precisely the eight-season depth the power calculation calls for (2,176 games to resolve a
3.0pp effect at 80% power). The fitting blocker is gone.

It also hands over three vectors' worth of inputs that v1 planned to compute the hard way:

| Column | What it replaces |
| --- | --- |
| `away_rest`, `home_rest` | the entire rest-differential calculation |
| `roof`, `temp`, `wind` | historical weather for the regime classifier |
| `home_qb_id`, `away_qb_id`, `*_qb_name` | **the starting QB of every historical game** |
| `spread_line`, `total_line`, `*_moneyline`, `*_spread_odds`, `under/over_odds` | `p_mkt` for every fitting row |
| `result`, `total` | the outcome being fitted |

`home_qb_id` is the important one: it makes the Personnel vector fittable on history, which the
ESPN-only plan could not do at all.

Play-by-play comes from the nflverse release assets as parquet
(`nflverse-data/releases/download/pbp/play_by_play_<year>.parquet`, ~20MB/season, HTTP 200 verified).
`nfl_data_py` is NOT installed and is not needed — the parquet URLs are fetched directly.

**This supersedes the hand-built expected-points map.** nflfastR already ships a fitted expected-points
model: `ep` and `epa` per play, with `yardline_100` as *absolute* field position. Building our own
`g(endYardLine)` from drive text would be a worse version of a well-validated public model. Use `ep`.

Likewise `xpass` and `pass_oe` (pass rate over expected) exist in pbp, so the regime classifier's
PROE input is real rather than aspirational.

### Layer 2 — per-book movement (OddsPapi, user's key)

`GET /v4/historical-odds?fixtureId=...&bookmakers=pinnacle,...` returns, per bookmaker and market,
the **full price history as timestamped entries**: `createdAt`, `price`, and `limit`.

That `createdAt` is the anchor v1 said it lacked. `P_residual` needs "the line at the moment the
news broke", and a timestamped per-book price series supplies it directly — no injury-report
timestamp required, because the move itself is dated. The `limit` field is a bonus: a rising
Pinnacle limit toward kickoff is the market firming, which `lib/pinnacle.js` already comments on.

**Quota reality: the free tier is 250 requests/month.** That cannot backfill 2,227 games, and should
not try. It comfortably covers going forward — one request per fixture per week is ~16/week, ~64/month.
So: fit on nflverse, and accumulate per-book movement from today onward for the residual term and CLV.

### The one honest caveat

nflverse closing lines are **consensus/market closers, not Circa or Pinnacle specifically**.
Coefficients fitted against a consensus close and then deployed against Circa and Pinnacle is
acceptable — both are near-efficient and highly correlated with the consensus close — but it is an
approximation and must be stated, not buried. As OddsPapi history accumulates, refit on Pinnacle
itself and compare coefficient sets; if they differ materially, the consensus fit was biased and
the Pinnacle fit wins.

### Layer 3 — serving live (unchanged, already in the repo)

Circa (`vsin: 'Circa'`, Action Network id 78) and Pinnacle (`guest.api.arcadia.pinnacle.com`,
league 889) are both already flagged `sharp: true` in `lib/books.js` and sit first in board order.
They are the live sharp anchor for `p_mkt`. ESPN supplies live game state, injuries and
win probability. VAS.md v1 named DraftKings-adjacent sourcing; that was wrong and is corrected here.

## The frame: everything lives in log-odds, nothing lives on a 0-100 scale

v0 of this spec scored a play 0-100 and then compared that score to a separately measured edge.
That is two currencies for one question, and it forces arbitrary thresholds ("A >= 75") that cannot
be validated against anything. v1 puts the vectors and the market in the same units.

The market's no-vig price is the prior. The vectors are an **additive adjustment in log-odds**:

    p_mkt    = no-vig market probability          (edge.js: noVig / edgeNoVig)
    D        = B_F*F + B_P*P + B_C*C + B_R*R      (R = regime-bet interaction)
    p_model  = sigmoid( logit(p_mkt) + D )
    edge     = p_model - p_mkt

This buys three things v0 could not have:

1. **The B's are fittable, not asserted.** Logistic regression of outcome on the vectors with
   `logit(p_mkt)` as a **fixed offset** (coefficient pinned to 1). The null hypothesis B = 0 is
   exactly "the market already knows this." Any vector whose B is not significantly non-zero out of
   sample is decoration and gets deleted. v0 had no way to ever discover that.
2. **Edge is one number, measured once.** A tier can no longer outrun the edge, because the tier is
   computed *from* the edge. The separate "alignment" scale is gone.
3. **Uncertainty propagates.** The regression gives `SE(D)`, so every edge carries a confidence
   interval, and tiers key off the interval's lower bound rather than a point estimate.

Sigmoid saturation replaces the ad-hoc `tanh` clamps: extreme vector values can no longer push
`p_model` past 0 or 1, so no clipping rule is needed.

## Shrinkage — the part that matters most in September

Today is Week 2. A points-per-drive estimate from two games is mostly noise, and v0 had no guard
at all: it fed raw season stats into a z-score and would have produced confident garbage.

Every team rate is shrunk toward the league mean by empirical Bayes:

    theta_hat = (n*theta_obs + k*theta_league) / (n + k)
    k         = sigma_within^2 / sigma_between^2

`k` is estimated from the league, not chosen. For points per drive the within-team drive-to-drive
SD is about 2.0 points and the between-team spread of true talent is about 0.35 points per drive:

    k = 2.0^2 / 0.35^2 = 33 drives = roughly 3 games

So a Week 2 team sits ~80% on the league prior and a Week 12 team ~85% on its own record, with no
cliff between them. `k` is recomputed each season from that season's realised variances and written
to `data/eb-<season>.json` alongside the margins file.

## Vector 1 — Fundamental (F) : is the record earned?

Per-drive so pace cannot distort it, shrunk per above, then differenced.

    offPPD = points on own drives / own drives
    defPPD = points allowed on opp drives / opp drives

**The regression term, rebuilt.** v0 used
`luck = actualPointMargin/games - ppdMargin*drivesPerGame`. That is algebraically zero whenever both
teams get equal drives, which is nearly always: points-for is *defined* as `offPPD * ownDrives`, so
subtracting `ppdMargin * DPG` subtracts the same quantity back out. It measured drive-count
asymmetry and called it luck. It is removed.

The honest construction compares points actually scored against points the **field position earned**:

    xPts(drive) = g(endYardLine)     empirical league map, points by drive end position
    xPPD        = mean xPts over the team's drives
    finishing   = actualPPD - xPPD

Two drives that both die on the opponent 5 have identical `xPts`; one kicked a field goal and one
turned it over on downs. That gap is finishing, and finishing mean-reverts hard. `g()` is fitted
once per season from every drive in the league — `summaryOf().drives` already carries `end`,
`result` and `yds`, and scoring plays give the points.

    F = w1*z(offPPD_hat - defPPD_hat) - w2*z(finishing)

Third-down and red-zone conversion stay out of the stable term by construction: they are what
`finishing` is made of. `w1, w2` are not hand-set — they are absorbed into `B_F` by the fit, so the
only real choice is that finishing enters with the opposite sign to efficiency.

**Differencing z-scores.** Team z-scores are computed against the league first, then differenced.
The difference of two independent unit-variance scores has SD sqrt(2), so it is divided by sqrt(2)
to stay unit-variance. v0 wrote `z(x_diff)`, which is a different and undefined quantity.

## Vector 2 — Personnel (P) : the residual, not the news

The hard abort is unchanged and sits **outside** the probability model, because it is a
data-quality veto rather than a belief: if depth-chart QB1 is Out or Doubtful, or unresolved inside
90 minutes of kickoff, the play is killed. Not downgraded. This is the GSAA gate ported intact.

The continuous part needed the biggest correction. **The market has already read the injury report.**
Adding a QB penalty on top of a market-anchored prior double-counts it, and the model would
systematically fade every team with public bad news — a guaranteed losing bias.

Only the *unpriced residual* may enter:

    P_raw      = z(qbDelta) + 0.5*z(posIndex)
    moved      = logit(p_mkt_now) - logit(p_mkt_at_report)
    P          = P_raw - (moved / B_P)          clipped at 0 from the correct side

`p_mkt_at_report` comes from the per-book line history already stored in `data/weeks/*.json`, keyed
to the injury report timestamp. If the line has already moved the full implied amount, `P` goes to
zero and the vector correctly contributes nothing. If news broke minutes ago and the line has not
moved, `P` retains its full value. This is the only place the model can genuinely beat the market,
so it is the one place worth being precise.

    qbDelta  = xPPD_withStarter - xPPD_withBackup      (xPPD, not PPD: finishing excluded)
    posIndex = sum over injured of weight(pos) * severity(status)
    weights    LT .18 | C .12 | CB1 .10 | EDGE1 .10 | WR1 .08 | other .02
    severity   Out 1.0 | Doubtful 0.75 | Questionable 0.35

Severity is a probability of absence, not a judgement — it is calibrated against how often each
ESPN status actually results in the player missing the game, and refit each season.

## Vector 3 — Context (C) and Regime (R) : separated, because they are different objects

**C is a fatigue and travel term** and enters the log-odds sum like the others:

    C = a1*z(restDiff) + a2*shortWeek + a3*byeReturn - a4*z(travelMiles) - a5*tzPenalty

All coefficients come from the fit. `restDiff`, travel distance and time-zone shift are computed
from the schedule and `data/geo.json`; `tzPenalty` applies to west-coast teams in 1pm ET kicks.

**R is not a score and not a multiplier.** v0 multiplied the 0-100 alignment by 0.5 on a regime
mismatch. On a scale where 50 is neutral, halving sends a neutral play to 25 — i.e. a *mismatch*
manufactured a strong negative signal out of nothing. That is a sign error, not a tuning problem.

R is an **interaction term**: regime classification crossed with bet type, entering the sum with its
own fitted coefficient.

    regime  = classifier over projected plays, pass rate, and wind
              GRIND    low pace / low pass rate / sustained wind >= 15mph
              CHAOS    high pace / high pass rate / dome or calm
              STANDARD otherwise
    R       = +1 bet type matches regime, -1 opposed, 0 orthogonal

Wind stays a regime input rather than its own vector; gusts >= 20mph force GRIND. The regime
classifier emits a **probability** over the three states, not a hard label, and `R` is the
expectation over that distribution — so a borderline game contributes a small `R` instead of
flipping discontinuously between two classifications.

## From probability to a bet

`p_model` and the offered price are all that is needed, and both are measured:

    dec    = decimal odds offered
    EV     = p_model*(dec - 1) - (1 - p_model)
    kelly  = EV / (dec - 1)
    stake  = lambda * kelly                      lambda = 0.25, quarter Kelly

This retires the NHL file's hand-assigned "1.5U" — unit size now follows from edge and price, and
feeds the existing `public/js/kelly.js`.

**Tiers key off the lower confidence bound, never the point estimate.** With `SE(D)` from the fit:

    D_lo   = D - 1.64*SE(D)                      one-sided 95%
    EV_lo  = EV evaluated at sigmoid(logit(p_mkt) + D_lo)

| Tier | Requires |
| --- | --- |
| DIAMOND | `EV_lo >= 3%` and no abort |
| GOLD | `EV_lo >= 1%` and no abort |
| SILVER | `EV_lo > 0` and no abort |
| NO PLAY | abort fired, or `EV_lo <= 0` |

A play with a big point-estimate edge built on two games of data has a wide interval and will not
tier. That is the intended behaviour and it is what makes the September output trustworthy.

**Slate-level false positives.** A 16-game slate across spread, total and moneyline is ~100
simultaneous tests, so at any fixed threshold some plays clear on noise alone. Candidates are
ranked by `EV_lo` and Benjamini-Hochberg is applied at FDR 10% across the slate. A DIAMOND on a
14-game Sunday is a stricter claim than on a 2-game Thursday, which is correct.

## Validation — the model must earn its place

None of the above is worth running unless it beats the price it is anchored to. Out-of-sample,
on held-out weeks:

- **Log loss and Brier score vs. the market baseline** (`p_mkt` alone). If `p_model` does not beat
  `p_mkt`, the vectors are noise and ship nothing.
- **Reliability curve in deciles** — of the plays given a 58% chance, about 58% must win.
- **Per-vector B with confidence intervals.** Any vector whose interval spans zero is dropped.
- **Closing line value** — the true test for a bet model is whether flagged plays beat the close,
  and `data/weeks/*.json` already stores the close for every game. This is measurable today on
  stored history, before a single new bet is placed.

Refit weekly; log every coefficient set to `data/fit-<season>-w<week>.json` so any historical call
is reproducible from the exact model that made it.

## Live triggers — the same model, re-run on live state

Triggers are not hand-written trees; they are the pre-game model re-evaluated with live inputs,
firing when the live market disagrees with it.

    p_live_model  = sigmoid( logit(p_live_mkt) + D_live )
    fire when     EV_lo(live) >= tier threshold

`D_live` drops the pre-game context terms once the game starts (rest and travel are spent) and adds
game state. ESPN's `winprobability` series is used as a **feature and a cross-check, not as truth** —
it is another model, with its own bias, and treating a rival model's output as ground truth would
make this one a copy of it.

    GRIND + leader up >= 10 after Q1   -> live under, clock is the ally
    CHAOS + within 3 at half           -> live over
    any   + wp swing >= 25pts on one drive and live price not yet moved -> re-price
    pre-kick QB1 unconfirmed           -> ABORT banner, blocks the card

The third is the only one that is genuinely an edge: it fires on the *lag between a state change
and the market's response*, which is a timing claim rather than a prediction claim.

## What this spec deliberately does not include

The pasted analysis lists the Fundamental Vector as 5v5 xG%, HDCF% and PDO. Measured across all
three NHL files: HDCF appears 0 times, PDO 0 times, xG once, as prose. That trio was written down
but never implemented, so there is nothing to port and no NFL analog is built for it. GSAA is the
one quantified rule the NHL system really ran, and it ports as the QB gate above.

## Injuries — a feed, a vector input, and an alert

The summary `injuries` node carries player, position and status for both teams. It feeds three
things, and they must not be confused:

1. **Vector input** — the weighted positional index inside Personnel (above).
2. **Display** — an injury table per game, the analog of the NHL Goalie Matrix. Columns:
   `Player | Pos | Status | Side | VAS weight | Effect`, sorted by weight so the line-movers sit
   at the top rather than being buried among practice-squad DTs.
3. **Alert** — a status *change* is the alert, not the status itself. Out -> Questionable is noise;
   QB1 Questionable -> Out is the whole bet. Only weighted positions fire, and QB1 always fires.

Statuses seen live: `Out`, `Questionable`, `Doubtful`. A QB1 at Questionable inside 90 minutes of
kickoff is treated as unresolved, which is an abort — same as unconfirmed.

## Alerts — from a three-state bell to a real menu

The transport is already built and works: `S.alerts` (`public/js/core.js:67`) rides the `/api/stream`
SSE channel with `Notification` permission and a chime. What goes is the **cycling**. Alerts are set
explicitly, never by tapping through states to find the one you want.

Two controls cycle or collapse today, and both are replaced:

- `public/js/boot.js:166` — the header bell cycles `off -> mine -> all -> off`. **Gone.** The bell
  opens the alerts panel in the existing `#dlg` sheet. One tap, one destination, no guessing which
  state you landed on. The icon still reflects state (`ICON.bell` / `ICON.bellOn`) and the
  `aria-label` names the active profile, so it reads correctly to a screen reader without being a
  control that changes meaning each press.
- `public/js/views.js:652` — the three-option `<select>` in Tools. **Replaced** by a row that opens
  the same panel, so there is exactly one place alerts are configured.

Each channel is set independently — off / my bets+teams / everything:

| Channel | Fires on | Default |
| --- | --- | --- |
| Line move | move >= threshold (0.5pt default, or any) | mine |
| Injury status change | weighted position changes status; QB1 always | mine |
| VAS tier change | play crosses a tier boundary either way | mine |
| Abort | QB1 unconfirmed or ruled out inside 90 min | **always on, all games** |
| Live trigger | a trigger predicate fires in-game | mine |
| CLV window | current price beats your logged price | mine |

`S.alerts` becomes an object rather than a string. Existing stored values migrate on read:
`'off'` -> all channels off, `'mine'` -> the defaults above, `'all'` -> every channel on everything.
Nobody loses their setting and nobody gets a surprise notification.

Abort is not user-disableable — a killed play is the one message that must not be missed.

## Porting to Hook & Ladder (NCAAF) — read before starting

Per this repo's own boundary rule, the NCAAF build happens in `~/Projects/hook-and-ladder` in its
own session. Nothing here cross-edits it. Two things do not port cleanly and need deciding there:

- **Personnel breaks.** College injury reporting is not mandated the way the NFL's is; ESPN
  coverage is thin and inconsistent across FBS. The QB1 hard-abort gate is only as good as the
  status feed, and for much of the Group of Five there is effectively no feed. Options: restrict
  the gate to teams with confirmed reporting, or replace the abort with a confidence haircut.
- **Every coefficient must be refit, and the shrinkage constant changes most.** College talent
  spread is far wider, so `sigma_between` is much larger and `k = sigma_within^2 / sigma_between^2`
  is correspondingly *smaller* — a college team's own record becomes trustworthy in fewer games
  than an NFL team's. Copying the NFL `k` would over-shrink every team toward a league mean that
  spans Alabama and Kent State, which is a meaningless centre. The tier thresholds themselves
  (`EV_lo >= 3%` etc.) are in EV units and do port unchanged; that is a benefit of leaving the
  0-100 scale behind.
- **The market is softer, which cuts both ways.** Thinner college lines mean real edges are larger,
  but `p_mkt` is a weaker prior, so the model carries more of the load and the validation bar
  (beating the market's log loss) is easier to clear while meaning less. Hold it to closing line
  value rather than to log loss there.

Bing Bong Live (MLB) is out of scope for this work.

## Live Trigger Mode — the user-facing design

The NHL page hand-wrote a decision tree per game. Three games is a briefing; sixteen is a wall nobody
reads during a Sunday slate. The mode has to stay quiet to stay useful.

### The governing rule

**A trigger is silent until it is actionable.** Most of a game, the strip shows one calm line. The card
only earns attention at the moment something changed AND there is still a price to act on. Anything that
does not meet both tests never becomes a card.

### Three states, never more

    ARMED    one quiet line. "Watching · GRIND · under 44.5 if NE leads by 10+"
    FIRED    a card, with the action, the price, the confidence and a one-tap why
    VOID     the abort. Red, blocking, and it outranks everything else on the card

`ARMED` is the resting state and it is deliberately boring. `VOID` is the only state allowed to
interrupt, because a killed play is the one message that must not be missed.

### What a fired card actually says

Generated from the model's own terms — never pre-written prose:

    ▲ NE under 44.5 · -108 Circa                              8:42 Q2
      Model 71% · market 64% · edge +7.0pp (lo +3.1pp) · 0.4u
      Why ▾

    Why ▴
      Regime GRIND — pace 4th percentile, wind 18mph
      Win prob swung +22pts on the last drive
      Circa has not moved in 2m — the lag is the edge
      Model re-priced at 8:41; this expires if the number moves past 45.5

Every line is a value the model computed, rendered in words. Nothing is authored per game, so it
scales from a Thursday single to a full Sunday without anyone writing copy.

### Keeping it clean when twelve games are live

- **One active trigger per game.** The highest `EV_lo` wins the slot; the rest collapse behind a
  `+2 more` disclosure that stays closed unless tapped.
- **Triggers expire themselves.** When the condition stops holding or the price moves through the
  number, the card fades to `expired` and removes itself. A stale trigger is worse than no trigger.
- **The board ranks, the user doesn't.** Cards sort by `EV_lo`, so the top of the screen is always the
  best available action and scrolling is optional rather than required.
- **A hard ceiling on cards shown.** Beyond that, a single summary row: `4 more live edges ·  view`.
- **Progressive disclosure everywhere.** One line always, three on tap, full term-by-term breakdown on
  expand. The detail exists for the one game you care about, not for all twelve at once.

### The explainer users get

Live Trigger Mode needs one short sheet, reachable from the mode toggle, that says plainly:

> **Live Trigger Mode** watches every live game and tells you when the in-game price is behind what the
> game is actually doing.
>
> It is **not** a prediction of who wins. It fires on the lag between something changing — a score, an
> injury, a momentum swing — and the book moving its number. That gap is measured in seconds and minutes,
> so a trigger is a short-lived opportunity, not a recommendation to hold.
>
> **Armed** means it is watching and nothing has happened. **Fired** means there is a number worth acting
> on right now, with the reasoning shown. **Void** means something invalidated the play and you should not
> bet it.
>
> Live limits are lower and live prices move faster than pregame. Stakes shown are a quarter-Kelly
> suggestion from the model's own edge, and they are only as good as that edge.

### Build gate — what ships when

Live Trigger Mode is feature-complete only once the live model has evidence behind it. Until then the
trigger engine runs and logs, and the cards are simply not rendered.

**This is a build gate, not UI copy.** Nothing in the app explains what it is not yet doing — a feature
that is not present needs no announcement, and an app that apologises to its users reads worse than one
that just works. When the live model earns its cards, they arrive as a new feature, not as a correction.

Every evaluated trigger is logged with its price and the settled number, so the validation set builds
itself as a by-product of running.

### Where it plugs in

`public/js/live.js` already has the render scheduling (`invalidate()` on `requestAnimationFrame`) and the
`/api/stream` SSE channel already pushes updates, so the strip updates without a reload. Live prices come
from `lib/action.js`, which filters `is_live` and is described in-repo as the only free source of live
in-game lines. Game state comes from the ESPN summary. No new transport is needed.

## Closing lines and movement — what ESPN's core API actually gives

Probed live on 2026-09-20 against `sports.core.api.espn.com/v2/.../competitions/{id}/odds`:

**The odds item carries `open`, `close` AND `current`, each with full pricing.** On a completed game the
total read `open 52.5 (over -110)` and `close 54.5 (over -118)`. This is a genuine closing line, per game,
retrievable historically, free.

That matters because the earlier audit found `data/weeks/*.json` is capturing openers, not closes — one
close across sixteen games. **ESPN's `close` is the fix**: CLV does not depend on this app having polled at
the right moment, it can be read after the fact for any game. Closing line value becomes measurable
retroactively rather than only going forward.

**But odds movement history is empty.** `odds/{provider}/history/0/movement` returns HTTP 200 with
`count: 0` and zero items. The endpoint exists and is unpopulated, so there is no timestamped price series
here. Per-book intraday movement still has to come from OddsPapi or from this app's own polling.

**And there is only one provider.** Both a completed and an upcoming game returned `count: 1`, DraftKings
(id 100) — not the six providers the community reference lists. So ESPN's close is a DraftKings close.
It correlates tightly with the consensus close and is fine for CLV measurement, but it is not Circa and
not Pinnacle, and should be labelled as what it is.

## Field View — live games as a football field

A separate feature from Live Trigger Mode, sharing its data path. The scoreboard `situation` node already
carries everything needed, and the app already polls it.

Verified live (8 games in progress at time of probe):

    down                1
    distance            10
    yardLine            49
    downDistanceText    "1st & 10 at ATL 49"
    possession          "1"            team id
    isRedZone           false
    homeTimeouts        3
    awayTimeouts        3
    lastPlay            text, type, statYardage, probability, drive,
                        start {yardLine, team}, end {yardLine, team}, athletesInvolved

`lastPlay.start` and `lastPlay.end` both give a yard line and a team, which is what lets the field animate
the most recent play rather than only marking a static spot.

### The drawing

One compact field per live game, sized to read at a glance in a grid — not a stadium broadcast graphic:

    ┌──────────────────────────────────────────────────┐
    │ CAR 14  ·  ATL 17            2nd  7:12   ▾ ATL   │
    │ ░░│    ·    │    ·    │    ·    │    ·    │░░░░░ │
    │ ◄─────────────●━━━━━━┫                          │
    │   1st & 10 at ATL 49        J.Strand → A.Hooper  │
    │   +13 yds · WP +2.4                    ⏱ 3 · 3   │
    └──────────────────────────────────────────────────┘

- `●` is the ball at absolute field position; `┫` is the first-down marker at `yardLine + distance`.
- `━━━` is the last play swept from `start.yardLine` to `end.yardLine`, drawn in the possessing team's
  colour and animated once on arrival, then left static. Motion happens on change, never on a loop.
- End zones shade to each team's colour; the red zone tints when `isRedZone` is true.
- Timeouts are pips, not a number to parse.

### Normalising the yard line — the one real gotcha

`yardLine: 49` with `possessionText: "ATL 49"` is **team-relative**. Drawing it raw puts half the league on
the wrong end of the field. Absolute position must be derived from `yardLine` together with the team on
`lastPlay.start.team` / `possession`, and the direction of travel flips by period. This is the single
place this feature will break if rushed, so it gets its own unit test with a fixture per quarter.

### Keeping it clean

- **The field is the whole card.** No stat tables underneath — tapping opens the existing game sheet.
- **Eight live games fit on a phone** because each field is three lines tall. That is the design
  constraint everything else bends to.
- **Nothing blinks.** The only motion is the last-play sweep, once, on data change.
- **Colour is never the only signal** — possession is shown by the `▾` marker and the team abbreviation,
  not only by tint, and the down-and-distance text always states the situation in words.
- Dark and light themes both get explicit field, line and end-zone tokens rather than one tinted image.

### Where it plugs in

`public/js/live.js` renders the live tab and already schedules on `requestAnimationFrame` via
`invalidate()`; the scoreboard poll already returns `situation`, so no new fetch is required — `lib/espn.js`
currently discards it in `gameFromEvent()` and must stop. Field geometry is inline SVG in a new
`public/js/field.js` with `public/field.css` for tokens, following the repo's one-file-per-feature CSS
convention.

## Live Pinnacle — confirmed, and it changes the live anchor

Probed 2026-09-20 with 8 games in progress. `guest.api.arcadia.pinnacle.com/0.1/leagues/889` returns
`isLive: true` on exactly those 8 matchups, and `lib/pinnacle.js:23` **already reads `live: !!m.isLive`** —
the field is parsed and then unused.

Live prices are real and carry limits:

    moneyline  home -311 / away +249    maxRiskStake $5,000
    moneyline  home +390 / away -530    maxRiskStake $5,000
    spread     -16.5  home -249/away +194   maxRiskStake $3,000
    total       29.5  over +110/under -138  maxRiskStake $2,000

So the live trigger anchor is **Pinnacle, not Circa-via-Action-Network**. That is a materially better
reference and it needs no new provider, no key and no scraping.

### Two things the probe also proves, both design-relevant

**Live coverage is sparse and intermittent.** Only 4 open markets existed across 8 live games at the
moment of the probe — Pinnacle pulls markets during plays and reopens between them. The trigger engine
must therefore treat "no live price right now" as the *normal* state, not an error: a trigger with no
current sharp price is `ARMED`, never `FIRED`. Firing against a stale sharp number is the single easiest
way to show a user an edge that does not exist.

**Live limits are 20-50x smaller than pregame.** $2k-$5k live against the $100k maxRiskStake seen on the
pregame main slate. Two consequences, both of which belong in the UI rather than in a footnote:
- Pinnacle's own limit is a confidence signal. A $2,000 total is Pinnacle saying it is less sure than it
  is about a $100,000 side. Surface the limit on the live card; it is free information about how much
  the sharpest book trusts its own number.
- Even a genuine live edge is capped in dollars. Quarter-Kelly on a live trigger will frequently be
  larger than the market will actually take, so the suggested stake must be `min(kelly, what is
  realistically available)` and say so, rather than printing a number nobody can bet.

### Sources considered and rejected or deferred

**PickTheOdds** — Cloudflare returns HTTP 403 to every request including the bare domain. That is an
active anti-automation control, so building on it would mean circumventing an access control on a third
party's service, and it would break mid-slate when the challenge changes. Not used. It is unnecessary
anyway now that Pinnacle's own live feed is confirmed.

**The Odds API** (the-odds-api.com, via the edge-scanner reference) — a legitimate keyed API covering many
US/EU books including Pinnacle, free tier 500 requests/month. Worth holding as the **fallback** if
Pinnacle's guest feed is ever rate-limited or pulled, and as the source for cross-book comparison if
arbitrage/middles are ever wanted. Not needed for the core model.


## VAS trigger trees — the NHL structure, grounded

The NHL command centre's most useful feature was the **pre-armed branch**: you read the tree before
kickoff, and during the game you already knew what to watch for. That structure ports. What changes is
what sits on each branch.

In the NHL file a branch asserted an outcome — *"COL still wins 68% historically even trailing"*. We
cannot say that: the backtest showed our predictions do not beat the market. So a branch instead names a
**condition to watch** and a **market to price when it happens**. The tree is the map; the card is the
action.

### What a game looks like, pre-kick

    ⚡ CIN @ NE                                                    armed · pre-kick
    ────────────────────────────────────────────────────────────────────────────
    VAS   Personnel   ⚠   CIN QB1 questionable (ESPN, 2h ago)
          Context     ✓   wind 18mph · NE +3 days rest
          Fundamental –   NE +0.07 EPA/play edge · not priced-in information

    IF  NE leads by 10+ after Q1
        → price the live under 44.5 · clock becomes the ally
        → Context points here: wind 18mph, both bottom-10 pass rate

    IF  CIN ties or leads at half
        → price the live over · script flips to pass

    IF  CIN QB1 leaves the game
        → VOID every CIN side · the Personnel gate fails

Three vector rows, then the branches each vector implies. A user reads this once before kickoff and then
knows what the game is about.

### How a branch becomes a bet

A branch has three states, and only the third has a number on it:

    ARMED     the condition has not happened. One quiet line.
    WATCHING  the condition IS true, but no fresh sharp price exists to measure against.
              Says so: "no sharp live price right now" — silence explained, not silence unexplained.
    FIRED     condition true AND a measured gap exists between a bettable price and the live sharp
              no-vig number. Only now does a card appear, with EV, limit and stake.

This is the whole honesty mechanism. The tree can say "watch the under" all day, because that is a
statement about what to look at. It cannot say "take the under" until a real price is off a real sharp
number, which is arithmetic.

### The vector rows are labels, not scores

    Personnel    QB1 status, injuries (ESPN lists up to five per team), and the hard VOID gate
    Context      rest, travel, wind, roof, regime
    Fundamental  EPA/play differential, as-of, shrunk

Marked `✓` / `⚠` / `–`, never a number and never a tier. `–` means "nothing notable", not "unknown".
The backtest is explicit that none of these beat the close, so they are shown as **what is true about
this game**, which is useful, and never as **what will happen**, which is not ours to claim.

The one exception is the Personnel VOID, which is a hard rule rather than a prediction: if QB1 is ruled
out, every branch on that side dies. That gate is the one thing the NHL model had that was genuinely
quantified, and it ports intact.

### Which branches exist

Generated per game from measurable state, not authored:

| Branch | Condition | Prices |
| --- | --- | --- |
| Clock | leader up >= 10 after Q1 | live under, leader's spread |
| Shootout | tied or within 3 at half, pace above median | live over |
| Swing | win probability moves >= 20pts on one drive | the side that moved, before the book catches up |
| Wind | sustained >= 15mph and total still above the wind-adjusted band | under |
| QB exit | listed QB1 no longer the passer of record | VOID that side |
| Backdoor | favourite up 14+, late, spread within a key number | dog's live spread |

Each carries its own `expiresWhen`. A branch that can no longer happen removes itself rather than
sitting stale — a tree of dead branches is exactly the wall of text this design exists to avoid.
