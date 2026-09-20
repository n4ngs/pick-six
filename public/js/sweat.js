'use strict';
/* Pick Six — Sweat mode: one calm, full-screen sheet for the bets that are live right now.
   Every number updates in place, play by play. Chances are estimates (see coverChance in core.js).
   The hedge calculator only shows numbers; it never places or logs anything. */

// ------------------------------------------------------------ state (memory only, except the watch list)
const SWEAT_HIST = new Map();      // history key -> [[time, chance]] for the momentum sparkline
const SWEAT_HIST_MAX = 400;
const SWEAT_DRIVES = new Map();    // gid -> { poss, yl } where the current drive started
const SWEAT_POSS = new Map();      // gid -> last known team with the ball (ignores the gaps between plays)
const SWEAT_SEEDED = new Map();    // gid -> when we last asked the game endpoint for the current drive
const SWEAT_HEDGE = new Set();     // leg keys with the hedge calculator open
const SWEAT_UI = { pick: false, last: 0, timer: 0, waiting: 0 };
const sweatWatch = new Set(store.get('sweatWatch', []));
const sweatOpp = { home: 'away', away: 'home', over: 'under', under: 'over' };
const sweatR2 = (n) => Math.round(n * 100) / 100;
const sweatCalm = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// ------------------------------------------------------------ which bets and games
const sweatLiveBets = () => S.bets.filter((b) => b.status === 'open' && b.legs.some((l) => l.state === 'open' && isLive(gameById(l.gid))));
const sweatWatched = () => [...sweatWatch].map(gameById).filter((g) => g && isLive(g));
const sweatLegKey = (l) => `L:${l.gid}|${l.mkt}|${l.side}|${l.line ?? ''}|${l.team ?? ''}`;

// Estimated chance a leg cashes. Live: coverChance. Before kickoff: the same model from the market number.
function sweatChance(g, l) {
  if (l.state && l.state !== 'open') return l.state === 'lost' ? 0 : 1; // pushes and voids drop out of a parlay
  if (!g) return null;
  const now = legNow(g, l);
  if (isFinal(g)) return now == null ? null : now < 0 ? 0 : 1;
  if (isLive(g)) {
    const p = coverChance(g, l);
    if (p != null) return p;
    if (l.mkt?.startsWith('h1') && (g.half || g.period >= 3) && now != null) return now < 0 ? 0 : 1;
    return null;
  }
  if (isPre(g)) {
    const m = g.mkt || closeOf(g);
    if ((l.mkt === 's' || l.mkt === 'ml') && m?.s != null) {
      const need = l.mkt === 'ml' ? 0 : -(l.side === 'home' ? l.line : -l.line);
      const p = 1 - ncdf((need - -m.s) / SIGMA);
      return clamp(l.side === 'away' ? 1 - p : p, 0.005, 0.995);
    }
    if (l.mkt === 't' && m?.t != null) {
      const p = 1 - ncdf((l.line - m.t) / 13);
      return clamp(l.side === 'over' ? p : 1 - p, 0.005, 0.995);
    }
  }
  return null;
}
function sweatTicket(b) {
  let p = 1;
  for (const l of b.legs) {
    const c = sweatChance(gameById(l.gid), l);
    if (c == null) return null;
    p *= c;
  }
  return p;
}
// Most urgent first: closest to flipping, then least time left.
function sweatUrgency(b) {
  let pts = Infinity, left = 1;
  for (const l of b.legs) {
    const g = gameById(l.gid);
    if (l.state !== 'open' || !isLive(g)) continue;
    const n = Math.abs(legNow(g, l) ?? 99);
    if (n < pts || (n === pts && remaining(g) < left)) { pts = n; left = remaining(g); }
  }
  return [pts, left];
}
const sweatByUrgency = (a, b) => a.u[0] - b.u[0] || a.u[1] - b.u[1];

// The closing-line view of a game with no bet on it: the favorite's spread and the over.
function sweatWatchLegs(g) {
  const c = closeOf(g);
  const out = {};
  if (c?.s != null) {
    const fav = c.s < 0 ? 'home' : c.s > 0 ? 'away' : 'home';
    const line = lineFor(g, fav, c);
    out.s = { gid: g.id, mkt: 's', side: fav, line, label: `${g[fav].abbr} ${fmtPts(line)}`, state: 'open' };
  }
  if (c?.t != null) out.t = { gid: g.id, mkt: 't', side: 'over', line: c.t, label: `Over ${fmtTot(c.t)}`, state: 'open' };
  return out;
}

// ------------------------------------------------------------ momentum history
function sweatRecord(key, p) {
  if (p == null || Number.isNaN(p)) return;
  const t = Date.now();
  let a = SWEAT_HIST.get(key);
  if (!a) SWEAT_HIST.set(key, (a = []));
  const last = a.at(-1);
  if (last && Math.abs(last[1] - p) < 0.0005) return; // flat: the line to "now" carries it
  if (last && t - last[0] < 1500 && a.length > 1) { last[0] = t; last[1] = p; return; }
  a.push([t, p]);
  if (a.length > SWEAT_HIST_MAX) a.splice(0, a.length - SWEAT_HIST_MAX);
}
function sweatSample(g) {
  if (!g || !isLive(g)) return;
  for (const b of S.bets) {
    if (b.status !== 'open' || !b.legs.some((l) => l.gid === g.id)) continue;
    for (const l of b.legs) if (l.gid === g.id && l.state === 'open') sweatRecord(sweatLegKey(l), sweatChance(g, l));
    if (b.legs.length > 1) sweatRecord(`T:${b.id}`, sweatTicket(b));
  }
  if (sweatWatch.has(g.id)) {
    const w = sweatWatchLegs(g);
    if (w.s) sweatRecord(`W:${g.id}:s`, sweatChance(g, w.s));
    if (w.t) sweatRecord(`W:${g.id}:t`, sweatChance(g, w.t));
  }
}
function sweatSampleAll() {
  const ids = new Set([...S.bets.filter((b) => b.status === 'open').flatMap((b) => b.legs.map((l) => l.gid)), ...sweatWatch]);
  for (const id of ids) sweatSample(gameById(id));
}

// ------------------------------------------------------------ the current drive
// Tracked locally from possession changes; seeded once from the game endpoint (a read-only GET).
function sweatNoteDrive(prev, g) {
  if (!g.poss || g.sit?.yl == null) return;
  const was = SWEAT_POSS.get(g.id) ?? prev?.poss ?? null;
  SWEAT_POSS.set(g.id, g.poss);
  if (was && was !== g.poss) SWEAT_DRIVES.set(g.id, { poss: g.poss, yl: g.sit.yl });
}
function sweatSpotYl(g, txt) {
  const m = /^\s*([A-Za-z&.'-]+)?\s*(\d{1,2})\s*$/.exec(txt || '');
  if (!m) return null;
  const n = Number(m[2]);
  if (n === 0) return null; // ESPN writes touchbacks as "XXX 0"; better no shading than wrong shading
  if (!m[1] || n === 50) return 50;
  if (m[1].toUpperCase() === String(g.home.abbr).toUpperCase()) return n;
  if (m[1].toUpperCase() === String(g.away.abbr).toUpperCase()) return 100 - n;
  return null;
}
async function sweatSeedDrive(gid) {
  const g0 = gameById(gid);
  if (!g0 || !isLive(g0) || SWEAT_DRIVES.has(gid) || Date.now() - (SWEAT_SEEDED.get(gid) || 0) < 120e3) return;
  SWEAT_SEEDED.set(gid, Date.now());
  try {
    const d = await api(`/api/game/${gid}`);
    const g = gameById(gid);
    const cur = d.summary?.drives?.at(-1);
    if (!g?.poss || !cur || cur.result || SWEAT_DRIVES.has(gid) || cur.team !== String(g[g.poss].id)) return;
    const yl = sweatSpotYl(g, cur.start);
    if (yl != null) { SWEAT_DRIVES.set(gid, { poss: g.poss, yl }); SWEAT_POSS.set(gid, g.poss); sweatPaint(true); }
  } catch { /* the field still shows the ball without the drive */ }
}
function sweatField(g) {
  let svg = fieldSVG(g);
  const d = SWEAT_DRIVES.get(g.id), yl = g.sit?.yl;
  if (d && d.poss === g.poss && yl != null && d.yl !== yl) {
    const a = 10 + clamp(Math.min(d.yl, yl), 0, 100), w = Math.abs(clamp(yl, 0, 100) - clamp(d.yl, 0, 100));
    svg = svg.replace('<line class="los"', `<rect class="drive" x="${a}" y="1" width="${w}" height="14" rx="1"/><line class="los"`);
  }
  return svg;
}

// ------------------------------------------------------------ small pieces
function sweatStand(l, now, g) {
  if (now == null) return { cls: 'push', text: '—' };
  const n = trim(Math.abs(now));
  const need = trim(-now + (Number.isInteger(l.line ?? 0) ? 1 : 0.5));
  if (l.mkt === 'ml') return now > 0 ? { cls: 'win', text: `Leading by ${n}` } : now < 0 ? { cls: 'lose', text: `Trailing by ${n}` } : { cls: 'push', text: 'Tied' };
  if (now === 0) return { cls: 'push', text: 'On the number · push' };
  if (l.side === 'under') return now > 0 ? { cls: 'win', text: `Under by ${n}` } : { cls: 'lose', text: `Over by ${n}` };
  if (l.side === 'over') return now > 0 ? { cls: 'win', text: `Over by ${n}` } : { cls: 'lose', text: `Needs ${need} more` };
  return now > 0 ? { cls: 'win', text: `Covering by ${n}` } : { cls: 'lose', text: `Needs ${need} more` };
}
function sweatLiveNote(g, l) {
  const L = g.live?.cons || g.live?.dk;
  if (!L) return 'No live line';
  if ((l.mkt === 's' || l.mkt === 'ml') && L.s != null) return `Live ${L.s === 0 ? 'PK' : `${g[L.s < 0 ? 'home' : 'away'].abbr} ${fmtPts(-Math.abs(L.s))}`}`;
  if (l.mkt === 't' && L.t != null) return `Live total ${fmtTot(L.t)}`;
  return '';
}
function sweatScore(g) {
  const tm = (side) => {
    const t = g[side], o = g[sweatOpp[side]];
    return `<span class="sw-tm${(t.score ?? 0) < (o.score ?? 0) ? ' trail' : ''}">${logo(t)}<b>${esc(t.abbr)}</b><b class="num">${t.score ?? 0}</b>${g.poss === side ? '<span class="poss-dot" title="Has the ball"></span>' : ''}</span>`;
  };
  return `${tm('away')}${tm('home')}<span class="sw-clk"><span class="dot pulse"></span>${esc(clockLabel(g))}</span>`;
}
function sweatSpark(key, win) {
  const pts = SWEAT_HIST.get(key) || [];
  if (!pts.length) return '';
  const W = 120, H = 40;
  const t0 = pts[0][0], t1 = Math.max(Date.now(), t0 + 60e3);
  const X = (t) => (1 + ((t - t0) / (t1 - t0)) * (W - 5)).toFixed(1);
  const Y = (p) => (3 + (1 - p) * (H - 6)).toFixed(1);
  const last = pts.at(-1);
  const d = `M${pts.map((p) => `${X(p[0])},${Y(p[1])}`).join(' L')} L${X(t1)},${Y(last[1])}`;
  const since = timeLabel(new Date(t0).toISOString());
  return `<svg class="sw-spark${win ? ' win' : ''}" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Chance to cash since ${esc(since)}: ${fmtPct(pts[0][1])} to ${fmtPct(last[1])}"><line class="g" x1="0" x2="${W}" y1="${Y(0.5)}" y2="${Y(0.5)}"/><path d="${d}"/><circle cx="${X(t1)}" cy="${Y(last[1])}" r="2.5"/></svg><span class="sw-lab">since ${esc(since)}</span>`;
}
function sweatBig(p, key, win, label) {
  return `<div class="sw-big" data-sw-part="big-${key}"><div><div class="sw-pct num${win ? ' win' : ''}">${p == null ? '—' : `${Math.round(p * 100)}%`}</div><div class="sw-lab">${esc(label)}</div></div><div class="sw-mo">${sweatSpark(key, win)}</div></div>
    <div class="sw-meter" data-sw-part="meter-${key}" data-sw-w="${p == null ? 0 : (p * 100).toFixed(1)}" role="img" aria-label="${p == null ? 'No estimate' : `Estimated ${fmtPct(p)} chance`}"><i class="${win ? 'win' : ''}" style="width:${p == null ? 0 : (p * 100).toFixed(1)}%"></i></div>`;
}

// ------------------------------------------------------------ hedge (numbers only)
function sweatQuote(g, l) {
  if (!['s', 't', 'ml'].includes(l.mkt)) return null;
  const opp = sweatOpp[l.side];
  for (const k of ['cons', 'dk']) {
    const q = sideOf(g.live?.[k], l.mkt, opp);
    if (q && q.odds != null && Math.abs(q.odds) >= 100 && (l.mkt === 'ml' || q.line != null)) return { ...q, book: k, opp };
  }
  return null;
}
function sweatPayout(b) {
  // Same as the server's grading: pushed or voided legs drop out and the rest pay at their own prices.
  const dropped = b.legs.some((l) => l.state === 'push' || l.state === 'void');
  const d = b.legs.length === 1 || !dropped ? dec(b.odds) : b.legs.filter((l) => l.state !== 'push' && l.state !== 'void').reduce((p, l) => p * dec(l.odds), 1);
  return b.stake * (d - 1);
}
function sweatHedge(b, g, l, key) {
  const q = sweatQuote(g, l);
  if (!q) return `<p class="sw-s">There's no live price on the other side of this bet right now, so there's nothing to hedge against yet.</p>`;
  const pay = sweatPayout(b), hs = b.stake;
  // Bet h on the other side so both outcomes net the same: pay - h = h*(dec-1) - hs  =>  h = (pay + hs) / dec
  const h = (pay + hs) / dec(q.odds);
  const lock = pay - h;
  const side = l.mkt === 't' ? `${q.opp === 'under' ? 'Under' : 'Over'} ${fmtTot(q.line)}` : l.mkt === 'ml' ? `${g[q.opp].abbr} to win` : `${g[q.opp].abbr} ${fmtPts(q.line)}`;
  const mine = l.mkt === 't' ? fmtTot(l.line) : fmtPts(-l.line);
  const differs = l.mkt !== 'ml' && q.line !== (l.mkt === 't' ? l.line : -l.line);
  return `<div class="sw-hq"><div><div class="sw-lab">Bet on ${esc(side)} ${esc(fmtOdds(q.odds))}</div><div class="sw-hv num">${fmtMoney(sweatR2(h))}</div></div><div><div class="sw-lab">${lock >= 0 ? 'Locks in, either way' : 'Caps the loss at'}</div><div class="sw-hv num">${fmtMoney(sweatR2(lock), true)}</div></div></div>
    <p class="sw-s">Unhedged it's ${fmtMoney(sweatR2(pay), true)} or ${fmtMoney(-hs)}. Live ${esc(bookName(q.book))} price.${differs ? ` The live number (${esc(mine)} for you) has moved from yours, so a final score between them can win or lose both.` : ''} For reference only; nothing is placed or logged.</p>`;
}

// ------------------------------------------------------------ cards
// One live leg in full: score, estimated chance, where it stands, the field, momentum and the hedge.
function sweatLegBlock(key, g, l, { pick = false, hedgeBet = null, neutral = false, hist = sweatLegKey(l), label = 'est. chance to cash', stop = '' } = {}) {
  const now = legNow(g, l);
  const p = sweatChance(g, l);
  const st = sweatStand(l, now, g);
  const win = !neutral && now > 0;
  const hOpen = SWEAT_HEDGE.has(key);
  const sit = g.half ? '<b>Halftime</b>' : `${g.sit?.text ? `<b>${esc(g.sit.text)}</b>` : ''}${g.sit?.rz ? ' <b class="sw-rz">Red zone</b>' : ''}${g.last ? ` ${esc(g.last.slice(0, 140))}` : ''}`;
  return `<div class="sw-leg" data-sw-leg="${key}">
    ${pick ? `<div class="sw-pick"><b>${esc(l.label)}</b><span class="sw-s num">${esc(fmtOdds(l.odds))}</span></div>` : ''}
    <div class="sw-score" data-sw-part="score-${key}">${sweatScore(g)}</div>
    ${sweatBig(p, hist, win, label)}
    <div class="sw-st" data-sw-part="st-${key}"><span class="cov ${neutral ? (st.cls === 'push' ? 'push' : 'lose') : st.cls}">${esc(st.text)}</span><span class="sw-s">${esc(sweatLiveNote(g, l))}</span></div>
    <div class="sw-fld" data-sw-part="fld-${key}">${g.half ? '' : sweatField(g)}<div class="sw-situ">${sit}</div></div>
    <div class="sw-acts" data-sw-part="acts-${key}">${hedgeBet ? `<button type="button" class="sw-btn" data-sweat-hedge="${key}" aria-expanded="${hOpen}" aria-controls="swh-${key}">Hedge</button>` : ''}${stop}<button type="button" class="sw-btn" data-open="${g.id}">Open game ${ICON.chev}</button></div>
    ${hedgeBet ? `<div class="sw-hedge" id="swh-${key}" data-sw-part="hedge-${key}"${hOpen ? '' : ' hidden'}>${hOpen ? sweatHedge(hedgeBet, g, l, key) : ''}</div>` : ''}
  </div>`;
}
function sweatHead(title, odds, sub, extra = '') {
  return `<div class="sw-hd"><div style="min-width:0"><div class="sw-ttl"><b>${esc(title)}</b>${odds ? ` <span class="num">${esc(odds)}</span>` : ''}</div><div class="sw-s">${esc(sub)}</div></div>${extra}</div>`;
}
function sweatBetCard(b) {
  const gids = [...new Set(b.legs.map((l) => l.gid))];
  const sub = [`${fmtMoney(b.stake)} to win ${fmtMoney(sweatR2(sweatPayout(b)))}`, b.book].filter(Boolean).join(' · ');
  const open = b.legs.filter((l) => l.state === 'open');
  if (b.legs.length === 1) {
    const l = b.legs[0], g = gameById(l.gid);
    return `<article class="card sw-card" data-sw-key="B:${b.id}" data-sw-gids=" ${gids.join(' ')} ">
      ${sweatHead(l.label, fmtOdds(b.odds), sub)}
      ${sweatLegBlock(`${b.id}-0`, g, l, { hedgeBet: b })}
    </article>`;
  }
  const p = sweatTicket(b);
  const liveLegs = b.legs.map((l, i) => ({ l, i, g: gameById(l.gid) })).filter((x) => x.l.state === 'open' && isLive(x.g));
  const allCovering = !b.legs.some((l) => l.state === 'lost') && liveLegs.every((x) => legNow(x.g, x.l) > 0);
  const rows = b.legs.map((l, i) => {
    const g = gameById(l.gid);
    let cls = 'push', txt = '';
    if (l.state !== 'open') { cls = l.state === 'won' ? 'win' : l.state === 'lost' ? 'lose' : 'push'; txt = { won: 'Won', lost: 'Lost', push: 'Push', void: 'Void' }[l.state] || l.state; }
    else if (g && isLive(g)) { const s = sweatStand(l, legNow(g, l), g); cls = s.cls; txt = s.text; }
    else if (g && isPre(g)) txt = `${dayLabel(g.start)} ${timeLabel(g.start)}`;
    else if (g && isFinal(g)) txt = 'Grading';
    return `<div class="sw-lrow" data-sw-part="lrow-${b.id}-${i}"><span class="sw-lname"><b>${esc(l.label)}</b><span class="sw-s">${esc(l.matchup || '')}</span></span><span class="cov ${cls}">${esc(txt)}</span></div>`;
  }).join('');
  const hedgeIdx = open.length === 1 && liveLegs.length === 1 ? liveLegs[0].i : -1;
  return `<article class="card sw-card sw-parlay" data-sw-key="B:${b.id}" data-sw-gids=" ${gids.join(' ')} ">
    ${sweatHead(`${b.legs.length}-leg parlay`, fmtOdds(b.odds), sub)}
    ${sweatBig(p, `T:${b.id}`, allCovering, 'est. chance the ticket cashes')}
    <div class="sw-lrows">${rows}</div>
    ${liveLegs.map(({ l, i, g }) => sweatLegBlock(`${b.id}-${i}`, g, l, { pick: true, hedgeBet: i === hedgeIdx ? b : null })).join('')}
  </article>`;
}
function sweatWatchCard(g) {
  const w = sweatWatchLegs(g);
  const c = closeOf(g);
  const stop = `<button type="button" class="sw-btn" data-sweat-watch="${g.id}" aria-pressed="true" aria-label="Stop watching ${esc(g.away.abbr)} at ${esc(g.home.abbr)}">Stop watching</button>`;
  const sub = `Watching, no bet · closing line${c?.s != null ? ` ${w.s.label}` : ''}${c?.t != null ? `, O/U ${fmtTot(c.t)}` : ''}`;
  let tot = '';
  if (w.t) {
    const now = legNow(g, w.t), p = sweatChance(g, w.t);
    const pts = (g.home.score ?? 0) + (g.away.score ?? 0);
    tot = `<div class="sw-tot" data-sw-part="tot-${g.id}"><span>Total <b class="num">${pts}</b> vs ${fmtTot(w.t.line)} · ${esc(now > 0 ? `over by ${trim(now)}` : now === 0 ? 'on the number' : `over needs ${trim(-now + (Number.isInteger(w.t.line) ? 1 : 0.5))} more`)}</span><span>${p == null ? '' : `est. ${fmtPct(p)} over`}</span></div>`;
  }
  const body = w.s
    ? sweatLegBlock(`W${g.id}`, g, w.s, { neutral: true, hist: `W:${g.id}:s`, label: `est. chance ${g[w.s.side].abbr} covers`, stop })
    : `<div class="sw-leg"><div class="sw-score" data-sw-part="score-W${g.id}">${sweatScore(g)}</div><div class="sw-fld" data-sw-part="fld-W${g.id}">${sweatField(g)}</div><div class="sw-acts">${stop}<button type="button" class="sw-btn" data-open="${g.id}">Open game ${ICON.chev}</button></div></div>`;
  return `<article class="card sw-card sw-watch" data-sw-key="W:${g.id}" data-sw-gids=" ${g.id} ">
    ${sweatHead(`${g.away.abbr} @ ${g.home.abbr}`, '', sub)}
    ${body}${tot}
  </article>`;
}

// ------------------------------------------------------------ the sheet
function sweatModel() {
  const bets = sweatLiveBets().map((b) => ({ b, u: sweatUrgency(b) })).sort(sweatByUrgency).map((x) => x.b);
  const watched = sweatWatched().map((g) => {
    const w = sweatWatchLegs(g);
    return { g, u: [Math.abs(w.s ? legNow(g, w.s) : 99), remaining(g)] };
  }).sort(sweatByUrgency).map((x) => x.g);
  return { bets, watched, live: liveGames() };
}
function sweatLede(m) {
  if (!m.bets.length) return m.live.length ? `${plural(m.live.length, 'game')} live · none of your bets in play` : 'Nothing is live right now.';
  const legs = m.bets.flatMap((b) => b.legs.filter((l) => l.state === 'open' && isLive(gameById(l.gid))));
  const cov = legs.filter((l) => legNow(gameById(l.gid), l) > 0).length;
  const risk = m.bets.reduce((s, b) => s + b.stake, 0);
  return `${plural(m.bets.length, 'live bet')} · ${cov} of ${plural(legs.length, 'live leg')} covering · ${fmtMoney(risk)} at risk`;
}
function sweatPicker(m) {
  if (!m.live.length) {
    const next = allGames().filter(isPre).sort((a, b) => Date.parse(a.start) - Date.parse(b.start))[0];
    return `<div class="card empty sw-none"><b>No games are live</b>${next ? `Next kickoff: ${esc(next.away.abbr)} @ ${esc(next.home.abbr)}, ${esc(dayLabel(next.start))} ${esc(timeLabel(next.start))}.` : 'Check back on game day.'}</div>`;
  }
  const collapsed = m.bets.length && !SWEAT_UI.pick;
  const head = `<div class="sub-h sw-sub-h"><span class="sw-h">${m.bets.length ? 'Watch a game without a bet' : 'Live now'}</span>${m.bets.length ? `<button type="button" class="sw-more" data-sweat-pick aria-expanded="${!collapsed}">${collapsed ? `Show ${plural(m.live.length, 'game')}` : 'Hide'}</button>` : `<span>${plural(m.live.length, 'game')}</span>`}</div>`;
  if (collapsed) return head;
  const games = [...m.live].sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || String(a.id).localeCompare(String(b.id)));
  const row = (g) => {
    const on = sweatWatch.has(g.id);
    const c = closeOf(g), fav = c?.s == null ? null : c.s < 0 ? 'home' : c.s > 0 ? 'away' : null;
    const t = (side) => `<span class="sw-pt${(g[side].score ?? 0) < (g[sweatOpp[side]].score ?? 0) ? ' trail' : ''}">${logo(g[side])}<b>${esc(g[side].abbr)}</b><b class="num">${g[side].score ?? 0}</b></span>`;
    const line = c?.s == null ? '' : fav ? `${g[fav].abbr} ${fmtPts(-Math.abs(c.s))}` : 'PK';
    return `<button type="button" class="sw-prow" data-sweat-watch="${g.id}" aria-pressed="${on}"><span class="sw-pteams">${t('away')}${t('home')}</span><span class="sw-pmeta"><span>${esc(clockLabel(g))}</span><span>${esc(line)}</span></span><span class="sw-ptog">${on ? 'Watching' : 'Watch'}</span></button>`;
  };
  return `${head}<div class="card sw-plist">${games.map(row).join('')}</div>`;
}
function sweatParts(m) {
  const empty = m.bets.length ? '' : `<div class="card empty sw-empty"><b>No live bets right now</b>When a game you have money on kicks off, it lands here with its chance to cash, updating play by play.${m.live.length ? ' Until then, pick a live game below to sweat along.' : ''}</div>`;
  return {
    lede: `<p class="lede" data-sw-part="lede">${esc(sweatLede(m))}</p>`,
    empty: `<div data-sw-part="empty">${empty}</div>`,
    hwatch: `<div data-sw-part="hwatch">${m.watched.length ? `<div class="sub-h sw-sub-h"><span class="sw-h">Watching</span><span>closing lines, no money on it</span></div>` : ''}</div>`,
    picker: `<div class="sw-sec" data-sw-part="picker">${sweatPicker(m)}</div>`,
  };
}
function sweatHTML(m) {
  const p = sweatParts(m);
  return `<div class="sw" id="swRoot">
    <div class="sw-top"><h2 id="dlgTitle"><span class="dot pulse"></span>Sweat mode</h2>${p.lede}</div>
    ${p.empty}
    <div class="sw-list" id="swBets">${m.bets.map(sweatBetCard).join('')}</div>
    ${p.hwatch}
    <div class="sw-list" id="swWatch">${m.watched.map(sweatWatchCard).join('')}</div>
    ${p.picker}
    <p class="sw-note">Chances are estimates from the live market line and the time left, not a promise. The hedge calculator only does the math; nothing is placed or logged.</p>
  </div>`;
}

// ------------------------------------------------------------ painting in place
const sweatFrag = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
function sweatPatchPart(old, nu) {
  if (old.outerHTML === nu.outerHTML) return;
  if (old.dataset.swW !== undefined && nu.dataset.swW !== undefined && old.firstElementChild && nu.firstElementChild) {
    // The meter slides to its new width instead of being redrawn.
    old.firstElementChild.className = nu.firstElementChild.className;
    old.firstElementChild.style.width = nu.firstElementChild.style.width;
    old.dataset.swW = nu.dataset.swW;
    old.setAttribute('aria-label', nu.getAttribute('aria-label') || '');
    return;
  }
  old.replaceWith(nu);
}
function sweatPatchCard(el, html) {
  const nu = sweatFrag(html);
  const oldParts = [...el.querySelectorAll('[data-sw-part]')];
  const newParts = [...nu.querySelectorAll('[data-sw-part]')];
  const names = (a) => a.map((x) => x.dataset.swPart).join(',');
  if (names(oldParts) !== names(newParts)) { if (el.classList.contains('sw-flash')) nu.classList.add('sw-flash'); el.replaceWith(nu); return; }
  const flashing = el.classList.contains('sw-flash');
  if (el.className.replace(' sw-flash', '') !== nu.className) el.className = nu.className + (flashing ? ' sw-flash' : '');
  newParts.forEach((p, i) => sweatPatchPart(oldParts[i], p));
  // Header text (stake, closing line) rarely changes; keep it honest anyway.
  const oh = el.querySelector('.sw-hd'), nh = nu.querySelector('.sw-hd');
  if (oh && nh && oh.outerHTML !== nh.outerHTML) oh.replaceWith(nh);
}
function sweatSync(box, cards) {
  const have = new Map([...box.children].map((c) => [c.dataset.swKey, c]));
  // Re-sort only near the top of the sheet; while you're reading further down, cards stay where they are.
  const same = cards.length === have.size && cards.every((c) => have.has(c.key));
  if (same && ($('#dlgIn')?.scrollTop || 0) > 40) {
    const order = [...have.keys()];
    cards = [...cards].sort((x, y) => order.indexOf(x.key) - order.indexOf(y.key));
  }
  const keep = new Set();
  let prev = null;
  for (const { key, html } of cards) {
    keep.add(key);
    let el = have.get(key);
    if (el) sweatPatchCard(el, html);
    else el = sweatFrag(html);
    el = box.querySelector(`[data-sw-key="${key}"]`) || el;
    const want = prev ? prev.nextElementSibling : box.firstElementChild;
    if (want !== el) box.insertBefore(el, want);
    prev = el;
  }
  for (const [k, c] of have) if (!keep.has(k)) c.remove();
}
function sweatPaint(now = false) {
  if (S.sheet?.kind !== 'sweat') return;
  const root = $('#swRoot');
  const m = sweatModel();
  SWEAT_UI.last = Date.now();
  if (!root || now === 'full') { $('#dlgBody').innerHTML = sweatHTML(m); return; }
  // Put keyboard focus back on the same control after its part is redrawn.
  const a = document.activeElement;
  const focusSel = a && root.contains(a) ? ['sweatWatch', 'sweatHedge', 'sweatPick', 'open'].map((k) => (a.dataset[k] !== undefined ? `[data-${k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}="${a.dataset[k]}"]` : null)).find(Boolean) : null;
  const parts = sweatParts(m);
  for (const [name, html] of Object.entries(parts)) {
    const old = root.querySelector(`[data-sw-part="${name}"]`);
    if (old) sweatPatchPart(old, sweatFrag(html));
  }
  sweatSync($('#swBets'), m.bets.map((b) => ({ key: `B:${b.id}`, html: sweatBetCard(b) })));
  sweatSync($('#swWatch'), m.watched.map((g) => ({ key: `W:${g.id}`, html: sweatWatchCard(g) })));
  if (focusSel && document.activeElement !== a) root.querySelector(focusSel)?.focus({ preventScroll: true });
}

// ------------------------------------------------------------ public entry points
function sweatOpen() {
  const inner = $('#dlgIn');
  const already = S.sheet?.kind === 'sweat' && $('#swRoot');
  S.sheet = { kind: 'sweat' };
  sweatSampleAll();
  sweatPaint('full');
  showSheet('sweat');
  if (!already && inner) inner.scrollTop = 0;
  if (location.hash !== '#sweat') history.replaceState(null, '', '#sweat');
  for (const b of sweatLiveBets()) for (const l of b.legs) sweatSeedDrive(l.gid);
  for (const g of sweatWatched()) sweatSeedDrive(g.id);
}
// Called by refreshSheet() on every live update while this sheet is open. About once a second, at most.
function sweatRefresh() {
  if (S.sheet?.kind !== 'sweat') return;
  const wait = 1000 - (Date.now() - SWEAT_UI.last);
  if (wait > 0) {
    if (!SWEAT_UI.timer) SWEAT_UI.timer = setTimeout(() => { SWEAT_UI.timer = 0; sweatRefresh(); }, wait);
    return;
  }
  sweatPaint();
}

// ------------------------------------------------------------ events
document.addEventListener('hl:game', (e) => {
  const { prev, g } = e.detail || {};
  if (!g) return;
  sweatNoteDrive(prev, g);
  sweatSample(g);
  if (S.sheet?.kind !== 'sweat' || !prev || sweatCalm()) return;
  const scored = (prev.home.score ?? 0) !== (g.home.score ?? 0) || (prev.away.score ?? 0) !== (g.away.score ?? 0);
  if (!scored) return;
  for (const c of $$(`[data-sw-gids*=" ${g.id} "]`)) {
    c.classList.remove('sw-flash');
    void c.offsetWidth; // restart the animation
    c.classList.add('sw-flash');
    setTimeout(() => c.classList.remove('sw-flash'), 1700);
  }
});

document.addEventListener('click', (ev) => {
  const t = ev.target.closest('[data-sweat-open], [data-sweat-watch], [data-sweat-hedge], [data-sweat-pick]');
  if (!t) return;
  ev.preventDefault();
  const d = t.dataset;
  if (d.sweatOpen !== undefined) { sweatOpen(); return; }
  if (d.sweatWatch) {
    const id = d.sweatWatch;
    if (sweatWatch.has(id)) sweatWatch.delete(id); else { sweatWatch.add(id); sweatSample(gameById(id)); sweatSeedDrive(id); }
    store.set('sweatWatch', [...sweatWatch]);
    sweatPaint();
    return;
  }
  if (d.sweatHedge) {
    if (SWEAT_HEDGE.has(d.sweatHedge)) SWEAT_HEDGE.delete(d.sweatHedge); else SWEAT_HEDGE.add(d.sweatHedge);
    sweatPaint();
    return;
  }
  if (d.sweatPick !== undefined) { SWEAT_UI.pick = !SWEAT_UI.pick; sweatPaint(); }
});

// Deep link: #sweat opens the sheet once the first snapshot has loaded.
function sweatWhenReady(fn) {
  if (S.weeks.size) { fn(); return; }
  clearInterval(SWEAT_UI.waiting);
  SWEAT_UI.waiting = setInterval(() => { if (S.weeks.size) { clearInterval(SWEAT_UI.waiting); SWEAT_UI.waiting = 0; if (location.hash === '#sweat') fn(); } }, 200);
}
if (location.hash === '#sweat') sweatWhenReady(sweatOpen);
window.addEventListener('hashchange', () => { if (location.hash === '#sweat') sweatWhenReady(sweatOpen); });
// Leaving the sheet takes #sweat off the address so a reload lands on the tab you were on.
$('#dlg').addEventListener('close', () => { if (location.hash === '#sweat') history.replaceState(null, '', `#${S.tab}`); });
