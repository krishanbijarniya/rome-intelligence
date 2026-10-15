#!/usr/bin/env bash
set -e

cd "$HOME/rome-intelligence"
source .venv/bin/activate

mkdir -p logs

echo "===== Daily run: $(date -Is) ====="

python collector.py
python classify_news.py

echo "===== Completed: $(date -Is) ====="
