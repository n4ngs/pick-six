'use strict';
/* Pick Six — wiring: tabs and routes, one delegated click handler, theme and alerts, start-up. */

const pendingDeletes = new Set(); // bets hidden while their Undo toast is showing

// ------------------------------------------------------------ tabs & routes
const TABS = ['live', 'board', 'bets', 'tools', 'admin'];
// The Group tab belongs to whoever runs the board. A guest never sees it, and can't reach it by typing #admin.
const canAdmin = () => S.me?.role !== 'guest' && !!S.me?.shared;
function setTab(tab, push = true) {
  if (!TABS.includes(tab)) tab = 'live';
  if (tab === 'admin' && !canAdmin()) tab = 'live';
  S.tab = tab;
  for (const v of $$('.view')) v.classList.toggle('on', v.dataset.view === tab);
  for (const a of $$('[data-tab]')) a.classList.toggle('on', a.dataset.tab === tab && !a.classList.contains('brand'));
  store.set('lastTab', tab);
  if (push && location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
  if (tab === 'board' && !S.boardWeek) S.boardWeek = S.def;
  window.scrollTo({ top: 0 });
  renderAll();
}
// A tab hash switches tabs. Anything else (#game/…, #edges, #sweat, #tm/…) is a sheet that opens over the tab you
// were on, so a restart or a deep link never throws you back to Live. Feature sheets open themselves from the hash.
let routed = false;
function route() {
  const h = location.hash.slice(1);
  if (TABS.includes(h)) { setTab(h, false); routed = true; return; }
  if (!routed) { const last = store.get('lastTab', 'live'); setTab(TABS.includes(last) ? last : 'live', false); routed = true; }
  const gm = /^game\/(\d+)$/.exec(h);
  if (gm) openGame(gm[1]);
}
window.addEventListener('hashchange', route);

// ------------------------------------------------------------ theme & alerts
function applyTheme() {
  const t = S.theme;
  if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  const b = $('#themeBtn');
  b.innerHTML = t === 'dark' ? ICON.moon : t === 'light' ? ICON.sun : ICON.auto;
  b.setAttribute('aria-label', `Theme: ${t === 'auto' ? 'automatic' : t}`);
}
function applyAlerts() {
  const b = $('#alertBtn');
  b.innerHTML = S.alerts === 'off' ? ICON.bell : ICON.bellOn;
  b.classList.toggle('on', S.alerts !== 'off');
  b.setAttribute('aria-label', `Alerts: ${S.alerts === 'off' ? 'off' : S.alerts === 'mine' ? 'my bets and teams' : 'everything, board included'}`);
  b.title = b.getAttribute('aria-label');
}
async function setAlerts(mode) {
  S.alerts = mode;
  store.set('alerts', mode);
  applyAlerts();
  if (mode !== 'off') {
    unlockAudio();
    chime(true);
    if ('Notification' in window && Notification.permission === 'default') { try { await Notification.requestPermission(); } catch { /* ignore */ } }
  }
  toastText(mode === 'off' ? 'Alerts off.' : mode === 'mine' ? 'Alerts on for your bets and teams.' : 'Alerts on for every line move.');
}

// ------------------------------------------------------------ one click handler for the whole app
document.addEventListener('click', (ev) => {
  const t = ev.target.closest('button, a, [data-open], [data-bet]');
  if (!t) return;
  const d = t.dataset;

  if (d.bet) { // a price: log a bet at that number
    ev.preventDefault(); ev.stopPropagation();
    const [gid, mkt, side, book] = d.bet.split('|');
    openSlip({ gid, mkt, side, book });
    return;
  }
  if (d.tab && t.tagName === 'A') { ev.preventDefault(); setTab(d.tab); return; }
  if (d.open) { ev.preventDefault(); openGame(d.open); return; }
  if (d.week !== undefined && d.week) { openWeek(d.week); return; }
  if (d.mkt) { S.mkt = d.mkt; store.set('mkt', S.mkt); renderBoard(); return; }
  if (d.filter) { S.filter = d.filter; store.set('filter', S.filter); renderBoard(); return; }
  if (d.phbook) { S.phBook = d.phbook; store.set('phBook', S.phBook); renderBoard(); return; }
  if (d.bseg) { S.bseg = d.bseg; store.set('bseg', S.bseg); renderBets(); return; }
  if (d.cm) { S.sheet.chartMkt = d.cm; if (d.cm !== 'ml') S.sheet.tableMkt = d.cm; paintGame(); return; }
  if (d.tm) { S.sheet.tableMkt = d.tm; paintGame(); return; }
  if (d.focus) { S.sheet.focus = S.sheet.focus === d.focus ? null : d.focus; paintGame(); return; }
  if (d.follow) {
    if (S.follow.has(d.follow)) S.follow.delete(d.follow); else S.follow.add(d.follow);
    store.set('follow', [...S.follow]);
    paintGame(); invalidate();
    return;
  }
  if (d.counter) { openCounter(d.counter); return; }
  if (d.books !== undefined) { openBooks(); return; }
  if (d.closesheet !== undefined) { closeSheet(); return; }
  if (d.cbook) { S.sheet.book = d.cbook; paintCounter(); return; }
  if (d.cfav) { S.sheet.fav = d.cfav; paintCounter(); return; }
  if (d.csave !== undefined) { saveCounter(); return; }
  if (d.cdel) {
    const gid = S.sheet.gid;
    api(`/api/manual?gid=${gid}&book=${d.cdel}`, { method: 'DELETE' })
      .then(() => { if (S.mine[gid]) { delete S.mine[gid][d.cdel]; if (!Object.keys(S.mine[gid]).length) delete S.mine[gid]; } repaintMine(gid); openGame(gid); })
      .catch((e) => toastText(e.message));
    return;
  }
  if (d.back) { openGame(d.back); return; }
  if (d.slipBook && S.sheet?.slip) { // a book tile in the slip: use that book and its price
    readSlip();
    const sl = S.sheet.slip, l = sl.legs[0], g = gameById(l?.gid);
    sl.book = d.slipBook;
    if (g && d.slipBook !== 'other') { const f = legFrom(g, l.mkt, l.side, d.slipBook); if (f.odds != null) { l.odds = f.odds; if (f.line != null) l.line = f.line; l.book = d.slipBook; } }
    paintSlip();
    return;
  }
  if (d.savebet !== undefined) { saveBet(); return; }
  if (d.addleg !== undefined) {
    readSlip();
    const l = S.sheet.slip.legs[0];
    if (S.parlay.some((x) => x.gid === l.gid && x.mkt === l.mkt)) { toastText('That game and market is already in the parlay.'); return; }
    S.parlay.push({ ...l });
    toastText(`Added. ${plural(S.parlay.length, 'leg')} in the parlay.`);
    returnFromSlip(S.sheet.returnTo);
    renderTray();
    return;
  }
  if (d.rmleg !== undefined) { readSlip(); S.sheet.slip.legs.splice(Number(d.rmleg), 1); S.parlay = S.sheet.slip.legs.map((l) => ({ ...l })); if (!S.parlay.length) closeSheet(); else paintSlip(); renderTray(); return; }
  if (d.parlayOpen !== undefined) { openSlip({ parlay: true }); return; }
  if (d.parlayClear !== undefined) { S.parlay = []; renderTray(); return; }
  if (d.pick) { const [gid, mkt, side, book] = d.pick.split('|'); openSlip({ gid, mkt, side, book }); return; }
  if (d.newbet !== undefined) { openSlip({}); return; }
  if (d.void) {
    const id = d.void;
    api(`/api/bets/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'void' }) })
      .then(() => toastText('Bet voided. No win or loss.', { label: 'Undo', run: () => api(`/api/bets/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'open' }) }).catch((e) => toastText(e.message)) }))
      .catch((e) => toastText(e.message));
    return;
  }
  if (d.del) {
    // Take it off the screen now; only delete on the server if Undo isn't tapped within 6 seconds.
    const id = d.del;
    const bet = S.bets.find((b) => b.id === id);
    S.bets = S.bets.filter((b) => b.id !== id);
    pendingDeletes.add(id);
    invalidate();
    const timer = setTimeout(() => { pendingDeletes.delete(id); api(`/api/bets/${id}`, { method: 'DELETE' }).catch((e) => toastText(e.message)); }, 6000);
    toastText('Bet deleted.', { label: 'Undo', run: () => { clearTimeout(timer); pendingDeletes.delete(id); if (bet && !S.bets.some((b) => b.id === id)) S.bets = [bet, ...S.bets]; invalidate(); } });
    return;
  }
  if (d.hide) {
    if (S.hidden.has(d.hide)) S.hidden.delete(d.hide); else S.hidden.add(d.hide);
    store.set('hiddenBooks', [...S.hidden]);
    invalidate();
    return;
  }
});

document.addEventListener('input', (ev) => {
  const id = ev.target.id;
  if (id === 'search') { S.query = ev.target.value; renderBoard(); return; }
  if (['tOdds', 'tStake', 'nvA', 'nvB', 'pLegs', 'pStake', 'hPay', 'hStake', 'hOdds'].includes(id)) { updateTools(); return; }
  if (id === 'unitIn') { const v = Number(ev.target.value); if (v > 0) { S.unit = v; store.set('unit', v); } return; }
  if (['slOdds', 'slStake', 'slLine'].includes(id)) { readSlip(); updateSlipCalc(); } // payout math only; never redraw a field mid-typing
});
document.addEventListener('change', (ev) => {
  if (ev.target.id === 'alertSel') setAlerts(ev.target.value);
  if (ev.target.id === 'slBook') { readSlip(); updateSlipCalc(); } // the Open-book link follows the book
  if (ev.target.id === 'pkGame') $('#pkSides').innerHTML = pickerSides(ev.target.value);
});

$('#alertBtn').addEventListener('click', () => setAlerts(S.alerts === 'off' ? 'mine' : S.alerts === 'mine' ? 'all' : 'off'));
$('#themeBtn').addEventListener('click', () => {
  S.theme = S.theme === 'auto' ? 'dark' : S.theme === 'dark' ? 'light' : 'auto';
  store.set('theme', S.theme);
  applyTheme();
});
$('#phoneBtn').addEventListener('click', openPhone);
document.addEventListener('click', (ev) => { if (ev.target.id === 'phoneBtn2') openPhone(); });
$('#dlgClose').addEventListener('click', closeSheet);
$('#dlg').addEventListener('click', (ev) => { if (ev.target === $('#dlg')) closeSheet(); });
$('#dlg').addEventListener('close', () => { if (S.sheet) closeSheet(); });

// Clocks, "3 min ago" labels and the move card's 20-minute window all age without new data.
setInterval(() => { if (S.tab === 'live' && !S.sheet) renderLive(); renderPill(); }, 30000);

// ------------------------------------------------------------ start
applyTheme();
applyAlerts();
route();
connect();
loadMine().then(remergeMine);
loadKeys().then(() => invalidate());
