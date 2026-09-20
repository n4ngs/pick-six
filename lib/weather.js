'use strict';
/* Kickoff weather for outdoor games from Open-Meteo (free, no key): wind, gusts, rain chance, temperature.
   Wind is the one weather number that reliably moves totals, so it's worth having for every game. */

const { getBody, readJSON, writeJSON, log } = require('./util');

const STATES = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware',
  DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa',
  KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota',
  MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey',
  NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon',
  PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah',
  VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', PR: 'Puerto Rico',
};

const geo = readJSON('geo.json', {}); // "City, ST" -> [lat, lon] | null
async function locate(city, st) {
  const k = `${city}, ${st}`;
  if (k in geo) return geo[k];
  try {
    const j = await getBody(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=10&country=US`);
    const want = STATES[st] || st;
    const hit = (j.results || []).find((r) => r.admin1 === want) || (st ? null : j.results?.[0]);
    geo[k] = hit ? [hit.latitude, hit.longitude] : null;
    writeJSON('geo.json', geo);
  } catch (e) {
    log('geocode', k, e.message);
    return undefined; // unknown: try again next time
  }
  return geo[k];
}

const compass = (d) => (d == null ? null : ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(d / 45) % 8]);

// games: [{ id, start, venue:{city,st,indoor} }] -> Map(id -> wx)
async function forecast(games) {
  const out = new Map();
  const want = [];
  for (const g of games) {
    if (!g.venue || g.venue.indoor || !g.venue.city) continue;
    const ll = await locate(g.venue.city, g.venue.st);
    if (ll) want.push({ g, ll });
  }
  for (let i = 0; i < want.length; i += 40) {
    const chunk = want.slice(i, i + 40);
    const lat = chunk.map((x) => x.ll[0].toFixed(3)).join(',');
    const lon = chunk.map((x) => x.ll[1].toFixed(3)).join(',');
    try {
      const j = await getBody(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m,wind_direction_10m&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=UTC&forecast_days=16`, { timeout: 20000 });
      const list = Array.isArray(j) ? j : [j];
      chunk.forEach(({ g }, idx) => {
        const h = list[idx]?.hourly;
        if (!h) return;
        const hour = new Date(g.start).toISOString().slice(0, 13) + ':00';
        const at = h.time.indexOf(hour);
        if (at < 0) return;
        // Average kickoff through the second half (about 3.5 hours), and keep the worst gust.
        const span = [at, at + 1, at + 2, at + 3].filter((x) => x < h.time.length);
        const avg = (k) => Math.round(span.reduce((s, x) => s + (h[k][x] ?? 0), 0) / span.length);
        out.set(g.id, {
          temp: Math.round(h.temperature_2m[at]),
          wind: avg('wind_speed_10m'),
          gust: Math.round(Math.max(...span.map((x) => h.wind_gusts_10m[x] ?? 0))),
          dir: compass(h.wind_direction_10m[at]),
          pop: Math.max(...span.map((x) => h.precipitation_probability[x] ?? 0)),
          src: 'Open-Meteo',
          at: Date.now(),
        });
      });
    } catch (e) {
      log('weather', e.message);
    }
  }
  return out;
}

module.exports = { forecast };
