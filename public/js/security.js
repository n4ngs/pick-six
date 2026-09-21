'use strict';
/* Owner Security Center — the investigation surface over the telemetry API. Owner only; every endpoint it
   calls is owner-gated server-side, so this is a convenience layer, not the security boundary.

   It opens on #security as a full-screen overlay with sub-views: Overview, Devices, Sessions, Network,
   Security, Audit, and a filterable Timeline. Any device / session / IP / user drills into a detail view
   with its unified chronological timeline and the admin actions that apply to it. */

(function () {
  var S = { view: 'overview', data: {}, filter: {} };
  var api = function (path) { return fetch('/api/security/' + path, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); }); };
  var action = function (a, target, extra) {
    return fetch('/api/security/action', { method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(Object.assign({ action: a, target: target }, extra || {})) }).then(function (r) { return r.json(); });
  };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var ago = function (t) { if (!t) return ''; var s = (Date.now() - t) / 1000; if (s < 60) return Math.round(s) + 's ago'; if (s < 3600) return Math.round(s / 60) + 'm ago'; if (s < 86400) return Math.round(s / 3600) + 'h ago'; return Math.round(s / 86400) + 'd ago'; };
  var clock = function (t) { if (!t) return ''; var d = new Date(t); return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }); };
  var short = function (s, n) { s = String(s || ''); return s.length > (n || 10) ? s.slice(0, n || 10) + '…' : s; };

  function el() { var e = document.getElementById('secCenter'); if (!e) { e = document.createElement('div'); e.id = 'secCenter'; e.className = 'sec-center'; document.body.appendChild(e); } return e; }

  var NAV = [['overview', 'Overview'], ['devices', 'Devices'], ['sessions', 'Sessions'], ['network', 'Network'], ['security', 'Security'], ['risk', 'Risk'], ['audit', 'Audit'], ['timeline', 'Timeline']];

  function open() {
    location.hash = 'security';
    render();
  }
  function close() { var e = document.getElementById('secCenter'); if (e) e.remove(); if (location.hash === '#security') history.replaceState(null, '', '#' + (window.S && S.tab || 'live')); }

  function chrome(body) {
    return '<div class="sc-wrap"><header class="sc-head"><h1>Security Center</h1>'
      + '<nav class="sc-nav">' + NAV.map(function (n) { return '<button data-sv="' + n[0] + '" class="' + (S.view === n[0] ? 'on' : '') + '">' + n[1] + '</button>'; }).join('') + '</nav>'
      + '<button class="sc-x" data-scx aria-label="Close">✕</button></header><div class="sc-body">' + body + '</div></div>';
  }
  function loading() { el().innerHTML = chrome('<div class="sc-load">Loading…</div>'); }

  function render() {
    loading();
    var v = S.view;
    if (v === 'overview') return api('overview').then(function (d) { paint(overview(d)); });
    if (v === 'devices') return api('devices').then(function (d) { paint(devices(d.devices)); });
    if (v === 'sessions') return api('sessions').then(function (d) { paint(sessions(d.sessions)); });
    if (v === 'network') return api('ips').then(function (d) { paint(network(d.ips)); });
    if (v === 'security') return api('security').then(function (d) { paint(events('Security events', d.events)); });
    if (v === 'risk') return Promise.all([api('devices'), api('relationships')]).then(function (r) { paint(risk(r[0].devices, r[1])); });
    if (v === 'audit') return api('audit').then(function (d) { paint(events('Admin audit trail', d.events)); });
    if (v === 'timeline') return timeline();
  }
  function paint(html) { el().innerHTML = chrome(html); }

  // ---- views ----
  function stat(k, v, sub) { return '<div class="sc-stat"><b>' + esc(v) + '</b><span>' + esc(k) + '</span>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div>'; }
  function overview(d) {
    return '<div class="sc-grid">'
      + stat('Active users (24h)', d.activeUsers) + stat('Active devices', d.activeDevices, 'last 15 min')
      + stat('Active sessions', d.activeSessions) + stat('Visits today', d.visitsToday)
      + stat('Actions today', d.actionsToday) + stat('Unique IPs', d.uniqueIps)
      + stat('New devices', d.newDevices) + stat('New IPs', d.newIps)
      + stat('Login failures', d.loginFailures) + stat('401 / 403 / 429', d.e401 + ' / ' + d.e403 + ' / ' + d.e429)
      + stat('5xx errors', d.e5xx) + stat('Client errors', d.clientErrors)
      + stat('API latency p50 / p95', (d.apiLatencyP50 == null ? '—' : d.apiLatencyP50 + 'ms') + ' / ' + (d.apiLatencyP95 == null ? '—' : d.apiLatencyP95 + 'ms'))
      + stat('Elevated / high risk', d.riskElevated + ' / ' + d.riskHigh) + stat('Devices known', d.devicesKnown)
      + '</div><p class="sc-fine">' + esc(d.app) + ' · ' + esc(d.env) + ' · commit ' + esc(d.commit) + '</p>';
  }
  function riskPill(r) { return '<span class="sc-risk ' + r + '">' + r + '</span>'; }
  function devices(list) {
    return '<table class="sc-tbl"><thead><tr><th>Device</th><th>Users</th><th>Device</th><th>IPs</th><th>Sessions</th><th>Seen</th><th>Risk</th><th></th></tr></thead><tbody>'
      + list.map(function (d) {
        return '<tr data-dev="' + esc(d.did) + '"><td class="mono">' + esc(short(d.did, 12)) + (d.blocked ? ' <span class="sc-tag bad">blocked</span>' : '') + '</td>'
          + '<td>' + esc((d.users || []).join(', ') || '—') + '</td>'
          + '<td>' + esc(d.ua || d.os || '—') + '</td><td>' + d.ipCount + '</td><td>' + d.sessions + '</td>'
          + '<td>' + esc(ago(d.last)) + '</td><td>' + riskPill(d.risk) + '</td><td class="chev">›</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function sessions(list) {
    return '<table class="sc-tbl"><thead><tr><th>Session</th><th>Device</th><th>User</th><th>IPs</th><th>Reqs</th><th>Started</th><th>State</th></tr></thead><tbody>'
      + list.map(function (s) {
        return '<tr data-sess="' + esc(s.sid) + '"><td class="mono">' + esc(short(s.sid, 12)) + '</td><td class="mono">' + esc(short(s.deviceId, 10)) + '</td>'
          + '<td>' + esc(s.userId || '—') + '</td><td>' + (s.ips ? s.ips.length : 0) + (s.multiIp ? ' <span class="sc-tag">multi</span>' : '') + '</td>'
          + '<td>' + s.reqs + '</td><td>' + esc(ago(s.created)) + '</td><td>' + (s.revoked ? '<span class="sc-tag bad">revoked</span>' : s.active ? '<span class="sc-tag ok">active</span>' : 'ended') + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function network(list) {
    return '<table class="sc-tbl"><thead><tr><th>IP (hashed)</th><th>Devices</th><th>Users</th><th>Events</th><th>First</th><th>Last</th></tr></thead><tbody>'
      + list.map(function (i) {
        return '<tr data-ip="' + esc(i.ipHash) + '"><td class="mono">' + esc(i.ipHash) + ((i.users || []).length > 1 ? ' <span class="sc-tag">shared</span>' : '') + '</td>'
          + '<td>' + (i.devices || []).length + '</td><td>' + esc((i.users || []).join(', ') || '—') + '</td>'
          + '<td>' + i.events + '</td><td>' + esc(ago(i.first)) + '</td><td>' + esc(ago(i.last)) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }
  function events(title, list) {
    return '<h2 class="sc-h2">' + esc(title) + '</h2>' + timelineList(list);
  }
  function risk(list, rel) {
    var flagged = list.filter(function (d) { return d.risk !== 'low'; });
    var block = function (title, rows, cols) {
      if (!rows.length) return '';
      return '<h2 class="sc-h2">' + esc(title) + '</h2><ul class="sc-rel">' + rows.map(cols).join('') + '</ul>';
    };
    return (flagged.length ? '<h2 class="sc-h2">Elevated devices</h2><table class="sc-tbl"><tbody>' + flagged.map(function (d) {
        return '<tr data-dev="' + esc(d.did) + '"><td class="mono">' + esc(short(d.did, 12)) + '</td><td>' + riskPill(d.risk) + '</td><td>' + esc((d.riskWhy || []).join('; ')) + '</td></tr>';
      }).join('') + '</tbody></table>' : '<p class="sc-fine">No elevated devices.</p>')
      + block('Devices used by more than one user', rel.devicesWithMultipleUsers, function (r) { return '<li><span class="mono">' + esc(short(r.key, 12)) + '</span> — ' + esc(r.members.join(', ')) + '</li>'; })
      + block('IPs shared by multiple users', rel.ipsWithMultipleUsers, function (r) { return '<li><span class="mono">' + esc(short(r.key, 12)) + '</span> — ' + esc(r.members.join(', ')) + '</li>'; })
      + block('Devices using many IPs', rel.devicesWithManyIps, function (r) { return '<li><span class="mono">' + esc(short(r.key, 12)) + '</span> — ' + r.n + ' IPs</li>'; })
      + block('Concurrent sessions', rel.concurrentSessions, function (r) { return '<li><span class="mono">' + esc(short(r.device, 12)) + '</span> — ' + r.sessions.length + ' at once</li>'; });
  }

  // ---- the unified timeline, used raw and filtered ----
  function timelineList(list) {
    if (!list || !list.length) return '<p class="sc-fine">Nothing here yet.</p>';
    return '<ol class="sc-tl">' + list.map(function (e) {
      var d = e.data || {};
      var label = e.kind === 'security' ? (d.signal || 'security') : e.kind === 'app_action' ? (d.action || 'action') : e.kind === 'request' ? (e.method + ' ' + e.route + ' ' + e.status) : e.kind === 'client_error' ? (d.cls + ': ' + (d.msg || '')) : (e.route || e.kind);
      var extra = [e.user, e.uid ? short(e.uid, 8) : '', e.ipHash ? short(e.ipHash, 8) : ''].filter(Boolean).join(' · ');
      return '<li class="sc-ev sev-' + esc(e.sev) + '"><span class="sc-t">' + esc(clock(e.t)) + '</span>'
        + '<span class="sc-k">' + esc(e.kind) + '</span><span class="sc-l">' + esc(label) + '</span>'
        + '<span class="sc-m">' + esc(extra) + '</span></li>';
    }).join('') + '</ol>';
  }
  function timeline() {
    var f = S.filter;
    var qs = Object.keys(f).filter(function (k) { return f[k]; }).map(function (k) { return k + '=' + encodeURIComponent(f[k]); }).join('&');
    var bar = '<div class="sc-filters">'
      + inp('q', 'search…') + inp('uid', 'device id') + inp('sid', 'session id') + inp('user', 'user') + inp('ip', 'ip hash')
      + sel('kind', ['', 'request', 'page_view', 'click', 'app_action', 'login_success', 'login_failure', 'security', 'client_error', 'perf', 'admin_audit'])
      + sel('sev', ['', 'info', 'notice', 'warn', 'error'])
      + sel('risk', ['', 'low', 'elevated', 'high'])
      + '<button data-scq>Search</button><button data-scclear class="ghost">Clear</button></div>';
    return api('query' + (qs ? '?' + qs : '')).then(function (d) { paint(bar + timelineList(d.events)); });
  }
  function inp(name, ph) { return '<input class="sc-in" data-f="' + name + '" placeholder="' + ph + '" value="' + esc(S.filter[name] || '') + '">'; }
  function sel(name, opts) { return '<select class="sc-in" data-f="' + name + '">' + opts.map(function (o) { return '<option' + (S.filter[name] === o ? ' selected' : '') + '>' + esc(o || (name)) + '</option>'; }).join('') + '</select>'; }

  // ---- detail drill-downs with actions ----
  function actionsFor(kind, target, d) {
    var b = [];
    if (kind === 'device') {
      b.push(btn(d.blocked ? 'unblock_device' : 'block_device', target, d.blocked ? 'Unblock device' : 'Block device', !d.blocked));
      b.push(btn('require_reauth', target, 'Require re-auth', true));
    } else if (kind === 'session') {
      b.push(btn('revoke_session', target, 'Revoke session', true));
    } else if (kind === 'user') {
      b.push(btn(d.disabled ? 'enable_user' : 'disable_user', target, d.disabled ? 'Enable user' : 'Disable user', !d.disabled));
      b.push(btn('revoke_user', target, 'Revoke all sessions', true));
      b.push(btn('require_reauth_user', target, 'Require re-auth', true));
    }
    return '<div class="sc-acts">' + b.join('') + '</div>';
  }
  function btn(a, target, label, danger) { return '<button class="sc-act ' + (danger ? 'danger' : '') + '" data-act="' + a + '" data-target="' + esc(target) + '">' + esc(label) + '</button>'; }

  function detail(kind, id) {
    loading();
    var path = kind === 'user' ? 'user/' + encodeURIComponent(id) : kind + '/' + encodeURIComponent(id);
    return api(path).then(function (d) {
      var head, meta;
      if (kind === 'device') { head = 'Device ' + short(id, 16); meta = kv({ Users: (d.users || []).join(', '), Device: d.ua, OS: d.os, Browser: d.browser, Class: d.cls, Timezone: d.tz, Locale: d.locale, Viewport: d.viewport, Touch: d.touch, Standalone: d.standalone, 'IP count': d.ipCount, Sessions: d.sessions, Logins: d.logins, Fails: d.fails, Risk: d.risk + (d.riskWhy && d.riskWhy.length ? ' (' + d.riskWhy.join('; ') + ')' : ''), Blocked: d.blocked, 'First seen': clock(d.first), 'Last seen': clock(d.last) }); }
      else if (kind === 'session') { head = 'Session ' + short(id, 16); meta = kv({ Device: d.deviceId, User: d.userId, Started: clock(d.created), Authenticated: d.authenticated ? clock(d.authenticated) : 'no', 'Last activity': clock(d.last), State: d.revoked ? 'revoked' : d.active ? 'active' : 'ended', IPs: (d.ips || []).join(', '), Requests: d.reqs, 'Page views': d.views, Clicks: d.clicks, Actions: d.acts, Errors: d.errs }); }
      else if (kind === 'ip') { head = 'IP ' + id; meta = kv({ Devices: (d.devices || []).join(', '), Users: (d.users || []).join(', '), Events: d.events, 'First seen': clock(d.first), 'Last seen': clock(d.last) }); }
      else { head = 'User ' + esc(id); meta = kv({ Devices: (d.devices || []).length, Sessions: (d.sessions || []).length, Disabled: d.disabled }); }
      var ipHist = kind === 'device' && d.ipHistory && d.ipHistory.length ? '<h2 class="sc-h2">IP history</h2><table class="sc-tbl"><tbody>' + d.ipHistory.map(function (h) { return '<tr><td class="mono">' + esc(h.ipHash) + '</td><td>' + h.n + ' events</td><td>' + esc(clock(h.first)) + '</td><td>' + esc(clock(h.last)) + '</td></tr>'; }).join('') + '</tbody></table>' : '';
      paint('<button class="sc-back" data-scback>‹ Back</button><h2 class="sc-h2">' + esc(head) + '</h2>' + actionsFor(kind, id, d) + meta + ipHist
        + '<h2 class="sc-h2">Timeline</h2>' + timelineList(d.timeline));
    }).catch(function () { paint('<button class="sc-back" data-scback>‹ Back</button><p class="sc-fine">Not found.</p>'); });
  }
  function kv(o) { return '<dl class="sc-kv">' + Object.keys(o).map(function (k) { return o[k] == null || o[k] === '' ? '' : '<div><dt>' + esc(k) + '</dt><dd>' + esc(o[k]) + '</dd></div>'; }).join('') + '</dl>'; }

  // ---- events ----
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t.closest('[data-open-security]')) { e.preventDefault(); open(); return; }
    if (!document.getElementById('secCenter')) return;
    var sv = t.closest('[data-sv]'); if (sv) { S.view = sv.getAttribute('data-sv'); render(); return; }
    if (t.closest('[data-scx]')) { close(); return; }
    if (t.closest('[data-scback]')) { render(); return; }
    var dv = t.closest('[data-dev]'); if (dv) { detail('device', dv.getAttribute('data-dev')); return; }
    var ss = t.closest('[data-sess]'); if (ss) { detail('session', ss.getAttribute('data-sess')); return; }
    var ip = t.closest('[data-ip]'); if (ip) { detail('ip', ip.getAttribute('data-ip')); return; }
    if (t.closest('[data-scq]')) { readFilters(); S.view = 'timeline'; timeline(); return; }
    if (t.closest('[data-scclear]')) { S.filter = {}; timeline(); return; }
    var act = t.closest('[data-act]');
    if (act) {
      var a = act.getAttribute('data-act'), target = act.getAttribute('data-target');
      if (act.classList.contains('danger') && !confirm('Run "' + a + '" on ' + short(target, 16) + '?')) return;
      act.disabled = true; act.textContent = 'Working…';
      action(a, target).then(function () { render(); }).catch(function () { act.disabled = false; act.textContent = 'Failed — retry'; });
      return;
    }
  });
  function readFilters() { S.filter = {}; Array.prototype.forEach.call(document.querySelectorAll('#secCenter [data-f]'), function (i) { var v = i.value.trim(); if (v && v !== i.getAttribute('data-f')) S.filter[i.getAttribute('data-f')] = v; }); }

  addEventListener('hashchange', function () { if (location.hash === '#security') open(); else if (document.getElementById('secCenter')) close(); });
  if (location.hash === '#security') open();
  window.openSecurity = open;
})();
