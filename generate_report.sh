#!/usr/bin/env bash
# generate_report.sh — Generate signal performance report
# Output: backend/reports/report.json + stdout
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

echo "[$(date)] Generating performance report..."

# Try API first
if response=$(curl -sf "$BACKEND_URL/api/report" 2>/dev/null); then
  echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
  exit 0
fi

# Fallback: run Python directly
echo "Backend unreachable, running directly..."
cd "$(dirname "$0")/backend"
source .venv/bin/activate 2>/dev/null || { echo "No venv found. Run start.sh first."; exit 1; }
python3 -m app.report
