#!/usr/bin/env bash
#
# post-init.sh — Run AFTER weave init completes.
# Handles: bots start, key import, contract deploy, env wiring.
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHAIN_ID="initia-signal-1"
KEY_NAME="gas-station"
KEYRING="test"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'; NC='\033[0m'
info()  { printf "${BLUE}[setup]${NC}  %s\n" "$1"; }
ok()    { printf "${GREEN}[setup]${NC}  %s\n" "$1"; }
warn()  { printf "${YELLOW}[setup]${NC}  %s\n" "$1"; }
err()   { printf "${RED}[setup]${NC}  %s\n" "$1"; exit 1; }

# ============================================================
# 1. Verify appchain is running
# ============================================================
info "Checking appchain status..."
HEIGHT=$(minitiad status 2>/dev/null | jq -r '.sync_info.latest_block_height // empty' || true)
if [ -z "$HEIGHT" ]; then
  err "Appchain is not running. Did weave init complete? Try: weave rollup start -d"
fi
ok "Appchain running at height $HEIGHT"

# Auto-detect chain ID from config
DETECTED_CHAIN=$(jq -r '.l2_config.chain_id // empty' ~/.minitia/artifacts/config.json 2>/dev/null || true)
if [ -n "$DETECTED_CHAIN" ]; then
  CHAIN_ID="$DETECTED_CHAIN"
  ok "Detected chain ID: $CHAIN_ID"
fi

# ============================================================
# 2. Import gas-station key
# ============================================================
info "Importing gas-station key..."
MNEMONIC=$(jq -r '.common.gas_station.mnemonic // empty' ~/.weave/config.json 2>/dev/null)
if [ -z "$MNEMONIC" ]; then
  err "No gas-station mnemonic found in ~/.weave/config.json"
fi

# Import into minitiad (L2) — skip if already exists
if minitiad keys show "$KEY_NAME" --keyring-backend "$KEYRING" &>/dev/null; then
  ok "gas-station key already in minitiad keyring"
else
  echo "$MNEMONIC" | minitiad keys add "$KEY_NAME" --recover --keyring-backend "$KEYRING" \
    --coin-type 60 --key-type eth_secp256k1 --source /dev/stdin 2>/dev/null
  ok "Imported gas-station into minitiad"
fi

# Import into initiad (L1) — skip if already exists
if initiad keys show "$KEY_NAME" --keyring-backend "$KEYRING" &>/dev/null; then
  ok "gas-station key already in initiad keyring"
else
  echo "$MNEMONIC" | initiad keys add "$KEY_NAME" --recover --keyring-backend "$KEYRING" \
    --coin-type 60 --key-type eth_secp256k1 --source /dev/stdin 2>/dev/null
  ok "Imported gas-station into initiad"
fi

# Verify balance
ADDR=$(minitiad keys show "$KEY_NAME" -a --keyring-backend "$KEYRING")
info "Gas station address: $ADDR"
BALANCE=$(minitiad query bank balances "$ADDR" -o json 2>/dev/null | jq -r '.balances[0].amount // "0"')
ok "L2 balance: $BALANCE"
if [ "$BALANCE" = "0" ]; then
  err "Gas station has zero balance on L2. Something went wrong with genesis."
fi

# ============================================================
# 3. Build and deploy contract
# ============================================================
info "Building SignalRegistry contract..."
cd "$ROOT_DIR/contracts"
forge build --via-ir --silent
ok "Contract built"

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
  err "Failed to broadcast tx. Output: $TX_OUTPUT"
fi
info "TX broadcast: $TX_HASH"

info "Waiting for indexing..."
sleep 6

CONTRACT_ADDR=""
for i in 1 2 3; do
  CONTRACT_ADDR=$(minitiad q tx "$TX_HASH" --output json 2>/dev/null \
    | jq -r '.events[] | select(.type=="contract_created") | .attributes[] | select(.key=="contract") | .value' || true)
  [ -n "$CONTRACT_ADDR" ] && break
  info "Retry $i..."
  sleep 3
done

if [ -z "$CONTRACT_ADDR" ]; then
  err "Could not find contract address. Check: minitiad q tx $TX_HASH"
fi
ok "Contract deployed at: $CONTRACT_ADDR"

# Cleanup bytecode
rm -f SignalRegistry.bin

# Verify
info "Verifying deployment..."
CALLDATA=$(cast calldata "getSignalCount()")
RESULT=$(minitiad query evm call "$ADDR" "$CONTRACT_ADDR" "$CALLDATA" -o json 2>/dev/null | jq -r '.response // empty' || true)
if [ -n "$RESULT" ]; then
  ok "getSignalCount() = $RESULT ✓"
fi

# ============================================================
# 4. Wire .env files
# ============================================================
info "Wiring configuration..."
cd "$ROOT_DIR"

# Get private key
PRIV_KEY=$(jq -r '.common.gas_station.private_key // empty' ~/.weave/config.json 2>/dev/null)

# Backend .env
if [ -f backend/.env ]; then
  sed -i '' "s|^CONTRACT_ADDRESS=.*|CONTRACT_ADDRESS=$CONTRACT_ADDR|" backend/.env
  [ -n "$PRIV_KEY" ] && sed -i '' "s|^PRIVATE_KEY=.*|PRIVATE_KEY=$PRIV_KEY|" backend/.env
  ok "Updated backend/.env"
else
  warn "backend/.env not found, skipping"
fi

# Frontend .env
if [ -f frontend/.env ]; then
  sed -i '' "s|^VITE_CONTRACT_ADDRESS=.*|VITE_CONTRACT_ADDRESS=$CONTRACT_ADDR|" frontend/.env
  sed -i '' "s|^VITE_CHAIN_ID=.*|VITE_CHAIN_ID=$CHAIN_ID|" frontend/.env
  ok "Updated frontend/.env"
else
  warn "frontend/.env not found, skipping"
fi

# Submission JSON
if [ -f .initia/submission.json ]; then
  TMP=$(mktemp)
  jq --arg addr "$CONTRACT_ADDR" --arg cid "$CHAIN_ID" \
    '.deployed_address = $addr | .rollup_chain_id = $cid' .initia/submission.json > "$TMP"
  mv "$TMP" .initia/submission.json
  ok "Updated .initia/submission.json"
fi

# ============================================================
# Done
# ============================================================
echo ""
printf "${GREEN}════════════════════════════════════════${NC}\n"
printf "${GREEN}  Setup Complete!${NC}\n"
printf "${GREEN}════════════════════════════════════════${NC}\n"
printf "  Chain ID:  %s\n" "$CHAIN_ID"
printf "  Contract:  %s\n" "$CONTRACT_ADDR"
printf "  Gas Stn:   %s\n" "$ADDR"
printf "  TX Hash:   %s\n" "$TX_HASH"
printf "${GREEN}════════════════════════════════════════${NC}\n"
printf "  Next: run ${GREEN}./start.sh${NC} to launch the app\n"
printf "${GREEN}════════════════════════════════════════${NC}\n"
