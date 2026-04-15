#!/usr/bin/env bash
#
# start.sh — Start Ape or Fade (KINETIC) full-stack
#
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/.logs"
mkdir -p "$LOG_DIR"

# Colors
if [[ -z "${NO_COLOR:-}" ]]; then
  G='\033[0;32m'; Y='\033[0;33m'; B='\033[0;34m'; R='\033[0;31m'; N='\033[0m'
else
  G=''; Y=''; B=''; R=''; N=''
fi

info()  { printf "${B}[info]${N}  %s\n" "$1"; }
ok()    { printf "${G}[ok]${N}    %s\n" "$1"; }
warn()  { printf "${Y}[warn]${N}  %s\n" "$1"; }
fail()  { printf "${R}[FAIL]${N} %s\n" "$1"; printf "${R}       → Fix: %s${N}\n" "$2"; }

# Error log — append structured errors for debugging
log_error() {
  local ts=$(date '+%Y-%m-%d %H:%M:%S')
  local step="$1" msg="$2" fix="${3:-}"
  echo "[$ts] STEP=$step ERROR=$msg FIX=$fix" >> "$LOG_DIR/start-errors.log"
  fail "$msg" "${fix:-Check $LOG_DIR/start-errors.log}"
}

# Cleanup
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

# ─── Step 1: Prerequisites ───────────────────────────────────
info "Checking prerequisites..."
for cmd in python3 node npm; do
  if ! command -v "$cmd" &>/dev/null; then
    log_error "prereqs" "$cmd not found" "Install $cmd (brew install $cmd)"
    exit 1
  fi
done

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "python3 ($PY_VER), node ($(node -v)), npm ($(npm -v))"

# ─── Step 2: Env files ──────────────────────────────────────
for dir in "$BACKEND_DIR" "$FRONTEND_DIR"; do
  name="$(basename "$dir")"
  if [[ ! -f "$dir/.env" ]]; then
    if [[ -f "$dir/.env.example" ]]; then
      cp "$dir/.env.example" "$dir/.env"
      ok "Created $name/.env from .env.example"
    else
      warn "$name/.env missing (no .env.example either) — using defaults"
    fi
  fi
done

# ─── Step 3: Backend deps ───────────────────────────────────
info "Setting up backend..."
if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  python3 -m venv "$BACKEND_DIR/.venv" || {
    log_error "venv" "Failed to create Python venv" "python3 -m ensurepip; python3 -m venv backend/.venv"
    exit 1
  }
  ok "Created Python venv"
fi

source "$BACKEND_DIR/.venv/bin/activate"

if ! pip install -r "$BACKEND_DIR/requirements.txt" > "$LOG_DIR/pip-install.log" 2>&1; then
  log_error "pip" "pip install failed — see $LOG_DIR/pip-install.log" \
    "Check Python version ($PY_VER) compat. Try: pip install --upgrade pip && pip install -r requirements.txt"
  echo "--- Last 10 lines of pip output ---"
  tail -10 "$LOG_DIR/pip-install.log"
  exit 1
fi
ok "Backend deps installed"

# Quick import check
if ! python3 -c "import fastapi, httpx, psycopg2, boto3" 2>"$LOG_DIR/import-check.log"; then
  log_error "imports" "Python import check failed" "See $LOG_DIR/import-check.log"
  cat "$LOG_DIR/import-check.log"
  exit 1
fi
ok "Python imports verified (fastapi, httpx, psycopg2, boto3)"

# ─── Step 4: Frontend deps ──────────────────────────────────
info "Setting up frontend..."
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  if ! (cd "$FRONTEND_DIR" && npm install) > "$LOG_DIR/npm-install.log" 2>&1; then
    log_error "npm" "npm install failed — see $LOG_DIR/npm-install.log" "cd frontend && npm install"
    exit 1
  fi
  ok "Frontend deps installed"
else
  ok "Frontend node_modules exists"
fi

# ─── Step 5: Start services ─────────────────────────────────
echo ""
info "Starting services..."

(cd "$BACKEND_DIR" && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) \
  > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
info "Waiting for backend..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    ok "Backend ready (pid=$BACKEND_PID)"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log_error "backend" "Backend process died on startup" "Check $LOG_DIR/backend.log"
    echo "--- Last 20 lines ---"
    tail -20 "$LOG_DIR/backend.log"
    exit 1
  fi
  sleep 1
done

if ! curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
  log_error "backend" "Backend not responding after 15s" "Check $LOG_DIR/backend.log"
  tail -20 "$LOG_DIR/backend.log"
  exit 1
fi

(cd "$FRONTEND_DIR" && npx vite --host 0.0.0.0 --port 5173) \
  > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
sleep 2

if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  log_error "frontend" "Frontend process died on startup" "Check $LOG_DIR/frontend.log"
  tail -20 "$LOG_DIR/frontend.log"
  exit 1
fi
ok "Frontend ready (pid=$FRONTEND_PID)"

# ─── Step 6: Initial card generation ────────────────────────
if grep -q "DATABASE_URL=." "$BACKEND_DIR/.env" 2>/dev/null; then
  info "Triggering initial card generation..."
  if curl -sf -X POST http://localhost:8000/api/cards/generate > /dev/null 2>&1; then
    ok "Card generation triggered"
  else
    warn "Card generation failed (Bedrock credentials may not be configured)"
  fi
fi

# ─── Banner ──────────────────────────────────────────────────
echo ""
printf "${G}╔══════════════════════════════════════════╗${N}\n"
printf "${G}║   🦍 APE OR FADE — KINETIC               ║${N}\n"
printf "${G}╠══════════════════════════════════════════╣${N}\n"
printf "${G}║${N}  Frontend:  http://localhost:5173         ${G}║${N}\n"
printf "${G}║${N}  Backend:   http://localhost:8000         ${G}║${N}\n"
printf "${G}║${N}  Health:    http://localhost:8000/api/health  ${G}║${N}\n"
printf "${G}║${N}  Cards:     http://localhost:8000/api/cards   ${G}║${N}\n"
printf "${G}╠══════════════════════════════════════════╣${N}\n"
printf "${G}║${N}  Logs:      .logs/backend.log              ${G}║${N}\n"
printf "${G}║${N}             .logs/frontend.log             ${G}║${N}\n"
printf "${G}║${N}  Errors:    .logs/start-errors.log         ${G}║${N}\n"
printf "${G}╠══════════════════════════════════════════╣${N}\n"
printf "${G}║${N}  Press Ctrl+C to stop all services         ${G}║${N}\n"
printf "${G}╚══════════════════════════════════════════╝${N}\n"
echo ""

wait
