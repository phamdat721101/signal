#!/usr/bin/env bash
# reset_signals.sh — Deploy fresh SignalRegistry to clear all old signals
# The contract is append-only (no delete), so we redeploy a clean instance.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_ENV="$ROOT_DIR/backend/.env"
FRONTEND_ENV="$ROOT_DIR/frontend/.env"

# Colors
GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { printf "${BLUE}[info]${NC}  %s\n" "$1"; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$1"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$1"; }

# Load private key and RPC from backend .env
PRIVATE_KEY=$(grep '^PRIVATE_KEY=' "$BACKEND_ENV" | cut -d= -f2)
NETWORK=$(grep '^NETWORK=' "$BACKEND_ENV" | cut -d= -f2)

if [[ "$NETWORK" == "testnet" ]]; then
  RPC_URL=$(grep '^TESTNET_JSON_RPC_URL=' "$BACKEND_ENV" | cut -d= -f2)
else
  RPC_URL=$(grep '^LOCAL_JSON_RPC_URL=' "$BACKEND_ENV" | cut -d= -f2)
fi

if [[ -z "$PRIVATE_KEY" || -z "$RPC_URL" ]]; then
  echo "ERROR: PRIVATE_KEY or RPC_URL not found in $BACKEND_ENV"
  exit 1
fi

info "Network: $NETWORK | RPC: $RPC_URL"
info "Deploying fresh SignalRegistry..."

# Deploy using Python + web3
NEW_ADDRESS=$(cd "$ROOT_DIR/backend" && source .venv/bin/activate && python3 -c "
import json
from pathlib import Path
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

w3 = Web3(Web3.HTTPProvider('$RPC_URL'))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
account = w3.eth.account.from_key('$PRIVATE_KEY')

abi = json.loads(Path('app/abi.json').read_text())

# Read bytecode from existing build
bin_path = Path('$ROOT_DIR/contracts/SignalRegistry.bin')
if not bin_path.exists():
    # Try forge build output
    import glob
    candidates = glob.glob('$ROOT_DIR/contracts/out/SignalRegistry.sol/SignalRegistry.json')
    if candidates:
        data = json.loads(Path(candidates[0]).read_text())
        bytecode = data['bytecode']['object']
    else:
        raise FileNotFoundError('No bytecode found. Run: cd contracts && forge build --via-ir')
else:
    bytecode = '0x' + bin_path.read_text().strip()

contract = w3.eth.contract(abi=abi, bytecode=bytecode)
nonce = w3.eth.get_transaction_count(account.address)
tx = contract.constructor().build_transaction({
    'from': account.address,
    'nonce': nonce,
    'gas': 2_000_000,
    'gasPrice': 0,
})
signed = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
print(receipt['contractAddress'])
")

if [[ -z "$NEW_ADDRESS" ]]; then
  echo "ERROR: Deployment failed"
  exit 1
fi

ok "New SignalRegistry deployed at: $NEW_ADDRESS"

# Update backend .env
OLD_ADDR=$(grep '^CONTRACT_ADDRESS=' "$BACKEND_ENV" | cut -d= -f2)
sed -i '' "s|^CONTRACT_ADDRESS=.*|CONTRACT_ADDRESS=$NEW_ADDRESS|" "$BACKEND_ENV"
ok "Updated backend/.env: $OLD_ADDR → $NEW_ADDRESS"

# Update frontend .env
sed -i '' "s|^VITE_CONTRACT_ADDRESS=.*|VITE_CONTRACT_ADDRESS=$NEW_ADDRESS|" "$FRONTEND_ENV"
ok "Updated frontend/.env"

# Clear in-memory state if backend is running
if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
  warn "Backend is running — restart it to pick up the new contract address"
fi

printf "\n${GREEN}========================================${NC}\n"
printf "${GREEN}  All old signals cleared!${NC}\n"
printf "${GREEN}  New contract: $NEW_ADDRESS${NC}\n"
printf "${GREEN}  Restart backend + frontend to apply${NC}\n"
printf "${GREEN}========================================${NC}\n"
