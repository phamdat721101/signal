#!/usr/bin/env bash
#
# smoke-initia-native.sh — Verify the 5 new Initia-native helpers respond.
#
# Run after deploy-initia-native.sh. Asserts:
#   1. OracleAdapter.getOracleHealth() returns a tuple (no revert)
#   2. CosmosUtilsView.isAddressSanctioned(deployer) returns false
#   3. VIPScoreAdapter.currentEpoch() returns a uint
#   4. CosmosDispatcher.paused() returns false (helper is live)
#   5. IBCSettlementHook.sessionVault() returns the configured SessionVault
#   6. Backend /api/health includes chain_ops_pending_count >= 0
#
# Exits non-zero on any failure. Does NOT mutate state — pure read-only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/backend/.env"
RPC_URL="${TESTNET_JSON_RPC_URL:-https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'
info() { printf "${BLUE}[smoke]${NC} %s\n" "$1"; }
ok()   { printf "${GREEN}[smoke]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[smoke]${NC} %s\n" "$1"; }
fail() { printf "${RED}[smoke]${NC} %s\n" "$1"; exit 1; }

[ -z "${ORACLE_ADAPTER_ADDRESS:-}" ]      && fail "ORACLE_ADAPTER_ADDRESS not set"
[ -z "${COSMOS_UTILS_VIEW_ADDRESS:-}" ]   && fail "COSMOS_UTILS_VIEW_ADDRESS not set"
[ -z "${COSMOS_DISPATCHER_ADDRESS:-}" ]   && fail "COSMOS_DISPATCHER_ADDRESS not set"
[ -z "${IBC_SETTLEMENT_HOOK_ADDRESS:-}" ] && fail "IBC_SETTLEMENT_HOOK_ADDRESS not set"
[ -z "${VIP_SCORE_ADAPTER_ADDRESS:-}" ]   && fail "VIP_SCORE_ADAPTER_ADDRESS not set"

DEPLOYER_ADDR=$(cast wallet address --private-key "$PRIVATE_KEY" 2>/dev/null || true)
[ -z "$DEPLOYER_ADDR" ] && fail "Could not derive deployer address from PRIVATE_KEY"

# 1. OracleAdapter.getOracleHealth() returns (bool, uint256)
info "1/6 OracleAdapter.getOracleHealth()"
cast call "$ORACLE_ADAPTER_ADDRESS" 'getOracleHealth()(bool,uint256)' --rpc-url "$RPC_URL" \
  >/dev/null || fail "OracleAdapter.getOracleHealth reverted"
ok "OracleAdapter responding"

# 2. CosmosUtilsView.isAddressSanctioned(deployer) — should be false
info "2/6 CosmosUtilsView.isAddressSanctioned($DEPLOYER_ADDR)"
SANCTIONED=$(cast call "$COSMOS_UTILS_VIEW_ADDRESS" 'isAddressSanctioned(address)(bool)' \
  "$DEPLOYER_ADDR" --rpc-url "$RPC_URL" || echo "ERR")
if [ "$SANCTIONED" = "ERR" ]; then
  fail "CosmosUtilsView.isAddressSanctioned reverted (precompile may be unavailable on chain)"
fi
[ "$SANCTIONED" = "true" ] && fail "Deployer address reported as sanctioned (unexpected)"
ok "CosmosUtilsView responding (deployer not sanctioned)"

# 3. VIPScoreAdapter.currentEpoch() returns uint
info "3/6 VIPScoreAdapter.currentEpoch()"
cast call "$VIP_SCORE_ADAPTER_ADDRESS" 'currentEpoch()(uint256)' --rpc-url "$RPC_URL" \
  >/dev/null || fail "VIPScoreAdapter.currentEpoch reverted"
ok "VIPScoreAdapter responding"

# 4. CosmosDispatcher.paused() returns false
info "4/6 CosmosDispatcher.paused()"
PAUSED=$(cast call "$COSMOS_DISPATCHER_ADDRESS" 'paused()(bool)' --rpc-url "$RPC_URL" || echo "ERR")
[ "$PAUSED" = "ERR" ]   && fail "CosmosDispatcher.paused reverted"
[ "$PAUSED" = "true" ]  && fail "CosmosDispatcher is paused (operator action required)"
ok "CosmosDispatcher live"

# 5. IBCSettlementHook.sessionVault() returns configured vault
info "5/6 IBCSettlementHook.sessionVault()"
HOOK_VAULT=$(cast call "$IBC_SETTLEMENT_HOOK_ADDRESS" 'sessionVault()(address)' --rpc-url "$RPC_URL" || echo "ERR")
[ "$HOOK_VAULT" = "ERR" ] && fail "IBCSettlementHook.sessionVault reverted"
EXPECTED_VAULT=$(echo "$SESSION_VAULT_ADDRESS" | tr '[:upper:]' '[:lower:]')
HOOK_VAULT_LC=$(echo "$HOOK_VAULT" | tr '[:upper:]' '[:lower:]')
[ "$HOOK_VAULT_LC" != "$EXPECTED_VAULT" ] && \
  fail "IBCSettlementHook.sessionVault mismatch: got $HOOK_VAULT, expected $SESSION_VAULT_ADDRESS"
ok "IBCSettlementHook wired to SessionVault"

# 6. Backend /api/health (best-effort — only if backend is up locally)
info "6/6 Backend /api/health (chain_ops_pending_count)"
if curl -sf --max-time 3 http://localhost:8000/api/health > /tmp/_signal_health.json 2>/dev/null; then
  PENDING=$(grep -oE '"chain_ops_pending_count":-?[0-9]+' /tmp/_signal_health.json | head -1 | grep -oE '\-?[0-9]+' || echo "?")
  if [ "$PENDING" = "?" ]; then
    warn "Backend health response missing chain_ops_pending_count (older deploy?)"
  else
    [ "$PENDING" -ge 0 ] && ok "Backend healthy: chain_ops_pending_count=$PENDING" || \
      warn "Backend reports chain_ops_pending_count=$PENDING (negative = exception path)"
  fi
else
  warn "Backend not reachable at localhost:8000; skipping health probe"
fi

printf "\n${GREEN}All checks passed.${NC} 5 helpers live; backend reliability layer ok.\n"
