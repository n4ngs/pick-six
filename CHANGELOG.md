# Pick Six — changelog

Newest first. Dates are when the change went live on Railway.

## 2026-09-20

The day the app was built, shipped, and opened up to other people.

### Sharing, and who sees what
- **Share links.** The owner makes one link per person in the new **Group** tab and sends it. Tapping it
  lets that phone in for good — a guest never types a code. Turning a link off locks out only the phones
  that used it. (`77002d3`, `049e747`)
- **A Group tab for whoever runs the board.** Who has joined, what the group has running, and each
  person's log. (`77002d3`)
- **Link two of your own devices.** A short code, good for ten minutes, folds a second device into the
  same bet log — one row on the board instead of two, and bets logged on either appear on both.
  (`ccd9afe`)
- **Opening your own share link says so** rather than appearing to do nothing. (`d32afdb`)
- **The guest's own card** moved in with the other per-device settings in Tools. (`b1bae08`)
- **The guest card now reads** "Your bet log is yours and kept private." (`1ab4e28`)

### Home Screen
- **The installed icon signs itself in, every launch.** (`cc1fd86`)

  An installed web app on iOS gets its own cookie jar, so the cookie set when the link was tapped in
  Safari often isn't there when the icon is opened — the guest met an access-code screen for a code they
  never had. The icon now launches from a URL carrying its own credential (`/?k=<token>` for a guest,
  `/?c=<key>` for the owner), and each launch re-asserts the cookie and re-checks the token against the
  live invite list. Revoking a link still locks someone out on the very next request; nothing is cached.

  The manifest is served per identity at `/m/k/<token>` and `/m/c/<key>`, with the token in the path — a
  manifest is fetched with credentials omitted, so one that read cookies would be served the gate page as
  HTML and the phone would install the defaults without a word. Icon srcs are made absolute there;
  relative ones resolve against the manifest's own URL, 404, and leave Android installing a shortcut
  rather than an app.

- **The gate is no longer a bare code box.** It leads with "Paste my link" — the way back in for a guest
  who has no code — and keeps the code form as a quiet secondary for the owner. (`cc1fd86`)
- **A turned-off link says so** instead of telling someone to tap the link they just tapped. (`66befc6`)

### Fixed
- **A one-request remote crash.** `sameHash` compared JS string length and then handed
  `crypto.timingSafeEqual` UTF-8 buffers, so any 32-character multi-byte value threw outside the request
  handler and killed the process. It compares byte length now. (`cc1fd86`)
- **The owner launch key is shape-checked and rate-limited** on the same counter as `/login`, so it is not
  a way around the lockout. (`cc1fd86`)

### Betting
- **Counter numbers per device** — numbers you type in yourself, standing at a window. (`049e747`)
- **Nevada book links**, and faster odds near kickoff. (`049e747`)

### Born
- **Pick Six** — live NFL lines, line movement and bet tracking. The NFL sibling of Hook & Ladder.
  (`43e5db4`)
