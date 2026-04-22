# Ape or Fade — Product Context & Architecture

Primary context document for AI agents and developers. Updated 2026-04-22.

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
| RewardEngine.sol | Win streak tracking, 3% rebate, streak bonus. | Deployed, wired via scheduler |
| ProofOfAlpha.sol | Soulbound ERC-721 achievement NFTs. 5 tiers. | Deployed, wired via scheduler |

### 2.2 Backend Modules

| Module | Role |
|--------|------|
| main.py | FastAPI app. 30+ endpoints: Card/Signal/Rewards/Payment/Provider/Profile APIs |
| config.py | Pydantic Settings. Network switching (local/testnet). AWS Bedrock + chain + Supabase config |
| content_engine.py | 5-stage card pipeline: harvest (CoinGecko) → analyze (anomaly signals) → narrate (Claude Bedrock + template fallback) → visual (SVG generation) → assemble + store |
| signal_engine.py | EMA(5)/EMA(10) crossover + RSI(14) signal generation. Dynamic asset registry. Multi-timeframe. CoinGecko/Oracle prices. Simulation + on-chain dual-write |
| db.py | Supabase/Postgres. 5 tables: signals, cards, swipes, trades, daily_swipes |
| chain.py | web3.py wrapper. POA middleware. gasPrice=0 |
| scheduler.py | APScheduler: card_gen(5m), position_monitor(5m), signal_cycle(3x/day @8,14,20h), resolve(23:55), expire_cards(10m), backfill_charts(30m) |
| mpp_middleware.py | MPP payment verification via ServicePaid event parsing |
| agent_client.py | Reference SDK for AI agents with session voucher signing |
| error_tracker.py | In-memory error tracking with code-based aggregation |

### 2.3 Frontend

6 pages: Feed, Portfolio, Leaderboard, History, Profile, TradeSuccess
5 components: TokenCard, Layout, BridgePrompt, Onboarding, Paywall
7 hooks: useCards, useSignals, useSignalActions, usePrices, useIUSDBalance, useSession, useApeTransaction

### 2.4 Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Backend health + chain status |
| GET | `/api/signals` | All signals (paginated, filterable by provider) |
| GET | `/api/cards` | Active card feed with expiry filtering |
| POST | `/api/cards/{id}/ape` | Ape action: record trade + swipe + daily limit |
| POST | `/api/cards/{id}/fade` | Fade action: record swipe + daily limit |
| POST | `/api/signals/generate` | Trigger signal cycle (configurable assets/timeframe/target%) |
| POST | `/api/cards/generate` | Trigger card generation pipeline |
| GET | `/api/leaderboard` | PnL-ranked leaderboard with .init username resolution |
| GET | `/api/profile/{address}` | Aggregated profile: rewards + achievements + trades + trading IQ |
| POST | `/api/provider/signals` | External provider signal submission |
| GET | `/api/metrics` | Appchain metrics (signals, cards, swipes, trades, unique users) |
| GET | `/api/report` | Performance report with per-asset breakdown |

## 3. Database (Supabase/Postgres)

- **signals**: id, asset, symbol, is_bull, confidence, target/entry/exit_price, timestamp, resolved, creator, provider, pattern, analysis
- **cards**: id, token_symbol, token_name, hook, roast, metrics (JSONB), verdict, risk_level, risk_score, image_url, price, price_change_24h, volume_24h, market_cap, sparkline (JSONB), patterns (JSONB), expires_at
- **swipes**: id, card_id, user_address, action, created_at
- **trades**: id, card_id, user_address, token_symbol, entry_price, amount_usd, token_amount, tx_hash, exit_price, pnl_usd, pnl_pct, resolved
- **daily_swipes**: id, user_address, swipe_date, count (premium gate: 5 free/day)

## 4. Content Engine Pipeline (5 stages)

1. **Harvest**: CoinGecko markets API → top 15 tokens by volume
2. **Analyze**: Anomaly signal detection (volume spikes, price momentum, buy/sell imbalance, supply concentration, mcap ratio) → risk score 0-100
3. **Chart Analysis**: CoinGecko market_chart → EMA crossover, breakout, higher/lower highs, consolidation, support test patterns + sparkline
4. **Narrate**: Claude Bedrock (Haiku) → sarcastic Gen-Z hook + roast + 3 metrics; template fallback on failure
5. **Assemble + Quality Gates**: Merge all data, validate (hook ≤80 chars, 3 metrics, valid verdict, volume ≥$5K), store in Supabase

## 5. Working Features (2026-04-22)

- Card generation pipeline (CoinGecko → analyze → Claude/template → chart patterns → Supabase)
- Swipe UX (ape/fade with wallet integration + daily limit gating)
- Trade execution with PnL tracking (auto-resolve after 24h)
- Leaderboard (PnL-ranked with .init username resolution)
- Portfolio with trade history
- Profile with Trading IQ score
- Signal engine (EMA/RSI → dual-write: simulation + Supabase)
- Rewards/achievements (computed from trades, wired to RewardEngine contract on resolution)
- Payment verification middleware (MPP)
- Card SVG generation for sharing
- Card expiry enforcement (4h TTL)
- Chart pattern detection + sparkline data
- External provider signal API
- MockIUSD faucet + Privy wallet

## 6. Deployment

- **Backend**: FastAPI on VPS (bitnami@13.212.80.72) via deploy-vps.sh — port 8000
- **Frontend**: Vite build, static hosting or dev server — port 5173
- **SSH Key**: nim-claw.pem
- **API URL**: http://13.212.80.72:8000
- **Frontend env**: VITE_BACKEND_URL=http://13.212.80.72:8000

---
*Updated 2026-04-22 — Full codebase analysis with deployment context.*
