# 🏈 PICK SIX — NFL. This folder is the **NFL** app. Nothing else.

**App:** Pick Six · live NFL lines, line movement, and bet tracking
**Folder:** `~/Projects/pick-six` · **Port:** 4849 · **Repo:** `n4ngs/pick-six` (branch `main`)
**Live:** https://pick-six-production-1051.up.railway.app · health: `/api/health`

If a request is about college football or baseball, you are in the wrong folder. Stop and say so.

## Boundary — this session edits ONLY Pick Six

The three sports apps are siblings with near-identical shape (one-file Node server, same design system,
same rules), which makes them very easy to confuse. They do not share code and must not be cross-edited.

| Ask about… | It lives in | Not here |
| --- | --- | --- |
| **Pick Six** — NFL | `~/Projects/pick-six` (this folder) | — |
| **Hook & Ladder** — college football / NCAAF, port 4848 | `~/Projects/hook-and-ladder` | its own session |
| **Bing Bong Live** — MLB home runs, port 4747 | `~/bing-bong-live` | its own session |

Rules:
- Never read from or write to a sibling folder to "just make the same change." Each app has its own session.
- If asked for NCAAF or MLB work, answer: *"That's Hook & Ladder / Bing Bong Live — it lives in `<folder>`, open a session there."* Do not reach across.
- If a request mixes apps, do only the Pick Six part and name the rest as out of scope.
- Before editing anything, confirm the path you are touching starts with this folder. A file called `server.js` exists in all three.

## Deploy — users are live

- **Pushing `main` auto-deploys to Railway.** There is no staging step and no confirm. A push is a ship.
- People are on the live site. Ship silently: no banners, no "deployed by Claude," no changelog noise in the UI.
- **Uncommitted work means the live site is BEHIND what is on disk.** Before saying anything shipped, run `git status`
  and `git log origin/main..HEAD`. If either is non-empty, the change is local only — say that plainly.
- Another session may be editing this repo at the same time. Check `git status` before and after your edits, and never
  commit files you did not touch.
- Deploy settings live in `railway.json`: start `node server.js`, health `/api/health`, `numReplicas: 1`
  (bets and line history live on one volume — do not scale it up).

## Run it locally

```bash
node server.js          # from ~/Projects/pick-six → http://localhost:4849
sports local nfl        # same thing via the launcher
```
Node 18+, zero dependencies, nothing to install. `PORT` defaults to 4849. `DATA_DIR` defaults to `./data`.

## App rules

- **Nevada books only for "where to bet."** Link to each book's own site and Nevada app. The app never asks for a
  sportsbook login, never stores one, and never places a bet.
- **Informational, not prescriptive.** Steam, reverse line moves, money-vs-tickets splits and key numbers describe what
  the market is doing. Never phrase output as a pick, a lock, or advice. Estimates stay labeled as estimates.
- **Closing line value stays honest.** Counter-typed numbers are per-device and must never enter recorded line history
  or the closing line.
- Keep 21+ / 1-800-GAMBLER present wherever betting actions appear.
- Feeds (ESPN, Action Network, VSiN, Pinnacle, Open-Meteo) are unofficial public endpoints: poll gently, respect the
  existing intervals and their minimums, cache results. Do not add a paid or keyed source without being asked.
- Books are defined in `lib/books.js` — add, rename or reorder there, not inline.

## Layout

```
server.js   HTTP, event stream, polling loops, feed merge order (Action → VSiN → public → Pinnacle → ESPN)
lib/        espn, action, vsin, pinnacle, lines, bets, weather, margins, books, manual, util
public/     index.html, app.css, js/ (core, live, views, sheets, boot)
data/       bets.json, manual.json, weeks/ — runtime state, not source
```

Newest of the three apps (created 2026-09-20). Built as the NFL sibling of Hook & Ladder: same server shape,
same look, NFL lines instead of CFB. When in doubt about a pattern, match Hook & Ladder's approach — by reading
this repo's history, not its folder.
