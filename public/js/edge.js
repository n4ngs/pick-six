'use strict';
/* Pick Six — Edge Finder: how each book's price compares with the sharp price, honestly.

   The sharp price is Pinnacle's (else Circa's) with the bookmaker's cut removed, and only when that price is fresh
   (listed by the source in the last 10 minutes). If neither sharp book is fresh, no comparison is made: the market
   average is never used as "fair", since it's built from the very books being scored.

   Gap = expected return per $1 at that price if the sharp price is right: P(win) × decimal odds + P(push) − 1.
   When a book hangs a different number than the sharp one, a model moves between numbers: a normal curve of final
   margins (SIGMA points; 16.5 for totals) fitted to the sharp price, bumped only at the margins that history supports
   (3, 7, 10, 14). Moneylines remove the cut with the power method (proportional removal flatters underdogs).

   Every reading is an estimate, so each row says how sure it is:
     Solid      the gap is at least twice its uncertainty AND the rest of the market agrees (still +1% against the
                median of the other books) AND the sharp price is fresh with a real limit behind it.
     Thin       the gap is bigger than its uncertainty and the other books don't contradict it.
     Weak read  everything else. Hidden unless you ask for it.
   Uncertainty (1 sd, in edge): about 1.3% at the sharp number, 2.2% across numbers on a spread, 3% on a total,
   2.5% on moneyline underdogs, plus 0.5% when a key number is crossed.

   Presentation is informational by design: sorted by kickoff (not by size), whole percentages, no stake on the
   list, no alerts, and tapping a row opens the game rather than a bet slip. */

const EDGE_MIN = 0.005;           // scored from +0.5%; the user's setting chooses what's shown
const EDGE_MAX = 0.12;            // above this it's almost always a stale or broken price
const EDGE_MAX_GAP = 3;           // points between a book's line and the sharp line we'll model across
const EDGE_ML_LONG = 500;         // skip moneylines longer than +500
const EDGE_TOTAL_SD = 16.5;       // spread of final totals around the market total, points
const EDGE_SRC = ['pin', 'circa'];
const EDGE_SHARP_FRESH = 10 * 60e3;
const EDGE_KEYS = [3, 7, 10, 14]; // the only margins with enough history to trust a bump
const EDGE_MKTS = new Set(['s', 't', 'ml', 'h1s']);

// ------------------------------------------------------------ key-number shape from last season (spreads only)
let edgeLumpSrc = null, edgeLumpM = null;
function edgeLumpOf(hist) {
  const out = new Map();
  if (!hist) return out;
  const c = (v) => Number(hist[v]) || 0;
  for (const v of EDGE_KEYS) {
    let sum = 0, n = 0;
    for (let d = -3; d <= 3; d++) { const x = v + d; if (x >= 1) { sum += c(x); n++; } }
    if (sum < 25 || !n) continue;
    out.set(v, clamp(c(v) / (sum / n), 0.5, 3));
  }
  return out;
}
function edgeLumps() {
  if (edgeLumpSrc !== S.keys) { edgeLumpSrc = S.keys; edgeLumpM = S.keys?.n ? edgeLumpOf(S.keys.margin) : new Map(); }
  return edgeLumpM;
}
const edgeModeled = () => !!S.keys?.n;

// Probability of each integer outcome: home margins (no ties in NFL) or totals.
function edgePmf(kind, mu) {
  if (!Number.isFinite(mu)) return [];
  const L = kind === 's' ? edgeLumps() : null;
  const sd = kind === 's' ? SIGMA : EDGE_TOTAL_SD;
  const lo = kind === 's' ? Math.floor(mu - 5 * sd) : Math.max(0, Math.floor(mu - 5 * sd));
  const hi = Math.ceil(mu + 5 * sd);
  const pts = [];
  let z = 0;
  for (let v = lo; v <= hi; v++) {
    if (kind === 's' && v === 0) continue;
    const w = Math.exp(-0.5 * ((v - mu) / sd) ** 2) * (L?.get(Math.abs(v)) ?? 1);
    pts.push([v, w]); z += w;
  }
  return z > 0 ? pts.map(([v, w]) => [v, w / z]) : [];
}
// Win / push chances for "outcome + line > 0" (spread, home side) or "total > line" (over).
function edgeWP(pmf, kind, line) {
  let w = 0, p = 0;
  for (const [v, q] of pmf) {
    const x = kind === 's' ? v + line : v - line;
    if (x > 0) w += q; else if (x === 0) p += q;
  }
  return { w, p };
}
// Fit the curve's centre so it reproduces the sharp no-vig chance at the sharp number.
function edgeFit(kind, line, pNoVig) {
  let lo = kind === 's' ? -90 : 0, hi = kind === 's' ? 90 : 160;
  for (let i = 0; i < 36; i++) {
    const mid = (lo + hi) / 2;
    const { w, p } = edgeWP(edgePmf(kind, mid), kind, line);
    if (w / (1 - p || 1) < pNoVig) lo = mid; else hi = mid;
  }
  return edgePmf(kind, (lo + hi) / 2);
}
// Chance for side A with the cut removed. Moneylines use the power method: find k with pA^k + pB^k = 1.
/* Two prices in, one probability out — the calculation everything else here is built on.

   This used Shin's method as of 2026-09-20, replacing plain normalisation for spreads and totals and the
   power method for moneylines. Shin (1992,1993) treats the overround as the book protecting itself
   against informed money, which falls harder on the longshot; Strumbelj (2014) found it better calibrated
   than both of the methods it replaces. `shinNoVig` in core.js carries the derivation.

   The reason for changing it here was consistency rather than accuracy. Measured on a real board, the
   pregame effect is almost nothing — NFL pregame prices sit near -110 where every method agrees, no
   confidence tier moved and no solid row changed, the largest EV move was 0.31 points. But VAS prices a
   branch with the live path after kickoff and this path before it, into the same card. Two methods meant
   an edge could appear or vanish at kickoff because the arithmetic changed rather than the market.

   The old power method is kept as the fallback, so an odd market degrades instead of dropping out. */
function edgeNoVig(mkt, a, b) {
  const shin = shinNoVig(a, b);
  if (shin != null && shin > 0 && shin < 1) return shin;
  if (mkt !== 'ml') return noVig(a, b)?.a ?? null;
  const pa = imp(a), pb = imp(b);
  if (!(pa > 0 && pb > 0 && pa < 1 && pb < 1)) return null;
  let lo = 0.5, hi = 4;
  for (let i = 0; i < 50; i++) { const k = (lo + hi) / 2; if (pa ** k + pb ** k > 1) lo = k; else hi = k; }
  return pa ** ((lo + hi) / 2);
}

// ------------------------------------------------------------ the sharp price
const edgeSrcOf = (g, mkt) => (mkt === 'h1s' ? g.h1 : g.books) || {};
const edgeAgeOf = (L) => (L?.seen ? serverNow() - L.seen : null);
const edgeFairMemo = new WeakMap(); // game object -> { v, byMkt }
function edgeFair(g, mkt) {
  const v = edgeVer();
  let m = edgeFairMemo.get(g);
  if (!m || m.v !== v) { m = { v, byMkt: {} }; edgeFairMemo.set(g, m); }
  if (mkt in m.byMkt) return m.byMkt[mkt];
  let out = null;
  const src = edgeSrcOf(g, mkt);
  const [a, b] = mkt === 't' ? ['over', 'under'] : ['home', 'away'];
  for (const k of EDGE_SRC) {
    const L = src[k];
    const age = edgeAgeOf(L);
    if (!L || L.m || age == null || age > EDGE_SHARP_FRESH) continue; // sharp prices must be recent, and never typed in
    const pa = sideOf(L, mkt, a), pb = sideOf(L, mkt, b);
    if (!pa || !pb || pa.odds == null || pb.odds == null) continue;
    if (mkt !== 'ml' && pa.line == null) continue;
    const p = edgeNoVig(mkt, pa.odds, pb.odds);
    if (p == null) continue;
    out = { book: k, line: pa.line, p, sideA: a, age, limit: k === 'pin' ? g.pinLimit ?? null : null, pmf: null };
    break;
  }
  m.byMkt[mkt] = out;
  return out;
}
const edgeCurve = (F, kind) => F.pmf || (F.pmf = edgeFit(kind, F.line, F.p));

// ------------------------------------------------------------ the rest of the market
// Median no-vig chance for this side among the other fresh books hanging this exact number.
function edgeMarketP(g, mkt, side, line, exclude) {
  const other = { home: 'away', away: 'home', over: 'under', under: 'over' }[side];
  const ps = [];
  for (const [k, L] of Object.entries(edgeSrcOf(g, mkt))) {
    if (k === exclude || k === 'cons' || k === 'open' || !L || L.m || isOld(L)) continue;
    const a = sideOf(L, mkt, side), b = sideOf(L, mkt, other);
    if (!a || !b || a.odds == null || b.odds == null) continue;
    if (mkt !== 'ml' && a.line !== line) continue;
    const p = edgeNoVig(mkt, a.odds, b.odds);
    if (p != null) ps.push(p);
  }
  if (ps.length < 2) return null;
  ps.sort((x, y) => x - y);
  const mid = ps.length >> 1;
  return { p: ps.length % 2 ? ps[mid] : (ps[mid - 1] + ps[mid]) / 2, n: ps.length };
}
// True when no other book offers this side at as good a number or price (a lone outlier is often a stale line).
function edgeOnlyBook(g, mkt, side, line, odds, book) {
  const d0 = dec(odds);
  for (const [k, L] of Object.entries(edgeSrcOf(g, mkt))) {
    if (k === book || k === 'cons' || k === 'open' || !L || isOld(L)) continue;
    const px = sideOf(L, mkt, side);
    if (!px || px.odds == null) continue;
    if (mkt !== 'ml') {
      if (px.line == null) continue;
      const better = mkt === 't' ? (side === 'over' ? px.line < line : px.line > line) : px.line > line;
      if (better) return false;
      if (px.line !== line) continue;
    }
    if (dec(px.odds) >= d0 - 0.05) return false;
  }
  return true;
}

// ------------------------------------------------------------ one price, fully read
// Used by the list, the bet slip and the "Most likely to hit" ranking, so they always agree.
function edgePrice(g, mkt, side, line, odds, book = null) {
  if (!g || !EDGE_MKTS.has(mkt) || odds == null || Math.abs(odds) < 100) return null;
  const F = edgeFair(g, mkt);
  if (!F) return null;
  const kind = mkt === 't' ? 't' : 's';
  const pSide = side === F.sideA ? F.p : 1 - F.p;
  const sLine = mkt === 'ml' ? null : mkt === 't' ? F.line : side === 'home' ? F.line : -F.line;
  const d = dec(odds);
  let w = pSide, push = 0, est = false, gap = 0;
  if (mkt !== 'ml') {
    if (line == null || !Number.isFinite(line)) return null;
    gap = Math.abs(line - sLine);
    if (line !== sLine) {
      if (mkt === 'h1s' || gap > EDGE_MAX_GAP) return null; // no first-half margin history to model with
      const pmf = edgeCurve(F, kind);
      const r = kind === 't' ? edgeWP(pmf, 't', line) : side === 'home' ? edgeWP(pmf, 's', line) : edgeWP(pmf, 's', -line);
      push = r.p;
      w = (kind === 't' && side === 'under') || (kind === 's' && side === 'away') ? 1 - r.w - r.p : r.w;
      est = true;
    } else if (Number.isInteger(line)) {
      if (mkt === 'h1s') return null; // a whole-number first half can push, and we can't price that
      const r = edgeWP(edgeCurve(F, kind), kind, kind === 's' && side === 'away' ? -line : line);
      push = r.p; w = pSide * (1 - push);
    }
  }
  const ev = w * d + push - 1;
  const M = edgeMarketP(g, mkt, side, mkt === 'ml' ? null : line, book);
  const evMkt = M ? M.p * (1 - push) * d + push - 1 : null;
  // how uncertain the reading is
  let sig = est ? (kind === 't' ? 0.03 : 0.022) : 0.013;
  if (mkt === 'ml' && odds >= 150) sig = Math.max(sig, 0.025);
  if (mkt === 'h1s') sig = Math.max(sig, 0.02);
  const lo = Math.min(Math.abs(line ?? 0), Math.abs(sLine ?? 0)), hi = Math.max(Math.abs(line ?? 0), Math.abs(sLine ?? 0));
  const keyCrossed = est && kind === 's' ? EDGE_KEYS.find((k) => lo <= k && k <= hi && lo !== hi) ?? null : null;
  if (keyCrossed) sig += 0.005;
  const lowLimit = F.book === 'pin' && F.limit != null && F.limit < 5000;
  const tinyLimit = F.book === 'pin' && F.limit != null && F.limit < 3000;
  let conf = ev >= 2 * sig && evMkt != null && evMkt >= 0.01 && !lowLimit ? 'solid' : ev >= sig && (evMkt == null || evMkt > 0) ? 'thin' : 'weak';
  if (tinyLimit && conf === 'thin') conf = 'weak';
  const pFair = w / (1 - push || 1);
  return {
    g, gid: g.id, mkt, side, book, line, odds, ev, evMkt, mktN: M?.n || 0, p: pFair, push, fairAm: probToAm(pFair),
    src: F.book, srcLine: sLine, srcAge: F.age, srcLimit: F.limit, est, gap, keyCrossed, lowLimit, sig, conf,
    onlyBook: book ? edgeOnlyBook(g, mkt, side, line, odds, book) : false,
    age: book ? edgeAgeOf(edgeSrcOf(g, mkt)[book]) : null,
  };
}

function edgeScoreGame(g) {
  const out = [];
  if (!g || !isPre(g) || g.state === 'off') return out;
  // The price has to be one you can actually take. Pinnacle, DraftKings and FanDuel don't book Nevada
  // bets, so they stay what lib/books.js calls them — reference. They set the fair number; they never
  // appear as the play.
  const books = visibleBooks().filter((b) => b.vegas).map((b) => b.key);
  for (const mkt of EDGE_MKTS) {
    const F = edgeFair(g, mkt);
    if (!F) continue;
    for (const side of mkt === 't' ? ['over', 'under'] : ['home', 'away']) {
      for (const k of books) {
        if (k === F.book) continue;
        const L = edgeSrcOf(g, mkt)[k];
        if (!L || isOld(L)) continue;
        const px = sideOf(L, mkt, side);
        if (!px || px.odds == null || Math.abs(px.odds) < 100) continue;
        if (mkt === 'ml' && px.odds > EDGE_ML_LONG) continue;
        const e = edgePrice(g, mkt, side, mkt === 'ml' ? null : px.line, px.odds, k);
        if (e && e.ev >= EDGE_MIN && e.ev <= EDGE_MAX) out.push(e);
      }
    }
  }
  return out;
}

// Memo: games are replaced on every update, so key on the object and on everything else the score reads.
const edgeMemo = new WeakMap();
const edgeVer = () => `${S.lastMsg}|${[...S.hidden].sort().join(',')}|${S.keys ? 1 : 0}|${S.books.length}|${Math.floor(serverNow() / 60e3)}`;
const edgeShowWeak = () => !!store.get('edgeWeak', false);
function edgesFor(g, all = false) {
  if (!g) return [];
  const v = edgeVer();
  let m = edgeMemo.get(g);
  if (!m || m.v !== v) { m = { v, list: edgeScoreGame(g) }; edgeMemo.set(g, m); }
  const min = kellyMinEdge();
  return m.list.filter((e) => e.ev >= min && (all || edgeShowWeak() || e.conf !== 'weak'));
}
// Rows for the list: the same price at several books is one row. Sorted by kickoff, then game, never by size.
function edgeRows(all = false) {
  const groups = new Map();
  for (const e of allGames().filter(isPre).flatMap((g) => edgesFor(g, all))) {
    const k = `${e.gid}|${e.mkt}|${e.side}|${e.line}|${e.odds}`;
    const r = groups.get(k);
    if (!r) groups.set(k, { ...e, books: [e.book] });
    else { r.books.push(e.book); if (e.onlyBook === false) r.onlyBook = false; r.onlyBook = r.onlyBook && r.books.length === 1; }
  }
  const rank = { solid: 0, thin: 1, weak: 2 };
  return [...groups.values()].sort((a, b) => Date.parse(a.g.start) - Date.parse(b.g.start) || a.gid.localeCompare(b.gid) || rank[a.conf] - rank[b.conf]);
}
const edgeAll = () => edgeRows();

// ------------------------------------------------------------ words
const EDGE_CONF = { solid: 'Solid', thin: 'Thin', weak: 'Weak read' };
const edgePctTxt = (e) => `${e.est ? '≈ ' : ''}+${Math.max(1, Math.round(e.ev * 100))}%`;
function edgePick(e) {
  const g = e.g;
  if (e.mkt === 't') return `${e.side === 'over' ? 'Over' : 'Under'} ${fmtTot(e.line)}`;
  const t = g[e.side].abbr;
  if (e.mkt === 'ml') return `${t} ML`;
  if (e.mkt === 'h1s') return `${t} 1H ${fmtPts(e.line)}`;
  return `${t} ${fmtPts(e.line)}`;
}
const edgeLineTxt = (e, v) => (e.mkt === 't' ? fmtTot(v) : fmtPts(v));
const edgeWhen = (g) => (g.tbd ? 'Time TBA' : `${dayLabel(g.start)} ${timeLabel(g.start)}`);
function edgeReadTxt(e) {
  const src = bookName(e.src);
  if (!e.est) return `${src}, no cut: ${fmtOdds(e.fairAm)}`;
  return `${edgeModeled() ? 'Model' : 'Rough model'}: about ${fmtOdds(e.fairAm)} here, from ${src} at ${edgeLineTxt(e, e.srcLine)}`;
}
// What could make this reading wrong, in plain words. At most three, most important first.
function edgeCaveats(e) {
  const c = [];
  if (e.evMkt != null && e.evMkt < 0) c.push('Other books disagree');
  if (e.mktN < 2) c.push('Few books to compare');
  if (e.onlyBook) c.push('Only book at this price');
  if (e.keyCrossed) c.push(`Across ${e.keyCrossed}`); else if (e.est) c.push(`Across ${trim(e.gap)} pt${e.gap === 1 ? '' : 's'}`);
  const age = e.age != null ? Math.round(e.age / 60e3) : null;
  if (age != null && age >= 5) c.push(`Price ${age} min old`);
  if (e.lowLimit) c.push('Low Pinnacle limit');
  if ((e.g.moves || []).some((m) => (m.mkt === e.mkt || (e.mkt === 'h1s' && m.mkt === 's')) && serverNow() - m.t < 3600e3)) c.push('Line moved in the last hour');
  if (e.mkt === 'h1s') c.push('First half, thinner market');
  if (e.mkt === 'ml' && e.odds >= 200) c.push('Long moneyline');
  return c.slice(0, 3);
}
function edgeLabel(e) {
  const pct = Math.max(1, Math.round(e.ev * 100));
  return `${e.books.map(bookFull).join(', ')}: ${edgePick(e)} at ${fmtOdds(e.odds)}. ${e.est ? 'About' : ''} ${pct} percent above the ${e.est ? 'estimated ' : ''}sharp price. ${EDGE_CONF[e.conf]}. ${edgeCaveats(e).join('. ')}. ${e.g.away.short} at ${e.g.home.short}, ${edgeWhen(e.g)}. Opens game details.`.replace(MINUS, 'minus ');
}
function edgeRow(e) {
  const g = e.g;
  const t = e.mkt === 't' ? g.home : g[e.side];
  const cav = edgeCaveats(e);
  return `<button type="button" class="edge-row c-${e.conf}" data-open="${esc(e.gid)}" aria-label="${esc(edgeLabel(e))}">
    ${logo(t, 'logo edge-logo')}
    <span class="edge-mid">
      <span class="edge-t"><b>${esc(edgePick(e))}</b> <span class="num">${esc(fmtOdds(e.odds))}</span> <span class="edge-bk">· ${esc(e.books.map(bookName).join(', '))}</span></span>
      <span class="edge-s">${esc(edgeReadTxt(e))}</span>
      ${cav.length ? `<span class="edge-c">${esc(cav.join(' · '))}</span>` : ''}
      <span class="edge-s">${esc(edgeWhen(g))} · ${esc(g.away.abbr)} @ ${esc(g.home.abbr)}</span>
    </span>
    <span class="edge-v"><span class="edge-p num">${esc(edgePctTxt(e))}</span><span class="edge-k">${esc(EDGE_CONF[e.conf])}</span></span>
  </button>`;
}

// ------------------------------------------------------------ Live tab: one quiet entry, no picks
const EDGE_EXPLAIN = 'An estimate of how each price compares with the sharp price after removing the bookmaker’s cut. Sharp prices are close, not exact, and small gaps are often noise.';
function edgeLive() {
  const view = $('#view-live');
  if (!view) return;
  let sec = $('#edgeTop');
  if (!sec) {
    sec = document.createElement('section');
    sec.id = 'edgeTop';
    sec.className = 'edge-top';
    sec.setAttribute('aria-label', 'Edge Finder');
    const after = $('#liveSec') || $('#hero');
    if (after?.parentNode) after.parentNode.insertBefore(sec, after.nextSibling); else view.appendChild(sec);
  }
  edgeDeepLink();
  const rows = edgeRows();
  const solid = rows.filter((e) => e.conf === 'solid').length;
  const sub = rows.length ? `${plural(rows.length, 'price')} differ from the sharp price${solid ? ` · ${solid} solid` : ''} · estimates` : 'Nothing notable against the sharp price right now';
  const html = `<button type="button" class="edge-entry" data-edge-all aria-label="Open Edge Finder. ${esc(sub)}"><span><b>Edge Finder</b><span>${esc(sub)}</span></span>${ICON.chev}</button>`;
  if (sec.dataset.html !== html) { sec.innerHTML = html; sec.dataset.html = html; }
}

// ------------------------------------------------------------ the list (sheet)
const EDGE_CHIPS = [['all', 'All'], ['s', 'Spread'], ['t', 'Total'], ['ml', 'Money']];
let edgeMkt = 'all', edgeLastPaint = 0, edgeTimer = 0, edgeLastHTML = '';
const edgeInChip = (e, f) => f === 'all' || (f === 's' ? e.mkt === 's' || e.mkt === 'h1s' : e.mkt === f);
function edgeSheetHTML() {
  const rows = edgeRows();
  const list = rows.filter((e) => edgeInChip(e, edgeMkt));
  const weakN = edgeShowWeak() ? 0 : edgeRows(true).filter((e) => e.conf === 'weak').length;
  const chips = EDGE_CHIPS.map(([k, l]) => `<button type="button" class="chip" data-edge-mkt="${k}" aria-pressed="${edgeMkt === k}">${esc(l)}<small class="num">${rows.filter((e) => edgeInChip(e, k)).length}</small></button>`).join('');
  const min = kellyCfg().minEdge;
  return `<h2 id="dlgTitle">Edge Finder</h2>
    <p class="lede">${esc(EDGE_EXPLAIN)}</p>
    <p class="edge-sizing">Pre-game prices, by kickoff. Showing gaps of +${min}% or more · <button type="button" class="edge-sizing-btn" data-kelly-settings>Change</button></p>
    <div class="chips edge-chips" role="group" aria-label="Market">${chips}</div>
    ${list.length ? `<div class="card edge-list">${list.map(edgeRow).join('')}</div>`
      : `<p class="edge-none">${rows.length ? `Nothing +${min}% or more from the sharp price in this market.` : `No prices are +${min}% or more from the sharp price right now. That’s normal most of the time.`}</p>`}
    <div class="edge-opts">
      <button type="button" class="chip" data-edge-weak aria-pressed="${edgeShowWeak()}">${edgeShowWeak() ? 'Showing weak reads' : `Show weak reads${weakN ? ` (${weakN})` : ''}`}</button>
      <button type="button" class="chip" data-edge-marks aria-pressed="${!!store.get('edgeMarks', false)}">Mark on the board</button>
    </div>
    <p class="note"><b>How this works.</b> We take Pinnacle’s price (else Circa’s), remove the cut, and use it only if it was listed in the last 10 minutes; otherwise there’s no comparison. When a book hangs a different number, a model converts between numbers using how often games have landed on 3, 7, 10 and 14; those rows show “≈” and are less reliable. <b>Solid</b> means the gap is well beyond its uncertainty and the other books agree; <b>Thin</b> means it might be real; <b>Weak read</b> is probably noise. None of this predicts a result, and prices change often.</p>`;
}
function edgePaintSheet() {
  if (S.sheet?.kind !== 'edges') return;
  edgeLastPaint = Date.now();
  const html = edgeSheetHTML();
  if (html === edgeLastHTML && $('#dlgBody .edge-chips')) return;
  edgeLastHTML = html;
  const box = $('#dlgIn'), top = box ? box.scrollTop : 0;
  const focused = document.activeElement?.closest?.('#dlgBody [data-edge-mkt], #dlgBody [data-open]');
  const fKey = focused ? (focused.dataset.edgeMkt ? `[data-edge-mkt="${focused.dataset.edgeMkt}"]` : null) : null;
  $('#dlgBody').innerHTML = html;
  if (box) box.scrollTop = top;
  if (fKey) $(`#dlgBody ${fKey}`)?.focus({ preventScroll: true });
}
function edgeOpen() {
  S.sheet = { kind: 'edges' };
  edgeLastHTML = edgeSheetHTML();
  $('#dlgBody').innerHTML = edgeLastHTML;
  showSheet('edges', true);
  const box = $('#dlgIn');
  if (box) box.scrollTop = 0;
  edgeLastPaint = Date.now();
}
// Called by refreshSheet() on every live update while this sheet is open; repaints at most every 1.5 s.
function edgeRefresh() {
  if (S.sheet?.kind !== 'edges') return;
  const wait = 1500 - (Date.now() - edgeLastPaint);
  if (wait > 0) {
    if (!edgeTimer) edgeTimer = setTimeout(() => { edgeTimer = 0; edgeRefresh(); }, wait);
    return;
  }
  edgePaintSheet();
}

// Deep link: #edges opens the list once the week has loaded.
let edgeWantLink = location.hash === '#edges';
window.addEventListener('hashchange', () => { if (location.hash === '#edges') { edgeWantLink = true; edgeDeepLink(); } });
function edgeDeepLink() {
  if (!edgeWantLink || !S.books.length || !allGames().length) return;
  edgeWantLink = false;
  setTimeout(edgeOpen, 0);
}
$('#dlg').addEventListener('close', () => { if (location.hash === '#edges') history.replaceState(null, '', `#${S.tab}`); });

// ------------------------------------------------------------ board: optional quiet marks, and the filter
function edgeBadge(g, mkt, side, book) {
  if (!store.get('edgeMarks', false) || !g || !isPre(g) || book === 'cons' || book === 'open') return '';
  const e = edgesFor(g).find((x) => x.mkt === mkt && x.side === side && x.book === book);
  return e ? '<span class="edge-b" aria-hidden="true"></span>' : '';
}
function edgeGame(g) { return isPre(g) && edgesFor(g).length > 0; }

// ------------------------------------------------------------ clicks (data-edge-* only; rows open the game via data-open)
document.addEventListener('click', (ev) => {
  const t = ev.target.closest('[data-edge-all], [data-edge-mkt], [data-edge-weak], [data-edge-marks]');
  if (!t) return;
  const d = t.dataset;
  if (d.edgeAll !== undefined) { ev.preventDefault(); edgeOpen(); return; }
  if (d.edgeMkt) { edgeMkt = d.edgeMkt; edgePaintSheet(); return; }
  if (d.edgeWeak !== undefined) { store.set('edgeWeak', !edgeShowWeak()); edgePaintSheet(); invalidate(); return; }
  if (d.edgeMarks !== undefined) { store.set('edgeMarks', !store.get('edgeMarks', false)); edgePaintSheet(); invalidate(); }
});
