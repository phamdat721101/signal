# Ape or Fade — Product Context & Architecture

Primary context document for AI agents and developers.

## 1. Product Overview

**Ape or Fade** (KINETIC) is a mobile-first, TikTok-style token discovery app on Initia EVM appchain. Users swipe through AI-generated token cards — swipe right to **Ape** (buy), swipe left to **Fade** (skip). Cards feature sarcastic/hype summaries from live CoinGecko data, powered by Claude AI (Bedrock) with template fallback.

Design System: "The Kinetic Terminal" — #0e0e0e void bg, #8eff71 green (Ape), #ff7166 red (Fade), #bf81ff purple (AI). Space Grotesk + Inter fonts.

## 2. Architecture

```
contracts/   → Foundry Solidity — 4 smart contracts (Initia EVM)
backend/     → Python FastAPI — AI content engine + signal engine + REST API
frontend/    → Vite + React 19 + TailwindCSS v4 — Kinetic Terminal UI
signal-ui/   → 11 HTML mockups — design reference
```

### 2.1 Backend Modules

| Module | Role |
|--------|------|
| `content_engine.py` | CoinGecko trending → Claude (Bedrock) with template fallback → card JSON → Supabase |
| `signal_engine.py` | Legacy EMA/RSI signal generation + CoinGecko/Oracle prices |
| `db.py` | 3 tables: `cards`, `swipes`, `signals`. Full CRUD. |
| `scheduler.py` | Card gen every 5min + signal cycle 3x/day + EOD resolve |
| `config.py` | Pydantic Settings. AWS Bedrock + Initia chain + Supabase config |
| `chain.py` | web3.py wrapper for Initia EVM |
| `main.py` | FastAPI app with card API + legacy signal API |

### 2.2 Content Engine Strategy
1. **Primary**: Claude AI via AWS Bedrock — sarcastic, personalized card content
2. **Fallback**: Template-based generation — uses CoinGecko data to create cards with randomized sarcastic hooks/roasts when Bedrock is unavailable (IAM permissions, quota, etc.)
3. Cards always get created — the feed never runs dry

### 2.3 API Endpoints

**Card API**: `GET /api/cards` · `GET /api/cards/{id}` · `POST /api/cards/{id}/ape` · `POST /api/cards/{id}/fade` · `GET /api/cards/user/{address}` · `GET /api/leaderboard` · `POST /api/cards/generate`

**Legacy**: `/api/signals` · `/api/prices` · `/api/report` · `/api/health`

### 2.4 Frontend

**Pages**: Feed (`/`), Portfolio (`/portfolio`), Leaderboard (`/leaderboard`), History (`/history`), TradeSuccess (`/trade-success/:id`)

**Components**: Layout (KINETIC header + bottom nav), TokenCard (swipe card)

**Hooks**: useCards, useSignals, useSignalActions, usePrices, useIUSDBalance, useSession

## 3. Database (Supabase/Postgres)

**cards**: id, token_symbol, token_name, chain, hook, roast, metrics JSONB, image_url, price, price_change_24h, volume_24h, market_cap, coingecko_id, status, created_at

**swipes**: id, card_id, user_address, action ('ape'|'fade'), created_at

**signals**: id, asset, symbol, is_bull, confidence, target/entry/exit_price, timestamp, resolved, creator, provider, pattern, analysis

## 4. Deployment

| Service | URL | Port |
|---------|-----|------|
| VPS Backend API | `https://13-212-80-72.sslip.io/signal-api` | 8001 (Caddy proxy) |
| Local Backend | `http://localhost:8000` | 8000 |
| Local Frontend | `http://localhost:5173` | 5173 |

**VPS**: Lightsail instance. Caddy reverse proxy at `/signal-api/*` → `localhost:8001`. Backend at `~/signal/backend/`. SSH: `ssh -i nim-claw.pem bitnami@13.212.80.72` (key at `/Users/phamdat/arbitrum/arbi-agent/nim-claw.pem`).

**Frontend .env**: `VITE_BACKEND_URL=https://13-212-80-72.sslip.io/signal-api`

## 5. Environment Variables

**Backend** (`backend/.env`): NETWORK, PRIVATE_KEY, CONTRACT_ADDRESS, DATABASE_URL, AWS_REGION, AWS_BEDROCK_MODEL_ID, SESSION_VAULT_ADDRESS, MOCK_IUSD_ADDRESS, PAYMENT_GATEWAY_ADDRESS

**Frontend** (`frontend/.env`): VITE_NETWORK, VITE_CONTRACT_ADDRESS, VITE_CHAIN_ID, VITE_BACKEND_URL, VITE_COSMOS_RPC_URL, VITE_REST_URL

---
*Updated 2026-04-15 — VPS deployed with fallback content engine. Cards generating via template when Bedrock unavailable.*

---

## 8. On-Chain Feature Upgrade (from Notion "on-chain feature" sub-page)

### Part 1 — Target Smart Contract Architecture (4 contracts)

| Contract | Purpose | Status |
|----------|---------|--------|
| `ApeVault.sol` | USDC custody, ZK-verified trade execution, 24h withdrawal timelock, per-user sub-accounts | **NEW** — replaces simple pool |
| `SignalRegistry.sol` | On-chain signal mapping with `TokenSignal` struct (token, sentiment, confidence, dataHash→IPFS, resolved, wasCorrect). AI agent publishes BEFORE surfacing card. Oracle resolves 24h later. | **UPGRADE** — existing contract needs new struct |
| `RewardEngine.sol` | Streak detection, win rebates (3% USDC), weekly prize pool. Listens to ApeVault + SignalRegistry events. Rewards tracked by `proofHash` not wallet (privacy). | **NEW** |
| `ProofOfAlpha.sol` | Soulbound ERC-5192 achievement NFTs. ZK-verified stats. Tiers: Bronze/Silver/Gold/Diamond/Signal Sage. Non-transferable. | **NEW** |
| `AccessController.sol` | Role management: AI Agent, Relayer, Oracle, Keeper | **NEW** |

### Part 2 — x402 Agent Payment Architecture (5 flows)

| Flow | What | Price | Pattern |
|------|------|-------|---------|
| A: Per-Card Fee | $0.05 USDC per card served | Micro | x402 per-request, invisible background payment |
| B: Deep Analysis | $0.25 USDC per AI drill-down | Micro | x402 per-request on `POST /analyze` |
| C: Premium Tier | $9.99 USDC/month subscription | Subscription | x402 payment → JWT (30-day pass) → skip micro-charges |
| D: Agent Deposit | $X USDC to fund AI agent wallet | Agent-to-agent | User deposits "Agent Fuel" → AI agent auto-pays for premium data sources |
| E: Signal API | $0.10 USDC per signal query | B2B | Third-party bots/apps pay for signal history |

**Key concepts**:
- x402 V2 on Base mainnet (production-ready, 75M+ transactions)
- `@x402/express` middleware wraps endpoints
- `HTTPFacilitatorClient` → `https://x402.org/facilitator`
- Premium JWT: payment IS the authorization (no subscription DB needed)
- Agent Fuel: separate balance from trading pool, AI agent has autonomous wallet (CDP AgentKit + x402 client)
- If Agent Fuel = $0, falls back to free-tier data sources

### Full Integrated Flow (Target)
```
User opens app → wallet checks: Trading Pool ($85), Agent Fuel ($6.40), Premium (22d left)
→ Feed loads (no charge, Premium JWT) → AI agent polls DexScreener Premium (auto-pays $0.001)
→ AI publishes signal on-chain (SignalRegistry) → generates card → Supabase
→ User swipes right ($50 trade) → ZK Proof → Relayer → 1inch swap → ApeVault emits TradeExecuted
→ 24h later: Oracle resolves signal → RewardEngine triggers rebate
→ Win streak hit 5 → ProofOfAlpha mints Silver Ape badge (Soulbound)
```

### Implementation Modules (from Notion)
1. **Smart Contract Deployment**: ApeVault, SignalRegistry, RewardEngine, ProofOfAlpha, AccessController (Hardhat + OpenZeppelin + Chainlink + Base Sepolia)
2. **x402 Payment Middleware**: @x402/express wrapping /feed, /analyze, /signals + Premium JWT issuer + Agent Fuel sub-account + CDP AgentKit
3. **Signal Oracle Integration**: Chainlink Automation (24h resolution) + IPFS uploader + accuracy dashboard
4. **Reward & NFT Claim Flow**: Event listener → RewardEngine → ZK achievement circuit (Noir) → Soulbound NFT mint

### What Exists vs What's Needed

| Feature | Current State | Notion Target |
|---------|--------------|---------------|
| Signal on-chain | ✅ SignalRegistry.sol (basic) | Upgrade: add TokenSignal struct, dataHash→IPFS, wasCorrect |
| Payment sessions | ✅ SessionVault.sol (MPP) | Replace with x402 V2 + ApeVault.sol |
| Rewards | ❌ None | NEW: RewardEngine.sol (streaks, rebates, weekly pool) |
| Achievement NFTs | ❌ None | NEW: ProofOfAlpha.sol (Soulbound ERC-5192) |
| Agent payments | ✅ agent_client.py (basic vouchers) | Upgrade: CDP AgentKit + x402 autonomous wallet |
| Micro-payments | ✅ MPP middleware | Replace with @x402/express middleware |
| Premium tier | ❌ None | NEW: x402 subscription → JWT pass |

---
*Updated 2026-04-15 — Added on-chain feature upgrade spec and x402 agent payment architecture from Notion.*

---

## 9. Card Generation Pipeline (from Notion "card generate" sub-page)

### Overview
5-stage multi-agent pipeline. Each stage is a specialized agent with one job. Runs every 5 minutes, processes ~20 tokens in parallel. If any stage fails, card ships with fallback.

### Pipeline Stages

```
[Stage 1] DATA HARVESTER → Raw on-chain JSON (DexScreener + GeckoTerminal + RPC)
[Stage 2] SIGNAL ANALYZER → Scored anomaly signals (volume, whale, liquidity, dev)
[Stage 3] NARRATIVE WRITER (LLM) → Structured card JSON (hook, roast, verdict, metrics)
[Stage 4] VISUAL GENERATOR (Image AI) → Token card image (meme aesthetic)
[Stage 5] CARD ASSEMBLER → Final card → on-chain signal anchor → Supabase → Feed API
```

### Stage 1 — Data Harvester
3 parallel data sources: DexScreener API (price, volume, txCount, liquidity), GeckoTerminal (holders, top10 concentration, whale activity), Base RPC (contract age, dev wallet, supply).

### Stage 2 — Signal Analyzer (pure logic, no LLM)
11 signal types detected: VOLUME_SPIKE, WHALE_ENTRY, LIQUIDITY_LOCK, LIQUIDITY_RUG_RISK, DEV_WALLET_LOCKED, DEV_WALLET_ACTIVE, NEW_TOKEN, HOLDER_CONCENTRATION, BUY_SELL_IMBALANCE, PRICE_MOMENTUM, MCAP_TO_VOLUME_RATIO.

Each signal has: type, severity (1-5), direction (bullish/bearish/neutral), rawFinding, emoji.

Risk score: base 50, +5 per bearish severity, -3 per bullish severity, clamped 0-100.

### Stage 3 — Narrative Writer (LLM)
Uses structured outputs (guaranteed valid JSON). Output schema:
- `hook`: 1 punchy sentence, max 12 words (scroll-stopper)
- `roast`: 1-2 sarcastic sentences (the meat)
- `verdict`: "APE" | "FADE" | "DYOR"
- `verdictReason`: 1 sentence explaining verdict
- `metrics`: exactly 3 MetricBullet objects (emoji, label, value, sentiment)
- `riskLevel`: "DEGEN" | "MID" | "SAFE"
- `imagePrompt`: visual generation prompt
- `notificationHook`: push notification if token pumps (max 15 words, should sting)

Tone: Gen-Z, sharp, irreverent. Like a hedge fund analyst who grew up on 4chan.

Key principle: **LLM's job is NOT analysis** — that's Stage 2's job. LLM only makes raw signals *entertaining*.

### Stage 4 — Visual Generator
DALL·E 3 or Stable Diffusion XL. 9:16 vertical (mobile card format). Color coding: APE=green neon, FADE=red warning, DYOR=amber fog. Risk modifiers: DEGEN=chaotic/explosive, MID=urban street art, SAFE=clean/minimal. No text in images. Pin to IPFS.

### Stage 5 — Card Assembler
1. Pin raw data to IPFS (for on-chain anchoring)
2. Publish signal to SignalRegistry.sol (on-chain timestamped BEFORE users see card)
3. Assemble final TokenCard object
4. Store in Supabase
5. Cards expire after 4 hours

### Quality Gates
Before entering feed: hook ≤80 chars, exactly 3 metrics, valid verdict, image stored on IPFS, on-chain anchor exists, liquidity ≥$5K, market cap ≤$50M.

### Performance Targets
- Stage 1 (Harvest): <500ms per token
- Stage 2 (Analyze): <50ms (pure logic)
- Stage 3 (Narrative): <2s (LLM call)
- Stage 4 (Image): <8s (parallel with Stage 3)
- Stage 5 (Assemble): <1s
- Total per card: <3s (Stages 3+4 parallel)
- Pipeline cycle: 20 cards in <30s

### Current Implementation vs Target

| Feature | Current State | Notion Target |
|---------|--------------|---------------|
| Data source | CoinGecko markets API | DexScreener + GeckoTerminal + Base RPC (3 parallel) |
| Signal analysis | None (raw price data only) | 11 signal types with severity scoring |
| LLM | Claude (Bedrock) with template fallback | Structured outputs (guaranteed JSON schema) |
| Card schema | Basic (hook, roast, metrics) | Full TokenCard with verdict, riskLevel, notificationHook |
| Image generation | CoinGecko token logo (fallback) | DALL·E 3 / SDXL with verdict-based color coding |
| On-chain anchoring | Not yet | SignalRegistry.publishSignal() with dataHash→IPFS |
| Quality gates | None | 7 automated checks before feed entry |
| Card expiry | None | 4-hour TTL |
| Parallelism | Sequential | 20 concurrent tokens, Stages 3+4 parallel |

---
*Updated 2026-04-15 — Added card generation pipeline spec from Notion "card generate" sub-page.*
