'use strict';
/* Pick Six — Closing line value report card (My bets → Results).
   At kickoff the server records, for every bet, how your number compared with where the market closed (lib/bets.js
   clvOf): points for spreads and totals, and percent for moneylines and same-number juice. Beating the close is the
   most reliable sign of good betting over time, and it says nothing about any single result. The card reports it
   plainly, with how many bets it's based on, and never suggests betting more. */

const CLV_MKT = { s: 'Spreads', t: 'Totals', ml: 'Moneylines', h1s: '1st-half spreads', h1t: '1st-half totals', tt: 'Team totals' };

function clvLegs() {
  const out = [];
  for (const b of S.bets) {
    if (b.status === 'void') continue;
    for (const l of b.legs) if (l.clv && (l.clv.pts != null || l.clv.pct != null)) out.push({ b, l, t: Date.parse(b.placed) || b.created || 0 });
  }
  return out.sort((x, y) => x.t - y.t);
}
const clvAvg = (a) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : null);
const clvSigned = (v, unit, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? MINUS : ''}${Math.abs(v).toFixed(d)}${unit}`);

function clvCard() {
  const legs = clvLegs();
  if (!legs.length) return `<div class="card clv"><h3>Closing line value</h3><p class="clv-lede">At kickoff, each bet is compared with where the market closed. Getting a better number than the close is the most reliable sign of good betting over time. Your report shows up after your first bet kicks off.</p></div>`;
  const pts = legs.filter((x) => x.l.clv.pts != null).map((x) => x.l.clv.pts);
  const pcts = legs.filter((x) => x.l.clv.pts == null || x.l.clv.pts === 0).map((x) => x.l.clv.pct).filter((v) => v != null);
  const avgPts = clvAvg(pts), avgPct = clvAvg(pcts);
  const beat = pts.filter((v) => v > 0).length, same = pts.filter((v) => v === 0).length, worse = pts.filter((v) => v < 0).length;
  const n = legs.length;
  // Plain verdict; the sample size comes first because it matters most.
  let verdict;
  if (n < 20) verdict = `Early days: ${plural(n, 'bet')} with a closing number. Closing line value starts to mean something around 50 bets.`;
  else if ((avgPts ?? 0) > 0.3 || (avgPts == null && (avgPct ?? 0) > 1)) verdict = 'You’re regularly getting a better number than where the market closed. Over time that’s the most reliable sign of good betting, though it says nothing about any single result.';
  else if ((avgPts ?? 0) < -0.3 || (avgPts == null && (avgPct ?? 0) < -1)) verdict = 'You’re usually getting a worse number than the close. Betting earlier, or comparing books before you bet, tends to help.';
  else verdict = 'You’re getting about the closing number on average.';
  // Running average in points over time.
  let run = 0;
  const series = legs.filter((x) => x.l.clv.pts != null).map((x, i) => (run += x.l.clv.pts) / (i + 1));
  const chart = series.length >= 3 ? clvSpark(series) : '';
  // By market and by book.
  const group = (keyOf) => {
    const m = new Map();
    for (const x of legs) {
      const k = keyOf(x); const r = m.get(k) || { n: 0, pts: [], pct: [], beat: 0, beatPct: 0 }; r.n++;
      if (x.l.clv.pts != null) { r.pts.push(x.l.clv.pts); if (x.l.clv.pts > 0) r.beat++; }
      else if (x.l.clv.pct != null) { r.pct.push(x.l.clv.pct); if (x.l.clv.pct > 0) r.beatPct++; }
      m.set(k, r);
    }
    return [...m].sort((a, b) => b[1].n - a[1].n);
  };
  const rows = (title, g) => `<table class="brk clv-t"><thead><tr><th>${esc(title)}</th><th>Bets</th><th>Avg vs close</th><th>Beat it</th></tr></thead><tbody>${g.map(([k, r]) => `<tr><td>${esc(k)}</td><td>${r.n}</td><td>${r.pts.length ? clvSigned(clvAvg(r.pts), ' pts') : r.pct.length ? clvSigned(clvAvg(r.pct), '%') : '—'}</td><td>${r.pts.length ? fmtPct(r.beat / r.pts.length) : r.pct.length ? fmtPct(r.beatPct / r.pct.length) : '—'}</td></tr>`).join('')}</tbody></table>`;
  return `<div class="card clv">
    <h3>Closing line value</h3>
    <p class="clv-lede">How your number compared with where the market closed at kickoff. It measures the price you got, not whether you won.</p>
    <div class="clv-sum">
      <div><b class="num">${pts.length ? clvSigned(avgPts, '') : clvSigned(avgPct, '%')}</b><span>${pts.length ? 'avg points vs the close' : 'avg vs the close'}</span></div>
      <div><b class="num">${pts.length ? fmtPct(beat / pts.length) : '—'}</b><span>beat the close</span></div>
      <div><b class="num">${n}</b><span>bets measured</span></div>
    </div>
    ${pts.length ? `<div class="clv-split" aria-label="${beat} better, ${same} same, ${worse} worse than the close"><i style="flex:${beat}"></i><i style="flex:${same}"></i><i style="flex:${worse}"></i></div><div class="clv-split-l"><span>Better ${beat}</span><span>Same ${same}</span><span>Worse ${worse}</span></div>` : ''}
    <p class="clv-v">${esc(verdict)}</p>
    ${chart}
    ${rows('Market', group((x) => CLV_MKT[x.l.mkt] || x.l.mkt))}
    ${rows('Book', group((x) => x.b.book || 'Unknown'))}
    ${avgPct != null && pts.length ? `<p class="note">On moneylines and same-number bets the price difference averages ${clvSigned(avgPct, '%')} against the close with the cut removed.</p>` : ''}
  </div>`;
}
function clvSpark(series) {
  const W = 640, H = 120, P = 8;
  const lo = Math.min(0, ...series), hi = Math.max(0, ...series);
  const X = (i) => P + (i / Math.max(1, series.length - 1)) * (W - 2 * P);
  const Y = (v) => P + ((hi - v) / (hi - lo || 1)) * (H - 2 * P);
  return `<div class="clv-chart"><div class="sub-h">Running average<span>points vs the close, over time</span></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Running average closing line value, now ${clvSigned(series.at(-1), ' points')}">
      <line class="z" x1="${P}" x2="${W - P}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/>
      <polyline class="ln" points="${series.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')}"/>
      <circle class="end" cx="${X(series.length - 1).toFixed(1)}" cy="${Y(series.at(-1)).toFixed(1)}" r="4"/>
    </svg></div>`;
}
