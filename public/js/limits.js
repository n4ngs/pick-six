'use strict';
/* Pick Six — Play limits (Tools). Optional daily and weekly limits on the total stake you log, off by default
   and stored on this device only. When saving a bet would take you past one, the slip says so plainly and the Save
   button becomes "Save anyway"; a second tap saves. Nothing is ever blocked. My bets shows "This week: $X of your
   $Y limit" while a limit is set. "Take a break" hides Edge Finder's entry on Live and its marks and filter on the
   board until you turn it off or the date you picked has passed (up to 30 days).
   Hooks: renderTools/updateTools (limCard, limPaint), renderBets (limBetsLine), saveBet (limGate), and limBreak()
   checks in renderLive, passes() and pxCell (views.js). */

const LIM_DEF = { day: 0, week: 0, brk: false, until: 0 };
const LIM_MAX_DAYS = 30;
let limCache = null;

function limCfg() {
  if (limCache) return limCache;
  const c = { ...LIM_DEF, ...(store.get('limits', null) || {}) };
  c.day = Number(c.day) > 0 ? Number(c.day) : 0;
  c.week = Number(c.week) > 0 ? Number(c.week) : 0;
  c.brk = !!c.brk;
  c.until = Number(c.until) > 0 ? Number(c.until) : 0;
  return (limCache = c);
}
function limSet(patch) {
  const c = { ...limCfg(), ...patch };
  store.set('limits', c);
  limCache = null;
  limPaint();
  invalidate();
}
// True while a break is on. Called for every price on the board, so it only reads the cached settings.
function limBreak() {
  const c = limCfg();
  return c.brk && (!c.until || Date.now() < c.until);
}

// ------------------------------------------------------------ what's been logged
const limDayStart = (t = Date.now()) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
const limWeekStart = (t = Date.now()) => { const d = new Date(limDayStart(t)); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.getTime(); }; // Monday
function limLogged(since) {
  let sum = 0;
  for (const b of S.bets) {
    if (b.status === 'void') continue;
    const t = Date.parse(b.placed) || b.created || 0;
    if (t >= since) sum += Number(b.stake) || 0;
  }
  return sum;
}
const limMoney = (n) => fmtMoney(Math.round(n * 100) / 100);

// ------------------------------------------------------------ the slip: a calm notice, then "Save anyway"
function limOver(stake) {
  const c = limCfg();
  const out = [];
  if (!(stake > 0)) return out;
  if (c.day) { const to = limLogged(limDayStart()) + stake; if (to > c.day) out.push(`This would take you to ${limMoney(to)} logged today, past your ${limMoney(c.day)} daily limit.`); }
  if (c.week) { const to = limLogged(limWeekStart()) + stake; if (to > c.week) out.push(`This would take you to ${limMoney(to)} logged this week, past your ${limMoney(c.week)} limit.`); }
  return out;
}
// Called by saveBet() after the slip checks out. Returns true to save now.
function limGate() {
  const sl = S.sheet?.slip;
  if (!sl) return true;
  const msgs = limOver(sl.stake);
  if (!msgs.length) { $('#limNote')?.remove(); return true; }
  if ($('#limNote') && sl.limAck === sl.stake) return true; // second tap, same amount: save
  sl.limAck = sl.stake;
  limNotice(msgs);
  return false;
}
function limNotice(msgs) {
  let n = $('#limNote');
  const btns = $('#slBtns');
  if (!btns) return;
  if (!n) { n = document.createElement('p'); n.id = 'limNote'; n.className = 'lim-note'; n.setAttribute('role', 'status'); btns.parentNode.insertBefore(n, btns); }
  n.textContent = msgs.join(' ');
  limSaveLabel();
}
function limSaveLabel() {
  const b = $('#slBtns [data-savebet]');
  if (b && $('#limNote')) b.textContent = 'Save anyway';
}
// Typing a new stake redraws the slip's buttons (updateSlipCalc); keep or clear the notice to match.
function limSlipSync() {
  const sl = S.sheet?.slip;
  if (!sl || !$('#limNote')) return;
  if (sl.stake !== sl.limAck) { $('#limNote').remove(); sl.limAck = null; return; }
  limSaveLabel();
}

// ------------------------------------------------------------ My bets
function limBetsLine() {
  const c = limCfg();
  if (!c.day && !c.week) return '';
  const parts = [];
  if (c.day) parts.push(`Today: <b class="num">${esc(limMoney(limLogged(limDayStart())))}</b> of your ${esc(limMoney(c.day))} limit`);
  if (c.week) parts.push(`This week: <b class="num">${esc(limMoney(limLogged(limWeekStart())))}</b> of your ${esc(limMoney(c.week))} limit`);
  return `<div class="lim-line"><span>${parts.join('<span class="lim-sep" aria-hidden="true"> · </span>')}</span><button type="button" class="k-link" data-lim-settings aria-label="Change play limits in Tools">Limits</button></div>`;
}

// ------------------------------------------------------------ the Tools card
const limDateStr = (t) => { const d = new Date(t); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
function limCard() {
  const today = limDateStr(Date.now());
  const max = limDateStr(Date.now() + LIM_MAX_DAYS * 864e5);
  return `<div class="card tool lim" id="limTool">
    <h3>Play limits</h3>
    <p>Optional limits on how much you log. If a bet would take you past one, the slip mentions it before you save, and you can still save. Leave a box empty for no limit. Saved on this device.</p>
    <div class="fgrid">
      <label class="fld">Daily limit ($)<input class="inp" id="limDay" inputmode="decimal" autocomplete="off" placeholder="None"></label>
      <label class="fld">Weekly limit ($)<input class="inp" id="limWeek" inputmode="decimal" autocomplete="off" placeholder="None"></label>
    </div>
    <div class="lim-now" id="limNow" aria-live="polite"></div>
    <button type="button" class="lim-sw" role="switch" id="limBrk" aria-checked="false" aria-describedby="limBrkSub" data-lim-break><span><b>Take a break</b><span id="limBrkSub">Hides Edge Finder on Live and its marks on the board.</span></span><i aria-hidden="true"></i></button>
    <div class="lim-until" id="limUntilBox">
      <label class="fld">Until (optional)<input class="inp" id="limUntil" type="date" min="${today}" max="${max}"></label>
      <p class="lim-until-s" id="limUntilS"></p>
    </div>
  </div>`;
}
function limPaint() {
  const card = $('#limTool');
  if (!card) return;
  let c = limCfg();
  if (c.brk && c.until && Date.now() >= c.until) { store.set('limits', { ...c, brk: false, until: 0 }); limCache = null; c = limCfg(); } // the break ran its course
  const set = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
  set('#limDay', c.day ? String(c.day) : '');
  set('#limWeek', c.week ? String(c.week) : '');
  $('#limNow').innerHTML = `Logged today <b class="num">${esc(limMoney(limLogged(limDayStart())))}</b> · this week <b class="num">${esc(limMoney(limLogged(limWeekStart())))}</b> <span class="faint">(weeks start Monday)</span>`;
  const on = limBreak();
  $('#limBrk').setAttribute('aria-checked', String(on));
  $('#limUntilBox').hidden = !on;
  set('#limUntil', c.until ? limDateStr(c.until - 1) : '');
  $('#limUntilS').textContent = on ? (c.until ? `On through ${new Date(c.until - 1).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}. Turn it off any time.` : 'On until you turn it off.') : '';
}

// ------------------------------------------------------------ wiring
document.addEventListener('input', (ev) => {
  const id = ev.target.id;
  if (id === 'limDay' || id === 'limWeek') {
    const raw = String(ev.target.value).replace(/[^\d.]/g, '');
    const v = raw === '' ? 0 : Number(raw);
    if (Number.isFinite(v)) limSet({ [id === 'limDay' ? 'day' : 'week']: v > 0 ? v : 0 });
    return;
  }
  if (id === 'slStake' || id === 'slOdds' || id === 'slLine') setTimeout(limSlipSync, 0); // after the slip redraws its buttons
});
document.addEventListener('change', (ev) => {
  if (ev.target.id !== 'limUntil') return;
  const v = ev.target.value; // YYYY-MM-DD, local
  if (!v) { limSet({ until: 0 }); return; }
  const [y, m, d] = v.split('-').map(Number);
  const end = new Date(y, m - 1, d + 1).getTime(); // through the end of that day
  const cap = limDayStart() + (LIM_MAX_DAYS + 1) * 864e5;
  limSet({ until: clamp(end, limDayStart() + 864e5, cap) });
});
document.addEventListener('click', (ev) => {
  const t = ev.target.closest('[data-lim-break], [data-lim-settings]');
  if (!t) return;
  if (t.dataset.limBreak !== undefined) {
    const on = limBreak();
    limSet(on ? { brk: false, until: 0 } : { brk: true, until: 0 });
    toastText(on ? 'Break over. Edge Finder is back.' : 'Break on. Edge Finder is hidden until you turn this off.');
    return;
  }
  ev.preventDefault();
  if (S.sheet) closeSheet();
  setTab('tools');
  requestAnimationFrame(() => $('#limTool')?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }));
});
window.addEventListener('storage', (ev) => { if (ev.key === 'ps.limits') { limCache = null; invalidate(); } }); // another tab changed them
