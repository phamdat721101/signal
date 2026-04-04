#!/usr/bin/env bash
#
# deploy.sh — Build and deploy SignalRegistry to the local Initia EVM appchain
#
set -euo pipefail

CHAIN_ID="initia-signal-1"
KEY_NAME="gas-station"
KEYRING="test"
CONTRACTS_DIR="$(cd "$(dirname "$0")/contracts" && pwd)"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { printf "${BLUE}[deploy]${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}[deploy]${NC} %s\n" "$1"; }
err()   { printf "${RED}[deploy]${NC} %s\n" "$1"; exit 1; }

# --- Preflight ---
for cmd in forge jq minitiad cast; do
  command -v "$cmd" &>/dev/null || err "$cmd not found in PATH"
done

minitiad keys show "$KEY_NAME" --keyring-backend "$KEYRING" &>/dev/null \
  || err "Key '$KEY_NAME' not found. Import it first (see README)."

info "Building contract..."
cd "$CONTRACTS_DIR"
forge build --via-ir --silent

info "Extracting bytecode..."
jq -r '.bytecode.object' out/SignalRegistry.sol/SignalRegistry.json \
  | sed 's/^0x//' | tr -d '\n' > SignalRegistry.bin

info "Deploying to $CHAIN_ID..."
TX_OUTPUT=$(minitiad tx evm create SignalRegistry.bin \
  --from "$KEY_NAME" \
  --keyring-backend "$KEYRING" \
  --chain-id "$CHAIN_ID" \
  --gas auto --gas-adjustment 1.4 \
  --output json \
  --yes 2>&1)

TX_HASH=$(echo "$TX_OUTPUT" | jq -r '.txhash // empty')
if [ -z "$TX_HASH" ]; then
  err "Failed to broadcast tx. Output:\n$TX_OUTPUT"
fi
info "TX broadcast: $TX_HASH"

info "Waiting for indexing..."
sleep 6

CONTRACT_ADDR=$(minitiad q tx "$TX_HASH" --output json 2>/dev/null \
  | jq -r '.events[] | select(.type=="contract_created") | .attributes[] | select(.key=="contract") | .value')

if [ -z "$CONTRACT_ADDR" ]; then
  err "Could not find contract address in tx events. Check: minitiad q tx $TX_HASH"
fi

ok "Contract deployed at: $CONTRACT_ADDR"

# --- Cleanup bytecode ---
rm -f SignalRegistry.bin

# --- Verify ---
info "Verifying deployment..."
SENDER=$(minitiad keys show "$KEY_NAME" -a --keyring-backend "$KEYRING")
CALLDATA=$(cast calldata "getSignalCount()")
RESULT=$(minitiad query evm call "$SENDER" "$CONTRACT_ADDR" "$CALLDATA" -o json 2>/dev/null | jq -r '.response // empty')
if [ -n "$RESULT" ]; then
  ok "getSignalCount() returned: $RESULT (expected 0x...0)"
else
  info "Could not verify via CLI query, but contract was created successfully."
fi

# --- Wire .env files ---
info "Updating .env files..."

# Get private key from weave config
PRIV_KEY=""
if [ -f "$HOME/.weave/config.json" ]; then
  PRIV_KEY=$(jq -r '.common.gas_station.private_key // empty' "$HOME/.weave/config.json")
fi

# Backend .env
if [ -f "$ROOT_DIR/backend/.env" ]; then
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|^CONTRACT_ADDRESS=.*|CONTRACT_ADDRESS=$CONTRACT_ADDR|" "$ROOT_DIR/backend/.env"
    [ -n "$PRIV_KEY" ] && sed -i '' "s|^PRIVATE_KEY=.*|PRIVATE_KEY=$PRIV_KEY|" "$ROOT_DIR/backend/.env"
  else
    sed -i "s|^CONTRACT_ADDRESS=.*|CONTRACT_ADDRESS=$CONTRACT_ADDR|" "$ROOT_DIR/backend/.env"
    [ -n "$PRIV_KEY" ] && sed -i "s|^PRIVATE_KEY=.*|PRIVATE_KEY=$PRIV_KEY|" "$ROOT_DIR/backend/.env"
  fi
  ok "Updated backend/.env"
fi

# Frontend .env
if [ -f "$ROOT_DIR/frontend/.env" ]; then
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|^VITE_CONTRACT_ADDRESS=.*|VITE_CONTRACT_ADDRESS=$CONTRACT_ADDR|" "$ROOT_DIR/frontend/.env"
    sed -i '' "s|^VITE_CHAIN_ID=.*|VITE_CHAIN_ID=$CHAIN_ID|" "$ROOT_DIR/frontend/.env"
  else
    sed -i "s|^VITE_CONTRACT_ADDRESS=.*|VITE_CONTRACT_ADDRESS=$CONTRACT_ADDR|" "$ROOT_DIR/frontend/.env"
    sed -i "s|^VITE_CHAIN_ID=.*|VITE_CHAIN_ID=$CHAIN_ID|" "$ROOT_DIR/frontend/.env"
  fi
  ok "Updated frontend/.env"
fi

# Submission JSON
if [ -f "$ROOT_DIR/.initia/submission.json" ]; then
  TMP=$(mktemp)
  jq --arg addr "$CONTRACT_ADDR" '.deployed_address = $addr' "$ROOT_DIR/.initia/submission.json" > "$TMP"
  mv "$TMP" "$ROOT_DIR/.initia/submission.json"
  ok "Updated .initia/submission.json"
fi

echo ""
printf "${GREEN}========================================${NC}\n"
printf "${GREEN}  Deployment Complete${NC}\n"
printf "${GREEN}========================================${NC}\n"
printf "  Contract: %s\n" "$CONTRACT_ADDR"
printf "  Chain:    %s\n" "$CHAIN_ID"
printf "  TX:       %s\n" "$TX_HASH"
printf "${GREEN}========================================${NC}\n"
printf "  Run ./start.sh to launch the app\n"
printf "${GREEN}========================================${NC}\n"
