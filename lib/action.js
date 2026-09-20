'use strict';
/* Action Network's public web feeds: lines from many books (pregame and live), the consensus market,
   public betting splits (tickets vs money), team totals, Vegas rotation numbers and live cover odds.
   The public-betting feed adds Station Casinos and first-half lines. Everything is mapped onto ESPN games. */

const { getBody, num, norm } = require('./util');
const { BOOKS, CONSENSUS, OPENER, AN_IDS } = require('./books');

const AN = 'https://api.actionnetwork.com/web';
const ALL = [CONSENSUS, OPENER, ...BOOKS];
const A1_IDS = [...new Set([15, 30, 68, 69, 75, ...BOOKS.flatMap((b) => b.an1 || [])])];

const v2Url = ({ season, week }) => `${AN}/v2/scoreboard/nfl?bookIds=${AN_IDS.join(',')}&week=${week}&season=${season}&periods=event`;
const v1Url = ({ season, week }) => `${AN}/v1/scoreboard/publicbetting/nfl?bookIds=${A1_IDS.join(',')}&week=${week}&season=${season}`;

// ---------------------------------------------------------------- matching to ESPN
function teamScore(t, e) {
  if (!t || !e) return 0;
  const full = norm(t.full_name), loc = norm(t.location), disp = norm(t.display_name);
  if (full && full === e.key) return 4;
  if (loc && loc === e.locKey) return 3;
  if (disp && (disp === norm(e.short) || disp === e.locKey)) return 3;
  if (full && e.key && (full.startsWith(e.locKey) || e.key.startsWith(loc)) && Math.min(loc.length, e.locKey.length) >= 5) return 2;
  if (t.abbr && e.abbr && t.abbr.toUpperCase() === e.abbr.toUpperCase()) return 1;
  return 0;
}

// Returns { id: espnGameId, side: { [anTeamId]: 'home'|'away' } } or null.
function matchGame(ag, espnGames, cache) {
  if (cache.has(ag.id)) return cache.get(ag.id);
  const th = ag.teams?.find((t) => t.id === ag.home_team_id);
  const ta = ag.teams?.find((t) => t.id === ag.away_team_id);
  const t0 = Date.parse(ag.start_time);
  let best = null;
  for (const g of espnGames) {
    if (Math.abs(Date.parse(g.start) - t0) > 8 * 3600e3) continue;
    const straight = Math.min(teamScore(th, g.home), teamScore(ta, g.away));
    const swapped = Math.min(teamScore(th, g.away), teamScore(ta, g.home));
    const s = Math.max(straight, swapped);
    if (s >= 1 && (!best || s > best.s)) best = { s, g, swap: swapped > straight };
  }
  if (!best) return null;
  const m = {
    id: best.g.id,
    side: { [ag.home_team_id]: best.swap ? 'away' : 'home', [ag.away_team_id]: best.swap ? 'home' : 'away' },
    swap: best.swap,
  };
  cache.set(ag.id, m);
  return m;
}

// ---------------------------------------------------------------- v2: many books, live lines, splits
function emptyLine() { return { s: null, so: [null, null], t: null, to: [null, null], ml: [null, null] }; }

function readMarkets(ev, side, live) {
  const L = emptyLine();
  const pick = (list) => (list || []).filter((o) => !!o.is_live === live);
  for (const o of pick(ev.spread)) {
    const sd = side[o.team_id];
    if (!sd) continue;
    if (sd === 'home') { L.s = num(o.value); L.so[0] = num(o.odds); } else { L.so[1] = num(o.odds); if (L.s == null) L.s = num(o.value) == null ? null : -num(o.value); }
  }
  for (const o of pick(ev.total)) {
    if (o.side === 'over') { L.t = num(o.value); L.to[0] = num(o.odds); }
    if (o.side === 'under') { L.to[1] = num(o.odds); if (L.t == null) L.t = num(o.value); }
  }
  for (const o of pick(ev.moneyline)) {
    const sd = side[o.team_id];
    if (sd) L.ml[sd === 'home' ? 0 : 1] = num(o.odds);
  }
  const has = L.s != null || L.t != null || L.ml[0] != null;
  return has ? L : null;
}

function splitsOf(ev, side) {
  const pct = (o, k) => (o?.bet_info?.[k]?.percent == null ? null : num(o.bet_info[k].percent));
  const pre = (list) => (list || []).filter((o) => !o.is_live);
  const sp = pre(ev.spread).find((o) => side[o.team_id] === 'home');
  const ov = pre(ev.total).find((o) => o.side === 'over');
  const ml = pre(ev.moneyline).find((o) => side[o.team_id] === 'home');
  const out = {
    s: sp ? { tix: pct(sp, 'tickets'), money: pct(sp, 'money') } : null,
    t: ov ? { tix: pct(ov, 'tickets'), money: pct(ov, 'money') } : null,
    ml: ml ? { tix: pct(ml, 'tickets'), money: pct(ml, 'money') } : null,
  };
  // A feed with no action yet reports 0/0 on both sides; treat that as unknown.
  for (const k of Object.keys(out)) if (out[k] && !out[k].tix && !out[k].money) out[k] = null;
  return out;
}

function teamTotals(ev, side) {
  const out = {};
  for (const o of (ev.core_bet_type_6_team_score || []).filter((x) => !x.is_live)) {
    const sd = side[o.team_id];
    if (!sd) continue;
    const r = (out[sd] ||= { pts: null, over: null, under: null });
    r.pts = num(o.value);
    r[o.side] = num(o.odds);
  }
  return Object.keys(out).length ? out : null;
}

function parseV2(j, espnGames, cache) {
  const out = new Map(); // espnId -> patch
  for (const ag of j.games || []) {
    const m = matchGame(ag, espnGames, cache);
    if (!m) continue;
    const books = {}, live = {};
    for (const b of ALL) {
      for (const id of b.an || []) {
        const ev = ag.markets?.[id]?.event;
        if (!ev) continue;
        if (!books[b.key]) { const L = readMarkets(ev, m.side, false); if (L) books[b.key] = L; }
        if (!live[b.key]) { const L = readMarkets(ev, m.side, true); if (L) live[b.key] = L; }
      }
    }
    const consEv = ag.markets?.[CONSENSUS.an[0]]?.event || Object.values(ag.markets || {})[0]?.event || {};
    const lp = ag.last_play || {};
    const flip = (p) => (p == null ? null : m.swap ? 1 - p : p);
    out.set(m.id, {
      an: ag.id,
      rot: { home: m.swap ? num(ag.away_rotation_number) : num(ag.home_rotation_number), away: m.swap ? num(ag.home_rotation_number) : num(ag.away_rotation_number) },
      books,
      live,
      splits: splitsOf(consEv, m.side),
      tt: teamTotals(consEv, m.side),
      bets: num(ag.num_bets),
      prob: lp.home_win_pct != null ? { home: flip(num(lp.home_win_pct)), over: num(lp.over_win_pct), cover: flip(num(lp.home_spread_win_pct)) } : null,
    });
  }
  return out;
}

// ---------------------------------------------------------------- v1: Station Casinos + first-half lines
function parseV1(j, espnGames, cache) {
  const keyOf = Object.fromEntries(BOOKS.flatMap((b) => (b.an1 || []).map((id) => [id, b.key])));
  const h1Key = { 15: 'cons', 18: 'stn', 68: 'dk', 69: 'fd', 75: 'mgm' };
  const out = new Map();
  for (const ag of j.games || []) {
    const m = matchGame(ag, espnGames, cache);
    if (!m) continue;
    const books = {}, h1 = {};
    for (const o of ag.odds || []) {
      const homeIsHome = !m.swap;
      const L = {
        s: num(homeIsHome ? o.spread_home : o.spread_away),
        so: homeIsHome ? [num(o.spread_home_line), num(o.spread_away_line)] : [num(o.spread_away_line), num(o.spread_home_line)],
        t: num(o.total),
        to: [num(o.over), num(o.under)],
        ml: homeIsHome ? [num(o.ml_home), num(o.ml_away)] : [num(o.ml_away), num(o.ml_home)],
        at: Date.parse(o.inserted || 0) || null,
      };
      if (L.s == null && L.t == null && L.ml[0] == null) continue;
      if (o.type === 'game' && keyOf[o.book_id]) books[keyOf[o.book_id]] = L;
      if (o.type === 'firsthalf' && h1Key[o.book_id]) h1[h1Key[o.book_id]] = { s: L.s, so: L.so, t: L.t, to: L.to };
    }
    out.set(m.id, { books, h1 });
  }
  return out;
}

async function fetchV2(week) { return getBody(v2Url(week), { timeout: 20000, headers: { 'cache-control': 'no-cache' } }); }
async function fetchV1(week) { return getBody(v1Url(week), { timeout: 20000, headers: { 'cache-control': 'no-cache' } }); }

module.exports = { fetchV2, fetchV1, parseV2, parseV1 };
