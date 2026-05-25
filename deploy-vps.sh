#!/bin/bash
set -e

VPS="bitnami@13.212.80.72"
KEY="nim-claw.pem"
REMOTE_DIR="~/signal-backend"

echo "=== Step 1: Package backend ==="
cd /Users/phamdat/initia/signal
tar czf /tmp/signal-backend.tar.gz \
  backend/app/ \
  backend/requirements.txt \
  --exclude='__pycache__' --exclude='.venv'

echo "=== Step 2: Upload to VPS ==="
scp -i "$KEY" /tmp/signal-backend.tar.gz "$VPS:/tmp/"

echo "=== Step 3: Deploy on VPS ==="
ssh -i "$KEY" "$VPS" << 'REMOTE'
set -e
mkdir -p ~/signal-backend && cd ~/signal-backend
tar xzf /tmp/signal-backend.tar.gz --strip-components=1
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt

# Create .env if not exists
[ -f app/.env ] || cat > app/.env << 'ENVEOF'
NETWORK=local
LOCAL_JSON_RPC_URL=http://localhost:8545
DATABASE_URL=
PRIVATE_KEY=
CONTRACT_ADDRESS=
ENVEOF

# Stop old process if running
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1

# Start backend
cd ~/signal-backend
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
echo "Backend PID: $!"
sleep 2
curl -s http://localhost:8000/api/health | head -100
echo ""
echo "=== API URL: http://13.212.80.72:8000 ==="
REMOTE

echo ""
echo "=== Done! ==="
echo "API URL: http://13.212.80.72:8000"
echo ""
echo "Now update your frontend .env:"
echo "  VITE_BACKEND_URL=http://13.212.80.72:8000"
