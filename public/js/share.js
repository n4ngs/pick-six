'use strict';
/* Pick Six — share a bet as an image. A Share button on each bet card (betCard, views.js) opens a preview sheet
   with a 1080×1350 PNG drawn on a canvas in the app's own colors (read live from the design tokens, so it follows
   light or dark). Stake and payout stay off the image unless you turn on "Include amount". Share uses the system
   share sheet with the file when the browser supports it; Save image is always there as a plain download. */

const SHARE_W = 1080, SHARE_H = 1350, SHARE_P = 72;
const SHARE_FONT = '"Geist", ui-sans-serif, system-ui, sans-serif';
const SHARE_STATUS = { open: 'Open', won: 'Won', lost: 'Lost', push: 'Push', void: 'Void' };
const SHARE_LEG_STATE = { won: 'Won', lost: 'Lost', push: 'Push', void: 'Void' };
let shareUrl = null, shareFile = null, shareSeq = 0;

// The button that goes on each bet card.
const shareBtn = (b) => `<button type="button" class="share-btn" data-share-bet="${esc(b.id)}" aria-label="Share this bet as an image">${ICON.share}Share</button>`;

// ------------------------------------------------------------ drawing helpers
function shareTokens() {
  const cs = getComputedStyle(document.documentElement);
  const v = (k, d) => cs.getPropertyValue(k).trim() || d;
  return { bg: v('--bg', '#F4F4F6'), surface: v('--surface', '#FFFFFF'), ink: v('--ink', '#0B0B0D'), ink2: v('--ink-2', '#62626B'), ink3: v('--ink-3', '#707078'), line: v('--line', 'rgba(11,11,13,.08)'), fill: v('--fill', 'rgba(11,11,13,.045)'), accent: v('--accent', '#EE3A2E'), win: v('--win', '#12753F'), winFill: v('--win-fill', 'rgba(18,117,63,.1)') };
}
function shareFont(ctx, size, weight = 500, track = 0) {
  ctx.font = `${weight} ${size}px ${SHARE_FONT}`;
  if ('letterSpacing' in ctx) ctx.letterSpacing = `${track}px`;
}
function shareRound(ctx, x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
  else { ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
}
// Text that must fit a width: shrink down to min, then cut with an ellipsis.
function shareFit(ctx, text, maxW, size, min, weight, track = 0) {
  let s = size;
  shareFont(ctx, s, weight, track);
  while (s > min && ctx.measureText(text).width > maxW) { s -= 2; shareFont(ctx, s, weight, track); }
  let t = text;
  while (t.length > 1 && ctx.measureText(t).width > maxW) t = t.slice(0, -2) + '…';
  return { t, s };
}
function shareImg(src) {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}
// The app's mark: an ink tile with the football, and the live-red dot.
function shareMark(ctx, x, y, s, T) {
  shareRound(ctx, x, y, s, s, s * 0.3); ctx.fillStyle = T.ink; ctx.fill();
  ctx.save();
  ctx.translate(x + s / 2, y + s / 2); ctx.scale(s / 26, s / 26); ctx.rotate(-35 * Math.PI / 180);
  ctx.beginPath(); ctx.ellipse(0, 0, 7.6, 4.4, 0, 0, Math.PI * 2); ctx.fillStyle = T.surface; ctx.fill();
  ctx.strokeStyle = T.ink; ctx.lineWidth = 1.1; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(-3, 0); ctx.lineTo(3, 0); for (const lx of [-1.6, 0, 1.6]) { ctx.moveTo(lx, -1.2); ctx.lineTo(lx, 1.2); } ctx.stroke();
  ctx.restore();
  const r = s * 0.16;
  ctx.beginPath(); ctx.arc(x + s - r * 0.4, y + r * 0.4, r + s * 0.06, 0, Math.PI * 2); ctx.fillStyle = T.bg; ctx.fill();
  ctx.beginPath(); ctx.arc(x + s - r * 0.4, y + r * 0.4, r, 0, Math.PI * 2); ctx.fillStyle = T.accent; ctx.fill();
}
// Book logo (same-origin PNG, on white like the slip tiles) or the slip's monogram.
async function shareBookIcon(ctx, key, name, x, y, s, T) {
  const icon = key && typeof BOOK_ICON !== 'undefined' && BOOK_ICON.has(key) ? await shareImg(`icons/books/${key}.png`) : null;
  shareRound(ctx, x, y, s, s, s * 0.28);
  if (icon) {
    ctx.save(); ctx.fillStyle = '#FFFFFF'; ctx.fill(); ctx.clip();
    ctx.drawImage(icon, x, y, s, s);
    ctx.restore();
    return;
  }
  ctx.fillStyle = T.fill; ctx.fill();
  const mono = /^other$/i.test(name) ? '…' : (name || '?').replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase() || '?';
  shareFont(ctx, s * 0.38, 650, 1); ctx.fillStyle = T.ink; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(mono, x + s / 2, y + s / 2 + 1);
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
}

// ------------------------------------------------------------ what the card says
function shareModel(b) {
  const leg0 = b.legs[0];
  const single = b.legs.length === 1;
  const g = single ? gameById(leg0.gid) : null;
  const [awayAb, homeAb] = String(leg0.matchup || '').split(' @ ');
  const bk = S.books.find((x) => x.name === b.book || x.short === b.book || x.key === b.book);
  const when = (iso) => (iso ? `${new Date(iso).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })} · ${timeLabel(iso).replace(/\u00a0/g, ' ')}` : '');
  const clvTxt = (l) => (!l?.clv ? '' : l.clv.pts != null ? (l.clv.pts === 0 ? 'Same number as the close' : `${trim(Math.abs(l.clv.pts))} ${Math.abs(l.clv.pts) === 1 ? 'point' : 'points'} ${l.clv.pts > 0 ? 'better' : 'worse'} than the close`) : l.clv.pct != null ? `${l.clv.pct > 0 ? '+' : l.clv.pct < 0 ? MINUS : ''}${Math.abs(l.clv.pct)}% vs the closing price` : '');
  const finalTxt = (l) => (l?.final ? `Final · ${l.matchup ? `${shareAwayAb(l)} ${l.final.a}, ${shareHomeAb(l)} ${l.final.h}` : `${l.final.a}–${l.final.h}`}` : '');
  const pays = toWin(b.stake, b.odds);
  const amount = b.status === 'won' ? `Stake ${fmtMoney(b.stake)} · Paid ${fmtMoney(Math.round((b.stake + (b.net ?? pays ?? 0)) * 100) / 100)}`
    : b.status === 'open' ? `Stake ${fmtMoney(b.stake)} · To win ${fmtMoney(Math.round((pays || 0) * 100) / 100)}`
    : b.status === 'push' || b.status === 'void' ? `Stake ${fmtMoney(b.stake)} · Returned` : `Stake ${fmtMoney(b.stake)}`;
  return {
    status: SHARE_STATUS[b.status] || 'Open', st: b.status,
    kind: single ? (typeof MKT_NAME !== 'undefined' && MKT_NAME[leg0.mkt]) || 'Straight bet' : 'Parlay',
    pick: single ? leg0.label : `${b.legs.length}-leg parlay`,
    odds: fmtOdds(b.odds),
    bookKey: bk?.key || '', book: b.book || '',
    matchup: g ? `${g.away.short} @ ${g.home.short}` : single ? (awayAb && homeAb ? `${awayAb} @ ${homeAb}` : leg0.matchup || '') : '',
    date: single ? when(leg0.start || g?.start) : '',
    final: single && b.status !== 'open' ? finalTxt(leg0) : '',
    clv: single ? clvTxt(leg0) : '',
    legs: single ? [] : b.legs.map((l) => ({ label: l.label, odds: fmtOdds(l.odds), sub: [l.matchup, l.final ? `${l.final.a}–${l.final.h}` : when(l.start)].filter(Boolean).join(' · '), state: SHARE_LEG_STATE[l.state] || '', won: l.state === 'won' && b.status === 'won' })), // green only on a winning ticket
    amount,
    placed: b.placed ? new Date(b.placed).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : '',
  };
}
const shareAwayAb = (l) => String(l.matchup || '').split(' @ ')[0] || 'Away';
const shareHomeAb = (l) => String(l.matchup || '').split(' @ ')[1] || 'Home';

// ------------------------------------------------------------ the image
async function shareDraw(b, withAmount) {
  try { await Promise.all([document.fonts.load(`650 96px ${SHARE_FONT}`), document.fonts.load(`500 32px ${SHARE_FONT}`)]); } catch { /* system font fallback */ }
  try { await document.fonts.ready; } catch { /* fine */ }
  const T = shareTokens();
  const M = shareModel(b);
  const cv = document.createElement('canvas');
  cv.width = SHARE_W; cv.height = SHARE_H;
  const ctx = cv.getContext('2d');
  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = T.bg; ctx.fillRect(0, 0, SHARE_W, SHARE_H);
  const P = SHARE_P;

  // header: mark + name, status pill on the right
  shareMark(ctx, P, P, 84, T);
  shareFont(ctx, 44, 650, -0.8); ctx.fillStyle = T.ink; ctx.fillText('Pick Six', P + 108, P + 57);
  const pill = { won: [T.winFill, T.win], lost: [T.fill, T.ink2], push: [T.fill, T.ink], void: [T.fill, T.ink2] }[M.st] || [T.surface, T.ink];
  shareFont(ctx, 34, 600, 0);
  const pw = ctx.measureText(M.status).width + 64;
  shareRound(ctx, SHARE_W - P - pw, P + 6, pw, 72, 36); ctx.fillStyle = pill[0]; ctx.fill();
  ctx.fillStyle = pill[1]; ctx.fillText(M.status, SHARE_W - P - pw + 32, P + 54);

  // the ticket
  const cx = P, cy = 208, cw = SHARE_W - 2 * P, ch = 1000;
  shareRound(ctx, cx, cy, cw, ch, 56); ctx.fillStyle = T.surface; ctx.fill();
  const x0 = cx + 64, iw = cw - 128;
  let y = cy + 104;
  shareFont(ctx, 34, 500, 0); ctx.fillStyle = T.ink2; ctx.fillText(M.kind, x0, y);
  y += 118;
  const pk = shareFit(ctx, M.pick, iw, 104, 60, 650, -3);
  ctx.fillStyle = T.ink; ctx.fillText(pk.t, x0, y);
  y += 88;
  shareFont(ctx, 64, 600, -1.5); ctx.fillStyle = T.ink2; ctx.fillText(M.odds, x0, y);

  // book
  y += 60;
  const bs = 88;
  if (M.book) {
    await shareBookIcon(ctx, M.bookKey, M.book, x0, y, bs, T);
    const bt = shareFit(ctx, M.book, iw - bs - 28, 40, 28, 600, -0.4); ctx.fillStyle = T.ink; ctx.fillText(bt.t, x0 + bs + 28, y + bs / 2 + 14);
    y += bs;
  } else y += 8;

  // divider
  y += 52;
  ctx.fillStyle = T.line; ctx.fillRect(x0, y, iw, 2);
  y += 2;

  if (M.legs.length) {
    // As many legs as fit above the amount line (or the card's bottom); the rest become "and N more legs".
    const limit = cy + ch - (withAmount ? 150 : 48);
    const n = M.legs.length;
    let max = n;
    while (max > 1 && y + 12 + max * 120 + (max < n ? 56 : 0) > limit) max--;
    y += 12;
    for (const l of M.legs.slice(0, max)) {
      y += 60;
      const right = [l.state, l.odds].filter(Boolean).join('  ');
      shareFont(ctx, 34, 600, 0);
      const rw = ctx.measureText(right).width;
      const lt = shareFit(ctx, l.label, iw - rw - 32, 38, 28, 600, -0.4);
      ctx.fillStyle = T.ink; ctx.fillText(lt.t, x0, y);
      shareFont(ctx, 34, 600, 0); ctx.textAlign = 'right';
      if (l.state) {
        const ow = l.odds ? ctx.measureText(`  ${l.odds}`).width : 0;
        ctx.fillStyle = l.won ? T.win : T.ink2; ctx.fillText(l.state, x0 + iw - ow, y);
        ctx.fillStyle = T.ink2; if (l.odds) ctx.fillText(`  ${l.odds}`, x0 + iw, y);
      } else { ctx.fillStyle = T.ink2; ctx.fillText(l.odds, x0 + iw, y); }
      ctx.textAlign = 'left';
      y += 44;
      const st = shareFit(ctx, l.sub, iw, 28, 22, 500, 0); ctx.fillStyle = T.ink2; ctx.fillText(st.t, x0, y);
      y += 16;
    }
    if (n > max) { y += 48; shareFont(ctx, 30, 500, 0); ctx.fillStyle = T.ink2; ctx.fillText(`and ${plural(M.legs.length - max, 'more leg')}`, x0, y); }
  } else {
    y += 84;
    const mu = shareFit(ctx, M.matchup, iw, 48, 32, 600, -0.8); ctx.fillStyle = T.ink; ctx.fillText(mu.t, x0, y);
    if (M.date) { y += 56; shareFont(ctx, 34, 500, 0); ctx.fillStyle = T.ink2; ctx.fillText(M.date, x0, y); }
    const facts = [M.final, M.clv].filter(Boolean);
    for (const f of facts) { y += 64; const ft = shareFit(ctx, f, iw, 36, 26, 500, 0); ctx.fillStyle = T.ink; ctx.fillText(ft.t, x0, y); }
  }
  if (withAmount) {
    const ay = cy + ch - 72;
    ctx.fillStyle = T.line; ctx.fillRect(x0, ay - 70, iw, 2);
    const at = shareFit(ctx, M.amount, iw, 38, 26, 600, -0.4); ctx.fillStyle = T.ink; ctx.fillText(at.t, x0, ay);
  }

  // footer
  shareFont(ctx, 30, 500, 0); ctx.fillStyle = T.ink2;
  ctx.fillText(`Logged on Pick Six${M.placed ? ` · ${M.placed}` : ''}`, P, SHARE_H - 84);
  shareFont(ctx, 26, 500, 0); ctx.fillStyle = T.ink3;
  ctx.fillText('21+. Gambling problem? Call 1-800-GAMBLER.', P, SHARE_H - 40);
  return cv;
}

// ------------------------------------------------------------ the sheet
function shareAlt(b, withAmount) {
  const M = shareModel(b);
  return [`Pick Six bet card: ${M.pick} ${M.odds}`, M.book, M.matchup, M.date, M.status, M.final, M.clv, withAmount ? M.amount : ''].filter(Boolean).join('. ').replace(MINUS, 'minus ');
}
function shareSheetHTML() {
  const s = S.sheet;
  const can = !!(navigator.share && navigator.canShare);
  return `<h2 id="dlgTitle">Share this bet</h2>
    <p class="lede">A picture of your ticket. Amounts stay off unless you add them.</p>
    <div class="share-prev"><img id="shareImg" alt="" width="${SHARE_W}" height="${SHARE_H}"></div>
    <button type="button" class="share-sw" role="switch" aria-checked="${!!s.amt}" data-share-amt><span>Include amount</span><i aria-hidden="true"></i></button>
    <div class="row-btns share-btns">${can ? `<button class="btn" type="button" data-share-go disabled>${ICON.share}Share</button>` : ''}<a class="btn${can ? ' ghost' : ''}" id="shareSave" download="pick-six-bet.png" aria-disabled="true">Save image</a></div>
    <p class="err" id="shareErr" role="alert"></p>`;
}
async function shareRender() {
  const s = S.sheet;
  if (s?.kind !== 'share') return;
  const b = S.bets.find((x) => x.id === s.id);
  if (!b) return;
  const seq = ++shareSeq;
  const cv = await shareDraw(b, !!s.amt);
  const blob = await new Promise((res) => cv.toBlob(res, 'image/png'));
  if (seq !== shareSeq || S.sheet?.kind !== 'share' || !blob) return;
  if (shareUrl) URL.revokeObjectURL(shareUrl);
  shareUrl = URL.createObjectURL(blob);
  shareFile = new File([blob], 'pick-six-bet.png', { type: 'image/png' });
  const img = $('#shareImg');
  if (img) { img.src = shareUrl; img.alt = shareAlt(b, !!s.amt); }
  const save = $('#shareSave');
  if (save) { save.href = shareUrl; save.removeAttribute('aria-disabled'); }
  const go = $('[data-share-go]');
  if (go) {
    let ok = false;
    try { ok = navigator.canShare({ files: [shareFile] }); } catch { ok = false; }
    if (ok) go.disabled = false;
    else { go.remove(); save?.classList.remove('ghost'); }
  }
}
function shareOpen(id) {
  if (!S.bets.some((x) => x.id === id)) return;
  S.sheet = { kind: 'share', id, amt: false };
  $('#dlgBody').innerHTML = shareSheetHTML();
  showSheet('share', true);
  const box = $('#dlgIn');
  if (box) box.scrollTop = 0;
  shareRender();
}

document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-share-bet], [data-share-amt], [data-share-go], #shareSave');
  if (!t) return;
  if (t.dataset.shareBet) { ev.preventDefault(); ev.stopPropagation(); shareOpen(t.dataset.shareBet); return; }
  if (S.sheet?.kind !== 'share') return;
  if (t.dataset.shareAmt !== undefined) {
    S.sheet.amt = !S.sheet.amt;
    t.setAttribute('aria-checked', String(S.sheet.amt));
    shareRender();
    return;
  }
  if (t.id === 'shareSave') { if (!shareUrl) ev.preventDefault(); return; }
  if (t.dataset.shareGo !== undefined) {
    if (!shareFile) return;
    try { await navigator.share({ files: [shareFile], title: 'My bet' }); }
    catch (e) { if (e?.name !== 'AbortError') { const er = $('#shareErr'); if (er) er.textContent = 'Couldn’t open sharing. Save the image instead.'; } }
  }
});
$('#dlg').addEventListener('close', () => { shareSeq++; if (shareUrl) { URL.revokeObjectURL(shareUrl); shareUrl = null; } shareFile = null; });
