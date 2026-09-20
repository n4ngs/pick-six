'use strict';
/* Pick Six — your private bet log. Each device has its own log (a random id in a secure cookie; nothing to
   sign up for). This card links a second device to the same log with a 10-minute code, and lets the app's owner
   claim bets saved before logs were private. */

let acctMe = null;       // { bets, claimable } from /api/me
let acctLink = null;     // { code, exp } while a link code is showing
let acctTimer = 0;

function acctCard() {
  return `<div class="card tool acct" id="acctTool">
    <h3>Your bets</h3>
    <p>Your bet log is private: only this device sees it. To see the same bets on your phone and your computer, link them.</p>
    <div class="acct-link" id="acctLinkBox"></div>
    <div class="acct-join">
      <label class="fld">Have a code from your other device?<input class="inp acct-code" id="acctJoinCode" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="8-character code" maxlength="9"></label>
      <button class="btn ghost" type="button" data-acct-join>Link this device</button>
    </div>
    <div class="err" id="acctErr" role="alert"></div>
    <div id="acctClaim"></div>
  </div>`;
}

function acctPaint() {
  const box = $('#acctLinkBox');
  if (!box) return;
  if (!acctMe) acctLoad();
  const left = acctLink ? Math.max(0, Math.round((acctLink.exp - Date.now()) / 1000)) : 0;
  if (acctLink && left <= 0) acctLink = null;
  const html = acctLink
    ? `<div class="acct-code-show"><span>On your other device, open Tools → Your bets and enter</span><b class="num">${esc(acctLink.code.slice(0, 4))} ${esc(acctLink.code.slice(4))}</b><span>Good for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} · one use</span></div>`
    : `<button class="btn" type="button" data-acct-link>Link another device</button>`;
  if (box.dataset.key !== html) { box.innerHTML = html; box.dataset.key = html; }
  const c = $('#acctClaim');
  const claim = acctMe?.claimable
    ? `<div class="acct-claim"><b>${plural(acctMe.claimable, 'bet')} from before logs were private</b><p>They're hidden from everyone. If you run this app, enter your owner code to move them into your log; delete any that aren't yours.</p>
       <div class="acct-join"><label class="fld">Owner code<input class="inp" id="acctOwner" type="password" autocomplete="off" spellcheck="false"></label><button class="btn ghost" type="button" data-acct-claim>Claim</button></div></div>`
    : '';
  if (c.dataset.key !== claim) { c.innerHTML = claim; c.dataset.key = claim; }
}
async function acctLoad() {
  acctMe = { bets: 0, claimable: 0 };
  try { acctMe = await api('/api/me'); } catch { /* offline: the card still works for linking */ }
  acctPaint();
}
function acctErr(msg) { const e = $('#acctErr'); if (e) e.textContent = msg || ''; }

document.addEventListener('click', async (ev) => {
  if (ev.target.closest('[data-acct-link]')) {
    acctErr('');
    try { acctLink = await api('/api/me/link', { method: 'POST', body: '{}' }); } catch (e) { acctErr(e.message); return; }
    clearInterval(acctTimer);
    acctTimer = setInterval(() => { acctPaint(); if (!acctLink) clearInterval(acctTimer); }, 1000);
    acctPaint();
    return;
  }
  if (ev.target.closest('[data-acct-join]')) {
    const code = String($('#acctJoinCode')?.value || '').replace(/\s/g, '');
    if (code.length < 8) { acctErr('Enter the 8-character code from your other device.'); return; }
    acctErr('');
    try {
      const r = await api('/api/me/join', { method: 'POST', body: JSON.stringify({ code }) });
      $('#acctJoinCode').value = '';
      acctMe = null;
      toastText(`Linked. This device now shares that log${r.moved ? `, and brought ${plural(r.moved, 'bet')} with it` : ''}.`);
      acctPaint();
    } catch (e) { acctErr(e.message); }
    return;
  }
  if (ev.target.closest('[data-acct-claim]')) {
    const code = String($('#acctOwner')?.value || '').trim();
    if (!code) { acctErr('Enter the owner code.'); return; }
    acctErr('');
    try {
      const r = await api('/api/me/claim', { method: 'POST', body: JSON.stringify({ code }) });
      acctMe = null;
      toastText(r.claimed ? `Moved ${plural(r.claimed, 'bet')} into your log. Delete any that aren't yours in My bets.` : 'Nothing left to claim.');
      acctPaint();
    } catch (e) { acctErr(e.message); }
  }
});
