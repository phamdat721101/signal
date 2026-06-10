#!/usr/bin/env bash
#
# deploy-somnia-prophecy.sh — Deploy KineticProphecyBridge ONLY.
#
# Pure-additive: leaves every existing contract on Somnia testnet 50312
# untouched. Reads CONVICTION_ENGINE_ADDRESS from the existing Somnia
# deployment record so we never touch ConvictionEngine itself — the
# script just authorizes the bridge as a resolver.
#
# After deploy: writes the bridge address to backend/.env (PROPHECY_BRIDGE_ADDRESS)
# and frontend/.env (VITE_SOMNIA_PROPHECY_BRIDGE_ADDRESS). Idempotent — a
# re-run replaces the bridge address (a fresh deploy is the same cost as
# the first one on Somnia testnet).
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTRACTS_DIR="$ROOT_DIR/contracts"

# shellcheck source=/dev/null
source "$ROOT_DIR/backend/.env"

RPC_URL="${SOMNIA_TESTNET_RPC:-https://api.infra.testnet.somnia.network}"
CONVICTION_ENGINE_ADDR="${SOMNIA_CONVICTION_ENGINE_ADDRESS:-}"
BACKEND_HOT_WALLET="${SOMNIA_BACKEND_HOT_WALLET:-}"   # optional grant

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { printf "${BLUE}[prophecy-deploy]${NC} %s\n" "$1" >&2; }
ok()    { printf "${GREEN}[prophecy-deploy]${NC} %s\n" "$1" >&2; }
err()   { printf "${RED}[prophecy-deploy]${NC} %s\n" "$1" >&2; exit 1; }

[ -z "${PRIVATE_KEY:-}" ] && err "PRIVATE_KEY not set in backend/.env"
[ -z "$CONVICTION_ENGINE_ADDR" ] && \
  err "SOMNIA_CONVICTION_ENGINE_ADDRESS not set — deploy 05_DeploySomnia first"

info "RPC:                $RPC_URL"
info "ConvictionEngine:   $CONVICTION_ENGINE_ADDR"
[ -n "$BACKEND_HOT_WALLET" ] && info "Backend hot wallet: $BACKEND_HOT_WALLET (will be granted bind+relay)"

cd "$CONTRACTS_DIR"
info "Building contracts (--via-ir)..."
forge build --via-ir > /tmp/forge-build-prophecy.log 2>&1 \
  || { tail -30 /tmp/forge-build-prophecy.log; err "forge build failed"; }

info "Broadcasting 06_DeployProphecyBridge..."
CONVICTION_ENGINE_ADDRESS="$CONVICTION_ENGINE_ADDR" \
  ${BACKEND_HOT_WALLET:+BACKEND_HOT_WALLET="$BACKEND_HOT_WALLET"} \
  forge script script/06_DeployProphecyBridge.s.sol \
    --rpc-url "$RPC_URL" \
    --broadcast \
    --via-ir \
  | tee /tmp/forge-deploy-prophecy.log

BRIDGE_ADDR="$(grep -oE 'KineticProphecyBridge: 0x[0-9a-fA-F]{40}' /tmp/forge-deploy-prophecy.log | tail -1 | awk '{print $2}')"
[ -z "$BRIDGE_ADDR" ] && err "Could not parse bridge address from forge output"
ok "Bridge deployed at $BRIDGE_ADDR"

# Stamp the addresses into both .env files. We use line-level upsert so a
# missing key gets appended and an existing key gets replaced in place.
upsert_env() {
  local file="$1" key="$2" value="$3"
  [ -f "$file" ] || { touch "$file"; }
  if grep -qE "^${key}=" "$file"; then
    # macOS-portable inline sed
    sed -i.bak -E "s|^${key}=.*$|${key}=${value}|" "$file" && rm -f "${file}.bak"
  else
    printf "%s=%s\n" "$key" "$value" >> "$file"
  fi
}

upsert_env "$ROOT_DIR/backend/.env"   "PROPHECY_BRIDGE_ADDRESS"             "$BRIDGE_ADDR"
upsert_env "$ROOT_DIR/backend/.env"   "PROPHECY_CARD_GEN_ENABLED"           "true"
upsert_env "$ROOT_DIR/frontend/.env"  "VITE_SOMNIA_PROPHECY_BRIDGE_ADDRESS" "$BRIDGE_ADDR"

ok "backend/.env  ← PROPHECY_BRIDGE_ADDRESS=$BRIDGE_ADDR"
ok "backend/.env  ← PROPHECY_CARD_GEN_ENABLED=true"
ok "frontend/.env ← VITE_SOMNIA_PROPHECY_BRIDGE_ADDRESS=$BRIDGE_ADDR"

# Persist alongside the existing Somnia deployment record for ops visibility.
DEPLOY_FILE="$CONTRACTS_DIR/deployments/50312.json"
if [ -f "$DEPLOY_FILE" ]; then
  python3 - "$DEPLOY_FILE" "$BRIDGE_ADDR" <<'PY'
import json, sys
path, addr = sys.argv[1], sys.argv[2]
data = json.load(open(path))
data["KineticProphecyBridge"] = addr
json.dump(data, open(path, "w"), indent=2)
PY
  ok "deployments/50312.json updated"
fi

echo
ok "Done. Restart backend to pick up the new env: bash restart_signal.sh"
