'use strict';
/* Pick Six — the Line Time Machine: replay one game's line history across every book, like scrubbing a
   video. Drag the scrubber (or press play) and the whole market moves: each book's number at that moment, who
   moved first, steam and key-number crossings, the open, the close, and where your own bets sit.
   Every top-level name here starts with tm / TM_ (all scripts share one global scope). */

const TM_PLAY_MS = 8000;        // a full replay takes about this long
const TM_STEP_MS = 650;         // reduced motion: one change per step, no easing
const TM_KEYS = [3, 7, 10, 14]; // same key numbers lib/lines.js watches
const TM_REFETCH_MS = 60000;
const TM_SVG = {
  play: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5 3.1v9.8c0 .5.5.8.9.5l7.4-4.9a.6.6 0 0 0 0-1L5.9 2.6c-.4-.3-.9 0-.9.5z"/></svg>',
  pause: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><rect x="3.5" y="3" width="3.2" height="10" rx="1"/><rect x="9.3" y="3" width="3.2" height="10" rx="1"/></svg>',
  prev: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3.5L5.5 8l4.5 4.5"/></svg>',
  next: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3.5L10.5 8 6 12.5"/></svg>',
};

let tmS = null;       // the open time machine: { gid, mkt, data, game, M, sc, t, atEnd, playing, drag, pending, focus, … }
let tmTimer = 0;      // periodic refetch
let tmSoon = 0;       // throttled refetch after live data

const tmReduced = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const tmIso = (t) => new Date(t).toISOString();
const tmWhen = (t) => `${dayLabel(tmIso(t))} ${timeLabel(tmIso(t))}`;
const tmActive = () => !!(tmS && S.sheet?.kind === 'tm' && S.sheet.gid === tmS.gid && $('#dlg')?.open);
const tmSigned = (d) => (d == null ? '—' : d === 0 ? '0' : `${d > 0 ? '+' : MINUS}${trim(Math.abs(d))}`);
const tmArrow = (d) => (!d ? '' : `${d > 0 ? '▲' : '▼'} ${tmSigned(d)}`);
const tmPointAt = (pts, t) => { let v = null; for (const p of pts) { if (p[0] <= t) v = p; else break; } return v; };
const tmLastMove = (mv, t) => { let v = null; for (const m of mv) { if (m.t <= t) v = m; else break; } return v; };

// ------------------------------------------------------------ model
// Lines are plotted from the favorite's side ("points favored by"), like the game sheet's chart: up = the
// favorite got more expensive (or the total went up).
function tmModel(g, H, mkt) {
  if (!g || !H) return null;
  const favHome = (g.mkt?.s ?? g.close?.s ?? H.close?.s ?? -1) <= 0;
  const conv = (v) => (v == null ? null : mkt === 't' ? v : favHome ? -v : v);
  const fav = favHome ? g.home : g.away, dog = favHome ? g.away : g.home;
  const series = [];
  for (const k of ['cons', ...visibleBooks().map((b) => b.key)]) {
    const pts = (H.b?.[k]?.[mkt] || []).filter((p) => p[1] != null).map((p) => [p[0], conv(p[1]), p[2] ?? null]);
    const mv = [];
    for (let i = 1; i < pts.length; i++) if (pts[i][1] !== pts[i - 1][1]) mv.push({ t: pts[i][0], from: pts[i - 1][1], to: pts[i][1] });
    series.push({ key: k, pts, mv, cons: k === 'cons', sharp: !!S.books.find((b) => b.key === k)?.sharp });
  }
  const has = series.filter((s) => s.pts.length);
  const open = H.open?.[mkt] != null ? { t: H.open.at || null, v: conv(H.open[mkt]) } : null;
  const live = (H.l?.[mkt] || []).filter((p) => p[1] != null).map((p) => [p[0], conv(p[1])]);
  const ko = Date.parse(g.start);
  const firstSeen = has.length ? Math.min(...has.map((s) => s.pts[0][0])) : null;
  const lastSeen = has.length ? Math.max(...has.map((s) => s.pts.at(-1)[0])) : null;
  if (firstSeen == null && !open?.t) return null;
  const end = isFinal(g) ? Math.max(ko + 4 * 3600e3, live.at(-1)?.[0] ?? 0, lastSeen ?? 0) : Math.max(serverNow(), lastSeen ?? 0, live.at(-1)?.[0] ?? 0);
  const t0 = open?.t && (firstSeen == null || open.t < firstSeen) ? open.t : firstSeen ?? end - 3600e3;
  const t1 = Math.max(end, t0 + 60e3);
  const tEndPre = isPre(g) ? t1 : Math.min(ko, t1);
  const cons = has.find((s) => s.cons) || null;
  const closeV = H.close?.[mkt] != null ? conv(H.close[mkt]) : !isPre(g) && cons ? stepAt(cons.pts, ko) : null;

  const M = { g, H, mkt, favHome, conv, fav, dog, series, has, cons, open, live, ko, t0, t1, tEndPre, firstSeen, closeV };
  // your bets on this game
  M.legs = S.bets.flatMap((b) => b.legs.filter((l) => l.gid === g.id && (l.mkt === 's' || l.mkt === 't') && l.line != null)
    .map((l) => {
      const raw = l.mkt === 't' ? l.line : l.side === 'home' ? l.line : -l.line;
      const placed = Date.parse(l.placed || b.placed) || b.created || null;
      return { bet: b, leg: l, placed, v: l.mkt === mkt ? conv(raw) : null };
    }));
  M.mine = M.legs.filter((x) => x.leg.mkt === mkt);

  const vals = [...has.flatMap((s) => s.pts.map((p) => p[1])), ...(open ? [open.v] : []), ...live.map((p) => p[1]), ...M.mine.filter((x) => x.placed >= t0 && x.placed <= t1).map((x) => x.v)];
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 2) { lo -= 1; hi += 1; }
  M.lo = Math.floor(lo * 2) / 2 - 0.5;
  M.hi = Math.ceil(hi * 2) / 2 + 0.5;
  M.moves = (H.moves || []).filter((m) => m.mkt === mkt && m.t >= t0 - 60e3).sort((a, b) => a.t - b.t);
  M.events = tmEvents(M);
  const stops = new Set([t0, t1, ...M.events.map((e) => e.t)]);
  for (const s of has) { stops.add(s.pts[0][0]); for (const m of s.mv) stops.add(m.t); }
  for (const p of live) stops.add(p[0]);
  M.stops = [...stops].filter((t) => t >= t0 && t <= t1).sort((a, b) => a - b);
  return M;
}

// A line in plain words from whichever team is favored at that value.
function tmLine(M, v) {
  if (v == null) return '—';
  if (M.mkt === 't') return fmtTot(v);
  if (v === 0) return 'PK';
  return v > 0 ? `${M.fav.abbr} ${fmtPts(-v)}` : `${M.dog.abbr} ${fmtPts(v)}`;
}
const tmNum = (M, v) => (v == null ? '—' : M.mkt === 't' ? fmtTot(v) : fmtPts(-v));

// The market number at time t: in-game line after kickoff, else consensus, else the median book, else the open.
function tmMarketAt(M, t) {
  if (t > M.ko && M.live.length) { const v = stepAt(M.live, t); if (v != null) return { v, kind: 'live' }; }
  const tt = Math.min(t, M.tEndPre);
  if (M.cons) { const v = stepAt(M.cons.pts, tt); if (v != null) return { v, kind: t > M.ko && !isPre(M.g) ? 'close' : 'cons' }; }
  const vs = M.has.map((s) => stepAt(s.pts, tt)).filter((v) => v != null).sort((a, b) => a - b);
  if (vs.length) return { v: vs[Math.floor(vs.length / 2)], kind: 'median' };
  if (M.open && M.open.t <= t) return { v: M.open.v, kind: 'open' };
  return null;
}

// The earliest book to move in direction `dir` around time t (optionally only among `only`).
function tmLeader(M, t, dir, only) {
  let best = null;
  for (const s of M.has) {
    if (s.cons || (only && !only.includes(s.key))) continue;
    const m = s.mv.find((x) => x.t >= t - 20 * 60e3 && x.t <= t + 2 * 60e3 && Math.sign(x.to - x.from) === dir);
    if (m && (!best || m.t < best.t)) best = { key: s.key, t: m.t };
  }
  return best;
}

function tmEvents(M) {
  const ev = [];
  const word = { steam: 'Steam', key: 'Key number', flip: 'Favorite flipped', move: 'Big move' };
  if (M.open?.t) ev.push({ t: M.open.t, kind: 'open', label: 'Opened', text: tmLine(M, M.open.v) });
  for (const m of M.moves) {
    const from = M.conv(m.from), to = M.conv(m.to);
    const dir = Math.sign(to - from);
    const lead = dir ? tmLeader(M, m.t, dir, m.kind === 'steam' ? m.books : null) : null;
    let text = `${tmLine(M, from)} → ${tmLine(M, to)}`;
    if (m.kind === 'steam') {
      const n = m.books?.length || 0;
      const secs = m.secs || 0;
      text = `${plural(n, 'book')} to ${tmLine(M, to)}${secs >= 60 ? ` in ${Math.round(secs / 60)} min` : secs > 0 ? ` in ${secs} sec` : ''}`;
    } else if (m.kind === 'key') text = `${m.onto ? 'Onto' : 'Through'} ${m.key}: ${text}`;
    ev.push({ t: m.t, kind: m.kind, label: word[m.kind] || 'Move', text, lead });
  }
  // Market (consensus) changes the server didn't call out, so the log still shows how the number walked.
  const mk = (M.cons?.mv || []).filter((c) => !M.moves.some((m) => Math.abs(m.t - c.t) < 5 * 60e3)).slice(-40);
  for (const c of mk) {
    const dir = Math.sign(c.to - c.from);
    ev.push({ t: c.t, kind: 'mkt', label: 'Market', text: `${tmLine(M, c.from)} → ${tmLine(M, c.to)}`, lead: tmLeader(M, c.t, dir) });
  }
  for (const x of M.mine) if (x.placed) ev.push({ t: x.placed, kind: 'bet', label: 'Your bet', text: tmLegText(M.g, x.leg) });
  if (M.ko >= M.t0 && M.ko <= M.t1) ev.push({ t: M.ko, kind: 'ko', label: 'Kickoff', text: M.closeV != null ? `Closed ${tmLine(M, M.closeV)}` : '' });
  return ev.filter((e) => e.t >= M.t0 - 60e3 && e.t <= M.t1 + 60e3).sort((a, b) => a.t - b.t);
}

const tmLegText = (g, l) => (l.mkt === 't' ? `${l.side === 'over' ? 'Over' : 'Under'} ${fmtTot(l.line)}` : `${g[l.side]?.abbr || l.side} ${fmtPts(l.line)}`);
// Points in the bettor's favor versus a market value v (plotted scale). Positive = you beat that number.
function tmClv(M, leg, v) {
  if (v == null || leg.line == null) return null;
  const raw = M.mkt === 't' ? v : M.favHome ? -v : v; // back to the home team's side
  const d = leg.mkt === 't' ? (leg.side === 'over' ? raw - leg.line : leg.line - raw) : leg.line - (leg.side === 'home' ? raw : -raw);
  return Math.round(d * 10) / 10;
}

function tmHistSig(H) {
  if (!H) return '';
  let n = 0, last = 0;
  for (const b of Object.values(H.b || {})) for (const m of ['s', 't']) { n += b[m]?.length || 0; last += b[m]?.at(-1)?.[0] || 0; }
  return [n, last, H.moves?.length, H.moves?.at(-1)?.t, H.close?.at, H.l?.s?.length, H.l?.t?.length, H.open?.at, H.open?.s, H.open?.t].join('|');
}

// ------------------------------------------------------------ open / fetch / refresh
async function tmOpen(gid, mkt = 's') {
  gid = String(gid);
  mkt = mkt === 't' ? 't' : 's';
  tmStop();
  const same = tmS?.gid === gid;
  const cached = S.game?.game?.id === gid && S.game.hist ? S.game : same && tmS.data?.hist ? tmS.data : null;
  tmS = {
    gid, mkt, data: cached, game: gameById(gid) || cached?.game || null, M: null,
    t: same ? tmS.t : null, atEnd: same ? tmS.atEnd : true, playing: false, drag: false, pending: false,
    focus: null, fetchedAt: 0, hsig: '', gsig: '', bets: S.bets, boardSig: '', W: 0,
  };
  S.sheet = { kind: 'tm', gid, mkt, chartMkt: mkt };
  $('#dlgBody').innerHTML = '<div class="empty" style="padding:64px 16px"><b>Loading the line history…</b>Every number every book has posted for this game.</div>';
  showSheet('tm');
  const want = `#tm/${gid}${mkt === 't' ? '/t' : ''}`;
  if (location.hash !== want) history.replaceState(null, '', want);
  if (cached) tmPaint();
  tmFetch();
}

async function tmFetch() {
  clearTimeout(tmTimer);
  const st = tmS;
  if (!st || !tmActive()) return;
  st.fetchedAt = Date.now();
  try {
    const d = await api(`/api/game/${st.gid}`);
    if (tmS !== st || !tmActive()) return;
    tmApply(d);
  } catch (e) {
    if (tmS === st && !st.data && tmActive()) $('#dlgBody').innerHTML = `${tmNavHTML(st.gid)}<div class="empty"><b>Couldn't load this game's history</b>${esc(e.message)}</div>`;
  }
  if (tmS === st) tmTimer = setTimeout(tmFetch, TM_REFETCH_MS);
}

function tmApply(d) {
  const st = tmS;
  const first = !st.data;
  st.data = d;
  st.game = gameById(st.gid) || d.game || st.game;
  // Only redraw (and only extend "Now") when new points actually arrived.
  if (!first && tmHistSig(d.hist) === st.hsig) return;
  if (st.drag || st.playing) { st.pending = true; return; }
  tmPaint();
}

// Called by refreshSheet() on every live update while this sheet is open. Cheap unless something changed.
function tmRefresh() {
  const st = tmS;
  if (!st || !tmActive()) return;
  const g = gameById(st.gid);
  if (g) {
    const sig = JSON.stringify([g.state, g.mkt?.s, g.mkt?.t, g.close?.s, g.close?.t, g.live?.cons?.s, g.live?.cons?.t]);
    if (sig !== st.gsig) {
      const had = st.gsig;
      st.gsig = sig;
      st.game = g;
      if (had && !tmSoon) tmSoon = setTimeout(() => { tmSoon = 0; tmFetch(); }, Math.max(0, 8000 - (Date.now() - st.fetchedAt)));
    }
  }
  if (S.bets !== st.bets) {
    st.bets = S.bets;
    if (st.drag || st.playing) st.pending = true; else if (st.data) tmPaint();
  }
}

// ------------------------------------------------------------ paint
function tmPaint() {
  const st = tmS;
  if (!st || !tmActive()) return;
  st.pending = false;
  st.game = gameById(st.gid) || st.data?.game || st.game;
  st.M = tmModel(st.game, st.data?.hist, st.mkt);
  st.hsig = tmHistSig(st.data?.hist);
  st.boardSig = '';
  if (st.M) {
    if (st.t == null || st.atEnd) st.t = st.M.t1;
    st.t = clamp(st.t, st.M.t0, st.M.t1);
  }
  const inner = $('#dlgIn');
  const top = inner?.scrollTop || 0;
  $('#dlgBody').innerHTML = tmHTML();
  if (inner) inner.scrollTop = top;
  tmDrawChart();
  tmWire();
  tmUpdate();
}

const tmNavHTML = (gid) => `<div class="tm-nav"><button class="tm-back" type="button" data-tm-back="${esc(gid)}">${ICON.back}<span>Game</span></button></div>`;

function tmHTML() {
  const st = tmS, M = st.M, g = st.game;
  if (!g) return `${tmNavHTML(st.gid)}<div class="empty"><b>Loading…</b></div>`;
  const when = g.tbd ? `${dayLabel(g.start, true)} · time TBA` : `${dayLabel(g.start, true)} · ${timeLabel(g.start)}`;
  const head = `${tmNavHTML(st.gid)}
    <div class="tm-head">
      <div class="tm-ttl"><div class="tm-eye">Line time machine</div>
        <h2 id="dlgTitle">${esc(teamName(g.away))} <span>at</span> ${esc(teamName(g.home))}</h2>
        <div class="tm-meta">${esc([when, isPre(g) ? null : clockLabel(g), g.tv].filter(Boolean).join(' · '))}</div></div>
      <div class="seg tm-seg" role="group" aria-label="Market"><button type="button" data-tm-mkt="s" aria-pressed="${st.mkt === 's'}">Spread</button><button type="button" data-tm-mkt="t" aria-pressed="${st.mkt === 't'}">Total</button></div>
    </div>`;
  if (!M) {
    return `${head}<div class="card empty tm-none"><b>${st.data ? 'No line history yet' : 'Loading history…'}</b>${st.data ? 'The app records every change each book makes from now on. Lines usually open Sunday.' : ''}</div>`;
  }
  const chips = [
    '<button type="button" class="tm-chip" data-tm-jump="open">Open</button>',
    `<button type="button" class="tm-chip tm-ic" data-tm-jump="prev" aria-label="Previous change">${TM_SVG.prev}</button>`,
    `<button type="button" class="tm-chip tm-ic" data-tm-jump="next" aria-label="Next change">${TM_SVG.next}</button>`,
    !isPre(g) && M.ko >= M.t0 && M.ko <= M.t1 ? '<button type="button" class="tm-chip" data-tm-jump="close">Close</button>' : '',
    !isFinal(g) ? '<button type="button" class="tm-chip" data-tm-jump="now">Now</button>' : '',
  ].join('');
  const legend = [
    ['cons', 'Market'], ['sh', 'Sharp books'], ['bk', 'Other books'],
  ].map(([c, t]) => `<span><i class="tm-sw ${c}"></i>${t}</span>`).join('')
    + (M.moves.some((m) => m.kind === 'steam') ? '<span><i class="tm-mk steam"></i>Steam</span>' : '')
    + (M.moves.some((m) => m.kind !== 'steam') ? '<span><i class="tm-mk key"></i>Key number or flip</span>' : '')
    + (M.mine.length ? '<span><i class="tm-mk ybet"></i>Your bet</span>' : '');
  const note = M.mkt === 't' ? 'Total points. Up means the total went up.' : `${M.fav.abbr}'s spread. Up means ${M.fav.abbr} became a bigger favorite.`;
  const mineOther = M.legs.length - M.mine.length;
  return `${head}
    <section class="tm-now" id="tmNow" aria-label="The market at the playhead"></section>
    <div class="tm-grid">
      <div class="tm-col tm-main">
        <div class="card tm-chart" id="tmChart">
          <div class="tm-plot"><div id="tmSvg" class="tm-svg"></div>
            <div class="tm-scrub" id="tmScrub"><input class="tm-range" id="tmRange" type="range" min="0" max="1000" step="1" value="1000" aria-label="Replay time"></div></div>
          <div class="tm-ctl">
            <button type="button" class="tm-play" id="tmPlay" data-tm-play="1" aria-label="Play the replay">${TM_SVG.play}</button>
            <div class="tm-chips">${chips}</div>
          </div>
          <div class="tm-legend">${legend}</div>
          <p class="tm-note">${esc(note)}${M.mkt === 's' ? ' Dashed rows are key numbers.' : ''}${M.live.length ? ' Dashed line after kickoff: the in-game line.' : ''}</p>
        </div>
        <section class="tm-sec tm-o4" aria-label="What moved">
          <div class="sub-h">What moved <span>${plural(M.events.length, 'event')} · tap to jump</span></div>
          ${tmLogHTML(M)}
        </section>
      </div>
      <div class="tm-col tm-side">
        <section class="tm-sec tm-o2" aria-label="Every book at the playhead">
          <div class="sub-h">Every book at this moment <span>${M.mkt === 't' ? '▲ up · ▼ down' : `▲ toward ${esc(M.fav.abbr)} · ▼ toward ${esc(M.dog.abbr)}`}</span></div>
          <div class="card tm-board" id="tmBoard"></div>
        </section>
        ${M.mine.length ? `<section class="tm-sec tm-o3" aria-label="Your bets"><div class="sub-h">Your bets <span>+ means you beat that number</span></div><div class="card tm-bets" id="tmBets"></div></section>`
          : mineOther ? `<p class="note tm-o3">${plural(mineOther, 'bet')} on this game's ${M.mkt === 's' ? 'total' : 'spread'}. Switch markets to see ${mineOther === 1 ? 'it' : 'them'}.</p>` : ''}
      </div>
    </div>`;
}

function tmMarker(kind, x, y) {
  if (kind === 'steam') return `<circle class="ev steam" cx="${x}" cy="${y}" r="4.5"/>`;
  if (kind === 'key' || kind === 'flip') return `<circle class="ev key" cx="${x}" cy="${y}" r="4"/>`;
  if (kind === 'bet') return `<path class="ev ybet" d="M${x} ${y - 5}l5 5-5 5-5-5z"/>`;
  if (kind === 'open') return `<circle class="ev open" cx="${x}" cy="${y}" r="4"/>`;
  if (kind === 'ko') return `<path class="ev ko" d="M${x - 0.75} ${y - 6}h1.5v12h-1.5z"/>`;
  return `<circle class="ev emv" cx="${x}" cy="${y}" r="3"/>`;
}

function tmLogHTML(M) {
  if (!M.events.length) return '<div class="card empty tm-empty">No steam, key-number crossings or flips yet. Every change a book makes shows up here.</div>';
  return `<div class="card tm-log" id="tmLog">${M.events.map((e, i) => `<button type="button" class="tm-ev" data-tm-t="${e.t}" data-tm-ev="${i}">
      <svg class="tm-evm" viewBox="0 0 16 16" aria-hidden="true">${tmMarker(e.kind, 8, 8)}</svg>
      <span class="tm-evx"><span class="tm-evt num">${esc(tmWhen(e.t))} · <b>${esc(e.label)}</b></span><span class="tm-evd">${esc(e.text)}${e.lead ? ` · ${esc(bookName(e.lead.key))} moved first` : ''}</span></span>
    </button>`).join('')}</div>`;
}

// ------------------------------------------------------------ chart
function tmDrawChart() {
  const st = tmS, M = st?.M, box = $('#tmSvg');
  if (!box || !M) return;
  const W = Math.max(280, Math.round(box.clientWidth || 640));
  const Ht = W < 560 ? 232 : 300;
  const T = 14, B = Ht - 44, EY = B + 14;
  const sc = chartScale(M, W);
  const Y = (v) => T + ((M.hi - v) / (M.hi - M.lo)) * (B - T);
  const X = (t) => clamp(sc.X(t), sc.L, sc.R);
  Object.assign(st, { W, Ht, T, B, EY, sc, Y, X });
  const f = (n) => n.toFixed(1);

  // value grid, key numbers
  const range = M.hi - M.lo;
  const step = range > 16 ? 4 : range > 8 ? 2 : range > 3 ? 1 : 0.5;
  let grid = '';
  for (let v = Math.ceil(M.lo / step) * step; v <= M.hi; v += step) {
    grid += `<line class="gl" x1="${sc.L}" x2="${sc.R}" y1="${f(Y(v))}" y2="${f(Y(v))}"/><text class="ax" x="${sc.L - 8}" y="${f(Y(v) + 4)}" text-anchor="end">${esc(tmNum(M, v))}</text>`;
  }
  if (M.mkt === 's') for (const k of TM_KEYS) for (const v of [k, -k]) if (v > M.lo && v < M.hi) grid += `<line class="kl" x1="${sc.L}" x2="${sc.R}" y1="${f(Y(v))}" y2="${f(Y(v))}"/>`;

  // time axis: day or hour ticks, the squeezed pre-tracking gap, kickoff
  const from = sc.gapEnd || M.t0;
  const ticks = [];
  if (M.t1 - from > 30 * 3600e3) {
    const d = new Date(from); d.setHours(24, 0, 0, 0);
    for (; d.getTime() < M.t1; d.setDate(d.getDate() + 1)) ticks.push([d.getTime(), dayLabel(tmIso(d.getTime()))]);
  } else {
    const hrs = [1, 2, 3, 6, 12].find((h) => (M.t1 - from) / (h * 3600e3) <= (sc.R - sc.L) / 72) || 12;
    const d = new Date(from); d.setMinutes(0, 0, 0); d.setHours(Math.ceil((d.getHours() + (from > d.getTime() ? 1 : 0)) / hrs) * hrs);
    for (; d.getTime() < M.t1; d.setHours(d.getHours() + hrs)) ticks.push([d.getTime(), timeLabel(tmIso(d.getTime())).replace(':00', '')]);
  }
  const labels = [];
  const place = (x, text, anchor, cls = 'ax') => {
    const w = text.length * 6.4;
    const a = anchor === 'start' ? x : anchor === 'end' ? x - w : x - w / 2;
    if (labels.some((l) => a < l.b + 8 && a + w > l.a - 8)) return '';
    labels.push({ a, b: a + w });
    return `<text class="${cls}" x="${f(x)}" y="${Ht - 6}" text-anchor="${anchor}">${esc(text)}</text>`;
  };
  let xa = '';
  if (sc.gapEnd && M.open?.t) xa += place(sc.L, `Opened ${dayLabel(tmIso(M.open.t))}`, 'start');
  if (!isFinal(M.g)) xa += place(sc.R, 'Now', 'end');
  let tl = '';
  for (const [t, text] of ticks) {
    const x = X(t);
    if (x < (sc.gapEnd ? sc.X(sc.gapEnd) + 4 : sc.L + 4) || x > sc.R - 4) continue;
    const lab = place(x, text, 'middle');
    if (lab) { tl += `<line class="gt" x1="${f(x)}" x2="${f(x)}" y1="${T}" y2="${B}"/>`; xa += lab; }
  }
  if (!sc.gapEnd && M.open?.t) xa += place(sc.L, 'Open', 'start');
  const brk = sc.gapEnd ? `<path class="xbrk" d="M${f(sc.X(sc.gapEnd) - 4)} ${B + 5}l3 -10M${f(sc.X(sc.gapEnd))} ${B + 5}l3 -10"/>` : '';

  // series: faint books, then sharp, then the market on top
  const path = (pts, tEnd) => {
    let d = `M${f(X(pts[0][0]))},${f(Y(pts[0][1]))}`;
    for (let i = 1; i < pts.length; i++) d += ` H${f(X(pts[i][0]))} V${f(Y(pts[i][1]))}`;
    return `${d} H${f(X(tEnd))}`;
  };
  const order = [...M.has].sort((a, b) => (a.cons - b.cons) || (a.sharp - b.sharp));
  const lines = order.map((s) => {
    const cls = `s${s.cons ? ' cons' : s.sharp ? ' sh' : ''}${st.focus ? (st.focus === s.key ? ' on' : ' dim') : ''}`;
    return `<path class="${cls}" data-k="${esc(s.key)}" d="${path(s.pts, M.tEndPre)}"/>`;
  }).join('');
  const lead = M.cons || M.has[0];
  const gap = M.open?.t && lead && M.open.t < lead.pts[0][0] ? `<path class="gap" d="M${f(X(M.open.t))},${f(Y(M.open.v))} L${f(X(lead.pts[0][0]))},${f(Y(lead.pts[0][1]))}"/>` : '';
  const live = M.live.length ? `<path class="s live" d="${path(M.live, M.t1)}"/>` : '';
  const openDot = M.open?.t ? `<circle class="od" cx="${f(X(M.open.t))}" cy="${f(Y(M.open.v))}" r="4"><title>Opened ${esc(tmLine(M, M.open.v))}</title></circle>` : '';
  const koX = X(M.ko);
  const ko = M.ko > M.t0 && M.ko < M.t1 ? `<line class="ko" x1="${f(koX)}" x2="${f(koX)}" y1="${T}" y2="${B}"/><text class="kol" x="${f(koX + (koX > sc.R - 60 ? -4 : 4))}" y="${T + 10}" text-anchor="${koX > sc.R - 60 ? 'end' : 'start'}">Kickoff</text>` : '';
  const bets = M.mine.filter((x) => x.placed >= M.t0 && x.placed <= M.t1).map((x) => { const bx = f(X(x.placed)); return `<path class="ybet" d="M${bx} ${f(Y(x.v) - 6)}l6 6-6 6-6-6z"><title>Your bet: ${esc(tmLegText(M.g, x.leg))}</title></path><text class="bl" x="${bx}" y="${f(Y(x.v) - 10)}" text-anchor="middle">You ${esc(tmNum(M, x.v))}</text>`; }).join('');
  const evs = M.events.filter((e) => ['steam', 'key', 'flip', 'move', 'bet'].includes(e.kind)).sort((a, b) => (a.kind === 'steam') - (b.kind === 'steam')).map((e) => `<g><title>${esc(`${e.label}: ${e.text}`)}</title>${tmMarker(e.kind, f(X(e.t)), EY)}</g>`).join('');
  const aria = `Line history for ${M.mkt === 't' ? 'the total' : `${M.fav.abbr}'s spread`} across ${plural(M.has.length, 'book')}, from ${tmWhen(M.t0)} to ${tmWhen(M.t1)}.`;
  box.innerHTML = `<svg class="tm-c" viewBox="0 0 ${W} ${Ht}" width="${W}" height="${Ht}" role="img" aria-label="${esc(aria)}">
    ${tl}${grid}<line class="axl" x1="${sc.L}" x2="${sc.R}" y1="${B}" y2="${B}"/>${brk}${gap}${lines}${live}${ko}${openDot}${bets}${evs}${xa}<g id="tmHead"></g></svg>`;
  // line the scrubber's thumb travel up with the plot area (thumb is 24px wide)
  const sw = $('#tmScrub');
  if (sw) { sw.style.marginLeft = `calc(${((sc.L / W) * 100).toFixed(3)}% - 12px)`; sw.style.width = `calc(${(((sc.R - sc.L) / W) * 100).toFixed(3)}% + 24px)`; }
}

function tmDrawHead() {
  const st = tmS, M = st.M, g = $('#tmHead');
  if (!g || !st.sc) return;
  const x = st.X(st.t).toFixed(1);
  const tt = Math.min(st.t, M.tEndPre);
  let dots = '';
  const order = [...M.has].sort((a, b) => (a.cons - b.cons) || (a.sharp - b.sharp));
  for (const s of order) {
    if (tt < s.pts[0][0]) continue;
    const v = stepAt(s.pts, tt);
    if (v == null) continue;
    const r = s.cons ? 4.5 : s.sharp ? 3.5 : 2.75;
    dots += `<circle class="d${s.cons ? ' cons' : s.sharp ? ' sh' : ''}${st.focus === s.key ? ' on' : ''}" cx="${x}" cy="${st.Y(v).toFixed(1)}" r="${r}"/>`;
  }
  if (st.t > M.ko && M.live.length) { const v = stepAt(M.live, st.t); if (v != null) dots += `<circle class="d cons" cx="${x}" cy="${st.Y(v).toFixed(1)}" r="4.5"/>`; }
  g.innerHTML = `<line class="ph" x1="${x}" x2="${x}" y1="${st.T - 6}" y2="${st.EY + 8}"/>${dots}`;
}

// ------------------------------------------------------------ the playhead
function tmUpdate(src) {
  const st = tmS, M = st?.M;
  if (!M || !tmActive()) return;
  const t = st.t;
  st.atEnd = t >= M.t1 - 1000;
  const mk = tmMarketAt(M, t);
  const r = $('#tmRange');
  if (r && st.sc) {
    if (src !== 'range') r.value = String(Math.round(((st.X(t) - st.sc.L) / (st.sc.R - st.sc.L)) * 1000));
    r.setAttribute('aria-valuetext', `${tmWhen(t)}, ${mk ? tmLine(M, mk.v) : 'no line yet'}`);
  }
  tmDrawHead();
  tmReadout(M, t, mk);
  tmBoard(M, t);
  tmBets(M, t);
  // the event log: highlight the latest event at or before the playhead
  const rows = $$('#tmLog .tm-ev');
  let on = -1;
  M.events.forEach((e, i) => { if (e.t <= t + 1000) on = i; });
  rows.forEach((b, i) => { b.classList.toggle('on', i === on); if (i === on) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current'); });
}

function tmRel(t, M) {
  const ms = M.ko - t, a = Math.abs(ms);
  if (a < 60e3) return 'at kickoff';
  const m = Math.round(a / 60e3), h = Math.round(a / 3600e3), d = Math.round(a / 86400e3);
  const n = m < 90 ? `${m} min` : a < 40 * 3600e3 ? `${h} hr` : `${d} days`;
  return `${n} ${ms > 0 ? 'before' : 'after'} kickoff`;
}

function tmReadout(M, t, mk) {
  const el = $('#tmNow');
  if (!el) return;
  const st = tmS;
  const now = st.atEnd && !isFinal(M.g);
  const when = `<b>${now ? 'Now' : esc(tmWhen(t))}</b> · ${esc(M.g.tbd ? 'kickoff time TBA' : tmRel(t, M))}`;
  const eye = !mk ? 'No line yet' : mk.kind === 'live' ? 'In-game line' : mk.kind === 'close' ? 'Closing line' : mk.kind === 'open' ? 'Opening line' : mk.kind === 'median' ? 'Middle of the books' : 'Market';
  let mv = '';
  if (mk && M.open) {
    const d = Math.round((mk.v - M.open.v) * 10) / 10;
    const toward = M.mkt === 't' ? '' : d > 0 ? ` toward ${M.fav.abbr}` : d < 0 ? ` toward ${M.dog.abbr}` : '';
    mv = d ? `<span class="tm-mv num">${tmArrow(d)}</span><span class="tm-mvx">${esc(toward)} since the open</span>` : '<span class="tm-mvx">Even with the open</span>';
  }
  // who got to the current market number first
  let lead = '';
  const tt = Math.min(t, M.tEndPre);
  const cv = M.cons ? stepAt(M.cons.pts, tt) : null;
  const cm = M.cons ? tmLastMove(M.cons.mv, tt) : null;
  if (cv != null && cm) {
    let best = null;
    for (const s of M.has) {
      if (s.cons || stepAt(s.pts, tt) !== cv) continue;
      const lm = tmLastMove(s.mv, tt);
      if (lm && lm.to === cv && (!best || lm.t < best.t)) best = { key: s.key, t: lm.t };
    }
    if (best) lead = `${bookName(best.key)} got to ${tmLine(M, cv)} first, ${tmWhen(best.t)}`;
  }
  const ctx = [M.open ? `Opened ${tmLine(M, M.open.v)}${M.open.t ? ` ${dayLabel(tmIso(M.open.t))}` : ''}` : null, M.closeV != null ? `closed ${tmLine(M, M.closeV)}` : null, lead || null].filter(Boolean).join(' · ');
  el.innerHTML = `<div class="tm-when">${when}</div>
    <div class="tm-eye2">${esc(eye)}</div>
    <div class="tm-big"><span class="tm-line num">${esc(mk ? tmLine(M, mk.v) : '—')}</span><span class="tm-mvw">${mv}</span></div>
    ${ctx ? `<div class="tm-ctx">${esc(ctx)}</div>` : ''}`;
}

function tmBoard(M, t) {
  const el = $('#tmBoard');
  if (!el) return;
  const st = tmS;
  const tt = Math.min(t, M.tEndPre);
  const win = Math.max(10 * 60e3, (M.t1 - M.t0) * 0.012);
  const cv = M.cons ? stepAt(M.cons.pts, tt) : null;
  const rows = M.series.map((s) => {
    const p = s.pts.length ? tmPointAt(s.pts, tt) : null;
    const lm = tmLastMove(s.mv, tt);
    return { s, v: p ? p[1] : null, j: p ? p[2] : null, lm, moved: !!(lm && tt - lm.t < win && t <= M.tEndPre + win) };
  });
  // first to the market's current number
  let lead = null;
  if (cv != null && M.cons && tmLastMove(M.cons.mv, tt)) {
    for (const r of rows) if (!r.s.cons && r.v === cv && r.lm && r.lm.to === cv && (!lead || r.lm.t < lead.lm.t)) lead = r;
  }
  const sig = rows.map((r) => `${r.s.key}${r.v}${r.j}${r.lm?.t}${r.moved}`).join() + (lead?.s.key || '') + st.focus;
  if (sig === st.boardSig) return;
  st.boardSig = sig;
  const name = (k) => bookName(k);
  rows.sort((a, b) => (b.s.cons - a.s.cons) || ((a.v == null) - (b.v == null)) || ((b.v ?? 0) - (a.v ?? 0)) || name(a.s.key).localeCompare(name(b.s.key)));
  // juice is stored for the home side (spread) or the over (total)
  const juice = (j) => (j == null || (M.mkt === 's' && !M.favHome) ? '' : `${M.mkt === 't' ? 'o' : ''}${fmtOdds(j)}`);
  // Books that never posted a number for this game collapse into one line instead of a stack of dashes.
  const none = rows.filter((r) => !r.s.pts.length && !r.s.cons);
  const shown = rows.filter((r) => r.s.pts.length || r.s.cons);
  el.innerHTML = shown.map((r) => {
    const k = r.s.key;
    const d = r.lm ? Math.round((r.lm.to - r.lm.from) * 10) / 10 : 0;
    const tags = `${r.s.sharp ? '<span class="tag sharp">Sharp</span>' : ''}${lead === r ? '<span class="tag ink">First</span>' : ''}${r.moved ? '<span class="tag tm-hot">Moved</span>' : ''}`;
    const sub = r.v == null ? (r.s.pts.length ? `from ${tmWhen(r.s.pts[0][0])}` : 'no line recorded') : r.lm ? `from ${tmNum(M, r.lm.from)} · ${tmWhen(r.lm.t)}` : 'no change yet';
    const label = `${bookFull(k)}: ${r.v == null ? 'no line yet' : tmLine(M, r.v)}${d ? `, ${d > 0 ? 'up' : 'down'} ${trim(Math.abs(d))} from ${tmNum(M, r.lm.from)}` : ''}${r.s.sharp ? ', sharp book' : ''}${r.moved ? ', just moved' : ''}. Tap to highlight on the chart.`;
    return `<button type="button" class="tm-row${r.s.cons ? ' cons' : ''}${r.moved ? ' moved' : ''}" data-tm-focus="${esc(k)}" aria-pressed="${st.focus === k}" aria-label="${esc(label)}">
      <span class="tm-bk"><span class="tm-bn">${esc(name(k))}</span>${tags}<small>${esc(sub)}</small></span>
      <span class="tm-ch num">${d ? esc(tmArrow(d)) : ''}</span>
      <span class="tm-v num">${esc(tmNum(M, r.v))}<small>${esc(juice(r.j))}</small></span>
    </button>`;
  }).join('') + (none.length ? `<div class="tm-none-row"><span>No line recorded</span> ${esc(none.map((r) => name(r.s.key)).join(', '))}</div>` : '');
}

function tmBets(M, t) {
  const el = $('#tmBets');
  if (!el) return;
  const at = tmMarketAt(M, t);
  const closed = M.closeV != null;
  const ref = closed ? M.closeV : (M.cons ? M.cons.pts.at(-1)[1] : null);
  el.innerHTML = M.mine.map((x) => {
    const l = x.leg, b = x.bet;
    const vsNow = tmClv(M, l, at?.v);
    const vsClose = tmClv(M, l, ref);
    const book = S.books.find((k) => k.key === b.book) ? bookName(b.book) : b.book;
    const won = l.state === 'won' || l.state === 'win';
    return `<button type="button" class="tm-bet" data-tm-t="${x.placed || ''}" aria-label="${esc(`Your bet ${tmLegText(M.g, l)} ${fmtOdds(l.odds)}. ${tmSigned(vsNow)} versus the line at the playhead, ${tmSigned(vsClose)} versus the ${closed ? 'close' : 'current line'}. Tap to jump to when you placed it.`)}">
      <span class="tm-bw"><b class="num">${esc(tmLegText(M.g, l))}</b> <span class="num muted">${esc(fmtOdds(l.odds))}</span>${won ? ' <span class="tm-won">Won</span>' : ''}
        <small>${esc([book, x.placed ? `placed ${tmWhen(x.placed)}` : null].filter(Boolean).join(' · '))}</small></span>
      <span class="tm-cl"><b class="num">${esc(tmSigned(vsNow))}</b><small>vs playhead</small></span>
      <span class="tm-cl"><b class="num">${esc(tmSigned(vsClose))}</b><small>${closed ? 'vs close' : 'vs now'}</small></span>
    </button>`;
  }).join('');
}

// ------------------------------------------------------------ playback & seeking
function tmSeek(t) {
  const st = tmS;
  if (!st?.M) return;
  st.t = clamp(t, st.M.t0, st.M.t1);
  tmUpdate();
}
function tmPlayBtn() {
  const b = $('#tmPlay');
  if (!b) return;
  const on = !!tmS?.playing;
  b.innerHTML = on ? TM_SVG.pause : TM_SVG.play;
  b.setAttribute('aria-label', on ? 'Pause the replay' : 'Play the replay');
  b.classList.toggle('on', on);
}
function tmPlay() {
  const st = tmS;
  if (!st?.M || !st.sc) return;
  if (st.playing) { tmStop(); return; }
  if (st.atEnd || st.X(st.t) >= st.sc.R - 1) st.t = st.M.t0;
  st.playing = true;
  tmPlayBtn();
  if (tmReduced()) {
    // No animation: jump from one change to the next.
    const step = () => {
      if (!st.playing || tmS !== st || !tmActive()) { tmStop(); return; }
      const n = st.M.stops.find((x) => x > st.t + 500);
      st.t = n ?? st.M.t1;
      tmUpdate();
      if (n == null || st.t >= st.M.t1) { tmStop(); return; }
      st.timer = setTimeout(step, TM_STEP_MS);
    };
    tmUpdate();
    st.timer = setTimeout(step, TM_STEP_MS);
    return;
  }
  const x0 = st.X(st.t), start = performance.now();
  const frame = (now) => {
    if (!st.playing || tmS !== st || !tmActive()) { tmStop(); return; }
    const { sc } = st;
    const x = Math.min(sc.R, x0 + ((now - start) / TM_PLAY_MS) * (sc.R - sc.L));
    st.t = x >= sc.R ? st.M.t1 : sc.inv(x);
    tmUpdate();
    if (x >= sc.R) { tmStop(); return; }
    st.raf = requestAnimationFrame(frame);
  };
  st.raf = requestAnimationFrame(frame);
}
function tmStop() {
  const st = tmS;
  if (!st) return;
  const was = st.playing;
  st.playing = false;
  cancelAnimationFrame(st.raf);
  clearTimeout(st.timer);
  if (was) { tmPlayBtn(); if (st.pending && !st.drag && tmActive()) tmPaint(); }
}
function tmDragEnd() {
  const st = tmS;
  if (!st?.drag) return;
  st.drag = false;
  if (st.pending && !st.playing && tmActive()) tmPaint();
}
function tmJump(where) {
  const st = tmS, M = st?.M;
  if (!M) return;
  tmStop();
  if (where === 'open') tmSeek(M.open?.t ?? M.t0);
  else if (where === 'close') tmSeek(M.ko);
  else if (where === 'now') tmSeek(M.t1);
  else if (where === 'next') tmSeek(M.stops.find((x) => x > st.t + 500) ?? M.t1);
  else if (where === 'prev') tmSeek([...M.stops].reverse().find((x) => x < st.t - 500) ?? M.t0);
}

// Pointer scrubbing on the chart itself. Touch: a horizontal drag or a tap scrubs; a vertical drag scrolls.
function tmWire() {
  const st = tmS;
  const card = $('#tmChart');
  if (card) card.addEventListener('touchstart', (e) => e.stopPropagation(), { passive: true }); // never swipe the sheet closed from here
  const svg = $('#tmSvg');
  if (!svg || !st?.M) return;
  let id = null, x0 = 0, moved = false, type = '';
  const toT = (ev) => {
    const r = svg.getBoundingClientRect();
    const x = clamp(((ev.clientX - r.left) / r.width) * st.W, st.sc.L, st.sc.R);
    return st.sc.inv(x);
  };
  svg.addEventListener('pointerdown', (ev) => {
    id = ev.pointerId; x0 = ev.clientX; moved = false; type = ev.pointerType;
    if (type === 'mouse') { tmStop(); st.drag = true; moved = true; try { svg.setPointerCapture(id); } catch { /* ok */ } tmSeek(toT(ev)); }
  });
  svg.addEventListener('pointermove', (ev) => {
    if (ev.pointerId !== id) return;
    if (!moved) {
      if (Math.abs(ev.clientX - x0) < 6) return;
      moved = true; tmStop(); st.drag = true;
      try { svg.setPointerCapture(id); } catch { /* ok */ }
    }
    tmSeek(toT(ev));
  });
  const end = (ev, ok) => {
    if (ev.pointerId !== id) return;
    if (ok && !moved) { tmStop(); tmSeek(toT(ev)); }
    id = null;
    tmDragEnd();
  };
  svg.addEventListener('pointerup', (e) => end(e, true));
  svg.addEventListener('pointercancel', (e) => end(e, false));
}

// ------------------------------------------------------------ events (all delegated, data-tm-* only)
document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-tm-open],[data-tm-back],[data-tm-mkt],[data-tm-play],[data-tm-jump],[data-tm-t],[data-tm-focus]');
  if (!el) return;
  const d = el.dataset;
  if (d.tmOpen) { ev.preventDefault(); tmOpen(d.tmOpen, d.tmMkt); return; }
  if (!tmS || S.sheet?.kind !== 'tm') return;
  if (d.tmBack) { tmStop(); clearTimeout(tmTimer); openGame(d.tmBack); return; }
  if (d.tmMkt) {
    if (d.tmMkt === tmS.mkt) return;
    tmStop();
    tmS.mkt = d.tmMkt === 't' ? 't' : 's';
    tmS.focus = null;
    S.sheet.mkt = tmS.mkt; S.sheet.chartMkt = tmS.mkt;
    history.replaceState(null, '', `#tm/${tmS.gid}${tmS.mkt === 't' ? '/t' : ''}`);
    tmPaint();
    return;
  }
  if (d.tmPlay) { tmPlay(); return; }
  if (d.tmJump) { tmJump(d.tmJump); return; }
  if (d.tmT) { const t = Number(d.tmT); if (t) { tmStop(); tmSeek(t); } return; }
  if (d.tmFocus) {
    tmS.focus = tmS.focus === d.tmFocus ? null : d.tmFocus;
    tmDrawChart();
    tmUpdate();
  }
});

document.addEventListener('input', (ev) => {
  if (ev.target.id !== 'tmRange' || !tmS?.M || !tmS.sc) return;
  tmStop();
  const { sc } = tmS;
  const x = sc.L + (Number(ev.target.value) / 1000) * (sc.R - sc.L);
  tmS.t = clamp(sc.inv(x), tmS.M.t0, tmS.M.t1);
  tmUpdate('range');
});
document.addEventListener('change', (ev) => { if (ev.target.id === 'tmRange') tmDragEnd(); });
document.addEventListener('pointerdown', (ev) => { if (ev.target.id === 'tmRange' && tmS) tmS.drag = true; });
document.addEventListener('pointerup', () => tmDragEnd());
document.addEventListener('pointercancel', () => tmDragEnd());
// Arrow keys on the scrubber step from one change to the next; Home/End still go to the ends.
document.addEventListener('keydown', (ev) => {
  if (ev.target.id !== 'tmRange' || !tmS?.M) return;
  if (ev.key === 'ArrowRight' || ev.key === 'ArrowUp') { ev.preventDefault(); tmJump('next'); }
  else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowDown') { ev.preventDefault(); tmJump('prev'); }
  else if (ev.key === ' ' || ev.key === 'k') { ev.preventDefault(); tmPlay(); }
});

let tmResizeT = 0;
window.addEventListener('resize', () => {
  clearTimeout(tmResizeT);
  tmResizeT = setTimeout(() => {
    if (!tmActive() || !tmS.M) return;
    const w = $('#tmSvg')?.clientWidth || 0;
    if (Math.abs(w - tmS.W) > 4) { tmDrawChart(); tmUpdate(); }
  }, 120);
});

$('#dlg').addEventListener('close', () => {
  if (tmS) { tmStop(); tmS.drag = false; }
  clearTimeout(tmTimer); clearTimeout(tmSoon); tmSoon = 0;
  if (location.hash.startsWith('#tm/')) history.replaceState(null, '', `#${S.tab}`);
});

// ------------------------------------------------------------ deep link: #tm/<gid> or #tm/<gid>/t
function tmRoute() {
  const m = /^#tm\/(\d+)(?:\/(s|t))?$/.exec(location.hash);
  if (!m) return;
  const gid = m[1], mkt = m[2] || 's';
  const go = (n) => {
    if (location.hash !== m[0]) return;
    if (!S.weeks.size && n < 80) { setTimeout(() => go(n + 1), 200); return; }
    if (tmActive() && tmS.gid === gid && tmS.mkt === mkt) return;
    tmOpen(gid, mkt);
  };
  go(0);
}
window.addEventListener('hashchange', tmRoute);
setTimeout(tmRoute, 0);
