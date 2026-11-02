#!/bin/sh
# Build paper.pdf from paper.md: pandoc (md -> standalone HTML, MathML) then headless Chromium print-to-PDF.
set -e
cd "$(dirname "$0")"
(cd ../.. && python3 report/paper/scripts/fig_ablation.py)
pandoc paper.md -s --mathml --number-sections --css style.css --embed-resources --metadata pagetitle="reefcensus paper" -o paper.html
CHROME=${CHROME:-$HOME/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell}
"$CHROME" --no-sandbox --headless --disable-gpu --no-pdf-header-footer --print-to-pdf=paper.pdf "file://$PWD/paper.html" 2>/dev/null
ls -l paper.pdf
