'use strict';
/* First-party product telemetry, sent to this app's own server. Page views, interactions, bet actions,
   client errors and standard performance timings — the things the owner needs to see what happened on the
   board, correlated by the device cookie the server already set.

   What it collects and what it does not. Once per visit it sends benign runtime context the owner asked
   for: viewport, screen size, device-pixel-ratio, timezone, locale, language and touch capability. It
   does NOT fingerprint: no battery, no hardware/memory enumeration, no canvas or font probing, no
   VPN/Tor guessing. Everything here is either a product action or a coarse display/locale fact, sent to
   our own origin only, and it degrades to nothing if the network is down. */

(function () {
  var ENDPOINT = '/api/telemetry';
  var queue = [];
  var route = location.hash.slice(1) || 'live';
  var flushTimer = 0;
  // A visit id for this page load, so every event this load produces correlates to one visit. The device
  // id and session id are the server's to assign (from the cookie); the client owns only the visit.
  var VISIT = 'v_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

  function ctx() {
    var c = {};
    try {
      c.vw = innerWidth; c.vh = innerHeight;
      c.sw = screen.width; c.sh = screen.height; c.dpr = Math.round((devicePixelRatio || 1) * 100) / 100;
      c.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
      c.tzo = new Date().getTimezoneOffset();
      c.locale = (navigator.languages && navigator.languages[0]) || navigator.language || '';
      c.langs = (navigator.languages || []).slice(0, 4).join(',');
      c.touch = navigator.maxTouchPoints || 0;
      c.standalone = !!(matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
      c.online = navigator.onLine !== false;
      var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (conn) { c.net = conn.effectiveType || ''; c.rtt = conn.rtt || null; c.down = conn.downlink || null; c.saver = !!conn.saveData; }
    } catch (e) { /* a missing API is fine */ }
    return c;
  }

  function push(kind, data) {
    try {
      queue.push({ kind: kind, t: Date.now(), route: route, vid: VISIT, data: data || undefined });
      if (queue.length >= 20) flush();
      else if (!flushTimer) flushTimer = setTimeout(flush, 4000);
    } catch (e) { /* never throw from an event handler */ }
  }

  function flush(sync) {
    if (flushTimer) { clearTimeout(flushTimer); flushTimer = 0; }
    if (!queue.length) return;
    var batch = queue.splice(0, 40);
    var body = JSON.stringify({ events: batch });
    try {
      if (sync && navigator.sendBeacon) { navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' })); return; }
      fetch(ENDPOINT, { method: 'POST', headers: { 'content-type': 'application/json' }, body: body, keepalive: true, credentials: 'same-origin' })
        .catch(function () { /* drop on failure; telemetry is never worth a retry storm */ });
    } catch (e) { /* ignore */ }
  }

  // ---- public API the app can call for semantic actions ----
  window.tel = {
    view: function (r) { route = r || (location.hash.slice(1) || 'live'); push('page_view', { title: document.title }); },
    act: function (name, data) { push('app_action', Object.assign({ action: name }, data || {})); },
    click: function (label, data) { push('click', Object.assign({ label: label }, data || {})); },
    flush: flush,
  };

  // ---- automatic capture ----
  // Page view on load and on every route change.
  addEventListener('hashchange', function () { window.tel.view(); });
  // Interactions: anything the app marks, plus tabs, primary buttons and outbound links.
  addEventListener('click', function (e) {
    try {
      var el = e.target.closest('[data-tel],[data-tab],button,a');
      if (!el) return;
      if (el.hasAttribute('data-tel')) { push('click', { label: el.getAttribute('data-tel'), id: el.id || '' }); return; }
      if (el.hasAttribute('data-tab')) { push('click', { label: 'tab:' + el.getAttribute('data-tab') }); return; }
      var tag = el.tagName.toLowerCase();
      if (tag === 'a' && el.host && el.host !== location.host) { push('click', { label: 'outbound', href: el.host }); return; }
      var txt = (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40);
      if (txt) push('click', { label: txt, el: tag });
    } catch (err) { /* ignore */ }
  }, true);

  // App foreground/background.
  addEventListener('visibilitychange', function () { push(document.visibilityState === 'visible' ? 'app_action' : 'app_action', { action: document.visibilityState === 'visible' ? 'APP_FOREGROUND' : 'APP_BACKGROUND' }); flush(document.visibilityState !== 'visible'); });
  addEventListener('pagehide', function () { push('app_action', { action: 'PAGE_EXIT' }); flush(true); });
  addEventListener('online', function () { push('app_action', { action: 'ONLINE' }); });
  addEventListener('offline', function () { push('app_action', { action: 'OFFLINE' }); });

  // Client errors and unhandled rejections, de-duplicated by the server.
  addEventListener('error', function (e) {
    if (e.target && e.target !== window && e.target.src) { push('client_error', { cls: 'resource', msg: String(e.target.src).slice(0, 200) }); return; }
    push('client_error', { cls: e.error && e.error.name || 'Error', msg: (e.message || '').slice(0, 300), at: (e.filename || '') + ':' + (e.lineno || 0) });
  });
  addEventListener('unhandledrejection', function (e) {
    var r = e.reason; push('client_error', { cls: 'UnhandledRejection', msg: String(r && (r.message || r)).slice(0, 300) });
  });

  // Performance: navigation timing once, plus LCP / CLS / long tasks if the browser reports them.
  function perf() {
    try {
      var nav = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      var d = {};
      if (nav) { d.load = Math.round(nav.loadEventEnd || 0); d.ttfb = Math.round(nav.responseStart || 0); d.dcl = Math.round(nav.domContentLoadedEventEnd || 0); }
      var fcp = performance.getEntriesByName && performance.getEntriesByName('first-contentful-paint')[0];
      if (fcp) d.fcp = Math.round(fcp.startTime);
      push('perf', d);
      if (window.PerformanceObserver) {
        try {
          var lcp = 0;
          new PerformanceObserver(function (l) { var es = l.getEntries(); lcp = Math.round(es[es.length - 1].startTime); }).observe({ type: 'largest-contentful-paint', buffered: true });
          var cls = 0;
          new PerformanceObserver(function (l) { l.getEntries().forEach(function (e2) { if (!e2.hadRecentInput) cls += e2.value; }); }).observe({ type: 'layout-shift', buffered: true });
          var longs = 0;
          new PerformanceObserver(function (l) { longs += l.getEntries().length; }).observe({ type: 'longtask', buffered: true });
          addEventListener('pagehide', function () { push('perf', { lcp: lcp, cls: Math.round(cls * 1000) / 1000, longtasks: longs }); }, { once: true });
        } catch (e) { /* observer types vary by browser */ }
      }
    } catch (e) { /* ignore */ }
  }

  // Open the visit with the runtime context, then start.
  push('visit_open', { ctx: ctx(), ref: document.referrer ? new URL(document.referrer).host : '' });
  window.tel.view();
  if (document.readyState === 'complete') perf();
  else addEventListener('load', perf);
})();
