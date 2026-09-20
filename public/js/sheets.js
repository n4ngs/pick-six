'use strict';
/* Pick Six — sheets: one game in depth (with the interactive line chart), the bet slip,
   typing in a number from the counter, and opening the app on a phone. */

const dlg = () => $('#dlg');
function showSheet(kind, narrow = false) {
  const d = dlg();
  d.classList.toggle('narrow', narrow);
  if (!d.open) d.showModal();
  S.sheet = { ...(S.sheet || {}), kind };
}
function closeSheet() {
  S.sheet = null;
  S.game = null;
  clearTimeout(gameTimer);
  if (dlg().open) dlg().close();
  if (location.hash.startsWith('#game/')) history.replaceState(null, '', `#${S.tab}`);
  invalidate(); // the tab underneath wasn't redrawn while the sheet was up
}

// ------------------------------------------------------------ one game
let gameTimer = 0;
async function openGame(gid) {
  const g = gameById(gid);
  S.sheet = { kind: 'game', gid, chartMkt: S.sheet?.gid === gid ? S.sheet.chartMkt : (S.mkt === 't' ? 't' : 's'), focus: null };
  S.game = { game: g, hist: null, summary: null };
  $('#dlgBody').innerHTML = g ? gameSheet() : '<div class="empty"><b>Loading…</b></div>';
  showSheet('game');
  if (!location.hash.startsWith('#game/')) history.replaceState(null, '', `#game/${gid}`);
  await fetchGame(gid);
}
async function fetchGame(gid) {
  clearTimeout(gameTimer);
  if (S.sheet?.kind !== 'game' || S.sheet.gid !== gid) return;
  try {
    const d = await api(`/api/game/${gid}`);
    if (S.sheet?.gid !== gid) return;
    S.game = d;
    loadKeys().then(() => { if (S.sheet?.gid === gid) paintGame(); });
    paintGame();
  } catch (e) {
    if (!S.game?.game) $('#dlgBody').innerHTML = `<div class="empty"><b>Couldn't load this game</b>${esc(e.message)}</div>`;
  }
  const g = S.game?.game;
  gameTimer = setTimeout(() => fetchGame(gid), g && isLive(g) ? Math.max(8000, S.liveMs) : 60000);
}
let lastPaint = 0;
function refreshSheet() {
  // Feature sheets repaint themselves on live data (sweat.js, tmachine.js, edge.js).
  const hook = { sweat: 'sweatRefresh', tm: 'tmRefresh', edges: 'edgeRefresh' }[S.sheet?.kind];
  if (hook) { if (typeof window[hook] === 'function') window[hook](); return; }
  if (S.sheet?.kind !== 'game' || !S.game) return;
  const g = gameById(S.sheet.gid);
  if (g) S.game.game = g;
  if (Date.now() - lastPaint < 1500 || chartActive) return;
  paintGame();
}
function paintGame() {
  if (S.sheet?.kind !== 'game') return;
  lastPaint = Date.now();
  const body = $('#dlgBody');
  body.innerHTML = gameSheet();
  wireChart();
}

function gameSheet() {
  const { game: g, hist: H, summary: sm } = S.game || {};
  if (!g) return '<div class="empty"><b>Loading…</b></div>';
  const mkt = S.sheet.chartMkt;
  const tm = (t, side) => {
    const other = side === 'home' ? g.away : g.home;
    const trail = !isPre(g) && (t.score ?? 0) < (other.score ?? 0);
    return `<div class="gs-t ${side === 'home' ? 'h' : ''}${trail ? ' trail' : ''}">${logo(t)}<div style="min-width:0"><div class="a">${esc([t.rank ? `#${t.rank}` : null, t.rec, rotOf(g, side) ? `rot ${rotOf(g, side)}` : null].filter(Boolean).join(' · '))}</div><div class="n">${esc(teamName(t))}${g.poss === side && isLive(g) ? '<span class="poss-dot"></span>' : ''}</div></div>${isPre(g) ? '' : `<div class="s num">${t.score ?? 0}</div>`}</div>`;
  };
  const meta = [g.tv, g.venue?.name, g.neutral ? 'Neutral site' : null, g.confGame ? 'Conference game' : null, g.note].filter(Boolean);
  const follow = (t) => `<button class="chip" type="button" data-follow="${t.id}" aria-pressed="${S.follow.has(t.id)}">${S.follow.has(t.id) ? ICON.starOn.replace('<svg', '<svg width="14" height="14"') : ICON.star.replace('<svg', '<svg width="14" height="14"')}${esc(t.abbr)}</button>`;
  const mine = S.bets.filter((b) => b.legs.some((l) => l.gid === g.id));
  return `
    <div class="gs-h">${tm(g.away, 'away')}<div class="gs-mid"><b>${isLive(g) ? '<span class="dot pulse"></span>' : ''}${esc(clockLabel(g))}</b>${esc(isPre(g) ? dayLabel(g.start, true) : g.detail || '')}</div>${tm(g.home, 'home')}</div>
    <div class="gs-meta">${meta.map((m) => `<span class="tag">${esc(m)}</span>`).join('')}${follow(g.away)}${follow(g.home)}</div>
    ${isLive(g) ? `<div class="gs-sec">${fieldSVG(g, true)}<div class="situ"><span>${g.sit?.text ? `<b>${esc(g.sit.text)}</b>` : ''}${g.last ? ` ${esc(g.last.slice(0, 120))}` : ''}</span>${g.sit?.rz ? '<span class="rz">Red zone</span>' : ''}</div></div>` : ''}
    <div class="gs-grid gs-sec">
      <div>
        <div class="sub-h">Line movement <span class="seg" style="padding:2px" role="group" aria-label="Chart market"><button type="button" data-cm="s" aria-pressed="${mkt === 's'}" style="height:28px">Spread</button><button type="button" data-cm="t" aria-pressed="${mkt === 't'}" style="height:28px">Total</button></span></div>
        <div class="card chart" id="chart">${chartSVG(g, H, mkt)}</div>
        ${H ? `<button type="button" class="tm-open" data-tm-open="${g.id}" data-tm-mkt="${mkt}">Replay the line, book by book</button>` : ''}
      </div>
      <div>${numbersPanel(g)}</div>
    </div>
    <div class="gs-sec"><div class="sub-h">Every book <span class="bt-note">Tap a price to log a bet</span><span class="seg bt-seg" role="group" aria-label="Book table market"><button type="button" data-tm="s" aria-pressed="${(S.sheet.tableMkt || 's') === 's'}">Spread</button><button type="button" data-tm="t" aria-pressed="${S.sheet.tableMkt === 't'}">Total</button><button type="button" data-tm="ml" aria-pressed="${S.sheet.tableMkt === 'ml'}">Money</button></span></div>${bookTable(g)}</div>
    <div class="gs-grid gs-sec even">
      <div>${splitsPanel(g)}</div>
      <div>${keysPanel(g)}</div>
    </div>
    ${g.h1 || g.tt ? `<div class="gs-sec"><div class="sub-h">First half &amp; team totals</div>${halfPanel(g)}</div>` : ''}
    ${!isPre(g) && sm ? livePanel(g, sm) : ''}
    ${mine.length ? `<div class="gs-sec"><div class="sub-h">Your bets here</div><div class="bets">${mine.map(betCard).join('')}</div></div>` : ''}
    <p class="note" style="margin-top:24px">${esc(spreadWords(g[favSide(g) || 'home'], lineFor(g, favSide(g) || 'home', g.mkt)))} ${esc(totalWords(g.mkt?.t))}</p>`;
}

// ------------------------------------------------------------ chart
let chartActive = false;
function chartModel(g, H, mkt) {
  if (!H) return null;
  // Plot from the favorite's side, "points favored by", so up means the favorite got more expensive.
  const favHome = (g.mkt?.s ?? g.close?.s ?? -1) <= 0;
  const conv = (v) => (mkt === 't' ? v : favHome ? -v : v);
  const series = [];
  const books = ['cons', ...visibleBooks().map((b) => b.key)];
  for (const k of books) {
    const pts = (H.b?.[k]?.[mkt] || []).map((p) => [p[0], conv(p[1])]);
    if (pts.length) series.push({ key: k, pts });
  }
  const open = H.open?.[mkt] != null ? { t: H.open.at, v: conv(H.open[mkt]) } : null;
  const live = (H.l?.[mkt] || []).map((p) => [p[0], conv(p[1])]);
  const ko = Date.parse(g.start);
  const end = isPre(g) ? serverNow() : isLive(g) ? serverNow() : Math.max(ko + 4 * 3600e3, ...(live.length ? [live.at(-1)[0]] : [ko]));
  const firstSeen = Math.min(...series.flatMap((s) => [s.pts[0][0]]), Infinity);
  const t0 = open?.t && open.t < firstSeen ? open.t : Number.isFinite(firstSeen) ? firstSeen : end - 3600e3;
  const vals = [...series.flatMap((s) => s.pts.map((p) => p[1])), ...(open ? [open.v] : []), ...live.map((p) => p[1])];
  if (!vals.length) return null;
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 2) { lo -= 1; hi += 1; }
  const moves = (H.moves || []).filter((m) => m.mkt === mkt && m.t >= t0);
  return { series, open, live, t0, t1: Math.max(end, t0 + 60e3), lo: Math.floor(lo * 2) / 2 - 0.5, hi: Math.ceil(hi * 2) / 2 + 0.5, ko, moves, favHome, firstSeen };
}
// Time runs left to right, but hours before the first recorded point are squeezed so the tracked part is readable.
function chartScale(M, W) {
  // No book history yet means firstSeen is Infinity: that's not a gap, and drawing it would throw.
  const gapEnd = Number.isFinite(M.firstSeen) && M.open?.t && M.firstSeen - M.open.t > 6 * 3600e3 ? M.firstSeen : null;
  const L = 44, R = W - 12;
  if (!gapEnd) return { X: (t) => L + ((t - M.t0) / (M.t1 - M.t0)) * (R - L), inv: (x) => M.t0 + ((x - L) / (R - L)) * (M.t1 - M.t0), gapEnd: null, L, R };
  const gw = (R - L) * 0.14;
  const X = (t) => (t <= gapEnd ? L + ((t - M.t0) / (gapEnd - M.t0)) * gw : L + gw + ((t - gapEnd) / (M.t1 - gapEnd)) * (R - L - gw));
  const inv = (x) => (x <= L + gw ? M.t0 + ((x - L) / gw) * (gapEnd - M.t0) : gapEnd + ((x - L - gw) / (R - L - gw)) * (M.t1 - gapEnd));
  return { X, inv, gapEnd, L, R };
}
const stepAt = (pts, t) => { let v = null; for (const p of pts) { if (p[0] <= t) v = p[1]; else break; } return v; };

function chartSVG(g, H, mkt) {
  const M = chartModel(g, H, mkt);
  if (!M) return `<div class="empty" style="padding:32px 8px"><b>${H ? 'No line history yet' : 'Loading history…'}</b>${H ? 'The app records every change from now on. Lines usually open Sunday.' : ''}</div>`;
  const W = 640, Ht = 240, T = 12, B = Ht - 26;
  const sc = chartScale(M, W);
  const Y = (v) => T + ((M.hi - v) / (M.hi - M.lo)) * (B - T);
  const step = M.hi - M.lo > 16 ? 4 : M.hi - M.lo > 8 ? 2 : M.hi - M.lo > 3 ? 1 : 0.5;
  let grid = '';
  for (let v = Math.ceil(M.lo / step) * step; v <= M.hi; v += step) {
    const label = mkt === 't' ? fmtTot(v) : fmtPts(-v);
    grid += `<line class="gl" x1="${sc.L}" x2="${sc.R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="ax" x="${sc.L - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${esc(label)}</text>`;
  }
  const path = (pts, tEnd) => {
    if (!pts.length) return '';
    let d = `M${sc.X(pts[0][0]).toFixed(1)},${Y(pts[0][1]).toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) d += ` H${sc.X(pts[i][0]).toFixed(1)} V${Y(pts[i][1]).toFixed(1)}`;
    return `${d} H${sc.X(tEnd).toFixed(1)}`;
  };
  const tEndPre = isPre(g) ? M.t1 : Math.min(M.ko, M.t1);
  const focus = S.sheet.focus;
  const colors = {};
  const lines = M.series.map((s, i) => {
    const color = s.key === 'cons' ? 'var(--ink)' : `hsl(${(i * 47 + 200) % 360} 55% 50%)`;
    colors[s.key] = color;
    const cls = s.key === 'cons' ? 'ser cons' : `ser${focus ? (focus === s.key ? ' focus' : ' dim') : ''}`;
    return `<path class="${cls}" d="${path(s.pts, tEndPre)}" style="${s.key === 'cons' ? '' : `stroke:${color}`}"/>`;
  }).join('');
  const cons = M.series.find((s) => s.key === 'cons') || M.series[0];
  const gap = M.open && cons && M.open.t < cons.pts[0][0] ? `<path class="gap" d="M${sc.X(M.open.t).toFixed(1)},${Y(M.open.v).toFixed(1)} L${sc.X(cons.pts[0][0]).toFixed(1)},${Y(cons.pts[0][1]).toFixed(1)}"/>` : '';
  const live = M.live.length ? `<path class="ser live" d="${path(M.live, M.t1)}"/>` : '';
  const ko = M.ko > M.t0 && M.ko < M.t1 ? `<line class="ko" x1="${sc.X(M.ko)}" x2="${sc.X(M.ko)}" y1="${T}" y2="${B}"/><text class="kol" x="${sc.X(M.ko) + 4}" y="${T + 10}">Kickoff</text>` : '';
  const mk = M.moves.map((m) => { const v = cons ? stepAt(cons.pts, m.t) : null; return v == null ? '' : `<circle class="mk" cx="${sc.X(m.t).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="5"><title>${esc(moveWord[m.kind])}</title></circle>`; }).join('');
  const openDot = M.open ? `<circle class="open" cx="${sc.X(M.open.t || M.t0).toFixed(1)}" cy="${Y(M.open.v).toFixed(1)}" r="4.5"><title>Opened</title></circle>` : '';
  const last = cons?.pts.at(-1);
  const nowDot = last ? `<circle class="now" cx="${sc.X(tEndPre).toFixed(1)}" cy="${Y(last[1]).toFixed(1)}" r="4"/>` : '';
  // x labels: open, gap end, now
  const xl = [];
  if (M.open?.t) xl.push([sc.X(M.open.t), `Opened ${dayLabel(new Date(M.open.t).toISOString())}`, 'start']);
  xl.push([sc.R, isPre(g) ? 'Now' : isFinal(g) ? 'Final' : 'Now', 'end']);
  if (sc.gapEnd) xl.push([sc.X(sc.gapEnd), `Tracking since ${timeLabel(new Date(sc.gapEnd).toISOString())}`, 'start']);
  const xlab = xl.map(([x, t, a]) => `<text class="ax" x="${x.toFixed(1)}" y="${Ht - 6}" text-anchor="${a}">${esc(t)}</text>`).join('');
  const legend = M.series.map((s) => `<button class="lg" type="button" data-focus="${s.key}" aria-pressed="${focus === s.key}"><i style="background:${colors[s.key]}"></i>${esc(bookName(s.key))}</button>`).join('');
  const fav = M.favHome ? g.home : g.away;
  const note = mkt === 't' ? 'Total points. Up means the total went up.' : `${fav.abbr}'s spread. Up means ${fav.abbr} became a bigger favorite.`;
  S.chart = { M, sc, Y, W, Ht, T, B, colors, tEndPre };
  return `<svg viewBox="0 0 ${W} ${Ht}" role="img" aria-label="Line movement chart">${grid}${gap}${lines}${live}${ko}${openDot}${mk}${nowDot}${xlab}<line class="cur" id="cur" x1="0" x2="0" y1="${T}" y2="${B}" visibility="hidden"/></svg>
    <div class="tip" id="tip" hidden></div>
    <div class="legend">${legend}</div>
    <div class="chart-note">${esc(note)} ${M.live.length ? 'Dashed: the live in-game line.' : ''} ${M.moves.length ? 'Red dots: steam or key-number moves.' : ''} Drag across the chart to read any moment.</div>`;
}

function wireChart() {
  const box = $('#chart');
  const svg = box?.querySelector('svg');
  if (!svg || !S.chart) return;
  const tip = $('#tip'), cur = $('#cur');
  const show = (ev) => {
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * S.chart.W;
    const { M, sc } = S.chart;
    if (x < sc.L || x > sc.R) return hide();
    const t = sc.inv(x);
    chartActive = true;
    cur.setAttribute('x1', x); cur.setAttribute('x2', x); cur.setAttribute('visibility', 'visible');
    const mkt = S.sheet.chartMkt;
    const rows = M.series.map((s) => [s.key, stepAt(s.pts, Math.min(t, S.chart.tEndPre))]).filter((r) => r[1] != null);
    const lv = t > M.ko && M.live.length ? stepAt(M.live, t) : null;
    const fmt = (v) => (mkt === 't' ? fmtTot(v) : fmtPts(-v));
    const when = new Date(t);
    tip.innerHTML = `<b>${esc(when.toLocaleDateString([], { weekday: 'short' }))} ${esc(when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }))}</b>${lv != null ? `<div><span>Live</span><strong class="num">${esc(fmt(lv))}</strong></div>` : ''}${rows.slice(0, 9).map(([k, v]) => `<div><span>${esc(bookName(k))}</span><strong class="num">${esc(fmt(v))}</strong></div>`).join('')}`;
    tip.hidden = false;
    const px = (x / S.chart.W) * box.clientWidth;
    tip.style.left = `${clamp(px, 80, box.clientWidth - 80)}px`;
  };
  const hide = () => { chartActive = false; tip.hidden = true; cur.setAttribute('visibility', 'hidden'); };
  svg.addEventListener('pointermove', show);
  svg.addEventListener('pointerdown', show);
  svg.addEventListener('pointerleave', hide);
  svg.addEventListener('pointerup', (e) => { if (e.pointerType !== 'mouse') setTimeout(hide, 1500); });
}

// ------------------------------------------------------------ sheet panels
function bookTable(g) {
  const live = isLive(g);
  const src = live ? g.live || {} : g.books || {};
  const keys = ['cons', ...(!live ? ['open'] : []), ...visibleBooks().map((b) => b.key)];
  const best = {};
  for (const [m, s] of [['s', 'away'], ['s', 'home'], ['t', 'over'], ['t', 'under'], ['ml', 'away'], ['ml', 'home']]) best[`${m}${s}`] = bestOf(src, m, s);
  const cell = (k, m, side) => {
    const L = k === 'open' ? { s: g.open?.s, so: [null, null], t: g.open?.t, to: [null, null], ml: g.open?.ml || [null, null] } : src[k];
    const p = sideOf(L, m, side);
    if (!p || (p.line == null && p.odds == null)) return '<span class="px na">—</span>';
    const b = best[`${m}${side}`];
    const isBest = k !== 'cons' && k !== 'open' && b?.book === k && !isFinal(g);
    const main = m === 'ml' ? fmtOdds(p.odds) : m === 't' ? `${side === 'over' ? 'o' : 'u'}${fmtTot(p.line)}` : fmtPts(p.line);
    const flash = flashAttr(g.id, live ? 'live' : 'pre', k, m);
    const old = isOld(L);
    const cls = `px num${isBest ? ' best' : ''}${L?.m ? ' man' : ''}${flash.cls}${k === 'open' ? ' na' : ''}${old ? ' old' : ''}`;
    const inner = `${esc(main)}${m !== 'ml' && p.odds != null ? `<small>${esc(fmtOdds(p.odds))}</small>` : ''}`;
    if (k === 'open' || isFinal(g)) return `<span class="${cls}"${flash.style}>${inner}</span>`;
    const who = side === 'over' ? 'Over' : side === 'under' ? 'Under' : teamName(g[side]);
    const label = [bookFull(k), `${who} ${main}`, m !== 'ml' ? fmtOdds(p.odds) : '', isBest ? 'best price' : '', L?.m ? 'typed in' : '', flash.label, old ? `checked ${ago(L.seen)}` : ''].filter(Boolean).join(', ');
    return `<button type="button" class="${cls}"${flash.style} data-bet="${g.id}|${m}|${side}|${k}" aria-label="${esc(label)}">${inner}</button>`;
  };
  const rows = keys.filter((k) => k === 'cons' || k === 'open' || src[k] || S.books.find((b) => b.key === k && !b.feed)).map((k) => {
    const b = S.books.find((x) => x.key === k);
    const L = src[k];
    const age = L?.m ? `typed ${ago(L.at)}` : L?.src === 'vsin' ? 'via VSiN' : L?.src === 'pin' ? 'Pinnacle feed' : k === 'open' && g.open?.at ? dayLabel(new Date(g.open.at).toISOString()) : '';
    const op = g.opens?.[k]?.s != null && !live ? `opened ${fmtPts(favSide(g) === 'away' ? -g.opens[k].s : g.opens[k].s)}` : '';
    return `<tr class="${k === 'cons' ? 'cons' : ''}"><td><div class="bk">${esc(bookName(k))}${b?.sharp ? '<span class="tag sharp">Sharp</span>' : ''}</div><small class="faint" style="font-size:11px">${esc([age, op].filter(Boolean).join(' · ') || (b && !b.feed && !L ? 'counter only' : ''))}</small></td>
      <td class="c-s">${cell(k, 's', 'away')}</td><td class="c-s">${cell(k, 's', 'home')}</td><td class="c-t">${cell(k, 't', 'over')}</td><td class="c-t">${cell(k, 't', 'under')}</td><td class="c-ml">${cell(k, 'ml', 'away')}</td><td class="c-ml">${cell(k, 'ml', 'home')}</td></tr>`;
  }).join('');
  return `<div class="card" style="overflow-x:auto;padding-top:14px"><table class="btable m-${S.sheet.tableMkt || 's'}"><thead><tr><th>${live ? 'Live' : 'Book'}</th><th class="c-s">${esc(g.away.abbr)}</th><th class="c-s">${esc(g.home.abbr)}</th><th class="c-t">Over</th><th class="c-t">Under</th><th class="c-ml">${esc(g.away.abbr)} ML</th><th class="c-ml">${esc(g.home.abbr)} ML</th></tr></thead><tbody>${rows}</tbody></table>
    ${isFinal(g) ? '' : `<button class="addnum" type="button" data-counter="${g.id}">${ICON.plus} Add a number from the counter</button>`}</div>`;
}

function numbersPanel(g) {
  const out = [];
  const m = g.mkt, c = g.close;
  const fav = favSide(g);
  if (fav && m?.s != null) out.push([`${g[fav].abbr} spread`, fmtPts(-Math.abs(m.s)), g.open?.s != null ? `Opened ${fmtPts(fav === 'home' ? g.open.s : -g.open.s)}${c ? ` · closed ${fmtPts(fav === 'home' ? c.s : -c.s)}` : ''}` : '']);
  if (m?.t != null) out.push(['Total', fmtTot(m.t), g.open?.t != null ? `Opened ${fmtTot(g.open.t)}${c ? ` · closed ${fmtTot(c.t)}` : ''}` : '']);
  // the model: ESPN's FPI win chance turned into points
  if (g.fpi != null) {
    const ms = spreadFromWin(g.fpi);
    const mf = ms < 0 ? 'home' : 'away';
    const edge = m?.s != null ? Math.round((m.s - ms) * 10) / 10 : null;
    out.push(['FPI model', `${g[mf].abbr} ${fmtPts(-Math.abs(ms))}`, `${fmtPct(g.fpi >= 0.5 ? g.fpi : 1 - g.fpi)} win chance for ${g[g.fpi >= 0.5 ? 'home' : 'away'].abbr}${edge ? ` · ${trim(Math.abs(edge))} pts ${edge > 0 ? `more on ${g.home.abbr}` : `more on ${g.away.abbr}`} than the market` : ''}`]);
  }
  const pin = g.books?.pin;
  if (pin?.ml?.[0] != null && pin?.ml?.[1] != null) {
    const nv = noVig(pin.ml[0], pin.ml[1]);
    out.push(['Pinnacle fair', fmtPct(Math.max(nv.a, nv.b), 1), `No-vig win chance for ${g[nv.a >= nv.b ? 'home' : 'away'].abbr}${g.pinLimit ? ` · limit ${fmtMoney(g.pinLimit)}` : ''}`]);
  }
  const w = g.wx || {};
  if (w.dome) out.push(['Weather', 'Dome', 'Indoors']);
  else if (w.wind != null || w.temp != null) out.push(['Wind', w.wind != null ? `${w.wind}<small>mph</small>` : '—', [w.gust ? `gusts ${w.gust}` : null, w.dir, w.temp != null ? `${w.temp}°` : null, w.pop != null ? `${w.pop}% rain` : null, w.cond].filter(Boolean).join(' · ')]);
  if (g.tickets) out.push(['Bets tracked', g.tickets.toLocaleString(), 'Tickets in the public count']);
  const windy = w.wind >= 15 ? `<p class="quote"><b>Windy.</b> Sustained wind around ${w.wind} mph with gusts to ${w.gust} tends to cut deep passing and long kicks, which pulls scoring down.</p>` : '';
  return `<div class="sub-h">The numbers</div><div class="kv" style="grid-template-columns:1fr 1fr">${out.slice(0, 6).map(([k, v, x]) => `<div><div class="k">${esc(k)}</div><div class="v num">${v}</div><div class="x">${esc(x)}</div></div>`).join('')}</div>${windy}`;
}

function splitsPanel(g) {
  const sp = g.splits;
  if (!sp || (!sp.s && !sp.t && !sp.ml)) return `<div class="sub-h">Where the money is</div><div class="card empty" style="padding:24px 16px;font-size:13px">No public betting splits for this game yet.</div>`;
  const bar = (label, left, right, a) => (a == null ? '' : `<div class="sp-row"><span>${esc(label)}</span><div class="bar2"><i style="width:${Math.max(a, 12)}%">${esc(left)} ${a}%</i><i>${100 - a}% ${esc(right)}</i></div></div>`);
  const part = (title, s, left, right, flip) => (!s ? '' : `<div class="sp"><div class="sp-h">${esc(title)}<span>${esc(left)} vs ${esc(right)}</span></div>${bar('Tickets', left, right, flip ? 100 - s.tix : s.tix)}${bar('Money', left, right, s.money == null ? null : flip ? 100 - s.money : s.money)}</div>`);
  const sig = signals(g);
  return `<div class="sub-h">Where the money is <span>Action Network public count</span></div><div class="card splits">
    ${part('Spread', sp.s, g.away.abbr, g.home.abbr, true)}${part('Total', sp.t, 'Over', 'Under', false)}${part('Moneyline', sp.ml, g.away.abbr, g.home.abbr, true)}
    ${sig.length ? sig.map((s) => `<p class="signal">${s.text}</p>`).join('') : '<p class="signal muted">No split between the public and the line movement yet.</p>'}</div>`;
}

function keysPanel(g) {
  const k = S.keys;
  const m = g.mkt;
  if (!k?.n || m?.s == null) return `<div class="sub-h">Key numbers</div><div class="card empty" style="padding:24px 16px;font-size:13px">Loading last season's margins…</div>`;
  const L = Math.abs(m.s);
  const lo = Math.max(1, Math.floor(L) - 6), hi = Math.floor(L) + 7;
  const range = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
  const mx = Math.max(...range.map((x) => k.margin[x] || 0), 1);
  const pct = (x) => ((k.margin[x] || 0) / k.n) * 100;
  const land = Number.isInteger(L) ? [L] : [Math.floor(L), Math.ceil(L)];
  const fav = favSide(g);
  const text = Number.isInteger(L)
    ? `At ${fmtPts(-L)}, a ${L}-point ${fav ? `${g[fav].abbr} ` : ''}win is a push. That exact margin happened in ${pct(L).toFixed(1)}% of NFL games last season.`
    : `At ${fmtPts(-L)}, a ${Math.ceil(L)}-point ${fav ? `${g[fav].abbr} ` : ''}win covers and a ${Math.floor(L)}-point win doesn't. ${Math.floor(L)} happened in ${pct(Math.floor(L)).toFixed(1)}% of games last season, ${Math.ceil(L)} in ${pct(Math.ceil(L)).toFixed(1)}%.`;
  const nearKey = [3, 7, 10, 14].find((x) => Math.abs(x - L) <= 1);
  return `<div class="sub-h">Key numbers <span>${k.season} NFL finals</span></div><div class="card keys">
    <div class="hist">${range.map((x) => `<div class="${land.includes(x) ? 'on' : [3, 7, 10, 14, 17, 21, 24, 28].includes(x) ? 'k' : ''}" title="${x}: ${pct(x).toFixed(1)}%"><i style="height:${((k.margin[x] || 0) / mx) * 100}%"></i><span>${x}</span></div>`).join('')}</div>
    <p>${esc(text)}${nearKey ? ` <b>${nearKey} is a key number</b>: getting the hook on the right side of it is worth shopping for.` : ''}</p></div>`;
}

function halfPanel(g) {
  const h = g.h1 || {};
  const keys = ['cons', ...visibleBooks().map((b) => b.key)].filter((k) => h[k]);
  const rows = keys.map((k) => {
    const L = h[k];
    const c = (m, side) => {
      const p = sideOf(L, m, side);
      if (p?.line == null) return '<span class="px na" aria-hidden="true">—</span>';
      const main = m === 'h1t' ? `${side === 'over' ? 'o' : 'u'}${fmtTot(p.line)}` : fmtPts(p.line);
      const who = side === 'over' ? 'First-half over' : side === 'under' ? 'First-half under' : `${teamName(g[side])} first half`;
      return `<button type="button" class="px num" data-bet="${g.id}|${m}|${side}|${k}" aria-label="${esc(`${bookFull(k)}, ${who} ${main}, ${fmtOdds(p.odds)}`)}">${esc(main)}<small>${esc(fmtOdds(p.odds))}</small></button>`;
    };
    return `<tr><td><div class="bk">${esc(bookName(k))}</div></td><td>${c('h1s', 'away')}</td><td>${c('h1s', 'home')}</td><td>${c('h1t', 'over')}</td><td>${c('h1t', 'under')}</td></tr>`;
  }).join('');
  const tt = g.tt ? ['away', 'home'].filter((s) => g.tt[s]).map((s) => `<div><div class="k">${esc(g[s].abbr)} team total</div><div class="v num">${fmtTot(g.tt[s].pts)}</div><div class="x">o ${esc(fmtOdds(g.tt[s].over))} · u ${esc(fmtOdds(g.tt[s].under))}</div></div>`).join('') : '';
  return `<div class="gs-grid">${rows ? `<div class="card" style="overflow-x:auto;padding-top:14px"><table class="btable"><thead><tr><th>1st half</th><th>${esc(g.away.abbr)}</th><th>${esc(g.home.abbr)}</th><th>Over</th><th>Under</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div></div>'}${tt ? `<div class="kv" style="grid-template-columns:1fr 1fr;align-self:start">${tt}</div>` : ''}</div>`;
}

function livePanel(g, sm) {
  const parts = [];
  if (sm.wp?.length > 2) {
    const W = 640, H = 150, n = sm.wp.length;
    const X = (i) => 8 + (i / (n - 1)) * (W - 16), Y = (v) => 8 + ((100 - v) / 100) * (H - 16);
    const d = sm.wp.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
    const last = sm.wp.at(-1);
    parts.push(`<div><div class="sub-h">Win probability <span>${esc(g.home.abbr)} ${last.toFixed(0)}% · per play</span></div><div class="card chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Win probability"><line class="gl" x1="8" x2="${W - 8}" y1="${Y(50)}" y2="${Y(50)}" stroke-dasharray="3 4"/><text class="ax" x="10" y="18">${esc(g.home.abbr)}</text><text class="ax" x="10" y="${H - 10}">${esc(g.away.abbr)}</text><polyline points="${d}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/><circle cx="${X(n - 1)}" cy="${Y(last)}" r="4" fill="var(--accent)"/></svg></div></div>`);
  }
  if (sm.box) {
    const order = ['yardsPerPlay', 'totalYards', 'netPassingYards', 'rushingYards', 'turnovers', 'thirdDownEff', 'firstDowns', 'possessionTime', 'totalPenaltiesYards'];
    const rows = order.filter((k) => sm.box[k]).map((k) => {
      const r = sm.box[k];
      const a = parseFloat(r.away), h = parseFloat(r.home);
      const better = k === 'turnovers' || k === 'totalPenaltiesYards' ? (a < h ? 'a' : h < a ? 'h' : '') : a > h ? 'a' : h > a ? 'h' : '';
      return `<tr><td class="${better === 'a' ? 'lead' : 'lag'}">${esc(r.away ?? '—')}</td><td>${esc(r.label)}</td><td class="${better === 'h' ? 'lead' : 'lag'}">${esc(r.home ?? '—')}</td></tr>`;
    }).join('');
    parts.push(`<div><div class="sub-h">Box score <span>${esc(g.away.abbr)} · ${esc(g.home.abbr)}</span></div><div class="card" style="padding:4px 0"><table class="box">${rows}</table></div></div>`);
  }
  const scoring = (sm.scoring || []).slice(-8).reverse();
  const sc = scoring.length ? `<div class="gs-sec"><div class="sub-h">Scoring</div><div class="card list">${scoring.map((p) => `<div class="li"><span class="tag">${esc(p.type || '')}</span><div><div>${esc((p.text || '').slice(0, 110))}</div><div class="m">${esc(quarter(p.q || 1))} ${esc(p.clock || '')}</div></div><div class="v num">${p.a}–${p.h}</div></div>`).join('')}</div></div>` : '';
  return `${parts.length ? `<div class="gs-grid gs-sec even">${parts.join('')}</div>` : ''}${sc}`;
}

// ------------------------------------------------------------ bet slip
const MKT_NAME = { s: 'Spread', t: 'Total', ml: 'Moneyline', h1s: '1st-half spread', h1t: '1st-half total', tt: 'Team total' };
function legFrom(g, mkt, side, book) {
  const src = mkt.startsWith('h1') ? g.h1 : isLive(g) ? g.live : g.books;
  const L = book ? src?.[book] : null;
  const p = sideOf(L, mkt, side) || {};
  return { gid: g.id, mkt, side, line: p.line ?? null, odds: p.odds ?? -110, book: book && book !== 'cons' && book !== 'open' ? book : '', live: isLive(g) };
}
function legLabel(g, l) {
  const t = l.side === 'home' || l.side === 'away' ? g[l.side] : null;
  if (l.mkt === 's') return `${t.abbr} ${fmtPts(l.line)}`;
  if (l.mkt === 'h1s') return `${t.abbr} 1H ${fmtPts(l.line)}`;
  if (l.mkt === 'ml') return `${t.abbr} ML`;
  if (l.mkt === 't') return `${l.side === 'over' ? 'Over' : 'Under'} ${fmtTot(l.line)}`;
  if (l.mkt === 'h1t') return `1H ${l.side === 'over' ? 'Over' : 'Under'} ${fmtTot(l.line)}`;
  if (l.mkt === 'tt') return `${g[l.team].abbr} ${l.side === 'over' ? 'o' : 'u'}${fmtTot(l.line)}`;
  return '';
}
// The fair price for the side from the sharpest book that has it, with the vig removed.
// The sharp read for one bet: the same calculation Edge Finder shows, so the slip and the list always agree.
// Pre-game only; live prices aren't compared. Returns { p, push, ev, book, est, conf } or null.
function fairFor(g, l) {
  if (!g || !isPre(g) || typeof edgePrice !== 'function') return null;
  const r = edgePrice(g, l.mkt, l.side, l.mkt === 'ml' ? null : l.line, l.odds, l.book || null);
  return r ? { p: r.p, push: r.push, ev: r.ev, book: r.src, est: r.est, conf: r.conf } : null;
}

// Where a bet slip was opened from (a game, Edges, Sweat Mode, the Time Machine) and how far down you were, so
// Add to parlay and Save bet put you back there instead of closing everything onto the tab underneath.
function sheetOrigin() {
  const s = S.sheet;
  if (!s) return null;
  if (s.kind === 'slip') return s.returnTo || null;
  const scroll = $('#dlgIn')?.scrollTop || 0;
  if (s.kind === 'game') return { kind: 'game', gid: s.gid, scroll };
  if (s.kind === 'edges' || s.kind === 'sweat') return { kind: s.kind, scroll };
  if (s.kind === 'tm') return { kind: 'tm', gid: s.gid, mkt: s.mkt, scroll };
  return null;
}
function returnFromSlip(r) {
  if (r?.kind === 'game') openGame(r.gid);
  else if (r?.kind === 'edges' && typeof edgeOpen === 'function') edgeOpen();
  else if (r?.kind === 'sweat' && typeof sweatOpen === 'function') sweatOpen();
  else if (r?.kind === 'tm' && typeof tmOpen === 'function') tmOpen(r.gid, r.mkt);
  else { closeSheet(); return; }
  if (r.scroll) requestAnimationFrame(() => requestAnimationFrame(() => { const box = $('#dlgIn'); if (box) box.scrollTop = r.scroll; }));
}

function openSlip(opts = {}) {
  let slip;
  if (opts.parlay) slip = { legs: S.parlay.map((l) => ({ ...l })), stake: S.unit, book: S.parlay.find((l) => l.book)?.book || '', parlay: true };
  else if (opts.gid) {
    const g = gameById(opts.gid);
    const l = legFrom(g, opts.mkt, opts.side, opts.book);
    slip = { legs: [l], stake: S.unit, book: l.book, odds: l.odds };
  } else slip = { legs: [], stake: S.unit, book: '', pick: true };
  S.sheet = { kind: 'slip', slip, returnTo: sheetOrigin() };
  paintSlip();
  showSheet('slip', true);
}

// Book icons shipped in public/icons/books; books without one get a clean monogram.
const BOOK_ICON = new Set(['circa', 'stn', 'czr', 'mgm', 'sp', 'wg', 'wynn', 'dk', 'fd', 'pin']);
function bookIcon(k, size = 32) {
  if (BOOK_ICON.has(k)) return `<img class="bk-ico" src="icons/books/${k}.png" width="${size}" height="${size}" alt="" loading="lazy">`;
  const name = k === 'other' ? '…' : (S.books.find((b) => b.key === k)?.short || k).replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase();
  return `<span class="bk-ico bk-mono" style="width:${size}px;height:${size}px" aria-hidden="true">${esc(name)}</span>`;
}
// Every book's price for this exact pick, best first, as big tappable tiles. Tapping one switches the slip to it.
function slipBooksHTML(g, l, sel) {
  const src = (l.mkt.startsWith('h1') ? g.h1 : isLive(g) ? g.live : g.books) || {};
  const m = l.mkt === 'h1s' ? 'h1s' : l.mkt;
  const rows = [];
  for (const b of visibleBooks()) {
    const L = src[b.key];
    const p = sideOf(L, m, l.side);
    if (!p || p.odds == null || (m !== 'ml' && p.line == null)) continue;
    rows.push({ k: b.key, p, typed: !!L?.m, old: isOld(L) });
  }
  if (!rows.length) return '';
  const best = bestOf(src, m, l.side)?.book;
  rows.sort((a, b) => (a.k === best ? -1 : b.k === best ? 1 : 0) || (better(m, l.side, a.p, b.p) ? -1 : better(m, l.side, b.p, a.p) ? 1 : 0));
  const priceTxt = (p) => (m === 'ml' ? fmtOdds(p.odds) : `${m === 't' || m === 'h1t' ? (l.side === 'over' ? 'o' : 'u') + fmtTot(p.line) : fmtPts(p.line)} ${fmtOdds(p.odds)}`);
  return `<div class="slip-books-h"><span>Where to bet</span><span>Tap a book to use its price · <button type="button" class="k-link" data-books>book links</button></span></div>
    <div class="slip-books" role="group" aria-label="Choose a book">${rows.map((r) => `<button type="button" class="bk-tile${sel === r.k ? ' on' : ''}${r.old ? ' old' : ''}" data-slip-book="${r.k}" aria-pressed="${sel === r.k}" aria-label="${esc(`${bookFull(r.k)}: ${priceTxt(r.p)}${r.k === best ? ', best price' : ''}${r.typed ? ', typed in' : ''}${r.old ? ', price may be old' : ''}`.replace(MINUS, 'minus '))}">
      ${bookIcon(r.k)}<span class="bk-n">${esc(bookName(r.k))}</span><span class="bk-p num">${esc(priceTxt(r.p))}</span>${r.k === best ? '<span class="bk-best">Best</span>' : r.typed ? '<span class="bk-best">Typed</span>' : ''}
    </button>`).join('')}
      <button type="button" class="bk-tile${sel === 'other' ? ' on' : ''}" data-slip-book="other" aria-pressed="${sel === 'other'}" aria-label="Another book">${bookIcon('other')}<span class="bk-n">Other</span><span class="bk-p">Type the price</span></button>
    </div>`;
}
// The parlay button follows what's in your parlay right now.
function slipBtnsHTML() {
  const sl = S.sheet.slip;
  const single = sl.legs.length === 1 && !sl.parlay;
  let parlayBtn = '', parlayLine = '';
  if (single) {
    const l = sl.legs[0];
    const n = S.parlay.length;
    const inIt = S.parlay.some((x) => x.gid === l.gid && x.mkt === l.mkt);
    const combo = n && Number.isFinite(l.odds) && Math.abs(l.odds) >= 100 ? toAm(S.parlay.reduce((p, x) => p * dec(x.odds), 1) * dec(l.odds)) : null;
    if (n) parlayLine = `<p class="slip-parlay">Your parlay: ${plural(n, 'leg')} · <span class="num">${esc(fmtOdds(toAm(S.parlay.reduce((p, x) => p * dec(x.odds), 1))))}</span> <button type="button" class="k-link" data-parlay-open>Review</button></p>`;
    parlayBtn = inIt ? `<button class="btn ghost" type="button" data-parlay-open>In your parlay ✓ · Review</button>`
      : n ? `<button class="btn ghost" type="button" data-addleg>Add as leg ${n + 1}${combo != null ? ` · <span class="num">${esc(fmtOdds(combo))}</span>` : ''}</button>`
      : `<button class="btn ghost" type="button" data-addleg>Start a parlay</button>`;
  }
  return `${parlayLine}<div class="row-btns">${parlayBtn}<button class="btn" type="button" data-savebet>Save bet</button></div>`;
}

function paintSlip() {
  const sl = S.sheet.slip;
  const body = $('#dlgBody');
  if (sl.pick && !sl.legs.length) { body.innerHTML = pickerHTML(); return; }
  const legs = sl.legs.map((l) => ({ l, g: gameById(l.gid) })).filter((x) => x.g);
  const single = legs.length === 1;
  const odds = slipOdds();
  const bookOpts = ['', ...S.books.map((b) => b.key), 'other'].map((k) => `<option value="${k}" ${sl.book === k ? 'selected' : ''}>${k ? esc(k === 'other' ? 'Other' : bookFull(k)) : 'Choose a book'}</option>`).join('');
  const lineVal = single && legs[0].l.mkt !== 'ml' ? (legs[0].l.mkt.endsWith('t') || legs[0].l.mkt === 'tt' ? fmtTot(legs[0].l.line) : fmtPts(legs[0].l.line).replace(MINUS, '-')) : '';
  body.innerHTML = `
    <h2 id="dlgTitle">${single ? 'Log this bet' : `${legs.length}-leg parlay`}</h2>
    <p class="lede">${single ? esc(MKT_NAME[legs[0].l.mkt] || '') : 'Every leg has to win. Pushes drop out.'}</p>
    ${legs.map(({ l, g }, i) => `<div class="card slip-pick" style="margin-top:12px"><div><b class="num">${esc(legLabel(g, l))}</b><span>${esc(g.away.abbr)} @ ${esc(g.home.abbr)} · ${esc(isLive(g) ? `live, ${clockLabel(g)}` : `${dayLabel(g.start)} ${timeLabel(g.start)}`)}${rotOf(g, l.side === 'home' ? 'home' : 'away') ? ` · rot ${rotOf(g, l.side === 'home' ? 'home' : 'away')}` : ''}</span></div>${single ? '' : `<span class="num" style="font-weight:600">${esc(fmtOdds(l.odds))}</span><button class="ibtn" type="button" data-rmleg="${i}" aria-label="Remove ${esc(legLabel(g, l))}">✕</button>`}</div>`).join('')}
    ${single && !sl.parlay ? slipBooksHTML(legs[0].g, legs[0].l, sl.book) : ''}
    <div class="fgrid">
      ${single && legs[0].l.mkt !== 'ml' ? `<label class="fld">Line<input class="inp" id="slLine" inputmode="text" autocomplete="off" value="${esc(lineVal)}"></label>` : ''}
      <label class="fld">${single ? 'Odds' : 'Ticket odds'}<input class="inp" id="slOdds" inputmode="text" autocomplete="off" value="${esc(Number.isFinite(odds) ? String(odds) : '')}"></label>
      <label class="fld">Stake ($)<input class="inp" id="slStake" inputmode="decimal" autocomplete="off" value="${esc(Number.isFinite(sl.stake) ? String(sl.stake) : '')}"></label>
      ${single && !sl.parlay && sl.book !== 'other' ? '' : `<label class="fld">Book<select class="inp" id="slBook">${bookOpts}</select></label>`}
      <label class="fld full">Note<input class="inp" id="slNote" style="font-weight:500;font-size:15px" placeholder="Optional: why you like it" value="${esc(sl.note || '')}"></label>
    </div>
    <div id="slCalc">${slipCalcHTML()}</div>
    <div class="err" id="slErr" role="alert"></div>
    <div id="slBtns">${slipBtnsHTML()}</div>`;
  // Keep the chosen book's tile in view.
  const on = body.querySelector('.bk-tile.on');
  if (on) on.parentElement.scrollLeft = Math.max(0, on.offsetLeft - on.parentElement.offsetLeft - 16);
}
function slipOdds() {
  const sl = S.sheet.slip;
  if (sl.legs.length === 1) return sl.legs[0].odds;
  if (Number.isFinite(sl.odds) && sl.odds !== sl.autoOdds) return sl.odds;
  sl.autoOdds = toAm(sl.legs.reduce((p, l) => p * dec(l.odds), 1));
  return sl.autoOdds;
}
// Payout, implied chance and edge against the sharp fair price. Redrawn on every keystroke.
function slipCalcHTML() {
  const sl = S.sheet.slip;
  const legs = sl.legs.map((l) => ({ l, g: gameById(l.gid) })).filter((x) => x.g);
  const single = legs.length === 1;
  const odds = slipOdds();
  const okOdds = Number.isFinite(odds) && Math.abs(odds) >= 100;
  const win = okOdds && sl.stake > 0 ? toWin(sl.stake, odds) : null;
  const fair = single && okOdds ? fairFor(legs[0].g, legs[0].l) : null;
  const edge = fair ? fair.ev : null;
  const l0 = legs[0]?.l;
  const words = !single || !l0 ? '' : l0.mkt === 's' && Number.isFinite(l0.line) ? spreadWords(legs[0].g[l0.side], l0.line) : l0.mkt === 't' && Number.isFinite(l0.line) ? totalWords(l0.line) : l0.mkt === 'ml' && okOdds ? oddsWords(l0.odds) : '';
  return `<div class="calc"><div><div class="k">To win</div><div class="v num">${win == null ? '—' : fmtMoney(Math.round(win * 100) / 100)}</div></div><div><div class="k">Implied</div><div class="v num">${okOdds ? fmtPct(imp(odds), 1) : '—'}</div></div><div><div class="k">${fair ? `vs ${esc(bookName(fair.book))}${fair.est ? ' (est.)' : ''}` : 'vs sharp'}</div><div class="v num soft">${edge == null ? '—' : `${fair.est ? '≈ ' : ''}${edge >= 0 ? '+' : MINUS}${Math.abs(Math.round(edge * 100))}%`}</div></div></div>
    ${kellySlipHTML(fair, odds, okOdds, sl.stake)}
    ${words || fair ? `<p class="note">${esc(words)}${fair ? ` With the cut removed, ${esc(bookName(fair.book))}’s price implies about ${Math.round(fair.p * 100)}% for this side: the market’s estimate, not a sure thing. ${fair.ev > 0 ? `Reading: ${esc(EDGE_CONF[fair.conf] || '')}.` : 'This price is at or below the sharp price.'}` : ''}</p>` : ''}
    ${bookLinkHTML(single ? S.sheet.slip.book : '')}`;
}
// Kelly sizing, only when asked: collapsed by default, never pre-fills the stake, and needs a bankroll you entered.
function kellySlipHTML(fair, odds, okOdds, stake) {
  if (!fair || !okOdds) return '';
  const c = kellyCfg();
  const open = S.sheet?.slip?.kOpen ? ' open' : '';
  if (!c.bankroll) return `<details class="k-slip"${open}><summary>Kelly sizing</summary><p>Kelly sizing needs a bankroll. <button type="button" class="k-link" data-kelly-settings>Set one in Tools</button></p></details>`;
  const k = kellyStake(fair.p * (1 - (fair.push || 0)), odds, fair.push || 0);
  if (!k) return '';
  if (!k.dollars) return `<details class="k-slip"${open}><summary>Kelly sizing</summary><p>At ${esc(fmtOdds(odds))} this is at or below the sharp price, so Kelly sizing is $0.</p></details>`;
  const same = Math.abs((stake || 0) - k.dollars) < 0.5;
  return `<details class="k-slip"${open}><summary>Kelly sizing</summary><p>At your ${esc(kellyName())} settings this works out to <b class="num">${esc(fmtMoney(k.dollars))}</b> (${(k.pct * 100).toFixed(1)}% of your bankroll${k.capped ? ', held to your cap' : ''}). Kelly assumes the win chance is right; if it’s too high, Kelly bets too much.</p>${same ? '<span class="k-on">Stake matches</span>' : `<button type="button" class="k-link" data-kelly-use="${k.dollars}">Put ${esc(fmtMoney(k.dollars))} in the stake</button>`}</details>`;
}
// Where to place it: the book's own site and its Nevada app. You sign in at the book — this app never asks
// for a sportsbook login and never places a bet.
function bookLinkHTML(book) {
  const site = bookSite(book), app = bookApp(book);
  if (!site && !app) return `<p class="book-go"><button type="button" class="k-link" data-books>Where to bet ↗</button><span>Pick a Nevada book to place this at.</span></p>`;
  const links = [site ? `<a class="k-link" href="${site}" target="_blank" rel="noopener noreferrer">Open ${esc(bookFull(book))} ↗</a>` : '',
                 app ? `<a class="k-link" href="${app}" target="_blank" rel="noopener noreferrer">Get the app ↗</a>` : ''].filter(Boolean).join('');
  return `<p class="book-go">${links}<span>You sign in at the book. Prices there can differ from what’s shown here — check the ticket before you bet.</span></p>`;
}

// ------------------------------------------------------------ where to bet
// Every Nevada book on the board, with the two ways in. Nothing here takes a login: the links open the book's
// own site or its App Store page, and the account stays entirely between you and the book.
function openBooks() {
  S.sheet = { kind: 'books' };
  const nv = S.books.filter((b) => b.vegas);
  const off = S.books.filter((b) => !b.vegas);
  const row = (b) => {
    const links = [b.site ? `<a class="btn ghost sm" href="${b.site}" target="_blank" rel="noopener noreferrer">Open site ↗</a>` : '',
                   b.ios ? `<a class="btn ghost sm" href="${b.ios}" target="_blank" rel="noopener noreferrer">Get the app ↗</a>` : ''].filter(Boolean).join('');
    const tags = [b.sharp ? '<span class="tag sharp">Sharp</span>' : '', b.feed ? '<span class="tag">Live on the board</span>' : '<span class="tag">Counter numbers</span>'].join('');
    return `<div class="bk-row">${bookIcon(b.key, 36)}<div class="bk-row-m"><b>${esc(b.name)}</b><div class="tags">${tags}</div></div>
      <div class="bk-row-go">${links || '<span class="m">No app or site — at the window only</span>'}</div></div>`;
  };
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">Where to bet</h2>
    <p class="lede">Pick Six shows the numbers. The bet is placed at the book: these open the book's own site or its Nevada app, where you sign in yourself. This app never asks for a sportsbook login, never stores one, and never places a bet for you.</p>
    <div class="card bk-note"><b>Two things Nevada asks first</b>Nevada apps make you sign up in person at the casino once, with ID. After that you can bet from your phone, but only while you're inside the state.</div>
    <div class="sub-h" style="margin-top:20px">Nevada books</div>
    <div class="card list bk-list">${nv.map(row).join('')}</div>
    <div class="sub-h" style="margin-top:20px">On the board for comparison</div>
    <p class="m" style="margin:0 0 8px">${esc(off.map((b) => b.name).join(', '))} don't take Nevada bets. They're here because ${esc(off.some((b) => b.sharp) ? 'the sharp offshore number and the big national apps tell you where the market really is' : 'the big national apps tell you where the market really is')}.</p>
    <button class="btn ghost" type="button" data-closesheet>Done</button>`;
  showSheet('books', true);
}
document.addEventListener('toggle', (ev) => { if (ev.target.matches?.('.k-slip') && S.sheet?.slip) S.sheet.slip.kOpen = ev.target.open; }, true);
function updateSlipCalc() {
  const el = $('#slCalc');
  if (el) el.innerHTML = slipCalcHTML();
  const bt = $('#slBtns');
  if (bt) bt.innerHTML = slipBtnsHTML();
  showSlipProblems([]);
}

function pickerHTML() {
  const games = allGames().filter((g) => !isFinal(g)).sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  return `<h2 id="dlgTitle">Log a bet</h2><p class="lede">Pick the game, then the side. Or tap any price on the board.</p>
    <div class="fgrid"><label class="fld full">Game<select class="inp" id="pkGame"><option value="">Choose a game</option>${games.map((g) => `<option value="${g.id}">${esc(`${dayLabel(g.start)} ${timeLabel(g.start)} · ${g.away.short} @ ${g.home.short}`)}</option>`).join('')}</select></label></div>
    <div id="pkSides" style="margin-top:16px"></div>`;
}
function pickerSides(gid) {
  const g = gameById(gid);
  if (!g) return '';
  const mk = marketKey(g, 's') || 'cons';
  const btn = (mkt, side, label) => { const p = sideOf((isLive(g) ? g.live : g.books)?.[mk], mkt, side); return `<button class="chip" type="button" data-pick="${g.id}|${mkt}|${side}|${mk}">${esc(label)}${p ? ` <small>${esc(mkt === 'ml' ? fmtOdds(p.odds) : mkt === 't' ? fmtTot(p.line) : fmtPts(p.line))}</small>` : ''}</button>`; };
  return `<div class="sub-h">Spread</div><div class="chips">${btn('s', 'away', g.away.abbr)}${btn('s', 'home', g.home.abbr)}</div>
    <div class="sub-h" style="margin-top:16px">Total</div><div class="chips">${btn('t', 'over', 'Over')}${btn('t', 'under', 'Under')}</div>
    <div class="sub-h" style="margin-top:16px">Moneyline</div><div class="chips">${btn('ml', 'away', g.away.abbr)}${btn('ml', 'home', g.home.abbr)}</div>`;
}

function readSlip() {
  const sl = S.sheet.slip;
  const num = (id) => {
    const v = $(id)?.value;
    if (v == null) return undefined;
    const t = String(v).trim().replace(MINUS, '-');
    if (/^pk$/i.test(t)) return 0;
    if (/^ev(en)?$/i.test(t)) return 100;
    const n = Number(t.replace(/[$,\s]/g, '').replace(/^\+/, ''));
    return t === '' ? NaN : n;
  };
  const line = num('#slLine'), odds = num('#slOdds'), stake = num('#slStake');
  if (line !== undefined && sl.legs.length === 1) sl.legs[0].line = line;
  if (odds !== undefined) { if (sl.legs.length === 1) sl.legs[0].odds = odds; sl.odds = odds; }
  if (stake !== undefined) sl.stake = stake;
  sl.book = $('#slBook')?.value ?? sl.book;
  sl.note = $('#slNote')?.value ?? sl.note;
}

// Returns a list of [fieldId, message]; empty means the slip is good to save.
function slipProblems() {
  const sl = S.sheet.slip;
  const out = [];
  if (!(sl.stake > 0) || !Number.isFinite(sl.stake)) out.push(['#slStake', 'Enter how much you risked.']);
  const odds = sl.legs.length === 1 ? sl.legs[0].odds : sl.odds;
  if (!Number.isFinite(odds) || Math.abs(odds) < 100) out.push(['#slOdds', 'Use American odds like −110 or +150.']);
  if (sl.legs.length === 1 && sl.legs[0].mkt !== 'ml' && !Number.isFinite(sl.legs[0].line)) out.push(['#slLine', 'Enter the line, like −3.5 or 51.5.']);
  return out;
}
function showSlipProblems(list) {
  for (const id of ['#slStake', '#slOdds', '#slLine']) { const el = $(id); if (el) { el.removeAttribute('aria-invalid'); el.parentElement.querySelector('.hint')?.remove(); } }
  for (const [id, msg] of list) {
    const el = $(id);
    if (!el) continue;
    el.setAttribute('aria-invalid', 'true');
    el.insertAdjacentHTML('afterend', `<span class="hint err">${esc(msg)}</span>`);
  }
  if (list.length) $(list[0][0])?.focus();
}

async function saveBet() {
  readSlip();
  const problems = slipProblems();
  showSlipProblems(problems);
  if (problems.length) return;
  if (typeof limGate === 'function' && !limGate()) return; // past a play limit: say so once, then "Save anyway" (limits.js)
  const sl = S.sheet.slip;
  const legs = sl.legs.map((l) => { const g = gameById(l.gid); return { ...l, label: legLabel(g, l), matchup: `${g.away.abbr} @ ${g.home.abbr}`, start: g.start }; });
  try {
    const bet = await api('/api/bets', { method: 'POST', body: JSON.stringify({ legs, stake: sl.stake, odds: legs.length > 1 ? sl.odds : undefined, book: sl.book === 'other' ? 'Other' : sl.book ? bookFull(sl.book) : '', note: sl.note }) });
    if (sl.parlay) S.parlay = [];
    const back = S.sheet.returnTo;
    toastText('Bet saved. It grades itself when the game ends.', { label: 'Undo', run: () => api(`/api/bets/${bet.id}`, { method: 'DELETE' }).catch((e) => toastText(e.message)) });
    returnFromSlip(back);
    invalidate();
  } catch (e) {
    $('#slErr').textContent = e.message;
  }
}

// ------------------------------------------------------------ swipe a sheet down to close (phones)
(() => {
  const d = $('#dlg');
  let y0 = null, dy = 0;
  d.addEventListener('touchstart', (e) => {
    const inner = $('#dlgIn');
    if (inner.scrollTop > 0 || e.target.closest('input, select, textarea, .chart, .bt-wrap, .strip')) { y0 = null; return; }
    y0 = e.touches[0].clientY; dy = 0; d.classList.add('drag');
  }, { passive: true });
  d.addEventListener('touchmove', (e) => {
    if (y0 == null) return;
    dy = Math.max(0, e.touches[0].clientY - y0);
    d.style.transform = dy ? `translateY(${dy}px)` : '';
  }, { passive: true });
  d.addEventListener('touchend', () => {
    if (y0 == null) return;
    d.classList.remove('drag');
    y0 = null;
    if (dy > 110) { d.style.transform = ''; closeSheet(); return; }
    d.classList.add('snap');
    d.style.transform = '';
    setTimeout(() => d.classList.remove('snap'), 260);
  });
})();

// ------------------------------------------------------------ counter numbers
function openCounter(gid) {
  const g = gameById(gid);
  if (!g) return;
  const books = S.books.filter((b) => b.vegas || b.sharp);
  S.sheet = { kind: 'counter', gid, book: books.find((b) => !b.feed)?.key || books[0]?.key, fav: favSide(g) || 'home', returnTo: gid };
  paintCounter();
  showSheet('counter', true);
}
function paintCounter() {
  const { gid, book, fav } = S.sheet;
  const g = gameById(gid);
  const L = g.books?.[book];
  const cur = L ? { s: L.s == null ? '' : trim(Math.abs(L.s)), t: L.t == null ? '' : trim(L.t) } : { s: '', t: '' };
  const books = S.books.filter((b) => b.vegas || b.sharp);
  const mine = Object.entries(g.books || {}).filter(([, x]) => x.m);
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">Add a number</h2><p class="lede">Standing at a window? Type what the board says. It shows on <em>your</em> board with a thin outline and a timestamp — nobody else sharing this app sees it — and the next live update from that book replaces it.</p>
    <div class="sub-h" style="margin-top:16px">Book</div><div class="chips">${books.map((b) => `<button class="chip" type="button" data-cbook="${b.key}" aria-pressed="${b.key === book}">${esc(b.short)}${b.feed ? '' : ' <small>counter</small>'}</button>`).join('')}</div>
    <div class="sub-h" style="margin-top:16px">Favorite</div><div class="chips"><button class="chip" type="button" data-cfav="away" aria-pressed="${fav === 'away'}">${esc(g.away.abbr)}</button><button class="chip" type="button" data-cfav="home" aria-pressed="${fav === 'home'}">${esc(g.home.abbr)}</button></div>
    <div class="fgrid">
      <label class="fld">Spread (favorite gives)<input class="inp" id="cS" inputmode="decimal" placeholder="e.g. 3.5" value="${esc(cur.s)}"></label>
      <label class="fld">Juice on favorite<input class="inp" id="cSo" inputmode="text" value="-110"></label>
      <label class="fld">Total<input class="inp" id="cT" inputmode="decimal" placeholder="e.g. 51.5" value="${esc(cur.t)}"></label>
      <label class="fld">Over juice<input class="inp" id="cTo" inputmode="text" value="-110"></label>
      <label class="fld">${esc(g.away.abbr)} moneyline<input class="inp" id="cMa" inputmode="text" placeholder="optional"></label>
      <label class="fld">${esc(g.home.abbr)} moneyline<input class="inp" id="cMh" inputmode="text" placeholder="optional"></label>
    </div>
    <div class="err" id="cErr"></div>
    <button class="btn" type="button" data-csave>Save number</button>
    ${mine.length ? `<div class="sub-h" style="margin-top:24px">Typed in for this game</div><div class="card list">${mine.map(([k, x]) => `<div class="li"><span class="tag">${esc(bookName(k))}</span><div><div>${esc(favLine(g, x))} · ${esc(fmtTot(x.t))}</div><div class="m">${esc(ago(x.at))}</div></div><button class="lg" type="button" data-cdel="${k}">Remove</button></div>`).join('')}</div>` : ''}
    <button class="btn ghost" type="button" data-back="${gid}">Back to the game</button>`;
}
async function saveCounter() {
  const { gid, book, fav } = S.sheet;
  const n = (id) => { const v = String($(id).value || '').trim().replace(MINUS, '-'); if (!v) return null; if (/^pk$/i.test(v)) return 0; const x = Number(v.replace(/^\+/, '')); return Number.isFinite(x) ? x : NaN; };
  const s = n('#cS'), so = n('#cSo') ?? -110, t = n('#cT'), to = n('#cTo') ?? -110, ma = n('#cMa'), mh = n('#cMh');
  if ([s, so, t, to, ma, mh].some((x) => Number.isNaN(x))) { $('#cErr').textContent = 'One of those numbers doesn’t read right.'; return; }
  const home = s == null ? null : fav === 'home' ? -Math.abs(s) : Math.abs(s);
  const other = (o) => (o == null ? -110 : o < 0 ? -(220 + o) : -110); // mirror the juice on the other side (e.g. -120 / +100)
  try {
    const L = await api('/api/manual', { method: 'POST', body: JSON.stringify({ gid, book, s: home, so: fav === 'home' ? [so, other(so)] : [other(so), so], t, to: [to, other(to)], ml: [mh, ma] }) });
    (S.mine[gid] ||= {})[book] = L;
    repaintMine(gid);
    toastText(`${bookName(book)} number saved. It shows on your board only.`);
    openGame(gid);
  } catch (e) { $('#cErr').textContent = e.message; }
}

// ------------------------------------------------------------ phone
async function openPhone() {
  S.sheet = { kind: 'phone' };
  $('#dlgBody').innerHTML = '<div class="empty"><b>Finding this Mac on Wi-Fi…</b></div>';
  showSheet('phone', true);
  let url = null, pub = false;
  try { const j = await api('/api/lan'); url = j.urls?.[0] || null; pub = !!j.public; } catch { /* offline */ }
  $('#dlgBody').innerHTML = `<h2 id="dlgTitle">Open on your iPhone</h2><p class="lede">${pub ? 'This link works anywhere, on Wi-Fi or cellular.' : 'Your phone needs to be on the same Wi-Fi as this Mac.'}</p>
    ${url ? `<div class="qr" id="qr"></div><div class="url">${esc(url)}</div>` : '<div class="card empty" style="margin-top:24px"><b>No Wi-Fi address found</b>Connect this Mac to Wi-Fi and try again.</div>'}
    <ol class="steps"><li><b>1</b><span>Point the iPhone camera at the code and tap the link.</span></li><li><b>2</b><span>In Safari, tap Share, then <strong>Add to Home Screen</strong>.</span></li><li><b>3</b><span>Turn on alerts with the bell to hear line moves and cover changes.</span></li></ol>`;
  if (!url) return;
  const draw = () => { try { new QRCode($('#qr'), { text: url, width: 200, height: 200, colorDark: '#0B0B0D', colorLight: '#FFFFFF' }); } catch { $('#qr')?.remove(); } };
  if (window.QRCode) return draw();
  const sc = document.createElement('script');
  sc.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
  sc.onload = draw;
  sc.onerror = () => $('#qr')?.remove();
  document.head.appendChild(sc);
}
