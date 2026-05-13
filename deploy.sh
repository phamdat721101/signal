#!/bin/bash
set -e
VPS="bitnami@47.130.193.211"
KEY="$HOME/Downloads/nim-claw.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no $VPS"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"

echo "=== Deploying backend ==="
$SCP backend/app/main.py backend/app/scheduler.py backend/app/content_engine.py \
     backend/app/agent_api.py backend/app/trustless_escrow.py backend/app/x402_payment.py \
     $VPS:/home/bitnami/signal-backend/app/

echo "=== Restarting + verifying ==="
$SSH "sudo pkill -9 -f 'app.main.*8001' 2>/dev/null; sleep 1; sudo systemctl start signal-backend; \
  for i in \$(seq 1 12); do sleep 5; curl -sf http://localhost:8001/api/health && echo ' UP!' && exit 0; done; \
  echo 'TIMEOUT'; journalctl -u signal-backend -n 10 --no-pager; exit 1"
