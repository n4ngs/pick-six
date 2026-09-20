'use strict';
/* Pick Six — the four tabs: Live, Board, My bets, Tools. */

function renderAll() {
  renderPill();
  renderNav();
  renderTray();
  // While a sheet covers the screen, leave the tab underneath alone: on a full Sunday the board is thousands of nodes and
  // rebuilding it on every live update froze phones mid-tap (and got the app restarted). closeSheet() catches up.
  if (S.sheet && dlg().open && renderAll.drawn === S.tab) { refreshSheet(); return; }
  renderAll.drawn = S.tab; // each tab still draws once, so a sheet opened at start-up has something behind it
  if (S.tab === 'live') renderLive();
  if (S.tab === 'board') renderBoard();
  if (S.tab === 'bets') renderBets();
  if (S.tab === 'tools') renderTools();
  renderFoot();
  if (S.sheet) refreshSheet();
}

// ------------------------------------------------------------ top bar
function renderPill() {
  const pill = $('#livePill');
  const n = liveGames().length;
  pill.classList.toggle('stale', !S.connected);
  $('#liveText').textContent = !S.connected ? 'Reconnecting' : n ? `Live · ${plural(n, 'game')}` : 'Up to date';
  pill.querySelector('.dot').classList.toggle('pulse', S.connected && n > 0);
}
function renderNav() {
  const open = S.bets.filter((b) => b.status === 'open');
  const live = open.filter((b) => b.legs.some((l) => isLive(gameById(l.gid)))).length;
  for (const id of ['#betBadge', '#betBadgeD']) {
    const el = $(id);
    el.hidden = !live;
    el.textContent = live;
  }
}

// ------------------------------------------------------------ shared selectors
const allGames = () => [...new Map([...S.weeks.values()].filter((w) => S.tracked.includes(w.meta.id)).flatMap((w) => [...w.games.values()]).map((g) => [g.id, g])).values()];
const liveGames = () => allGames().filter(isLive);
const todayGames = () => allGames().filter((g) => g.day === todayET() || isLive(g));
const openLegs = () => S.bets.filter((b) => b.status === 'open').flatMap((b) => b.legs.map((l) => ({ ...l, bet: b })));

// Covered or not, from the closing line: "ALA covered", "Over".
function atsResult(g) {
  const c = g.close || g.mkt;
  if (!isFinal(g) || !c) return null;
  const out = {};
  if (c.s != null) {
    const m = (g.home.score - g.away.score) + c.s;
    out.side = m > 0 ? 'home' : m < 0 ? 'away' : null;
    out.s = m === 0 ? 'Push' : `${g[out.side].abbr} covered`;
    const fav = c.s < 0 ? 'home' : c.s > 0 ? 'away' : null;
    out.favCovered = fav ? out.side === fav : null;
  }
  if (c.t != null) {
    const t = g.home.score + g.away.score;
    out.t = t > c.t ? 'Over' : t < c.t ? 'Under' : 'Push';
  }
  return out;
}

// The favorite's number, "ALA −19.5".
function favLine(g, L = g.mkt) {
  if (!L || L.s == null) return '—';
  if (L.s === 0) return 'PK';
  const f = L.s < 0 ? g.home : g.away;
  return `${f.abbr} ${fmtPts(-Math.abs(L.s))}`;
}

// How exciting a live game is right now, for picking the hero.
function drama(g) {
  const p = g.prob?.home ?? 0.5;
  const close = 1 - Math.abs(p - 0.5) * 2;
  const late = 1 - remaining(g);
  const ranked = (g.home.rank || g.away.rank) ? 0.35 : 0;
  const mine = openLegs().some((l) => l.gid === g.id) ? 3 : 0;
  const pop = Math.log10((g.tickets || 10) + 1) / 8;
  return close * 1.4 + late * 0.8 + ranked + pop + mine;
}

// ------------------------------------------------------------ LIVE
function renderLive() {
  const games = todayGames();
  const live = games.filter(isLive).sort((a, b) => drama(b) - drama(a));
  const pre = games.filter(isPre).sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  const done = games.filter(isFinal);
  const W = defWeek();

  // headline
  const next = pre[0] || allGames().filter(isPre).sort((a, b) => Date.parse(a.start) - Date.parse(b.start))[0];
  if (live.length) {
    $('#headline').textContent = `${plural(live.length, 'game')} live`;
    $('#subline').textContent = [pre.length && `${pre.length} more kick off today`, next && `next at ${timeLabel(next.start)}`, done.length && `${done.length} final`].filter(Boolean).join(' · ');
  } else if (pre.length) {
    $('#headline').textContent = `${plural(games.length, 'game')} today`;
    $('#subline').textContent = `First kickoff ${timeLabel(pre[0].start)} · ${W?.meta.label || ''}`;
  } else if (done.length) {
    $('#headline').textContent = 'All final today';
    $('#subline').textContent = next ? `Next kickoff ${dayLabel(next.start)} ${timeLabel(next.start)} · ${gameById(next.id)?.wk === S.def ? W?.meta.label : 'next week'}` : '';
  } else {
    $('#headline').textContent = next ? `${W?.meta.label || 'This week'}` : 'NFL';
    $('#subline').textContent = next ? `No games today. Next kickoff ${dayLabel(next.start, true)}, ${timeLabel(next.start)}.` : 'Loading…';
  }

  // desktop numbers next to the headline
  const g8 = glanceNumbers(games);
  $('#glanceTop').innerHTML = [
    ['Live now', live.length, ''],
    ['Favorites ATS', g8.fav, g8.favSub],
    ['Overs', g8.over, g8.overSub],
  ].map(([l, v, s]) => `<div><div class="v num">${v}</div><div class="l">${esc(l)}${s ? ` · ${esc(s)}` : ''}</div></div>`).join('');

  renderMoveCards();
  if (typeof edgeLive === 'function' && !(typeof limBreak === 'function' && limBreak())) edgeLive(); // Edge Finder: top edges on the Live tab (edge.js)
  else $('#edgeTop')?.remove(); // hidden while you're taking a break (limits.js)
  renderHero(live, pre);
  renderHeroSide();

  // scores strip
  const strip = [...live, ...pre, ...done.sort((a, b) => Date.parse(b.start) - Date.parse(a.start))];
  $('#scoreMeta').textContent = strip.length ? `All ${strip.length} ›` : 'Board ›';
  $('#strip').innerHTML = strip.length ? strip.slice(0, 40).map(stripCard).join('') : `<div class="gm" style="width:auto"><div class="gm-h">No games today</div><div class="muted" style="font-size:13px">Lines for the week are on the board.</div></div>`;

  // on the field
  $('#liveSec').hidden = !live.length;
  $('#liveMeta').textContent = live.length ? `${live.filter((g) => g.sit?.rz).length ? `${live.filter((g) => g.sit?.rz).length} in the red zone · ` : ''}updates every ${Math.round(S.liveMs / 1000)}s` : '';
  $('#liveCards').innerHTML = live.map(liveCard).join('');

  // glance (phone)
  $('#glance').innerHTML = [
    [g8.fav, 'Favorites ATS', g8.favSub || 'Against the closing spread'],
    [g8.over, 'Overs', g8.overSub || 'Against the closing total'],
    [g8.upset, 'Biggest upset', g8.upsetSub],
    [g8.move, 'Biggest move', g8.moveSub],
  ].map(([v, l, s]) => `<div><div class="v num">${v}</div><div class="l">${esc(l)}</div><div class="s">${esc(s || '')}</div></div>`).join('');

  renderLearn();
}

function glanceNumbers(games) {
  const fin = games.filter(isFinal).map((g) => ({ g, r: atsResult(g) })).filter((x) => x.r);
  const fw = fin.filter((x) => x.r.favCovered === true).length, fl = fin.filter((x) => x.r.favCovered === false).length;
  const ov = fin.filter((x) => x.r.t === 'Over').length, un = fin.filter((x) => x.r.t === 'Under').length;
  // biggest upset: the longest moneyline underdog that won today
  let upset = null;
  for (const { g } of fin) {
    const c = g.close || g.mkt;
    if (!c?.ml) continue;
    const winner = g.home.score > g.away.score ? 'home' : 'away';
    const o = winner === 'home' ? c.ml[0] : c.ml[1];
    if (o > 0 && (!upset || o > upset.o)) upset = { o, g, winner };
  }
  // biggest move this week, open to now
  let move = null;
  for (const g of defWeek() ? [...defWeek().games.values()] : []) {
    if (g.open?.s == null || g.mkt?.s == null) continue;
    const d = Math.abs(g.mkt.s - g.open.s);
    if (!move || d > move.d) move = { d, g };
  }
  return {
    fav: fin.length ? `${fw}–${fl}` : '—', favSub: fin.length ? `${plural(fin.length, 'final')}` : 'No finals yet',
    over: fin.length ? `${ov}–${un}` : '—', overSub: fin.length ? `Over–under` : '',
    upset: upset ? fmtOdds(upset.o) : '—', upsetSub: upset ? `${upset.g[upset.winner].abbr} beat ${upset.g[upset.winner === 'home' ? 'away' : 'home'].abbr}` : 'None yet',
    move: move ? `${trim(move.d)}` : '—', moveSub: move ? `${move.g.away.abbr} @ ${move.g.home.abbr}: ${fmtPts(move.g.open.s)} → ${fmtPts(move.g.mkt.s)} (home)` : '',
  };
}

// The early signal: a line that just moved. Shows for 20 minutes.
function renderMoveCards() {
  const seen = new Set();
  const fresh = S.moves.filter((m) => serverNow() - m.t < 20 * 60e3 && gameById(m.gid) && isPre(gameById(m.gid)))
    .sort((a, b) => (b.kind === 'steam') - (a.kind === 'steam') || b.t - a.t)
    .filter((m) => { const k = `${m.gid}|${m.mkt}`; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 2);
  $('#moveSlot').innerHTML = fresh.map((m) => {
    const g = gameById(m.gid);
    const tx = moveText(m, g);
    const kicker = m.kind === 'steam' ? `Steam · ${m.books?.length || 3} books${m.secs != null ? ` in ${Math.max(1, Math.round(m.secs / 60))} min` : ''}` : moveWord[m.kind];
    const t = m.dir === 'over' || m.dir === 'under' ? null : g[m.dir];
    return `<button class="card mv" type="button" data-open="${g.id}">
      <div class="mv-top"><span class="lab"><span class="dot pulse"></span>${esc(kicker)}</span><span class="muted">${esc(ago(m.t))}</span></div>
      <div class="mv-main">${t ? logo(t, 'logo') : ''}<div class="who"><b>${esc(tx.title)}</b><span>${esc(g.away.short)} @ ${esc(g.home.short)} · ${esc(dayLabel(g.start))} ${esc(timeLabel(g.start))}</span></div>
        <div class="mv-num num"><s>${esc(tx.from.replace(/^[A-Z&]+ /, ''))}</s>${esc(tx.to.replace(/^[A-Z&]+ /, ''))}</div></div>
      <div class="mv-foot"><span>${m.books?.length ? `${esc(m.books.map(bookName).join(', '))}` : 'Market consensus'}</span><span>${esc(m.mkt === 't' ? 'Total' : 'Spread')} ${ICON.chev}</span></div>
      <div class="wait"></div></button>`;
  }).join('');
}

function renderHero(live, pre) {
  const hero = $('#hero');
  const myLive = openLegs().filter((l) => isLive(gameById(l.gid)));
  if (myLive.length) {
    // Your sweat: every live leg, most urgent first.
    const rows = myLive.map((l) => ({ l, g: gameById(l.gid), now: legNow(gameById(l.gid), l) })).sort((a, b) => Math.abs(a.now) - Math.abs(b.now));
    hero.innerHTML = `<div class="hero-lab"><b><span class="dot pulse"></span>Your sweat</b><button type="button" class="sweat-open" data-sweat-open>${plural(myLive.length, 'live bet')} · Sweat mode ${ICON.chev}</button></div>
      <div class="card hcard">${rows.map(({ l, g, now }) => sweatRow(l, g, now)).join('')}</div>`;
    return;
  }
  const g = live[0];
  if (g) { hero.innerHTML = heroLive(g); return; }
  const up = pre.slice(0, 12).sort((a, b) => interest(b) - interest(a))[0] || allGames().filter(isPre).sort((a, b) => Date.parse(a.start) - Date.parse(b.start))[0];
  hero.innerHTML = up ? heroPre(up) : '';
}
const interest = (g) => (g.home.rank ? 30 - g.home.rank : 0) + (g.away.rank ? 30 - g.away.rank : 0) + Math.log10((g.tickets || 1) + 1) * 4 - Date.parse(g.start) / 3.6e6 / 6;

function sweatRow(l, g, now) {
  const p = coverChance(g, l);
  const win = now > 0;
  const pos = clamp(50 + (now / 28) * 50, 2, 98);
  return `<div class="bet-leg" data-open="${g.id}">
    <div class="leg-h">${esc(l.label)} <span class="cov ${now > 0 ? 'win' : now < 0 ? 'lose' : 'push'}">${now > 0 ? `Covering by ${trim(now)}` : now < 0 ? `Needs ${trim(-now + (Number.isInteger(l.line) ? 1 : 0.5))}` : 'Push right now'}</span></div>
    <div class="leg-s"><span>${esc(g.away.abbr)} <b>${g.away.score}</b> · ${esc(g.home.abbr)} <b>${g.home.score}</b> · ${esc(clockLabel(g))}${g.sit?.rz ? ' · <b class="rz">Red zone</b>' : ''}</span><span>${p != null ? `${fmtPct(p)} to cash <i class="info" title="Estimate from the live line and time left">i</i>` : ''}</span></div>
    <div class="prog"><i class="${win ? 'win' : ''}" style="${now >= 0 ? `left:50%;width:${pos - 50}%` : `left:${pos}%;width:${50 - pos}%`}"></i><b></b></div>
  </div>`;
}

function heroLive(g) {
  const fav = favSide(g) || 'home';
  const c = closeOf(g);
  const favLineClose = lineFor(g, fav, c);
  const cover = favLineClose == null ? null : margin(g, fav) + favLineClose;
  const lv = g.live?.cons || g.live?.dk;
  const pts = (g.home.score ?? 0) + (g.away.score ?? 0);
  const played = 1 - remaining(g);
  const pace = played > 0.2 ? Math.round(pts / played) : null;
  const ph = g.prob?.home;
  const lead = (g.home.score ?? 0) === (g.away.score ?? 0) ? null : (g.home.score > g.away.score ? 'home' : 'away');
  const favT = g[fav];
  const say = [];
  const m = Math.abs(margin(g, 'home'));
  say.push(lead ? `${teamName(g[lead])} leads by ${m}${g.half ? ' at the half' : g.period ? ` in the ${quarter(g.period)}` : ''}.` : 'Tied.');
  if (cover != null) say.push(`At ${fmtPts(favLineClose)}, ${teamName(favT)} ${cover > 0 ? `is covering by ${trim(cover)}` : cover < 0 ? `needs ${trim(-cover)} more to cover` : 'is sitting on a push'}.`);
  if (lv?.s != null) say.push(`The live market has it ${favLine(g, lv)}.`);
  const tot = c?.t != null ? `Total ${pts} so far${pace ? `, on pace for ${pace}` : ''} against a close of ${fmtTot(c.t)}.` : '';
  return `<div class="hero-lab"><b><span class="dot pulse"></span>Game of the moment</b><span>${esc([g.tv, g.home.conf === g.away.conf ? g.home.conf : null].filter(Boolean).join(' · '))}</span></div>
  <button class="card hcard" type="button" data-open="${g.id}">
    ${scoreboard(g)}
    ${fieldSVG(g, true)}
    <div class="situ"><span>${g.sit?.text ? `<b>${esc(g.sit.text)}</b>` : esc(g.last ? g.last.slice(0, 80) : '')}</span>${g.sit?.rz ? '<span class="rz">Red zone</span>' : `<span>${esc(g.poss ? `${g[g.poss].abbr} ball` : '')}</span>`}</div>
    <div class="big3">
      <div><div class="v num">${cover == null ? '—' : cover === 0 ? 'Push' : `${trim(Math.abs(cover))}<small>${cover > 0 ? 'ahead' : 'short'}</small>`}</div><div class="l">${esc(favT.abbr)} ${esc(fmtPts(favLineClose))} at the close</div></div>
      <div><div class="v num">${lv?.s != null ? esc(fmtPts(-Math.abs(lv.s))) : '—'}</div><div class="l">Live line${lv?.s != null ? ` (${esc(lv.s < 0 ? g.home.abbr : g.away.abbr)})` : ''}</div></div>
      <div><div class="v num">${ph == null ? '—' : fmtPct(ph >= 0.5 ? ph : 1 - ph)}</div><div class="l">${ph == null ? 'Win chance' : `${esc(g[ph >= 0.5 ? 'home' : 'away'].abbr)} win chance`}</div></div>
    </div>
    ${ph != null ? `<div class="wpb"><i style="width:${(1 - ph) * 100}%"></i></div><div class="wpl"><span><b>${esc(g.away.abbr)}</b> ${fmtPct(1 - ph)}</span><span>${fmtPct(ph)} <b>${esc(g.home.abbr)}</b></span></div>` : ''}
    <p class="say">${esc(say.join(' '))}<span class="muted">${esc(tot)}</span></p>
  </button>`;
}

function heroPre(g) {
  const m = g.mkt, o = g.open;
  const fav = favSide(g);
  const moved = o?.s != null && m?.s != null ? m.s - o.s : null;
  const sig = signals(g)[0];
  const w = g.wx || {};
  return `<div class="hero-lab"><b>Up next</b><span>${esc(dayLabel(g.start))} ${esc(timeLabel(g.start))}${g.tv ? ` · ${esc(g.tv)}` : ''}</span></div>
  <button class="card hcard" type="button" data-open="${g.id}">
    ${scoreboard(g)}
    <div class="big3">
      <div><div class="v num">${m?.s == null ? '—' : m.s === 0 ? 'PK' : esc(fmtPts(-Math.abs(m.s)))}</div><div class="l">${fav ? `${esc(g[fav].abbr)} spread` : 'Spread'}${o?.s != null ? ` · opened ${esc(fmtPts(-Math.abs(o.s)))}` : ''}</div></div>
      <div><div class="v num">${fmtTot(m?.t)}</div><div class="l">Total${o?.t != null ? ` · opened ${fmtTot(o.t)}` : ''}</div></div>
      <div><div class="v num">${g.splits?.s?.tix != null ? `${Math.max(g.splits.s.tix, 100 - g.splits.s.tix)}%` : '—'}</div><div class="l">${g.splits?.s?.tix != null ? `of tickets on ${esc(g[g.splits.s.tix >= 50 ? 'home' : 'away'].abbr)}` : 'Tickets'}</div></div>
    </div>
    <p class="say">${esc(fav ? spreadWords(g[fav], -Math.abs(m.s)) : m?.s === 0 ? 'Pick\'em.' : '')} ${moved ? esc(`The line has moved ${trim(Math.abs(moved))} toward ${teamName(moved < 0 ? g.home : g.away)} since it opened.`) : ''}
      <span class="muted">${sig ? sig.text.replace(/<[^>]+>/g, '') : ''}${w.wind != null && w.wind >= 12 ? ` Wind ${w.wind} mph, gusts ${w.gust}.` : ''}</span></p>
  </button>`;
}

function scoreboard(g) {
  const tm = (t, side) => {
    const other = side === 'home' ? g.away : g.home;
    const trail = !isPre(g) && (t.score ?? 0) < (other.score ?? 0);
    return `<div class="t ${side === 'home' ? 'h' : ''}${trail ? ' trail' : ''}">${logo(t)}<div style="min-width:0"><div class="nm">${rankTag(t)}${esc(teamName(t))}${g.poss === side ? '<span class="poss-dot"></span>' : ''}</div><div class="rc">${esc(t.rec || '')}${rotOf(g, side) ? ` · ${rotOf(g, side)}` : ''}</div></div>${isPre(g) ? '' : `<div class="sc num">${t.score ?? 0}</div>`}</div>`;
  };
  return `<div class="sb">${tm(g.away, 'away')}<div class="mid"><b>${isLive(g) ? '<span class="dot pulse"></span>' : ''}${esc(clockLabel(g))}</b>${isPre(g) ? esc(dayLabel(g.start)) : ''}</div>${tm(g.home, 'home')}</div>`;
}

function renderHeroSide() {
  const side = $('#heroSide');
  const moves = S.moves.filter((m) => gameById(m.gid) && isPre(gameById(m.gid))).slice(0, 6);
  const sigs = allGames().filter(isPre).map((g) => ({ g, s: signals(g) })).filter((x) => x.s.length).sort((a, b) => Date.parse(a.g.start) - Date.parse(b.g.start)).slice(0, 4);
  side.innerHTML = `
    <section><div class="sec-h" style="margin-bottom:12px"><h2 style="font-size:17px">Line moves</h2><span class="more" style="font-size:13px">${moves.length ? 'Newest first' : ''}</span></div>
      <div class="card list">${moves.length ? moves.map((m) => {
        const g = gameById(m.gid), tx = moveText(m, g);
        return `<div class="li" data-open="${g.id}">${m.kind === 'steam' ? '<span class="tag hot">Steam</span>' : `<span class="tag">${esc(m.kind === 'key' ? `Key ${m.key}` : m.kind === 'flip' ? 'Flip' : 'Move')}</span>`}<div><div>${esc(tx.title)}</div><div class="m">${esc(g.away.abbr)} @ ${esc(g.home.abbr)} · ${esc(ago(m.t))}</div></div><div class="v num">${esc(tx.to)}</div></div>`;
      }).join('') : '<div class="empty" style="padding:24px 16px;font-size:13px"><b style="font-size:15px">Quiet so far</b>Steam, key-number crossings and big moves show up here the moment they happen.</div>'}</div></section>
    ${sigs.length ? `<section><div class="sec-h" style="margin-bottom:12px"><h2 style="font-size:17px">Sharp signals</h2><span class="more" style="font-size:13px">Splits vs movement</span></div>
      <div class="card list">${sigs.map(({ g, s }) => `<div class="li" data-open="${g.id}" style="grid-template-columns:1fr auto"><div><div style="font-weight:600">${esc(g.away.abbr)} @ ${esc(g.home.abbr)} <span class="m">· ${esc(dayLabel(g.start))} ${esc(timeLabel(g.start))}</span></div><div class="m" style="margin-top:2px">${s[0].text.replace(/<[^>]+>/g, '')}</div></div><div class="v num">${esc(favLine(g))}</div></div>`).join('')}</div></section>` : ''}`;
}

function stripCard(g) {
  const r = atsResult(g);
  const lead = (g.home.score ?? 0) > (g.away.score ?? 0) ? 'home' : 'away';
  const row = (t, side) => `<div class="gm-r${!isPre(g) && lead !== side && g.home.score !== g.away.score ? ' lose' : ''}">${logo(t)}${rankTag(t)}${esc(t.abbr)}${g.poss === side && isLive(g) ? '<span class="poss-dot"></span>' : ''}<b class="num">${isPre(g) ? '' : t.score ?? ''}</b></div>`;
  let foot;
  if (isFinal(g) && r) foot = `<b>${esc(r.s || '')}</b><span>${esc(r.t || '')}</span>`;
  else if (isLive(g)) {
    const fav = favSide(g);
    const cov = fav ? margin(g, fav) + lineFor(g, fav) : null;
    foot = `<span>${esc(favLine(g, closeOf(g)))}</span>${cov == null ? '' : `<b>${cov > 0 ? 'covering' : cov < 0 ? `needs ${trim(-cov)}` : 'push'}</b>`}`;
  } else foot = `<span>${esc(favLine(g))}</span><b class="num">${fmtTot(g.mkt?.t)}</b>`;
  return `<button class="gm${isLive(g) ? ' live' : ''}" type="button" data-open="${g.id}"><div class="gm-h">${isLive(g) ? '<span class="dot pulse"></span>' : ''}${esc(clockLabel(g))}${g.tv && !isFinal(g) ? ` · ${esc(g.tv)}` : ''}</div>${row(g.away, 'away')}${row(g.home, 'home')}<div class="gm-f">${foot}</div></button>`;
}

function liveCard(g) {
  const fav = favSide(g) || 'home';
  const c = closeOf(g);
  const fl = lineFor(g, fav, c);
  const cover = fl == null ? null : margin(g, fav) + fl;
  const lv = g.live?.cons || g.live?.dk;
  const ph = g.prob?.home;
  const lead = g.home.score === g.away.score ? null : g.home.score > g.away.score ? 'home' : 'away';
  const mine = openLegs().filter((l) => l.gid === g.id);
  const row = (t, side) => `<div class="lc-tr${lead && lead !== side ? ' trail' : ''}"><span class="pos${g.poss === side ? '' : ' off'}"></span>${logo(t)}<span class="nm">${rankTag(t)}${esc(teamName(t))}<small>${esc(t.rec || '')}</small></span><b class="num">${t.score ?? 0}</b></div>`;
  return `<button class="card lc" type="button" data-open="${g.id}">
    <div class="lc-top"><span>${esc([g.tv, mine.length ? `${plural(mine.length, 'bet')} here` : null].filter(Boolean).join(' · '))}</span><span class="q"><span class="dot pulse"></span>${esc(clockLabel(g))}</span></div>
    ${row(g.away, 'away')}${row(g.home, 'home')}
    ${fieldSVG(g)}
    <div class="lc-mk">
      <div><div class="k">Closed</div><div class="v num">${esc(favLine(g, c))}</div></div>
      <div><div class="k">Live</div><div class="v num">${lv?.s != null ? esc(favLine(g, lv)) : '—'}<small>${lv?.t != null ? `o/u ${fmtTot(lv.t)}` : ''}</small></div></div>
      <div><div class="k">Win</div><div class="v num">${ph == null ? '—' : `${esc(g[ph >= 0.5 ? 'home' : 'away'].abbr)} ${fmtPct(ph >= 0.5 ? ph : 1 - ph)}`}</div></div>
    </div>
    <div class="lc-say">${g.sit?.text ? `<b>${esc(g.sit.text)}</b>${g.sit.rz ? ' · <b style="color:var(--accent)">red zone</b>' : ''}. ` : ''}${cover == null ? '' : `${esc(g[fav].abbr)} ${cover > 0 ? `covering by ${trim(cover)}` : cover < 0 ? `needs ${trim(-cover)} to cover` : 'on the number'}.`}</div>
  </button>`;
}

function renderLearn() {
  const k = S.keys;
  const pct = (n) => (k?.n ? `${((k.margin[n] || 0) / k.n * 100).toFixed(1)}%` : null);
  const keyLine = k?.n ? `Last season ${pct(3)} of NFL games ended by exactly 3 and ${pct(7)} by exactly 7, so half a point around those numbers is worth more than anywhere else.` : 'Games end on 3 and 7 far more than on other margins, so half a point around them matters most.';
  $('#learn').innerHTML = `<div class="card learn">
    <h3>New to betting?</h3>
    <p>Eight ideas explain almost every number on this app.</p>
    <div class="terms">
      <div class="term"><b>Spread</b><span>Points added to the underdog. Alabama −19.5 has to win by 20 or more; Florida State +19.5 covers by losing by 19 or fewer.</span></div>
      <div class="term"><b>Total (over/under)</b><span>Both teams' points added together. Bet whether the game lands over or under the number.</span></div>
      <div class="term"><b>Moneyline</b><span>Just pick the winner. −300 means risk $300 to win $100; +250 means $100 wins $250.</span></div>
      <div class="term"><b>Juice</b><span>The −110 next to most lines. It's the book's cut: risk $110 to win $100. Better juice at another book adds up over a season.</span></div>
      <div class="term"><b>Key numbers &amp; the hook</b><span>${esc(keyLine)} The ".5" is called the hook.</span></div>
      <div class="term"><b>Line movement</b><span>Books move numbers when money comes in. Movement from sharp books like Circa and Pinnacle tends to matter most.</span></div>
      <div class="term"><b>Steam &amp; reverse moves</b><span>Steam is several books moving the same way within minutes. A reverse move is the line going against the side most tickets are on.</span></div>
      <div class="term"><b>Closing line value</b><span>Beat the final number before kickoff and you're usually on the right side long-term, win or lose that day. My bets tracks it for you.</span></div>
    </div></div>`;
}

// ------------------------------------------------------------ BOARD
const FILTERS = [
  ['all', 'All'], ['mine', 'My teams'], ['bets', 'My bets'], ['moving', 'Moving'], ['live', 'Live'], ['edges', 'Vs sharp'],
  ['AFC', 'AFC'], ['NFC', 'NFC'],
  ['AFC East', 'AFC East'], ['AFC North', 'AFC North'], ['AFC South', 'AFC South'], ['AFC West', 'AFC West'],
  ['NFC East', 'NFC East'], ['NFC North', 'NFC North'], ['NFC South', 'NFC South'], ['NFC West', 'NFC West'],
];
function passes(g, f) {
  if (f === 'all') return true;
  if (f === 'mine') return S.follow.has(g.home.id) || S.follow.has(g.away.id);
  if (f === 'bets') return S.bets.some((b) => b.legs.some((l) => l.gid === g.id));
  if (f === 'moving') return (g.open?.s != null && g.mkt?.s != null && Math.abs(g.mkt.s - g.open.s) >= 1.5) || (g.open?.t != null && g.mkt?.t != null && Math.abs(g.mkt.t - g.open.t) >= 2) || (g.moves || []).some((m) => serverNow() - m.t < 6 * 3600e3);
  if (f === 'live') return isLive(g);
  if (f === 'edges') return typeof edgeGame === 'function' && !(typeof limBreak === 'function' && limBreak()) && edgeGame(g);
  if (f === 'AFC' || f === 'NFC') return [g.home.conf, g.away.conf].some((c) => String(c || '').startsWith(f));
  return g.home.conf === f || g.away.conf === f;
}
function matchesQuery(g) {
  const q = S.query.trim().toLowerCase();
  if (!q) return true;
  return [g.home, g.away].some((t) => [t.name, t.abbr, t.short, t.loc].some((x) => String(x || '').toLowerCase().includes(q)));
}

function renderBoard(loading = false) {
  const W = boardWeek();
  const meta = W?.meta || S.cal.find((c) => c.id === S.boardWeek) || {};
  $('#boardTitle').textContent = meta.label ? `${meta.label} board` : 'The board';
  const idx = S.cal.findIndex((c) => c.id === (meta.id || S.boardWeek));
  const prev = S.cal[idx - 1], next = S.cal[idx + 1];
  $('#weekNav').innerHTML = `<button class="ibtn" type="button" data-week="${prev?.id || ''}" ${prev ? '' : 'disabled'} aria-label="Previous week">${ICON.back}</button><span class="lab">${esc(meta.detail || meta.label || '')}</span><button class="ibtn" type="button" data-week="${next?.id || ''}" ${next ? '' : 'disabled'} aria-label="Next week">${ICON.chev}</button>`;
  $$('#mktSeg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mkt === S.mkt)));
  if (typeof wxBoard === 'function') wxBoard(loading ? null : W); // Weather watch card (weather.js)
  if (loading || !W) { $('#boardSub').textContent = 'Loading…'; $('#boardBody').innerHTML = '<div class="card empty"><b>Loading the week</b>Pulling every game and line.</div>'; return; }

  const games = [...W.games.values()].filter((g) => g.state !== 'off' || true);
  const counts = Object.fromEntries(FILTERS.map(([f]) => [f, games.filter((g) => passes(g, f)).length]));
  $('#filters').innerHTML = FILTERS.filter(([f]) => counts[f] || f === 'all' || f === S.filter).map(([f, l]) => `<button class="pbtn" type="button" data-filter="${esc(f)}" aria-pressed="${S.filter === f}">${f === 'mine' ? ICON.starOn.replace('<svg', '<svg width="12" height="12"') : ''}${esc(l)}<span class="n">${counts[f]}</span></button>`).join('');
  const shown = games.filter((g) => passes(g, S.filter) && matchesQuery(g)).sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || (a.rot?.away || 0) - (b.rot?.away || 0));
  const live = games.filter(isLive).length;
  const feeds = S.books.filter((b) => b.feed).length;
  $('#boardSub').innerHTML = `${plural(games.length, 'game')}${live ? ` · ${live} live` : ''} · ${feeds} books with live feeds${W.meta.tracked === false ? ' · archive' : ''}<span id="fresh"></span>`;
  renderFreshness();

  if (!shown.length) { $('#boardBody').innerHTML = `<div class="card empty" style="margin-top:24px"><b>No games match</b>${S.query ? `Nothing for “${esc(S.query)}”.` : 'Try another filter.'}</div>`; return; }

  // group by day + TV window; games that are over drop to one folded group at the bottom
  const groups = [];
  const done = shown.filter((g) => isFinal(g) || g.state === 'off');
  for (const g of shown.filter((x) => !done.includes(x))) {
    const key = `${etDay(g.start)}|${windowOf(g)}`;
    let grp = groups.find((x) => x.key === key);
    if (!grp) groups.push(grp = { key, day: dayLabel(g.start, true), win: windowOf(g), games: [] });
    grp.games.push(g);
  }
  const mkt = S.mkt;
  const cols = visibleBooks().filter((b) => shown.some((g) => sideKeys(mkt).some((sd) => boardPrice(g, mkt, sd, b.key))));
  if (S.phBook !== 'mkt' && !cols.some((b) => b.key === S.phBook)) S.phBook = 'mkt'; // that book has nothing on this slate
  $('#phBooks').innerHTML = [['mkt', 'Market'], ...cols.map((b) => [b.key, b.short])]
    .map(([k, l]) => `<button class="pbtn" type="button" data-phbook="${esc(k)}" aria-pressed="${S.phBook === k}">${esc(l)}${k !== 'mkt' && S.books.find((b) => b.key === k)?.sharp ? '<span class="tag sharp">S</span>' : ''}</button>`).join('');
  const colName = S.phBook === 'mkt' ? 'Market' : bookName(S.phBook);
  const head = `<div class="br-hd"><span>${esc(mkt === 't' ? 'Over / under' : mkt === 'ml' ? 'Moneyline' : mkt === 'h1' ? '1st-half spread' : 'Spread')}</span><span>${esc(colName)}</span><span>Best</span></div>`;
  const block = (games) => `<div class="card brd m">${head}${games.map((g) => boardRow(g, mkt)).join('')}</div>${boardTable(games, mkt, cols)}`;
  const wasOpen = $('#doneGroup')?.open;
  $('#boardBody').innerHTML = groups.map((grp) => `
    <div class="win-h"><h3>${esc(grp.day)} · ${esc(grp.win)}</h3><span>${plural(grp.games.length, 'game')}</span></div>${block(grp.games)}`).join('')
    + (done.length ? `<details class="done" id="doneGroup"${wasOpen || !groups.length ? ' open' : ''}><summary class="win-h"><h3>Final</h3><span>${plural(done.length, 'game')} · closing lines and results ${ICON.chev}</span></summary>${block(done.sort((a, b) => Date.parse(b.start) - Date.parse(a.start)))}</details>` : '');
}

// What the board shows for one side: live line when a game is on, else the current pregame number.
function boardPrice(g, mkt, side, book) {
  const L = mkt === 'h1' ? g.h1?.[book] : isLive(g) ? g.live?.[book] : g.books?.[book];
  const m = mkt === 'h1' ? 'h1s' : mkt;
  return sideOf(L, m, side);
}
function sideKeys(mkt) { return mkt === 't' ? ['over', 'under'] : ['away', 'home']; }
function pxCell(g, mkt, side, book, best, opts = {}) {
  const p = boardPrice(g, mkt, side, book);
  const m = mkt === 'h1' ? 'h1s' : mkt;
  if (!p || (p.odds == null && p.line == null)) return `<span class="px na" aria-hidden="true">—</span>`;
  const isBest = best && best.book === book && !isFinal(g);
  const L = mkt === 'h1' ? g.h1?.[book] : isLive(g) ? g.live?.[book] : g.books?.[book];
  const flash = flashAttr(g.id, mkt === 'h1' ? 'h1' : isLive(g) ? 'live' : 'pre', book, m);
  const main = m === 'ml' ? fmtOdds(p.odds) : mkt === 't' ? `${side === 'over' ? 'o' : 'u'}${fmtTot(p.line)}` : fmtPts(p.line);
  const sub = opts.sub ?? (m === 'ml' ? '' : fmtOdds(p.odds));
  const who = side === 'over' ? 'Over' : side === 'under' ? 'Under' : teamName(g[side]);
  const old = isOld(L);
  const label = [bookFull(book), `${who} ${m === 'ml' ? fmtOdds(p.odds) : mkt === 't' ? fmtTot(p.line) : fmtPts(p.line)}`, m === 'ml' ? '' : fmtOdds(p.odds), isBest ? 'best price' : '', L?.m ? 'typed in' : '', flash.label, old ? `checked ${ago(L.seen)}` : ''].filter(Boolean).join(', ');
  const cls = `px num${isBest ? ' best' : ''}${L?.m ? ' man' : ''}${flash.cls}${old ? ' old' : ''}`;
  if (isFinal(g)) return `<span class="${cls}"${flash.style} aria-label="${esc(label)}">${esc(main)}${sub ? `<small>${esc(sub)}</small>` : ''}</span>`;
  return `<button type="button" class="${cls}"${flash.style} data-bet="${g.id}|${m}|${side}|${book}" aria-label="${esc(label)}" title="${esc(label)}">${esc(main)}${sub ? `<small>${esc(sub)}</small>` : ''}${typeof edgeBadge === 'function' && !(typeof limBreak === 'function' && limBreak()) ? edgeBadge(g, m, side, book) : ''}</button>`;
}
function bestFor(g, mkt, side) {
  const books = mkt === 'h1' ? g.h1 : isLive(g) ? g.live : g.books;
  return bestOf(books, mkt === 'h1' ? 'h1s' : mkt, side);
}
function marketKey(g, mkt) {
  const src = mkt === 'h1' ? g.h1 : isLive(g) ? g.live : g.books;
  return src?.cons ? 'cons' : src?.dk ? 'dk' : Object.keys(src || {})[0];
}

function boardRow(g, mkt) {
  const [s1, s2] = sideKeys(mkt);
  const lead = (g.home.score ?? 0) > (g.away.score ?? 0) ? 'home' : 'away';
  // On a narrow screen there's room for two numbers: the book you picked (market consensus by default)
  // and the best price anywhere. The wide board shows every book at once, so it ignores this.
  const mk = S.phBook === 'mkt' ? marketKey(g, mkt) : S.phBook;
  const row = (t, side, pside) => {
    const best = bestFor(g, mkt, pside);
    return `<div class="br-t${!isPre(g) && lead !== side && g.home.score !== g.away.score ? ' trail' : ''}"><span class="rot">${rotOf(g, side) ?? ''}</span>${logo(t)}<span class="nm">${rankTag(t)}${esc(teamName(t))}<small>${esc(t.rec || '')}</small></span><span class="sc num">${isPre(g) ? '' : t.score ?? ''}</span>${mk ? pxCell(g, mkt, pside, mk, null) : '<span class="px na">—</span>'}${best && !isFinal(g) ? pxCell(g, mkt, pside, best.book, best, { sub: bookName(best.book) }) : '<span class="px na"></span>'}</div>`;
  };
  const r = atsResult(g);
  const moved = mkt === 't' ? (g.open?.t != null && g.mkt?.t != null ? g.mkt.t - g.open.t : null) : (g.open?.s != null && g.mkt?.s != null ? g.mkt.s - g.open.s : null);
  const sp = mkt === 't' ? g.splits?.t : g.splits?.s;
  const bits = [];
  bits.push(isLive(g) ? `<span class="hot">${esc(clockLabel(g))}</span>` : isFinal(g) ? `<b>${esc(clockLabel(g))}</b>` : `<b>${esc(timeLabel(g.start))}</b>`);
  if (g.tv && !isFinal(g)) bits.push(esc(g.tv));
  if (r) bits.push(`<b>${esc(mkt === 't' ? r.t : r.s)}</b>`);
  else if (moved) bits.push(`Opened ${mkt === 't' ? fmtTot(g.open.t) : fmtPts(g.open.s)} <b>${moved > 0 ? '▲' : '▼'}${trim(Math.abs(moved))}</b>`);
  if (sp?.tix != null && isPre(g)) bits.push(mkt === 't' ? `${sp.tix}% on over` : `${Math.max(sp.tix, 100 - sp.tix)}% on ${esc(g[sp.tix >= 50 ? 'home' : 'away'].abbr)}`);
  if (g.wx?.wind >= 12 && isPre(g)) bits.push(`<span class="${g.wx.wind >= 18 ? 'hot' : ''}">Wind ${g.wx.wind}</span>`);
  if ((g.moves || []).some((m) => m.kind === 'steam' && serverNow() - m.t < 3 * 3600e3)) bits.push('<span class="hot">Steam</span>');
  if (S.bets.some((b) => b.status === 'open' && b.legs.some((l) => l.gid === g.id))) bits.push('<b>Your bet</b>');
  const spark = mkt === 't' ? g.spark?.t : g.spark?.s;
  return `<div class="br" data-open="${g.id}">${row(g.away, 'away', s1)}${row(g.home, 'home', s2)}<button type="button" class="br-f" data-open="${g.id}" aria-label="${esc(`${g.away.short} at ${g.home.short}: open the game`)}">${bits.join('<span class="sep"></span>')}<span class="spk">${isPre(g) ? sparkSVG(spark) : ''}</span></button></div>`;
}

function boardTable(games, mkt, books = visibleBooks()) {
  const [s1, s2] = sideKeys(mkt);
  const head = `<thead><tr><th class="l stk">Matchup</th><th>Open</th><th>Market</th><th>Move</th>${books.map((b) => `<th title="${esc(b.name)}${b.sharp ? ' (sharp)' : ''}">${esc(b.short)}${b.sharp ? '<span class="tag sharp">S</span>' : ''}</th>`).join('')}<th>Tickets · money</th></tr></thead>`;
  const rows = games.map((g, i) => {
    const lead = (g.home.score ?? 0) > (g.away.score ?? 0) ? 'home' : 'away';
    const trail = !isPre(g) && g.home.score !== g.away.score ? (lead === 'home' ? 'trail0' : 'trail1') : '';
    const bestA = bestFor(g, mkt, s1), bestH = bestFor(g, mkt, s2);
    const open = (side) => {
      const o = g.open;
      if (!o) return '<span class="px na">—</span>';
      if (mkt === 't') return o.t == null ? '<span class="px na">—</span>' : `<span class="px num na" style="color:var(--ink-2)">${side === 'over' ? 'o' : 'u'}${fmtTot(o.t)}</span>`;
      if (mkt === 'ml') return `<span class="px num na" style="color:var(--ink-2)">${fmtOdds(o.ml?.[side === 'home' ? 0 : 1])}</span>`;
      if (mkt === 'h1') return '<span class="px na">—</span>';
      return o.s == null ? '<span class="px na">—</span>' : `<span class="px num na" style="color:var(--ink-2)">${fmtPts(side === 'home' ? o.s : -o.s)}</span>`;
    };
    const mk = marketKey(g, mkt);
    const moved = mkt === 't' ? (g.open?.t != null && g.mkt?.t != null ? g.mkt.t - g.open.t : null) : (g.open?.s != null && g.mkt?.s != null ? g.mkt.s - g.open.s : null);
    const sp = mkt === 't' ? g.splits?.t : mkt === 'ml' ? g.splits?.ml : g.splits?.s;
    const aw = mkt === 't' ? 'O' : g.away.abbr, hm = mkt === 't' ? 'U' : g.home.abbr;
    const a = sp?.tix == null ? null : mkt === 't' ? sp.tix : 100 - sp.tix;
    const am = sp?.money == null ? null : mkt === 't' ? sp.money : 100 - sp.money;
    const r = atsResult(g);
    const w = g.wx || {};
    const wind = w.dome ? 'Dome' : w.wind >= 10 && isPre(g) ? `<span class="${w.wind >= 18 ? 'hot' : ''}">Wind ${w.wind}</span>` : '';
    const status = isLive(g) ? `<b class="hot"><span class="dot pulse" style="margin-right:5px"></span>${esc(clockLabel(g))}</b>` : `<b>${esc(isFinal(g) ? clockLabel(g) : timeLabel(g.start))}</b>`;
    return `<tr class="${i ? '' : 'g0'}" data-open="${g.id}">
      <td class="l stk"><div class="mu"><div class="meta">${status}${esc(g.tv || '')}${r ? `<br><span class="w">${esc(mkt === 't' ? r.t : r.s)}</span>` : ''}${wind ? `<br>${wind}` : ''}</div>
        <div class="tm2 ${trail}"><div><span class="rt">${rotOf(g, 'away') ?? ''}</span>${logo(g.away)}<span class="nm">${rankTag(g.away)}${esc(teamName(g.away))}<small>${esc(g.away.rec || '')}</small></span><span class="sc num">${isPre(g) ? '' : g.away.score ?? ''}</span></div><div><span class="rt">${rotOf(g, 'home') ?? ''}</span>${logo(g.home)}<span class="nm">${rankTag(g.home)}${esc(teamName(g.home))}<small>${esc(g.home.rec || '')}</small></span><span class="sc num">${isPre(g) ? '' : g.home.score ?? ''}</span></div></div></div></td>
      <td><div class="st2">${open(s1)}${open(s2)}</div></td>
      <td><div class="st2">${mk ? pxCell(g, mkt, s1, mk, null) : '<span class="px na">—</span>'}${mk ? pxCell(g, mkt, s2, mk, null) : '<span class="px na">—</span>'}</div></td>
      <td><div class="meta mvc">${isPre(g) ? sparkSVG(mkt === 't' ? g.spark?.t : g.spark?.s, 48, 18) : ''}${moved ? `<span>${moved > 0 ? '▲' : '▼'} ${trim(Math.abs(moved))}</span>` : isPre(g) ? '<span class="faint">steady</span>' : ''}</div></td>
      ${books.map((b) => `<td><div class="st2">${pxCell(g, mkt, s1, b.key, bestA)}${pxCell(g, mkt, s2, b.key, bestH)}</div></td>`).join('')}
      <td><div class="spl">${a != null ? `<div class="bar2" title="Tickets: ${esc(aw)} ${a}% / ${esc(hm)} ${100 - a}%"><i style="width:${Math.max(a, 18)}%">${a}%</i><i>${100 - a}%</i></div>` : ''}${am != null ? `<div class="bar2 m" style="margin-top:4px" title="Money: ${esc(aw)} ${am}% / ${esc(hm)} ${100 - am}%"><i style="width:${Math.max(am, 18)}%">${am}%</i><i>${100 - am}%</i></div>` : ''}${a == null ? '<span class="faint">—</span>' : ''}</div></td>
    </tr>`;
  }).join('');
  return `<div class="bt-wrap"><table class="bt">${head}<tbody>${rows}</tbody></table></div>`;
}

// "Lines checked 12s ago": how fresh the board is, updated every tick without redrawing it.
function renderFreshness() {
  const el = $('#fresh');
  if (!el) return;
  const at = S.at?.[S.boardWeek];
  const t = at ? Math.max(at.an || 0, at.vsin || 0) : 0;
  if (!t) { el.textContent = ''; return; }
  const s = Math.max(0, Math.round((serverNow() - t) / 1000));
  el.textContent = ` · lines checked ${s < 60 ? `${s}s` : `${Math.round(s / 60)} min`} ago`;
}

// ------------------------------------------------------------ MY BETS
function betLabel(b) { return b.legs.length > 1 ? `${b.legs.length}-leg parlay` : b.legs[0].label; }
function betCard(b) {
  const legs = b.legs.map((l) => {
    const g = gameById(l.gid);
    let status = '', prog = '';
    if (l.state !== 'open') {
      status = `<span class="cov ${l.state === 'won' ? 'win' : l.state === 'lost' ? 'lose' : ''}">${esc(l.state === 'won' ? 'Won' : l.state === 'lost' ? 'Lost' : l.state === 'push' ? 'Push' : 'Void')}</span>`;
    } else if (g && isLive(g)) {
      const now = legNow(g, l);
      const p = coverChance(g, l);
      status = `<span class="cov ${now > 0 ? 'win' : now < 0 ? 'lose' : 'push'}">${now > 0 ? `+${trim(now)}` : now < 0 ? `${MINUS}${trim(-now)}` : 'Push'}</span>`;
      const pos = clamp(50 + (now / 28) * 50, 2, 98);
      prog = `<div class="leg-s"><span>${esc(g.away.abbr)} <b>${g.away.score}</b> · ${esc(g.home.abbr)} <b>${g.home.score}</b> · ${esc(clockLabel(g))}</span><span>${p != null ? `est. ${fmtPct(p)} to cash` : ''}</span></div><div class="prog"><i class="${now > 0 ? 'win' : ''}" style="${now >= 0 ? `left:50%;width:${pos - 50}%` : `left:${pos}%;width:${50 - pos}%`}"></i><b></b></div>`;
    } else if (g && isPre(g)) {
      // closing line value so far: your number vs the market now
      const cur = sideOf(g.mkt, l.mkt, l.side);
      let edge = '';
      if (cur && l.mkt === 's') edge = trim(l.line - cur.line);
      if (cur && l.mkt === 't') edge = trim(l.side === 'over' ? cur.line - l.line : l.line - cur.line);
      const e = Number(edge);
      prog = `<div class="leg-s"><span>${esc(dayLabel(l.start || g.start))} ${esc(timeLabel(l.start || g.start))}${cur?.line != null ? ` · market now ${esc(l.mkt === 't' ? fmtTot(cur.line) : fmtPts(cur.line))}` : cur?.odds != null ? ` · market now ${esc(fmtOdds(cur.odds))}` : ''}</span>${edge !== '' && e !== 0 ? `<span class="${e > 0 ? 'w' : ''}">${e > 0 ? `${trim(e)} better than market` : `${trim(-e)} worse than market`}</span>` : ''}</div>`;
    } else if (g && isFinal(g)) {
      prog = `<div class="leg-s"><span>Final · ${esc(g.away.abbr)} ${g.away.score}, ${esc(g.home.abbr)} ${g.home.score}</span></div>`;
    }
    const clv = l.clv ? (l.clv.pts != null ? `<span class="${l.clv.pts > 0 ? 'w' : ''}">${l.clv.pts > 0 ? '+' : l.clv.pts < 0 ? MINUS : ''}${trim(Math.abs(l.clv.pts))} vs close</span>` : l.clv.pct != null ? `<span class="${l.clv.pct > 0 ? 'w' : ''}" title="Expected return of your price if the no-vig closing price is right">${l.clv.pct > 0 ? '+' : ''}${l.clv.pct}% edge at the close</span>` : '') : '';
    return `<div class="bet-leg" data-open="${l.gid}"><div class="leg-h">${esc(l.label)} ${fmtOdds(l.odds) && b.legs.length > 1 ? `<span>${esc(fmtOdds(l.odds))}</span>` : ''}${status}</div><div class="leg-s"><span>${esc(l.matchup)}</span>${clv}</div>${prog}</div>`;
  }).join('');
  const st = b.status;
  const tag = st === 'open' ? (b.legs.some((l) => isLive(gameById(l.gid))) ? '<span class="tag hot">Live</span>' : '<span class="tag">Open</span>') : `<span class="tag ${st === 'won' ? 'ink' : ''}">${esc(st[0].toUpperCase() + st.slice(1))}</span>`;
  return `<div class="card bet"><div class="bet-h"><div><b>${esc(betLabel(b))} <span class="num" style="font-weight:500;color:var(--ink-2);font-size:15px">${esc(fmtOdds(b.odds))}</span></b><div class="m">${esc([b.book, `${fmtMoney(b.stake)} to win ${fmtMoney(toWin(b.stake, b.odds))}`].filter(Boolean).join(' · '))}</div></div>${tag}</div>
    ${legs}
    <div class="bet-f">${st === 'open' ? `<span>Placed ${esc(new Date(b.placed).toLocaleDateString([], { month: 'short', day: 'numeric' }))}${b.note ? ` · ${esc(b.note)}` : ''}</span><span class="acts">${typeof shareBtn === 'function' ? shareBtn(b) : ''}<button type="button" data-void="${b.id}">Void</button><button type="button" data-del="${b.id}">Delete</button></span>` : `<span>${esc(b.note || new Date(b.settled || b.created).toLocaleDateString([], { month: 'short', day: 'numeric' }))}</span><span class="share-f">${typeof shareBtn === 'function' ? shareBtn(b) : ''}<b class="num ${b.net > 0 ? 'w' : ''}">${fmtMoney(b.net, true)}</b></span>`}</div></div>`;
}

function betStats(list) {
  const done = list.filter((b) => b.status !== 'open' && b.status !== 'void');
  const net = done.reduce((s, b) => s + (b.net || 0), 0);
  const risked = done.reduce((s, b) => s + b.stake, 0);
  const w = done.filter((b) => b.status === 'won').length, l = done.filter((b) => b.status === 'lost').length, p = done.filter((b) => b.status === 'push').length;
  const clvs = list.flatMap((b) => (b.legs.length === 1 && b.legs[0].clv?.pts != null ? [b.legs[0].clv.pts] : []));
  const avgClv = clvs.length ? clvs.reduce((a, b) => a + b, 0) / clvs.length : null;
  const beat = clvs.length ? clvs.filter((x) => x > 0).length / clvs.length : null;
  const open = list.filter((b) => b.status === 'open');
  return { net, risked, roi: risked ? net / risked : null, w, l, p, avgClv, beat, n: clvs.length, openRisk: open.reduce((s, b) => s + b.stake, 0), openWin: open.reduce((s, b) => s + (toWin(b.stake, b.odds) || 0), 0), open: open.length };
}

function renderBets() {
  $$('#betSeg button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.bseg === S.bseg)));
  const st = betStats(S.bets);
  const units = (n) => (S.unit ? `${(n / S.unit).toFixed(1)}u` : '');
  const top = `<div class="stats">
      <div><div class="v num ${st.net > 0 ? 'win' : ''}">${fmtMoney(st.net, true)}</div><div class="l">Net</div><div class="s">${esc(units(st.net))}${st.roi != null ? ` · ${(st.roi * 100).toFixed(1)}% ROI` : ''}</div></div>
      <div><div class="v num">${st.w}–${st.l}${st.p ? `–${st.p}` : ''}</div><div class="l">Record</div><div class="s">${st.w + st.l ? `${Math.round((st.w / (st.w + st.l)) * 100)}% winners` : 'No results yet'}</div></div>
      <div><div class="v num">${st.avgClv == null ? '—' : `${st.avgClv > 0 ? '+' : ''}${st.avgClv.toFixed(1)}`}</div><div class="l">Avg. points vs close <i class="info" title="Closing line value: how your number compared with the final market number at kickoff">i</i></div><div class="s">${st.beat == null ? 'Tracked from kickoff' : `Beat the close ${fmtPct(st.beat)} of ${st.n}`}</div></div>
      <div><div class="v num">${fmtMoney(st.openRisk)}</div><div class="l">At risk</div><div class="s">${plural(st.open, 'open bet')} · to win ${fmtMoney(st.openWin)}</div></div>
    </div>${typeof limBetsLine === 'function' ? limBetsLine() : ''}`;
  let list = '';
  if (S.bseg === 'open' || S.bseg === 'settled') {
    const bets = S.bets.filter((b) => (S.bseg === 'open' ? b.status === 'open' : b.status !== 'open'));
    if (S.bseg === 'open') bets.sort((a, b) => Number(b.legs.some((l) => isLive(gameById(l.gid)))) - Number(a.legs.some((l) => isLive(gameById(l.gid)))));
    // Open bets lead with the ranked 'Most likely to hit' board (hitlist.js).
    list = (S.bseg === 'open' ? hitList(bets) : '') + (bets.length ? `<div class="bets">${bets.map(betCard).join('')}</div>` : `<div class="card empty"><b>${S.bseg === 'open' ? 'No open bets' : 'Nothing settled yet'}</b>${S.bseg === 'open' ? 'Tap any price on the board to log a bet, or log one by hand.' : 'Bets grade themselves the moment a game goes final.'}</div>`);
  } else {
    list = resultsView();
  }
  $('#betsBody').innerHTML = `${top}
    <div class="row-btns" style="margin-top:var(--s2)"><button class="btn" type="button" data-newbet>${ICON.plus} Log a bet</button>${openLegs().some((l) => isLive(gameById(l.gid))) ? `<button class="btn ghost" type="button" data-sweat-open><span class="dot pulse"></span>Sweat mode</button>` : ''}${S.bets.length ? `<a class="btn ghost" href="/api/bets.csv" download>Export CSV</a>` : ''}</div>
    <div style="margin-top:var(--s3)">${list}</div>`;
}

function resultsView() {
  const done = S.bets.filter((b) => b.status !== 'open' && b.status !== 'void').sort((a, b) => (a.settled || 0) - (b.settled || 0));
  if (!done.length) return clvCard() + '<div class="card empty"><b>No results yet</b>Your profit chart, closing line value and best books show up after your first graded bet.</div>';
  // cumulative P&L
  let run = 0;
  const pts = [[0, 0], ...done.map((b, i) => [i + 1, (run += b.net || 0)])];
  const W = 640, H = 180, lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(0, ...pts.map((p) => p[1]));
  const X = (i) => 36 + (i / Math.max(1, pts.length - 1)) * (W - 48), Y = (v) => 12 + ((hi - v) / (hi - lo || 1)) * (H - 36);
  const chart = `<div class="card pnl"><div class="sub-h">Profit over time <span>${plural(done.length, 'bet')}</span></div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative profit">
    <line class="z" x1="36" x2="${W - 12}" y1="${Y(0)}" y2="${Y(0)}"/><text x="0" y="${Y(hi) + 4}">${esc(fmtMoney(hi))}</text><text x="0" y="${Y(lo) + 4}">${esc(fmtMoney(lo))}</text>
    <polyline class="ln" points="${pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ')}"/><circle class="end" cx="${X(pts.at(-1)[0])}" cy="${Y(pts.at(-1)[1])}" r="4"/></svg></div>`;
  const by = (keyFn) => {
    const m = new Map();
    for (const b of done) { const k = keyFn(b); const r = m.get(k) || { n: 0, w: 0, net: 0, risk: 0 }; r.n++; r.w += b.status === 'won'; r.net += b.net || 0; r.risk += b.stake; m.set(k, r); }
    return [...m].sort((a, b) => b[1].net - a[1].net);
  };
  const MK = { s: 'Spreads', t: 'Totals', ml: 'Moneylines', h1s: '1st-half spreads', h1t: '1st-half totals', tt: 'Team totals' };
  const table = (title, rows) => `<div class="card" style="padding:16px 0 4px"><div class="sub-h" style="padding:0 16px">${esc(title)}</div><table class="brk"><thead><tr><th>${esc(title.split(' ')[1] || '')}</th><th>Bets</th><th>Won</th><th>Net</th><th>ROI</th></tr></thead><tbody>${rows.map(([k, r]) => `<tr><td>${esc(k)}</td><td>${r.n}</td><td>${r.w}</td><td class="${r.net > 0 ? 'w' : ''}">${fmtMoney(r.net, true)}</td><td>${r.risk ? `${((r.net / r.risk) * 100).toFixed(0)}%` : '—'}</td></tr>`).join('')}</tbody></table></div>`;
  return clvCard() + `<div class="gs-grid even">${chart}<div style="display:grid;gap:12px">${table('By market', by((b) => (b.legs.length > 1 ? 'Parlays' : MK[b.legs[0].mkt] || b.legs[0].mkt)))}${table('By book', by((b) => b.book || 'Unknown'))}</div></div>`;
}

// ------------------------------------------------------------ TOOLS
let toolsState = { health: null, at: 0 };
function renderTools() {
  if (Date.now() - toolsState.at > 15000) {
    toolsState.at = Date.now();
    api('/api/health').then((h) => { toolsState.health = h; if (S.tab === 'tools') renderTools(); }).catch(() => {});
    loadKeys().then(() => { if (S.tab === 'tools' && !$('#keysTool')?.dataset.ready) renderTools(); });
  }
  const body = $('#toolsBody');
  if (body.dataset.built) { updateTools(); return; }
  body.dataset.built = '1';
  body.innerHTML = `<div class="tools">
    <div class="card tool"><h3>Odds converter</h3><p>American odds to decimal, implied chance and payout.</p>
      <div class="fgrid"><label class="fld">American odds<input class="inp" id="tOdds" inputmode="text" value="-110"></label><label class="fld">Stake<input class="inp" id="tStake" inputmode="decimal" value="${S.unit}"></label></div>
      <div class="out" id="tOddsOut"></div></div>
    <div class="card tool"><h3>No-vig fair price</h3><p>Strip the book's cut from both sides to see the real chance and fair odds. Use Pinnacle or Circa for the sharpest read.</p>
      <div class="fgrid"><label class="fld">Side A<input class="inp" id="nvA" inputmode="text" value="-112"></label><label class="fld">Side B<input class="inp" id="nvB" inputmode="text" value="-108"></label></div>
      <div class="out" id="nvOut"></div></div>
    <div class="card tool"><h3>Parlay</h3><p>Add each leg's odds, separated by spaces or commas.</p>
      <div class="fgrid"><label class="fld full">Leg odds<input class="inp" id="pLegs" value="-110, -110, +150"></label><label class="fld">Stake<input class="inp" id="pStake" inputmode="decimal" value="${S.unit}"></label></div>
      <div class="out" id="pOut"></div></div>
    <div class="card tool"><h3>Hedge</h3><p>Lock in profit (or cut a loss) by betting the other side. Works for a live sweat or a parlay's last leg.</p>
      <div class="fgrid"><label class="fld">Original payout if it wins<input class="inp" id="hPay" inputmode="decimal" value="500"></label><label class="fld">Original stake<input class="inp" id="hStake" inputmode="decimal" value="100"></label><label class="fld full">Hedge odds on the other side<input class="inp" id="hOdds" value="-150"></label></div>
      <div class="out" id="hOut"></div></div>
    ${acctCard()}
    ${kellyCard()}
    ${typeof limCard === 'function' ? limCard() : ''}
    <div class="card tool" id="keysTool"><h3>Key numbers</h3><p id="keysLede">How often last season's NFL games ended by exactly each margin.</p><div id="keysBody"></div></div>
    <div class="card tool"><h3>Where to bet</h3><p>Every Nevada book on this board, with a link to its site and its app. You sign in at the book — Pick Six never asks for a sportsbook login and never places a bet.</p>
      <button class="btn ghost" type="button" data-books>Open a sportsbook</button></div>
    <div class="card tool"><h3>Books on the board</h3><p>Tap to hide a book everywhere on this device. Books without a live feed take numbers you type in from the counter.</p><div class="bk-tog" id="bookTog"></div><div class="srcs" id="srcList" style="margin-top:16px"></div></div>
    <div class="card tool"><h3>Settings</h3><p>Unit size is used to show results in units.</p>
      <div class="fgrid"><label class="fld">Unit size ($)<input class="inp" id="unitIn" inputmode="decimal" value="${S.unit}"></label><label class="fld">Alerts<select class="inp" id="alertSel"><option value="off">Off</option><option value="mine">My bets &amp; teams</option><option value="all">Every line move</option></select></label></div>
      <button class="btn ghost" type="button" id="phoneBtn2">Open on iPhone</button></div>
  </div>`;
  updateTools();
}

function updateTools() {
  kellyPaint();
  acctPaint();
  if (typeof limPaint === 'function') limPaint();
  const n = (id) => Number(String($(id)?.value || '').replace(/[^\d.+-]/g, ''));
  const odds = n('#tOdds'), stake = n('#tStake');
  $('#tOddsOut').innerHTML = odds && Math.abs(odds) >= 100 ? `<div><div class="k">Decimal</div><div class="v num">${dec(odds).toFixed(3)}</div></div><div><div class="k">Implied</div><div class="v num">${fmtPct(imp(odds), 1)}</div></div><div><div class="k">Wins</div><div class="v num win">${fmtMoney(Math.round(toWin(stake, odds) * 100) / 100)}</div></div>` : '<div><div class="k">Enter odds like −110 or +150</div></div>';
  const a = n('#nvA'), b = n('#nvB');
  const nv = Math.abs(a) >= 100 && Math.abs(b) >= 100 ? noVig(a, b) : null;
  $('#nvOut').innerHTML = nv ? `<div><div class="k">Side A fair</div><div class="v num">${fmtOdds(probToAm(nv.a))}</div><div class="k">${fmtPct(nv.a, 1)}</div></div><div><div class="k">Side B fair</div><div class="v num">${fmtOdds(probToAm(nv.b))}</div><div class="k">${fmtPct(nv.b, 1)}</div></div><div><div class="k">Book's cut</div><div class="v num">${(nv.hold * 100).toFixed(1)}%</div></div>` : '';
  const legs = String($('#pLegs').value).split(/[\s,]+/).map(Number).filter((x) => Math.abs(x) >= 100);
  const pst = n('#pStake');
  const d = legs.reduce((p, o) => p * dec(o), 1);
  $('#pOut').innerHTML = legs.length ? `<div><div class="k">Odds</div><div class="v num">${fmtOdds(toAm(d))}</div></div><div><div class="k">Implied</div><div class="v num">${fmtPct(1 / d, 1)}</div></div><div><div class="k">Pays</div><div class="v num win">${fmtMoney(Math.round(pst * (d - 1) * 100) / 100)}</div></div>` : '';
  const pay = n('#hPay'), hs = n('#hStake'), ho = n('#hOdds');
  if (pay > 0 && Math.abs(ho) >= 100) {
    // Bet h on the other side so both outcomes net the same: pay - h = h*(dec-1) - hs  =>  h = (pay + hs) / dec
    const h = (pay + hs) / dec(ho);
    const lock = pay - h;
    $('#hOut').innerHTML = `<div><div class="k">Hedge stake</div><div class="v num">${fmtMoney(Math.round(h * 100) / 100)}</div></div><div><div class="k">Locked in</div><div class="v num ${lock > 0 ? 'win' : ''}">${fmtMoney(Math.round(lock * 100) / 100, true)}</div></div><div><div class="k">Either way</div><div class="v num" style="font-size:13px;font-weight:500">vs ${fmtMoney(pay)} or ${fmtMoney(-hs)}</div></div>`;
  } else $('#hOut').innerHTML = '';

  const k = S.keys;
  if (k?.n && !$('#keysTool').dataset.ready) {
    $('#keysTool').dataset.ready = '1';
    $('#keysLede').textContent = `How often ${k.n} NFL-vs-NFL games in ${k.season} ended by exactly each margin. Half a point across a tall bar is worth the most.`;
    const top = Object.entries(k.margin).map(([m, c]) => [Number(m), c]).filter(([m]) => m > 0 && m <= 35).sort((a, b) => b[1] - a[1]).slice(0, 10);
    const mx = Math.max(...top.map((x) => x[1]));
    const all = Array.from({ length: 28 }, (_, i) => i + 1);
    $('#keysBody').innerHTML = `<div class="hist">${all.map((m) => { const c = k.margin[m] || 0; return `<div class="${[3, 7, 10, 14].includes(m) ? 'k' : ''}" title="${m}: ${(c / k.n * 100).toFixed(1)}%"><i style="height:${(c / mx) * 100}%"></i><span>${m % 7 === 0 || m === 3 || m === 10 ? m : ''}</span></div>`; }).join('')}</div>
      <table class="brk" style="margin-top:12px"><thead><tr><th>Margin</th><th>Games</th><th>Share</th><th>Rank</th></tr></thead><tbody>${top.map(([m, c], i) => `<tr><td>${m}</td><td>${c}</td><td>${(c / k.n * 100).toFixed(1)}%</td><td>${i + 1}</td></tr>`).join('')}</tbody></table>`;
  }

  $('#bookTog').innerHTML = S.books.map((b) => `<button class="chip" type="button" data-hide="${b.key}" aria-pressed="${!S.hidden.has(b.key)}">${esc(b.short)}${b.sharp ? '<small>sharp</small>' : b.vegas ? '<small>NV</small>' : ''}</button>`).join('');
  const h = toolsState.health;
  const src = [
    ['ESPN', 'site.api.espn.com', 'Scores, field position, DraftKings, FPI'],
    ['Action Network', 'api.actionnetwork.com', 'Books, live lines, splits, rotation numbers'],
    ['VSiN line tracker', 'data.vsin.com', "Circa, Boomer's, Station, South Point, Westgate, Wynn"],
    ['Pinnacle', 'guest.api.arcadia.pinnacle.com', 'Sharp line and limits (up to 15 min old)'],
    ['Open-Meteo', 'api.open-meteo.com', 'Kickoff wind and rain'],
  ];
  $('#srcList').innerHTML = `<div class="list" style="padding:0">${src.map(([name, host, what]) => {
    const s = h?.sources?.[host];
    const ok = s?.lastOk && !s.lastErr;
    return `<div class="li" style="padding-left:0;padding-right:0"><span class="tag ${ok ? '' : s?.lastErr ? 'hot' : ''}">${ok ? 'OK' : s?.lastErr ? 'Error' : '…'}</span><div><div style="font-weight:600">${esc(name)}</div><div class="m">${esc(what)}</div></div><div class="v">${s?.lastOk ? esc(ago(s.lastOk)) : ''}</div></div>`;
  }).join('')}</div>`;
  $('#alertSel').value = S.alerts;
}

// ------------------------------------------------------------ footer + parlay tray
function renderFoot() {
  $('#foot').innerHTML = `Lines from Action Network, VSiN, Pinnacle and ESPN. Scores from ESPN, weather from Open-Meteo.<br>Numbers can lag the window by a few minutes. Check the ticket before you bet. 21+. Gambling problem? Call 1-800-GAMBLER.`;
}
function renderTray() {
  const saved = JSON.stringify(S.parlay);
  if (saved !== renderTray.last) { renderTray.last = saved; store.set('parlay', { at: Date.now(), legs: S.parlay }); }
  const t = $('#tray');
  t.hidden = !S.parlay.length;
  if (!S.parlay.length) return;
  const d = S.parlay.reduce((p, l) => p * dec(l.odds), 1);
  t.innerHTML = `<span>${plural(S.parlay.length, 'leg')} · ${esc(fmtOdds(toAm(d)))}</span><button type="button" data-parlay-open>Review</button><button type="button" class="x" data-parlay-clear aria-label="Clear parlay">✕</button>`;
}
