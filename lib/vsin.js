'use strict';
/* VSiN's Vegas line tracker: the only free place that shows the Las Vegas windows side by side —
   Circa, Boomer's, Station, South Point, Westgate, Wynn, Caesars and BetMGM — with each book's opener
   and first-half lines. It's an HTML page, not an API, so this reads the table. It covers today's games,
   updates every few minutes, and is only re-read when its "Odds updated" stamp changes. */

const { getText, num, norm, log, nameScore } = require('./util');
const { BOOKS } = require('./books');

const URL_ = 'https://data.vsin.com/vegas-odds-linetracker/?sportid=nfl';
const keyOf = Object.fromEntries(BOOKS.filter((b) => b.vsin).map((b) => [norm(b.vsin), b.key]));

const text = (s) => String(s || '').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/\s+/g, ' ').trim();
const cells = (row) => [...row.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1]);
const pair = (html) => {
  const n = /sp-s-num">([^<]*)</.exec(html)?.[1];
  const j = /sp-s-juice">(?:<span[^>]*>[ou]<\/span>)?([^<]*)</.exec(html)?.[1];
  return [num(String(n || '').replace('PK', '0').replace('pk', '0')), num(j)];
};
const plain = (html) => num(text(html).replace(/^PK$/i, '0').replace(/^EV(EN)?$/i, '100'));

function parse(html) {
  const stamp = /Odds updated:\s*([^<]+)</.exec(html)?.[1]?.trim() || null;
  const head = /<thead>([\s\S]*?)<\/thead>/.exec(html)?.[1] || '';
  const books = [...head.matchAll(/class="sp-book-group"[^>]*>([\s\S]*?)<\/th>/g)].map((m) => keyOf[norm(text(m[1]))] || null);
  const out = new Map(); // "YYYY-MM-DD|road|home" -> game
  for (const [, cls, body] of html.matchAll(/<tbody class="(sp-tbody-(?:fg|1h))">([\s\S]*?)<\/tbody>/g)) {
    const half = cls.endsWith('1h');
    const rows = [...body.matchAll(/<tr([^>]*)>([\s\S]*?)<\/tr>/g)].map((m) => ({ open: /sp-row-open/.test(m[1]), td: cells(m[2]) }));
    for (let i = 0; i + 2 < rows.length; i++) {
      if (!rows[i].open || rows[i + 1].open || rows[i + 2].open) continue;
      const [o, r, h] = [rows[i], rows[i + 1], rows[i + 2]];
      const id = /openGameDetail\('(\d{8})NFL(\d+)'\)/.exec(o.td[0] || '');
      const road = text(r.td[0]), home = text(h.td[0]);
      if (!road || !home) continue;
      const date = id ? `${id[1].slice(0, 4)}-${id[1].slice(4, 6)}-${id[1].slice(6, 8)}` : null;
      const k = `${date}|${norm(road)}|${norm(home)}`;
      const G = out.get(k) || { date, road, home, rot: id ? num(id[2]) : null, books: {}, open: {}, h1: {} };
      books.forEach((book, b) => {
        if (!book) return;
        const c = 1 + b * 3;
        const [rs, rj] = pair(r.td[c]), [hs, hj] = pair(h.td[c]);
        const rml = plain(r.td[c + 1]), hml = plain(h.td[c + 1]);
        const [tot, oj] = pair(r.td[c + 2]), [, uj] = pair(h.td[c + 2]);
        const L = {
          s: hs ?? (rs == null ? null : -rs), so: [hj, rj],
          t: tot, to: [oj, uj],
          ml: [hml, rml],
        };
        if (L.s == null && L.t == null && L.ml[0] == null) return;
        if (half) G.h1[book] = { s: L.s, so: L.so, t: L.t, to: L.to };
        else {
          G.books[book] = L;
          const os = pair(o.td[c])[0], oml = plain(o.td[c + 1]), ot = plain(o.td[c + 2]);
          if (os != null || ot != null) G.open[book] = { s: os == null ? null : -os, t: ot, ml: oml == null ? null : [null, oml] };
        }
      });
      out.set(k, G);
    }
  }
  return { stamp, games: [...out.values()] };
}

let last = { stamp: null, games: [], at: 0 };
async function fetchVsin() {
  const html = await getText(URL_, { timeout: 25000, headers: { accept: 'text/html' } });
  const stamp = /Odds updated:\s*([^<]+)</.exec(html)?.[1]?.trim() || null;
  if (stamp && stamp === last.stamp) return { ...last, same: true };
  const p = parse(html);
  if (!p.games.length) throw new Error('VSiN table not found (the page layout may have changed)');
  last = { ...p, at: Date.now() };
  return last;
}

// "9/19/2026 12:40 PM ET" -> epoch ms (Eastern, DST-aware enough for a freshness label)
function stampTime(s) {
  const m = /(\d+)\/(\d+)\/(\d{4})\s+(\d+):(\d+)\s*(AM|PM)/i.exec(s || '');
  if (!m) return null;
  let hh = Number(m[4]) % 12;
  if (/pm/i.test(m[6])) hh += 12;
  const guess = Date.UTC(Number(m[3]), Number(m[1]) - 1, Number(m[2]), hh + 4, Number(m[5]));
  // Eastern is UTC-4 in summer and UTC-5 in winter.
  const off = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'short' }).format(new Date(guess)).includes('EST') ? 1 : 0;
  return guess + off * 3600e3;
}

// Map VSiN games onto ESPN games by date and team names.
function matchAll(vgames, espnGames, teamScore = nameScore) {
  const out = new Map();
  for (const v of vgames) {
    let best = null;
    for (const g of espnGames) {
      if (v.date && g.day !== v.date) continue;
      const a = Math.min(teamScore(v.road, g.away), teamScore(v.home, g.home));
      const b = Math.min(teamScore(v.road, g.home), teamScore(v.home, g.away));
      const s = Math.max(a, b);
      if (s >= 2 && (!best || s > best.s)) best = { s, g, swap: b > a };
    }
    if (!best) { log('vsin: no match for', v.road, '@', v.home); continue; }
    const flip = (L) => (L && best.swap ? { ...L, s: L.s == null ? null : -L.s, so: L.so ? [L.so[1], L.so[0]] : L.so, ml: L.ml ? [L.ml[1], L.ml[0]] : L.ml } : L);
    const map = (o) => Object.fromEntries(Object.entries(o).map(([k, L]) => [k, flip(L)]));
    out.set(best.g.id, { books: map(v.books), open: map(v.open), h1: map(v.h1) });
  }
  return out;
}

module.exports = { fetchVsin, matchAll, stampTime, parse };
