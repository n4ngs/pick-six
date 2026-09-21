'use strict';
/* Owner observability + security telemetry. One append-only event log on the volume, plus the derived
   indexes the Security Center reads. Zero dependencies, bounded memory, reliability first: a telemetry
   failure must never take a request down, so every public function is wrapped and returns quietly.

   What this is and is NOT. This records what the SERVER already sees on a request (route, status, latency,
   IP, the app-issued device id, the UA string) plus first-party product events the app chooses to send
   (a page view, a bet created). It does not fingerprint a browser and never asks the client for battery,
   hardware or a VPN verdict — that is covert tracking, it is what app stores reject, and it is out of
   scope on purpose. The owner sees activity on their own board, correlated; not a dossier on a person.

   Shape. Events are JSONL under DATA/telemetry/events-YYYY-MM-DD.jsonl. A bounded ring buffer keeps the
   most recent N in memory for fast reads, and small rolling indexes (devices, sessions, ips) are kept so
   the admin views do not rescan the log. Retention trims old day-files on a timer. */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { DATA } = require('./util');

const DIR = path.join(DATA, 'telemetry');
fs.mkdirSync(DIR, { recursive: true });

const APP = process.env.APP_ID || 'pick-six';
const ENV = process.env.NODE_ENV === 'production' ? 'production' : 'testing';
const COMMIT = (process.env.RAILWAY_GIT_COMMIT_SHA || process.env.COMMIT_SHA || '').slice(0, 7) || 'dev';
// A per-boot key so IP hashes are pseudonymous in the log and cannot be reversed to an address by anyone
// who only has the file. The owner still sees the real IP live; the AT-REST log keeps the hash.
const IP_SALT = process.env.TELEMETRY_SALT || crypto.randomBytes(16).toString('hex');

const RING = 6000;                 // events kept in memory
const RETAIN_DAYS = Number(process.env.TELEMETRY_RETAIN_DAYS || 30);
const SESSION_GAP = 30 * 60e3;     // a quiet gap this long starts a new session
const RAPID_IP_MS = 10 * 60e3;     // two different IPs inside this window on one device is "rapid"

const ring = [];                   // recent events, newest last
const devices = new Map();         // did -> device record
const sessions = new Map();        // sid -> session record
const ips = new Map();             // ipHash -> ip record
let today = '';
let stream = null;
let seq = 0;
// While rebuilding indexes from the log on boot, replay is INERT: it must not write new lines to the log
// and must not re-derive security events, or every restart would double-count and grow the file. The
// historical events themselves are pushed back into the ring; only new derivation is suppressed.
let REPLAY = false;
let warmSkipped = 0;               // malformed/partial lines skipped on boot, surfaced in diagnostics()

// Only real user traffic drives new-device / IP-change detection. Derived events (security, audit,
// client_error, perf) must never feed back into it, or one signal cascades into thousands.
const PRIMARY = new Set(['request', 'login_success', 'login_failure', 'logout', 'page_view', 'click', 'app_action', 'visit_open', 'device_seen']);
const now = () => Date.now();
const id = (p) => `${p}_${now().toString(36)}${(seq++).toString(36)}${crypto.randomBytes(3).toString('hex')}`;
const ipHash = (ip) => (ip ? crypto.createHash('sha256').update(IP_SALT + '|' + ip).digest('hex').slice(0, 16) : '');
const dayOf = (t) => new Date(t).toISOString().slice(0, 10);

// ---- device family from a UA string. Coarse on purpose: a family, not a fingerprint. ----
function ua(uaStr) {
  const u = String(uaStr || '');
  if (!u) return { device: '', os: '', browser: '', mobile: null };
  const os = /iPhone|iPad|iPod/.test(u) ? 'iOS' : /Android/.test(u) ? 'Android' : /Macintosh|Mac OS X/.test(u) ? 'macOS'
    : /Windows/.test(u) ? 'Windows' : /CrOS/.test(u) ? 'ChromeOS' : /Linux/.test(u) ? 'Linux' : 'Unknown';
  const browser = /CriOS/.test(u) ? 'Chrome' : /FxiOS|Firefox\//.test(u) ? 'Firefox' : /Edg\//.test(u) ? 'Edge'
    : /Chrome\//.test(u) ? 'Chrome' : /Safari\//.test(u) ? 'Safari' : 'Unknown';
  const cls = /iPad|Tablet/.test(u) ? 'tablet' : /Mobi|iPhone|Android/.test(u) ? 'phone' : 'desktop';
  return { device: `${os === 'iOS' || os === 'macOS' ? '' : ''}${browser} on ${os}`.trim(), os, browser, cls };
}

function open(day) {
  if (stream && today === day) return;
  try { stream && stream.end(); } catch { /* ignore */ }
  today = day;
  stream = fs.createWriteStream(path.join(DIR, `events-${day}.jsonl`), { flags: 'a' });
  stream.on('error', () => { stream = null; });   // a broken stream must not throw on write
}

// ---- the one write path. Returns the event so a caller can thread its id into related events. ----
function record(kind, f = {}) {
  try {
    const t = now();
    const ipH = f.ip ? ipHash(f.ip) : (f.ipHash || '');
    const ev = {
      id: id('e'), t, kind, app: APP, env: ENV, commit: COMMIT,
      uid: f.uid || '', sid: f.sid || '', vid: f.vid || '', rid: f.rid || '',
      user: f.user || '', role: f.role || '',
      route: f.route || '', method: f.method || '', status: f.status ?? null, ms: f.ms ?? null,
      ipHash: ipH, sev: f.sev || 'info',
      data: f.data || undefined,
    };
    const day = dayOf(t);
    if (!REPLAY) { open(day); try { stream && stream.write(JSON.stringify(ev) + '\n'); } catch { /* ignore */ } }
    ring.push(ev);
    if (ring.length > RING) ring.splice(0, ring.length - RING);
    index(ev, f);
    return ev;
  } catch { return null; }
}

// ---- keep the small rolling indexes the admin views read, and derive change/security events. ----
function index(ev, f) {
  const t = ev.t;
  // device
  if (ev.uid) {
    let d = devices.get(ev.uid);
    if (!d) {
      d = { did: ev.uid, first: t, last: t, users: new Set(), apps: new Set(), sessions: new Set(),
        ipHashes: new Set(), ipLast: '', ua: '', os: '', browser: '', cls: '', logins: 0, fails: 0,
        visits: 0, events: 0, blocked: false, lastIpAt: 0, risk: 'low', riskWhy: [] };
      devices.set(ev.uid, d);
      if (PRIMARY.has(ev.kind) && ev.kind !== 'device_seen') security('NEW_DEVICE', ev, { device: ev.uid });
    }
    d.last = t; d.events++;
    d.apps.add(ev.app);
    if (ev.user) d.users.add(ev.user);
    if (ev.sid) d.sessions.add(ev.sid);
    if (f.uaParsed) { d.ua = f.uaParsed.device; d.os = f.uaParsed.os; d.browser = f.uaParsed.browser; d.cls = f.uaParsed.cls; }
    if (f.ctx && typeof f.ctx === 'object') {
      // Plain support fields the owner can read on the device — what size screen, what timezone, what
      // locale. Stored as-is, never combined into an identity key and never diffed for drift: this is
      // display/locale context, deliberately not a fingerprint.
      const c = f.ctx;
      if (c.tz) d.tz = c.tz;
      if (c.locale) d.locale = c.locale;
      if (c.vw && c.vh) d.viewport = `${c.vw}x${c.vh}`;
      if (c.touch != null) d.touch = c.touch;
      d.standalone = !!c.standalone;
      if (c.net) d.net = c.net;
    }
    if (ev.ipHash && PRIMARY.has(ev.kind)) {
      if (d.ipLast && d.ipLast !== ev.ipHash) {
        security('NEW_IP', ev, { device: ev.uid, from: d.ipLast, to: ev.ipHash });
        if (t - d.lastIpAt < RAPID_IP_MS) security('RAPID_IP_CHANGE', ev, { device: ev.uid, ms: t - d.lastIpAt }, 'warn');
      }
      d.ipHashes.add(ev.ipHash); d.ipLast = ev.ipHash; d.lastIpAt = t;
      // The full IP history for this device — every address it has used, first/last/count — so the owner
      // can see the sequence over time, not just the current one.
      const h = (d.ipHist ||= new Map()).get(ev.ipHash) || { ipHash: ev.ipHash, first: t, last: t, n: 0 };
      h.last = t; h.n++; d.ipHist.set(ev.ipHash, h);
    } else if (ev.ipHash) {
      d.ipHashes.add(ev.ipHash);   // record the address, but do not treat a derived event as a move
    }
    if (ev.kind === 'login_success') d.logins++;
    if (ev.kind === 'login_failure') d.fails++;
    if (ev.kind === 'visit_open') d.visits++;
    if (d.users.size > 1) d.risk = bump(d, 'device used by more than one identity');
  }
  // ip
  if (ev.ipHash) {
    let ip = ips.get(ev.ipHash);
    if (!ip) { ip = { ipHash: ev.ipHash, first: t, last: t, devices: new Set(), users: new Set(), apps: new Set(), events: 0 }; ips.set(ev.ipHash, ip); }
    ip.last = t; ip.events++; if (ev.uid) ip.devices.add(ev.uid); if (ev.user) ip.users.add(ev.user); ip.apps.add(ev.app);
  }
  // session
  if (ev.sid) {
    let s = sessions.get(ev.sid);
    if (!s) { s = { sid: ev.sid, deviceId: ev.uid, userId: ev.user, app: ev.app, created: t, last: t, ipFirst: ev.ipHash,
      ipLast: ev.ipHash, ua: f.uaParsed ? f.uaParsed.device : '', reqs: 0, views: 0, clicks: 0, acts: 0, errs: 0,
      auth: ev.role === 'owner' ? t : 0, ended: 0 }; sessions.set(ev.sid, s); }
    s.last = t; s.ipLast = ev.ipHash || s.ipLast;
    if (ev.user && !s.userId) s.userId = ev.user;           // a session names its user once it is known
    if (ev.ipHash) { (s.ips ||= new Set()).add(ev.ipHash); if (s.ips.size > 1) s.multiIp = true; }
    if (ev.uid && ev.uid !== s.deviceId) s.multiDevice = true;   // a session id seen from two devices is odd
    if (ev.kind === 'request') s.reqs++;
    if (ev.kind === 'page_view') s.views++;
    if (ev.kind === 'click') s.clicks++;
    if (ev.kind === 'app_action') s.acts++;
    if (ev.sev === 'error') s.errs++;
    if (ev.role === 'owner' && !s.auth) s.auth = t;
  }
}

const bump = (d, why) => { if (!d.riskWhy.includes(why)) d.riskWhy.push(why); return d.risk === 'high' ? 'high' : 'elevated'; };

// ---- a security event is just a record with a severity and its own kind. Suppressed during replay so a
//      restart never re-derives signals that are already in the log. ----
function security(kind, from, data, sev = 'notice') {
  if (REPLAY) return;
  record('security', { uid: from.uid, sid: from.sid, vid: from.vid, user: from.user, role: from.role,
    route: from.route, ipHash: from.ipHash, sev, data: { signal: kind, ...data } });
}

// ================================================================ the public API the server calls

// Assign/rotate a server-side session id for a device. A gap longer than SESSION_GAP starts a new one.
function sessionFor(uid) {
  const t = now();
  for (const s of sessions.values()) {
    if (s.deviceId === uid && !revokedSessions.has(s.sid) && !s.ended && t - s.last < SESSION_GAP) return s.sid;
  }
  return id('s');
}

// Called once per served request, after the route and status are known.
function request(f) {
  const uaParsed = ua(f.uaStr);
  const sid = f.sid || sessionFor(f.uid);
  record('request', { ...f, sid, uaParsed });
  // aggregate error classes as security signals worth surfacing
  if (f.status === 401) security('UNAUTHORIZED', { ...f, sid }, { route: f.route }, 'notice');
  if (f.status === 403) security('PERMISSION_FAILURE', { ...f, sid }, { route: f.route }, 'warn');
  if (f.status === 429) security('RATE_LIMIT_TRIGGERED', { ...f, sid }, { route: f.route }, 'warn');
  if (f.status >= 500) security('SERVER_ERROR', { ...f, sid }, { route: f.route, status: f.status }, 'warn');
  return sid;
}

function auth(kind, f) {          // 'login_success' | 'login_failure' | 'logout'
  const uaParsed = ua(f.uaStr);
  const sid = f.sid || sessionFor(f.uid);
  const ev = record(kind, { ...f, sid, uaParsed, sev: kind === 'login_failure' ? 'warn' : 'info' });
  if (kind === 'login_failure') {
    const d = devices.get(f.uid);
    const recent = ring.filter((e) => e.kind === 'login_failure' && now() - e.t < 15 * 60e3 && e.ipHash === ev.ipHash).length;
    if (recent >= 3) security('MULTIPLE_LOGIN_FAILURES', { ...f, sid }, { count: recent }, 'warn');
  }
  return sid;
}

// First-party product events from the client: page views, clicks, app/betting actions.
function event(f) {
  const kind = f.kind === 'page_view' ? 'page_view' : f.kind === 'click' ? 'click' : 'app_action';
  return record(kind, { ...f, sev: 'info' });
}
function clientError(f) { return record('client_error', { ...f, sev: 'error' }); }
function perf(f) { return record('perf', { ...f, sev: 'info' }); }

// Client batch ingest. `base` is the trusted server context (uid, ip, ua, sid); the client only supplies
// what it legitimately knows (route, kind, its own data). Bounded and defensive: bad items are skipped.
function ingest(batch, base) {
  if (!Array.isArray(batch)) return 0;
  let n = 0;
  const uaParsed = ua(base.uaStr);
  const sid = base.sid || sessionFor(base.uid);
  for (const it of batch.slice(0, 50)) {
    if (!it || typeof it.kind !== 'string') continue;
    const route = String(it.route || '').slice(0, 80);
    const vid = it.vid ? String(it.vid).slice(0, 40) : '';       // the client's per-load visit id
    const data = it.data && typeof it.data === 'object' ? clip(it.data) : undefined;
    const common = { uid: base.uid, role: base.role, user: base.user, ip: base.ip, sid, vid, route, uaParsed };
    switch (it.kind) {
      case 'visit_open': record('visit_open', { ...common, ctx: data && data.ctx, data }); break;
      case 'page_view': record('page_view', { ...common, data }); break;
      case 'click': record('click', { ...common, data }); break;
      case 'app_action': record('app_action', { ...common, data }); break;
      case 'client_error': clientError({ ...common, data }); break;
      case 'perf': perf({ ...common, data }); break;
      default: continue;
    }
    n++;
  }
  return n;
}
// Keep client-supplied data small and stringy — never trust its size or shape.
function clip(o) {
  const out = {};
  let i = 0;
  for (const k of Object.keys(o)) {
    if (i++ > 20) break;
    const v = o[k];
    if (v == null) continue;
    if (typeof v === 'object') { out[k] = clip(v); continue; }
    out[String(k).slice(0, 40)] = typeof v === 'string' ? v.slice(0, 300) : v;
  }
  return out;
}

// admin action, always audited
function audit(action, f) { return record('admin_audit', { ...f, sev: 'notice', data: { action, ...(f.data || {}) } }); }

// ================================================================ reads for the Security Center

const ser = (m) => [...m].map((v) => (v instanceof Set ? [...v] : v));
const dev = (d) => d && ({ did: d.did, first: d.first, last: d.last, users: [...d.users], apps: [...d.apps],
  sessions: d.sessions.size, ipCount: d.ipHashes.size, ipLast: d.ipLast, ua: d.ua, os: d.os, browser: d.browser,
  cls: d.cls, logins: d.logins, fails: d.fails, visits: d.visits, events: d.events,
  blocked: blockedDevices.has(d.did), blockReason: blockedDevices.get(d.did)?.reason || '', reauth: reauthDevices.has(d.did),
  tz: d.tz || '', locale: d.locale || '', viewport: d.viewport || '', touch: d.touch ?? null,
  standalone: !!d.standalone, net: d.net || '', risk: d.risk, riskWhy: d.riskWhy });
const sess = (s) => s && ({ sid: s.sid, deviceId: s.deviceId, userId: s.userId, app: s.app, created: s.created,
  authenticated: s.auth || 0, last: s.last, ended: s.ended || 0, revoked: revokedSessions.has(s.sid),
  ipFirst: s.ipFirst, ipLast: s.ipLast, ips: s.ips ? [...s.ips] : [], multiIp: !!s.multiIp, multiDevice: !!s.multiDevice,
  ua: s.ua, reqs: s.reqs, views: s.views, clicks: s.clicks, acts: s.acts, errs: s.errs,
  active: !revokedSessions.has(s.sid) && !s.ended && Date.now() - s.last < SESSION_GAP });

function overview() {
  const t = now(), dayAgo = t - 86400e3, min15 = t - 15 * 60e3;
  const recent = ring;
  const active = new Set(), activeDev = new Set();
  let views = 0, acts = 0, e401 = 0, e403 = 0, e429 = 0, e5xx = 0, errs = 0, fails = 0, lat = [], newDev = 0, newIp = 0, uniqIp = new Set();
  for (const e of recent) {
    if (e.t < dayAgo) continue;
    if (e.uid) activeDev.add(e.uid);
    if (e.user) active.add(e.user);
    if (e.ipHash) uniqIp.add(e.ipHash);
    if (e.kind === 'page_view') views++;
    if (e.kind === 'app_action' || e.kind === 'click') acts++;
    if (e.status === 401) e401++; if (e.status === 403) e403++; if (e.status === 429) e429++;
    if (e.status >= 500) e5xx++;
    if (e.kind === 'client_error') errs++;
    if (e.kind === 'login_failure') fails++;
    if (e.kind === 'request' && e.ms != null) lat.push(e.ms);
    if (e.kind === 'security' && e.data?.signal === 'NEW_DEVICE') newDev++;
    if (e.kind === 'security' && e.data?.signal === 'NEW_IP') newIp++;
  }
  const liveDev = new Set(), liveSess = new Set();
  for (const e of recent) if (e.t >= min15) { if (e.uid) liveDev.add(e.uid); if (e.sid) liveSess.add(e.sid); }
  const risk = [...devices.values()].reduce((a, d) => { a[d.risk] = (a[d.risk] || 0) + 1; return a; }, {});
  lat.sort((a, b) => a - b);
  return {
    app: APP, env: ENV, commit: COMMIT, at: t,
    activeUsers: active.size, activeDevices: liveDev.size, activeSessions: liveSess.size,
    visitsToday: views, actionsToday: acts, uniqueIps: uniqIp.size, newDevices: newDev, newIps: newIp,
    loginFailures: fails, e401, e403, e429, e5xx, clientErrors: errs,
    apiLatencyP50: lat.length ? lat[lat.length >> 1] : null, apiLatencyP95: lat.length ? lat[Math.floor(lat.length * 0.95)] : null,
    riskElevated: risk.elevated || 0, riskHigh: risk.high || 0, devicesKnown: devices.size,
  };
}

function listDevices() { return [...devices.values()].sort((a, b) => b.last - a.last).map(dev); }
function listSessions() { return [...sessions.values()].sort((a, b) => b.last - a.last).map(sess); }
function listIps() { return [...ips.values()].sort((a, b) => b.last - a.last).map((i) => ({ ipHash: i.ipHash, first: i.first, last: i.last, devices: [...i.devices], users: [...i.users], apps: [...i.apps], events: i.events })); }
function listSecurity(sev) { return ring.filter((e) => e.kind === 'security' && (!sev || e.sev === sev)).slice(-200).reverse(); }
function listAudit() { return ring.filter((e) => e.kind === 'admin_audit').slice(-200).reverse(); }

// A unified timeline for one correlation key: device / session / ip / user.
function timeline(key, val, limit = 200) {
  const f = key === 'device' ? (e) => e.uid === val : key === 'session' ? (e) => e.sid === val
    : key === 'ip' ? (e) => e.ipHash === val : key === 'user' ? (e) => e.user === val : () => false;
  return ring.filter(f).slice(-limit).reverse();
}

// The investigation query: any combination of filters, newest first. This is what makes the log a tool.
function query(q = {}) {
  const from = q.from ? Number(q.from) : 0;
  const to = q.to ? Number(q.to) : Infinity;
  const kinds = q.kind ? new Set(String(q.kind).split(',')) : null;
  const sev = q.sev ? new Set(String(q.sev).split(',')) : null;
  const text = q.q ? String(q.q).toLowerCase() : '';
  const out = [];
  for (let i = ring.length - 1; i >= 0 && out.length < (q.limit || 300); i--) {
    const e = ring[i];
    if (e.t < from || e.t > to) continue;
    if (q.uid && e.uid !== q.uid) continue;
    if (q.sid && e.sid !== q.sid) continue;
    if (q.user && e.user !== q.user) continue;
    if (q.ip && e.ipHash !== q.ip) continue;
    if (q.app && e.app !== q.app) continue;
    if (q.route && !String(e.route).includes(q.route)) continue;
    if (kinds && !kinds.has(e.kind)) continue;
    if (sev && !sev.has(e.sev)) continue;
    if (q.risk) { const d = devices.get(e.uid); if (!d || d.risk !== q.risk) continue; }
    if (text) { const hay = `${e.kind} ${e.route} ${e.user} ${e.uid} ${e.ipHash} ${JSON.stringify(e.data || '')}`.toLowerCase(); if (!hay.includes(text)) continue; }
    out.push(e);
  }
  return out;
}

// Cross-cutting relationships, computed from the indexes. The heart of the investigation view.
function relationships() {
  const userDevices = {}, deviceUsers = {}, ipUsers = {}, ipDevices = {}, deviceIps = {};
  for (const d of devices.values()) {
    for (const u of d.users) { (userDevices[u] ||= new Set()).add(d.did); (deviceUsers[d.did] ||= new Set()).add(u); }
    deviceIps[d.did] = [...(d.ipHist ? d.ipHist.values() : [])].sort((a, b) => b.last - a.last);
  }
  for (const ip of ips.values()) {
    for (const u of ip.users) (ipUsers[ip.ipHash] ||= new Set()).add(u);
    for (const dv of ip.devices) (ipDevices[ip.ipHash] ||= new Set()).add(dv);
  }
  const flag = (m, min) => Object.entries(m).filter(([, v]) => (v.size || v.length) >= min).map(([k, v]) => ({ key: k, n: v.size || v.length, members: [...(v.size ? v : v)] }));
  return {
    usersWithMultipleDevices: flag(userDevices, 2),
    devicesWithMultipleUsers: flag(deviceUsers, 2),           // the notable one: a shared device
    ipsWithMultipleUsers: flag(ipUsers, 2),                   // a shared network
    ipsWithMultipleDevices: flag(ipDevices, 2),
    devicesWithManyIps: Object.entries(deviceIps).filter(([, v]) => v.length >= 3).map(([k, v]) => ({ key: k, n: v.length })),
    concurrentSessions: concurrent(),
  };
}
// Sessions active in the same recent window, grouped by device — a spike is worth seeing.
function concurrent() {
  const t = now(), win = 15 * 60e3, live = [...sessions.values()].filter((s) => !revokedSessions.has(s.sid) && !s.ended && t - s.last < win);
  const byDevice = {};
  for (const s of live) (byDevice[s.deviceId] ||= []).push(s.sid);
  return Object.entries(byDevice).filter(([, v]) => v.length > 1).map(([k, v]) => ({ device: k, sessions: v }));
}

function deviceDetail(did) {
  const d = devices.get(did); if (!d) return null;
  return { ...dev(d), timeline: timeline('device', did, 150),
    ipHistory: [...(d.ipHist ? d.ipHist.values() : [])].sort((a, b) => b.last - a.last),
    sessionList: [...d.sessions].map((sid) => sess(sessions.get(sid))).filter(Boolean),
    forceReauth: reauthDevices.has(did), blocked: blockedDevices.has(did) };
}
function sessionDetail(sid) {
  const s = sessions.get(sid); if (!s) return null;
  return { ...sess(s), ips: s.ips ? [...s.ips] : [], timeline: timeline('session', sid, 200) };
}
function ipDetail(ipHash) {
  const i = ips.get(ipHash); if (!i) return null;
  return { ipHash: i.ipHash, first: i.first, last: i.last, devices: [...i.devices], users: [...i.users], apps: [...i.apps], events: i.events, timeline: timeline('ip', ipHash, 150) };
}
function userDetail(user) {
  const devs = [...devices.values()].filter((d) => d.users.has(user));
  const sess_ = [...sessions.values()].filter((s) => s.userId === user);
  return { user, devices: devs.map(dev), sessions: sess_.map(sess), timeline: timeline('user', user, 200), disabled: disabledUsers.has(user) };
}

/* ================================================================ ACCESS CONTROL STATE

   Canonical vocabulary, used consistently from here down:
     userId     the account name on the board            (event field `user`, session field `userId`)
     deviceId   the app-issued device-cookie id          (event field `uid`,  session field `deviceId`)
     sessionId  the server-derived session id            (event field `sid`,  session field `sid`)
     visitId    the client's per-page-load id            (event field `vid`)

   Four INDEPENDENT controls. None mutates another. Effective access is their OR, computed at request time
   by accessDenied() — so, for example, disabling a user never touches a device block that was set for a
   separate reason, and re-enabling the user leaves that device block exactly as it was.

     blockedDevices   deviceId  -> { reason, at }   hard 403 on every API for that device
     disabledUsers    Set<userId>                   the account is off, across all its devices
     reauthDevices    Set<deviceId>                 must sign in again once, then clears
     revokedSessions  Set<sessionId>                that one session is dead; the device is not

   All four are PERSISTED to the volume and restored on boot, because a restart must not silently drop a
   block or a disable. The append-only event log remains the audit trail; this file is the live state. */

const blockedDevices = new Map();
const disabledUsers = new Set();
const reauthDevices = new Set();
const revokedSessions = new Set();

const CTRL = path.join(DIR, 'controls.json');
function persist() {
  try {
    const tmp = CTRL + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify({
      v: 1,
      blockedDevices: [...blockedDevices.entries()],
      disabledUsers: [...disabledUsers],
      reauthDevices: [...reauthDevices],
      revokedSessions: [...revokedSessions],
    }));
    fs.renameSync(tmp, CTRL);
  } catch { /* best effort; the log still has the audit record */ }
}
function restore() {
  try {
    const s = JSON.parse(fs.readFileSync(CTRL, 'utf8'));
    for (const [k, v] of s.blockedDevices || []) blockedDevices.set(k, v);
    for (const u of s.disabledUsers || []) disabledUsers.add(u);
    for (const d of s.reauthDevices || []) reauthDevices.add(d);
    for (const sid of s.revokedSessions || []) revokedSessions.add(sid);
  } catch { /* no prior state */ }
}

// ---- device block (independent) ----
function blockDevice(deviceId, on = true, reason = 'owner') {
  if (on) blockedDevices.set(deviceId, { reason, at: now() });
  else blockedDevices.delete(deviceId);
  persist(); return true;
}
function isBlocked(deviceId) { return blockedDevices.has(deviceId); }

// ---- session revoke (independent): only the one session, never the device ----
function revokeSession(sessionId) {
  if (!sessions.has(sessionId)) return false;
  revokedSessions.add(sessionId); persist(); return true;
}
function isSessionRevoked(sessionId) { return revokedSessions.has(sessionId); }

// ---- revoke every session for a user, across devices (independent): sessions only, no reauth, no block ----
function revokeUser(userId) {
  let n = 0;
  for (const s of sessions.values()) if (s.userId === userId && !revokedSessions.has(s.sid)) { revokedSessions.add(s.sid); n++; }
  if (n) persist();
  return n;
}

// ---- require reauth for a DEVICE (independent): that device signs in again; its sessions are revoked ----
function requireReauth(deviceId) {
  reauthDevices.add(deviceId);
  for (const s of sessions.values()) if (s.deviceId === deviceId) revokedSessions.add(s.sid);
  persist(); return true;
}
// ---- require reauth for a USER: a separate function, applied to each of that user's devices ----
function requireReauthUser(userId) {
  let n = 0;
  for (const d of devices.values()) if (d.users.has(userId)) { reauthDevices.add(d.did); n++; }
  for (const s of sessions.values()) if (s.userId === userId) revokedSessions.add(s.sid);
  persist(); return n;
}
function needsReauth(deviceId) { return reauthDevices.has(deviceId); }
function clearReauth(deviceId) { if (reauthDevices.delete(deviceId)) persist(); }

// ---- user disable (independent): the account only. Never touches device-block state. ----
function disableUser(userId, off = true) {
  if (off) disabledUsers.add(userId); else disabledUsers.delete(userId);
  persist(); return true;
}
function isUserDisabled(userId) { return disabledUsers.has(userId); }

// ---- the single effective-access decision, an OR of the four independent controls ----
function accessDenied(deviceId, userId, sessionId) {
  if (deviceId && blockedDevices.has(deviceId)) return 'device_blocked';
  if (userId && disabledUsers.has(userId)) return 'user_disabled';
  if (sessionId && revokedSessions.has(sessionId)) return 'session_revoked';
  return null;
}

restore();

// ---- retention: drop day-files older than the window, on a slow timer ----
function sweep() {
  try {
    const cutoff = dayOf(now() - RETAIN_DAYS * 86400e3);
    for (const f of fs.readdirSync(DIR)) {
      const m = /^events-(\d{4}-\d{2}-\d{2})\.jsonl$/.exec(f);
      if (m && m[1] < cutoff) fs.unlinkSync(path.join(DIR, f));
    }
  } catch { /* best effort */ }
}

// ---- warm the indexes from today's + yesterday's files on boot, so a restart is not blind ----
function warm() {
  REPLAY = true;
  try {
    for (const day of [dayOf(now() - 86400e3), dayOf(now())]) {
      const file = path.join(DIR, `events-${day}.jsonl`);
      if (!fs.existsSync(file)) continue;
      const lines = fs.readFileSync(file, 'utf8').split('\n');
      for (const line of lines) {
        if (!line) continue;                       // a trailing newline leaves an empty final element
        let ev;
        try { ev = JSON.parse(line); } catch { warmSkipped++; continue; }   // partial/corrupt final line
        if (!ev || typeof ev.kind !== 'string') { warmSkipped++; continue; }
        ring.push(ev); index(ev, {});
      }
    }
    if (ring.length > RING) ring.splice(0, ring.length - RING);
  } catch { /* ignore */ } finally { REPLAY = false; }
}
warm();
setInterval(sweep, 6 * 3600e3).unref?.();
sweep();

module.exports = {
  APP, ENV, COMMIT, ipHash, ua,
  request, auth, event, clientError, perf, audit, ingest, sessionFor,
  overview, listDevices, listSessions, listIps, listSecurity, listAudit, timeline, query, relationships,
  deviceDetail, sessionDetail, ipDetail, userDetail,
  blockDevice, isBlocked, revokeSession, isSessionRevoked, revokeUser,
  requireReauth, requireReauthUser, needsReauth, clearReauth,
  disableUser, isUserDisabled, accessDenied,
  diagnostics,
  _sweep: sweep, _stats: () => ({ ring: ring.length, devices: devices.size, sessions: sessions.size, ips: ips.size }),
};

// Boot/health diagnostics: what was restored, and whether any log lines were unreadable on startup.
function diagnostics() {
  return {
    app: APP, env: ENV, commit: COMMIT,
    ring: ring.length, devices: devices.size, sessions: sessions.size, ips: ips.size,
    warmSkipped,                                   // partial/corrupt lines skipped safely on boot
    controls: { blockedDevices: blockedDevices.size, disabledUsers: disabledUsers.size, reauthDevices: reauthDevices.size, revokedSessions: revokedSessions.size },
  };
}
