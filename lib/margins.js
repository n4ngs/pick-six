'use strict';
/* Key numbers, measured instead of quoted: how often last season's NFL games ended by exactly N points,
   and how often the combined score landed on each total. Built once from ESPN's final scores, then cached.
   Three and seven carry more weight in the NFL than anywhere else in sport. */

const { getBody, readJSON, writeJSON, log, pool } = require('./util');

const SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl';

async function build(season) {
  const cached = readJSON(`margins-${season}.json`, null);
  if (cached?.n > 200) return cached;
  const margin = {}, total = {};
  let n = 0;
  const weeks = [...Array.from({ length: 18 }, (_, i) => ({ type: 2, week: i + 1 })), ...Array.from({ length: 5 }, (_, i) => ({ type: 3, week: i + 1 }))];
  const seen = new Set();
  await pool(weeks, 3, async ({ type, week }) => {
    const j = await getBody(`${SITE}/scoreboard?limit=100&week=${week}&seasontype=${type}&dates=${season}`, { timeout: 25000 });
    for (const e of j.events || []) {
      const c = e.competitions?.[0];
      if (!c?.status?.type?.completed || seen.has(e.id)) continue;
      const [a, b] = c.competitors || [];
      if (!a || !b) continue;
      const sa = Number(a.score), sb = Number(b.score);
      if (!Number.isFinite(sa) || !Number.isFinite(sb)) continue;
      seen.add(e.id);
      const m = Math.abs(sa - sb), t = sa + sb;
      margin[m] = (margin[m] || 0) + 1;
      total[t] = (total[t] || 0) + 1;
      n++;
    }
  });
  const out = { season, n, margin, total, built: Date.now() };
  if (n > 200) writeJSON(`margins-${season}.json`, out);
  log(`key numbers from ${season}: ${n} NFL games`);
  return out;
}

let current = null;
async function margins(season) {
  if (current?.season === season) return current;
  try { current = await build(season); } catch (e) { log('margins', e.message); }
  return current;
}

module.exports = { margins };
