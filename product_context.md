# Ape or Fade — Product Context & Architecture

Primary context document for AI agents and developers. Updated 2026-04-21.

## 1. Product Overview

**Ape or Fade** (KINETIC) is a mobile-first, TikTok-style token discovery app on Initia EVM appchain. Users swipe through AI-generated token cards — swipe right to **Ape** (buy), swipe left to **Fade** (skip). Cards feature sarcastic/hype summaries from live CoinGecko data, powered by Claude AI (Bedrock) with template fallback.

Design System: The Kinetic Terminal — #0e0e0e void bg, #8eff71 green (Ape), #ff7166 red (Fade), #bf81ff purple (AI). Space Grotesk + Inter fonts.

## 2. Architecture

| Layer | Stack | Description |
|-------|-------|-------------|
| contracts/ | Foundry Solidity | 6 smart contracts on Initia EVM |
| backend/ | Python FastAPI | AI content engine + signal engine + REST API |
| frontend/ | Vite + React 19 + TailwindCSS v4 | Kinetic Terminal UI |

### 2.1 Smart Contracts (6 deployed)

| Contract | Purpose | Status |
|----------|---------|--------|
| SignalRegistry.sol | On-chain signal storage with dataHash + wasCorrect. publishSignal() for authorized agents. | Working |
| SessionVault.sol | iUSD deposit sessions with voucher micropayments. | Deployed, partially integrated |
| SignalPaymentGateway.sol | Access record logging for signal API payments. | Deployed, not integrated |
| MockIUSD.sol | ERC20 test token with faucet. Initia ERC20Registry precompile. | Working |
| RewardEngine.sol | Win streak tracking, 3% rebate, streak bonus. | Deployed, NOT wired |
| ProofOfAlpha.sol | Soulbound ERC-721 achievement NFTs. 5 tiers. | Deployed, NOT wired |

### 2.2 Backend Modules

| Module | Role |
|--------|------|
| main.py | FastAPI app. 30+ endpoints across Card/Signal/Rewards/Payment/Provider APIs |
| config.py | Pydantic Settings. Network switching. AWS Bedrock + chain + Supabase config |
| content_engine.py | 5-stage card pipeline: harvest, analyze, narrate, visual, assemble+store |
| signal_engine.py | EMA crossover + RSI signal generation. CoinGecko/Oracle prices |
| db.py | Supabase/Postgres. 3 tables: signals, cards, swipes |
| chain.py | web3.py wrapper. POA middleware. gasPrice=0 |
| scheduler.py | APScheduler: card gen (5min), signal cycle (3x/day), EOD resolve |
| mpp_middleware.py | MPP payment verification via ServicePaid event parsing |

### 2.3 Frontend

5 pages: Feed, Portfolio, Leaderboard, History, TradeSuccess
2 components: TokenCard, Layout
6 hooks: useCards, useSignals, useSignalActions, usePrices, useIUSDBalance, useSession

## 3. Database (Supabase/Postgres)

- **signals**: id, asset, symbol, is_bull, confidence, target/entry/exit_price, timestamp, resolved, creator, provider, pattern, analysis
- **cards**: id, token_symbol, token_name, hook, roast, metrics (JSONB), image_url, price, price_change_24h, volume_24h, market_cap, verdict, risk_level, risk_score, signals (JSONB), expires_at
- **swipes**: id, card_id, user_address, action, created_at

## 4. Gap Analysis (2026-04-21)

### Working End-to-End
- Card generation pipeline (CoinGecko -> analyze -> Claude/template -> Supabase)
- Swipe UX (ape/fade with wallet integration)
- Leaderboard, Portfolio, History pages
- Legacy signal engine (EMA/RSI -> on-chain or simulation)
- Rewards/achievements API (computed from swipes, not on-chain)
- Payment verification middleware (MPP)
- MockIUSD faucet + InterwovenKit wallet + auto-signing

### Deployed but NOT Wired
- RewardEngine: onTradeResolved() never called from backend
- ProofOfAlpha: mintAchievement() never called from backend
- SignalPaymentGateway: not integrated into card flow
- SessionVault: frontend hooks exist but unused in card/swipe flow
- publishSignal(): content_engine never calls it (dataHash always bytes32(0))

### Major Gaps vs Notion Target
1. No ApeVault (trade execution contract)
2. No x402 payments (uses custom MPP instead)
3. No IPFS anchoring (dataHash always bytes32(0))
4. No image generation (CoinGecko logos only)
5. No quality gates enforcement
6. No card expiry filtering
7. No on-chain signal publishing from content_engine
8. No growth loops or referral system

### Priority for On-Chain Local Rollup
1. Wire content_engine -> SignalRegistry.publishSignal()
2. Wire swipe ape -> RewardEngine.onTradeResolved()
3. Wire achievements -> ProofOfAlpha.mintAchievement()
4. Enforce card expiry in get_cards()
5. Add quality gates before card insertion
6. Wire SessionVault into card access flow

---
*Updated 2026-04-21 — Full codebase analysis with gap analysis and on-chain integration priorities.*
