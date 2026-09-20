'use strict';
/* Every sportsbook the app knows about, in the default board order (sharp books first, then the Vegas windows,
   then national apps for reference). To add, rename, reorder or hide a book, edit this list.
   Each viewer can also hide books in the app.

   Where a book's numbers come from (the first source that has a line wins):
     an      Action Network live odds feed, by book id: fast, and the only free source of live in-game lines
     an1     Action Network public-betting feed, by book id (Station Casinos)
     vsin    VSiN's Vegas line tracker, by column name: today's games, refreshed every few minutes
     pin     Pinnacle's public guest feed: the offshore sharp line, cached up to 15 minutes by Pinnacle
     espn    ESPN's odds provider id (DraftKings), used when Action Network is unavailable
   Any book can also take a number you type in at the counter. */

const BOOKS = [
  { key: 'circa', name: 'Circa Sports', short: 'Circa', vegas: true, sharp: true, vsin: 'Circa', an: [78] },
  { key: 'pin', name: 'Pinnacle', short: 'Pinnacle', sharp: true, pin: true },
  { key: 'stn', name: 'Station Casinos', short: 'Station', vegas: true, vsin: 'Stations', an1: [18] },
  { key: 'boom', name: "Boomer's", short: "Boomer's", vegas: true, vsin: 'Boomers' },
  { key: 'czr', name: 'Caesars', short: 'Caesars', vegas: true, an: [49], vsin: 'Caesars' },
  { key: 'mgm', name: 'BetMGM', short: 'BetMGM', vegas: true, an: [444, 75], vsin: 'BetMGM' },
  { key: 'sp', name: 'South Point', short: 'S. Point', vegas: true, vsin: 'South Point', an: [31] },
  { key: 'wg', name: 'Westgate SuperBook', short: 'Westgate', vegas: true, vsin: 'Westgate', an: [14] },
  { key: 'wynn', name: 'Wynn', short: 'Wynn', vegas: true, vsin: 'Wynn' },
  { key: 'dk', name: 'DraftKings', short: 'DK', an: [68], espn: '100' },
  { key: 'fd', name: 'FanDuel', short: 'FanDuel', an: [69] },
];

// Not books you can bet at, but columns on the board.
const CONSENSUS = { key: 'cons', name: 'Market consensus', short: 'Market', an: [15] };
const OPENER = { key: 'open', name: 'Opening line', short: 'Open', an: [30] };

const byKey = Object.fromEntries(BOOKS.map((b) => [b.key, b]));
const AN_IDS = [...new Set([CONSENSUS, OPENER, ...BOOKS].flatMap((b) => b.an || []))];

module.exports = { BOOKS, CONSENSUS, OPENER, byKey, AN_IDS };
