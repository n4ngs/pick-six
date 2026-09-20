#!/bin/bash
# Renders public/icons/icon.svg into the PNG sizes phones want (needs Google Chrome).
# Usage: tools/icons.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SVG="$ROOT/public/icons/icon.svg"
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROF="$(mktemp -d)"
for size in 180 192 512; do
  name=$([ $size = 180 ] && echo apple-touch-icon || echo icon-$size)
  html="$PROF/i$size.html"
  printf '<!doctype html><html><body style="margin:0;background:transparent"><img src="file://%s" style="width:%spx;height:%spx;display:block"></body></html>' "$SVG" $size $size > "$html"
  ( "$CH" --headless=new --disable-gpu --hide-scrollbars --default-background-color=00000000 --user-data-dir="$PROF/p$size" --window-size=$size,$size --timeout=4000 --screenshot="$ROOT/public/icons/$name.png" "file://$html" >/dev/null 2>&1 & )
done
sleep 9
pkill -f "$PROF" 2>/dev/null || true
rm -rf "$PROF" 2>/dev/null || true
ls -la "$ROOT/public/icons"
