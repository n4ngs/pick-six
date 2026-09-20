# Pick Six

Live NFL lines for bettors. Every NFL game with the Las Vegas windows (Circa, Boomer's,
Station, South Point, Westgate, Wynn, Caesars, BetMGM), Pinnacle, DraftKings and FanDuel side by side,
lines that move on screen as the books move them, a chart of every move since the open, and your own
bets sweating live and grading themselves the second a game ends.

It's the NFL sibling of Hook & Ladder (college football) and Bing Bong Live (baseball): same build (one small
Node server, no installs), same look (one typeface, one live red), same idea that every number comes with a
plain-English read.

## Run it

```bash
node server.js
```

Then open http://localhost:4849. On a Mac you can also double-click **Start Pick Six.command**.

It needs Node 18 or newer and has no dependencies, so there's nothing to install. To use it on your
iPhone, tap **Open on iPhone** at the top of the desktop page and scan the code (same Wi-Fi).

## What's on the page

- **Live.** Games in progress with the field drawn live: down and distance, where the ball is, the
  first-down line, red zone. Each game shows the closing line, the live line, win chance, and whether
  the favorite is covering.
  - **Your sweat.** When you have money on a live game, the top card shows every live bet with how far
    it's covering or how many points it needs, and an estimated chance to cash.
  - **Line moving.** When books move a line, a card appears within seconds. It flags steam (three or more
    books moving the same way within 10 minutes), key-number crossings (3, 7, 10, 14), a favorite
    flipping, and any move of 1.5 points or more.
  - **Sharp signals.** Reverse line moves (the line moving against the side most tickets are on) and
    bigger-bet sides (money % well above tickets %).
- **Board.** The whole week, grouped by TV window (Thursday night, Sunday early, Sunday late, Sunday night,
  Monday night, and the London kickoffs), with Spread / Total / Money / 1st half.
  - Desktop shows a full odds screen with every book as a column. The best price on each side is
    highlighted, and each game shows its open, movement sparkline, and tickets vs money.
  - Prices flash when they change, and dim if their source hasn't confirmed them in 15 minutes.
  - Vegas rotation numbers are on every game.
  - Filter by conference, division, your teams, your bets, or games that are moving. Browse past weeks
    with the arrows.
- **Game sheet** (tap any game):
  - An interactive line chart: drag across it to read every book at any moment, from the open to kickoff
    to the live line.
  - Every book's price, plus each Vegas book's own opening number. Tap any price to log a bet at it.
  - Where the money is (tickets vs money), and ESPN's FPI projection turned into a point spread.
  - Pinnacle's no-vig price and its bet limit, and kickoff wind and gusts.
  - Key numbers for this exact spread, first-half lines, team totals, and, once the game starts, win
    probability, box score and scoring.
- **My bets.**
  - Log straight bets or parlays in two taps from any price.
  - Every bet grades itself when its game ends, and closing line value (your number vs the final number
    at kickoff) is recorded automatically.
  - Results show net profit, record, ROI, average points vs the close, and profit by market and by book.
    Export to CSV.
- **Tools.** Odds converter, no-vig fair price, parlay, hedge, and a key-number table measured from last
  season's actual NFL finals. Also: pick which books show, check each data source's health, and set
  your unit size and alerts.
- **Add a number from the counter.** Standing at a sportsbook window? Type what the board says. It shows
  on *your* board with a marker and a timestamp until that book's feed reports a newer change. Typed numbers
  belong to the device that typed them: friends sharing the app never see each other's, and nothing typed in
  reaches the recorded line history or the closing line, so closing line value stays honest.
- **Where to bet** (Tools, and from any bet slip). Every Nevada book on the board with a link to its own site
  and its Nevada app. You sign in at the book: this app never asks for a sportsbook login, never stores one,
  and never places a bet. Nevada also wants a one-time in-person signup and for you to be inside the state.
- **On a phone, pick the book.** The narrow board has room for two numbers per team: the book you choose from
  the chips above the board (Market by default, or Circa, Caesars, BetMGM, Station…) and the best price
  anywhere. The wide board shows every book at once.
- **Alerts** (bell icon): off, your bets and teams, or every line move. Alerts cover steam, key numbers,
  kickoff, cover flips, red zone and final results, with a sound and a desktop notification.

## Where the data comes from

All of these are free and need no key.

| Source | What it gives | How often |
| --- | --- | --- |
| ESPN scoreboard | Schedule, live score, down and distance, field position, DraftKings open and current, weather | Every 8 s while games are live |
| ESPN game summary | Win probability by play, drives, box score, FPI projection | When you open a game, and in the background for FPI |
| Action Network (odds feed) | Consensus, opener, DraftKings, FanDuel, BetMGM NV, Caesars NV, pregame and **live in-game**; public tickets and money; team totals; rotation numbers; live cover chance | Every 15 s near and during games |
| Action Network (public-betting feed) | Station Casinos, first-half lines, the opener's timestamp | Every 90 s on game days |
| VSiN Vegas line tracker | Circa, Boomer's, Station, South Point, Westgate, Wynn, Caesars, BetMGM: current line, each book's opener, and first-half lines | Checked every 2 min; only processed when VSiN's "Odds updated" time changes |
| Pinnacle | The offshore sharp line and its bet limit | Every 10 min (Pinnacle caches it for up to 15) |
| Open-Meteo | Wind, gusts, rain chance and temperature for kickoff through the fourth quarter | Hourly |
| ESPN (last season) | Final margins of every NFL game, regular season and playoffs, for the key-number tables | Once, then cached |

When more than one feed carries a book, the fastest wins: Action Network, then VSiN, then the
public-betting feed, then Pinnacle, then ESPN. Books are defined in `lib/books.js`; edit that list to
add, rename or reorder one.

Nobody publishes NFL line history for free, so the app keeps its own. Every change it sees
is written to `data/weeks/`, which is what the charts and steam alerts are built from. The longer it
runs, the more history you have. Openers come with their timestamp from the feed, so each chart still
starts at the true open.

## Settings

| Env var | Default | Meaning |
| --- | --- | --- |
| `PORT` | `4849` | Port to serve on |
| `LIVE_MS` | `8000` | How often scores are checked while games are live, in ms (minimum 4000) |
| `ODDS_MS` | `15000` | How often lines are checked near and during games, in ms (minimum 8000) |
| `HOT_MS` | `9000` | How often lines are checked in the last 15 minutes before kickoff and in game (minimum 6000) |
| `VSIN_MS` | `120000` | How often the Vegas line tracker is checked (minimum 60000) |
| `PIN_MS` | `600000` | How often Pinnacle is checked (minimum 300000) |
| `SOURCES_OFF` | | Comma list of sources to skip: `vsin`, `pinnacle` |
| `DATA_DIR` | `./data` | Where bets, counter numbers and line history are saved |
| `ACCESS_CODE` | | Require a code to open the app. Set this before putting it on the internet |

### Putting it online (Railway or similar)

`railway.json` has the deploy settings: start with `node server.js`, health check `/api/health`, and one
instance only (bets and line history live on one volume). On Railway the "Open on iPhone" code points at
the app's public address instead of your Wi-Fi.

1. Set `ACCESS_CODE` to a long passphrase. With it set, every page and API asks for the code once per
   device. Wrong codes are limited to 5 per 15 minutes per address.
2. Point `DATA_DIR` at a persistent volume, so bets and line history survive redeploys.
3. The platform sets `PORT` for you.

The login cookie stays valid until the code changes, so changing `ACCESS_CODE` signs every device out.

### Sharing it with friends

One access code lets everyone in, and each device still gets its own private log. A random id is set in a
secure cookie on the first visit; bets, counter numbers and CSV exports are scoped to that id, so nobody
reads or moves anybody else's. The board itself — feeds, line history, closing lines — is shared, which is
the point. Changes are capped at 120 per device per five minutes, well above real use, so one stuck script
can't churn the files. To read one log from a second device, use the link code in Tools.

## Files

```
server.js          HTTP, the event stream, polling loops, and how the feeds merge
lib/espn.js        ESPN scoreboard and game summary
lib/action.js      Action Network odds and public-betting feeds
lib/vsin.js        VSiN Vegas line tracker (reads the HTML table)
lib/pinnacle.js    Pinnacle guest feed
lib/lines.js       Line history, steam / key-number / flip detection, closing lines
lib/bets.js        Your bets: validation, grading, closing line value, CSV
lib/weather.js     Kickoff weather (Open-Meteo)
lib/margins.js     Key numbers from last season's finals
lib/books.js       The list of sportsbooks, where each one's numbers come from, and its site and app
lib/manual.js      Counter numbers, kept per device
lib/util.js        Fetch with backoff, dates, files, team-name matching
public/            The app: index.html, app.css, js/core, live, views, sheets, boot
railway.json       Railway deploy settings
data/              Created on first run: bets.json, manual.json, weeks/, caches
```

## Notes

- **Lines can lag the window.** Feeds typically run seconds to a few minutes behind the books, and
  Pinnacle up to 15 minutes. Always check the price on the ticket.
- **These feeds are unofficial.** VSiN, Action Network and Pinnacle's guest feed are public web pages
  and endpoints, not licensed APIs. The app polls them gently and caches the results. It's for personal
  use only; don't resell or republish the data.
- **Estimates are labeled as estimates:**
  - "Chance to cash" comes from the live market line and the time left.
  - FPI's win chance is converted to a spread assuming final margins vary about 16 points around the
    market.
  - Wind is averaged from kickoff through about the fourth quarter.
- **Signals aren't advice.** Steam, reverse moves and money splits describe what the market is doing.
  They don't tell you what will happen.
- 21+. Gambling problem? Call 1-800-GAMBLER.
