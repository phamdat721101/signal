#!/usr/bin/env bash
set -euo pipefail

CHAIN_ID="initia-signal-1"
KEY_NAME="gas-station"
KEYRING="test"
CONTRACTS_DIR="$(cd "$(dirname "$0")/contracts" && pwd)"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$ROOT_DIR/deploy.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'
info()  { printf "${BLUE}[deploy]${NC} %s\n" "$1"; echo "[$(date +%H:%M:%S)] INFO: $1" >> "$LOG_FILE"; }
ok()    { printf "${GREEN}[deploy]${NC} %s\n" "$1"; echo "[$(date +%H:%M:%S)] OK: $1" >> "$LOG_FILE"; }
warn()  { printf "${YELLOW}[deploy]${NC} %s\n" "$1"; echo "[$(date +%H:%M:%S)] WARN: $1" >> "$LOG_FILE"; }
err()   { printf "${RED}[deploy]${NC} %s\n" "$1"; echo "[$(date +%H:%M:%S)] ERROR: $1" >> "$LOG_FILE"; exit 1; }

echo "=== Deploy started at $(date) ===" > "$LOG_FILE"

deploy_contract() {
  local NAME=$1 BIN_FILE=$2

  if [ ! -f "$BIN_FILE" ]; then
    err "$NAME: bin file not found at $BIN_FILE"
  fi

  local BIN_SIZE=$(wc -c < "$BIN_FILE" | tr -d ' ')
  if [ "$BIN_SIZE" -lt 100 ]; then
    err "$NAME: bin file too small ($BIN_SIZE bytes) — build likely failed"
  fi
  info "$NAME: bytecode size = $BIN_SIZE bytes"

  info "Deploying $NAME..."
  local TX_OUT
  TX_OUT=$(minitiad tx evm create "$BIN_FILE" \
    --from "$KEY_NAME" --keyring-backend "$KEYRING" --chain-id "$CHAIN_ID" \
    --gas auto --gas-adjustment 1.4 --output json --yes 2>&1) || {
    echo "$TX_OUT" >> "$LOG_FILE"
    err "$NAME: minitiad tx failed. See deploy.log"
  }
  echo "$TX_OUT" >> "$LOG_FILE"

  local TX_HASH=$(echo "$TX_OUT" | jq -r '.txhash // empty' 2>/dev/null)
  if [ -z "$TX_HASH" ]; then
    err "$NAME: no txhash in response. Output: $(echo "$TX_OUT" | head -c 200)"
  fi
  info "$NAME TX: $TX_HASH"

  sleep 6

  local TX_RESULT
  TX_RESULT=$(minitiad q tx "$TX_HASH" --output json 2>/dev/null) || {
    err "$NAME: failed to query tx $TX_HASH"
  }
  echo "$TX_RESULT" | head -c 500 >> "$LOG_FILE"

  local ADDR=$(echo "$TX_RESULT" | jq -r '.events[] | select(.type=="contract_created") | .attributes[] | select(.key=="contract") | .value' 2>/dev/null)
  if [ -z "$ADDR" ]; then
    warn "$NAME: no contract_created event. Checking logs..."
    local CODE=$(echo "$TX_RESULT" | jq -r '.code // 0' 2>/dev/null)
    local RAW_LOG=$(echo "$TX_RESULT" | jq -r '.raw_log // "none"' 2>/dev/null | head -c 300)
    err "$NAME: deploy tx failed. code=$CODE raw_log=$RAW_LOG"
  fi

  ok "$NAME deployed at: $ADDR"
  rm -f "$BIN_FILE"
  echo "$ADDR"
}

extract_bytecode() {
  local NAME=$1 JSON_PATH=$2 BIN_PATH=$3

  if [ ! -f "$JSON_PATH" ]; then
    err "$NAME: compiled JSON not found at $JSON_PATH. Did forge build succeed?"
  fi

  # Validate JSON
  if ! jq empty "$JSON_PATH" 2>/dev/null; then
    err "$NAME: invalid JSON at $JSON_PATH"
  fi

  local BYTECODE=$(jq -r '.bytecode.object // empty' "$JSON_PATH" 2>/dev/null)
  if [ -z "$BYTECODE" ] || [ "$BYTECODE" = "null" ]; then
    err "$NAME: no bytecode in $JSON_PATH. Contract may have compile errors."
  fi

  echo "$BYTECODE" | sed 's/^0x//' | tr -d '\n' > "$BIN_PATH"
  ok "$NAME: bytecode extracted ($(wc -c < "$BIN_PATH" | tr -d ' ') bytes)"
}

# --- Preflight ---
info "Checking prerequisites..."
for cmd in forge jq minitiad cast; do
  if ! command -v "$cmd" &>/dev/null; then
    err "Required command '$cmd' not found in PATH"
  fi
done
ok "All tools found"

if ! minitiad keys show "$KEY_NAME" --keyring-backend "$KEYRING" &>/dev/null; then
  err "Key '$KEY_NAME' not found in keyring '$KEYRING'. Import it first (see README)."
fi
SENDER=$(minitiad keys show "$KEY_NAME" -a --keyring-backend "$KEYRING")
ok "Deployer: $SENDER"

# --- Build ---
info "Building contracts with forge..."
cd "$CONTRACTS_DIR"
BUILD_OUTPUT=$(forge build --via-ir 2>&1) || {
  echo "$BUILD_OUTPUT" >> "$LOG_FILE"
  err "forge build failed. See deploy.log. Last lines: $(echo "$BUILD_OUTPUT" | tail -5)"
}
echo "$BUILD_OUTPUT" >> "$LOG_FILE"
ok "Contracts compiled"

# --- 1. Deploy SignalRegistry ---
extract_bytecode "SignalRegistry" "out/SignalRegistry.sol/SignalRegistry.json" "SignalRegistry.bin"
CONTRACT_ADDR=$(deploy_contract "SignalRegistry" "SignalRegistry.bin")

# --- 2. Deploy MockIUSD ---
extract_bytecode "MockIUSD" "out/MockIUSD.sol/MockIUSD.json" "MockIUSD.bin"
IUSD_ADDR=$(deploy_contract "MockIUSD" "MockIUSD.bin")

# --- 3. Deploy SessionVault ---
extract_bytecode "SessionVault" "out/SessionVault.sol/SessionVault.json" "SessionVault.bin"
info "Encoding SessionVault constructor args (iUSD=$IUSD_ADDR, treasury=$SENDER)..."
CONSTRUCTOR_ARGS=$(cast abi-encode "constructor(address,address)" "$IUSD_ADDR" "$SENDER" 2>&1) || {
  err "cast abi-encode failed: $CONSTRUCTOR_ARGS"
}
echo -n "$(echo "$CONSTRUCTOR_ARGS" | sed 's/^0x//')" >> SessionVault.bin
VAULT_ADDR=$(deploy_contract "SessionVault" "SessionVault.bin")

# --- 4. Deploy SignalPaymentGateway ---
extract_bytecode "SignalPaymentGateway" "out/SignalPaymentGateway.sol/SignalPaymentGateway.json" "SignalPaymentGateway.bin"
GW_ADDR=$(deploy_contract "SignalPaymentGateway" "SignalPaymentGateway.bin")

# --- 5. Authorize backend as vault operator ---
info "Authorizing backend as SessionVault operator..."
AUTH_CALLDATA=$(cast calldata "setAuthorizedOperator(address,bool)" "$SENDER" true)
AUTH_OUT=$(minitiad tx evm call "$VAULT_ADDR" "$AUTH_CALLDATA" \
  --from "$KEY_NAME" --keyring-backend "$KEYRING" --chain-id "$CHAIN_ID" \
  --gas auto --gas-adjustment 1.4 --output json --yes 2>&1) || {
  echo "$AUTH_OUT" >> "$LOG_FILE"
  warn "Operator authorization may have failed. See deploy.log"
}
ok "Backend authorized as operator"

# --- Wire .env files ---
info "Updating .env files..."

PRIV_KEY=""
[ -f "$HOME/.weave/config.json" ] && PRIV_KEY=$(jq -r '.common.gas_station.private_key // empty' "$HOME/.weave/config.json" 2>/dev/null)

update_env() {
  local FILE=$1 KEY=$2 VAL=$3
  [ -f "$FILE" ] || return
  if grep -q "^${KEY}=" "$FILE"; then
    if [[ "$OSTYPE" == "darwin"* ]]; then sed -i '' "s|^${KEY}=.*|${KEY}=${VAL}|" "$FILE"
    else sed -i "s|^${KEY}=.*|${KEY}=${VAL}|" "$FILE"; fi
  else
    echo "${KEY}=${VAL}" >> "$FILE"
  fi
}

update_env "$ROOT_DIR/backend/.env" "CONTRACT_ADDRESS" "$CONTRACT_ADDR"
update_env "$ROOT_DIR/backend/.env" "MOCK_IUSD_ADDRESS" "$IUSD_ADDR"
update_env "$ROOT_DIR/backend/.env" "SESSION_VAULT_ADDRESS" "$VAULT_ADDR"
update_env "$ROOT_DIR/backend/.env" "PAYMENT_GATEWAY_ADDRESS" "$GW_ADDR"
update_env "$ROOT_DIR/backend/.env" "ENABLE_PAYMENT_GATING" "true"
[ -n "$PRIV_KEY" ] && update_env "$ROOT_DIR/backend/.env" "PRIVATE_KEY" "$PRIV_KEY"
ok "Updated backend/.env"

update_env "$ROOT_DIR/frontend/.env" "VITE_CONTRACT_ADDRESS" "$CONTRACT_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_CHAIN_ID" "$CHAIN_ID"
update_env "$ROOT_DIR/frontend/.env" "VITE_MOCK_IUSD_ADDRESS" "$IUSD_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_SESSION_VAULT_ADDRESS" "$VAULT_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_PAYMENT_GATEWAY_ADDRESS" "$GW_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_PAYMENT_ENABLED" "true"
ok "Updated frontend/.env"

[ -f "$ROOT_DIR/.initia/submission.json" ] && {
  TMP=$(mktemp)
  jq --arg addr "$CONTRACT_ADDR" '.deployed_address = $addr' "$ROOT_DIR/.initia/submission.json" > "$TMP"
  mv "$TMP" "$ROOT_DIR/.initia/submission.json"
  ok "Updated .initia/submission.json"
}

printf "\n${GREEN}========================================${NC}\n"
printf "${GREEN}  Deployment Complete${NC}\n"
printf "${GREEN}========================================${NC}\n"
printf "  SignalRegistry:        %s\n" "$CONTRACT_ADDR"
printf "  MockIUSD:              %s\n" "$IUSD_ADDR"
printf "  SessionVault:          %s\n" "$VAULT_ADDR"
printf "  SignalPaymentGateway:  %s\n" "$GW_ADDR"
printf "  Chain:                 %s\n" "$CHAIN_ID"
printf "  Deployer:              %s\n" "$SENDER"
printf "  Log:                   %s\n" "$LOG_FILE"
printf "${GREEN}========================================${NC}\n"
