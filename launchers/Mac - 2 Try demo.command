#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
[ -f .venv/bin/activate ] || { echo 'Run "Mac - 1 Setup.command" first.'; read -r -p "Press Return." _; exit 1; }
source .venv/bin/activate
echo "Made-up data only: nothing is read from or sent to Gmail or Zoho."
sales-pipeline ui --demo
