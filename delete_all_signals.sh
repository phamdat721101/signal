#!/usr/bin/env bash
# delete_all_signals.sh — Unified script to clear ALL signal data:
#   1. Supabase/Postgres DB (TRUNCATE)
#   2. On-chain SignalRegistry (redeploy fresh contract)
#   3. Backend in-memory state (API reset + restart advice)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_ENV="$ROOT_DIR/backend/.env"
FRONTEND_ENV="$ROOT_DIR/frontend/.env"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
info() { printf "${BLUE}[info]${NC}  %s\n" "$1"; }
ok()   { printf "${GREEN}[ok]${NC}    %s\n" "$1"; }
warn() { printf "${YELLOW}[skip]${NC}  %s\n" "$1"; }
fail() { printf "${RED}[fail]${NC}  %s\n" "$1"; }

load_env() { grep "^$1=" "$BACKEND_ENV" 2>/dev/null | cut -d= -f2- || echo ""; }

# ─── 1. Clear Database ──────────────────────────────────────
info "Step 1: Database"
DATABASE_URL=$(load_env DATABASE_URL)
if [[ -n "$DATABASE_URL" ]]; then
  DB_URL="${DATABASE_URL%%\?*}"
  if psql "$DB_URL" -c "TRUNCATE signals RESTART IDENTITY;" 2>/dev/null; then
    ok "Truncated signals table"
  else
    fail "DB truncate failed (psql error or table missing)"
  fi
else
  warn "DATABASE_URL not set — skipping DB"
fi

# ─── 2. Redeploy Contract ───────────────────────────────────
info "Step 2: On-chain (redeploy SignalRegistry)"
CONTRACT_ADDRESS=$(load_env CONTRACT_ADDRESS)
PRIVATE_KEY=$(load_env PRIVATE_KEY)
NETWORK=$(load_env NETWORK)

if [[ -z "$CONTRACT_ADDRESS" ]]; then
  warn "CONTRACT_ADDRESS not set — skipping on-chain (simulation mode)"
elif [[ -z "$PRIVATE_KEY" ]]; then
  warn "PRIVATE_KEY not set — skipping on-chain"
else
  if [[ "$NETWORK" == "testnet" ]]; then
    RPC_URL=$(load_env TESTNET_JSON_RPC_URL)
  else
    RPC_URL=$(load_env LOCAL_JSON_RPC_URL)
  fi

  NEW_ADDRESS=$(cd "$ROOT_DIR/backend" && source .venv/bin/activate && python3 -c "
import json, glob
from pathlib import Path
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

w3 = Web3(Web3.HTTPProvider('$RPC_URL'))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
if not w3.is_connected():
    raise SystemExit('RPC not reachable')
account = w3.eth.account.from_key('$PRIVATE_KEY')
abi = json.loads(Path('app/abi.json').read_text())

# Find bytecode
candidates = glob.glob('$ROOT_DIR/contracts/out/SignalRegistry.sol/SignalRegistry.json')
if candidates:
    bytecode = json.loads(Path(candidates[0]).read_text())['bytecode']['object']
else:
    bin_path = Path('$ROOT_DIR/contracts/SignalRegistry.bin')
    if bin_path.exists():
        bytecode = '0x' + bin_path.read_text().strip()
    else:
        raise FileNotFoundError('No bytecode. Run: cd contracts && forge build --via-ir')

contract = w3.eth.contract(abi=abi, bytecode=bytecode)
tx = contract.constructor().build_transaction({
    'from': account.address,
    'nonce': w3.eth.get_transaction_count(account.address),
    'gas': 2_000_000, 'gasPrice': 0,
})
signed = account.sign_transaction(tx)
receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
print(receipt['contractAddress'])
" 2>&1) || true

  if [[ -n "$NEW_ADDRESS" && "$NEW_ADDRESS" == 0x* ]]; then
    sed -i '' "s|^CONTRACT_ADDRESS=.*|CONTRACT_ADDRESS=$NEW_ADDRESS|" "$BACKEND_ENV"
    sed -i '' "s|^VITE_CONTRACT_ADDRESS=.*|VITE_CONTRACT_ADDRESS=$NEW_ADDRESS|" "$FRONTEND_ENV"
    ok "New SignalRegistry: $NEW_ADDRESS (updated .env files)"
  else
    fail "Contract deploy failed: ${NEW_ADDRESS:-unknown error}"
  fi
fi

# ─── 3. Clear In-Memory State ───────────────────────────────
info "Step 3: Backend in-memory state"
if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
  RESET=$(curl -sf -X POST http://localhost:8000/api/admin/reset 2>&1) || true
  if [[ "$RESET" == *"ok"* ]]; then
    ok "In-memory state cleared via API"
  else
    fail "Reset API call failed"
  fi
  warn "Restart backend to pick up new contract address"
else
  warn "Backend not running — in-memory state will be clean on next start"
fi

# ─── Summary ────────────────────────────────────────────────
printf "\n${GREEN}══════════════════════════════════════${NC}\n"
printf "${GREEN}  All signal data cleared!${NC}\n"
printf "${GREEN}  Restart backend + frontend to apply${NC}\n"
printf "${GREEN}══════════════════════════════════════${NC}\n"
