'use strict';
/* Pinnacle, the offshore book sharp bettors treat as "the market". Its public guest feed needs no key,
   but Pinnacle caches it for up to 15 minutes, so this polls gently and labels the age.
   Also carries Pinnacle's bet limits: a rising limit means the number is firming up toward kickoff. */

const { getBody, num, nameScore, log } = require('./util');

const BASE = 'https://guest.api.arcadia.pinnacle.com/0.1/leagues/889'; // 889 = NFL

async function fetchPinnacle() {
  const [matchups, markets] = await Promise.all([
    getBody(`${BASE}/matchups`, { timeout: 20000 }),
    getBody(`${BASE}/markets/straight`, { timeout: 20000 }),
  ]);
  const games = new Map(); // matchupId -> { start, home, away, live, full, h1, limit }
  for (const m of matchups || []) {
    if (m.parentId || m.type !== 'matchup' || m.special) continue;
    const home = m.participants?.find((p) => p.alignment === 'home')?.name;
    const away = m.participants?.find((p) => p.alignment === 'away')?.name;
    if (!home || !away) continue;
    games.set(m.id, { start: m.startTime, home, away, live: !!m.isLive, full: { s: null, so: [null, null], t: null, to: [null, null], ml: [null, null] }, h1: { s: null, so: [null, null], t: null, to: [null, null] }, limit: null });
  }
  for (const k of markets || []) {
    const g = games.get(k.matchupId);
    if (!g || k.isAlternate || (k.status && k.status !== 'open') || (k.period !== 0 && k.period !== 1)) continue;
    const L = k.period === 0 ? g.full : g.h1;
    const price = (d) => k.prices?.find((p) => p.designation === d);
    if (k.type === 'spread') {
      const h = price('home'), a = price('away');
      L.s = num(h?.points); L.so = [num(h?.price), num(a?.price)];
      if (k.period === 0) g.limit = num(k.limits?.find((x) => x.type === 'maxRiskStake')?.amount);
    } else if (k.type === 'total') {
      const o = price('over'), u = price('under');
      L.t = num(o?.points); L.to = [num(o?.price), num(u?.price)];
    } else if (k.type === 'moneyline' && k.period === 0) {
      L.ml = [num(price('home')?.price), num(price('away')?.price)];
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
    out.set(best.g.id, { line: p.live ? null : flip(p.full), h1: p.live || p.h1.s == null ? null : flip(p.h1), limit: p.limit, live: p.live });
  }
  return out;
}

module.exports = { fetchPinnacle, matchPinnacle };
