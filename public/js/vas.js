'use strict';
/* Pick Six — VAS: the pre-armed branch tree, and the live price trigger. NFL only.

   WHAT THIS IS. Every game gets a tree you can read before kickoff: three vector rows (Personnel,
   Context, Fundamental — marked ✓ / ⚠ / –, never a number and never a tier), then the IF/THEN branches
   those vectors imply. A branch names a condition to watch and a market to price when it happens.

   WHAT THIS IS NOT. It never predicts. A full backtest showed the predictive model does not beat the
   closing line, so there is no win probability here, no tier, no confidence score. The only number that
   ever appears is a MEASURED gap: a price a book is hanging against the sharp no-vig price from Pinnacle
   or Circa. That is arithmetic. Everything else on the screen is factual game state — quarter and clock,
   down and distance, field position, possession, timeouts, quarterback status, wind, and where the
   number sits relative to the key numbers 3 and 7.

   THREE STATES, AND ONLY THE LAST CARRIES A NUMBER.
     ARMED     the condition has not happened. One quiet line.
     WATCHING  the condition IS true, but nothing can be measured — says which, in words.
     FIRED     the condition is true AND a bettable price is off a fresh sharp number. Card with the
               gap, the limit and a stake.
     VOID      a quarterback on that side is listed out. Outranks everything, carries no number.

   THE QUIET STATE IS THE PRODUCT. Measured on a full Sunday: the honest pregame rule produced zero
   cards in thirteen consecutive scans of an eighteen-game board (3,916 prices), and the honest live rule
   with its freshness gate produced about zero. This is built so that hours of nothing look intended,
   because they are. The tree is what earns the screen; the card is the rare guest.

   THE LIVE GATES, all ANDed. Any one missing means WATCHING, never FIRED.
     1. The sharp price must be PROVABLY fresh (<= 120s). Pinnacle's guest feed is CDN-cached for up to
        ~15 minutes, so the time we polled it says nothing about the age of the price inside it. Only two
        things count as proof: a true `age` in milliseconds that the server read off the HTTP `age`
        header, or an Action Network live line, whose poll time IS the price's age. Without proof we do
        not fire. Firing against a stale sharp number is the worst failure this feature can have.
     2. SAME NUMBER ONLY. Never model between two live numbers: SIGMA and EDGE_TOTAL_SD are full-game
        constants and applied to a remaining-game line they invent EV out of nothing. A whole-number live
        line is skipped too, because its push cannot be priced without that same model.
     3. The gap must be >= 3%. The live noise floor is wider than pregame.
     4. The live market must not contradict it: the same price scored against the live consensus must
        still be >= 0. Without this gate, four out of five live "edges" against Pinnacle are lag.
     5. Price-shape guards: no moneyline longer than +500 or shorter than −300, and nothing above 12%.
     6. The stake is min(quarter Kelly, Pinnacle's live limit), and the limit is printed. Live limits run
        around $2,000–$5,000 against $100,000 pregame. Never print a stake nobody can bet.

   WHAT THIS FILE EXPORTS (plain globals; the app uses no modules):
     vasTriggers(g)   the tree. Returns an Array of branches, ranked void → fired (by gap) → watching →
                      armed, and that same array also carries .vectors and .branches so either shape in
                      the build contract works. vasTree(g) is the {vectors, branches} alias.
     vasCard(g, t)    HTML for ONE trigger card.
     vasPanel(g)      HTML for one game's VAS block: vectors, tree, context, measured edge.
     vasLiveStrip()   HTML for the ranked live trigger list, or '' when nothing qualifies.
   Every class name is prefixed vas- and styled in public/vas.css.

   INPUTS IT WILL USE IF THE SERVER EVER SENDS THEM, and degrades without:
     g.live[book].age    true age of that live price in ms (read from the HTTP `age` header)
     g.live.pin          Pinnacle's live child matchup, once lib/pinnacle.js stops skipping parentId
     g.pinLiveLimit      Pinnacle's live maxRiskStake. g.pinLimit is NOT used on a live game: the server
                         keeps the last PREGAME limit there, and showing $100,000 on a live card is a lie.
*/

// ------------------------------------------------------------ thresholds, all measured (see VAS.md)
const VAS_SHARP = ['pin', 'circa'];   // the sharp anchors, in order of preference
const VAS_LIVE_FRESH = 120e3;         // gate 1
const VAS_LIVE_EV = 0.03;             // gate 3, against a sharp book
const VAS_LIVE_EV_PEER = 0.04;        // gate 3, against the peer market: a weaker anchor pays a higher bar
const VAS_PEER_MIN = 3;               // peers required before their median may anchor a fire
const VAS_MAX_HOLD = 0.10;            // a peer holding more than this prices too loosely to inform an anchor
const VAS_ANCHOR_Z = 1;               // how pessimistic the anchor's low bound is (1 sd)
const VAS_SD_FLOOR = 0.0025;          // never claim the books agree to better than a quarter of a point
const VAS_LAG_MS = 45e3;              // a book this far behind a moved market is measurably stale
const VAS_PRE_EV = 0.02;              // pregame fire: above the 99th percentile of a real board
const VAS_PRE_EVMKT = 0.01;           // pregame fire: the rest of the market has to agree
const VAS_EV_CAP = typeof EDGE_MAX === 'number' ? EDGE_MAX : 0.12;
const VAS_ML_LONG = typeof EDGE_ML_LONG === 'number' ? EDGE_ML_LONG : 500;
const VAS_ML_SHORT = -300;            // gate 5: a cent is several EV points on a −450 live favourite
const VAS_KEYS = [3, 7];              // the NFL key numbers
const VAS_WIND = 15;                  // sustained mph
const VAS_GUST = 25;
const VAS_LEAD = 10;                  // Clock branch
const VAS_CLOSE = 3;                  // Shootout branch: "within a field goal"
const VAS_BLOWOUT = 14;               // Backdoor branch
const VAS_SWING_PTS = 7;              // Swing branch: one score
const VAS_SWING_MS = 5 * 60e3;
const VAS_MAX_CARDS = 6;              // hard ceiling on the live strip

const VAS_STATE = { fired: 'FIRED', watching: 'WATCHING', armed: 'ARMED', void: 'VOID' };
const VAS_RANK = { void: 0, fired: 1, watching: 2, armed: 3 };
const VAS_MARK = { ok: '✓', warn: '⚠', none: '–' };
const VAS_MARK_TXT = { ok: 'noted', warn: 'watch this', none: 'no flag' };

// ------------------------------------------------------------ small helpers
const vasReady = () => typeof edgeNoVig === 'function' && typeof sideOf === 'function' && typeof dec === 'function';
const vasFin = (v) => (Number.isFinite(v) ? v : null);
function vasAgo(ms) {
  if (!Number.isFinite(ms) || ms < 0) return null;
  const s = Math.round(ms / 1000);
  if (s < 90) return `${s}s`;
  const m = Math.round(s / 60);
  return m < 90 ? `${m} min` : `${Math.round(m / 60)} hr`;
}
const vasPct = (ev) => (ev == null ? '' : `${ev >= 0 ? '+' : MINUS}${(Math.abs(ev) * 100).toFixed(1)}%`);
// A pregame row where the book hangs a different number than the sharp book is modelled between the two,
// so it is an estimate and says so — the same "≈" edge.js puts on its own rows.
const vasEvTxt = (e) => `${e && e.est ? '≈ ' : ''}${vasPct(e ? e.ev : null)}`;
const vasTeam = (g, side) => (g?.[side] ? teamName(g[side]) : side);
const vasAbbr = (g, side) => g?.[side]?.abbr || side;

// "Under 44.5", "NE −7.5", "NE ML"
function vasPick(g, mkt, side, line) {
  if (mkt === 't' || mkt === 'h1t') return `${side === 'over' ? 'Over' : 'Under'} ${fmtTot(line)}`;
  if (mkt === 'ml') return `${vasAbbr(g, side)} ML`;
  if (mkt === 'h1s') return `${vasAbbr(g, side)} 1H ${fmtPts(line)}`;
  return `${vasAbbr(g, side)} ${fmtPts(line)}`;
}
const VAS_MKT_TXT = { s: 'spread', t: 'total', ml: 'moneyline', h1s: 'first-half spread', h1t: 'first-half total' };

// The whole point of the key numbers: does one sit between the book's number and the sharp one?
function vasKeyBetween(a, b) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const lo = Math.min(Math.abs(a), Math.abs(b)), hi = Math.max(Math.abs(a), Math.abs(b));
  return VAS_KEYS.find((k) => lo <= k && k <= hi && lo !== hi) ?? null;
}
// Where a spread sits relative to 3 and 7 — always true, needs no price.
function vasKeyTxt(v) {
  if (!Number.isFinite(v)) return null;
  const m = Math.abs(v);
  const k = VAS_KEYS.find((x) => Math.abs(m - x) < 0.001);
  if (k) return `the number is on ${k}`;
  const near = VAS_KEYS.find((x) => Math.abs(m - x) <= 0.5);
  return near ? `the number sits just ${m > near ? 'outside' : 'inside'} ${near}` : null;
}

// ------------------------------------------------------------ game state, read straight off the feed
const vasLive = (g) => typeof isLive === 'function' && isLive(g);
const vasPre = (g) => typeof isPre === 'function' && isPre(g);
const vasDead = (g) => !g || g.state === 'off' || (typeof isFinal === 'function' && isFinal(g));
const vasMargin = (g) => (g?.home?.score == null && g?.away?.score == null ? 0 : (g.home.score ?? 0) - (g.away.score ?? 0));
function vasLeader(g) {
  const m = vasMargin(g);
  return m > 0 ? 'home' : m < 0 ? 'away' : null;
}
// Points each side had at the half, from ESPN's line scores. Null until two quarters exist.
function vasHalfMargin(g) {
  const h = g?.home?.q, a = g?.away?.q;
  if (!Array.isArray(h) || !Array.isArray(a) || h.length < 2 || a.length < 2) return null;
  return Math.abs((h[0] ?? 0) + (h[1] ?? 0) - ((a[0] ?? 0) + (a[1] ?? 0)));
}
// Scoring against the number the market set, pro-rated by how much of the game has been played.
function vasPace(g) {
  const total = vasFin(g?.mkt?.t) ?? vasFin(g?.close?.t);
  if (total == null || typeof remaining !== 'function') return null;
  const played = 1 - remaining(g);
  if (!(played > 0.1)) return null;
  const pts = (g.home.score ?? 0) + (g.away.score ?? 0);
  const on = total * played;
  return { pts, total, on: Math.round(on * 10) / 10, ahead: pts > on };
}
// Quarter, clock, down and distance, field position, possession, timeouts. All facts, always available.
function vasSitTxt(g) {
  if (!vasLive(g)) return null;
  if (g.half) return 'Halftime';
  const out = [typeof clockLabel === 'function' ? clockLabel(g) : null];
  const s = g.sit;
  if (s && s.down > 0) {
    const who = g.poss ? vasAbbr(g, g.poss) : null;
    // s.text already names the spot ("2nd & 9 at SF 19"); s.short does not.
    const dd = s.text || [s.short || `${s.down} and ${s.dist}`, s.spot ? `at ${s.spot}` : null].filter(Boolean).join(' ');
    out.push(`${who ? `${who} ball, ` : ''}${dd}${s.rz ? ' · red zone' : ''}`);
  }
  if (s && Array.isArray(s.to) && s.to[0] != null && s.to[1] != null) {
    out.push(`timeouts ${vasAbbr(g, 'home')} ${s.to[0]}, ${vasAbbr(g, 'away')} ${s.to[1]}`);
  }
  return out.filter(Boolean).join(' · ') || null;
}
function vasScoreTxt(g) {
  if (g?.home?.score == null || g?.away?.score == null) return null;
  return `${vasAbbr(g, 'away')} ${g.away.score}, ${vasAbbr(g, 'home')} ${g.home.score}`;
}

// The live number the market is showing, used to name what a branch would price. Never used as "fair".
function vasLiveBooks(g) {
  const out = { ...(g?.live || {}) };
  const pin = g?.livePin || g?.pinLive || null;   // wherever lib/pinnacle.js's live child matchup lands
  if (pin && !out.pin) out.pin = pin;
  return out;
}
function vasLiveNum(g, mkt) {
  const src = vasLiveBooks(g);
  const order = ['cons', 'czr', 'mgm', 'dk', 'fd', ...Object.keys(src)];
  for (const k of order) {
    const L = src[k];
    if (!L || L.m) continue;
    const v = mkt === 't' ? L.t : L.s;
    if (v != null) return v;
  }
  return null;
}
// The under's number, live if the market is quoting one, otherwise the number the game opened against.
function vasTotalNow(g) {
  return vasLiveNum(g, 't') ?? vasFin(g?.mkt?.t) ?? vasFin(g?.close?.t) ?? null;
}
function vasSpreadNow(g) {
  return vasLiveNum(g, 's') ?? vasFin(g?.mkt?.s) ?? vasFin(g?.close?.s) ?? null;
}

// ------------------------------------------------------------ the score trail (for the Swing branch)
/* A swing is a fact about the scoreboard, not a probability. We keep the last half hour of margin
   changes per game so "the margin moved 10 points in five minutes" can be stated from real values.
   On a fresh page load the trail is empty, so nothing swings — which is the calm, correct answer. */
const vasTrail = new Map();
function vasNote(g) {
  if (!vasLive(g) || typeof serverNow !== 'function') { if (g && g.id) vasTrail.delete(g.id); return; }
  // A missing score is not a 0-0 tie. Recording one would invent a swing out of a feed hiccup.
  if (g.home?.score == null || g.away?.score == null) return;
  const t = serverNow(), m = vasMargin(g);
  const a = vasTrail.get(g.id) || [];
  const last = a[a.length - 1];
  if (!last || last[1] !== m) a.push([t, m]);
  while (a.length > 60 || (a.length > 1 && t - a[0][0] > 30 * 60e3)) a.shift();
  vasTrail.set(g.id, a);
}
/* De-vigging for the live path. The method itself is shinNoVig() in core.js, where the rest of the odds
   arithmetic lives; this is the anchor's entry point, with the app's older method as the fallback so an
   odd market degrades instead of dropping the game off the board. */
function vasDevig(mkt, oddsA, oddsB) {
  return shinNoVig(oddsA, oddsB) ?? edgeNoVig(mkt, oddsA, oddsB);
}
const vasShin = (a, b) => shinNoVig(a, b);   // kept: the name the rest of this file and its tests use

/* ------------------------------------------------------- the price trail, and which book is behind

   The live edge in this sport is usually a SLOW BOOK. Measured IND@KC, 3rd quarter: the market moved
   80.1%% -> 84.0%% on the home side over ~2.5 minutes while FanDuel never moved off -460. An EV number
   alone cannot tell that apart from a book that simply disagrees — but they are different things, and
   only one of them is an edge you can trust.

   So we keep a short series of each book's no-vig price and one for the market as a whole. If the market
   has moved more recently than a book has, that book is measurably behind, and by how long. That is a
   fact about observed prices, not a forecast, and it is the single most useful thing on a live card:
   a gap at a book that just moved is a disagreement; the same gap at a book that has not moved in two
   minutes is lag, and lag is what closes.

   On a fresh page load every trail is empty, so nothing is "behind" — the calm, correct answer. */
const vasPriceTrail = new Map();            // `${gid}|${book}|${mkt}` -> [[t, p], ...]
const vasPriceKey = (gid, k, mkt) => `${gid}|${k}|${mkt}`;
function vasPushPrice(key, t, p) {
  if (p == null || !(p > 0 && p < 1)) return;
  const a = vasPriceTrail.get(key) || [];
  const last = a[a.length - 1];
  // Ignore sub-point jitter so a book is not credited with "moving" on rounding.
  if (!last || Math.abs(last[1] - p) > 0.002) a.push([t, p]);
  while (a.length > 40 || (a.length > 1 && t - a[0][0] > 20 * 60e3)) a.shift();
  vasPriceTrail.set(key, a);
}
function vasNotePrices(g) {
  if (!vasLive(g) || !vasReady() || typeof serverNow !== 'function') return;
  const src = vasLiveBooks(g);
  const t = serverNow();
  for (const mkt of ['s', 't', 'ml']) {
    const [a, b] = mkt === 't' ? ['over', 'under'] : ['home', 'away'];
    const ps = [];
    for (const k of Object.keys(src)) {
      const L = src[k];
      if (!L || L.m || k === 'open') continue;
      const pa = sideOf(L, mkt, a), pb = sideOf(L, mkt, b);
      if (!pa || !pb || pa.odds == null || pb.odds == null) continue;
      const p = vasDevig(mkt, pa.odds, pb.odds);
      if (p == null || !(p > 0 && p < 1)) continue;
      vasPushPrice(vasPriceKey(g.id, k, mkt), t, p);
      if (k !== 'cons') ps.push(p);
    }
    if (ps.length >= 2) {
      ps.sort((x, y) => x - y);
      const mid = ps.length >> 1;
      vasPushPrice(vasPriceKey(g.id, '__mkt', mkt), t, ps.length % 2 ? ps[mid] : (ps[mid - 1] + ps[mid]) / 2);
    }
  }
}
/* How far behind a moved market this book is, in ms — or null when it is keeping up (or we cannot tell).
   Needs a real move on both series, so a quiet market never makes every book look stale. */
function vasLagOf(g, k, mkt) {
  if (!g || typeof serverNow !== 'function') return null;
  const bk = vasPriceTrail.get(vasPriceKey(g.id, k, mkt));
  const mk = vasPriceTrail.get(vasPriceKey(g.id, '__mkt', mkt));
  if (!bk || !mk || bk.length < 1 || mk.length < 2) return null;
  const bookLast = bk[bk.length - 1][0];
  const mktLast = mk[mk.length - 1][0];
  const behind = mktLast - bookLast;
  if (!(behind >= VAS_LAG_MS)) return null;
  // How far the market travelled while this book stood still, in probability points.
  const moved = mk.filter((x) => x[0] >= bookLast);
  const drift = moved.length >= 2 ? Math.abs(moved[moved.length - 1][1] - moved[0][1]) : null;
  return { ms: behind, pts: drift != null ? drift * 100 : null };
}
function vasLagTxt(g, k, mkt) {
  const l = vasLagOf(g, k, mkt);
  if (!l) return null;
  const pts = l.pts != null && l.pts >= 0.5 ? `, and the market has moved ${l.pts.toFixed(1)} points since` : '';
  return `${bookName(k)} has not moved in ${vasAgo(l.ms)}${pts}.`;
}
const VAS_TURN = /^(INT|FUM|FUMR|TO)/i;
function vasSwing(g) {
  if (!vasLive(g) || g.home?.score == null || g.away?.score == null) return null;
  const turn = VAS_TURN.test(String(g.lastType || '')) ? String(g.lastType).toUpperCase() : null;
  const a = vasTrail.get(g.id);
  let moved = null;
  if (a && a.length > 1) {
    const t = serverNow(), cut = t - VAS_SWING_MS;
    let base = a[0][1];
    for (const [ts, m] of a) { if (ts <= cut) base = m; }
    const d = a[a.length - 1][1] - base;
    if (Math.abs(d) >= VAS_SWING_PTS) moved = d;
  }
  if (moved == null && !turn) return null;
  return {
    pts: moved == null ? null : Math.abs(moved),
    toward: moved == null ? null : moved > 0 ? 'home' : 'away',
    turnover: turn ? (/^INT/i.test(turn) ? 'interception' : 'fumble') : null,
  };
}

// ------------------------------------------------------------ Personnel: injuries and the QB gate
/* ESPN sends at most five names per team on the game summary, and the summary only exists for the game
   that is open, so this is the headline list and nothing else. Every rendering says so. */
function vasInj(g) {
  const sm = typeof S !== 'undefined' && S.game && S.game.game && S.game.game.id === g?.id ? S.game.summary : null;
  const src = sm && Array.isArray(sm.inj) ? sm.inj : null;
  if (!src) return null;
  const out = { home: [], away: [] };
  for (const t of src) {
    const side = String(t.team) === String(g.home?.id) ? 'home' : String(t.team) === String(g.away?.id) ? 'away' : null;
    if (side) out[side] = (t.rows || []).filter((r) => r && r.name);
  }
  return out.home.length || out.away.length ? out : null;
}
const VAS_OUT = /^(out|injured reserve|ir\b|suspension|suspended)/i;
const VAS_IFFY = /^(doubtful|questionable|probable|day)/i;
// The one hard gate the design keeps: a quarterback listed out voids every branch on that side.
function vasQbGate(g) {
  const inj = vasInj(g);
  if (!inj) return null;
  const out = [], iffy = [];
  for (const side of ['home', 'away']) {
    for (const r of inj[side]) {
      if (String(r.pos || '').toUpperCase() !== 'QB') continue;
      if (VAS_OUT.test(String(r.status || ''))) out.push({ side, ...r });
      else if (VAS_IFFY.test(String(r.status || ''))) iffy.push({ side, ...r });
    }
  }
  return out.length || iffy.length ? { out, iffy } : null;
}

/* ================================================================ WHO IS BEHIND

   The one thing measured on a real Sunday that is both common and useful: books do not move together.
   IND@KC, 3rd quarter - the market went 80.1% -> 84.0% on the home side over about two and a half
   minutes while FanDuel never moved off -460, and Caesars trailed by 4.8 points. That is not rare and it
   is not subtle. It is the ordinary texture of a live board.

   A price that has not caught up is the only kind of live edge a person without a co-located server can
   actually reach, and it announces itself BEFORE it is worth anything: the market moves, and some book
   sits there. This says which book is sitting, for how long, and - the part that makes it actionable -
   WHICH SIDE is still carrying the old number.

   It deliberately stops short of telling anyone to bet. A stale price is not automatically a good price;
   it is an old one, and old can be old in either direction. What this answers is "where should I be
   looking right now", which is a question a board can answer honestly and an EV number cannot.

   Two facts per book, both measured, neither predicted:
     behind   the market has moved more recently than this book has - by how long, and how far it went
     habit    when the market moves, how long this book has taken to follow, over this game so far

   `habit` is the part that is useful before anything happens. A book that has answered the market four
   times at a median of 71 seconds is a book worth having open when the next score lands. */
const VAS_LAG_MIN_DRIFT = 0.005;   // 0.5 probability points: below this the market has not really moved
const VAS_LAG_MIN_N = 2;           // responses needed before a median is worth printing

// When the market moved, how long did this book take to answer? Median over this game.
function vasResponse(gid, k, mkt) {
  const bk = vasPriceTrail.get(vasPriceKey(gid, k, mkt));
  const mk = vasPriceTrail.get(vasPriceKey(gid, '__mkt', mkt));
  if (!bk || !mk || mk.length < 2) return null;
  const gaps = [];
  for (let i = 1; i < mk.length; i++) {
    const tm = mk[i][0];
    if (Math.abs(mk[i][1] - mk[i - 1][1]) < VAS_LAG_MIN_DRIFT) continue;   // the market barely twitched
    const next = bk.find((x) => x[0] >= tm);
    if (next) gaps.push(next[0] - tm);
  }
  if (gaps.length < VAS_LAG_MIN_N) return null;
  gaps.sort((a, b) => a - b);
  const mid = gaps.length >> 1;
  return { ms: gaps.length % 2 ? gaps[mid] : (gaps[mid - 1] + gaps[mid]) / 2, n: gaps.length };
}

/* Which books are behind right now, and on which side. Bettable Nevada books only - a stale number at a
   book you cannot reach is trivia. */
function vasLagRows(g) {
  if (!vasLive(g) || !vasReady() || typeof serverNow !== 'function') return [];
  const src = vasLiveBooks(g);
  const out = [];
  for (const k of vasBettable()) {
    const L = src[k];
    if (!L || L.m) continue;
    for (const mkt of ['ml', 's', 't']) {
      const mk = vasPriceTrail.get(vasPriceKey(g.id, '__mkt', mkt));
      const bk = vasPriceTrail.get(vasPriceKey(g.id, k, mkt));
      if (!mk || !bk || mk.length < 2 || !bk.length) continue;
      const bookLast = bk[bk.length - 1][0];
      const moved = mk.filter((x) => x[0] >= bookLast);
      const behind = mk[mk.length - 1][0] - bookLast;
      const drift = moved.length >= 2 ? moved[moved.length - 1][1] - moved[0][1] : 0;
      const habit = vasResponse(g.id, k, mkt);
      if (behind < VAS_LAG_MS || Math.abs(drift) < VAS_LAG_MIN_DRIFT) {
        if (habit) out.push({ gid: g.id, book: k, mkt, behind: 0, drift: 0, habit, quiet: true });
        continue;
      }
      /* The direction is the whole point. The trail stores the probability of side A (home, or over).
         If the market drifted UP on A, the lagging book still has A at the older, cheaper number, so A
         is the side still carrying the stale price. Down, and it is the other side. */
      const [A, B] = mkt === 't' ? ['over', 'under'] : ['home', 'away'];
      const side = drift > 0 ? A : B;
      const px = sideOf(L, mkt, side);
      out.push({
        gid: g.id, book: k, mkt, side, behind, drift: Math.abs(drift) * 100, habit,
        line: px ? px.line : null, odds: px ? px.odds : null, quiet: false,
      });
    }
  }
  return out.sort((a, b) => (b.drift - a.drift) || (b.behind - a.behind));
}

function vasSideWord(g, mkt, side, line) {
  try { return vasPick(g, mkt, side, line); } catch { return `${side} ${mkt}`; }
}

// One game's lag block, for the game sheet.
function vasLagPanel(g) {
  const rows = vasLagRows(g);
  const live = rows.filter((r) => !r.quiet).slice(0, 4);
  const seen = new Set();
  const habitRows = rows.filter((r) => r.habit).filter((r) => { const k = r.book + r.mkt; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 6);
  if (!live.length && !habitRows.length) return '';
  const lagLi = (r) => `<li class="vas-lag-row">
    <b>${esc(bookName(r.book))}</b>
    <span class="vas-lag-n">${esc(vasAgo(r.behind))} behind</span>
    <span class="vas-lag-d">market moved ${r.drift.toFixed(1)} pts</span>
    ${r.odds != null ? `<span class="vas-lag-s">still ${esc(vasSideWord(g, r.mkt, r.side, r.line))} at ${esc(fmtOdds(r.odds))}</span>` : ''}
  </li>`;
  /* A book that turns with the median is not "following it in 0 seconds" — it is one of the books the
     median is made of. Say that instead of printing a number that reads like a stopwatch error. */
  const habitTxt = (h) => (h.ms < 5000 ? 'moves with the market' : `follows the market in ${vasAgo(h.ms)}`);
  const habitLi = (r) => `<li class="vas-lag-row vas-lag-habit">
    <b>${esc(bookName(r.book))}</b>
    <span class="vas-lag-n">${esc(habitTxt(r.habit))}</span>
    <span class="vas-lag-d">over ${esc(plural(r.habit.n, 'market move'))}</span>
  </li>`;
  return `<div class="vas-lag">
    <h4 class="vas-h4">Who is behind</h4>
    ${live.length
      ? `<ul class="vas-lag-list">${live.map(lagLi).join('')}</ul>`
      : '<p class="vas-lag-none">Every book here has kept up with the last move.</p>'}
    ${habitRows.length ? `<ul class="vas-lag-list vas-lag-habits">${habitRows.map(habitLi).join('')}</ul>` : ''}
    <p class="vas-fine">Measured from the prices themselves: how long since each book last moved, against a market that has. A number that has not caught up is old, not automatically good &mdash; it can be old in either direction. This says where to look, never what to back.</p>
  </div>`;
}

// The ranked strip across every live game, for the Live tab.
function vasLagStrip() {
  let games = [];
  try { games = allGames().filter(vasLive); } catch { return ''; }
  const rows = [];
  for (const g of games) for (const r of vasLagRows(g)) if (!r.quiet) rows.push({ ...r, g });
  if (!rows.length) return '';
  rows.sort((a, b) => (b.drift - a.drift) || (b.behind - a.behind));
  return `<section class="vas-lagstrip" aria-label="Books behind the market">
    <div class="vas-head"><h3 class="vas-t">Behind the market</h3><span class="vas-sub">measured from the prices, not predicted</span></div>
    <ul class="vas-lag-list">${rows.slice(0, 5).map((r) => `<li class="vas-lag-row">
      <button type="button" class="vas-lag-go" data-open="${esc(r.g.id)}" aria-label="${esc(`${bookName(r.book)} is ${vasAgo(r.behind)} behind in ${vasAbbr(r.g, 'away')} at ${vasAbbr(r.g, 'home')}`)}">
        <span class="vas-lag-gm">${esc(vasAbbr(r.g, 'away'))}@${esc(vasAbbr(r.g, 'home'))}</span>
        <b>${esc(bookName(r.book))}</b>
        <span class="vas-lag-n">${esc(vasAgo(r.behind))} behind</span>
        <span class="vas-lag-d">market moved ${r.drift.toFixed(1)} pts</span>
        ${r.odds != null ? `<span class="vas-lag-s">still ${esc(vasSideWord(r.g, r.mkt, r.side, r.line))} at ${esc(fmtOdds(r.odds))}</span>` : ''}
      </button>
    </li>`).join('')}</ul>
  </section>`;
}

// ------------------------------------------------------------ the sharp price, live
/* edgeFair() reads g.books, which on a live game is PREGAME data. Wiring it up as-is would silently
   cross-check a live price against kickoff lines, so the live anchor is computed here instead. */
function vasTrueAge(g, L, key) {
  if (L && Number.isFinite(L.age)) return { ms: Math.max(0, L.age), proven: true };
  if (key === 'pin') return { ms: L && L.seen ? serverNow() - L.seen : null, proven: false }; // CDN-cached: our poll time proves nothing
  const at = vasFeedAt(g);
  if (at) return { ms: Math.max(0, serverNow() - at), proven: true };   // Action Network is a live feed
  if (L && L.seen) return { ms: serverNow() - L.seen, proven: false };
  return { ms: null, proven: false };
}
function vasFeedAt(g) {
  const at = typeof S !== 'undefined' && S.at ? S.at[g?.wk] : null;
  const v = at && typeof at === 'object' ? at.an : at;
  return Number.isFinite(v) ? v : null;
}
// Pinnacle's live limit only. g.pinLimit is the last PREGAME limit and must never be shown on a live card.
function vasLiveLimit(g, key) {
  if (key !== 'pin') return null;
  const src = vasLiveBooks(g);
  return vasFin(src.pin?.limit) ?? vasFin(g?.pinLiveLimit) ?? null;
}
/* The peer market as an anchor of last resort.

   MEASURED 2026-09-20, IND@KC 3rd quarter: the consensus moved 80.1%% -> 84.0%% on the home side while
   FanDuel sat frozen at -460 for two and a half minutes (6.4 probability points behind) and Caesars lagged
   4.8. Pinnacle quoted no live moneyline at all for that whole window. That is the shape of a live edge in
   this sport: a SLOW BOOK, not a sharp disagreement — and it is invisible to an engine that can only
   measure against Pinnacle.

   This is deliberately not as good as a sharp price and is never presented as one. The median of the other
   live books is a market average that includes soft books, so it pays a higher EV bar (VAS_LIVE_EV_PEER),
   needs VAS_PEER_MIN of them, and reports itself as "the live market", never as a book name.

   `exclude` is the whole point: the book being measured must not be inside its own anchor, or it is being
   compared against a number it helped set. */
function vasPeerFair(g, mkt, exclude) {
  const src = vasLiveBooks(g);
  const [a, b] = mkt === 't' ? ['over', 'under'] : ['home', 'away'];
  const rows = [];
  for (const k of Object.keys(src)) {
    if (k === exclude || k === 'cons' || k === 'open') continue;   // cons is an aggregate: it contains `exclude`
    const L = src[k];
    if (!L || L.m) continue;
    const age = vasTrueAge(g, L, k);
    if (!age.proven || !Number.isFinite(age.ms) || age.ms > VAS_LIVE_FRESH) continue;   // gate 1 still applies
    const pa = sideOf(L, mkt, a), pb = sideOf(L, mkt, b);
    if (!pa || !pb || pa.odds == null || pb.odds == null) continue;
    if (mkt !== 'ml' && pa.line == null) continue;
    const p = vasDevig(mkt, pa.odds, pb.odds);
    if (p == null || !(p > 0 && p < 1)) continue;
    // A book holding 12% is not quoting a considered price, it is quoting a wide one. De-vigging it
    // produces a number with no information in it, and three of those make a confident-looking anchor
    // out of nothing.
    const h = noVig(pa.odds, pb.odds)?.hold;
    if (Number.isFinite(h) && h > VAS_MAX_HOLD) continue;
    rows.push({ p, line: pa.line, age: age.ms, hold: Number.isFinite(h) ? h : null });
  }
  if (rows.length < VAS_PEER_MIN) return null;
  // Same-number rule: a spread or total anchor is only meaningful among books hanging the SAME line.
  let use = rows;
  if (mkt !== 'ml') {
    const byLine = new Map();
    for (const r of rows) byLine.set(r.line, [...(byLine.get(r.line) || []), r]);
    use = [...byLine.values()].sort((x, y) => y.length - x.length)[0] || [];
    if (use.length < VAS_PEER_MIN) return null;
  }
  const ps = use.map((r) => r.p).sort((x, y) => x - y);
  const mid = ps.length >> 1;
  const med = ps.length % 2 ? ps[mid] : (ps[mid - 1] + ps[mid]) / 2;
  /* How much the anchor itself could be wrong.

     A median of three books is not a fact, it is an estimate, and the books' own disagreement is the
     only honest measure of how good an estimate it is. Spread of 0.2 points across six books and spread
     of 3 points across three books produce the same median and are not remotely the same number — but a
     bare EV figure shows them identically, which is how a tool talks someone into a thin bet.

     Dispersion is the median absolute deviation (robust: one stray book cannot inflate it), scaled to a
     standard deviation, floored so we never claim more precision than the books have earned. The median's
     standard error carries the usual 1.2533 factor. */
  const devs = ps.map((x) => Math.abs(x - med)).sort((x, y) => x - y);
  const dmid = devs.length >> 1;
  const mad = devs.length % 2 ? devs[dmid] : (devs[dmid - 1] + devs[dmid]) / 2;
  const range = (ps[ps.length - 1] - ps[0]) / 2;
  const sd = Math.max(mad * 1.4826, mad > 0 ? 0 : range, VAS_SD_FLOOR);
  const se = (1.2533 * sd) / Math.sqrt(ps.length);
  const clamp = (v) => Math.min(0.999, Math.max(0.001, v));
  return {
    book: 'peer', peer: true, n: use.length, line: mkt === 'ml' ? null : use[0].line, sideA: a,
    p: med, pLo: clamp(med - VAS_ANCHOR_Z * se), pHi: clamp(med + VAS_ANCHOR_Z * se), sd, se,
    spread: (ps[ps.length - 1] - ps[0]) * 100,
    age: Math.max(...use.map((r) => r.age)), limit: null,
  };
}
function vasLiveFair(g, mkt) {
  if (!vasLive(g) || !vasReady() || (mkt !== 's' && mkt !== 't' && mkt !== 'ml')) return null;
  const src = vasLiveBooks(g);
  const [a, b] = mkt === 't' ? ['over', 'under'] : ['home', 'away'];
  for (const k of VAS_SHARP) {
    const L = src[k];
    if (!L || L.m) continue;
    const age = vasTrueAge(g, L, k);
    if (!age.proven || !Number.isFinite(age.ms) || age.ms > VAS_LIVE_FRESH) continue;   // gate 1
    const pa = sideOf(L, mkt, a), pb = sideOf(L, mkt, b);
    if (!pa || !pb || pa.odds == null || pb.odds == null) continue;
    if (mkt !== 'ml' && pa.line == null) continue;
    const p = vasDevig(mkt, pa.odds, pb.odds);
    if (p == null || !(p > 0 && p < 1)) continue;
    return { book: k, line: pa.line, p, sideA: a, age: age.ms, limit: vasLiveLimit(g, k) };
  }
  return null;
}
// Why there is no live anchor, in words. Silence explained, not silence unexplained.
function vasNoFairTxt(g) {
  const src = vasLiveBooks(g);
  for (const k of VAS_SHARP) {
    const L = src[k];
    if (!L || L.m) continue;
    const age = vasTrueAge(g, L, k);
    if (!age.proven) return `${bookName(k)} is quoting, but nothing proves how old that price is — it is not a live feed.`;
    if (Number.isFinite(age.ms) && age.ms > VAS_LIVE_FRESH) return `${bookName(k)}'s live price is ${vasAgo(age.ms)} old — too old to measure against.`;
  }
  const quoting = Object.keys(vasLiveBooks(g)).filter((k) => k !== 'cons' && k !== 'open' && !VAS_SHARP.includes(k));
  const sharp = VAS_SHARP.map((k) => bookName(k)).join(' nor ');
  return quoting.length
    ? `Neither ${sharp} is quoting this game live, so there is no sharp number to measure ${quoting.map(bookName).join(', ')} against.`
    : `Neither ${sharp} is quoting this game live, so there is no sharp number to measure against.`;
}

// The live market as a veto, never as "fair". Same number only.
function vasLiveVeto(g, mkt, side, line, exclude) {
  const src = vasLiveBooks(g);
  const other = { home: 'away', away: 'home', over: 'under', under: 'over' }[side];
  const at = (k) => {
    const L = src[k];
    if (!L || L.m) return null;
    const a = sideOf(L, mkt, side), b = sideOf(L, mkt, other);
    if (!a || !b || a.odds == null || b.odds == null) return null;
    if (mkt !== 'ml' && a.line !== line) return null;
    const p = vasDevig(mkt, a.odds, b.odds);
    return p != null && p > 0 && p < 1 ? p : null;
  };
  // The published consensus is an aggregate we cannot take `exclude` back out of, so a book is partly
  // vetoed by itself. Peers we can actually exclude are worth more here; cons is the fallback.
  const ps = [];
  for (const k of Object.keys(src)) {
    if (k === exclude || k === 'cons' || k === 'open' || VAS_SHARP.includes(k)) continue;
    const p = at(k);
    if (p != null) ps.push(p);
  }
  if (ps.length < 2) {
    const cons = at('cons');
    return cons != null ? { p: cons, from: 'the live market consensus', n: 1 } : null;
  }
  ps.sort((x, y) => x - y);
  const mid = ps.length >> 1;
  return { p: ps.length % 2 ? ps[mid] : (ps[mid - 1] + ps[mid]) / 2, from: `the ${ps.length} other live books`, n: ps.length };
}

// ------------------------------------------------------------ prices that clear the bar
function vasBettable() {
  try { return visibleBooks().filter((b) => b.vegas).map((b) => b.key); } catch { return []; }
}
/* Live. Pure arithmetic against a provably fresh sharp no-vig price at the SAME number, vetoed by the
   live consensus. No model runs anywhere in here: there is no calibrated one for a remaining-game line. */
function vasLiveEdges(g) {
  if (!vasLive(g) || !vasReady()) return [];
  const src = vasLiveBooks(g);
  const books = vasBettable();
  const out = [];
  for (const mkt of ['s', 't', 'ml']) {
    // The sharp anchor is one number for the whole market. The peer anchor is not: it has to be rebuilt
    // for every book, because each book must be left out of the anchor it is measured against.
    const sharp = vasLiveFair(g, mkt);
    // The anchor depends on the book (which one is excluded), never on the side — so it is built once
    // per book here rather than once per book per side.
    for (const k of books) {
      const A = sharp || vasPeerFair(g, mkt, k);
      if (!A || k === A.book) continue;
      const L = src[k];
      if (!L || L.m) continue;
      for (const side of mkt === 't' ? ['over', 'under'] : ['home', 'away']) {
        const srcLine = mkt === 'ml' ? null : mkt === 't' ? A.line : side === 'home' ? A.line : -A.line;
        const px = sideOf(L, mkt, side);
        if (!px || px.odds == null || Math.abs(px.odds) < 100) continue;
        if (mkt === 'ml') {
          if (px.odds > VAS_ML_LONG || px.odds < VAS_ML_SHORT) continue;          // gate 5
        } else {
          if (px.line == null || px.line !== srcLine) continue;                   // gate 2
          if (Number.isInteger(px.line)) continue;                                // a push we cannot price
        }
        const p = side === A.sideA ? A.p : 1 - A.p;
        // The pessimistic end of the anchor for THIS side: the interval flips with the side.
        const pLo = A.peer && A.pLo != null ? (side === A.sideA ? A.pLo : 1 - A.pHi) : p;
        const d = dec(px.odds);
        if (!(p > 0 && p < 1) || !(d > 1)) continue;
        const ev = p * d - 1;
        const evLo = pLo * d - 1;
        const bar = A.peer ? VAS_LIVE_EV_PEER : VAS_LIVE_EV;                      // gate 3
        if (!(ev >= bar && ev <= VAS_EV_CAP)) continue;                           // gates 3 and 5
        // Gate 3b: the edge has to survive the anchor's own disagreement. If three books spread far
        // enough apart that the pessimistic end of their median is already negative, there is no edge
        // here — there is a wide market, and a wide market is not an opportunity.
        if (A.peer && !(evLo >= 0)) continue;
        const V = vasLiveVeto(g, mkt, side, px.line, k);                          // gate 4
        if (!V) continue;
        const evMkt = V.p * d - 1;
        if (!(evMkt >= 0)) continue;
        out.push({
          live: true, gid: g.id, mkt, side, line: px.line, odds: px.odds, book: k, ev, evMkt, p,
          src: A.book, peer: !!A.peer, peerN: A.n || 0, srcLine, srcAge: A.age, limit: A.limit,
          evLo, anchorSpread: A.spread ?? null, anchorSd: A.sd ?? null,
          lag: vasLagOf(g, k, mkt), veto: V, push: 0,
          // Stake off the pessimistic end of the anchor, never the point estimate. Kelly is famously
          // unforgiving about an overstated p, and a 3-book median is exactly the kind of p that gets
          // overstated. This under-bets slightly when the anchor is sharp and a lot when it is not,
          // which is the correct direction to be wrong in.
          kelly: typeof kellyStake === 'function' ? kellyStake(pLo, px.odds, 0, kellyCfg()) : null,
        });
      }
    }
  }
  return out.sort((x, y) => y.ev - x.ev);
}
/* Pregame. edge.js already does this arithmetic and ships it; all this adds is the corroboration gate
   set that a fired card has to clear. On a real board it returns nothing, most of the time. */
function vasPreEdges(g) {
  if (!vasPre(g) || typeof edgesFor !== 'function') return [];
  return edgesFor(g, true)
    .filter((e) => e.ev >= VAS_PRE_EV && e.ev <= VAS_EV_CAP && e.conf === 'solid' && e.mktN >= 2 && !e.onlyBook && e.evMkt != null && e.evMkt >= VAS_PRE_EVMKT)
    .map((e) => ({
      live: false, gid: g.id, mkt: e.mkt, side: e.side, line: e.line, odds: e.odds, book: e.book,
      ev: e.ev, evMkt: e.evMkt, p: e.p, src: e.src, srcLine: e.srcLine, srcAge: e.srcAge,
      limit: e.srcLimit, push: e.push, est: e.est, keyCrossed: e.keyCrossed, raw: e,
      kelly: typeof kellyStake === 'function' ? kellyStake(e.p, e.odds, e.push, kellyCfg()) : null,
    }))
    .sort((x, y) => y.ev - x.ev);
}
// The quiet list: measured gaps worth knowing about, well under the bar to become a card.
function vasQuiet(g) {
  if (!vasPre(g) || typeof edgesFor !== 'function') return [];
  const min = typeof kellyMinEdge === 'function' ? kellyMinEdge() : 0.01;
  return edgesFor(g).filter((e) => e.ev >= min && e.ev <= VAS_EV_CAP).sort((a, b) => b.ev - a.ev).slice(0, 3);
}

// Stake: never more than the sharpest book will actually take.
function vasStake(e) {
  const k = e && e.kelly;
  if (!k || !(k.pct > 0)) return null;
  const lim = Number.isFinite(e.limit) && e.limit > 0 ? e.limit : null;
  let dollars = k.dollars, held = k.capped ? 'cap' : null;
  if (dollars != null && lim != null && dollars > lim) { dollars = lim; held = 'limit'; }
  return { dollars, pct: k.pct, limit: lim, held };
}
function vasStakeTxt(s) {
  if (!s) return null;
  if (s.dollars == null) return `${(s.pct * 100).toFixed(1)}% of bankroll${s.held === 'cap' ? ' · held to your cap' : ''}`;
  return `${fmtMoney(s.dollars)}${s.held === 'limit' ? ' · held to the live limit' : s.held === 'cap' ? ' · held to your cap' : ''}`;
}

// The anchor's name. `peer` is not a book and must never be printed as one.
function vasSrcName(e) {
  if (!e) return '';
  if (e.peer || e.src === 'peer') return e.peerN ? `the live market (${e.peerN} books)` : 'the live market';
  return typeof bookName === 'function' ? bookName(e.src) : e.src;
}
// ------------------------------------------------------------ why: real values, rendered in words
function vasWhy(g, e) {
  const w = [];
  if (!e) return w;
  const src = vasSrcName(e);
  if (e.live) {
    const age = vasAgo(e.srcAge);
    w.push(e.peer
      ? `Measured against the median of ${e.peerN} other live books, with the cut removed — ${bookName(e.book)} is not in its own anchor. A market median, not a sharp price, so this one clears a higher bar.`
      : `Measured against ${src}'s live price${age ? `, ${age} old` : ''}, with the cut removed.`);
    w.push(e.mkt === 'ml'
      ? `${bookName(e.book)} ${fmtOdds(e.odds)} against ${src}'s two-sided price — no number to model across.`
      : `Same number: ${bookName(e.book)} at ${vasPick(g, e.mkt, e.side, e.line)}, ${src} at ${vasPick(g, e.mkt, e.side, e.srcLine)}.`);
    // What the anchor's own disagreement does to this number. A reader deserves to see the worse end.
    if (e.peer && Number.isFinite(e.evLo)) {
      w.push(e.anchorSpread != null && e.anchorSpread >= 0.1
        ? `Those ${e.peerN} books spread ${e.anchorSpread.toFixed(1)} points apart, and at the pessimistic end of that the price is still ${vasPct(e.evLo)} — the edge survives them disagreeing.`
        : `Those ${e.peerN} books agree closely, and the edge holds at ${vasPct(e.evLo)} even at the cautious end of the anchor.`);
      w.push('The stake below is sized off that cautious end, not the middle.');
    }
    // The most useful line on the card: a gap at a book that has stopped moving is lag, and lag closes.
    if (e.lag) {
      const pts = e.lag.pts != null && e.lag.pts >= 0.5 ? ` while the market moved ${e.lag.pts.toFixed(1)} points` : '';
      w.push(`${bookName(e.book)} has not moved in ${vasAgo(e.lag.ms)}${pts} — this reads as lag, not disagreement.`);
    }
    if (e.veto) w.push(`${e.veto.from.replace(/^the /, 'The ')} reads ${vasPct(e.evMkt)} on the same price, so the market is not contradicting it.`);
    if (e.limit != null) {
      const pre = vasFin(g.pinLimit);
      w.push(`${src} will take ${fmtMoney(e.limit)} on it — that is the whole live limit${pre && pre !== e.limit ? `, against ${fmtMoney(pre)} before kickoff` : ''}.`);
    } else w.push('No live limit published, so there is nothing to say about how much is available.');
  } else {
    if (typeof edgeReadTxt === 'function' && e.raw) w.push(`${edgeReadTxt(e.raw)}.`);
    else w.push(`Measured against ${src}'s price with the cut removed.`);
    const kc = e.keyCrossed ?? vasKeyBetween(e.line, e.srcLine);
    if (kc) w.push(`${kc} sits between ${bookName(e.book)}'s number and ${src}'s.`);
    if (e.evMkt != null) w.push(`The rest of the market reads ${vasPct(e.evMkt)} on the same price.`);
    if (e.limit != null) w.push(`${src} will take ${fmtMoney(e.limit)} on it.`);
    if (typeof edgeCaveats === 'function' && e.raw) for (const c of edgeCaveats(e.raw)) w.push(`${c}.`);
  }
  const sit = vasSitTxt(g);
  if (sit) w.push(sit);
  const score = vasScoreTxt(g);
  if (score && vasLive(g)) w.push(score);
  return w.filter(Boolean);
}
function vasExpires(g, b, e) {
  const bits = [];
  if (b && b.expires) bits.push(b.expires);
  if (e) {
    const moved = e.mkt === 'ml'
      ? `${bookName(e.book)} moves off ${fmtOdds(e.odds)}`
      : `${bookName(e.book)} moves off ${vasPick(g, e.mkt, e.side, e.line)}`;
    bits.push(bits.length ? `It also goes when ${moved}` : `It goes when ${moved}`);
    if (e.live) bits.push(`or when ${bookName(e.src)}'s price ages past ${Math.round(VAS_LIVE_FRESH / 1000)} seconds`);
  }
  return bits.length ? `${bits.join(', ')}.` : '';
}

// ------------------------------------------------------------ the vector rows
function vasVectors(g) {
  const qb = vasQbGate(g);
  const inj = vasInj(g);
  // Personnel — quarterback status and the headline injury list. The QB is the NFL's hard gate.
  let personnel = { mark: 'none', text: 'Nothing notable listed.' };
  if (qb && qb.out.length) {
    personnel = { mark: 'warn', text: qb.out.map((r) => `${vasAbbr(g, r.side)} ${r.name} (QB) ${String(r.status).toLowerCase()}`).join(' · ') };
  } else if (qb && qb.iffy.length) {
    personnel = { mark: 'warn', text: qb.iffy.map((r) => `${vasAbbr(g, r.side)} ${r.name} (QB) ${String(r.status).toLowerCase()}`).join(' · ') };
  } else if (inj) {
    const n = inj.home.length + inj.away.length;
    personnel = { mark: n ? 'ok' : 'none', text: n ? `${plural(n, 'name')} listed, no quarterback among them` : 'Nothing notable listed.' };
  } else {
    personnel = { mark: 'none', text: 'No injury list loaded for this game.' };
  }
  // Context — wind, roof, temperature. Facts about how the game gets played.
  const w = g.wx || null;
  let context = { mark: 'none', text: 'No forecast yet.' };
  if (w && w.dome) context = { mark: 'ok', text: 'Indoors — no wind, no weather.' };
  else if (w && ((w.wind ?? 0) >= VAS_WIND || (w.gust ?? 0) >= VAS_GUST)) {
    context = { mark: 'warn', text: `Wind ${w.wind ?? '—'} mph${w.dir ? ` from the ${w.dir}` : ''}${w.gust != null ? `, gusts ${w.gust}` : ''}` };
  } else if (w && (w.wind != null || w.temp != null)) {
    const bits = [w.wind != null ? `Wind ${w.wind} mph` : null, w.temp != null ? `${w.temp}°F` : null, w.pop != null ? `${w.pop}% rain` : null].filter(Boolean);
    context = { mark: 'none', text: bits.length ? `${bits.join(' · ')} — nothing notable` : 'Nothing notable.' };
  }
  // Fundamental — where the number actually sits. No EPA in this build, and nothing is invented to fill it.
  let fundamental = { mark: 'none', text: 'No priced-in edge to point at.' };
  const sp = vasSpreadNow(g), tot = vasTotalNow(g);
  const kt = vasKeyTxt(sp);
  if (sp != null) {
    const fav = sp < 0 ? 'home' : sp > 0 ? 'away' : null;
    const line = fav ? `${vasAbbr(g, fav)} ${fmtPts(-Math.abs(sp))}` : 'Pick';
    fundamental = { mark: kt ? 'ok' : 'none', text: `${line}${tot != null ? `, total ${fmtTot(tot)}` : ''}${kt ? ` — ${kt}` : ''}` };
  }
  return { personnel, context, fundamental };
}

// ------------------------------------------------------------ the branches
/* Generated per game from measurable state, never authored per game. A branch that can no longer happen
   is not returned at all: a tree of dead branches is exactly the wall of text this design avoids. */
function vasSpecs(g) {
  const live = vasLive(g), pre = vasPre(g);
  const m = vasMargin(g), am = Math.abs(m);
  const lead = vasLeader(g);
  const q = g.period || 0;
  const specs = [];

  // --- QB exit. The one hard gate; it outranks everything and carries no number.
  const qb = vasQbGate(g);
  if (!vasDead(g)) {
    const out = qb && qb.out.length ? qb.out : null;
    specs.push({
      key: 'qb',
      name: 'QB exit',
      voided: !!out,
      met: !!out,
      condition: out
        ? out.map((r) => `${vasAbbr(g, r.side)}: ${r.name} (QB) listed ${String(r.status).toLowerCase()}`).join(' · ')
        : 'A quarterback on either side stops being the passer of record',
      action: out
        ? `Void every ${out.map((r) => vasAbbr(g, r.side)).join(' and ')} side until you know who is taking snaps.`
        : 'Void every side that loses its quarterback.',
      because: ['This gate is a rule, not a read: the sharp price we would measure against was set for a different quarterback.'],
      mkts: [],
      note: 'ESPN lists up to five names per team, so this is the headline list, not the full report.',
      expires: 'It stays until ESPN updates the listing',
    });
  }

  // --- Clock. A double-digit lead after the first quarter means fewer possessions left to score in.
  const clockGone = !live && !pre ? true : live && q >= 4 && (g.secs ?? 900) < 120;
  if (!vasDead(g) && !clockGone) {
    const met = live && q >= 2 && am >= VAS_LEAD;
    const tot = vasTotalNow(g);
    const want = [{ mkt: 't', side: 'under' }];
    if (met && lead) want.push({ mkt: 's', side: lead });
    specs.push({
      key: 'clock',
      name: 'Clock',
      met,
      condition: met
        ? `${vasAbbr(g, lead)} leads by ${am} in the ${quarter(q)}`
        : `Either side leads by ${VAS_LEAD}+ after the first quarter`,
      action: met
        ? `Price the live under${tot != null ? ` ${fmtTot(tot)}` : ''}${lead ? ` and ${vasAbbr(g, lead)} on the live spread` : ''}.`
        : `Price the live under${tot != null ? ` — ${fmtTot(tot)} now` : ''}.`,
      because: ['A double-digit lead leaves fewer possessions to score in. That is a fact about the clock, not a forecast of the score.'],
      mkts: want,
      expires: `It goes if the lead drops under ${VAS_LEAD}, or inside two minutes of the fourth quarter`,
    });
  }

  // --- Shootout. Close at the half with the scoring already ahead of the number.
  const hm = g.half ? am : q >= 3 ? vasHalfMargin(g) : null;
  const pace = vasPace(g);
  const shootDead = live && (q >= 4 || (q >= 3 && hm != null && hm > VAS_CLOSE));
  if (!vasDead(g) && !shootDead) {
    const met = !!(live && hm != null && hm <= VAS_CLOSE && pace && pace.ahead);
    specs.push({
      key: 'shootout',
      name: 'Shootout',
      met,
      condition: met
        ? `Within ${hm} at the half, ${pace.pts} points in against a ${fmtTot(pace.total)} total`
        : `Tied or within ${VAS_CLOSE} at the half with the scoring ahead of the number`,
      action: 'Price the live over.',
      because: [
        ...(met ? [`${pace.on} points was the pace for that number at this point.`] : []),
        'A one-score game at the half keeps both offences throwing and the clock running. That is a fact about the script, not a forecast of the score.',
      ],
      mkts: [{ mkt: 't', side: 'over' }],
      expires: 'It goes at the end of the third quarter, or once the half ends more than a field goal apart',
    });
  }

  // --- Swing. A score or a turnover, and whether the book has caught up yet.
  if (live) {
    const sw = vasSwing(g);
    const bits = [];
    if (sw && sw.pts) bits.push(`the margin moved ${sw.pts} points in the last five minutes`);
    if (sw && sw.turnover) bits.push(`the last play was ${sw.turnover === 'interception' ? 'an' : 'a'} ${sw.turnover}`);
    specs.push({
      key: 'swing',
      name: 'Swing',
      met: !!sw,
      condition: sw ? `${bits.join(' and ')}`.replace(/^./, (c) => c.toUpperCase()) : `One score or a turnover moves the game by ${VAS_SWING_PTS}+`,
      action: 'Price both sides against the live sharp number.',
      because: [sw && sw.toward
        ? `The book that has not moved off ${vasAbbr(g, sw.toward === 'home' ? 'away' : 'home')} yet is the one to read.`
        : 'The moment one book lags the others is the whole window here, and it is short.'],
      mkts: [{ mkt: 's' }, { mkt: 'ml' }],
      expires: 'It goes five minutes after the play, or as soon as the book moves its number',
    });
  }

  // --- Wind. A standing fact about the stadium, true from the forecast onward.
  const w = g.wx || null;
  const windy = !!(w && !w.dome && ((w.wind ?? 0) >= VAS_WIND || (w.gust ?? 0) >= VAS_GUST));
  if (!vasDead(g) && windy) {
    const tot = vasTotalNow(g);
    specs.push({
      key: 'wind',
      name: 'Wind',
      met: true,
      condition: `Wind ${w.wind ?? '—'} mph${w.dir ? ` from the ${w.dir}` : ''}${w.gust != null ? `, gusts ${w.gust}` : ''}`,
      action: `Price the under${tot != null ? ` ${fmtTot(tot)}` : ''}.`,
      because: ['Wind is a fact about how far the ball travels, not a forecast of the score.'],
      mkts: [{ mkt: 't', side: 'under' }],
      expires: 'It goes if the forecast drops under 15 mph sustained, or the roof is closed',
    });
  }

  // --- Backdoor. Late, a two-score lead, and a number a single score reaches.
  if (live && q >= 4 && am >= VAS_BLOWOUT && lead) {
    const s = vasSpreadNow(g);
    const dog = lead === 'home' ? 'away' : 'home';
    const dogLine = s == null ? null : dog === 'home' ? s : -s;
    const need = dogLine == null ? null : Math.round((am - Math.abs(dogLine)) * 10) / 10;
    const met = need != null && need >= 0 && need <= VAS_SWING_PTS;
    if (dogLine == null || (need != null && need >= -VAS_SWING_PTS)) {
      specs.push({
        key: 'backdoor',
        name: 'Backdoor',
        met,
        condition: met
          ? `${vasAbbr(g, lead)} up ${am} in the fourth, ${vasPick(g, 's', dog, dogLine)} — one score reaches the number`
          : `${vasAbbr(g, lead)} up ${am} in the fourth, with the live spread inside a single score`,
        action: `Price ${dogLine == null ? `${vasAbbr(g, dog)}` : vasPick(g, 's', dog, dogLine)} on the live spread.`,
        because: met ? [`It needs ${need} point${need === 1 ? '' : 's'} of the margin back, and both 3 and 7 cover that.`] : [],
        mkts: [{ mkt: 's', side: dog }],
        expires: 'It goes if the lead moves outside a single score of the number, or at the final whistle',
      });
    }
  }
  return specs;
}

// ------------------------------------------------------------ the tree
function vasPickPrice(prices, want) {
  if (!want || !want.length) return null;
  let best = null;
  for (const e of prices) {
    if (!want.some((x) => x.mkt === e.mkt && (x.side == null || x.side === e.side))) continue;
    if (!best || e.ev > best.ev) best = e;
  }
  return best;
}
// Which markets a branch could be priced in, and whether any of them has a sharp anchor at all.
function vasAnchor(g, mkts) {
  if (!mkts || !mkts.length) return null;
  const live = vasLive(g);
  for (const w of mkts) {
    const F = live ? vasLiveFair(g, w.mkt) : typeof edgeFair === 'function' ? edgeFair(g, w.mkt) : null;
    if (F) return F;
  }
  return null;
}

/* A price that clears every gate but belongs to no narrative branch still has to surface: the
   measurement IS its own condition, and it is the only thing on this screen that was ever allowed to
   carry a number. Without this, a corroborated live edge would sit invisible because no branch in the
   catalogue happened to be true at that second. */
function vasPriceBranch(g, e) {
  const stake = vasStake(e);
  const pick = vasPick(g, e.mkt, e.side, e.line);
  const sharp = e.mkt === 'ml' ? `${bookName(e.src)}'s two-sided price` : `${bookName(e.src)}'s ${vasPick(g, e.mkt, e.side, e.srcLine)}`;
  const b = {
    key: `${g.id}:price:${e.mkt}:${e.side}:${e.line}:${e.odds}:${e.book}`,
    id: `${g.id}:price:${e.mkt}:${e.side}`,
    kind: 'price',
    name: 'Price',
    gid: g.id,
    state: 'fired',
    condition: `${bookName(e.book)} is hanging ${pick} at ${fmtOdds(e.odds)} against ${sharp}`,
    action: `Price ${pick} at ${bookName(e.book)} — ${vasEvTxt(e)} against ${bookName(e.src)}'s number${e.est ? ', modelled between the two numbers' : ' with the cut removed, measured at the same number'}.`,
    mkt: e.mkt,
    mkts: [{ mkt: e.mkt, side: e.side }],
    why: vasWhy(g, e),
    expiresWhen: vasExpires(g, null, e),
    side: e.side, line: e.line, odds: e.odds, book: e.book, ev: e.ev, evPct: vasEvTxt(e), evMkt: e.evMkt,
    limit: e.limit ?? null, stake: stake ? stake.dollars : null, stakeOf: stake,
    src: e.src, srcAge: e.srcAge, live: !!e.live, price: e,
  };
  return b;
}

/* Called from every paint, for every game, so the work is memoised on the game object. Games are
   replaced wholesale on each update, so a new object always recomputes; the time bucket is what lets a
   sharp price age out of its freshness window between updates. */
const vasMemo = new WeakMap();
function vasVer() {
  const k = typeof S !== 'undefined' ? S : null;
  return `${k?.lastMsg}|${k?.hidden ? [...k.hidden].sort().join(',') : ''}|${k?.books?.length}|${k?.game?.game?.id || ''}|${k?.game?.summary ? 1 : 0}|${Math.floor(serverNow() / 5e3)}`;
}
// The game's own volatile state, so a memo can never outlive a score, a snap or a clock.
const vasSig = (g) => `${g.state}|${g.period}|${g.secs}|${g.half ? 1 : 0}|${g.home?.score}|${g.away?.score}|${g.lastType}|${g.poss}|${g.sit?.down}|${g.sit?.dist}|${g.sit?.yl}`;
function vasTriggers(g) {
  if (g && g.id) {
    const v = `${vasVer()}|${vasSig(g)}`;
    const hit = vasMemo.get(g);
    if (hit && hit.v === v) return hit.t;
    const t = vasBuild(g);
    vasMemo.set(g, { v, t });
    return t;
  }
  return vasBuild(g);
}
function vasBuild(g) {
  const out = [];
  out.vectors = { personnel: { mark: 'none', text: '' }, context: { mark: 'none', text: '' }, fundamental: { mark: 'none', text: '' } };
  out.branches = out;
  if (!g || vasDead(g)) return out;
  vasNote(g);
  vasNotePrices(g);
  out.vectors = vasVectors(g);
  const live = vasLive(g);
  /* The Personnel VOID is a rule, not a read, and it blocks. While a quarterback is listed out, nothing
     in this game carries a number: the sharp price we would measure against was set for a different
     quarterback and has not necessarily moved yet. Totals go too — a total has no side, but it has no
     immunity either. */
  const blocked = !!(vasQbGate(g) || {}).out?.length;
  const prices = blocked ? [] : live ? vasLiveEdges(g) : vasPreEdges(g);
  const used = new Set();
  for (const spec of vasSpecs(g)) {
    let e = null;
    if (!spec.voided && spec.met) {
      const cand = vasPickPrice(prices.filter((x) => !used.has(`${x.mkt}|${x.side}|${x.book}|${x.line}|${x.odds}`)), spec.mkts);
      if (cand) { e = cand; used.add(`${cand.mkt}|${cand.side}|${cand.book}|${cand.line}|${cand.odds}`); }
    }
    const state = spec.voided ? 'void' : e ? 'fired' : spec.met ? 'watching' : 'armed';
    const anchor = spec.met && !e && !spec.voided ? vasAnchor(g, spec.mkts) : null;
    const why = e ? vasWhy(g, e) : [];
    if (state === 'watching') {
      if (!spec.mkts.length) why.push('Nothing to price here — this branch is a gate, not a bet.');
      else if (!anchor) why.push(live ? vasNoFairTxt(g) : 'No fresh sharp price to measure against right now.');
      else why.push(`${bookName(anchor.book)} is the sharp number and every bettable price is at or inside it — there is nothing to take.`);
      const sit = vasSitTxt(g);
      if (sit) why.push(sit);
    }
    for (const x of spec.because || []) why.push(x);
    if (spec.note) why.push(spec.note);
    const b = {
      key: `${g.id}:${spec.key}${e ? `:${e.mkt}:${e.side}:${e.line}:${e.odds}:${e.book}` : ''}`,
      id: `${g.id}:${spec.key}`,
      kind: spec.key,
      name: spec.name,
      gid: g.id,
      state,
      condition: spec.condition,
      action: spec.action,
      mkt: e ? e.mkt : spec.mkts[0] ? spec.mkts[0].mkt : null,
      mkts: spec.mkts,
      why,
      expiresWhen: vasExpires(g, spec, e),
    };
    if (e) {
      const stake = vasStake(e);
      Object.assign(b, {
        side: e.side, line: e.line, odds: e.odds, book: e.book, ev: e.ev, evPct: vasEvTxt(e),
        evMkt: e.evMkt, limit: e.limit ?? null, stake: stake ? stake.dollars : null, stakeOf: stake,
        src: e.src, srcAge: e.srcAge, live: !!e.live, price: e,
      });
    }
    out.push(b);
  }
  let spare = 0;
  for (const e of prices) {
    if (spare >= 3) break;
    const sig = `${e.mkt}|${e.side}|${e.book}|${e.line}|${e.odds}`;
    if (used.has(sig)) continue;
    used.add(sig);
    spare++;
    out.push(vasPriceBranch(g, e));
  }
  out.sort((a, b2) => (VAS_RANK[a.state] - VAS_RANK[b2.state]) || ((b2.ev ?? -1) - (a.ev ?? -1)) || a.kind.localeCompare(b2.kind));
  return out;
}
const vasTree = (g) => { const t = vasTriggers(g); return { vectors: t.vectors, branches: [...t] }; };

// ------------------------------------------------------------ words for the screen
function vasWhenTxt(g) {
  if (vasLive(g)) return vasSitTxt(g) || (typeof clockLabel === 'function' ? clockLabel(g) : '');
  if (vasPre(g)) return typeof edgeWhen === 'function' ? edgeWhen(g) : timeLabel(g.start);
  return typeof clockLabel === 'function' ? clockLabel(g) : '';
}
function vasLabel(g, b) {
  const who = `${g.away?.short || g.away?.abbr} at ${g.home?.short || g.home?.abbr}`;
  if (b.state === 'fired') {
    return `${who}. ${VAS_STATE[b.state]}. ${vasPick(g, b.mkt, b.side, b.line)} at ${fmtOdds(b.odds)}, ${bookName(b.book)}. Measured gap ${b.evPct} against ${bookName(b.src)}. ${b.condition}. Opens the game.`.split(MINUS).join('minus ');
  }
  return `${who}. ${VAS_STATE[b.state]}. ${b.condition}. ${b.action} Opens the game.`.split(MINUS).join('minus ');
}
const vasStateTag = (s) => `<span class="vas-state vas-s-${s}">${VAS_STATE[s] || ''}</span>`;

// One trigger card. Header is the tap target; the why sits beside it so the markup stays valid.
function vasCard(g, t) {
  if (!g || !t) return '';
  const fired = t.state === 'fired';
  const stake = t.stakeOf || null;
  const nums = [];
  if (fired) {
    const srcTxt = vasSrcName(t.price || t);
    nums.push(`<span class="vas-ev num">${esc(t.evPct)}</span> <span class="vas-vs">vs ${esc(srcTxt)}${!(t.price || t).peer && t.srcAge != null ? `, ${esc(vasAgo(t.srcAge))} old` : ''}</span>`);
    if (t.limit != null) nums.push(`<span class="vas-lim">limit <b class="num">${esc(fmtMoney(t.limit))}</b></span>`);
    if (stake) {
      const money = stake.dollars != null ? fmtMoney(stake.dollars) : `${(stake.pct * 100).toFixed(1)}% of bankroll`;
      const held = stake.held === 'limit' ? ' held to the live limit' : stake.held === 'cap' ? ' held to your cap' : '';
      nums.push(`<span class="vas-stake">stake <b class="num">${esc(money)}</b>${held ? `<span class="vas-held">${esc(held)}</span>` : ''}</span>`);
    }
  }
  return `<article class="vas-card vas-c-${esc(t.state)}" data-vas-key="${esc(t.key)}">
    <button type="button" class="vas-ch" data-open="${esc(g.id)}" aria-label="${esc(vasLabel(g, t))}">
      <span class="vas-who">${esc(vasAbbr(g, 'away'))} @ ${esc(vasAbbr(g, 'home'))}</span>
      ${vasStateTag(t.state)}
      ${fired ? `<b class="vas-pick">${esc(vasPick(g, t.mkt, t.side, t.line))}</b><span class="vas-odds num">${esc(fmtOdds(t.odds))}</span><span class="vas-book">${esc(bookName(t.book))}</span>` : `<span class="vas-cond">${esc(t.condition)}</span>`}
      <span class="vas-when">${esc(vasWhenTxt(g))}</span>
    </button>
    ${nums.length ? `<div class="vas-nums">${nums.join('<span class="vas-dot" aria-hidden="true">·</span>')}</div>` : ''}
    ${fired ? '' : `<p class="vas-act">${esc(t.action)}</p>`}
    <details class="vas-why"><summary>Why</summary>
      ${fired ? `<p class="vas-act">${esc(t.action)}</p>` : ''}
      <ul class="vas-wl">${t.why.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
      <p class="vas-exp">${esc(t.expiresWhen)}</p>
      ${fired ? '<p class="vas-fine">A measured gap against a sharp price, not a prediction. 21+. Gambling problem? Call 1-800-GAMBLER.</p>' : ''}
    </details>
  </article>`;
}

// One branch, as a line in the tree. Quiet by default, detail on tap.
function vasBranchRow(g, b) {
  const fired = b.state === 'fired';
  const head = fired
    ? `<b class="vas-pick">${esc(vasPick(g, b.mkt, b.side, b.line))}</b> <span class="vas-odds num">${esc(fmtOdds(b.odds))}</span> <span class="vas-book">${esc(bookName(b.book))}</span> <span class="vas-ev num">${esc(b.evPct)}</span>`
    : `<span class="vas-cond">${esc(b.condition)}</span>`;
  const extra = [];
  if (fired) {
    if (b.limit != null) extra.push(`limit ${fmtMoney(b.limit)}`);
    const s = b.stakeOf;
    if (s) {
      const money = s.dollars != null ? fmtMoney(s.dollars) : `${(s.pct * 100).toFixed(1)}% of bankroll`;
      extra.push(`stake ${money}${s.held === 'limit' ? ' (held to the live limit)' : s.held === 'cap' ? ' (held to your cap)' : ''}`);
    }
  }
  return `<li class="vas-branch vas-c-${esc(b.state)}" data-vas-key="${esc(b.key)}">
    <div class="vas-bh">${vasStateTag(b.state)}<span class="vas-bn">${esc(b.name)}</span>${head}</div>
    <p class="vas-act"><span class="vas-arrow" aria-hidden="true">→</span> ${esc(fired ? b.condition : b.action)}</p>
    ${extra.length ? `<p class="vas-nums">${esc(extra.join(' · '))}</p>` : ''}
    <details class="vas-why"><summary>Why</summary>
      ${fired ? `<p class="vas-act">${esc(b.action)}</p>` : ''}
      ${b.why.length ? `<ul class="vas-wl">${b.why.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      <p class="vas-exp">${esc(b.expiresWhen)}</p>
    </details>
  </li>`;
}

function vasVectorRow(k, label, v) {
  return `<div class="vas-vec vas-m-${esc(v.mark)}" aria-label="${esc(`${label}: ${VAS_MARK_TXT[v.mark]}. ${v.text}`)}">
    <span class="vas-mark" aria-hidden="true">${esc(VAS_MARK[v.mark])}</span>
    <span class="vas-vk">${esc(label)}</span>
    <span class="vas-vt">${esc(v.text)}</span>
  </div>`;
}

// The quiet measured-edge rows: arithmetic, no card, no stake.
function vasQuietRows(g) {
  const rows = vasQuiet(g);
  if (!rows.length) return '';
  return `<div class="vas-meas">
    <h4 class="vas-h4">Measured price edge</h4>
    <ul class="vas-ml">${rows.map((e) => `<li><b>${esc(vasPick(g, e.mkt, e.side, e.line))}</b> <span class="num">${esc(fmtOdds(e.odds))}</span> <span class="vas-book">${esc(bookName(e.book))}</span> <span class="num vas-ev">${esc(vasEvTxt(e))}</span> <span class="vas-vs">vs ${esc(vasSrcName(e))}</span></li>`).join('')}</ul>
    <p class="vas-fine">The gap between the price and the sharp no-vig price. Arithmetic, not a forecast, and it is below the bar to become a card.</p>
  </div>`;
}

// Context: what is factually known about this game, every minute of it.
function vasContext(g) {
  const bits = [];
  const w = g.wx || null;
  if (w && w.dome) bits.push('Indoors');
  else if (w && (w.wind != null || w.temp != null)) {
    bits.push([w.wind != null ? `Wind ${w.wind} mph${w.dir ? ` ${w.dir}` : ''}` : null, w.gust != null ? `gusts ${w.gust}` : null, w.temp != null ? `${w.temp}°F` : null, w.pop != null ? `${w.pop}% rain` : null].filter(Boolean).join(' · '));
  }
  if (g.venue?.name) bits.push(`${g.venue.name}${g.venue.city ? `, ${g.venue.city}` : ''}${g.neutral ? ' · neutral site' : ''}`);
  if (g.home?.rec || g.away?.rec) bits.push(`${vasAbbr(g, 'away')} ${g.away.rec || '—'} · ${vasAbbr(g, 'home')} ${g.home.rec || '—'}`);
  const sit = vasSitTxt(g);
  if (sit) bits.unshift(sit);
  const score = vasScoreTxt(g);
  if (score && vasLive(g)) bits.unshift(score);
  const inj = vasInj(g);
  let injHtml = '';
  if (inj) {
    const list = (side) => inj[side].map((r) => `${r.name}${r.pos ? ` (${r.pos})` : ''}${r.status ? ` — ${r.status}` : ''}`);
    const rows = [['away', list('away')], ['home', list('home')]].filter(([, l]) => l.length);
    if (rows.length) {
      injHtml = `<div class="vas-inj"><h4 class="vas-h4">Injuries</h4>${rows.map(([s, l]) => `<p><b>${esc(vasAbbr(g, s))}</b> ${esc(l.join(' · '))}</p>`).join('')}<p class="vas-fine">ESPN lists up to five per team, so this is the headline list, not the full report.</p></div>`;
    }
  }
  if (!bits.length && !injHtml) return '';
  return `<div class="vas-ctx">${bits.length ? `<p class="vas-facts">${esc(bits.join(' · '))}</p>` : ''}${injHtml}</div>`;
}

// The VAS block for one game: vectors, the tree, the facts, the measured edge.
function vasPanel(g) {
  if (!g || vasDead(g)) return '';
  const t = vasTriggers(g);
  const v = t.vectors;
  const rest = t.filter((b) => b.state !== 'fired' && b.state !== 'void');
  const top = t.filter((b) => b.state === 'fired' || b.state === 'void');
  const when = vasLive(g) ? 'live' : vasPre(g) ? 'armed · pre-kick' : '';
  return `<section class="vas-panel" aria-label="VAS — ${esc(vasAbbr(g, 'away'))} at ${esc(vasAbbr(g, 'home'))}">
    <div class="vas-head"><h3 class="vas-t">VAS</h3>${when ? `<span class="vas-sub">${esc(when)}</span>` : ''}</div>
    <div class="vas-vectors">
      ${vasVectorRow('personnel', 'Personnel', v.personnel)}
      ${vasVectorRow('context', 'Context', v.context)}
      ${vasVectorRow('fundamental', 'Fundamental', v.fundamental)}
    </div>
    ${t.length ? `<ol class="vas-tree">${[...top, ...rest].map((b) => vasBranchRow(g, b)).join('')}</ol>` : ''}
    ${vasLagPanel(g)}
    ${vasContext(g)}
    ${vasQuietRows(g)}
    <p class="vas-fine">Branches name a condition to watch and a market to price when it happens. Nothing here predicts a result: a branch only carries a number when a bettable price is measurably off a fresh sharp price.</p>
  </section>`;
}

// The ranked live list across every live game. '' when nothing qualifies — the caller renders nothing.
function vasLiveStrip() {
  if (typeof allGames !== 'function') return '';
  let games = [];
  try { games = allGames().filter(vasLive); } catch { return ''; }
  const rows = [];
  for (const g of games) {
    const t = vasTriggers(g);
    const act = t.filter((b) => b.state === 'fired' || b.state === 'void');
    if (!act.length) continue;
    rows.push({ g, top: act[0], more: act.slice(1) });
  }
  if (!rows.length) return '';
  rows.sort((a, b) => (VAS_RANK[a.top.state] - VAS_RANK[b.top.state]) || ((b.top.ev ?? -1) - (a.top.ev ?? -1)));
  const shown = rows.slice(0, VAS_MAX_CARDS);
  const over = rows.length - shown.length;
  const cards = shown.map(({ g, top, more }) => `${vasCard(g, top)}${more.length ? `<details class="vas-more"><summary>+${more.length} more in this game</summary>${more.map((b) => vasCard(g, b)).join('')}</details>` : ''}`).join('');
  return `<section class="vas-strip" aria-label="Live triggers">
    <div class="vas-head"><h3 class="vas-t">Live triggers</h3><span class="vas-sub">${esc(plural(rows.length, 'game'))} · ranked by the measured gap</span></div>
    ${cards}
    ${over > 0 ? `<p class="vas-overflow">${esc(plural(over, 'more live edge', 'more live edges'))} below the top ${VAS_MAX_CARDS}.</p>` : ''}
  </section>`;
}

/* ------------------------------------------------------------------ wiring
   The live strip's host on the Live tab. Mirrors edgeLive() in edge.js — same insertion rules, so the
   two sit together under "On the field" and neither one fights the other for position.

   VAS_SHOW_CARDS is the build gate from the spec, expressed as one flag rather than scattered edits.
   Flip it to false and the engine still runs and still logs; the cards simply do not render. That is
   the intended state until the live model has evidence behind it. Nothing in the UI explains the
   difference, because a feature that is not present needs no announcement. */
const VAS_SHOW_CARDS = true;

function vasRenderLive() {
  const view = document.getElementById('view-live');
  if (!view) return;
  let sec = document.getElementById('vasTop');
  if (!sec) {
    sec = document.createElement('section');
    sec.id = 'vasTop';
    sec.className = 'vas-top';
    sec.setAttribute('aria-label', 'Live triggers');
    const after = document.getElementById('edgeTop') || document.getElementById('liveSec') || document.getElementById('hero');
    if (after && after.parentNode) after.parentNode.insertBefore(sec, after.nextSibling);
    else view.appendChild(sec);
  }
  let html = '';
  // A throw in here must never take the Live tab down with it: the strip is an extra, not the page.
  try { html = (VAS_SHOW_CARDS ? vasLiveStrip() : '') + vasLagStrip(); }
  catch (e) { html = ''; if (typeof console !== 'undefined') console.warn('vas: live strip failed', e); }
  if (sec.dataset.html !== html) { sec.innerHTML = html; sec.dataset.html = html; }
  sec.hidden = !html;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { vasTriggers, vasTree, vasCard, vasPanel, vasLiveStrip, vasRenderLive, vasLagRows, vasLagPanel, vasLagStrip, vasResponse };
}
