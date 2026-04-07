#!/usr/bin/env bash
#
# deploy-testnet.sh — Deploy all contracts to Initia testnet via forge
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTRACTS_DIR="$ROOT_DIR/contracts"

# Load env
source "$ROOT_DIR/backend/.env"
RPC_URL="${TESTNET_JSON_RPC_URL:-https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz}"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { printf "${BLUE}[deploy]${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}[deploy]${NC} %s\n" "$1"; }
err()   { printf "${RED}[deploy]${NC} %s\n" "$1"; exit 1; }

[ -z "$PRIVATE_KEY" ] && err "PRIVATE_KEY not set in backend/.env"

info "RPC: $RPC_URL"
info "Building contracts..."
cd "$CONTRACTS_DIR"
forge build --via-ir 2>&1 | tail -3

info "Deploying all contracts..."
DEPLOY_OUTPUT=$(forge script script/Deploy.s.sol \
  --rpc-url "$RPC_URL" \
  --private-key "$PRIVATE_KEY" \
  --broadcast \
  --via-ir \
  --skip-simulation \
  --with-gas-price 0 \
  --slow \
  2>&1) || {
  echo "$DEPLOY_OUTPUT"
  err "Forge script failed"
}

echo "$DEPLOY_OUTPUT"

# Parse addresses from console.log output
SIGNAL_ADDR=$(echo "$DEPLOY_OUTPUT" | grep "SignalRegistry:" | awk '{print $NF}')
IUSD_ADDR=$(echo "$DEPLOY_OUTPUT" | grep "MockIUSD:" | awk '{print $NF}')
VAULT_ADDR=$(echo "$DEPLOY_OUTPUT" | grep "SessionVault:" | awk '{print $NF}')
GW_ADDR=$(echo "$DEPLOY_OUTPUT" | grep "SignalPaymentGateway:" | awk '{print $NF}')

if [ -z "$SIGNAL_ADDR" ] || [ -z "$IUSD_ADDR" ]; then
  err "Could not parse contract addresses from output"
fi

# Update .env files
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

info "Updating .env files..."
update_env "$ROOT_DIR/backend/.env" "CONTRACT_ADDRESS" "$SIGNAL_ADDR"
update_env "$ROOT_DIR/backend/.env" "MOCK_IUSD_ADDRESS" "$IUSD_ADDR"
update_env "$ROOT_DIR/backend/.env" "SESSION_VAULT_ADDRESS" "$VAULT_ADDR"
update_env "$ROOT_DIR/backend/.env" "PAYMENT_GATEWAY_ADDRESS" "$GW_ADDR"
update_env "$ROOT_DIR/backend/.env" "NETWORK" "testnet"
update_env "$ROOT_DIR/backend/.env" "ENABLE_PAYMENT_GATING" "true"

update_env "$ROOT_DIR/frontend/.env" "VITE_CONTRACT_ADDRESS" "$SIGNAL_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_MOCK_IUSD_ADDRESS" "$IUSD_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_SESSION_VAULT_ADDRESS" "$VAULT_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_PAYMENT_GATEWAY_ADDRESS" "$GW_ADDR"
update_env "$ROOT_DIR/frontend/.env" "VITE_PAYMENT_ENABLED" "true"
update_env "$ROOT_DIR/frontend/.env" "VITE_NETWORK" "testnet"

ok "Updated backend/.env and frontend/.env"

# Extract ABIs
info "Extracting ABIs..."
jq '.abi' out/MockIUSD.sol/MockIUSD.json > "$ROOT_DIR/backend/app/mock_iusd_abi.json"
jq '.abi' out/SessionVault.sol/SessionVault.json > "$ROOT_DIR/backend/app/session_vault_abi.json"
jq '.abi' out/SignalPaymentGateway.sol/SignalPaymentGateway.json > "$ROOT_DIR/backend/app/payment_gateway_abi.json"
ok "ABIs extracted to backend/app/"

printf "\n${GREEN}========================================${NC}\n"
printf "${GREEN}  Testnet Deployment Complete${NC}\n"
printf "${GREEN}========================================${NC}\n"
printf "  SignalRegistry:        %s\n" "$SIGNAL_ADDR"
printf "  MockIUSD:              %s\n" "$IUSD_ADDR"
printf "  SessionVault:          %s\n" "$VAULT_ADDR"
printf "  SignalPaymentGateway:  %s\n" "$GW_ADDR"
printf "  RPC:                   %s\n" "$RPC_URL"
printf "${GREEN}========================================${NC}\n"
printf "\nNext: redeploy backend to VPS:\n"
printf "  scp -i ~/.ssh/nim-claw.pem -r backend/app backend/.env bitnami@13.212.80.72:~/signal/backend/\n"
printf "  ssh -i ~/.ssh/nim-claw.pem bitnami@13.212.80.72 '~/signal/restart.sh'\n"
printf "${GREEN}========================================${NC}\n"
