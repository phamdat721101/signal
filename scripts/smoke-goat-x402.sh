#!/usr/bin/env bash
# Smoke test for Kinetic GOAT testnet x402 rail.
#
# Asserts:
#   • GET /goat-api/api/v2/agent/decisions returns HTTP 402.
#   • Response carries a 'payment-required' base64-JSON envelope.
#   • The envelope advertises eip155:48816 (goat-testnet3) and a non-zero
#     maxAmountRequired in the configured token (default WGBTC).
#
# Usage:
#   bash scripts/smoke-goat-x402.sh                       # local — http://127.0.0.1:8002
#   bash scripts/smoke-goat-x402.sh https://ai.overguild.com/agent-api
#
# Exit codes: 0 on success, non-zero on the first assertion failure.
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8002}"
ROUTE="/goat-api/api/v2/agent/decisions"
URL="${BASE_URL%/}${ROUTE}"

echo "→ GET ${URL}"
HEADERS_FILE=$(mktemp)
trap 'rm -f "$HEADERS_FILE"' EXIT
HTTP_CODE=$(curl -sS -o /dev/null -w '%{http_code}' -D "$HEADERS_FILE" "$URL")

if [ "$HTTP_CODE" != "402" ]; then
  echo "✗ expected 402, got $HTTP_CODE"
  echo "── headers ──"; cat "$HEADERS_FILE"
  exit 1
fi
echo "✓ HTTP 402"

ENV_B64=$(awk 'tolower($1) == "payment-required:" { sub(/\r$/, "", $2); print $2; exit }' "$HEADERS_FILE")
if [ -z "$ENV_B64" ]; then
  echo "✗ missing payment-required header"
  cat "$HEADERS_FILE"
  exit 2
fi

DECODED=$(python3 -c "import base64,json,sys;print(json.dumps(json.loads(base64.b64decode(sys.argv[1]))))" "$ENV_B64")
echo "✓ payment-required envelope decoded"
echo "  $DECODED"

NETWORK=$(echo "$DECODED" | python3 -c "import json,sys;print(json.load(sys.stdin)['accepts'][0]['network'])")
AMT=$(echo "$DECODED"     | python3 -c "import json,sys;print(json.load(sys.stdin)['accepts'][0]['maxAmountRequired'])")
ASSET=$(echo "$DECODED"   | python3 -c "import json,sys;print(json.load(sys.stdin)['accepts'][0]['asset'])")

[ "$NETWORK" = "eip155:48816" ] || { echo "✗ wrong network: $NETWORK"; exit 3; }
[ "$AMT" -gt 0 ] 2>/dev/null   || { echo "✗ maxAmountRequired must be > 0 (got: $AMT)"; exit 4; }
[ -n "$ASSET" ]                || { echo "✗ asset missing"; exit 5; }

echo "✓ network=$NETWORK asset=$ASSET maxAmountRequired=$AMT"
echo "OK"
