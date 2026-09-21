#!/usr/bin/env node
'use strict';
/**
 * Pick Six — live NFL lines, scores and your bets.
 * Zero dependencies. Node 18+.
 *
 * Data sources (all public, no keys):
 *   ESPN scoreboard          schedule, live score, down & distance, field position, DraftKings open/current, weather
 *   ESPN summary             win probability by play, drives, box score, FPI projection (per game, on demand)
 *   Action Network v2        lines from many books, pregame and live, consensus, public splits, team totals, rotation numbers
 *   Action Network v1        Station Casinos lines and first-half lines
 *   VSiN line tracker        the Las Vegas windows: Circa, Boomer's, Station, South Point, Westgate, Wynn, Caesars, BetMGM
 *   Pinnacle guest feed      the offshore sharp line and its bet limits
 *   Open-Meteo               wind, gusts and rain chance at kickoff for outdoor games
 *
 * Every line change is written to data/weeks/ so the app can draw movement and flag steam.
 * The browser gets everything over one Server-Sent Events stream.
 */

const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const U = require('./lib/util');
const ESPN = require('./lib/espn');
const AN = require('./lib/action');
const { Week } = require('./lib/lines');
const { BOOKS } = require('./lib/books');
const WX = require('./lib/weather');
const VSIN = require('./lib/vsin');
const PIN = require('./lib/pinnacle');
const Bets = require('./lib/bets');
const Manual = require('./lib/manual');
const Group = require('./lib/group');
const { margins } = require('./lib/margins');

const { log } = U;
const PORT = Number(process.env.PORT) || 4849;
const LIVE_MS = Math.max(4000, Number(process.env.LIVE_MS) || 8000); // scores while games are live
const ODDS_MS = Math.max(8000, Number(process.env.ODDS_MS) || 15000); // lines while games are live or kicking off soon
const HOT_MS = Math.max(6000, Number(process.env.HOT_MS) || 9000);    // lines in the last minutes before kickoff and in game
const VSIN_MS = Math.max(60000, Number(process.env.VSIN_MS) || 120000); // Vegas windows (VSiN refreshes every few minutes)
const PIN_MS = Math.max(300000, Number(process.env.PIN_MS) || 600000); // Pinnacle caches its guest feed for 15 minutes
const ACCESS_CODE = process.env.ACCESS_CODE || ''; // set this before putting the app on the internet
// The address phones should open. On Railway it's the service's public domain; at home it's this Mac on Wi-Fi.
const PUBLIC_URL = (process.env.PUBLIC_URL || (process.env.RAILWAY_PUBLIC_DOMAIN ? `https://${process.env.RAILWAY_PUBLIC_DOMAIN}` : '')).replace(/\/$/, '');
const OFF = new Set(String(process.env.SOURCES_OFF || '').toLowerCase().split(',').filter(Boolean)); // e.g. SOURCES_OFF=vsin,pinnacle
const PUBLIC = path.join(__dirname, 'public');

// ---------------------------------------------------------------- state
const cal = { season: null, weeks: [], at: 0 };
const weeks = new Map(); // id -> W
let defId = null;        // the week the app opens on
let curId = null;        // the week containing today
const clients = new Set();

const wid = (k) => `${k.season}-${k.type}-${String(k.week).padStart(2, '0')}`;

class W {
  constructor(k) {
    this.k = { season: k.season, type: k.type, week: k.week };
    this.id = wid(this.k);
    const c = cal.weeks.find((x) => x.type === k.type && x.week === k.week);
    this.label = c?.label || `Week ${k.week}`;
    this.detail = c?.detail || '';
    this.games = new Map();
    this.lines = new Week(this.k);
    this.anCache = new Map();
    this.an = new Map();  // gid -> v2 patch
    this.a1 = new Map();  // gid -> v1 patch
    this.wx = new Map();  // gid -> Open-Meteo
    this.fpi = new Map(); // gid -> { home, at }
    this.vs = new Map();  // gid -> VSiN Vegas books { books, open, h1 }
    this.pin = new Map(); // gid -> Pinnacle { line, h1, limit }
    this.sent = new Map(); // gid -> last emitted JSON
    this.at = { espn: 0, an: 0, a1: 0, wx: 0, vsin: 0, pin: 0 };
    this.loading = null;
  }
}
function getWeek(k) {
  const id = wid(k);
  if (!weeks.has(id)) weeks.set(id, new W(k));
  return weeks.get(id);
}
const tracked = () => [curId, defId, nextId()].filter((x, i, a) => x && a.indexOf(x) === i).map((id) => weeks.get(id)).filter(Boolean);
function nextId() {
  const cur = weeks.get(curId);
  if (!cur) return null;
  const i = cal.weeks.findIndex((x) => x.type === cur.k.type && x.week === cur.k.week);
  const n = cal.weeks[i + 1];
  return n ? wid({ season: cal.season, type: n.type, week: n.week }) : null;
}

// ---------------------------------------------------------------- the public game object
// One line per book. When several feeds carry the same book, the fastest wins:
// Action Network, then VSiN, then Action's public-betting feed, then Pinnacle, then ESPN.
// These are the feeds only. Numbers typed in at a counter belong to the device that typed them, so each
// browser merges its own on top of this (see /api/manual) and the recorded history stays the real market.
function mergedBooks(G, W) {
  const an = W.an.get(G.id), a1 = W.a1.get(G.id), vs = W.vs.get(G.id), pin = W.pin.get(G.id);
  const out = {};
  // `seen` is when this app last confirmed the number with its source (the board dims old ones).
  const put = (src, books, seen) => { for (const [k, L] of Object.entries(books || {})) if (!out[k] && L) out[k] = { ...L, src, seen: seen || null }; };
  put('an', an?.books, W.at.an);
  put('vsin', vs?.books, VSIN_AT.t);
  put('an1', a1?.books, W.at.a1);
  // Pinnacle's age is when it last listed this game, not when we last polled: a game it pulled (often news) goes stale.
  if (pin?.line) put('pin', { pin: pin.line }, pin.at || null);
  if (G.dk?.cur && (G.state === 'pre' || !an)) put('espn', { dk: G.dk.cur }, W.at.espn);
  return out;
}

function mergedHalf(G, W) {
  const out = {};
  const pin = W.pin.get(G.id);
  // Each first-half price carries when its source last confirmed it, so stale ones can be dimmed and skipped.
  for (const [src, at] of [[W.a1.get(G.id)?.h1, W.at.a1], [W.vs.get(G.id)?.h1, VSIN_AT.t], [pin?.h1 ? { pin: pin.h1 } : null, pin?.at]]) {
    for (const [k, L] of Object.entries(src || {})) if (!out[k] && L && (L.s != null || L.t != null)) out[k] = { ...L, seen: at || null };
  }
  return Object.keys(out).length ? out : null;
}

function marketOf(books) {
  const c = books.cons || books.dk || Object.values(books).find((b) => !b.m && b.s != null);
  return c ? { s: c.s, so: c.so, t: c.t, to: c.to, ml: c.ml } : null;
}

function openOf(G, W, books) {
  const o = books.open || G.dk?.open;
  if (!o || (o.s == null && o.t == null)) return null;
  const at = W.a1.get(G.id)?.openAt || null;
  return { s: o.s, t: o.t, ml: o.ml, at };
}

function pub(G, W) {
  const an = W.an.get(G.id) || {};
  const P = W.pin.get(G.id) || {};
  const books = mergedBooks(G, W);
  const H = W.lines.full(G.id);
  const wx = G.venue?.indoor ? { dome: true } : { ...(G.wx || {}), ...(W.wx.get(G.id) || {}) };
  const { dk, ...base } = G;
  const strip = ({ key, locKey, ...t }) => t;
  return {
    ...base,
    home: strip(G.home),
    away: strip(G.away),
    wk: W.id,
    rot: an.rot || null,
    books,
    live: G.state === 'in' ? an.live || {} : null,
    mkt: marketOf(books),
    open: openOf(G, W, books),
    close: H?.close || null,
    splits: an.splits || null,
    tt: an.tt || null,
    h1: mergedHalf(G, W),
    opens: W.vs.get(G.id)?.open || null,
    pinLimit: P.limit ?? null,
    // The in-play sharp number, and the only thing that makes it usable: how old the price actually is.
    // `age` is derived from Pinnacle's HTTP `age` header, so it measures the price, not our poll. Anything
    // consuming this must gate on it — the feed is CDN-cached for up to ~15 minutes, and a stale sharp
    // number is how a board shows an edge that stopped existing minutes ago.
    // UNITS: `age` is MILLISECONDS. The HTTP header is seconds; it is converted here, once, because every
    // consumer compares it against a ms freshness budget. Publishing the raw header would make a
    // five-minute-old price read as 300ms — fresh — which is the worst bug this feature could have.
    pinLive: P.liveLine
      ? { line: P.liveLine, limit: P.liveLimit ?? null, age: Number.isFinite(P.liveAge) ? P.liveAge * 1000 : null }
      : null,
    prob: G.state === 'in' ? an.prob || null : null,
    tickets: an.bets || null,
    fpi: W.fpi.get(G.id)?.home ?? null,
    wx,
    spark: { s: W.lines.spark(G.id, 's'), t: W.lines.spark(G.id, 't') },
    moves: (H?.moves || []).slice(-4),
  };
}

function weekSnapshot(W) {
  return {
    id: W.id, ...W.k, label: W.label, detail: W.detail,
    games: [...W.games.values()].map((G) => pub(G, W)).sort((a, b) => Date.parse(a.start) - Date.parse(b.start)),
    moves: W.lines.moves(Date.now() - 7 * 86400e3).slice(0, 60),
    at: W.at,
  };
}

// Books that actually sent a line this week (the rest are typed in at the counter).
function feeds() {
  const seen = new Set();
  for (const W of tracked()) {
    for (const m of [W.an, W.a1, W.vs]) for (const p of m.values()) for (const k of Object.keys(p.books || {})) seen.add(k);
    if ([...W.pin.values()].some((p) => p.line)) seen.add('pin');
  }
  return seen;
}

function snapshot(uid, role = 'owner') {
  const W = weeks.get(defId);
  const me = Group.person(uid);
  return {
    now: Date.now(),
    season: cal.season,
    cal: cal.weeks.map((c) => ({ ...c, id: wid({ season: cal.season, type: c.type, week: c.week }) })),
    def: defId, cur: curId, tracked: tracked().map((w) => w.id),
    week: W ? weekSnapshot(W) : null,
    books: BOOKS.map(({ key, name, short, vegas, sharp, site, ios }) => ({ key, name, short, vegas: !!vegas, sharp: !!sharp, site: site || null, ios: ios || null, feed: feeds().has(key) })),
    bets: Bets.list(uid),
    liveMs: LIVE_MS,
    // Who you are on this board, and — for a guest — the plain truth about who can see their tickets.
    me: { role, name: me?.name || '', named: !!me?.name, owner: OWNER_NAME || '', shared: !!ACCESS_CODE },
  };
}

// ---------------------------------------------------------------- SSE
function emit(type, data) {
  const msg = `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) res.write(msg);
}
// Bets are private: each connection gets only its own owner's list.
function emitBets() {
  if (!clients.size) return;
  const by = Bets.byOwner();
  for (const res of clients) res.write(`event: bets\ndata: ${JSON.stringify(by.get(res.uid) || [])}\n\n`);
}
function emitSnapshot() {
  for (const res of clients) res.write(`event: snapshot\ndata: ${JSON.stringify(snapshot(res.uid, res.role))}\n\n`);
}
// Push every game in the week whose public view changed since the last push.
function flush(W) {
  if (!tracked().includes(W)) return;
  for (const G of W.games.values()) {
    const p = pub(G, W);
    const s = JSON.stringify(p);
    if (W.sent.get(G.id) === s) continue;
    W.sent.set(G.id, s);
    if (clients.size) emit('game', p);
  }
}

// ---------------------------------------------------------------- ESPN
async function pollEspn(W) {
  const j = await ESPN.fetchScoreboard(W.k);
  const seen = new Set();
  for (const e of j.events || []) {
    const g = ESPN.gameFromEvent(e);
    if (!g) continue;
    seen.add(g.id);
    const prev = W.games.get(g.id);
    // ESPN drops odds once a game starts; keep the last pregame DraftKings numbers.
    if (!g.dk && prev?.dk) g.dk = prev.dk;
    if (prev && prev.state === 'pre' && g.state !== 'pre') onKickoff(W, g);
    W.games.set(g.id, g);
  }
  for (const id of W.games.keys()) if (!seen.has(id) && j.events?.length) W.games.delete(id);
  W.at.espn = Date.now();
  // Games that started before this server did still need a closing line.
  for (const g of W.games.values()) if (g.state !== 'pre' && !W.lines.full(g.id)?.close) onKickoff(W, g);
  if (Bets.refresh(gameById, closeById)) emitBets();
}

// How long after kickoff the board still counts as the closing board. Inside it, the books this app can
// see are still the numbers the game closed at. Outside it, they are in-game numbers.
const CLOSE_WINDOW = 5 * 60e3;

// The last pregame price each book showed. `recordBooks` only runs while a game is 'pre', so this
// history is pregame by construction — which is the whole point when a close has to be taken late.
function closeFromHistory(W, g) {
  const H = W.lines.full(g.id);
  const out = {};
  for (const [k, B] of Object.entries(H?.b || {})) {
    if (k === 'open') continue;
    const s = B.s?.at(-1), t = B.t?.at(-1), ml = B.ml?.at(-1);
    if (!s && !t && !ml) continue;
    out[k] = {
      s: s ? s[1] : null, so: [s ? s[2] : null, null],
      t: t ? t[1] : null, to: [t ? t[2] : null, null],
      ml: ml ? [ml[1], ml[2]] : [null, null],
    };
  }
  return out;
}

function onKickoff(W, g) {
  // Normally this runs the moment a game flips, and the live board is still the closing board. But the
  // sweep at the top of the ESPN poll also catches a game that kicked off while this server was down,
  // and by then mergedBooks() is reporting in-game numbers. Recording one of those as "the close" is
  // worse than recording nothing: it looks like data and it is not. Past the window, use the stored
  // pregame history, and if there is none, take no close at all.
  const late = Date.now() - Date.parse(g.start) > CLOSE_WINDOW;
  const books = late ? closeFromHistory(W, g) : mergedBooks(g, W);
  const c = books.cons || books.dk;
  if (!c || (c.s == null && c.t == null)) return;
  // A close rebuilt from history is the last price this app SAW, not necessarily the last price the book
  // hung. Mark it, so anything measuring closing line value later can tell the two apart instead of
  // treating an approximation as a reading.
  if (W.lines.setClose(g.id, { s: c.s, so: c.so, t: c.t, to: c.to, ml: c.ml, ...(late ? { est: true } : {}), books: Object.fromEntries(Object.entries(books).filter(([k]) => k !== 'open').map(([k, L]) => [k, { s: L.s, t: L.t, ml: L.ml }])) })) {
    log('close', g.away.abbr, '@', g.home.abbr, c.s, c.t, late ? '(from pregame history)' : '');
  }
}

// ---------------------------------------------------------------- Action Network
async function pollAn(W) {
  const j = await AN.fetchV2(W.k);
  const espnGames = [...W.games.values()];
  const parsed = AN.parseV2(j, espnGames, W.anCache);
  const now = Date.now();
  for (const [gid, patch] of parsed) {
    W.an.set(gid, patch);
    const G = W.games.get(gid);
    if (!G) continue;
    if (G.state === 'pre') recordBooks(W, G, now);
    if (G.state === 'in' && patch.live?.cons) W.lines.recordLive(gid, patch.live.cons, now);
    const o = patch.books.open;
    if (o) W.lines.setOpen(gid, { s: o.s, t: o.t, ml: o.ml, at: W.a1.get(gid)?.openAt || W.lines.full(gid)?.open?.at || null });
  }
  W.at.an = now;
}

async function pollAn1(W) {
  const j = await AN.fetchV1(W.k);
  const parsed = AN.parseV1(j, [...W.games.values()], W.anCache);
  const now = Date.now();
  // The opener's timestamp only comes from this feed.
  for (const ag of j.games || []) {
    const patch = parsed.get(W.anCache.get(ag.id)?.id);
    const o = (ag.odds || []).find((x) => x.book_id === 30 && x.type === 'game');
    if (patch && o?.inserted) patch.openAt = Date.parse(o.inserted);
  }
  for (const [gid, patch] of parsed) {
    W.a1.set(gid, patch);
    const G = W.games.get(gid);
    if (G?.state === 'pre') recordBooks(W, G, now);
    const H = W.lines.full(gid);
    if (patch.openAt && H?.open && !H.open.at) W.lines.setOpen(gid, { ...H.open, at: patch.openAt });
  }
  W.at.a1 = now;
}

// Write down every book's current number for a pregame game, and flag anything newsworthy.
function recordBooks(W, G, now = Date.now()) {
  const books = mergedBooks(G, W);
  const changes = [];
  for (const [k, L] of Object.entries(books)) changes.push(...W.lines.record(G.id, k, L, now));
  if (!changes.length) return;
  const cons = marketOf(books);
  const found = W.lines.detect(G.id, changes, cons, now);
  for (const m of found) {
    const detail = { ...m, wk: W.id, matchup: `${G.away.abbr} @ ${G.home.abbr}`, start: G.start, home: G.home.abbr, away: G.away.abbr };
    log('move', m.kind, detail.matchup, m.mkt, m.from, '→', m.to, m.books ? `(${m.books.join(', ')})` : '');
    emit('move', detail);
  }
}

// ---------------------------------------------------------------- Vegas windows (VSiN) and Pinnacle
// Both feeds list games across days, so each poll is matched against every tracked week.
const VSIN_AT = { t: 0, stamp: null };
async function pollVsin() {
  const v = await VSIN.fetchVsin();
  if (v.same && VSIN_AT.stamp) return false;
  VSIN_AT.stamp = v.stamp;
  VSIN_AT.t = VSIN.stampTime(v.stamp) || Date.now();
  const { all, weekOf } = trackedGames();
  for (const [gid, patch] of VSIN.matchAll(v.games, all)) {
    const W = weekOf.get(gid);
    W.vs.set(gid, patch);
    const G = W.games.get(gid);
    if (G.state === 'pre') recordBooks(W, G);
  }
  for (const W of tracked()) W.at.vsin = Date.now();
  return true;
}

async function pollPin() {
  const pg = await PIN.fetchPinnacle();
  const { all, weekOf } = trackedGames();
  for (const [gid, patch] of PIN.matchPinnacle(pg, all)) {
    const W = weekOf.get(gid);
    const prev = W.pin.get(gid);
    // Pinnacle takes the pre-game parent off its board at kickoff and lists the game again as a live
    // child. Keep the last pregame number as `line` — that is what the game closed at — and let the
    // in-play price ride alongside it, never over it.
    W.pin.set(gid, patch.line
      ? { ...patch, at: Date.now() }
      : { ...prev, ...patch, line: prev?.line ?? null, h1: prev?.h1 ?? null, limit: prev?.limit ?? null, live: true, at: Date.now() }); // `at`: last time Pinnacle listed it
    const G = W.games.get(gid);
    if (G.state === 'pre' && patch.line) recordBooks(W, G);
  }
  for (const W of tracked()) W.at.pin = Date.now();
}

function trackedGames() {
  const all = [], weekOf = new Map();
  for (const W of tracked()) for (const G of W.games.values()) { all.push(G); weekOf.set(G.id, W); }
  return { all, weekOf };
}

// ---------------------------------------------------------------- FPI, weather
async function pollFpi(W) {
  const now = Date.now();
  const due = [...W.games.values()].find((g) => g.state === 'pre' && (!W.fpi.has(g.id) || now - W.fpi.get(g.id).at > 6 * 3600e3));
  if (!due) return false;
  try {
    const s = ESPN.summaryOf(await ESPN.fetchSummary(due.id));
    W.fpi.set(due.id, { home: s.fpi?.home ?? null, at: now });
    summaries.set(due.id, s);
  } catch (e) {
    W.fpi.set(due.id, { home: null, at: now - 5 * 3600e3 }); // try again in an hour
    throw e;
  }
  return true;
}

async function pollWx(W) {
  const soon = [...W.games.values()].filter((g) => g.state === 'pre' && Date.parse(g.start) - Date.now() < 10 * 86400e3);
  const got = await WX.forecast(soon);
  for (const [id, wx] of got) W.wx.set(id, wx);
  W.at.wx = Date.now();
}

// ---------------------------------------------------------------- one game in depth
const summaries = new Map(); // gid -> parsed summary
async function summary(G) {
  const s = summaries.get(G.id);
  const ttl = G.state === 'in' ? LIVE_MS : G.state === 'pre' ? 5 * 60e3 : 3600e3;
  if (s && Date.now() - s.at < ttl) return s;
  try {
    const fresh = ESPN.summaryOf(await ESPN.fetchSummary(G.id));
    summaries.set(G.id, fresh);
    return fresh;
  } catch (e) {
    log('summary', G.id, e.message);
    return s || null;
  }
}

// ---------------------------------------------------------------- bets need games from any week
function gameById(gid) {
  for (const W of weeks.values()) { const G = W.games.get(gid); if (G) return G; }
  return strays.get(gid) || null;
}
function closeById(gid) {
  for (const W of weeks.values()) { const H = W.lines.full(gid); if (H?.close) return H.close; }
  return null;
}
// Bets on games outside the loaded weeks (an old ticket, a bowl) get graded from the game summary.
const strays = new Map();
async function pollStrays() {
  for (const gid of Bets.openGameIds()) {
    if ([...weeks.values()].some((W) => W.games.has(gid))) continue;
    try {
      const j = await ESPN.fetchSummary(gid);
      const comp = j.header?.competitions?.[0];
      if (!comp) continue;
      const g = ESPN.gameFromEvent({ id: gid, date: comp.date, competitions: [comp] });
      if (g) strays.set(gid, g);
    } catch (e) { log('stray', gid, e.message); }
  }
  if (Bets.refresh(gameById, closeById)) emitBets();
}

// ---------------------------------------------------------------- calendar and the default week
async function refreshCalendar() {
  const j = await ESPN.fetchScoreboard();
  const c = ESPN.calendarOf(j);
  if (!c.season || !c.weeks.length) throw new Error('ESPN calendar missing');
  cal.season = c.season;
  cal.weeks = c.weeks;
  cal.at = Date.now();
  const now = Date.now();
  // The week containing today; between weeks, the next one to start.
  const cur = c.weeks.find((w) => now >= Date.parse(w.start) && now <= Date.parse(w.end))
    || c.weeks.find((w) => Date.parse(w.start) > now) || c.weeks.at(-1);
  curId = wid({ season: c.season, type: cur.type, week: cur.week });
  getWeek({ season: c.season, type: cur.type, week: cur.week });
  const nid = nextId();
  if (nid) { const n = cal.weeks.find((w) => wid({ season: c.season, type: w.type, week: w.week }) === nid); getWeek({ season: c.season, type: n.type, week: n.week }); }
  pickDefault();
}

// Open on the current week until its last game has been final for ten hours, then on next week's lines.
function pickDefault() {
  const cur = weeks.get(curId);
  let id = curId;
  if (cur && cur.games.size) {
    const all = [...cur.games.values()];
    const done = all.every((g) => g.state === 'post' || g.state === 'off');
    const last = Math.max(...all.map((g) => Date.parse(g.start)));
    if (done && Date.now() - last > 10 * 3600e3 && nextId()) id = nextId();
  }
  if (id !== defId) {
    const was = defId;
    defId = id;
    if (was) { log('default week', defId); emitSnapshot(); }
  }
}

// ---------------------------------------------------------------- loops
const busy = new Set();
async function once(key, fn) {
  if (busy.has(key)) return;
  busy.add(key);
  try { await fn(); } catch (e) { log(key, e.message); } finally { busy.delete(key); }
}
const liveish = (W) => [...W.games.values()].some((g) => g.state === 'in' || (g.state === 'pre' && Date.parse(g.start) - Date.now() < 30 * 60e3 && Date.parse(g.start) - Date.now() > -3 * 3600e3));
const today = (W) => [...W.games.values()].some((g) => g.day === U.etDate() && g.state !== 'post');
// The hot window: a game is on the field, or kickoff is inside the last quarter of an hour, when the number
// moves fastest and a stale board costs the most. Everything else can wait a few seconds longer.
const hot = (W) => [...W.games.values()].some((g) => g.state === 'in' || (g.state === 'pre' && Date.parse(g.start) - Date.now() < 15 * 60e3 && Date.parse(g.start) - Date.now() > -3 * 3600e3));

function every(fn, msFor) {
  const run = async () => {
    await fn();
    setTimeout(run, msFor());
  };
  run();
}

function startLoops() {
  every(async () => {
    await Promise.all(tracked().map((W) => once(`espn ${W.id}`, async () => {
      const ms = liveish(W) ? LIVE_MS : today(W) ? 45000 : 5 * 60e3;
      if (Date.now() - W.at.espn < ms - 500) return;
      await pollEspn(W);
      flush(W);
    })));
    pickDefault();
  }, () => 2000);

  every(async () => {
    await Promise.all(tracked().map((W) => once(`an ${W.id}`, async () => {
      if (!W.games.size) return;
      const ms = hot(W) ? HOT_MS : liveish(W) ? ODDS_MS : today(W) ? 30000 : 3 * 60e3;
      if (Date.now() - W.at.an < ms - 500) return;
      await pollAn(W);
      flush(W);
    })));
  }, () => 2000);

  every(async () => {
    await Promise.all(tracked().map((W) => once(`an1 ${W.id}`, async () => {
      if (!W.games.size) return;
      const ms = liveish(W) || today(W) ? 90000 : 5 * 60e3;
      if (Date.now() - W.at.a1 < ms - 500) return;
      await pollAn1(W);
      flush(W);
    })));
  }, () => 5000);

  every(async () => {
    for (const W of tracked()) {
      await once(`fpi ${W.id}`, async () => { if (await pollFpi(W)) flush(W); });
    }
  }, () => 2500);

  if (!OFF.has('vsin')) every(() => once('vsin', async () => { if (await pollVsin()) tracked().forEach(flush); }), () => (tracked().some(hot) ? Math.max(60000, Math.round(VSIN_MS / 2)) : VSIN_MS));
  if (!OFF.has('pinnacle')) every(() => once('pinnacle', async () => { await pollPin(); tracked().forEach(flush); }), () => PIN_MS);

  every(async () => {
    for (const W of tracked()) await once(`wx ${W.id}`, async () => { if (Date.now() - W.at.wx > 3600e3 && W.games.size) { await pollWx(W); flush(W); } });
  }, () => 60e3);

  every(() => once('strays', pollStrays), () => 10 * 60e3);
  every(() => once('calendar', refreshCalendar), () => 30 * 60e3);

  setInterval(() => { for (const W of weeks.values()) { try { W.lines.save(); } catch (e) { log('save', e.message); } } }, 30000);

  setInterval(() => {
    if (!clients.size) return;
    const W = weeks.get(curId);
    const live = W ? [...W.games.values()].filter((g) => g.state === 'in').length : 0;
    emit('tick', { now: Date.now(), live, at: Object.fromEntries(tracked().map((w) => [w.id, w.at])) });
  }, 2000);
}

// ---------------------------------------------------------------- other weeks (history browsing)
async function loadWeek(k) {
  const W = getWeek(k);
  if (tracked().includes(W) || Date.now() - W.at.espn < 10 * 60e3) return W;
  if (!W.loading) {
    W.loading = (async () => {
      await pollEspn(W);
      await Promise.allSettled([pollAn(W), pollAn1(W)]);
    })().finally(() => { W.loading = null; });
  }
  await W.loading;
  return W;
}

// ---------------------------------------------------------------- HTTP
function lanUrls() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) for (const a of list || []) if (a.family === 'IPv4' && !a.internal) out.push(`http://${a.address}:${PORT}`);
  return out;
}
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.json': 'application/json',
  '.webmanifest': 'application/manifest+json', '.txt': 'text/plain; charset=utf-8',
};
function sendJSON(res, code, body) {
  sendBody(res, code, JSON.stringify(body), { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    let n = 0; const chunks = [];
    req.on('data', (c) => { n += c.length; if (n > 64 * 1024) { reject(new Error('Too large')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => { try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}); } catch { reject(new Error('Bad JSON')); } });
    req.on('error', reject);
  });
}

// ---------------------------------------------------------------- optional access code
// Off by default (a Mac on home Wi-Fi). With ACCESS_CODE set, every page and API needs the code once per device.
const crypto = require('node:crypto');
const hashCode = (c) => crypto.createHash('sha256').update(`hl:${c}`).digest('hex');
const codeHash = ACCESS_CODE ? hashCode(ACCESS_CODE) : '';
// What an owner's installed icon carries in its start_url so a Home Screen launch is still the owner. Derived
// from the code, never stored; changing ACCESS_CODE invalidates it along with everything else.
const ownerKey = ACCESS_CODE ? crypto.createHash('sha256').update(`launch:${codeHash}`).digest('hex').slice(0, 32) : '';
const KEY_RE = /^[a-f0-9]{32}$/;
const TOK_RE = /^[a-f0-9]{24}$/;
const sameHash = (a, b) => {
  // Compare BYTE length, not JS string length: a 32-character multi-byte string is 64 bytes, and handing
  // timingSafeEqual two different-sized buffers throws. Untrusted input reaches here, so it must not throw.
  const A = Buffer.from(String(a ?? ''), 'utf8');
  const B = Buffer.from(String(b ?? ''), 'utf8');
  return A.length === B.length && A.length > 0 && crypto.timingSafeEqual(A, B);
};
// Five wrong codes from one address in 15 minutes locks that address out for the rest of the window,
// and 100 wrong codes from anywhere locks the login for everyone (a backstop against address rotation).
const LOGIN_WINDOW = 15 * 60e3;
const failures = new Map(); // ip -> [timestamps]
let allFailures = [];       // every wrong code, any address
// The client can write anything into X-Forwarded-For; only the last entry, appended by Railway's proxy, is real.
const clientIp = (req) => String(req.headers['x-forwarded-for'] || '').split(',').pop().trim() || req.socket.remoteAddress || '?';
function lockedOut(ip) {
  const now = Date.now();
  allFailures = allFailures.filter((t) => now - t < LOGIN_WINDOW);
  const recent = (failures.get(ip) || []).filter((t) => now - t < LOGIN_WINDOW);
  failures.set(ip, recent);
  if (failures.size > 5000) for (const [k, v] of failures) if (!v.length || now - v.at(-1) >= LOGIN_WINDOW) failures.delete(k);
  return recent.length >= 5 || allFailures.length >= 100;
}
// One device can't flood the shared files: a generous budget of changes, far above real use (a busy Sunday
// is a few dozen), so a runaway script or a stuck retry loop gets stopped and a person never notices.
const WRITE_WINDOW = 5 * 60e3, WRITE_MAX = 120;
const writes = new Map(); // uid -> times of recent changes
function writeBudget(uid) {
  const now = Date.now();
  if (writes.size > 5000) for (const [k, v] of writes) if (!v.length || now - v.at(-1) >= WRITE_WINDOW) writes.delete(k);
  const list = (writes.get(uid) || []).filter((t) => now - t < WRITE_WINDOW);
  writes.set(uid, list);
  if (list.length >= WRITE_MAX) return false;
  list.push(now);
  return true;
}
const cookieOf = (req) => Object.fromEntries(String(req.headers.cookie || '').split(';').map((c) => c.trim().split('=')).filter((x) => x[0]));
function authed(req) {
  return roleOf(req) !== null;
}
// ---------------------------------------------------------------- whose bets
// Every device gets a random id in a secure cookie, set silently on its first visit, so nobody signs up and
// nobody is signed out. Bets belong to that id. A second device joins the same log with a short-lived link
// code (Tools). OWNER_CODE lets the app's owner claim bets saved before ids existed.
const OWNER_CODE = process.env.OWNER_CODE || '';
// Whose board this is, for the wording a guest reads ("Chris's board"). Only a display name.
const OWNER_NAME = (process.env.OWNER_NAME || '').trim().slice(0, 24);
const UID_RE = /^[a-f0-9]{32}$/;
const uidOf = (req) => { const v = cookieOf(req).ps_uid || ''; return UID_RE.test(v) ? v : ''; };
// setHeader replaces; a join sets two cookies at once, so they're appended.
function addCookie(res, str) {
  const had = res.getHeader('set-cookie');
  res.setHeader('set-cookie', had ? [].concat(had, str) : [str]);
}
const cookieOpts = (req) => `Path=/; Max-Age=63072000; HttpOnly; SameSite=Lax${req.headers['x-forwarded-proto'] === 'https' ? '; Secure' : ''}`;
function setUid(req, res, uid) {
  addCookie(res, `ps_uid=${uid}; ${cookieOpts(req)}`);
}
function ensureUid(req, res) {
  let uid = uidOf(req);
  if (!uid) { uid = crypto.randomBytes(16).toString('hex'); setUid(req, res, uid); }
  return uid;
}
// Two ways in. The code makes you the owner of the board; a share link makes you a guest, who sees the whole
// board and only their own tickets. With no code set, the app is open and everyone is the owner.
function roleOf(req) {
  if (!ACCESS_CODE) return 'owner';
  if (sameHash(cookieOf(req).ps_code || '', codeHash)) return 'owner';
  return Group.byToken(cookieOf(req).ps_key || '') ? 'guest' : null;
}
// Link codes: 8 characters without look-alikes, good for 10 minutes and one use.
const LINK_ABC = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
const links = new Map(); // code -> { uid, exp }
function newLink(uid) {
  for (const [k, v] of links) if (v.exp < Date.now()) links.delete(k);
  let code = '';
  const bytes = crypto.randomBytes(8);
  for (const b of bytes) code += LINK_ABC[b % LINK_ABC.length];
  links.set(code, { uid, exp: Date.now() + 10 * 60e3 });
  return { code, exp: Date.now() + 10 * 60e3 };
}
const OPEN_PATHS = new Set(['/manifest.webmanifest', '/icons/icon.svg', '/icons/apple-touch-icon.png', '/icons/icon-192.png', '/icons/icon-512.png']);
function loginPage(res, wrong, note) {
  return gatePage(res, { mode: wrong ? 'wrong' : 'signedout', note });
}
// The one screen someone lands on without access. A guest has no code and never will, so the code box is not
// the offer here — getting back in with the link they already have is. Three modes, one layout.
function gatePage(res, { mode = 'signedout', note = '' } = {}) {
  const who = OWNER_NAME ? `${OWNER_NAME}'s board` : 'This board';
  const H = {
    signedout: ['Tap your link again', `${who} doesn't recognise this phone. Open the link you were texted and you're straight back in \u2014 there is nothing to type.`],
    revoked: ['This link was turned off', OWNER_NAME ? `Ask ${OWNER_NAME} for a new one.` : 'Ask for a new one.'],
    wrong: ['Pick Six', 'That code didn\u2019t match.'],
  }[mode] || ['Pick Six', note || ''];
  res.writeHead(mode === 'wrong' ? 401 : 200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
  res.end(`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="same-origin"><title>Pick Six</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#000;color:#F5F5F7;font:16px/1.45 ui-sans-serif,system-ui;padding:24px}.w{width:min(340px,90vw);text-align:center}h1{font-size:26px;margin:0 0 10px;letter-spacing:-.03em}p{color:#9C9CA4;margin:0 0 22px}button,input{height:48px;border-radius:14px;border:0;font:inherit;padding:0 14px;width:100%{}}button{background:#F5F5F7;color:#000;font-weight:600;cursor:pointer}input{background:#161618;color:#F5F5F7;margin-bottom:10px}.alt{margin-top:18px;font-size:14px;color:#6E6E76}.alt a{color:#9C9CA4}#code,#paste{display:none;margin-top:12px}.err{color:#FF6B6B;font-size:14px;min-height:18px;margin-top:8px}</style>
<div class="w"><h1>${H[0]}</h1><p>${H[1]}</p>
<button id="b">Paste my link</button>
<div id="paste"><input id="t" placeholder="Paste the link here" autocomplete="off"><button id="go">Open it</button></div>
<div class="err" id="e"></div>
<div class="alt"><a href="#" id="c">I have an access code</a></div>
<form id="code" method="post" action="/login"><input name="code" type="password" autocomplete="current-password" aria-label="Access code"><button>Open</button></form></div>
<script>
var TOK=/([a-f0-9]{24})/;
function go(v){var m=TOK.exec(String(v||''));if(m){location.href='/j/'+m[1];return true}return false}
document.getElementById('b').onclick=function(){
  var e=document.getElementById('e');e.textContent='';
  try{navigator.clipboard.readText().then(function(v){if(!go(v)){document.getElementById('paste').style.display='block';e.textContent='That clipboard has no link in it.'}},show)}catch(x){show()}
  function show(){document.getElementById('paste').style.display='block';document.getElementById('t').focus()}
};
document.getElementById('go').onclick=function(){if(!go(document.getElementById('t').value))document.getElementById('e').textContent='That does not look like your link.'};
document.getElementById('c').onclick=function(ev){ev.preventDefault();document.getElementById('code').style.display='grid'};
try{
  var m={mode};
  if(m==='revoked'){localStorage.removeItem('ps.key')}
  else if(!sessionStorage.getItem('ps.heal')){
    var c=localStorage.getItem('ps.ok'),k=localStorage.getItem('ps.key');
    if(c&&/^[a-f0-9]{32}$/.test(c)){sessionStorage.setItem('ps.heal','1');location.replace('/?c='+c)}
    else if(k&&/^[a-f0-9]{24}$/.test(k)){sessionStorage.setItem('ps.heal','1');location.replace('/?k='+k)}
  }
}catch(x){}
</script>`.replace('{mode}', JSON.stringify(mode)));
}
/* ------------------------------------------------------------------ compression

   Nothing here was compressed. The client is 472 KB of JS and CSS that gzips to 140 KB, and the week
   payload is ~59 KB of JSON that goes out on every load and every reconnect. On a phone on stadium wifi
   that difference is the difference between the board being there and the board still loading.

   Built into Node, so the zero-dependency rule holds. Compressed static files are cached in memory and
   keyed by mtime, so a file is compressed once per edit, not once per request. Brotli when the browser
   takes it (smaller), gzip otherwise.

   Deliberately NOT applied to the SSE stream: /api/stream is a long-lived push channel and putting a
   compressor in front of it risks buffering a live price update until the next flush. Live beats small. */
const zlib = require('zlib');
const COMPRESSIBLE = /^(?:text\/|application\/(?:json|javascript|manifest\+json)|image\/svg)/;
const fileMtime = (f) => { try { return fs.statSync(f).mtimeMs; } catch { return 0; } };
const COMPRESS_MIN = 1024;
const zCache = new Map();  // `${file}|${mtime}|${enc}` -> Buffer

function encFor(res) {
  const ae = String(res.__ae || '');
  if (/\bbr\b/.test(ae)) return 'br';
  if (/\bgzip\b/.test(ae)) return 'gzip';
  return null;
}
const zip = (buf, enc) => (enc === 'br'
  ? zlib.brotliCompressSync(buf, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 5 } })
  : zlib.gzipSync(buf, { level: 6 }));

// One place that decides whether a response is worth compressing, and does it.
function sendBody(res, code, body, headers) {
  const buf = Buffer.isBuffer(body) ? body : Buffer.from(body);
  const type = String(headers['content-type'] || '');
  const enc = buf.length >= COMPRESS_MIN && COMPRESSIBLE.test(type) ? encFor(res) : null;
  if (!enc) { res.writeHead(code, headers); return res.end(buf); }
  let out;
  try { out = zip(buf, enc); } catch { res.writeHead(code, headers); return res.end(buf); }
  res.writeHead(code, { ...headers, 'content-encoding': enc, vary: 'accept-encoding', 'content-length': out.length });
  res.end(out);
}

// public/index.html, read once and re-read when it changes on disk.
let idxCache = { mtime: 0, html: '' };
function indexHTML() {
  const f = path.join(PUBLIC, 'index.html');
  const m = fs.statSync(f).mtimeMs;
  if (m !== idxCache.mtime) idxCache = { mtime: m, html: fs.readFileSync(f, 'utf8') };
  return idxCache.html;
}

const server = http.createServer(async (req, res) => {
  res.__ae = req.headers['accept-encoding'] || '';   // read by sendBody(); keeps ~30 call sites unchanged
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const p = url.pathname;
  const M = req.method;
  if (ACCESS_CODE && p === '/login' && M === 'POST') {
    const ip = clientIp(req);
    if (lockedOut(ip)) { res.writeHead(429, { 'content-type': 'text/plain; charset=utf-8', 'retry-after': '900' }); return res.end('Too many tries. Wait 15 minutes.'); }
    let body = '';
    req.on('data', (c) => { body += c; if (body.length > 2000) req.destroy(); });
    req.on('end', () => {
      const code = new URLSearchParams(body).get('code') || '';
      if (!sameHash(hashCode(code), codeHash)) { failures.get(ip).push(Date.now()); allFailures.push(Date.now()); log('login: wrong code from', ip); return loginPage(res, true); }
      failures.delete(ip);
      const secure = req.headers['x-forwarded-proto'] === 'https' ? '; Secure' : '';
      res.writeHead(303, { location: '/', 'set-cookie': `ps_code=${codeHash}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax${secure}` });
      res.end();
    });
    return;
  }
  // A share link: /j/<token>. Opening it lets this phone in and remembers it, so a friend never types a code.
  const jm = /^\/j\/([a-f0-9]{24})$/.exec(p);
  if (jm && (M === 'GET' || M === 'HEAD')) {
    const inv = Group.byToken(jm[1]);
    if (!inv) return gatePage(res, { mode: 'revoked' });
    // Your own link, opened on the device that holds the code: you'd stay the owner and see no difference, and
    // the link would count a use that wasn't a friend. Say so instead.
    if (roleOf(req) === 'owner') {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
      return res.end(`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pick Six</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#000;color:#F5F5F7;font:16px/1.5 ui-sans-serif,system-ui;text-align:center;padding:24px}div{max-width:380px}h1{font-size:24px;margin:0 0 10px;letter-spacing:-.02em}p{color:#9C9CA4;margin:0 0 20px}a{color:#F5F5F7}</style>
<div><h1>That's your own link</h1><p>You're signed in as the owner on this device, so this link changes nothing here. To see what a friend sees, open it in a private window.</p><a href="/">Back to the board</a></div>`);
    }
    const uid = ensureUid(req, res);
    addCookie(res, `ps_key=${inv.token}; ${cookieOpts(req)}`);
    Group.useInvite(inv.token, uid);
    log('join:', inv.label);
    res.writeHead(303, { location: '/' });
    return res.end();
  }
  // ---- an installed icon: its manifest, and its launch ----------------------
  // The manifest an installed icon is built from. The token is in the PATH, not a cookie, because a manifest is
  // fetched with credentials omitted \u2014 a cookie-reading manifest would quietly be served the gate page as HTML
  // and the phone would install the defaults without a word. Sits above the gate, which is what makes it open.
  const mm = /^\/m\/([kc])\/([a-f0-9]{24,32})\.webmanifest$/.exec(p);
  if (mm && (M === 'GET' || M === 'HEAD')) {
    let base;
    try { base = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'manifest.webmanifest'), 'utf8')); }
    catch { return sendJSON(res, 500, { error: 'manifest' }); }
    base.start_url = `/?${mm[1]}=${mm[2]}`;
    base.scope = '/';
    // Icon srcs resolve against the MANIFEST's url, not the origin. Served two segments deep, a relative
    // "icons/icon-192.png" would resolve to /m/k/icons/... and 404, and Android would install a bare shortcut
    // with no icon instead of an app. Make them absolute.
    if (Array.isArray(base.icons)) base.icons = base.icons.map((i) => ({ ...i, src: String(i.src || '').replace(/^(?!\/|https?:)/, '/') }));
    res.writeHead(200, { 'content-type': 'application/manifest+json; charset=utf-8', 'cache-control': 'private, no-store' });
    return res.end(M === 'HEAD' ? '' : JSON.stringify(base));
  }
  if (p.startsWith('/m/') && (M === 'GET' || M === 'HEAD')) { res.writeHead(404); return res.end(); }

  // An installed icon launching. On iOS a Home Screen web app has its own cookie jar, so the cookie set when the
  // link was tapped in Safari may simply not be here. Re-assert it from the token baked into start_url, every
  // launch, and re-check it against the live invite list so revoking still locks someone out instantly.
  if (ACCESS_CODE && (p === '/' || p === '/index.html') && M === 'GET') {
    const c = url.searchParams.get('c') || '';
    const k = url.searchParams.get('k') || '';
    // Shape-check before any comparison: this is unauthenticated input, and it used to reach a byte-length
    // comparison that threw and took the process down.
    if (KEY_RE.test(c) && ownerKey) {
      const ip = clientIp(req);
      // Same throttle as /login. A launch key is an owner credential; it must not be a way around the lockout.
      if (lockedOut(ip)) { res.writeHead(429, { 'content-type': 'text/plain; charset=utf-8', 'retry-after': '900' }); return res.end('Too many tries. Wait 15 minutes.'); }
      if (sameHash(c, ownerKey)) {
        failures.delete(ip);
        addCookie(res, `ps_code=${codeHash}; ${cookieOpts(req)}`);
        req.headers.cookie = `${req.headers.cookie ? req.headers.cookie + '; ' : ''}ps_code=${codeHash}`;
      } else {
        failures.get(ip).push(Date.now()); allFailures.push(Date.now());
        log('launch: wrong owner key from', ip);
      }
    } else if (TOK_RE.test(k)) {
      const inv = Group.byToken(k);
      if (inv) {
        const who = ensureUid(req, res);
        addCookie(res, `ps_key=${inv.token}; ${cookieOpts(req)}`);
        req.headers.cookie = `${req.headers.cookie ? req.headers.cookie + '; ' : ''}ps_key=${inv.token}`;
        Group.touchInvite(inv.token, who);
      } else if (!authed(req)) {
        // Dead token AND no other way in: say the link was turned off. If they still hold a live cookie from a
        // newer link, fall through silently rather than locking them out of access they legitimately have \u2014
        // rotating a link must not brick the icon of someone already back in on the new one.
        return gatePage(res, { mode: 'revoked' });
      }
    }
  }

  if (p === '/api/health' && !authed(req)) return sendJSON(res, 200, { ok: true }); // uptime checks only; details need the code
  if (!authed(req) && !OPEN_PATHS.has(p)) {
    if (p.startsWith('/api/')) return sendJSON(res, 401, { error: 'Access code required' });
    return loginPage(res, false);
  }
  const uid = ensureUid(req, res);
  const role = roleOf(req);
  // The page carries the manifest that matches who is holding it, so Add to Home Screen bakes a start_url that
  // re-authenticates on every launch instead of one that depends on a cookie surviving.
  if ((p === '/' || p === '/index.html') && M === 'GET') {
    let link = '<link rel="manifest" href="/manifest.webmanifest">', stash = '';
    if (ACCESS_CODE && role === 'owner') {
      link = `<link rel="manifest" href="/m/c/${ownerKey}.webmanifest">`;
      stash = `<script>try{localStorage.setItem('ps.ok',${JSON.stringify(ownerKey)});sessionStorage.removeItem('ps.heal')}catch(e){}</script>`;
    } else if (ACCESS_CODE && role === 'guest') {
      const t = cookieOf(req).ps_key || '';
      if (TOK_RE.test(t)) {
        link = `<link rel="manifest" href="/m/k/${t}.webmanifest">`;
        stash = `<script>try{localStorage.setItem('ps.key',${JSON.stringify(t)});sessionStorage.removeItem('ps.heal')}catch(e){}</script>`;
      }
    }
    // Take the credential back out of the address bar as soon as it has done its job.
    stash += '<script>try{if(location.search)history.replaceState(null,"",location.pathname)}catch(e){}</script>';
    const html = indexHTML().replace('<link rel="manifest" href="manifest.webmanifest">', link + stash);
    return sendBody(res, 200, html, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'private, no-store', vary: 'cookie' });
  }
  // `self` records the owner's own phone so it is visible in the Admin Center. Only on a board with an
  // access code: without one everybody is the owner, and every passer-by would become a row.
  Group.note(uid, Group.byToken(cookieOf(req).ps_key || '')?.id || null, { ua: req.headers['user-agent'], addr: clientIp(req), self: role === 'owner' && !!ACCESS_CODE });
  if (M !== 'GET' && M !== 'HEAD' && p.startsWith('/api/') && !writeBudget(uid)) return sendJSON(res, 429, { error: 'That\u2019s a lot of changes at once. Give it five minutes.' });
  const ownerOnly = () => sendJSON(res, 403, { error: 'Only the person who runs this board can do that.' });
  try {
    if (p === '/api/stream') {
      res.writeHead(200, { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-store', connection: 'keep-alive', 'x-accel-buffering': 'no' });
      res.write('retry: 2000\n\n');
      res.write(`event: snapshot\ndata: ${JSON.stringify(snapshot(uid, role))}\n\n`);
      res.uid = uid;
      res.role = role;
      clients.add(res);
      const ping = setInterval(() => res.write(': ping\n\n'), 15000);
      req.on('close', () => { clearInterval(ping); clients.delete(res); });
      return;
    }
    if (p === '/api/week') {
      const k = { season: Number(url.searchParams.get('season')) || cal.season, type: Number(url.searchParams.get('type')) || 2, week: Number(url.searchParams.get('week')) };
      if (!(k.week >= 1 && k.week <= 20)) return sendJSON(res, 400, { error: 'Use ?week=N&type=2|3' });
      const W = await loadWeek(k);
      return sendJSON(res, 200, { now: Date.now(), tracked: tracked().includes(W), week: weekSnapshot(W) });
    }
    const gm = /^\/api\/game\/(\d+)$/.exec(p);
    if (gm) {
      for (const W of weeks.values()) {
        const G = W.games.get(gm[1]);
        if (!G) continue;
        const s = await summary(G);
        if (s?.fpi && G.state === 'pre') W.fpi.set(G.id, { home: s.fpi.home, at: Date.now() });
        return sendJSON(res, 200, { now: Date.now(), game: pub(G, W), hist: W.lines.full(G.id), summary: s });
      }
      return sendJSON(res, 404, { error: 'That game is not loaded. Open its week first.' });
    }
    // ---- the group: share links, who's here, and what they've got running (the owner's side)
    if (p === '/api/invites') {
      if (role !== 'owner') return ownerOnly();
      if (M === 'GET') return sendJSON(res, 200, { base: PUBLIC_URL || lanUrls()[0] || '', links: Group.invites() });
      if (M === 'POST') {
        const inv = Group.makeInvite((await readBody(req)).label);
        log('share link made for', inv.label);
        return sendJSON(res, 200, inv);
      }
    }
    const im = /^\/api\/invites\/([a-f0-9]{12})$/.exec(p);
    if (im && M === 'DELETE') {
      if (role !== 'owner') return ownerOnly();
      const gone = Group.revoke(im[1]);
      if (gone) log('share link turned off');
      return sendJSON(res, gone ? 200 : 404, { ok: gone });
    }
    if (p === '/api/group' && M === 'GET') {
      if (role !== 'owner') return ownerOnly();
      const links = Object.fromEntries(Group.invites().map((i) => [i.id, i.label]));
      const by = Bets.byOwner();
      // A summary per person plus whatever they have running: the size of this holds steady as the board grows.
      return sendJSON(res, 200, {
        people: Group.people(uid).map((P) => {
          const bets = by.get(P.uid) || [];
          const done = bets.filter((b) => b.status === 'won' || b.status === 'lost' || b.status === 'push');
          return {
            ...P,
            via: links[P.via] || null,
            n: bets.length,
            won: done.filter((b) => b.status === 'won').length,
            lost: done.filter((b) => b.status === 'lost').length,
            net: done.reduce((t, b) => t + (b.net || 0), 0),
            risk: done.reduce((t, b) => t + (b.stake || 0), 0),
            open: bets.filter((b) => b.status === 'open').map(({ owner, ...b }) => b),
          };
        }),
      });
    }
    const pm = /^\/api\/group\/([a-f0-9]{32})$/.exec(p);
    if (pm && M === 'GET') {
      if (role !== 'owner') return ownerOnly();
      const P = Group.person(pm[1]);
      if (!P) return sendJSON(res, 404, { error: 'Nobody by that id.' });
      return sendJSON(res, 200, { name: P.name || '', bets: Bets.list(pm[1]).map(({ owner, ...b }) => b) });
    }
    // ---- your log: status, your name, link another device, claim pre-accounts bets
    /* Owner-only, and deliberately richer than /api/group.

       A shared board's owner can already see who is on it and what they have running. What they cannot
       see is the shape of it: who is actually any good, who has gone quiet, who is betting more than
       they used to. All of that is derivable from records already on disk — no new tracking, nothing
       collected that was not already being stored to run the board.

       The sharpest column here is closing line value. Win rate over a handful of bets is mostly noise;
       whether someone consistently beats the number they bet into is the one measure that means
       something at this sample size, and every settled leg already carries it.

       The app makes no privacy claim to a guest in either direction — it does not announce this view, and
       it must not tell anyone their log is private, because it is not. */
    if (p === '/api/group/activity' && M === 'GET') {
      if (role !== 'owner') return ownerOnly();
      /* `since` is the background poll the owner's app runs to notice somebody joining or betting. It
         answers with the new events only and skips the ledger entirely, so watching the board costs a
         few hundred bytes a minute instead of the whole log. */
      const since = Number(url.searchParams.get('since')) || 0;
      if (since) {
        const out = [];
        const nm = new Map(Group.people().map((P) => [P.uid, P.name || '']));
        for (const P of Group.people()) {
          if (P.uid === uid) continue;                       // the owner's own comings and goings are not news
          if (P.first && P.first > since) out.push({ t: P.first, kind: 'joined', uid: P.uid, name: nm.get(P.uid) || '', dev: P.dev || '' });
        }
        for (const [owner, list] of Bets.byOwner()) {
          if (owner === uid || !nm.has(owner)) continue;
          for (const b of list) {
            const t = Date.parse(b.placed) || b.created || 0;
            if (t > since) out.push({ t, kind: 'placed', uid: owner, name: nm.get(owner) || '', stake: b.stake, book: b.book || '', legs: (b.legs || []).length });
            if (b.settled && b.settled > since) out.push({ t: b.settled, kind: b.status, uid: owner, name: nm.get(owner) || '', stake: b.stake, net: b.net });
          }
        }
        out.sort((a, b) => a.t - b.t);
        return sendJSON(res, 200, { now: Date.now(), since, events: out.slice(-25) });
      }
      const by = Bets.byOwner();
      const people = Group.people();   // every device, the owner's own included and marked below
      const nameOf = new Map(people.map((P) => [P.uid, P.name || 'Someone']));
      const median = (a) => { if (!a.length) return null; const v = [...a].sort((x, y) => x - y); const m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
      const timeline = [];
      const rows = people.map((P) => {
        const bets = by.get(P.uid) || [];
        const done = bets.filter((b) => b.status === 'won' || b.status === 'lost' || b.status === 'push');
        const open = bets.filter((b) => b.status === 'open');
        const stakes = bets.map((b) => b.stake).filter((x) => x > 0);
        const clvPts = [], mkts = {}, books = {};
        for (const b of bets) {
          for (const l of b.legs || []) {
            if (l.clv && Number.isFinite(l.clv.pts)) clvPts.push(l.clv.pts);
            if (l.mkt) mkts[l.mkt] = (mkts[l.mkt] || 0) + 1;
          }
          if (b.book) books[b.book] = (books[b.book] || 0) + 1;
          const t = Date.parse(b.placed) || b.created || 0;
          if (t) timeline.push({ t, kind: 'placed', uid: P.uid, name: nameOf.get(P.uid), stake: b.stake, book: b.book || '', legs: (b.legs || []).length, status: b.status });
          if (b.settled) timeline.push({ t: b.settled, kind: b.status, uid: P.uid, name: nameOf.get(P.uid), stake: b.stake, net: b.net, legs: (b.legs || []).length });
        }
        if (P.first) timeline.push({ t: P.first, kind: 'joined', uid: P.uid, name: nameOf.get(P.uid), via: P.via || null });
        // Current run, newest settled first.
        const seq = done.slice().sort((a, b) => (b.settled || 0) - (a.settled || 0));
        let streak = 0, dir = null;
        for (const b of seq) {
          if (b.status === 'push') continue;
          if (dir == null) { dir = b.status; streak = 1; } else if (b.status === dir) streak++; else break;
        }
        const days = P.first ? Math.max(1, Math.round((Date.now() - P.first) / 86400e3)) : 1;
        const risked = done.reduce((t, b) => t + (b.stake || 0), 0);
        const net = done.reduce((t, b) => t + (b.net || 0), 0);
        return {
          uid: P.uid, name: P.name || '', via: P.via || null, first: P.first || null, last: P.last || null,
          dev: P.dev || '', addr: P.addr || '', opens: P.opens || 0, seen: P.seen || [], self: P.uid === uid,
          n: bets.length, openN: open.length,
          openRisk: open.reduce((t, b) => t + (b.stake || 0), 0),
          won: done.filter((b) => b.status === 'won').length,
          lost: done.filter((b) => b.status === 'lost').length,
          push: done.filter((b) => b.status === 'push').length,
          net, risked, roi: risked > 0 ? net / risked : null,
          avgStake: stakes.length ? stakes.reduce((a, b) => a + b, 0) / stakes.length : null,
          maxStake: stakes.length ? Math.max(...stakes) : null,
          medStake: median(stakes),
          clvN: clvPts.length,
          clvAvg: clvPts.length ? clvPts.reduce((a, b) => a + b, 0) / clvPts.length : null,
          clvBeat: clvPts.length ? clvPts.filter((x) => x > 0).length / clvPts.length : null,
          perWeek: bets.length / Math.max(1, days / 7),
          mkts, books, streak, streakKind: dir,
          lastBet: bets.length ? Math.max(...bets.map((b) => Date.parse(b.placed) || b.created || 0)) : null,
        };
      });
      timeline.sort((a, b) => b.t - a.t);
      /* Every tracked bet on the board, settled ones included, newest first.

         /api/group deliberately sends only what is running plus counts for the rest, because it is the
         summary a shared board paints constantly. This is the owner's ledger: the whole log, with legs
         and closing line value, so nothing about the board is visible to the app but invisible to the
         person who runs it. Capped so one very busy season cannot make the response unbounded; the cap
         is reported rather than silently applied. */
      const all = [];
      for (const [owner, list] of by) {
        if (!nameOf.has(owner) && owner !== uid) continue;   // orphaned rows are not somebody's activity
        for (const b of list) {
          all.push({
            id: b.id, uid: owner, name: owner === uid ? 'You' : (nameOf.get(owner) || 'Someone'),
            placed: b.placed, created: b.created, settled: b.settled,
            book: b.book || '', stake: b.stake, odds: b.odds, status: b.status, net: b.net,
            note: b.note || '',
            legs: (b.legs || []).map((l) => ({ gid: l.gid, mkt: l.mkt, side: l.side, line: l.line, odds: l.odds, team: l.team || null, state: l.state || null, clv: l.clv || null })),
          });
        }
      }
      all.sort((a, b) => (Date.parse(b.placed) || b.created || 0) - (Date.parse(a.placed) || a.created || 0));
      const CAP = 400;
      return sendJSON(res, 200, {
        now: Date.now(), people: rows, timeline: timeline.slice(0, 60),
        bets: all.slice(0, CAP), betsTotal: all.length, capped: all.length > CAP,
      });
    }
    /* Clear a device, or sweep the residue of testing.

       Owner-only. `bets=1` also drops that device's tracked bets, which is a separate and larger act
       than tidying a list, so it is never the default — the caller has to ask for it and the UI says
       which it is doing. A cleared device is not banned: a live share link lets it back in as a new row. */
    const rmPerson = /^\/api\/group\/person\/([a-f0-9]{8,64})$/.exec(p);
    if (rmPerson && M === 'DELETE') {
      if (role !== 'owner') return ownerOnly();
      const target = rmPerson[1];
      if (target === uid) return sendJSON(res, 400, { error: 'That is this device. Clearing yourself would lock you out of your own board.' });
      const bets = url.searchParams.get('bets') === '1' ? Bets.removeOwner(target) : 0;
      const gone = Group.forget(target);
      if (!gone && !bets) return sendJSON(res, 404, { error: 'Nobody here by that id.' });
      log('group: cleared device', target.slice(0, 8), bets ? `and ${bets} bet(s)` : '(bets kept)');
      emitSnapshot();
      return sendJSON(res, 200, { ok: true, bets });
    }
    // The dozen empty rows a few people leave behind while a link is being tested.
    if (p === '/api/group/sweep' && M === 'POST') {
      if (role !== 'owner') return ownerOnly();
      const by = Bets.byOwner();
      const ids = Group.idle(uid, (k) => (by.get(k) || []).length > 0);
      let n = 0;
      for (const id of ids) if (Group.forget(id)) n++;
      log('group: swept', n, 'unnamed device(s) with no bets');
      if (n) emitSnapshot();
      return sendJSON(res, 200, { ok: true, cleared: n });
    }
    if (p === '/api/me' && M === 'GET') return sendJSON(res, 200, { role, name: Group.person(uid)?.name || '', bets: Bets.list(uid).length, claimable: OWNER_CODE ? Bets.unowned() : 0 });
    if (p === '/api/me/name' && M === 'POST') {
      try { return sendJSON(res, 200, { name: Group.setName(uid, (await readBody(req)).name) }); } catch (e) { return sendJSON(res, 400, { error: e.message }); }
    }
    if (p === '/api/me/link' && M === 'POST') return sendJSON(res, 200, newLink(uid));
    if ((p === '/api/me/join' || p === '/api/me/claim') && M === 'POST') {
      const ip = clientIp(req);
      if (lockedOut(ip)) return sendJSON(res, 429, { error: 'Too many tries. Wait 15 minutes.' });
      const code = String((await readBody(req)).code || '').toUpperCase().replace(/[^A-Z0-9-]/g, '');
      const fail = (msg) => { failures.get(ip).push(Date.now()); allFailures.push(Date.now()); return sendJSON(res, 400, { error: msg }); };
      if (p === '/api/me/join') {
        const L = links.get(code);
        if (!L || L.exp < Date.now()) return fail('That code didn’t work. Codes last 10 minutes; make a new one on your other device.');
        links.delete(code);
        const moved = L.uid === uid ? 0 : Bets.merge(uid, L.uid); // bring this device's bets along
        Group.merge(uid, L.uid); // and one row on the board, not two
        setUid(req, res, L.uid);
        for (const c of clients) if (c.uid === uid) c.uid = L.uid;
        emitBets();
        return sendJSON(res, 200, { ok: true, moved, bets: Bets.list(L.uid).length });
      }
      if (!OWNER_CODE || !sameHash(hashCode(code.toLowerCase()), hashCode(OWNER_CODE.toLowerCase()))) return fail('That isn’t the owner code.');
      const n = Bets.claimUnowned(uid);
      emitBets();
      return sendJSON(res, 200, { ok: true, claimed: n });
    }
    if (p === '/api/bets' && M === 'GET') return sendJSON(res, 200, Bets.list(uid));
    if (p === '/api/bets' && M === 'POST') {
      const b = Bets.create(await readBody(req), uid);
      Bets.refresh(gameById, closeById);
      emitBets();
      return sendJSON(res, 200, b);
    }
    const bm = /^\/api\/bets\/([\w-]+)$/.exec(p);
    if (bm && M === 'PATCH') {
      const b = Bets.update(bm[1], await readBody(req), uid);
      if (!b) return sendJSON(res, 404, { error: 'No such bet' });
      Bets.refresh(gameById, closeById);
      emitBets();
      return sendJSON(res, 200, b);
    }
    if (bm && M === 'DELETE') {
      const ok = Bets.remove(bm[1], uid);
      emitBets();
      return sendJSON(res, ok ? 200 : 404, { ok });
    }
    if (p === '/api/bets.csv') {
      res.writeHead(200, { 'content-type': 'text/csv; charset=utf-8', 'content-disposition': 'attachment; filename="pick-six-bets.csv"' });
      return res.end(Bets.csv(uid));
    }
    if (p === '/api/manual' && M === 'GET') return sendJSON(res, 200, Manual.list(uid));
    if (p === '/api/manual' && M === 'POST') {
      const body = await readBody(req);
      try { return sendJSON(res, 200, Manual.set(uid, String(body.gid || ''), String(body.book || ''), body)); } catch (e) { return sendJSON(res, 400, { error: e.message }); }
    }
    if (p === '/api/manual' && M === 'DELETE') {
      const ok = Manual.clear(uid, String(url.searchParams.get('gid') || ''), String(url.searchParams.get('book') || ''));
      return sendJSON(res, 200, { ok });
    }
    if (p === '/api/keys') return sendJSON(res, 200, (await margins((cal.season || new Date().getFullYear()) - 1)) || { n: 0 });
    if (p === '/api/lan') return sendJSON(res, 200, { urls: PUBLIC_URL ? [PUBLIC_URL] : lanUrls(), public: !!PUBLIC_URL, port: PORT });
    if (p === '/api/health') {
      return sendJSON(res, 200, {
        ok: true, season: cal.season, def: defId, cur: curId, clients: clients.size, sources: U.health(), vsin: VSIN_AT,
        weeks: tracked().map((W) => ({ id: W.id, games: W.games.size, matched: W.an.size, at: W.at, live: [...W.games.values()].filter((g) => g.state === 'in').length })),
      });
    }
    if (M !== 'GET' && M !== 'HEAD') return sendJSON(res, 405, { error: 'Method not allowed' });
    const file = path.normalize(path.join(PUBLIC, p === '/' ? 'index.html' : decodeURIComponent(p)));
    if (!file.startsWith(PUBLIC)) return sendJSON(res, 403, { error: 'Forbidden' });
    fs.readFile(file, (err, buf) => {
      if (err) return sendJSON(res, 404, { error: 'Not found' });
      const type = TYPES[path.extname(file)] || 'application/octet-stream';
      /* `no-cache` means "revalidate every time", not "never store" — but with no validator to revalidate
         AGAINST, every load re-downloaded the whole client. An ETag keeps the silent-update behaviour
         exactly as it was (the browser still asks on every load, so a push is picked up immediately) and
         turns the answer into an empty 304 whenever the file has not changed. */
      const tag = `W/"${buf.length.toString(16)}-${Math.round(fileMtime(file)).toString(16)}"`;
      const head = { 'content-type': type, 'cache-control': 'no-cache', etag: tag };
      if (req.headers['if-none-match'] === tag) { res.writeHead(304, { etag: tag, 'cache-control': 'no-cache' }); return res.end(); }
      const enc = buf.length >= COMPRESS_MIN && COMPRESSIBLE.test(type) ? encFor(res) : null;
      if (!enc) { res.writeHead(200, head); return res.end(buf); }
      const key = `${file}|${fileMtime(file)}|${enc}`;
      let out = zCache.get(key);
      if (!out) {
        try { out = zip(buf, enc); } catch { res.writeHead(200, head); return res.end(buf); }
        if (zCache.size > 200) zCache.clear();   // bounded: this is a small static tree
        zCache.set(key, out);
      }
      res.writeHead(200, { ...head, 'content-encoding': enc, vary: 'accept-encoding', 'content-length': out.length });
      res.end(out);
    });
  } catch (e) {
    log('http', p, e.message);
    const client = /needs|Pick|Enter|Odds|Unknown|Bad JSON|Too large/.test(e.message);
    sendJSON(res, client ? 400 : 502, { error: e.message });
  }
});

function shutdown() {
  for (const W of weeks.values()) { try { W.lines.save(true); } catch { /* best effort */ } }
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

(async () => {
  // Accept connections right away: hosting platforms health-check the port during boot.
  // Pages that connect early get an empty snapshot, then the full one as soon as the data is in.
  server.listen(PORT, () => {
    log(`Pick Six is up → ${PUBLIC_URL || `http://localhost:${PORT}`}`);
    if (!PUBLIC_URL) for (const u of lanUrls()) log(`  on your phone (same Wi-Fi) → ${u}`);
    if (ACCESS_CODE) log('  access code is on');
    else if (PUBLIC_URL) log('  WARNING: no ACCESS_CODE set, so anyone with the link can see and change your bets');
  });
  for (let i = 0; ; i++) {
    try { await refreshCalendar(); break; } catch (e) {
      log('starting: ESPN calendar failed,', e.message, '— retrying');
      await U.sleep(Math.min(30000, 2000 * 2 ** i));
    }
  }
  for (const W of tracked()) {
    try { await pollEspn(W); } catch (e) { log('espn', e.message); }
    await Promise.allSettled([pollAn(W), pollAn1(W)]);
  }
  pickDefault();
  emitSnapshot();
  startLoops(); // VSiN and Pinnacle load in the first loop pass
  margins(cal.season - 1); // warm the key-number table in the background
  const W = weeks.get(defId);
  log(`loaded ${W?.label || '?'}: ${W?.games.size || 0} games, ${W?.an.size || 0} with multi-book lines`);
})();
