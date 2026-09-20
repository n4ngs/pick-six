'use strict';
/* Pick Six — "Most likely to hit": your open bets ranked by their chance to cash, live.
   Where each leg's chance comes from:
     live game       coverChance (core.js), the live market line and time left. est.
     before kickoff  the sharp fair price with the vig removed (fairFor, sheets.js); if the sharp book isn't on
                     your number, the price you took (vig included, so slightly low). est.
     final           the result (won 100%, lost 0%, push counts as surviving).
   A parlay's chance is its open legs multiplied together. Expected profit = chance × payout − (1 − chance) × stake. */

const HIT_TIERS = [[0.6, 'Likely'], [0.4, 'Toss-up'], [0, 'Long shot']];
const hitTier = (p) => HIT_TIERS.find(([t]) => p >= t)[1];

// One leg: { p, how, now, g } where now = points ahead of the number (live/final) and how says where p came from.
function hitLeg(l) {
  if (l.state === 'won') return { p: 1, how: 'won' };
  if (l.state === 'lost') return { p: 0, how: 'lost' };
  if (l.state === 'push' || l.state === 'void') return { p: 1, how: 'push' };
  const g = gameById(l.gid);
  if (!g) return { p: l.odds != null ? imp(l.odds) : 0.5, how: 'price' };
  const now = isPre(g) ? null : legNow(g, l);
  if (isFinal(g)) return { p: now > 0 ? 1 : now < 0 ? 0 : 1, how: now > 0 ? 'won' : now < 0 ? 'lost' : 'push', now, g };
  if (isLive(g)) {
    const p = coverChance(g, l);
    if (p != null) return { p, how: 'live', now, g };
    return { p: now > 0 ? 0.6 : now < 0 ? 0.4 : 0.5, how: 'live', now, g, rough: true }; // halves and team totals: no model yet
  }
  const f = typeof fairFor === 'function' ? fairFor(g, l) : null;
  if (f) return { p: f.p, how: 'fair', g };
  return { p: l.odds != null ? imp(l.odds) : 0.5, how: 'price', g };
}

// One bet: its chance, what it pays, what it's expected to make, and the leg to open when tapped.
function hitBet(b) {
  const legs = b.legs.map((l) => ({ l, ...hitLeg(l) }));
  const p = legs.reduce((acc, x) => acc * x.p, 1);
  const open = legs.filter((x) => x.how === 'live' || x.how === 'fair' || x.how === 'price');
  const pays = toWin(b.stake, b.odds) || 0;
  const weakest = [...open].sort((x, y) => x.p - y.p)[0] || legs[0];
  const live = legs.some((x) => x.how === 'live');
  const kick = Math.min(...legs.map((x) => (x.g ? Date.parse(x.g.start) : Infinity)));
  // green only when your ticket is actually winning right now
  const winning = legs.every((x) => x.how === 'won' || x.how === 'push' || (x.how === 'live' && x.now > 0));
  return { b, legs, p, pays, ev: p * pays - (1 - p) * b.stake, weakest, live, kick, winning: live && winning };
}

function hitStatus(x) {
  const g = x.weakest?.g;
  if (x.b.legs.length > 1) {
    const left = x.legs.filter((y) => y.how === 'live' || y.how === 'fair' || y.how === 'price').length;
    return `${left} of ${x.legs.length} legs left${x.weakest && left ? ` · weakest ${esc(betLegShort(x.weakest.l))} ${fmtPct(x.weakest.p)}` : ''}`;
  }
  if (!g) return esc(x.b.legs[0].matchup || '');
  if (isLive(g)) {
    const now = x.weakest.now;
    const where = now == null ? '' : now > 0 ? ` · covering by ${trim(now)}` : now < 0 ? ` · needs ${trim(-now)}` : ' · on the number';
    return `<span class="dot pulse"></span>${esc(g.away.abbr)} ${g.away.score ?? 0}–${g.home.score ?? 0} ${esc(g.home.abbr)} · ${esc(clockLabel(g))}${esc(where)}`;
  }
  return `${esc(g.away.abbr)} @ ${esc(g.home.abbr)} · ${esc(dayLabel(g.start))} ${esc(timeLabel(g.start))}`;
}
const betLegShort = (l) => l.label || '';

// The ranked board, shown above your open bets.
function hitList(bets) {
  const open = bets.filter((b) => b.status === 'open');
  if (!open.length) return '';
  const rows = open.map(hitBet);
  const sort = store.get('hitSort', 'p');
  rows.sort(sort === 'time' ? (a, b) => a.kick - b.kick || b.p - a.p : (a, b) => b.p - a.p || a.kick - b.kick);
  const exp = rows.reduce((s, x) => s + x.p, 0);
  const ev = rows.reduce((s, x) => s + x.ev, 0);
  const risk = rows.reduce((s, x) => s + x.b.stake, 0);
  const anyPrice = rows.some((x) => x.legs.some((y) => y.how === 'price'));
  const row = (x, i) => {
    const pct = Math.round(x.p * 100);
    const openGid = x.weakest?.l?.gid || x.b.legs[0].gid;
    return `<button type="button" class="hit-row${x.live ? ' is-live' : ''}" data-open="${esc(openGid)}" aria-label="${esc(`${betLabel(x.b)}, ${pct}% estimated chance to cash, ${hitTier(x.p)}`)}">
      <span class="hit-rk num" aria-hidden="true">${i + 1}</span>
      <span class="hit-main">
        <b class="hit-pick">${esc(betLabel(x.b))} <small class="num">${esc(fmtOdds(x.b.odds))}</small></b>
        <span class="hit-sub">${hitStatus(x)}</span>
        <span class="hit-bar" aria-hidden="true"><i class="${x.winning ? 'win' : ''}" style="width:${Math.max(2, pct)}%"></i><em style="left:50%"></em></span>
      </span>
      <span class="hit-v"><b class="num${x.winning && x.p >= 0.5 ? ' win' : ''}">${pct}%</b><span class="hit-tier t-${hitTier(x.p).replace(/\W/g, '').toLowerCase()}">${hitTier(x.p)}</span></span>
    </button>`;
  };
  return `<section class="card hit" aria-labelledby="hitTitle">
    <div class="hit-h">
      <div><h3 id="hitTitle">Most likely to hit</h3><p>Updates live. Chances are est.${rows.some((x) => x.winning) ? ' A green bar is covering right now.' : ''}${anyPrice ? ' Some pre-game bets use the price you took.' : ''}</p></div>
      <div class="seg hit-seg" role="group" aria-label="Order"><button type="button" data-hit-sort="p" aria-pressed="${sort !== 'time'}">Likeliest</button><button type="button" data-hit-sort="time" aria-pressed="${sort === 'time'}">Kickoff</button></div>
    </div>
    <div class="hit-sum">
      <div><b class="num">${exp.toFixed(1)}</b><span>of ${open.length} expected to cash</span></div>
      <div><b class="num">${esc(fmtMoney(Math.round(ev), true))}</b><span>expected profit, est.</span></div>
      <div><b class="num">${esc(fmtMoney(risk))}</b><span>at risk</span></div>
    </div>
    <div class="hit-list">${rows.map(row).join('')}</div>
  </section>`;
}

document.addEventListener('click', (ev) => {
  const t = ev.target.closest('[data-hit-sort]');
  if (!t) return;
  store.set('hitSort', t.dataset.hitSort);
  invalidate();
});
