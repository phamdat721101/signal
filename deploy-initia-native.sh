#!/usr/bin/env bash
#
# deploy-initia-native.sh — Deploy ONLY the 5 new Initia-native helpers.
#
# Pure-additive: does NOT redeploy the 7 live contracts (SignalRegistry,
# ConvictionEngine, SessionVault, RewardEngine, ProofOfAlpha, MockIUSD,
# SignalPaymentGateway). Live data and 5,816+ resolved predictions stay intact.
#
# Deploys:
#   - OracleAdapter        (ConnectOracle proofs at resolution time)
#   - CosmosUtilsView      (read-only ICosmos precompile wrapper)
#   - CosmosDispatcher     (owner-gated execute_cosmos writes)
#   - IBCSettlementHook    (entry for EVM IBC Hooks ICS-20 packets)
#   - VIPScoreAdapter      (mirrors ConvictionEngine reputation)
#
# After deploy: writes addresses to backend/.env + frontend/.env and runs
# the smoke test. Idempotent — re-running redeploys (forge create writes new
# addresses each time; .env is updated; smoke verifies fresh state).
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTRACTS_DIR="$ROOT_DIR/contracts"

# shellcheck source=/dev/null
source "$ROOT_DIR/backend/.env"
RPC_URL="${TESTNET_JSON_RPC_URL:-https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz}"
GAS_PRICE="${EVM_GAS_PRICE_WEI:-100000000}"   # 0.1 gwei — evm-1 floor

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'
# All info/ok/warn/err write to stderr so command-substitution callers
# (e.g. ORACLE_ADAPTER=$(deploy_one ...)) don't capture status messages.
info()  { printf "${BLUE}[deploy]${NC} %s\n" "$1" >&2; }
ok()    { printf "${GREEN}[deploy]${NC} %s\n" "$1" >&2; }
warn()  { printf "${YELLOW}[deploy]${NC} %s\n" "$1" >&2; }
err()   { printf "${RED}[deploy]${NC} %s\n" "$1" >&2; exit 1; }

[ -z "${PRIVATE_KEY:-}" ] && err "PRIVATE_KEY not set in backend/.env"
[ -z "${CONTRACT_ADDRESS:-}" ] && err "CONTRACT_ADDRESS (SignalRegistry) not set"
[ -z "${CONVICTION_ENGINE_ADDRESS:-}" ] && err "CONVICTION_ENGINE_ADDRESS not set"
[ -z "${SESSION_VAULT_ADDRESS:-}" ] && err "SESSION_VAULT_ADDRESS not set"

CONNECT_ORACLE_ADDR="${CONNECT_ORACLE_ADDRESS:-}"
if [ -z "$CONNECT_ORACLE_ADDR" ]; then
  warn "CONNECT_ORACLE_ADDRESS not set — OracleAdapter will deploy with a placeholder"
  warn "and oracle reads will return empty until the address is set + setSupportedPair() called."
  CONNECT_ORACLE_ADDR="0x0000000000000000000000000000000000000000"
fi

info "RPC: $RPC_URL"
info "Gas price: $GAS_PRICE wei (0.1 gwei)"

cd "$CONTRACTS_DIR"
info "Building contracts (--via-ir)..."
forge build --via-ir > /tmp/forge-build.log 2>&1 \
  || { tail -30 /tmp/forge-build.log; err "forge build failed"; }
ok "build OK ($(wc -l < /tmp/forge-build.log | tr -d ' ') lines logged to /tmp/forge-build.log)"

# ── helpers ──
# Deploy one contract. Args: SRC_FILE CONTRACT_NAME [CTOR_ARGS...]
# Prints ONLY the deployed address to stdout — info/errors go to stderr.
deploy_one() {
  local SRC_FILE=$1 NAME=$2; shift 2
  info "Deploying $NAME (from $SRC_FILE)..."
  local OUTPUT
  if [ "$#" -gt 0 ]; then
    OUTPUT=$(forge create "${SRC_FILE}:${NAME}" \
      --rpc-url "$RPC_URL" \
      --private-key "$PRIVATE_KEY" \
      --gas-price "$GAS_PRICE" \
      --broadcast \
      --via-ir \
      --constructor-args "$@" 2>&1) || { echo "$OUTPUT" >&2; err "$NAME deploy failed"; }
  else
    OUTPUT=$(forge create "${SRC_FILE}:${NAME}" \
      --rpc-url "$RPC_URL" \
      --private-key "$PRIVATE_KEY" \
      --gas-price "$GAS_PRICE" \
      --broadcast \
      --via-ir 2>&1) || { echo "$OUTPUT" >&2; err "$NAME deploy failed"; }
  fi
  # Only the deployed address goes to stdout (caller captures this).
  local ADDR
  ADDR=$(echo "$OUTPUT" | grep -E "Deployed to:" | awk '{print $NF}')
  if [ -z "$ADDR" ]; then
    echo "$OUTPUT" >&2
    err "$NAME: could not parse 'Deployed to:' from forge output"
  fi
  echo "$ADDR"
}

update_env() {
  local FILE=$1 KEY=$2 VAL=$3
  [ -f "$FILE" ] || return
  if grep -q "^${KEY}=" "$FILE"; then
    if [[ "$OSTYPE" == "darwin"* ]]; then sed -i '' "s|^${KEY}=.*|${KEY}=${VAL}|" "$FILE"
    else sed -i "s|^${KEY}=.*|${KEY}=${VAL}|" "$FILE"; fi
  else
    # Ensure file ends with newline before appending — prevents key concatenation.
    [ -n "$(tail -c1 "$FILE")" ] && printf "\n" >> "$FILE"
    echo "${KEY}=${VAL}" >> "$FILE"
  fi
}

# ── deploy ──
ORACLE_ADAPTER=$(deploy_one "src/OracleAdapter.sol"     "OracleAdapter"     "$CONNECT_ORACLE_ADDR")
[ -z "$ORACLE_ADAPTER" ] && err "OracleAdapter deploy parsed empty address"
ok "OracleAdapter:        $ORACLE_ADAPTER"

# CosmosUtilsView is the deployable wrapper from CosmosUtils.sol
COSMOS_UTILS=$(deploy_one "src/CosmosUtils.sol"         "CosmosUtilsView")
[ -z "$COSMOS_UTILS" ] && err "CosmosUtilsView deploy parsed empty address"
ok "CosmosUtilsView:      $COSMOS_UTILS"

COSMOS_DISPATCHER=$(deploy_one "src/CosmosDispatcher.sol"  "CosmosDispatcher")
[ -z "$COSMOS_DISPATCHER" ] && err "CosmosDispatcher deploy parsed empty address"
ok "CosmosDispatcher:     $COSMOS_DISPATCHER"

IBC_HOOK=$(deploy_one "src/IBCSettlementHook.sol"      "IBCSettlementHook"  "$SESSION_VAULT_ADDRESS")
[ -z "$IBC_HOOK" ] && err "IBCSettlementHook deploy parsed empty address"
ok "IBCSettlementHook:    $IBC_HOOK"

VIP_SCORE=$(deploy_one "src/VIPScoreAdapter.sol"       "VIPScoreAdapter"    "$CONVICTION_ENGINE_ADDRESS")
[ -z "$VIP_SCORE" ] && err "VIPScoreAdapter deploy parsed empty address"
ok "VIPScoreAdapter:      $VIP_SCORE"

# ── env updates ──
info "Updating backend/.env + frontend/.env..."
update_env "$ROOT_DIR/backend/.env" "ORACLE_ADAPTER_ADDRESS"      "$ORACLE_ADAPTER"
update_env "$ROOT_DIR/backend/.env" "COSMOS_UTILS_VIEW_ADDRESS"   "$COSMOS_UTILS"
update_env "$ROOT_DIR/backend/.env" "COSMOS_DISPATCHER_ADDRESS"   "$COSMOS_DISPATCHER"
update_env "$ROOT_DIR/backend/.env" "IBC_SETTLEMENT_HOOK_ADDRESS" "$IBC_HOOK"
update_env "$ROOT_DIR/backend/.env" "VIP_SCORE_ADAPTER_ADDRESS"   "$VIP_SCORE"
update_env "$ROOT_DIR/backend/.env" "CONNECT_ORACLE_ADDRESS"      "$CONNECT_ORACLE_ADDR"

update_env "$ROOT_DIR/frontend/.env" "VITE_ORACLE_ADAPTER_ADDRESS"      "$ORACLE_ADAPTER"
update_env "$ROOT_DIR/frontend/.env" "VITE_COSMOS_UTILS_VIEW_ADDRESS"   "$COSMOS_UTILS"
update_env "$ROOT_DIR/frontend/.env" "VITE_COSMOS_DISPATCHER_ADDRESS"   "$COSMOS_DISPATCHER"
update_env "$ROOT_DIR/frontend/.env" "VITE_IBC_SETTLEMENT_HOOK_ADDRESS" "$IBC_HOOK"
update_env "$ROOT_DIR/frontend/.env" "VITE_VIP_SCORE_ADAPTER_ADDRESS"   "$VIP_SCORE"

ok "Env files updated."

# ── post-deploy authorizations ──
info "Authorizing CosmosDispatcher caller (deployer) and VIPScoreAdapter scorer..."
DEPLOYER_ADDR=$(cast wallet address --private-key "$PRIVATE_KEY" 2>/dev/null || true)
if [ -n "$DEPLOYER_ADDR" ]; then
  cast send "$COSMOS_DISPATCHER" \
    'setAuthorizedCaller(address,bool)' "$DEPLOYER_ADDR" true \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" \
    --gas-price "$GAS_PRICE" --gas-limit 250000 >/dev/null 2>&1 \
    && ok "CosmosDispatcher.setAuthorizedCaller($DEPLOYER_ADDR, true)" \
    || warn "CosmosDispatcher.setAuthorizedCaller failed (non-fatal)"

  cast send "$VIP_SCORE" \
    'setAuthorizedScorer(address,bool)' "$DEPLOYER_ADDR" true \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" \
    --gas-price "$GAS_PRICE" --gas-limit 250000 >/dev/null 2>&1 \
    && ok "VIPScoreAdapter.setAuthorizedScorer($DEPLOYER_ADDR, true)" \
    || warn "VIPScoreAdapter.setAuthorizedScorer failed (non-fatal)"

  cast send "$ORACLE_ADAPTER" \
    'setAuthorizedResolver(address,bool)' "$DEPLOYER_ADDR" true \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" \
    --gas-price "$GAS_PRICE" --gas-limit 250000 >/dev/null 2>&1 \
    && ok "OracleAdapter.setAuthorizedResolver($DEPLOYER_ADDR, true)" \
    || warn "OracleAdapter.setAuthorizedResolver failed (non-fatal)"

  cast send "$IBC_HOOK" \
    'setAuthorizedHookCaller(address,bool)' "$DEPLOYER_ADDR" true \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" \
    --gas-price "$GAS_PRICE" --gas-limit 250000 >/dev/null 2>&1 \
    && ok "IBCSettlementHook.setAuthorizedHookCaller($DEPLOYER_ADDR, true)" \
    || warn "IBCSettlementHook.setAuthorizedHookCaller failed (non-fatal)"
else
  warn "Could not derive deployer address; skipping authorization step."
fi

# ── summary ──
printf "\n${GREEN}═════════════════════════════════════════════════${NC}\n"
printf "${GREEN}  Initia-Native Helpers — Deployment Complete${NC}\n"
printf "${GREEN}═════════════════════════════════════════════════${NC}\n"
printf "  OracleAdapter        %s\n" "$ORACLE_ADAPTER"
printf "  CosmosUtilsView      %s\n" "$COSMOS_UTILS"
printf "  CosmosDispatcher     %s\n" "$COSMOS_DISPATCHER"
printf "  IBCSettlementHook    %s\n" "$IBC_HOOK"
printf "  VIPScoreAdapter      %s\n" "$VIP_SCORE"
printf "${GREEN}═════════════════════════════════════════════════${NC}\n"

# ── smoke test ──
if [ -x "$ROOT_DIR/smoke-initia-native.sh" ]; then
  info "Running smoke test..."
  "$ROOT_DIR/smoke-initia-native.sh" || err "Smoke test failed"
  ok "Smoke test passed."
else
  warn "smoke-initia-native.sh not found or not executable; skipping smoke."
fi

printf "\n${GREEN}Done.${NC} Restart backend to pick up new addresses:\n"
printf "  bash %s/restart_signal.sh\n" "$ROOT_DIR"
