'use strict';
/* ESPN NFL: the week's schedule, live scores and field position, DraftKings lines, weather,
   and (per game, on demand) win probability, drives, box score and ESPN's matchup projection. */

const { getBody, num, norm, etDate } = require('./util');

const SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl';

// The eight divisions, by team abbreviation: the NFL's own filter, and stable year to year.
const DIV = {
  BUF: 'AFC East', MIA: 'AFC East', NE: 'AFC East', NYJ: 'AFC East',
  BAL: 'AFC North', CIN: 'AFC North', CLE: 'AFC North', PIT: 'AFC North',
  HOU: 'AFC South', IND: 'AFC South', JAX: 'AFC South', TEN: 'AFC South',
  DEN: 'AFC West', KC: 'AFC West', LAC: 'AFC West', LV: 'AFC West',
  DAL: 'NFC East', NYG: 'NFC East', PHI: 'NFC East', WSH: 'NFC East',
  CHI: 'NFC North', DET: 'NFC North', GB: 'NFC North', MIN: 'NFC North',
  ATL: 'NFC South', CAR: 'NFC South', NO: 'NFC South', TB: 'NFC South',
  ARI: 'NFC West', LAR: 'NFC West', SEA: 'NFC West', SF: 'NFC West',
};
const CONF = DIV; // the board's filter list reads this

const scoreboardUrl = ({ season, type, week }) =>
  `${SITE}/scoreboard?limit=100${week ? `&week=${week}&seasontype=${type}&dates=${season}` : ''}`;

// The season calendar: every week label with its date range. Drives week navigation.
function calendarOf(j) {
  const league = j.leagues?.[0] || {};
  const out = [];
  for (const part of league.calendar || []) {
    const type = Number(part.value);
    if (type !== 2 && type !== 3) continue; // regular season and postseason only
    for (const e of part.entries || []) {
      out.push({ type, week: Number(e.value), label: type === 3 ? (e.label === 'Bowls' ? 'Bowls' : e.label) : e.label, detail: e.detail, start: e.startDate, end: e.endDate });
    }
  }
  return { season: league.season?.year || Number(String(j.season?.year || '').slice(0, 4)) || null, weeks: out };
}

function team(c) {
  const t = c.team || {};
  const rank = c.curatedRank?.current;
  return {
    id: t.id,
    abbr: t.abbreviation,
    name: t.displayName,
    short: t.shortDisplayName || t.location,
    loc: t.location,
    mascot: t.name,
    color: t.color ? `#${t.color}` : null,
    alt: t.alternateColor ? `#${t.alternateColor}` : null,
    logo: t.logo || `https://a.espncdn.com/i/teamlogos/ncaa/500/${t.id}.png`,
    conf: DIV[t.abbreviation] || '',
    div: DIV[t.abbreviation] || '',
    rank: rank && rank <= 25 ? rank : null,   // the NFL doesn't rank, so this stays empty
    rec: c.records?.find((r) => r.type === 'total')?.summary || c.records?.[0]?.summary || null,
    score: c.score === undefined || c.score === '' ? null : num(c.score),
    q: (c.linescores || []).map((l) => num(l.value) ?? 0),
    key: norm(t.displayName),
    locKey: norm(t.location),
  };
}

// ESPN occasionally swaps the weather text and code fields; take whichever one reads like words.
function weatherOf(w) {
  if (!w) return null;
  const words = [w.displayValue, w.conditionId].find((x) => x && Number.isNaN(Number(x)));
  return { temp: num(w.temperature), cond: words || null };
}

// DraftKings, as ESPN shows it. Numbers are from the home team's side.
function dkOdds(o) {
  if (!o) return null;
  const n = (s) => num(String(s ?? '').replace(/^[ou]/, ''));
  const ps = o.pointSpread || {}, tot = o.total || {}, ml = o.moneyline || {};
  const cur = {
    s: n(ps.home?.close?.line) ?? num(o.spread),
    so: [n(ps.home?.close?.odds), n(ps.away?.close?.odds)],
    t: n(tot.over?.close?.line) ?? num(o.overUnder),
    to: [n(tot.over?.close?.odds), n(tot.under?.close?.odds)],
    ml: [n(ml.home?.close?.odds), n(ml.away?.close?.odds)],
  };
  const open = {
    s: n(ps.home?.open?.line), so: [n(ps.home?.open?.odds), n(ps.away?.open?.odds)],
    t: n(tot.over?.open?.line), to: [n(tot.over?.open?.odds), n(tot.under?.open?.odds)],
    ml: [n(ml.home?.open?.odds), n(ml.away?.open?.odds)],
  };
  return { cur, open };
}

function gameFromEvent(e) {
  const c = e.competitions?.[0] || {};
  const st = c.status || e.status || {};
  const type = st.type || {};
  const home = c.competitors?.find((x) => x.homeAway === 'home');
  const away = c.competitors?.find((x) => x.homeAway === 'away');
  if (!home || !away) return null;
  const s = c.situation || {};
  const H = team(home), A = team(away);
  const poss = s.possession ? (String(s.possession) === H.id ? 'home' : String(s.possession) === A.id ? 'away' : null) : null;
  const dead = /POSTPONED|CANCELED|CANCELLED|SUSPENDED|FORFEIT/.test(type.name || '');
  const g = {
    id: String(e.id),
    start: c.date || e.date,
    tbd: c.timeValid === false,
    day: etDate(new Date(c.date || e.date)),
    state: dead ? 'off' : type.state || 'pre', // pre | in | post | off
    final: !!type.completed && !dead,
    half: type.name === 'STATUS_HALFTIME',
    detail: type.shortDetail || type.detail || '',
    period: num(st.period) || 0,
    clock: st.displayClock || null,
    secs: num(st.clock),
    neutral: !!c.neutralSite,
    confGame: !!c.conferenceCompetition,
    note: c.notes?.[0]?.headline || null,
    tv: c.broadcast || c.broadcasts?.[0]?.names?.[0] || null,
    venue: c.venue ? { name: c.venue.fullName, city: c.venue.address?.city, st: c.venue.address?.state, indoor: !!c.venue.indoor } : null,
    home: H,
    away: A,
    poss,
    sit: type.state === 'in' && s.down > 0
      ? {
        down: s.down, dist: s.distance, yl: num(s.yardLine), text: s.downDistanceText || null, short: s.shortDownDistanceText || null,
        spot: s.possessionText || null, rz: !!s.isRedZone, to: [num(s.homeTimeouts), num(s.awayTimeouts)],
      }
      : type.state === 'in' ? { yl: num(s.yardLine), to: [num(s.homeTimeouts), num(s.awayTimeouts)] } : null,
    last: s.lastPlay?.text || null,
    lastType: s.lastPlay?.type?.abbreviation || null,
    // Where the last play started and ended, so the field can draw it. Same absolute axis as sit.yl:
    // 0 is the home end zone, 100 the away one, and it does not flip between periods.
    lastYl: s.lastPlay && num(s.lastPlay.start?.yardLine) != null && num(s.lastPlay.end?.yardLine) != null
      ? [num(s.lastPlay.start.yardLine), num(s.lastPlay.end.yardLine), num(s.lastPlay.statYardage)]
      : null,
    wx: weatherOf(e.weather),
    dk: dkOdds(c.odds?.find((o) => String(o.provider?.id) === '100') || c.odds?.[0]),
  };
  return g;
}

// ---------------------------------------------------------------- summary (one game)
function summaryOf(j) {
  const out = { at: Date.now() };
  const pred = j.predictor;
  if (pred?.homeTeam?.gameProjection) out.fpi = { home: num(pred.homeTeam.gameProjection) / 100 };
  // Win probability, one point per play. Keep it compact: [homeWin%, playId].
  const wp = j.winprobability || [];
  if (wp.length) out.wp = wp.map((p) => Math.round(p.homeWinPercentage * 1000) / 10);
  const gw = j.gameInfo?.weather;
  if (gw) out.wx = { temp: num(gw.temperature), gust: num(gw.gust), pop: num(gw.precipitation) };
  // Who is hurt. ESPN sends at most five names per team here, so this is the headline list, not the
  // full report — say so wherever it is shown. The athlete id is what ties a name to the depth chart.
  const inj = (j.injuries || []).map((t) => ({
    team: String(t.team?.id || ''),
    rows: (t.injuries || []).map((r) => ({
      id: String(r.athlete?.id || '') || null,
      name: r.athlete?.displayName || null,
      pos: r.athlete?.position?.abbreviation || null,
      status: r.status || null,
      date: r.date || null,
    })).filter((r) => r.name),
  })).filter((t) => t.rows.length);
  if (inj.length) out.inj = inj;
  // Box score stats bettors read during a game.
  const pick = ['totalYards', 'netPassingYards', 'rushingYards', 'turnovers', 'thirdDownEff', 'fourthDownEff', 'possessionTime', 'firstDowns', 'totalPenaltiesYards', 'yardsPerRushAttempt', 'yardsPerPass'];
  const box = {};
  const plays = {};
  for (const t of j.boxscore?.teams || []) {
    const side = t.homeAway === 'home' ? 'home' : 'away';
    let yds = null, n = 0;
    for (const s of t.statistics || []) {
      if (s.name === 'totalYards') yds = num(s.displayValue);
      if (s.name === 'rushingAttempts') n += num(s.displayValue) || 0;
      if (s.name === 'completionAttempts') n += num(String(s.displayValue).split(/[/-]/)[1]) || 0;
      if (!pick.includes(s.name)) continue;
      (box[s.name] ||= { label: s.label, home: null, away: null })[side] = String(s.displayValue).trim();
    }
    // Yards per play isn't in the feed: total yards over rushes plus pass attempts (sacks aside).
    if (yds != null && n > 0) plays[side] = (yds / n).toFixed(1);
  }
  if (plays.home || plays.away) box.yardsPerPlay = { label: 'Yards per play', home: plays.home || null, away: plays.away || null };
  if (Object.keys(box).length) out.box = box;
  out.scoring = (j.scoringPlays || []).map((p) => ({
    q: p.period?.number, clock: p.clock?.displayValue, team: String(p.team?.id || ''), type: p.type?.abbreviation || p.type?.text,
    text: p.text, a: num(p.awayScore), h: num(p.homeScore),
  }));
  const drives = [...(j.drives?.previous || [])];
  if (j.drives?.current && !drives.some((d) => d.id === j.drives.current.id)) drives.push(j.drives.current);
  out.drives = drives.slice(-40).map((d) => ({
    team: String(d.team?.id || ''), desc: d.description, result: d.displayResult || d.result || null, score: !!d.isScore,
    q: d.start?.period?.number, start: d.start?.text, end: d.end?.text, yds: num(d.yards), plays: num(d.offensivePlays),
  }));
  out.last5 = (j.lastFiveGames || []).map((t) => ({
    team: String(t.team?.id || ''),
    games: (t.events || []).slice(0, 5).map((ev) => ({ date: ev.gameDate, opp: ev.opponent?.abbreviation, at: ev.atVs, res: ev.gameResult, score: ev.score })),
  }));
  const ats = (j.againstTheSpread || []).map((t) => ({ team: String(t.team?.id || ''), rec: (t.records || []).map((r) => ({ name: r.name || r.type, summary: r.summary })) })).filter((t) => t.rec.length);
  if (ats.length) out.ats = ats;
  return out;
}

async function fetchScoreboard(week) {
  return getBody(`${scoreboardUrl(week || {})}&_=${Math.floor(Date.now() / 5000)}`);
}
async function fetchSummary(id) {
  return getBody(`${SITE}/summary?event=${id}`);
}

module.exports = { CONF, DIV, calendarOf, gameFromEvent, summaryOf, fetchScoreboard, fetchSummary };
