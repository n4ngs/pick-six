#!/bin/bash
# Double-click to launch Pick Six, then it opens in your browser.
cd "$(dirname "$0")"
if ! command -v node >/dev/null 2>&1; then
  echo "Pick Six needs Node.js 18 or newer: https://nodejs.org"
  read -r -p "Press Return to close."
  exit 1
fi
PORT="${PORT:-4849}"
( sleep 3; open "http://localhost:$PORT" ) &
PORT="$PORT" node server.js
