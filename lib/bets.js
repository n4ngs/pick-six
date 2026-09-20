'use strict';
/* Tickets, one private log per person. Every bet carries its owner's id (a random device id from a secure cookie,
   see server.js); the list, edits, deletes and CSV only ever touch the caller's own bets. Bets saved before owners
   existed have no owner: nobody sees them until the app's owner claims them with OWNER_CODE.
   The server grades every leg the moment its game goes final and records closing line value at kickoff. */

const crypto = require('node:crypto');
const { readJSON, writeJSON, num } = require('./util');

const MARKETS = new Set(['s', 't', 'ml', 'h1s', 'h1t', 'tt']);
const SIDES = new Set(['home', 'away', 'over', 'under']);

const dec = (o) => (o == null ? null : o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o));
const imp = (o) => (o == null ? null : o > 0 ? 100 / (o + 100) : Math.abs(o) / (Math.abs(o) + 100));
const toAmerican = (d) => (d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1)));

let store = readJSON('bets.json', { v: 1, bets: [] });
const save = () => writeJSON('bets.json', store);
const mine = (owner) => (b) => !!owner && b.owner === owner;
const list = (owner) => store.bets.filter(mine(owner));
// Everyone who owns at least one bet (the server pushes each of them their own list).
const owners = () => new Set(store.bets.map((b) => b.owner).filter(Boolean));
const unowned = () => store.bets.filter((b) => !b.owner).length;
// Give every unowned (pre-accounts) bet to this owner. Returns how many moved.
function claimUnowned(owner) {
  let n = 0;
  for (const b of store.bets) if (!b.owner) { b.owner = owner; n++; }
  if (n) save();
  return n;
}
// Move all of one owner's bets to another (linking a second device to the same log).
function merge(from, to) {
  let n = 0;
  for (const b of store.bets) if (b.owner === from) { b.owner = to; n++; }
  if (n) save();
  return n;
}

// ---------------------------------------------------------------- validation
function cleanLeg(l) {
  const leg = {
    gid: String(l.gid || ''),
    mkt: String(l.mkt || ''),
    side: String(l.side || ''),
    team: l.team === 'home' || l.team === 'away' ? l.team : null,
    line: num(l.line),
    odds: num(l.odds),
    label: String(l.label || '').slice(0, 80),
    matchup: String(l.matchup || '').slice(0, 80),
    start: l.start ? String(l.start) : null,
    state: 'open',
  };
  if (!/^\d+$/.test(leg.gid)) throw new Error('Pick a game.');
  if (!MARKETS.has(leg.mkt)) throw new Error('Pick a market.');
  if (!SIDES.has(leg.side)) throw new Error('Pick a side.');
  if (leg.mkt !== 'ml' && leg.line == null) throw new Error('Enter the line.');
  if (leg.mkt === 'tt' && !leg.team) throw new Error('Pick the team for the team total.');
  if (leg.odds == null || (leg.odds > -100 && leg.odds < 100)) throw new Error('Odds look off. Use American odds like -110 or +150.');
  return leg;
}

function create(body, owner) {
  if (!owner) throw new Error('Reload the app and try again.');
  const legs = (Array.isArray(body.legs) ? body.legs : []).slice(0, 12).map(cleanLeg);
  if (!legs.length) throw new Error('A bet needs at least one pick.');
  const stake = num(body.stake);
  if (!(stake > 0)) throw new Error('Enter how much you risked.');
  const parlayDec = legs.reduce((p, l) => p * dec(l.odds), 1);
  const odds = legs.length === 1 ? legs[0].odds : num(body.odds) ?? toAmerican(parlayDec);
  const bet = {
    id: crypto.randomUUID().slice(0, 8),
    owner,
    created: Date.now(),
    placed: body.placed ? String(body.placed) : new Date().toISOString(),
    book: String(body.book || '').slice(0, 30),
    stake,
    odds,
    note: String(body.note || '').slice(0, 200),
    legs,
    status: 'open',
    net: null,
    settled: null,
  };
  store.bets.unshift(bet);
  save();
  return bet;
}

function update(id, body, owner) {
  const b = store.bets.find((x) => x.id === id && mine(owner)(x));
  if (!b) return null;
  if (body.stake != null && num(body.stake) > 0) b.stake = num(body.stake);
  if (body.note != null) b.note = String(body.note).slice(0, 200);
  if (body.book != null) b.book = String(body.book).slice(0, 30);
  if (body.status === 'void' || body.status === 'open') { b.status = body.status; b.net = body.status === 'void' ? 0 : null; b.settled = body.status === 'void' ? Date.now() : null; if (body.status === 'open') for (const l of b.legs) l.state = 'open'; }
  save();
  return b;
}

function remove(id, owner) {
  const n = store.bets.length;
  store.bets = store.bets.filter((x) => !(x.id === id && mine(owner)(x)));
  if (store.bets.length !== n) save();
  return store.bets.length !== n;
}

// ---------------------------------------------------------------- grading
const pts = (t, half) => (half ? (t.q?.[0] ?? 0) + (t.q?.[1] ?? 0) : t.score ?? 0);

// Where a leg stands right now. margin > 0 is winning, 0 is a push, < 0 is losing.
function legMargin(l, g) {
  const half = l.mkt === 'h1s' || l.mkt === 'h1t';
  const h = pts(g.home, half), a = pts(g.away, half);
  if (l.mkt === 's' || l.mkt === 'h1s') return (l.side === 'home' ? h - a : a - h) + l.line;
  if (l.mkt === 'ml') return l.side === 'home' ? h - a : a - h;
  if (l.mkt === 't' || l.mkt === 'h1t') return l.side === 'over' ? h + a - l.line : l.line - (h + a);
  if (l.mkt === 'tt') { const s = pts(g[l.team], false); return l.side === 'over' ? s - l.line : l.line - s; }
  return null;
}

function legDone(l, g) {
  if (g.state === 'off') return 'void';
  const half = l.mkt === 'h1s' || l.mkt === 'h1t';
  const done = g.final || (half && (g.period > 2 || (g.period === 2 && g.half)));
  if (!done) return null;
  const m = legMargin(l, g);
  if (m == null) return null;
  // Moneyline ties (rare, but overtime can't end tied in college) grade as a push.
  return m > 0 ? 'won' : m < 0 ? 'lost' : 'push';
}

function settle(b) {
  const states = b.legs.map((l) => l.state);
  if (states.includes('lost')) return { status: 'lost', net: -b.stake };
  if (states.includes('open')) return null;
  const live = b.legs.filter((l) => l.state === 'won');
  if (!live.length) return { status: states.every((s) => s === 'void') ? 'void' : 'push', net: 0 };
  // A pushed or voided leg drops out of a parlay; the rest pay at their own prices.
  const d = b.legs.length === 1 ? dec(b.odds) : b.legs.every((l) => l.state === 'won') ? dec(b.odds) : live.reduce((p, l) => p * dec(l.odds), 1);
  return { status: 'won', net: Math.round(b.stake * (d - 1) * 100) / 100 };
}

// Closing line value for one leg against the market's closing number.
function clvOf(l, close) {
  if (!close) return null;
  const out = {};
  if (l.mkt === 's' && close.s != null) {
    const c = l.side === 'home' ? close.s : -close.s;
    out.line = c; out.pts = Math.round((l.line - c) * 10) / 10;
    const co = l.side === 'home' ? close.so?.[0] : close.so?.[1];
    const other = l.side === 'home' ? close.so?.[1] : close.so?.[0];
    if (out.pts === 0 && co != null && other != null) out.pct = edge(l.odds, co, other);
  } else if (l.mkt === 't' && close.t != null) {
    out.line = close.t; out.pts = Math.round((l.side === 'over' ? close.t - l.line : l.line - close.t) * 10) / 10;
    const co = l.side === 'over' ? close.to?.[0] : close.to?.[1];
    const other = l.side === 'over' ? close.to?.[1] : close.to?.[0];
    if (out.pts === 0 && co != null && other != null) out.pct = edge(l.odds, co, other);
  } else if (l.mkt === 'ml' && close.ml?.[0] != null && close.ml?.[1] != null) {
    const co = l.side === 'home' ? close.ml[0] : close.ml[1];
    const other = l.side === 'home' ? close.ml[1] : close.ml[0];
    out.odds = co; out.pct = edge(l.odds, co, other);
  } else return null;
  return out;
}
// Expected return of the price you got if the no-vig closing price is the truth, in percent.
function edge(mine, close, other) {
  const p = imp(close) / (imp(close) + imp(other));
  return Math.round((dec(mine) * p - 1) * 1000) / 10;
}

// Called whenever games update. Returns true if anything changed.
function refresh(gameOf, closeOf) {
  let changed = false;
  for (const b of store.bets) {
    if (b.status !== 'open') continue;
    for (const l of b.legs) {
      const g = gameOf(l.gid);
      if (!g) continue;
      if (!l.clv && g.state !== 'pre') {
        const c = closeOf(l.gid);
        const v = c && clvOf(l, c);
        if (v) { l.clv = v; changed = true; }
      }
      if (l.state === 'open') {
        const s = legDone(l, g);
        if (s) { l.state = s; l.final = { h: g.home.score, a: g.away.score }; changed = true; }
      }
    }
    const r = settle(b);
    if (r) { Object.assign(b, r, { settled: Date.now() }); changed = true; }
  }
  if (changed) save();
  return changed;
}

function openGameIds() {
  return [...new Set(store.bets.filter((b) => b.status === 'open').flatMap((b) => b.legs.filter((l) => l.state === 'open' || !l.clv).map((l) => l.gid)))];
}

function csv(owner) {
  const head = ['placed', 'book', 'type', 'picks', 'odds', 'stake', 'status', 'net', 'clv_pts', 'note'];
  const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  // Typed text can't start a spreadsheet formula.
  const t = (v) => (/^[=+\-@\t\r]/.test(String(v ?? '')) ? `'${v}` : v);
  const rows = list(owner).map((b) => [
    b.placed, t(b.book), b.legs.length > 1 ? `${b.legs.length}-leg parlay` : 'straight',
    t(b.legs.map((l) => `${l.label} (${l.matchup})`).join(' + ')), b.odds, b.stake, b.status, b.net ?? '',
    b.legs.length === 1 ? b.legs[0].clv?.pts ?? '' : '', t(b.note),
  ].map(q).join(','));
  return [head.join(','), ...rows].join('\n');
}

module.exports = { list, owners, unowned, claimUnowned, merge, create, update, remove, refresh, openGameIds, csv, legMargin, dec, imp };
