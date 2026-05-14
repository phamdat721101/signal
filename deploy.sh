#!/bin/bash
set -e
VPS="bitnami@47.130.193.211"
KEY="$HOME/Downloads/nim-claw.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no $VPS"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"

echo "=== Deploying backend ==="
$SCP backend/app/main.py backend/app/scheduler.py backend/app/scheduler_worker.py \
     backend/app/db.py backend/app/chain.py backend/app/agent_api.py \
     backend/app/config.py backend/app/content_engine.py backend/app/trustless_escrow.py \
     $VPS:/home/bitnami/signal-backend/app/

echo "=== Deploying restart script ==="
$SCP deploy.sh $VPS:/home/bitnami/restart_signal.sh

echo "=== Restarting ==="
$SSH 'bash /home/bitnami/restart_signal.sh'
sleep 12
$SSH 'curl -sf localhost:8001/api/health && echo " API UP" || echo " API DOWN"'
