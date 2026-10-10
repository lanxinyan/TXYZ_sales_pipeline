#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
[ -f .venv/bin/activate ] || { echo 'Run "Mac - 1 Setup.command" first.'; read -r -p "Press Return." _; exit 1; }
source .venv/bin/activate
sales-pipeline zoho-auth && sales-pipeline zoho-setup --write
read -r -p "Press Return to close." _
