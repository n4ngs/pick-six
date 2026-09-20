'use strict';
/* Pick Six — core: state, formatting, betting math, football helpers, small SVG pieces.
   Classic scripts share these top-level names (same pattern as Bing Bong Live). */

// ------------------------------------------------------------ utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const store = {
  get(k, d) { try { const v = localStorage.getItem(`ps.${k}`); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`ps.${k}`, JSON.stringify(v)); } catch { /* private mode */ } },
};
const MINUS = '−';
const trim = (n) => (Number.isInteger(n) ? String(n) : (Math.round(n * 10) / 10).toFixed(1));
const fmtPts = (v) => (v == null ? '—' : v === 0 ? 'PK' : `${v > 0 ? '+' : MINUS}${trim(Math.abs(v))}`);
const fmtTot = (v) => (v == null ? '—' : trim(v));
const fmtOdds = (o) => (o == null ? '' : o === 100 ? 'EV' : o > 0 ? `+${o}` : `${MINUS}${Math.abs(o)}`);
const fmtPct = (p, d = 0) => (p == null ? '—' : `${(p * 100).toFixed(d)}%`);
const fmtMoney = (n, sign = false) => {
  if (n == null || Number.isNaN(n)) return '—';
  const a = Math.abs(n);
  const s = a >= 1000 ? `$${Math.round(a).toLocaleString()}` : `$${a % 1 ? a.toFixed(2) : a}`;
  return n < 0 ? `${MINUS}${s}` : sign && n > 0 ? `+${s}` : s;
};
const plural = (n, w, p = `${w}s`) => `${n} ${n === 1 ? w : p}`;

// ------------------------------------------------------------ icons
const ICON = {
  chev: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.5L8 6l-3.5 3.5"/></svg>',
  back: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.5 2.5L4 6l3.5 3.5"/></svg>',
  bell: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2a3.8 3.8 0 0 0-3.8 3.8v2.4L3 10.8h10l-1.2-2.4V6A3.8 3.8 0 0 0 8 2.2z"/><path d="M6.5 12.8a1.6 1.6 0 0 0 3 0"/></svg>',
  bellOn: '<svg viewBox="0 0 16 16" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.2a3.8 3.8 0 0 0-3.8 3.8v2.4L3 10.8h10l-1.2-2.4V6A3.8 3.8 0 0 0 8 2.2z"/><path d="M6.5 12.8a1.6 1.6 0 0 0 3 0" fill="none"/></svg>',
  auto: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor"/></svg>',
  sun: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1"/></svg>',
  moon: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M13.4 10.2A5.8 5.8 0 0 1 5.8 2.6a5.8 5.8 0 1 0 7.6 7.6z"/></svg>',
  star: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><path d="M8 1.9l1.8 3.7 4 .6-2.9 2.8.7 4-3.6-1.9-3.6 1.9.7-4L2.2 6.2l4-.6z"/></svg>',
  starOn: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 1.9l1.8 3.7 4 .6-2.9 2.8.7 4-3.6-1.9-3.6 1.9.7-4L2.2 6.2l4-.6z"/></svg>',
  plus: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M8 3v10M3 8h10"/></svg>',
  wind: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M2 6h8.5a2 2 0 1 0-2-2M2 10h10.5a2 2 0 1 1-2 2"/></svg>',
  share: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 10V2.5M5 5.2L8 2.3l3 2.9M4 8H3.5v5.5h9V8H12"/></svg>',
  play: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4.5 2.8v10.4c0 .6.7 1 1.2.7l8.3-5.2c.5-.3.5-1.1 0-1.4L5.7 2.1c-.5-.3-1.2.1-1.2.7z"/></svg>',
  up: '<svg viewBox="0 0 10 10" fill="currentColor" aria-hidden="true"><path d="M5 2l3.5 5h-7z"/></svg>',
  down: '<svg viewBox="0 0 10 10" fill="currentColor" aria-hidden="true"><path d="M5 8L1.5 3h7z"/></svg>',
};

// ------------------------------------------------------------ state
const S = {
  offset: 0, connected: false, lastMsg: Date.now(), liveMs: 8000,
  season: null, cal: [], def: null, cur: null, tracked: [],
  weeks: new Map(),       // week id -> { meta, games: Map }
  boardWeek: null,        // week id the board is showing
  books: [],              // [{ key, name, short, vegas, sharp, site, ios, feed }]
  mine: {},               // gid -> book -> number you typed in at a window: yours, on this device only
  bets: [],
  me: { role: 'owner', name: '', named: true, owner: '', shared: false },  // who you are on this board (server sets it)
  moves: [],              // recent line moves across tracked weeks, newest first
  keys: null,             // last season's margin/total distribution
  tab: 'live',
  mkt: store.get('mkt', 's'),
  phBook: store.get('phBook', 'mkt'),  // which book the narrow board shows beside Best ('mkt' = market consensus)
  filter: store.get('filter', 'all'),
  query: '',
  bseg: store.get('bseg', 'open'),
  hidden: new Set(store.get('hiddenBooks', [])),
  follow: new Set(store.get('follow', [])),
  alerts: store.get('alerts', 'off'), // off | mine | all
  theme: store.get('theme', 'auto'),
  unit: store.get('unit', 100),
  parlay: (() => { const p = store.get('parlay', null); return p && Array.isArray(p.legs) && Date.now() - (p.at || 0) < 24 * 3600e3 ? p.legs.slice(0, 12) : []; })(), // legs waiting in the tray, kept across restarts for a day
  ticks: new Map(),       // "gid|book|mkt" -> last value, for flashing changed prices
  flashed: new Map(),     // flash key -> time the price changed (live.js flashAttr)
  sheet: null,            // { kind, gid, ... }
  game: null,             // detail payload for the open game sheet
};
const serverNow = () => Date.now() + S.offset;
const defWeek = () => S.weeks.get(S.def);
const boardWeek = () => S.weeks.get(S.boardWeek) || defWeek();
function gameById(id) {
  for (const w of S.weeks.values()) { const g = w.games.get(id); if (g) return g; }
  return null;
}
const bookName = (k) => ({ cons: 'Market', open: 'Open' }[k] || S.books.find((b) => b.key === k)?.short || k);
const bookFull = (k) => ({ cons: 'Market consensus', open: 'Opening line' }[k] || S.books.find((b) => b.key === k)?.name || k);
const visibleBooks = () => S.books.filter((b) => !S.hidden.has(b.key));
// Where to go to place the bet: the book's own page and its Nevada app. You sign in there; this app never
// asks for a sportsbook login, never holds one, and never places a bet for you.
const bookOf = (k) => S.books.find((b) => b.key === k) || null;
const bookSite = (k) => bookOf(k)?.site || null;
const bookApp = (k) => bookOf(k)?.ios || null;
const canBetAt = (k) => !!(bookSite(k) || bookApp(k));

// ------------------------------------------------------------ odds math
const dec = (o) => (o == null ? null : o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o));
const imp = (o) => (o == null ? null : o > 0 ? 100 / (o + 100) : Math.abs(o) / (Math.abs(o) + 100));
const toAm = (d) => (d == null || d <= 1 ? null : d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1)));
const probToAm = (p) => (p <= 0 || p >= 1 ? null : p >= 0.5 ? Math.round((-100 * p) / (1 - p)) : Math.round((100 * (1 - p)) / p));
function noVig(a, b) {
  const pa = imp(a), pb = imp(b);
  if (pa == null || pb == null) return null;
  return { a: pa / (pa + pb), b: pb / (pa + pb), hold: pa + pb - 1 };
}
const toWin = (stake, o) => (stake && o != null ? stake * (dec(o) - 1) : null);
// Standard normal CDF and its inverse (Acklam), for turning win chances into point spreads.
function ncdf(x) {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp((-x * x) / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}
function ninv(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const pl = 0.02425;
  if (p < pl) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
  if (p > 1 - pl) return -ninv(1 - p);
  const q = p - 0.5, r = q * q;
  return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}
const SIGMA = 13.5; // spread of NFL final margins around the market, in points (approximate)
const spreadFromWin = (pHome) => (pHome == null ? null : Math.round(-SIGMA * ninv(clamp(pHome, 0.005, 0.995)) * 10) / 10);

// ------------------------------------------------------------ lines
// A line from one side's point of view: { line, odds } for spread / total / moneyline.
function sideOf(L, mkt, side) {
  if (!L) return null;
  if (mkt === 's' || mkt === 'h1s') { if (L.s == null) return null; return side === 'home' ? { line: L.s, odds: L.so?.[0] } : { line: -L.s, odds: L.so?.[1] }; }
  if (mkt === 't' || mkt === 'h1t') { if (L.t == null) return null; return { line: L.t, odds: side === 'over' ? L.to?.[0] : L.to?.[1] }; }
  if (mkt === 'ml') { const o = side === 'home' ? L.ml?.[0] : L.ml?.[1]; return o == null ? null : { line: null, odds: o }; }
  return null;
}
// Which of two prices is better for the bettor on that side.
function better(mkt, side, a, b) {
  if (!b) return true;
  if (!a) return false;
  if (mkt === 'ml') return a.odds > b.odds;
  const la = a.line, lb = b.line;
  const gain = mkt === 's' || mkt === 'h1s' ? la - lb : side === 'over' ? lb - la : la - lb;
  if (gain !== 0) return gain > 0;
  return (a.odds ?? -110) > (b.odds ?? -110);
}
function bestOf(books, mkt, side) {
  let best = null;
  for (const b of visibleBooks()) {
    const L = books?.[b.key];
    const p = sideOf(L, mkt, side);
    if (!p || p.odds == null) continue;
    if (!best || better(mkt, side, p, best)) best = { ...p, book: b.key };
  }
  return best;
}
const halfBooks = (g) => g.h1 || {};

// ------------------------------------------------------------ games
const isLive = (g) => g?.state === 'in';
const isFinal = (g) => g?.state === 'post';
const isPre = (g) => g?.state === 'pre';
const timeLabel = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).replace(/\s/g, '\u00a0') : '');
// Vegas rotation numbers are three or four digits; anything else in the feed is an internal id.
const rotOf = (g, side) => { const v = g.rot?.[side]; return v > 0 && v < 10000 ? v : null; };
const STALE_MS = 15 * 60e3;
const isOld = (L) => !!(L?.seen && serverNow() - L.seen > STALE_MS);
const dayLabel = (iso, long = false) => (iso ? new Date(iso).toLocaleDateString([], long ? { weekday: 'long', month: 'short', day: 'numeric' } : { weekday: 'short' }) : '');
const localDay = (iso) => new Date(iso).toLocaleDateString('en-CA');
const etHour = (iso) => { const p = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(new Date(iso)); return Number(p.find((x) => x.type === 'hour').value) + Number(p.find((x) => x.type === 'minute').value) / 60; };
const etDay = (iso) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date(iso));
// The betting day: Eastern date, held until 5 AM so a late West Coast kickoff still counts as its own day.
const todayET = () => etDay(new Date(serverNow() - 5 * 3600e3).toISOString());
// The NFL's week is a handful of named windows, in Eastern time.
function windowOf(g) {
  const h = etHour(g.start);
  const day = new Date(g.start).toLocaleDateString('en-US', { timeZone: 'America/New_York', weekday: 'long' });
  if (g.tbd) return 'Time TBA';
  if (day === 'Thursday') return 'Thursday night';
  if (day === 'Friday') return 'Friday';
  if (day === 'Saturday') return h < 17 ? 'Saturday' : 'Saturday night';
  if (day === 'Monday') return 'Monday night';
  if (day === 'Tuesday' || day === 'Wednesday') return day;
  if (h < 12) return 'London';          // the early kickoffs from abroad
  if (h < 15.5) return 'Sunday early';
  if (h < 19) return 'Sunday late';
  return 'Sunday night';
}
const quarter = (n) => (n <= 4 ? ['1st', '2nd', '3rd', '4th'][n - 1] : n === 5 ? 'OT' : `${n - 4}OT`);
function clockLabel(g) {
  if (isFinal(g)) return g.period > 4 ? `Final/${g.period === 5 ? 'OT' : `${g.period - 4}OT`}` : 'Final';
  if (g.state === 'off') return g.detail || 'Postponed';
  if (isPre(g)) return g.tbd ? 'TBA' : timeLabel(g.start);
  if (g.half) return 'Halftime';
  if (!g.period) return 'Starting';
  return `${quarter(g.period)} ${g.clock || ''}`.trim();
}
const teamName = (t) => t.short || t.loc || t.abbr;
const rankTag = (t) => (t.rank ? `<span class="rk">${t.rank}</span>` : '');
const logo = (t, cls = 'logo') => `<img class="${cls}" src="${esc(t.logo)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`;
// How much of the game is left, 0..1.
function remaining(g) {
  if (isPre(g)) return 1;
  if (isFinal(g)) return 0;
  if (g.half) return 0.5;
  if (g.period > 4) return 0.04;
  const secs = g.secs ?? 900;
  return clamp(((4 - g.period) * 900 + secs) / 3600, 0, 1);
}
const margin = (g, side) => (side === 'home' ? (g.home.score ?? 0) - (g.away.score ?? 0) : (g.away.score ?? 0) - (g.home.score ?? 0));
const favSide = (g) => (g.mkt?.s == null ? null : g.mkt.s < 0 ? 'home' : g.mkt.s > 0 ? 'away' : null);
const closeOf = (g) => g.close || g.mkt; // before kickoff, the current number is the "close so far"
function lineFor(g, side, L = closeOf(g)) { return L?.s == null ? null : side === 'home' ? L.s : -L.s; }

// Where a bet at `line` stands right now: coverBy > 0 is winning.
function legNow(g, leg) {
  if (!g) return null;
  const h = leg.mkt?.startsWith('h1') ? (g.home.q?.[0] ?? 0) + (g.home.q?.[1] ?? 0) : g.home.score ?? 0;
  const a = leg.mkt?.startsWith('h1') ? (g.away.q?.[0] ?? 0) + (g.away.q?.[1] ?? 0) : g.away.score ?? 0;
  if (leg.mkt === 's' || leg.mkt === 'h1s') return (leg.side === 'home' ? h - a : a - h) + leg.line;
  if (leg.mkt === 'ml') return leg.side === 'home' ? h - a : a - h;
  if (leg.mkt === 't' || leg.mkt === 'h1t') return leg.side === 'over' ? h + a - leg.line : leg.line - (h + a);
  if (leg.mkt === 'tt') { const s = leg.team === 'home' ? g.home.score ?? 0 : g.away.score ?? 0; return leg.side === 'over' ? s - leg.line : leg.line - s; }
  return null;
}

// Estimated chance a spread or total bet cashes from here. The live market line is the best guess of the
// final margin/total; the uncertainty shrinks with the time left. It's an estimate and labeled that way.
function coverChance(g, leg) {
  if (!g || isPre(g) || isFinal(g)) return null;
  const left = remaining(g);
  const live = g.live?.cons || g.live?.dk;
  const h = g.home.score ?? 0, a = g.away.score ?? 0;
  if (leg.mkt === 's' || leg.mkt === 'ml') {
    // expected final home margin
    let mu = live?.s != null ? -live.s : (h - a) + (-(closeOf(g)?.s ?? 0)) * left;
    const sd = Math.max(0.6, SIGMA * Math.sqrt(left));
    const need = leg.mkt === 'ml' ? 0 : -(leg.side === 'home' ? leg.line : -leg.line); // home margin must beat this
    let p = 1 - ncdf((need - mu) / sd);
    if (leg.side === 'away') p = 1 - p;
    return clamp(p, 0.005, 0.995);
  }
  if (leg.mkt === 't') {
    const mu = live?.t != null ? live.t : h + a + (closeOf(g)?.t ?? h + a) * left;
    const sd = Math.max(0.6, 13 * Math.sqrt(left));
    const p = 1 - ncdf((leg.line - mu) / sd);
    return clamp(leg.side === 'over' ? p : 1 - p, 0.005, 0.995);
  }
  return null;
}

// ------------------------------------------------------------ plain English
function spreadWords(team, line) {
  if (line == null) return '';
  const n = teamName(team);
  if (line === 0) return `Pick'em: ${n} just has to win.`;
  if (line < 0) {
    const m = Math.abs(line);
    return Number.isInteger(m) ? `${n} has to win by ${m + 1} or more. Winning by exactly ${m} is a push.` : `${n} has to win by ${Math.ceil(m)} or more.`;
  }
  return Number.isInteger(line) ? `${n} covers by winning or losing by ${line - 1} or fewer. Losing by exactly ${line} is a push.` : `${n} covers by winning, or by losing by ${Math.floor(line)} or fewer.`;
}
const totalWords = (t) => (t == null ? '' : Number.isInteger(t) ? `The over needs ${t + 1}+ combined points; exactly ${t} is a push.` : `The over needs ${Math.ceil(t)}+ combined points; the under needs ${Math.floor(t)} or fewer.`);
function oddsWords(o) {
  if (o == null) return '';
  return o < 0 ? `Risk ${fmtMoney(Math.abs(o))} to win $100 (${fmtPct(imp(o))} implied).` : `$100 wins ${fmtMoney(o)} (${fmtPct(imp(o))} implied).`;
}

// What the betting splits and movement say. Signals, not advice.
function signals(g) {
  const out = [];
  const sp = g.splits?.s, o = g.open, m = g.mkt;
  if (sp && sp.tix != null && o?.s != null && m?.s != null) {
    const moved = m.s - o.s; // negative = toward home
    const homeTix = sp.tix, homeMoney = sp.money;
    const pub = homeTix >= 60 ? 'home' : homeTix <= 40 ? 'away' : null;
    if (pub && Math.abs(moved) >= 1 && ((pub === 'home' && moved > 0) || (pub === 'away' && moved < 0))) {
      const other = pub === 'home' ? g.away : g.home;
      out.push({ kind: 'rlm', side: pub === 'home' ? 'away' : 'home', text: `<b>Reverse line move toward ${esc(teamName(other))}.</b> ${pub === 'home' ? homeTix : 100 - homeTix}% of tickets are on ${esc(teamName(pub === 'home' ? g.home : g.away))}, yet the line moved ${trim(Math.abs(moved))} the other way. That usually means bigger, sharper bets.` });
    }
    if (homeMoney != null) {
      const gap = homeMoney - homeTix;
      if (Math.abs(gap) >= 12) {
        const t = gap > 0 ? g.home : g.away;
        out.push({ kind: 'money', side: gap > 0 ? 'home' : 'away', text: `<b>Bigger bets on ${esc(teamName(t))}.</b> ${gap > 0 ? homeTix : 100 - homeTix}% of tickets but ${gap > 0 ? homeMoney : 100 - homeMoney}% of the money.` });
      }
    }
  }
  const st = g.splits?.t;
  if (st && st.tix != null && o?.t != null && m?.t != null) {
    const moved = m.t - o.t;
    if (st.tix >= 60 && moved <= -1.5) out.push({ kind: 'rlm', side: 'under', text: `<b>Total dropping against the public.</b> ${st.tix}% of tickets on the over, but it's down ${trim(-moved)} since it opened.` });
    if (st.tix <= 40 && moved >= 1.5) out.push({ kind: 'rlm', side: 'over', text: `<b>Total rising against the public.</b> ${100 - st.tix}% of tickets on the under, but it's up ${trim(moved)} since it opened.` });
  }
  return out;
}

// ------------------------------------------------------------ small SVGs
// The field, left end zone is the home team's. yl = yards from the home goal line (ESPN's convention).
function fieldSVG(g, big = false) {
  const s = g.sit || {};
  const X = (yl) => 10 + clamp(yl, 0, 100);
  const H = big ? 22 : 16;
  const lines = [20, 30, 40, 50, 60, 70, 80, 90, 100].map((x) => `<line class="${x === 60 ? 'mid' : 'yd'}" x1="${x}" x2="${x}" y1="1" y2="${H - 1}"/>`).join('');
  const nums = big ? [10, 20, 30, 40, 50, 40, 30, 20, 10].map((n, i) => `<text x="${20 + i * 10}" y="${H - 3}">${n}</text>`).join('') : '';
  let marks = '';
  if (s.yl != null && g.poss) {
    const dir = g.poss === 'home' ? 1 : -1;
    const bx = X(s.yl);
    marks += `<line class="los" x1="${bx}" x2="${bx}" y1="1" y2="${H - 1}"/>`;
    if (s.dist > 0) {
      const toGoal = g.poss === 'home' ? 100 - s.yl : s.yl;
      const fd = s.dist >= toGoal ? (g.poss === 'home' ? 110 : 10) : bx + dir * s.dist;
      marks += `<line class="fd" x1="${fd}" x2="${fd}" y1="1" y2="${H - 1}"/>`;
    }
    const cy = H / 2;
    marks += `<path class="ball" d="M${bx - dir * 2.2},${cy - 1.6} L${bx + dir * 1.6},${cy} L${bx - dir * 2.2},${cy + 1.6} z"/>`;
  }
  const ez = (t, x) => `<rect class="ez" x="${x}" y="0" width="10" height="${H}" rx="${x ? 0 : 1.5}" fill="${esc(t.color || 'var(--ink)')}"/><text class="ezl" x="${x + 5}" y="${H / 2}">${esc(t.abbr)}</text>`;
  return `<svg class="fieldv${s.rz ? ' rz' : ''}" viewBox="0 0 120 ${H}" role="img" aria-label="${esc(s.text || 'Field')}">
    <rect class="turf" x="0" y="0" width="120" height="${H}" rx="1.5"/>${ez(g.home, 0)}${ez(g.away, 110)}${lines}${nums}${marks}</svg>`;
}

function sparkSVG(pts, w = 64, h = 22) {
  if (!pts || pts.length < 2) return '';
  const vs = pts.map((p) => p[1]);
  const lo = Math.min(...vs), hi = Math.max(...vs);
  const span = hi - lo || 1;
  const X = (i) => (2 + (i * (w - 4)) / (pts.length - 1)).toFixed(1);
  const Y = (v) => (hi === lo ? h / 2 : 2 + ((hi - v) / span) * (h - 4)).toFixed(1);
  const d = pts.map((p, i) => `${X(i)},${Y(p[1])}`).join(' ');
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${d}"/><circle class="o" cx="${X(0)}" cy="${Y(pts[0][1])}" r="2"/><circle cx="${X(pts.length - 1)}" cy="${Y(pts.at(-1)[1])}" r="2.5"/></svg>`;
}

const moveWord = { steam: 'Steam', key: 'Key number', flip: 'Favorite flipped', move: 'Big move' };
function moveText(m, g) {
  const abbr = (side) => (g ? g[side].abbr : side === 'home' ? m.home : m.away);
  if (m.mkt === 't') return { title: `Total ${m.dir === 'over' ? 'up' : 'down'} to ${fmtTot(m.to)}`, from: fmtTot(m.from), to: fmtTot(m.to) };
  const fav = (v) => (v < 0 ? 'home' : 'away');
  const line = (v) => (v === 0 ? 'PK' : `${abbr(fav(v))} ${fmtPts(-Math.abs(v))}`);
  const toward = g ? teamName(g[m.dir]) : abbr(m.dir);
  const title = m.kind === 'flip' ? `${g ? teamName(g[fav(m.to)]) : abbr(fav(m.to))} now favored`
    : m.kind === 'key' ? `${m.onto ? 'Onto' : 'Through'} ${m.key}, toward ${toward}` : `Moving toward ${toward}`;
  return { title, from: line(m.from), to: line(m.to) };
}
function ago(t) {
  const m = Math.round((serverNow() - t) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  if (m < 36 * 60) return `${Math.round(m / 60)} hr ago`;
  return `${Math.round(m / 1440)} days ago`;
}
