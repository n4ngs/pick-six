'use strict';
/* Pick Six — bet sizing with the Kelly criterion, tuned by you.
   Full Kelly, as a share of bankroll: f* = (b·p − q) / b, where b = decimal odds − 1, p = the chance to win and
   q = the chance to lose (a push returns the stake, so it sits out). You pick how much of that to bet (a fraction
   of Kelly), your bankroll, a per-bet cap, the smallest edge worth showing and how stakes round. Edge Finder, the
   bet slip and the calculator here all size from these settings. Stored on this device only. */

const KELLY_DEF = { bankroll: 0, frac: 0.25, capPct: 2, minEdge: 1, round: 5 };
const KELLY_PRESETS = [[0.125, '⅛'], [0.25, '¼'], [0.5, '½']]; // no one-tap full Kelly
const KELLY_ROUNDS = [1, 5, 10, 25];

function kellyCfg() {
  const c = { ...KELLY_DEF, ...(store.get('kelly', null) || {}) };
  c.bankroll = Number(c.bankroll) > 0 ? Number(c.bankroll) : 0; // never invented: nothing is sized in dollars until you enter one
  c.frac = clamp(Number(c.frac) || KELLY_DEF.frac, 0.05, 0.5);
  c.capPct = clamp(Number(c.capPct) || KELLY_DEF.capPct, 0.5, 25);
  c.minEdge = clamp(Number(c.minEdge) || KELLY_DEF.minEdge, 0.5, 10);
  c.round = KELLY_ROUNDS.includes(Number(c.round)) ? Number(c.round) : KELLY_DEF.round;
  return c;
}
function kellySet(patch) {
  store.set('kelly', { ...kellyCfg(), ...patch });
  kellyPaint();
  invalidate(); // Edge Finder and any open sheet re-size on the next frame
}
// "¼ Kelly", or "30% Kelly" for a custom fraction.
function kellyName(f = kellyCfg().frac) {
  const p = KELLY_PRESETS.find(([v]) => Math.abs(v - f) < 0.001);
  return p ? `${p[1]} Kelly` : `${Math.round(f * 100)}% Kelly`;
}
// The smallest edge the user wants surfaced (Edge Finder filters on this).
const kellyMinEdge = () => kellyCfg().minEdge / 100;

// Stake for one bet. p = chance to win, odds = American, push = chance of a push.
// Returns null for unusable input, or { full, pct, dollars, capped, edge } at the user's settings.
function kellyStake(p, odds, push = 0, c = kellyCfg()) {
  const d = dec(odds);
  if (!(p > 0 && p < 1) || d == null || d <= 1) return null;
  const b = d - 1, q = Math.max(0, 1 - p - push);
  const edge = p * d + push - 1;
  const full = (b * p - q) / b;
  if (!(full > 0)) return { full: 0, pct: 0, dollars: 0, capped: false, edge };
  const want = full * c.frac;
  const pct = Math.min(want, c.capPct / 100);
  const dollars = c.bankroll ? Math.max(c.round, Math.round((pct * c.bankroll) / c.round) * c.round) : null;
  return { full, pct, dollars, capped: want > c.capPct / 100, edge };
}
// "$120 · 1.2%" for rows and chips.
const kellyShort = (k) => (k && k.pct > 0 ? (k.dollars ? `${fmtMoney(k.dollars)} · ${(k.pct * 100).toFixed(1)}%` : `${(k.pct * 100).toFixed(1)}% of bankroll`) : '');

// ------------------------------------------------------------ the Tools card
// Rendered inside the Tools tab (views.js renderTools calls kellyCard once, then kellyPaint on every update).
function kellyCard() {
  return `<div class="card tool kelly" id="kellyTool">
    <h3>Bet sizing · Kelly</h3>
    <p>Kelly is a formula that sizes a bet from a win chance and a price. It’s only as good as the win chance: overestimate it a little and Kelly bets too much. Most people who use it bet a small fraction of it, or nothing. Nothing is sized in dollars until you enter a bankroll.</p>
    <div class="fgrid">
      <label class="fld">Bankroll ($)<input class="inp" id="kBank" inputmode="decimal" autocomplete="off" placeholder="Not set"></label>
      <label class="fld">Round stakes to<select class="inp" id="kRound">${KELLY_ROUNDS.map((r) => `<option value="${r}">$${r}</option>`).join('')}</select></label>
    </div>
    <div class="k-fld">
      <div class="k-h"><span>How much of Kelly</span><b class="num" id="kFracV"></b></div>
      <div class="k-presets" role="group" aria-label="Kelly fraction presets">${KELLY_PRESETS.map(([v, l]) => `<button type="button" class="chip" data-kelly-frac="${v}">${l}</button>`).join('')}</div>
      <input class="k-range" id="kFrac" type="range" min="5" max="50" step="5" aria-label="Fraction of Kelly, percent">
    </div>
    <div class="k-fld">
      <div class="k-h"><span>Most on one bet</span><b class="num" id="kCapV"></b></div>
      <input class="k-range" id="kCap" type="range" min="0.5" max="10" step="0.5" aria-label="Largest bet, percent of bankroll">
    </div>
    <div class="k-fld">
      <div class="k-h"><span>Smallest edge to show</span><b class="num" id="kMinV"></b></div>
      <input class="k-range" id="kMin" type="range" min="0.5" max="5" step="0.5" aria-label="Smallest edge Edge Finder shows, percent">
    </div>
    <div class="k-ex" id="kEx" aria-live="polite"></div>
    <h4 class="k-sub">Try a bet</h4>
    <div class="fgrid">
      <label class="fld">Odds<input class="inp" id="kOdds" inputmode="text" autocomplete="off" value="-110"></label>
      <label class="fld">Your win chance (%)<input class="inp" id="kWin" inputmode="decimal" autocomplete="off" value="55"></label>
    </div>
    <div class="out" id="kOut"></div>
    <p class="note">Stakes are suggestions, not advice. They're only as good as the win chance behind them; in Edge Finder that's the sharp fair price with the vig removed. Saved on this device.</p>
  </div>`;
}
function kellyPaint() {
  const card = $('#kellyTool');
  if (!card) return;
  const c = kellyCfg();
  const set = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v; };
  set('#kBank', c.bankroll ? String(c.bankroll) : '');
  set('#kRound', String(c.round));
  set('#kFrac', String(Math.round(c.frac * 100)));
  set('#kCap', String(c.capPct));
  set('#kMin', String(c.minEdge));
  $('#kFracV').textContent = kellyName(c.frac);
  $('#kCapV').textContent = c.bankroll ? `${c.capPct}% · ${fmtMoney(Math.round((c.capPct / 100) * c.bankroll))}` : `${c.capPct}% of bankroll`;
  $('#kMinV').textContent = `+${c.minEdge}%`;
  for (const b of $$('[data-kelly-frac]', card)) b.setAttribute('aria-pressed', String(Math.abs(Number(b.dataset.kellyFrac) - c.frac) < 0.001));
  // A worked example at the current settings: a +4% edge at −110.
  const ex = kellyStake(1.04 / dec(-110), -110, 0, c);
  $('#kEx').innerHTML = ex ? `At these settings, a <b>+4% estimate at ${fmtOdds(-110)}</b> would size to ${ex.dollars ? `<b class="num">${fmtMoney(ex.dollars)}</b>, ` : ''}${(ex.pct * 100).toFixed(1)}% of your bankroll${ex.capped ? ' (held to your cap)' : ''}. If the real edge is 0%, Kelly’s answer is $0.` : '';
  kellyCalc();
}
function kellyCalc() {
  const out = $('#kOut');
  if (!out) return;
  const odds = Number(String($('#kOdds').value).replace(MINUS, '-').replace(/[^\d.+-]/g, ''));
  const win = Number(String($('#kWin').value).replace(/[^\d.]/g, '')) / 100;
  if (!(Math.abs(odds) >= 100) || !(win > 0 && win < 1)) { out.innerHTML = '<div><div class="k">Enter odds like −110 and a win chance between 1 and 99</div></div>'; return; }
  const k = kellyStake(win, odds);
  const cell = (label, v) => `<div><div class="k">${label}</div><div class="v num">${v}</div></div>`;
  out.innerHTML = !k || !(k.pct > 0)
    ? cell('Edge', `${(k ? k.edge * 100 : 0).toFixed(1)}%`) + cell('Kelly sizing', '$0') + cell('Break-even', fmtPct(imp(odds), 1))
    : cell('Edge', `+${(k.edge * 100).toFixed(1)}%`) + cell(kellyName(), k.dollars ? fmtMoney(k.dollars) : '—') + cell('Of bankroll', `${(k.pct * 100).toFixed(1)}%${k.capped ? ' cap' : ''}`);
}

// ------------------------------------------------------------ wiring
document.addEventListener('input', (ev) => {
  const id = ev.target.id;
  if (id === 'kBank') { const v = Number(String(ev.target.value).replace(/[^\d.]/g, '')); if (v >= 10) kellySet({ bankroll: v }); return; }
  if (id === 'kFrac') { kellySet({ frac: Number(ev.target.value) / 100 }); return; }
  if (id === 'kCap') { kellySet({ capPct: Number(ev.target.value) }); return; }
  if (id === 'kMin') { kellySet({ minEdge: Number(ev.target.value) }); return; }
  if (id === 'kOdds' || id === 'kWin') kellyCalc();
});
document.addEventListener('change', (ev) => { if (ev.target.id === 'kRound') kellySet({ round: Number(ev.target.value) }); });
document.addEventListener('click', (ev) => {
  const f = ev.target.closest('[data-kelly-frac]');
  if (f) { kellySet({ frac: Number(f.dataset.kellyFrac) }); return; }
  const s = ev.target.closest('[data-kelly-settings]');
  if (s) { ev.preventDefault(); if (S.sheet) closeSheet(); setTab('tools'); requestAnimationFrame(() => $('#kellyTool')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); return; }
  const u = ev.target.closest('[data-kelly-use]');
  if (u && S.sheet?.slip) { S.sheet.slip.stake = Number(u.dataset.kellyUse); paintSlip(); }
});
