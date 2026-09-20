'use strict';
/* Numbers you type in yourself, standing at a sportsbook window.

   They belong to the device that typed them: stored under that device's id and handed back only to that
   device, which merges them into its own board. Friends sharing this app never see each other's numbers and
   can't move each other's screens. Nothing typed in reaches the recorded line history or the closing line —
   those stay what the feeds reported, so closing line value is still measured against the real market. */

const { readJSON, writeJSON, num, log } = require('./util');
const { byKey } = require('./books');

// The old file held one shared set with no owner ({ gid: { book: line } }). There's no way to tell whose
// numbers those were, and a typed number is replaced by the next feed update anyway, so it starts fresh.
const store = (() => {
  const s = readJSON('manual.json', null);
  if (s && s.v === 1 && s.by) return s;
  if (s && Object.keys(s).length) log('counter numbers: clearing the old shared file (they are per-device now)');
  return { v: 1, by: {} };
})();
const save = () => writeJSON('manual.json', store);

const MAX_GAMES = 80;   // per device, so one phone can't grow the file without bound
const MAX_DEVICES = 500;

const gameAt = (g) => Math.max(0, ...Object.values(g).map((L) => L.at || 0));      // newest number for one game
const deviceAt = (mine) => Math.max(0, ...Object.values(mine).map(gameAt));        // newest number on one device
const range = (v, lo, hi) => { const n = num(v); return n == null || n < lo || n > hi ? null : n; };
const odds = (v) => { const n = num(v); return n == null || Math.abs(n) < 100 || Math.abs(n) > 100000 ? null : n; };
const juice = (v) => odds(v) ?? -110;

function list(uid) {
  return (uid && store.by[uid]) || {};
}

// One book's numbers for one game. Anything left blank is simply not recorded.
function set(uid, gid, book, body) {
  if (!uid) throw new Error('No device id.');
  if (!/^\d+$/.test(String(gid))) throw new Error('Unknown game.');
  if (!byKey[book]) throw new Error('Unknown book.');
  const s = range(body.s, -60, 60);
  const t = range(body.t, 20, 120);
  const ml = [odds(body.ml?.[0]), odds(body.ml?.[1])];
  // Say which number didn't read, rather than dropping it quietly.
  const given = (v) => v !== undefined && v !== null && v !== '';
  if (given(body.s) && s == null) throw new Error('That spread is outside what a football game can be.');
  if (given(body.t) && t == null) throw new Error('That total is outside what a football game can be.');
  if ((given(body.ml?.[0]) && ml[0] == null) || (given(body.ml?.[1]) && ml[1] == null)) throw new Error('A moneyline runs from −100000 to +100000 and never sits between −100 and +100.');
  if (s == null && t == null && ml[0] == null && ml[1] == null) throw new Error('Enter a spread, total or moneyline.');
  const L = {
    s, so: [juice(body.so?.[0]), juice(body.so?.[1])],
    t, to: [juice(body.to?.[0]), juice(body.to?.[1])],
    ml,
    at: Date.now(),
  };
  const mine = (store.by[uid] ||= {});
  (mine[gid] ||= {})[book] = L;
  const gids = Object.keys(mine);
  if (gids.length > MAX_GAMES) {
    gids.sort((a, b) => gameAt(mine[a]) - gameAt(mine[b]));
    for (const old of gids.slice(0, gids.length - MAX_GAMES)) delete mine[old];
  }
  const uids = Object.keys(store.by);
  if (uids.length > MAX_DEVICES) {
    uids.sort((a, b) => deviceAt(store.by[a]) - deviceAt(store.by[b]));
    for (const old of uids.slice(0, uids.length - MAX_DEVICES)) delete store.by[old];
  }
  save();
  return L;
}

function clear(uid, gid, book) {
  const mine = store.by[uid];
  if (!mine?.[gid]?.[book]) return false;
  delete mine[gid][book];
  if (!Object.keys(mine[gid]).length) delete mine[gid];
  if (!Object.keys(mine).length) delete store.by[uid];
  save();
  return true;
}

module.exports = { list, set, clear };
