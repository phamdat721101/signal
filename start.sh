#!/usr/bin/env bash
#
# start.sh — Start Initia Signal backend + frontend
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Colors (respect NO_COLOR convention)
if [[ -z "${NO_COLOR:-}" ]]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; NC='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''
fi

info()  { printf "${BLUE}[info]${NC}  %s\n" "$1"; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$1"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$1"; }
err()   { printf "${RED}[error]${NC} %s\n" "$1"; }

# --- Cleanup ---
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  info "Shutting down..."
  [[ -n "$BACKEND_PID" ]]  && kill "$BACKEND_PID"  2>/dev/null
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null
  wait 2>/dev/null
  ok "All services stopped."
}
trap cleanup EXIT INT TERM

# --- Prerequisites ---
info "Checking prerequisites..."
missing=0
for cmd in python3 node npm; do
  if ! command -v "$cmd" &>/dev/null; then
    err "$cmd is required but not found"
    missing=1
  fi
done
[[ $missing -eq 1 ]] && exit 1
ok "Prerequisites found (python3, node, npm)"

# --- Env files ---
info "Checking .env files..."
for dir in "$BACKEND_DIR" "$FRONTEND_DIR"; do
  name="$(basename "$dir")"
  if [[ ! -f "$dir/.env" ]]; then
    if [[ -f "$dir/.env.example" ]]; then
      cp "$dir/.env.example" "$dir/.env"
      ok "Created $name/.env from .env.example"
    else
      err "$name/.env.example not found — cannot create .env"
      exit 1
    fi
  else
    ok "$name/.env already exists"
  fi
done

# --- Backend setup ---
info "Setting up backend..."
if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv"
  ok "Created Python virtual environment"
fi
source "$BACKEND_DIR/.venv/bin/activate"
pip install -q -r "$BACKEND_DIR/requirements.txt"
ok "Backend dependencies installed"

# --- Frontend setup ---
info "Setting up frontend..."
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  (cd "$FRONTEND_DIR" && npm install)
  ok "Frontend dependencies installed"
else
  ok "Frontend dependencies already installed"
fi

# --- Start services ---
echo ""
info "Starting services..."
echo ""

(cd "$BACKEND_DIR" && uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

(cd "$FRONTEND_DIR" && npx vite --port 5173) &
FRONTEND_PID=$!

echo ""
printf "${GREEN}========================================${NC}\n"
printf "${GREEN}  Initia Signal — Running${NC}\n"
printf "${GREEN}========================================${NC}\n"
printf "  Backend:  http://localhost:8000\n"
printf "  Frontend: http://localhost:5173\n"
printf "  Health:   http://localhost:8000/api/health\n"
printf "${GREEN}========================================${NC}\n"
printf "  Press Ctrl+C to stop all services\n"
printf "${GREEN}========================================${NC}\n"
echo ""

wait
