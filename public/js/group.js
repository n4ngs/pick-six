'use strict';
/* Pick Six — the group: share links on the owner's side, a name and a plain explanation on a friend's.

   A friend never types a code. The owner makes one link per person, sends it, and opening it lets that phone
   in for good. Turning a link off locks out only the phones that used it.
 */

let grpLinks = null;    // { base, links: [] } from /api/invites
let grpPeople = null;   // [{ uid, name, via, last, bets }] from /api/group

const isOwner = () => S.me?.role !== 'guest';
const ownerLabel = () => (S.me?.owner ? `${S.me.owner}` : 'the person who runs this board');
const grpShareUrl = (t) => `${grpLinks?.base || location.origin}/j/${t}`;

// ------------------------------------------------------------ the Group tab (the owner's own screen)
/* One screen for the whole board: what the group has running right now, each person's log, and the links
   that let them in. Everything here is read-only — the owner watches, they don't touch anyone's tickets. */
/* ------------------------------------------------------------------ board health

   An admin's first question is not "who is on the board", it is "is the board actually working". The
   server has always known — /api/health carries every feed's last success, its consecutive failures and
   whether it is currently backing off — and none of it had anywhere to go. A feed can quietly stop and
   the only symptom is numbers that look slightly old, which is the hardest kind of failure to notice.

   Colour follows the house rule: green means a ticket of yours is winning and nothing else, so a healthy
   feed is just ink. Trouble takes the accent. */
const GRP_FEEDS = [
  ['site.api.espn.com', 'ESPN', 'scores, schedule, injuries'],
  ['api.actionnetwork.com', 'Action Network', 'live odds and splits'],
  ['data.vsin.com', 'VSiN', 'the Vegas windows'],
  ['guest.api.arcadia.pinnacle.com', 'Pinnacle', 'the sharp line'],
  ['api.open-meteo.com', 'Weather', 'wind and rain'],
];
const GRP_QUIET = 10 * 60e3;   // a feed with nothing new for this long is worth a second look
let grpHealth = null;

function grpLoadHealth() {
  if (typeof api !== 'function') return Promise.resolve();
  return api('/api/health')
    .then((h) => { grpHealth = h; })
    .catch(() => { grpHealth = { unreachable: true }; });
}

function grpFeedRow(host, name, what) {
  const src = grpHealth?.sources?.[host];
  if (!src) return `<div class="grp-feed"><b>${esc(name)}</b><span class="grp-feed-w">${esc(what)}</span><span class="grp-feed-s quiet">not called yet</span></div>`;
  const ago = src.lastOk ? serverNow() - src.lastOk : null;
  const bad = src.pausedFor > 0 || src.fails > 0;
  const state = src.pausedFor > 0
    ? `backing off ${vasAgoish(src.pausedFor)}`
    : src.fails > 0
      ? `${plural(src.fails, 'failed try', 'failed tries')}`
      : ago == null ? 'no answer yet'
        : ago > GRP_QUIET ? `quiet ${vasAgoish(ago)}`
          : `ok · ${vasAgoish(ago)} ago`;
  const cls = bad ? 'bad' : ago != null && ago > GRP_QUIET ? 'quiet' : '';
  return `<div class="grp-feed"><b>${esc(name)}</b><span class="grp-feed-w">${esc(what)}</span><span class="grp-feed-s ${cls}">${esc(state)}</span></div>`;
}
// A short duration, without pulling in the VAS file just for this.
function vasAgoish(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 90) return `${s}s`;
  const m = Math.round(s / 60);
  return m < 90 ? `${m} min` : `${Math.round(m / 60)}h`;
}

function grpHealthHTML() {
  if (!grpHealth) return '<div class="card grp-health"><p class="grp-lede">Checking the feeds…</p></div>';
  if (grpHealth.unreachable) return '<div class="card grp-health"><p class="grp-lede bad">Could not reach the server for a health check.</p></div>';
  const w = (grpHealth.weeks || [])[0];
  const here = grpHealth.clients ?? 0;
  const bad = GRP_FEEDS.filter(([h]) => { const x = grpHealth.sources?.[h]; return x && (x.fails > 0 || x.pausedFor > 0); }).length;
  return `<div class="card grp-health">
    <div class="grp-health-h">
      <span>${esc(bad ? `${plural(bad, 'feed')} having trouble` : 'Every feed answering')}</span>
      <span class="grp-health-n">${esc(plural(here, 'phone'))} connected${w ? ` · ${esc(`${w.matched}/${w.games} games matched`)}` : ''}</span>
    </div>
    ${GRP_FEEDS.map(([h, n, wt]) => grpFeedRow(h, n, wt)).join('')}
  </div>`;
}

/* ------------------------------------------------------------ the owner's ledger

   Everything on the board, in one list, newest first. /api/group paints the running summary; this is the
   full log including settled bets, which is what "I run this board" actually means. Server-side it is
   owner-only and answers 403 to anyone else.

   Guests are told, the first time they open the app, that the person who runs the board sees their
   tickets. That disclosure is what makes this fair, and it stays. */
let grpAct = null;

function grpLoadActivity() {
  if (typeof api !== 'function') return Promise.resolve();
  return api('/api/group/activity')
    .then((d) => { grpAct = d; })
    .catch(() => { grpAct = { failed: true }; });
}
const grpActOf = (uid) => (grpAct?.people || []).find((x) => x.uid === uid) || null;

// Closing line value, the one number that means something at this sample size.
function grpClvBadge(P) {
  if (!P || !P.clvN) return '';
  const avg = P.clvAvg;
  const cls = avg > 0.05 ? 'w' : avg < -0.05 ? 'l' : '';
  return `<span class="grp-clv ${cls}">CLV ${avg > 0 ? '+' : ''}${avg.toFixed(2)}<small>${Math.round((P.clvBeat || 0) * 100)}% beat · ${P.clvN}</small></span>`;
}

/* Exact and relative, both. "2h ago" is how you read a log at a glance; the wall-clock stamp is what
   you need when you are reconstructing what somebody did and when. */
function grpStamp(iso, ms) {
  const t = iso ? Date.parse(iso) : ms;
  if (!t) return '';
  const day = dayLabel(new Date(t).toISOString());
  return `${day} ${timeLabel(new Date(t).toISOString())} · ${ago(t)}`;
}
/* "home -2.5" is what the record holds; "KC -2.5" is what a person reading a log needs. The game is
   usually still in memory, so resolve the side to a team when we can and fall back to the stored text
   when we cannot — an old bet whose week is no longer loaded still has to render. */
function grpPickTxt(b) {
  const parts = (b.legs || []).map((l) => {
    const g = typeof gameById === 'function' ? gameById(l.gid) : null;
    const who = l.team
      || (g && (l.side === 'home' ? g.home?.abbr : l.side === 'away' ? g.away?.abbr : null))
      || (l.side === 'over' ? 'Over' : l.side === 'under' ? 'Under' : l.side || '');
    const num = l.line != null ? (l.mkt === 't' || l.mkt === 'h1t' ? fmtTot(l.line) : fmtPts(l.line)) : '';
    return `${who} ${num} ${fmtOdds(l.odds)}`.replace(/\s+/g, ' ').trim();
  });
  return parts.join(' + ') || grpLegs(b);
}
function grpLedgerRow(b) {
  const clv = (b.legs || []).map((l) => l.clv).find((c) => c && Number.isFinite(c.pts));
  const st = b.status === 'won' ? 'w' : b.status === 'lost' ? 'l' : '';
  const result = b.status === 'open'
    ? '<small>open</small>'
    : `<b class="${st}">${esc(fmtMoney(b.net, true))}</b><small>${esc(b.status)}${b.settled ? ` ${esc(ago(b.settled))}` : ''}</small>`;
  return `<div class="grp-led" data-grp-person="${esc(b.uid)}">
    <span class="grp-led-w">${esc(b.name)}<small>${esc(grpStamp(b.placed, b.created))}</small></span>
    <span class="grp-led-p">${esc(grpPickTxt(b))}<small>${esc(b.legs.length > 1 ? `${plural(b.legs.length, 'leg')} parlay` : '')}${esc(b.note ? `${b.legs.length > 1 ? ' · ' : ''}\u201c${b.note}\u201d` : '')}</small></span>
    <span class="grp-led-s">${esc(fmtMoney(b.stake))}<small>${esc(b.book || 'no book')} ${esc(fmtOdds(b.odds))}</small></span>
    <span class="grp-led-r">${result}</span>
    <span class="grp-led-c">${clv ? `${clv.pts > 0 ? '+' : ''}${clv.pts}` : '—'}</span>
  </div>`;
}

function grpLedgerHTML() {
  if (!grpAct) return '<div class="card grp-health"><p class="grp-lede">Loading the log…</p></div>';
  if (grpAct.failed) return '<div class="card grp-health"><p class="grp-lede bad">Could not load the activity log.</p></div>';
  const rows = grpAct.bets || [];
  if (!rows.length) {
    return '<div class="card grp-health"><p class="grp-lede">No tracked bets on the board yet. Everything anyone logs lands here, settled ones included.</p></div>';
  }
  const shown = rows.slice(0, 200);
  return `<div class="card grp-ledger">
    <div class="grp-health-h">
      <span>Everyone&rsquo;s bets</span>
      <span class="grp-health-n">${esc(plural(rows.length, 'bet'))}${grpAct.capped ? ` of ${grpAct.betsTotal}` : ''} · tap one for that person&rsquo;s log</span>
    </div>
    <div class="grp-led-h"><span>Who</span><span>Pick</span><span>Risk</span><span>Result</span><span>CLV</span></div>
    ${shown.map(grpLedgerRow).join('')}
    ${rows.length > shown.length ? `<p class="grp-fine" style="padding:12px 16px">Showing the newest ${shown.length}.</p>` : ''}
  </div>`;
}

function renderAdmin() {
  const body = $('#adminBody');
  if (!body) return;
  if (!grpPeople && !grpLoading) { grpLoading = Promise.all([grpLoadGroup(), grpLoadLinks(), grpLoadHealth(), grpLoadActivity()]).finally(() => { grpLoading = null; renderAdmin(); }); }
  const P = grpPeople || [];
  const open = P.reduce((n, x) => n + x.open.length, 0);
  const atRisk = P.reduce((n, x) => n + x.open.reduce((t, b) => t + (b.stake || 0), 0), 0);
  const net = P.reduce((n, x) => n + (x.net || 0), 0);
  const here = P.filter((x) => x.last && serverNow() - x.last < 15 * 60e3).length;
  $('#adminSub').textContent = `${plural(P.length, 'person', 'people')} · ${plural(open, 'open ticket')}${here ? ` · ${here} here now` : ''}`;
  body.innerHTML = `
    <div class="grp-sum">
      ${grpStat('On the board', String(P.length), here ? `${here} open right now` : 'nobody on right now')}
      ${grpStat('Open tickets', String(open), open ? `${fmtMoney(atRisk)} at risk` : 'nothing running')}
      ${grpStat('Group net', fmtMoney(net, true), 'settled bets only', net > 0 ? 'w' : net < 0 ? 'l' : '')}
    </div>
    <div class="sec-h" style="margin-top:28px"><h2>Board health</h2><span class="m">What the app is reading right now</span></div>
    ${grpHealthHTML()}
    <div class="sec-h" style="margin-top:28px"><h2>People</h2><span class="m">${P.length ? 'Tap a name for their log' : ''}</span></div>
    <div class="card grp-list" id="grpPeople"></div>
    <div class="sec-h" style="margin-top:28px"><h2>Everything logged</h2><span class="m">Every tracked bet on this board, settled included</span></div>
    ${grpLedgerHTML()}
    <div class="sec-h" style="margin-top:28px"><h2>Share links</h2><span class="m">One per person</span></div>
    <div class="card grp-share">
      <p class="grp-lede">Make a link and send it. They tap it once and they're in — no code to type. Turn a link off and only the phones that used it are out.</p>
      <div class="acct-join">
        <label class="fld">Who's it for?<input class="inp" id="grpLabel" autocomplete="off" placeholder="e.g. Mike" maxlength="40"></label>
        <button class="btn" type="button" data-grp-make>Make a link</button>
      </div>
      <div class="err" id="grpErr" role="alert"></div>
      <div id="grpLinkList"></div>
    </div>
    <p class="grp-fine">Your own tickets stay in My bets. Nobody here can see them — guests only ever see their own.</p>`;
  grpPaint();
}
/* What the summary cannot say: whether they are any good, how often they play, and where they are now.
   Only rendered when there is something real to report — an empty strip under every name is clutter. */
function grpAnalyticsHTML(uid) {
  const P = grpActOf(uid);
  if (!P || (!P.clvN && !P.n)) return '';
  const bits = [];
  if (P.clvN) bits.push(grpClvBadge(P));
  if (P.n) bits.push(`<span class="grp-a">${esc(P.perWeek >= 0.1 ? `${P.perWeek.toFixed(1)} bets a week` : 'rarely bets')}</span>`);
  if (P.medStake) bits.push(`<span class="grp-a">typical ${esc(fmtMoney(P.medStake))}${P.maxStake && P.maxStake > P.medStake ? ` · biggest ${esc(fmtMoney(P.maxStake))}` : ''}</span>`);
  if (P.streak >= 2 && P.streakKind) bits.push(`<span class="grp-a">${P.streak} ${esc(P.streakKind === 'won' ? 'in a row' : 'losses running')}</span>`);
  if (P.lastBet) bits.push(`<span class="grp-a">last bet ${esc(ago(P.lastBet))}</span>`);
  if (P.last) bits.push(`<span class="grp-a">${esc(serverNow() - P.last < 10 * 60e3 ? 'on the board now' : `last open ${ago(P.last)}`)}</span>`);
  if (P.first) bits.push(`<span class="grp-a">joined ${esc(ago(P.first))}${P.via ? ` via ${esc(P.via)}` : ''}</span>`);
  return bits.length ? `<div class="grp-arow">${bits.join('')}</div>` : '';
}
const grpStat = (k, v, sub, cls = '') => `<div class="grp-stat"><span class="grp-stat-k">${esc(k)}</span><b class="${cls}">${esc(v)}</b><span class="grp-stat-s">${esc(sub)}</span></div>`;

// A guest's own card: their name, and the truth about who can see what.
function grpGuestCard() {
  if (isOwner()) return '';
  return `<div class="card tool grp" id="grpGuest">
    <h3>You on this board</h3>
    <p>Set the name the board shows next to your tickets.</p>
    <div class="acct-join">
      <label class="fld">Your name here<input class="inp" id="grpName" autocomplete="off" maxlength="24" value="${esc(S.me?.name || '')}"></label>
      <button class="btn ghost" type="button" data-grp-name>Save</button>
    </div>
    <div class="err" id="grpErr" role="alert"></div>
  </div>`;
}

function grpPaint() {
  const list = $('#grpLinkList');
  if (list) {
    const rows = (grpLinks?.links || []).map((l) => `<div class="grp-link">
      <div class="grp-link-m"><b>${esc(l.label)}</b><span>${l.uses ? `opened ${plural(l.uses, 'time')}${l.last ? ` · last ${ago(l.last)}` : ''}` : 'not opened yet'}</span></div>
      <div class="grp-link-go">
        <button type="button" class="btn ghost sm" data-grp-copy="${esc(l.token)}">Copy link</button>
        <button type="button" class="btn ghost sm" data-grp-qr="${esc(l.token)}">QR</button>
        <button type="button" class="lg" data-grp-revoke="${esc(l.id)}" aria-label="${esc(`Turn off ${l.label}'s link`)}">Turn off</button>
      </div></div>`).join('');
    const html = rows || '<p class="grp-none">No links yet. Make one above and send it.</p>';
    if (list.dataset.key !== html) { list.innerHTML = html; list.dataset.key = html; }
  }
  const box = $('#grpPeople');
  if (box) {
    const html = (grpPeople || []).length ? grpPeople.map(grpPersonHTML).join('') : '<p class="grp-none">Nobody has opened a link yet. Make one below and send it.</p>';
    if (box.dataset.key !== html) { box.innerHTML = html; box.dataset.key = html; }
  }
}

// One person, at a glance: what they have running and how they've done.
function grpPersonHTML(P) {
  const done = P.won + P.lost;
  const roi = P.risk ? (P.net / P.risk) * 100 : null;
  return `<button type="button" class="grp-p" data-grp-person="${esc(P.uid)}">
    <span class="grp-p-n">${esc(P.name || 'Someone')}${P.via ? `<small>${esc(P.via)}${P.last ? ` · ${esc(ago(P.last))}` : ''}</small>` : ''}</span>
    <span class="grp-p-o">${P.open.length ? `${P.open.length} open<small>${esc(fmtMoney(P.open.reduce((t, b) => t + (b.stake || 0), 0)))} at risk</small>` : '<small>nothing open</small>'}</span>
    <span class="grp-p-r">${done ? `<b class="${P.net > 0 ? 'w' : P.net < 0 ? 'l' : ''}">${esc(fmtMoney(P.net, true))}</b><small>${P.won}-${P.lost}${roi != null ? ` · ${roi > 0 ? '+' : ''}${roi.toFixed(0)}%` : ''}</small>` : '<small>no results yet</small>'}</span>
    <span class="grp-p-c">${ICON.chev}</span>
  </button>
  ${grpAnalyticsHTML(P.uid)}`;
}

// Their full log, newest first. Read-only.
async function grpPersonSheet(uid) {
  const P = (grpPeople || []).find((x) => x.uid === uid);
  S.sheet = { kind: 'person', uid };
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">${esc(P?.name || 'Someone')}</h2><div class="empty"><b>Loading their log…</b></div>`;
  showSheet('person', true);
  let d = null;
  try { d = await api(`/api/group/${uid}`); } catch (e) { $('#dlgBody').innerHTML = `<h2 id="dlgTitle">Couldn't load that</h2><p class="lede">${esc(e.message)}</p>`; return; }
  if (S.sheet?.kind !== 'person' || S.sheet.uid !== uid) return;
  const open = d.bets.filter((b) => b.status === 'open');
  const done = d.bets.filter((b) => b.status !== 'open');
  const row = (b) => `<div class="grp-b">
    <span class="grp-b-m">${esc(grpLegs(b))}${b.book ? `<small>${esc(bookName(b.book))}</small>` : ''}</span>
    <span class="grp-b-r">${esc(fmtMoney(b.stake))}${b.status === 'open' ? '<small>open</small>' : `<b class="${b.net > 0 ? 'w' : b.net < 0 ? 'l' : ''}">${esc(fmtMoney(b.net || 0, true))}</b><small>${esc(b.status)}</small>`}</span></div>`;
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">${esc(d.name || P?.name || 'Someone')}</h2>
    <p class="lede">${P?.via ? `Joined on ${esc(P.via)}'s link. ` : ''}${plural(d.bets.length, 'ticket')} in their log.</p>
    ${open.length ? `<div class="sub-h" style="margin-top:20px">Running now</div><div class="card grp-blist">${open.map(row).join('')}</div>` : ''}
    ${done.length ? `<div class="sub-h" style="margin-top:20px">Settled</div><div class="card grp-blist">${done.slice(0, 60).map(row).join('')}</div>` : ''}
    ${d.bets.length ? '' : '<div class="card empty" style="margin-top:20px"><b>No tickets yet</b>They haven\'t logged a bet.</div>'}
    <button class="btn ghost" type="button" data-closesheet>Done</button>`;
}
const GRP_MKT = { s: 'spread', t: 'total', ml: 'ML', h1s: '1H spread', h1t: '1H total', tt: 'team total' };
function grpLegs(b) {
  return b.legs.map((l) => `${l.team || (l.side === 'over' ? 'Over' : l.side === 'under' ? 'Under' : l.side || '')} ${l.line != null ? (l.mkt === 't' || l.mkt === 'h1t' ? fmtTot(l.line) : fmtPts(l.line)) : ''} ${fmtOdds(l.odds)}`.replace(/\s+/g, ' ').trim()).join(' + ') || GRP_MKT[b.legs[0]?.mkt] || 'Bet';
}

let grpLoading = null;
async function grpLoadLinks() {
  if (!grpLinks) grpLinks = { base: '', links: [] };
  try { grpLinks = await api('/api/invites'); } catch { /* offline: the tab still draws */ }
  grpPaint();
}
async function grpLoadGroup() {
  if (!grpPeople) grpPeople = [];
  try { grpPeople = (await api('/api/group')).people || []; } catch { /* offline */ }
  if (S.tab === 'admin' && !S.sheet) renderAdmin(); else grpPaint();
}
// The group is re-read while the tab is open, so a friend's ticket shows up without a reload.
setInterval(() => { if (S.tab === 'admin' && !S.sheet && document.visibilityState === 'visible') { grpLoadGroup(); Promise.all([grpLoadHealth(), grpLoadActivity()]).then(() => { if (S.tab === 'admin' && !S.sheet) renderAdmin(); }); } }, 20000);
function grpErr(msg) { const e = $('#grpErr'); if (e) e.textContent = msg || ''; }

// ------------------------------------------------------------ clicks
document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-grp-make],[data-grp-copy],[data-grp-qr],[data-grp-revoke],[data-grp-person],[data-grp-name]');
  if (!t) return;
  const d = t.dataset;

  if (d.grpMake !== undefined) {
    grpErr('');
    const label = String($('#grpLabel')?.value || '').trim();
    try {
      const inv = await api('/api/invites', { method: 'POST', body: JSON.stringify({ label }) });
      $('#grpLabel').value = '';
      grpLinks = null;
      await grpLoadLinks();
      grpCopy(grpShareUrl(inv.token), `Link for ${inv.label} copied. Send it to them.`);
    } catch (e) { grpErr(e.message); }
    return;
  }
  if (d.grpCopy) { grpCopy(grpShareUrl(d.grpCopy), 'Link copied.'); return; }
  if (d.grpQr) { grpQrSheet(d.grpQr); return; }
  if (d.grpRevoke) {
    const label = grpLinks?.links.find((l) => l.id === d.grpRevoke)?.label || 'that link';
    try {
      await api(`/api/invites/${d.grpRevoke}`, { method: 'DELETE' });
      grpLinks = null; grpPeople = null;
      await Promise.all([grpLoadLinks(), grpLoadGroup()]);
      if (S.tab === 'admin') renderAdmin();
      toastText(`${label}'s link is off. Anyone using it is signed out.`);
    } catch (e) { grpErr(e.message); }
    return;
  }
  if (d.grpPerson) { grpPersonSheet(d.grpPerson); return; }
  if (d.grpName !== undefined) {
    const name = String($('#grpName')?.value || '').trim();
    if (!name) { grpErr('Type a name the board can call you.'); return; }
    grpErr('');
    try {
      const r = await api('/api/me/name', { method: 'POST', body: JSON.stringify({ name }) });
      S.me = { ...S.me, name: r.name, named: true };
      toastText('Saved.');
    } catch (e) { grpErr(e.message); }
  }
});

function grpCopy(url, msg) {
  const done = () => toastText(msg);
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(url).then(done).catch(() => grpShowUrl(url));
  else grpShowUrl(url);
}
// Clipboards are blocked in some browsers; show the link so it can be copied by hand.
function grpShowUrl(url) {
  S.sheet = { kind: 'link' };
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">Share link</h2><p class="lede">Send this to one person. Anyone with it can open the board.</p>
    <div class="url" style="user-select:all">${esc(url)}</div><button class="btn ghost" type="button" data-closesheet>Done</button>`;
  showSheet('link', true);
}

function grpQrSheet(token) {
  const url = grpShareUrl(token);
  S.sheet = { kind: 'link' };
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">Scan to join</h2><p class="lede">Point their camera at this. It opens the board on their phone and remembers it.</p>
    <div class="qr" id="grpQr"></div><div class="url" style="user-select:all">${esc(url)}</div>
    <button class="btn ghost" type="button" data-closesheet>Done</button>`;
  showSheet('link', true);
  const draw = () => { try { new QRCode($('#grpQr'), { text: url, width: 200, height: 200, colorDark: '#0B0B0D', colorLight: '#FFFFFF' }); } catch { $('#grpQr')?.remove(); } };
  if (window.QRCode) return draw();
  const sc = document.createElement('script');
  sc.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
  sc.onload = draw;
  sc.onerror = () => $('#grpQr')?.remove();
  document.head.appendChild(sc);
}
