'use strict';
/* Shared helpers: fetch with timeout and backoff, a tiny worker pool, Eastern-time dates, atomic JSON files. */

const fs = require('node:fs');
const path = require('node:path');

const DATA = process.env.DATA_DIR ? path.resolve(process.env.DATA_DIR) : path.join(__dirname, '..', 'data');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36';

const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a);
const num = (v) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- fetch
// Each host gets its own health record so one flaky source never slows the others.
const hosts = new Map(); // host -> { ok, fail, lastOk, lastErr, until }
function hostOf(url) { try { return new URL(url).host; } catch { return url; } }
function health() {
  return Object.fromEntries([...hosts].map(([h, v]) => [h, { lastOk: v.lastOk, lastErr: v.lastErr, fails: v.fail, pausedFor: Math.max(0, v.until - Date.now()) }]));
}

async function getJSON(url, { timeout = 15000, headers = {}, text = false } = {}) {
  const host = hostOf(url);
  const h = hosts.get(host) || { ok: 0, fail: 0, lastOk: 0, lastErr: null, until: 0 };
  hosts.set(host, h);
  if (h.until > Date.now()) throw new Error(`${host} paused after errors`);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(url, { signal: ctl.signal, headers: { accept: 'application/json', 'user-agent': UA, ...headers } });
    if (r.status === 429 || r.status >= 500) throw Object.assign(new Error(`HTTP ${r.status} ${host}`), { retry: true });
    if (!r.ok) throw new Error(`HTTP ${r.status} ${url.split('?')[0]}`);
    const body = text ? await r.text() : await r.json();
    h.ok++; h.fail = 0; h.lastOk = Date.now(); h.lastErr = null;
    return { body, headers: r.headers };
  } catch (e) {
    h.fail++;
    h.lastErr = `${new Date().toISOString()} ${e.name === 'AbortError' ? 'timeout' : e.message}`;
    // Back off a host that keeps failing: 5 s, 10 s, 20 s … up to 2 min.
    if (h.fail >= 3) h.until = Date.now() + Math.min(120000, 5000 * 2 ** (h.fail - 3));
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
const getBody = async (url, opts) => (await getJSON(url, opts)).body;
const getText = async (url, opts) => (await getJSON(url, { ...opts, text: true })).body;

async function pool(items, n, fn) {
  const q = [...items];
  const worker = async () => {
    while (q.length) {
      const it = q.shift();
      try { await fn(it); } catch (e) { log('pool', e.message); }
    }
  };
  await Promise.all(Array.from({ length: Math.min(n, q.length) }, worker));
}

// ---------------------------------------------------------------- dates
// NFL runs on Eastern time: windows, "Saturday" and the day roll all use it.
function etParts(d = new Date()) {
  return Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23',
    }).formatToParts(d).map((x) => [x.type, x.value]),
  );
}
const etDate = (d = new Date()) => { const p = etParts(d); return `${p.year}-${p.month}-${p.day}`; };
const etHour = (d) => { const p = etParts(d); return Number(p.hour) + Number(p.minute) / 60; };

// ---------------------------------------------------------------- files
fs.mkdirSync(DATA, { recursive: true });
function readJSON(name, fallback) {
  try { return JSON.parse(fs.readFileSync(path.join(DATA, name), 'utf8')); } catch { return fallback; }
}
// Write to a temp file and rename, so a crash mid-write never leaves a half file behind.
function writeJSON(name, value) {
  const file = path.join(DATA, name);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value));
  fs.renameSync(tmp, file);
}

// How well a team name from another feed matches an ESPN team: 4 exact, 3 school name, 2 close, 0 no.
const ALIAS = {
  miamifl: 'miami', miamiflorida: 'miami', miamioh: 'miamioh', southerncalifornia: 'usc', usc: 'usc', ucf: 'ucf', centralflorida: 'ucf',
  lsu: 'lsu', louisianastate: 'lsu', smu: 'smu', southernmethodist: 'smu', tcu: 'tcu', texaschristian: 'tcu', byu: 'byu', brighamyoung: 'byu',
  olemiss: 'olemiss', mississippi: 'olemiss', uconn: 'uconn', connecticut: 'uconn', umass: 'massachusetts', utsa: 'utsa', texassanantonio: 'utsa', utsa: 'utsa', tennesseemartin: 'utmartin', nichollsstate: 'nicholls', nichollsst: 'nicholls', mcneesestate: 'mcneese', mcneesest: 'mcneese', utmartin: 'utmartin', miamiohio: 'miamioh',
  utep: 'utep', texaselpaso: 'utep', uab: 'uab', alabamabirmingham: 'uab', unlv: 'unlv', nevadalasvegas: 'unlv', fiu: 'fiu', floridainternational: 'fiu',
  floridaintl: 'fiu', louisianamonroe: 'ulmonroe', ulmonroe: 'ulmonroe', ulm: 'ulmonroe', louisianalafayette: 'louisiana', ullafayette: 'louisiana',
  hawaii: 'hawaii', sanjosestate: 'sanjosestate', sanjosest: 'sanjosestate', appstate: 'appalachianstate', appalachianst: 'appalachianstate',
  ncstate: 'ncstate', northcarolinastate: 'ncstate', pittsburgh: 'pitt', pitt: 'pitt', jacksonvillest: 'jacksonvillestate', gasouthern: 'georgiasouthern',
  georgiasouthern: 'georgiasouthern', gastate: 'georgiastate', southernmiss: 'southernmiss', southernmississippi: 'southernmiss', olddominion: 'olddominion',
  middletennessee: 'middletennessee', middletennesseestate: 'middletennessee', mtsu: 'middletennessee', westernkentucky: 'westernkentucky', wku: 'westernkentucky',
  sambhouston: 'samhouston', samhoustonstate: 'samhouston', samhouston: 'samhouston', texasam: 'texasam', texasaandm: 'texasam',
};
const canon = (s) => { const n = norm(s); return ALIAS[n] || n; };
// Other feeds shorten school names: "San Diego ST Aztecs", "N Illinois Huskies", "Miss State".
const expand = (s) => String(s || '')
  .replace(/\bSt\.?(?=\s|$)/gi, 'State').replace(/\bN\.?(?=\s)/g, 'Northern ').replace(/\bS\.?(?=\s)/g, 'Southern ')
  .replace(/\bE\.?(?=\s)/g, 'Eastern ').replace(/\bW\.?(?=\s)/g, 'Western ').replace(/\bC\.?(?=\s)/g, 'Central ')
  .replace(/\bMiss\b(?!issippi)/g, 'Mississippi').replace(/\bMich\b/g, 'Michigan').replace(/\bTenn\b/g, 'Tennessee').replace(/\bLa\.?(?=\s)/g, 'Louisiana ').replace(/\bFL\b/g, 'Florida');
function nameScore(name, e) {
  if (!name || !e) return 0;
  const n = norm(expand(name)), raw = norm(name);
  const key = norm(e.name), masc = norm(e.mascot);
  if (n === key || raw === key) return 4;
  const hasMascot = masc && n.endsWith(masc) && n.length > masc.length;
  const school = hasMascot ? n.slice(0, -masc.length) : n;
  const st = (x) => (ALIAS[x] || x).replace(/st$/, 'state');
  const mine = st(school);
  const theirs = [e.loc, e.short, e.abbr].map((x) => st(norm(x)));
  if (theirs.includes(mine) || theirs.includes(st(raw))) return hasMascot ? 4 : 3;
  // Mascot matches and the school starts the same way ("Texas-San Antonio Roadrunners" vs "UTSA Roadrunners" needs the alias above).
  if (hasMascot && [...theirs, norm(e.loc), norm(e.short)].some((t) => t.slice(0, 4) === school.slice(0, 4))) return 2;
  return 0;
}

const UA_HEADERS = { 'user-agent': UA, 'accept-language': 'en-US,en;q=0.9' };

const round = (v, d = 1) => (v == null ? null : Math.round(v * 10 ** d) / 10 ** d);
const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/&/g, 'and').replace(/[^a-z0-9]/g, '');

module.exports = { DATA, UA_HEADERS, nameScore, log, num, sleep, getJSON, getBody, getText, health, pool, etParts, etDate, etHour, readJSON, writeJSON, round, norm };
