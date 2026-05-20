#!/bin/bash
# Restart Signal stack: Python consumer (8001, loopback only) + Scheduler + Node agent-provider (8002, public).
# Caddy must route /agent-api/* -> :8002 and /api/* -> :8001 (the latter via VPS-internal only).
set -euo pipefail
cd /home/bitnami/signal-backend

pkill -9 -f "uvicorn app.main" 2>/dev/null || true
pkill -9 -f "app.scheduler_worker" 2>/dev/null || true
pkill -9 -f "uvicorn app.agent_main" 2>/dev/null || true   # legacy Python agent — replaced by Node
sleep 2

# Python consumer + admin: bound to LOOPBACK so only Node (and the VPS) can reach it
nohup .venv/bin/python3 -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8001 --workers 1 >> backend.log 2>&1 &
echo "API PID: $!"

# Scheduler (unchanged)
nohup .venv/bin/python3 -m app.scheduler_worker >> scheduler.log 2>&1 &
echo "Scheduler PID: $!"

# Node agent-provider via PM2 (HTTP server + settlement retry worker)
if [ -d "agent-provider/dist" ]; then
  pm2 startOrReload agent-provider/ecosystem.config.cjs --update-env
  pm2 save
  echo "agent-provider reloaded via PM2"
else
  echo "WARN: agent-provider/dist not found — run 'cd agent-provider && pnpm install && pnpm build' first"
fi

echo "started"
