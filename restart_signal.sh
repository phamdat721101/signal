#!/bin/bash
# Restart Signal API + Scheduler as separate processes
cd /home/bitnami/signal-backend

pkill -9 -f "uvicorn app.main" 2>/dev/null
pkill -9 -f "app.scheduler_worker" 2>/dev/null
sleep 2

# API: single worker (avoids fork issues with pydantic-settings)
nohup .venv/bin/python3 -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8001 --workers 1 >> backend.log 2>&1 &
echo "API PID: $!"

# Scheduler: 1 process, background jobs only
nohup .venv/bin/python3 -m app.scheduler_worker >> scheduler.log 2>&1 &
echo "Scheduler PID: $!"

echo "started"
