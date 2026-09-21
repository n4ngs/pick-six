'use strict';
/* Pinnacle, the offshore book sharp bettors treat as "the market". Its public guest feed needs no key,
   but Pinnacle caches it for up to 15 minutes, so this polls gently and labels the age.
   Also carries Pinnacle's bet limits: a rising limit means the number is firming up toward kickoff. */

const { getBody, getJSON, num, nameScore, log } = require('./util');

const BASE = 'https://guest.api.arcadia.pinnacle.com/0.1/leagues/889'; // 889 = NFL

async function fetchPinnacle() {
  const [matchups, mk] = await Promise.all([
    getBody(`${BASE}/matchups`, { timeout: 20000 }),
    getJSON(`${BASE}/markets/straight`, { timeout: 20000 }),
  ]);
  const markets = mk.body;
  // Pinnacle serves this through a CDN with a quarter-hour TTL, so the number in hand is anywhere from
  // seconds to minutes old. `age` says which. Before kickoff that hardly matters; in play it is the whole
  // story, so it travels with the price and the caller decides what is too old to use.
  const age = Number(mk.headers?.get?.('age')) || 0;
  const games = new Map(); // matchupId -> { start, home, away, live, full, h1, limit, age }
  for (const m of matchups || []) {
    if (m.type !== 'matchup' || m.special) continue;
    // A game in play is a CHILD matchup: parentId set, isLive, status 'started'. Pinnacle drops the
    // pre-game parent at the same moment, so these are the only way to see a live number. Every other
    // child is an alternate or a prop and is not this game's price.
    if (m.parentId && !m.isLive) continue;
    const home = m.participants?.find((p) => p.alignment === 'home')?.name;
    const away = m.participants?.find((p) => p.alignment === 'away')?.name;
    if (!home || !away) continue;
    games.set(m.id, { start: m.startTime, home, away, live: !!m.isLive, age, full: { s: null, so: [null, null], t: null, to: [null, null], ml: [null, null] }, h1: { s: null, so: [null, null], t: null, to: [null, null] }, limit: null });
  }
  for (const k of markets || []) {
    const g = games.get(k.matchupId);
    if (!g || k.isAlternate || (k.status && k.status !== 'open') || (k.period !== 0 && k.period !== 1)) continue;
    const L = k.period === 0 ? g.full : g.h1;
    const price = (d) => k.prices?.find((p) => p.designation === d);
    if (k.type === 'spread') {
      const h = price('home'), a = price('away');
      L.s = num(h?.points); L.so = [num(h?.price), num(a?.price)];
      if (k.period === 0) g.limit = num(k.limits?.find((x) => x.type === 'maxRiskStake')?.amount) ?? g.limit;
    } else if (k.type === 'total') {
      const o = price('over'), u = price('under');
      L.t = num(o?.points); L.to = [num(o?.price), num(u?.price)];
    } else if (k.type === 'moneyline' && k.period === 0) {
      L.ml = [num(price('home')?.price), num(price('away')?.price)];
      // Only if the spread never turned up: in play the spread is sometimes pulled while the moneyline
      // stays, and a limit from the wrong market is worse than none.
      if (g.limit == null) g.limit = num(k.limits?.find((x) => x.type === 'maxRiskStake')?.amount);
    }
  }
  return [...games.values()].filter((g) => g.full.s != null || g.full.t != null || g.full.ml[0] != null);
}

// Map Pinnacle games onto ESPN games by kickoff and team names.
function matchPinnacle(pgames, espnGames) {
  const out = new Map();
  for (const p of pgames) {
    const t0 = Date.parse(p.start);
    let best = null;
    for (const g of espnGames) {
      if (Math.abs(Date.parse(g.start) - t0) > 6 * 3600e3) continue;
      const a = Math.min(nameScore(p.away, g.away), nameScore(p.home, g.home));
      const b = Math.min(nameScore(p.away, g.home), nameScore(p.home, g.away));
      const s = Math.max(a, b);
      if (s >= 2 && (!best || s > best.s)) best = { s, g, swap: b > a };
    }
    if (!best) { log('pinnacle: no match for', p.away, '@', p.home); continue; }
    const flip = (L) => (best.swap ? { ...L, s: L.s == null ? null : -L.s, so: [L.so[1], L.so[0]], ml: L.ml ? [L.ml[1], L.ml[0]] : L.ml } : L);
    const prev = out.get(best.g.id) || {};
    if (p.live) {
      // In play. Kept beside the pre-game number, never on top of it: `line` is what the game closed at
      // and the board reads it as such. A first-half market on a live child is "rest of the half", which
      // is a different bet from the one a pre-game H1 line prices, so it is left out entirely.
      out.set(best.g.id, { ...prev, line: prev.line ?? null, h1: prev.h1 ?? null, live: true, liveLine: flip(p.full), liveLimit: p.limit, liveAge: p.age });
    } else {
      out.set(best.g.id, { ...prev, line: flip(p.full), h1: p.h1.s == null ? null : flip(p.h1), limit: p.limit, live: prev.live || false, age: p.age });
    }
  }
  return out;
}

module.exports = { fetchPinnacle, matchPinnacle };
