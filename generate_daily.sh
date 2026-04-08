#!/usr/bin/env bash
# generate_daily.sh — Trigger daily signal generation
# Usage: ./generate_daily.sh [TOKEN_PAIR]
# Examples:
#   ./generate_daily.sh              # all assets
#   ./generate_daily.sh BTC/USD      # BTC only
#   ./generate_daily.sh BTC/USD,ETH/USD  # BTC + ETH
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
ASSETS="${1:-}"

url="$BACKEND_URL/api/signals/generate"
[[ -n "$ASSETS" ]] && url="$url?assets=$ASSETS"

echo "[$(date)] Generating signals${ASSETS:+ for $ASSETS}..."

# Try API first (if backend is running)
if response=$(curl -sf -X POST "$url" 2>/dev/null); then
  echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
  exit 0
fi

# Fallback: run Python directly
echo "Backend unreachable, running directly..."
cd "$(dirname "$0")/backend"
source .venv/bin/activate 2>/dev/null || { echo "No venv found. Run start.sh first."; exit 1; }

if [[ -n "$ASSETS" ]]; then
  python3 -c "
from app.signal_engine import bootstrap_price_history, run_signal_cycle
bootstrap_price_history()
r = run_signal_cycle(assets='$ASSETS'.split(','))
import json; print(json.dumps(r, indent=2))
"
else
  python3 -c "
from app.signal_engine import bootstrap_price_history, run_signal_cycle
bootstrap_price_history()
r = run_signal_cycle()
import json; print(json.dumps(r, indent=2))
"
fi
