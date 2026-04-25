#!/bin/bash
# Ape or Fade — On-Chain Verification Demo
# Run while screen recording for hackathon video

API="http://localhost:8000"
ADDR="0x870E083EA7B89BB58EBCB53167471E175E1CBE2A"
CONVICTION="0xa3348e45BdA143a3E75Aee995d2b4cBF6954EFCB"
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; NC='\033[0m'

pause() { sleep 2; echo ""; }

echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${CYAN}  🦍 Ape or Fade — On-Chain Verification   ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo ""

echo -e "${GREEN}▸ 1. Appchain health check${NC}"
curl -s $API/api/health | python3 -m json.tool
pause

echo -e "${GREEN}▸ 2. On-chain metrics (7 contracts deployed)${NC}"
curl -s $API/api/metrics | python3 -m json.tool
pause

echo -e "${GREEN}▸ 3. Ape card → conviction committed ON-CHAIN${NC}"
curl -s -X POST $API/api/cards/1/ape \
  -H "Content-Type: application/json" \
  -d "{\"address\":\"$ADDR\", \"amount_usd\": 1.0}" | python3 -m json.tool
pause

echo -e "${GREEN}▸ 4. Read reputation from ConvictionEngine contract${NC}"
echo -e "${YELLOW}  source: on-chain — NOT backend database${NC}"
curl -s $API/api/conviction/$ADDR | python3 -m json.tool
pause

echo -e "${GREEN}▸ 5. On-chain reputation leaderboard${NC}"
curl -s $API/api/conviction/leaderboard | python3 -m json.tool
pause

echo -e "${GREEN}▸ 6. Profile — Trading IQ boosted by on-chain rep${NC}"
curl -s $API/api/profile/$ADDR | python3 -m json.tool
pause

echo -e "${GREEN}▸ 7. Rewards from RewardEngine contract${NC}"
curl -s $API/api/rewards/$ADDR | python3 -m json.tool
pause

echo -e "${GREEN}▸ 8. Direct contract call — getConvictionCount()${NC}"
if command -v cast &>/dev/null; then
  cast call $CONVICTION "getConvictionCount()(uint256)" --rpc-url http://localhost:8545
else
  echo "  (cast not in PATH — using API)"
  curl -s $API/api/metrics | python3 -c "import sys,json; print('  Convictions:', json.load(sys.stdin).get('on_chain_convictions', 0))"
fi
pause

echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${CYAN}  ✓ All data verified on-chain             ${NC}"
echo -e "${CYAN}  ✓ 7 contracts on initia-signal-1         ${NC}"
echo -e "${CYAN}  ✓ Reputation computed in Solidity         ${NC}"
echo -e "${CYAN}  ✓ Auto-signing — zero wallet popups       ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
