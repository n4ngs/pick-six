'use strict';
/* Pick Six — live data: the event stream, week loading, alerts and toasts. */

// ------------------------------------------------------------ render scheduling
let raf = 0;
function invalidate() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; renderAll(); }); }

// ------------------------------------------------------------ numbers you typed in at a window
/* The server sends what the feeds report, the same board for everyone. Numbers typed in at a counter belong
   to the device that typed them, so they're fetched separately and merged in here — one person at a window
   never moves a friend's screen. A typed number holds until that book's feed reports something newer. */
async function loadMine() {
  try { S.mine = (await (await fetch('/api/manual')).json()) || {}; } catch { /* offline: the board still works */ }
}
function withMine(g) {
  const feed = g.feed || g.books || {};
  const mine = S.mine[g.id];
  const out = { ...g, feed };
  if (!mine || !Object.keys(mine).length) { out.books = feed; return out; }
  const books = { ...feed };
  for (const [k, L] of Object.entries(mine)) {
    if (!(books[k]?.seen > L.at)) books[k] = { ...L, m: true, src: 'you', seen: L.at };
  }
  out.books = books;
  return out;
}
// Re-merge one game everywhere it's shown, after you save or remove a number.
function repaintMine(gid) {
  for (const w of S.weeks.values()) { const g = w.games.get(gid); if (g) w.games.set(gid, withMine(g)); }
  if (S.game?.game?.id === gid) S.game.game = gameById(gid);
  invalidate();
}
// Your numbers can land after the first board does; fold them into whatever is already on screen.
function remergeMine() {
  for (const w of S.weeks.values()) for (const [id, g] of w.games) w.games.set(id, withMine(g));
  if (S.game?.game) S.game.game = gameById(S.game.game.id) || S.game.game;
  invalidate();
}

// ------------------------------------------------------------ weeks
function putWeek(w, meta = {}) {
  const prev = S.weeks.get(w.id);
  const games = new Map(w.games.map((g) => [g.id, withMine(g)]));
  S.weeks.set(w.id, { meta: { id: w.id, season: w.season, type: w.type, week: w.week, label: w.label, detail: w.detail, ...meta }, games, moves: w.moves || [] });
  if (prev) for (const g of w.games) notePrices(prev.games.get(g.id), g);
}

function loadSnapshot(d) {
  S.offset = d.now - Date.now();
  S.season = d.season;
  S.cal = d.cal || [];
  S.def = d.def;
  S.cur = d.cur;
  S.tracked = d.tracked || [];
  S.books = d.books || S.books;
  S.bets = d.bets || [];
  if (d.me) S.me = d.me;
  S.liveMs = d.liveMs || S.liveMs;
  if (d.week) putWeek(d.week, { tracked: true });
  if (!S.boardWeek || !S.weeks.has(S.boardWeek)) S.boardWeek = S.def;
  S.moves = mergeMoves(d.week?.moves || [], S.moves);
  if (typeof grpMaybeWelcome === 'function') grpMaybeWelcome();
  invalidate();
}
const mergeMoves = (a, b) => [...new Map([...a, ...b].map((m) => [m.id, m])).values()].sort((x, y) => y.t - x.t).slice(0, 120);

async function openWeek(id) {
  if (!id || id === S.boardWeek && S.weeks.has(id)) return;
  S.boardWeek = id;
  const c = S.cal.find((x) => x.id === id);
  if (!S.weeks.has(id) || !S.weeks.get(id).meta.tracked) {
    renderBoard(true);
    try {
      const r = await fetch(`/api/week?season=${S.season}&type=${c.type}&week=${c.week}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not load that week');
      putWeek(j.week, { tracked: j.tracked });
    } catch (e) {
      toastText(e.message);
    }
  }
  invalidate();
}

// ------------------------------------------------------------ price flashes
// Remember each visible price so the board can flash the ones that just moved.
// Pregame, live and first-half prices are separate numbers, so each gets its own key.
const FLASH_MS = 2400;
const flashKey = (gid, src, book, m) => `${gid}|${src}|${book}|${m}`;
function notePrices(prev, g) {
  if (!prev) return;
  const now = Date.now();
  const diff = (src, cur, old, fields) => {
    for (const [k, L] of Object.entries(cur || {})) {
      const P = old?.[k];
      if (!P || !L) continue;
      for (const [m, a, b] of fields(P, L)) if (a !== b && !(a == null && b == null)) S.flashed.set(flashKey(g.id, src, k, m), now);
    }
  };
  const full = (P, L) => [['s', P.s, L.s], ['s', P.so?.[0], L.so?.[0]], ['t', P.t, L.t], ['t', P.to?.[0], L.to?.[0]], ['ml', P.ml?.[0], L.ml?.[0]], ['ml', P.ml?.[1], L.ml?.[1]]];
  diff('pre', g.books, prev.books, full);
  diff('live', g.live, prev.live, full);
  diff('h1', g.h1, prev.h1, (P, L) => [['h1s', P.s, L.s], ['h1s', P.so?.[0], L.so?.[0]], ['h1t', P.t, L.t], ['h1t', P.to?.[0], L.to?.[0]]]);
  // Redraw once the flash has run its course, so reduced-motion outlines clear on time.
  clearTimeout(notePrices.t);
  notePrices.t = setTimeout(invalidate, FLASH_MS + 50);
}
// Class and inline delay for a price cell. Redraws resume the animation where it was instead of restarting it.
function flashAttr(gid, src, book, m) {
  const at = S.flashed.get(flashKey(gid, src, book, m));
  const age = at == null ? Infinity : Date.now() - at;
  if (age >= FLASH_MS) { if (at != null) S.flashed.delete(flashKey(gid, src, book, m)); return { cls: '', style: '', label: '' }; }
  return { cls: ' tick', style: ` style="animation-delay:-${age}ms"`, label: 'just moved' };
}

// ------------------------------------------------------------ event stream
let es = null;
function connect() {
  es = new EventSource('/api/stream');
  const on = (type, fn) => es.addEventListener(type, (m) => { S.lastMsg = Date.now(); S.connected = true; fn(JSON.parse(m.data)); });
  es.onopen = () => { S.connected = true; S.lastMsg = Date.now(); renderPill(); };
  es.onerror = () => { S.connected = false; renderPill(); };
  on('snapshot', loadSnapshot);
  on('tick', (d) => { S.offset = d.now - Date.now(); S.liveCount = d.live; S.at = d.at || S.at; renderPill(); renderFreshness(); });
  on('game', (g) => {
    const w = S.weeks.get(g.wk);
    if (!w) return;
    const prev = w.games.get(g.id);
    const cur = withMine(g);
    notePrices(prev, cur);
    w.games.set(cur.id, cur);
    if (prev) watchGame(prev, cur);
    if (S.game?.game?.id === cur.id) S.game.game = cur;
    document.dispatchEvent(new CustomEvent('hl:game', { detail: { prev, g: cur } }));
    invalidate();
  });
  on('move', (m) => {
    S.moves = mergeMoves([m], S.moves);
    const w = S.weeks.get(m.wk);
    if (w) w.moves = mergeMoves([m], w.moves || []);
    announceMove(m);
    invalidate();
  });
  on('bets', (list) => { const before = S.bets; S.bets = list.filter((b) => !pendingDeletes.has(b.id)); settleAlerts(before, S.bets); invalidate(); });
}
function reconnect() {
  try { es?.close(); } catch { /* already closed */ }
  connect();
}
// Phones freeze background tabs; reconnect the moment the page is visible again.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && (!S.connected || Date.now() - S.lastMsg > 20000)) reconnect();
});
window.addEventListener('pageshow', (ev) => { if (ev.persisted) reconnect(); });
setInterval(() => { if (Date.now() - S.lastMsg > 30000) { S.connected = false; renderPill(); reconnect(); } }, 10000);

// ------------------------------------------------------------ alerts
let audio = null;
function unlockAudio() { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); if (audio.state === 'suspended') audio.resume(); } catch { audio = null; } }
document.addEventListener('pointerdown', () => { if (S.alerts !== 'off') unlockAudio(); }, { passive: true });
// Two soft notes, like a sportsbook ticker: up for good news, down for a line move.
function chime(up = true) {
  if (!audio) return;
  const t0 = audio.currentTime;
  [0, 0.12].forEach((dt, i) => {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = 'sine';
    o.frequency.value = up ? [660, 880][i] : [740, 554][i];
    g.gain.setValueAtTime(0, t0 + dt);
    g.gain.linearRampToValueAtTime(0.12, t0 + dt + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.35);
    o.connect(g).connect(audio.destination);
    o.start(t0 + dt);
    o.stop(t0 + dt + 0.4);
  });
}
function notify(title, body, tag) {
  if (document.visibilityState === 'visible' || !('Notification' in window) || Notification.permission !== 'granted') return;
  try { new Notification(title, { body, tag, icon: 'icons/icon-192.png' }); } catch { /* not allowed here */ }
}
// Toasts wait while you're reading or reaching for them.
function autoDismiss(el, ms) {
  let left = ms, t0 = Date.now(), timer = setTimeout(() => el.remove(), left);
  const pause = () => { clearTimeout(timer); left -= Date.now() - t0; };
  const resume = () => { t0 = Date.now(); clearTimeout(timer); timer = setTimeout(() => el.remove(), Math.max(1500, left)); };
  el.addEventListener('pointerenter', pause); el.addEventListener('pointerleave', resume);
  el.addEventListener('focusin', pause); el.addEventListener('focusout', resume);
}
function toastText(msg, action) {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast text';
  el.setAttribute('role', 'status');
  el.innerHTML = `<span>${esc(msg)}</span>${action ? `<button class="undo" type="button">${esc(action.label)}</button>` : ''}`;
  if (action) el.querySelector('button').onclick = () => { el.remove(); action.run(); };
  box.prepend(el);
  autoDismiss(el, action ? 6000 : 4000);
}
function toast({ logoUrl, kicker, title, line, win = false, open }) {
  const box = $('#toasts');
  const el = document.createElement('button');
  el.type = 'button';
  el.className = 'toast';
  el.innerHTML = `${logoUrl ? `<img src="${esc(logoUrl)}" alt="">` : '<span></span>'}<div><div class="t1${win ? ' w' : ''}">${win ? '' : '<span class="dot"></span>'}${esc(kicker)}</div><div class="t2">${esc(title)}</div><div class="t3">${esc(line || '')}</div></div>`;
  el.onclick = () => { el.remove(); if (open) openGame(open); };
  box.prepend(el);
  while (box.children.length > 3) box.lastChild.remove();
  autoDismiss(el, 8000);
}

const myGameIds = () => new Set(S.bets.filter((b) => b.status === 'open').flatMap((b) => b.legs.map((l) => l.gid)));
const followsGame = (g) => g && (S.follow.has(g.home.id) || S.follow.has(g.away.id));
function cares(gid) {
  if (S.alerts === 'all') return true;
  if (S.alerts !== 'mine') return false;
  return myGameIds().has(gid) || followsGame(gameById(gid));
}

function announceMove(m) {
  if (!cares(m.gid) || m.t < serverNow() - 5 * 60e3) return;
  const g = gameById(m.gid);
  const tx = moveText(m, g);
  const kicker = m.kind === 'steam' ? `Steam · ${m.books?.length || 3} books` : moveWord[m.kind];
  toast({ logoUrl: g?.[m.dir === 'home' || m.dir === 'away' ? m.dir : 'home']?.logo, kicker, title: tx.title, line: `${tx.from} → ${tx.to} · ${m.matchup || ''}`, open: m.gid });
  chime(false);
  notify(`${kicker}: ${tx.title}`, `${tx.from} → ${tx.to} · ${m.matchup || ''}`, m.id);
}

// Score and cover changes on games you have money on.
function watchGame(prev, g) {
  const legs = S.bets.filter((b) => b.status === 'open').flatMap((b) => b.legs.filter((l) => l.gid === g.id && l.state === 'open'));
  const kick = isPre(prev) && isLive(g);
  if (kick && (legs.length || (S.alerts !== 'off' && followsGame(g)))) {
    toast({ logoUrl: g.home.logo, kicker: 'Kickoff', title: `${g.away.abbr} @ ${g.home.abbr}`, line: closeOf(g)?.s != null ? `Closed ${favSide(g) ? `${g[favSide(g)].abbr} ${fmtPts(-Math.abs(closeOf(g).s))}` : 'PK'} · O/U ${fmtTot(closeOf(g).t)}` : '', open: g.id });
  }
  if (!legs.length || S.alerts === 'off') return;
  const scored = (prev.home.score ?? 0) !== (g.home.score ?? 0) || (prev.away.score ?? 0) !== (g.away.score ?? 0);
  for (const l of legs) {
    const a = legNow(prev, l), b = legNow(g, l);
    if (a == null || b == null) continue;
    if (scored && Math.sign(a) !== Math.sign(b)) {
      const winning = b > 0, push = b === 0;
      const kicker = push ? 'On the number · push' : winning ? 'Now covering' : 'Not covering';
      toast({ logoUrl: g[l.side === 'away' ? 'away' : 'home'].logo, kicker, title: `${l.label}`, line: `${g.away.abbr} ${g.away.score} · ${g.home.abbr} ${g.home.score} · ${clockLabel(g)}`, win: winning, open: g.id });
      if (!push) chime(winning);
      notify(`${kicker}: ${l.label}`, `${g.away.abbr} ${g.away.score} – ${g.home.abbr} ${g.home.score}, ${clockLabel(g)}`, `${g.id}-${l.label}`);
    }
  }
  if (!prev.sit?.rz && g.sit?.rz && legs.length) {
    const t = g[g.poss];
    toast({ logoUrl: t?.logo, kicker: 'Red zone', title: `${t?.abbr} at the ${g.sit.spot || 'red zone'}`, line: `${g.sit.short || ''} · ${clockLabel(g)} · you have ${plural(legs.length, 'bet')} here`, open: g.id });
  }
}

function settleAlerts(before, after) {
  const was = new Map(before.map((b) => [b.id, b.status]));
  for (const b of after) {
    if (was.get(b.id) !== 'open' || b.status === 'open') continue;
    const win = b.status === 'won';
    const label = b.legs.length > 1 ? `${b.legs.length}-leg parlay` : b.legs[0].label;
    toast({ kicker: b.status === 'won' ? 'Winner' : b.status === 'lost' ? 'Lost' : b.status === 'push' ? 'Push' : 'Void', title: label, line: `${fmtMoney(b.net, true)} · ${b.book || ''}`, win });
    if (S.alerts !== 'off') { chime(win); notify(`${b.status === 'won' ? 'Winner' : 'Graded'}: ${label}`, fmtMoney(b.net, true), `bet-${b.id}`); }
  }
}

// ------------------------------------------------------------ server calls
async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { 'content-type': 'application/json', ...(opts.headers || {}) } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
  return j;
}
async function loadKeys() {
  if (S.keys) return S.keys;
  try { S.keys = await api('/api/keys'); } catch { S.keys = null; }
  return S.keys;
}
