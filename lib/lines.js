'use strict';
/* Line history for one week of games. Every time a book's number changes, it's written down with the time,
   so the app can draw how a line moved and call out steam, key-number crossings and favorite flips.
   Nobody publishes free CFB line history, so this file is the record. It persists in data/weeks/. */

const { readJSON, writeJSON } = require('./util');

const KEYS = [3, 7, 10, 14];      // the margins college games land on most often
const STEAM_BOOKS = 3;            // this many books moving the same way…
const STEAM_WINDOW = 10 * 60e3;   // …inside this window is steam
const MAX_POINTS = 500;

const same = (a, b) => a === b || (a == null && b == null);

class Week {
  constructor({ season, type, week }) {
    this.id = `${season}-${type}-${String(week).padStart(2, '0')}`;
    this.file = `weeks/${this.id}.json`;
    const saved = readJSON(this.file, null);
    this.games = saved?.games || {}; // gid -> { b: {book: {s:[], t:[], ml:[]}}, l: {s:[], t:[]}, open, close, moves: [], recent: [] }
    this.dirty = false;
  }

  g(gid) {
    return (this.games[gid] ||= { b: {}, l: { s: [], t: [] }, open: null, close: null, moves: [] });
  }

  // Record one book's pregame line. Returns the spread/total value changes it caused.
  record(gid, book, L, t = Date.now()) {
    if (!L) return [];
    const G = this.g(gid);
    const H = (G.b[book] ||= { s: [], t: [], ml: [] });
    const changes = [];
    const push = (arr, pt) => { arr.push(pt); if (arr.length > MAX_POINTS) arr.splice(1, 1); this.dirty = true; };
    const lastS = H.s.at(-1), lastT = H.t.at(-1), lastM = H.ml.at(-1);
    if (L.s != null && (!lastS || !same(lastS[1], L.s) || Math.abs((lastS[2] ?? 0) - (L.so?.[0] ?? 0)) >= 5)) {
      if (lastS && !same(lastS[1], L.s)) changes.push({ mkt: 's', book, from: lastS[1], to: L.s, t });
      push(H.s, [t, L.s, L.so?.[0] ?? null]);
    }
    if (L.t != null && (!lastT || !same(lastT[1], L.t) || Math.abs((lastT[2] ?? 0) - (L.to?.[0] ?? 0)) >= 5)) {
      if (lastT && !same(lastT[1], L.t)) changes.push({ mkt: 't', book, from: lastT[1], to: L.t, t });
      push(H.t, [t, L.t, L.to?.[0] ?? null]);
    }
    if (L.ml?.[0] != null && (!lastM || !same(lastM[1], L.ml[0]) || !same(lastM[2], L.ml[1]))) {
      push(H.ml, [t, L.ml[0], L.ml[1]]);
    }
    return changes;
  }

  // Live (in-game) market line, consensus only: it moves with the score, so it's context, not a signal.
  recordLive(gid, L, t = Date.now()) {
    if (!L) return;
    const G = this.g(gid);
    const ls = G.l.s.at(-1), lt = G.l.t.at(-1);
    if (L.s != null && (!ls || ls[1] !== L.s)) { G.l.s.push([t, L.s]); this.dirty = true; }
    if (L.t != null && (!lt || lt[1] !== L.t)) { G.l.t.push([t, L.t]); this.dirty = true; }
    if (G.l.s.length > MAX_POINTS) G.l.s.splice(0, G.l.s.length - MAX_POINTS);
    if (G.l.t.length > MAX_POINTS) G.l.t.splice(0, G.l.t.length - MAX_POINTS);
  }

  setOpen(gid, open) {
    const G = this.g(gid);
    if (!open || (G.open && G.open.s === open.s && G.open.t === open.t && G.open.at === open.at)) return;
    G.open = open;
    this.dirty = true;
  }

  // The last pregame number, frozen at kickoff. Closing line value is measured against this.
  setClose(gid, close) {
    const G = this.g(gid);
    if (G.close || !close) return false;
    G.close = { ...close, at: Date.now() };
    this.dirty = true;
    return true;
  }

  // Look at a batch of book changes for one game and decide if any of it is news.
  detect(gid, changes, cons, now = Date.now()) {
    const G = this.g(gid);
    const out = [];
    G.recent = (G.recent || []).filter((c) => now - c.t < STEAM_WINDOW);
    for (const c of changes) if (c.book !== 'cons' && c.book !== 'open') G.recent.push(c);
    const flagged = (kind, mkt, within) => G.moves.some((m) => m.kind === kind && m.mkt === mkt && now - m.t < within);

    for (const mkt of ['s', 't']) {
      const recent = G.recent.filter((c) => c.mkt === mkt);
      const up = new Set(recent.filter((c) => c.to > c.from).map((c) => c.book));
      const down = new Set(recent.filter((c) => c.to < c.from).map((c) => c.book));
      for (const [dirBooks, sign] of [[up, 1], [down, -1]]) {
        if (dirBooks.size >= STEAM_BOOKS && !flagged('steam', mkt, 30 * 60e3)) {
          const rs = recent.filter((c) => dirBooks.has(c.book) && Math.sign(c.to - c.from) === sign).sort((a, b) => a.t - b.t);
          // Report where the moving books went; the consensus often lags them by a poll or two.
          if (rs[0].from === rs.at(-1).to) continue;
          out.push({
            kind: 'steam', mkt, from: rs[0].from, to: rs.at(-1).to, books: [...dirBooks], t: now,
            dir: mkt === 's' ? (sign < 0 ? 'home' : 'away') : sign > 0 ? 'over' : 'under', secs: Math.round((rs.at(-1).t - rs[0].t) / 1000),
          });
        }
      }
    }

    // Market (consensus) changes: key numbers, favorite flips, big moves.
    for (const c of changes.filter((x) => x.book === 'cons')) {
      if (c.mkt === 's') {
        const a = Math.abs(c.from), b = Math.abs(c.to), lo = Math.min(a, b), hi = Math.max(a, b);
        if (c.from && c.to && Math.sign(c.from) !== Math.sign(c.to)) {
          out.push({ kind: 'flip', mkt: 's', from: c.from, to: c.to, t: now, dir: c.to < 0 ? 'home' : 'away' });
        } else {
          const key = KEYS.find((k) => lo <= k && k <= hi && lo !== hi);
          if (key) out.push({ kind: 'key', mkt: 's', from: c.from, to: c.to, key, t: now, dir: c.to < c.from ? 'home' : 'away', onto: b === key });
        }
      }
      // A big move: the market is 1.5+ (spread) or 2+ (total) away from where it was last called out.
      const last = [...G.moves].reverse().find((m) => m.mkt === c.mkt && m.kind !== 'steam');
      const base = last ? last.to : (c.mkt === 's' ? G.open?.s : G.open?.t);
      if (base != null && Math.abs(c.to - base) >= (c.mkt === 's' ? 1.5 : 2) && !out.some((m) => m.mkt === c.mkt)) {
        out.push({ kind: 'move', mkt: c.mkt, from: base, to: c.to, t: now, dir: c.mkt === 's' ? (c.to < base ? 'home' : 'away') : c.to > base ? 'over' : 'under' });
      }
    }
    for (const m of out) {
      m.id = `${gid}-${m.kind}-${m.mkt}-${now}`;
      m.gid = gid;
      G.moves.push(m);
      this.dirty = true;
    }
    if (G.moves.length > 60) G.moves.splice(0, G.moves.length - 60);
    return out;
  }

  // A small, even sample of the market line for sparklines on the board.
  spark(gid, mkt, n = 24) {
    const G = this.games[gid];
    if (!G) return null;
    const pts = [];
    if (G.open?.[mkt] != null) pts.push([G.open.at || 0, G.open[mkt]]);
    const H = G.b.cons?.[mkt] || G.b.dk?.[mkt] || [];
    for (const p of H) pts.push([p[0], p[1]]);
    if (pts.length <= n) return pts;
    const out = [pts[0]];
    for (let i = 1; i < n - 1; i++) out.push(pts[Math.round((i * (pts.length - 1)) / (n - 1))]);
    out.push(pts.at(-1));
    return out;
  }

  full(gid) { return this.games[gid] || null; }

  moves(since = 0) {
    return Object.values(this.games).flatMap((G) => G.moves || []).filter((m) => m.t >= since).sort((a, b) => b.t - a.t);
  }

  save(force = false) {
    if (!this.dirty && !force) return;
    const games = {};
    for (const [gid, G] of Object.entries(this.games)) { const { recent, ...rest } = G; games[gid] = rest; }
    writeJSON(this.file, { v: 1, id: this.id, saved: Date.now(), games });
    this.dirty = false;
  }
}

module.exports = { Week, KEYS };
