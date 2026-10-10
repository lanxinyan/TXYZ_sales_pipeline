#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
echo "Setting up Sales Desk (one time, about a minute)..."
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo
  echo "Python 3.10 or newer was not found."
  echo "Install it from https://www.python.org/downloads/ and double-click this file again."
  read -r -p "Press Return to close." _
  exit 1
fi
python3 -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip >/dev/null \
  && pip install -e . || { read -r -p "Install failed - see the messages above. Press Return to close." _; exit 1; }
[ -f .env ] || cp .env.example .env
echo
sales-pipeline check
echo
echo 'Done. Next: "Mac - 2 Try demo.command" to look around with made-up data.'
read -r -p "Press Return to close." _
