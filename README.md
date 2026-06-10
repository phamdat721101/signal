# Kinetic — Card-Summon DeFi on Uniswap v4

> **Swipe a card. Summon a monster. Open a real liquidity position.**
>
> The first product where a non-DeFi user opens a concentrated-liquidity position by performing a card-game gesture.

[![Accuracy](https://img.shields.io/badge/Track%20Record-60.8%25%20across%205%2C816%2B%20predictions-brightgreen)](#track-record)
[![x402](https://img.shields.io/badge/Agent%20API-x402%20Pay--per--call-blue)](https://ai.overguild.com/agent-api/api/v2/agent/decisions)

---

## The Insight

DeFi has a UX cliff. Concentrated liquidity (Uniswap v3/v4) is 10× more capital-efficient than passive pools — but requires users to pick `tickLower`, `tickUpper`, fee tier, and direction. **99% of crypto users never open a v3/v4 LP.**

Meanwhile, trading-card games ship the tightest UX primitive in software: **play a card → effect happens**. One gesture, zero configuration.

Kinetic bridges the gap: **AI-curated cards ARE the LP recipes. The v4 hook enforces the recipe. The user just plays the card.**

---

## How It Works — Three Card Types, One Swipe

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   🃏 CARD FEED (Tinder-style swipe)                                 │
│                                                                     │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│   │ 💎 GEM HUNT  │  │ 🔮 PREDICT   │  │ 🐉 SUMMON LP │            │
│   │              │  │              │  │              │            │
│   │ Hidden gems  │  │ 24h price    │  │ Open a real  │            │
│   │ from Flap +  │  │ prediction   │  │ Uniswap v4   │            │
│   │ DexScreener  │  │ resolved by  │  │ LP position  │            │
│   │              │  │ oracle       │  │ via hook     │            │
│   │ Swipe APE =  │  │ Swipe APE =  │  │ Swipe APE =  │            │
│   │ "I'm early"  │  │ "I'm right"  │  │ "I summon"   │            │
│   └──────────────┘  └──────────────┘  └──────────────┘            │
│                                                                     │
│   Every swipe is an on-chain conviction.                            │
│   Every card resolves. Every outcome is verifiable.                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Card Type 1 — 💎 Gem Hunt (Flap + DexScreener)

AI scans Flap-launched tokens on X Layer + DexScreener trending pairs. Scores by bonding-curve progress, liquidity depth, holder distribution, and momentum. Surfaces as "Gem Cards" in the feed.

**Swipe APE** = "I believe this gem will 3× before it rugs."
**Resolution** = 24h later, price oracle checks. Right → reputation up. Wrong → streak resets.

### Card Type 2 — 🔮 Prediction (AI Multi-Agent Debate)

Three AI agents debate (Technical + Sentiment + Fundamental) using SoSoValue institutional data, ETF flows, macro events, and on-chain metrics. Produces a verdict: APE or FADE, with entry/target/stop.

**Swipe APE** = "I agree with the AI's bullish call."
**Resolution** = 24h later, Slinky oracle resolves. 60.8% accuracy across 5,816+ resolved predictions.

### Card Type 3 — 🐉 Summon LP (Uniswap v4 Hook)

The card's `entry/target/stop` map deterministically to v4 ticks. Swiping APE **opens a real concentrated-liquidity position** on X Layer's Uniswap v4 pool. The hook enforces the recipe. The user earns real swap fees.

**Swipe APE** = "Summon this monster. I earn fees while the price trades in range."
**Resolution** = Card expires in 24h. User can close early or let it ride.

---

## Uniswap v4 — The Hook That Makes Cards Financial

This is the core innovation. Three contracts turn AI signal cards into the **only valid recipe** for opening an LP position:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  SignalCardNFT (ERC-721)                                        │
│  ├── tokenSymbol: "BTC"                                         │
│  ├── stopTickHint: -120    ← pre-computed by AI engine          │
│  ├── targetTickHint: 120   ← maps to v4 tick range             │
│  ├── riskScore: 58         ← drives dynamic fee (30+58 = 88bp) │
│  ├── rarity: Rare          ← visual tier + fee multiplier       │
│  ├── isBull: true          ← APE direction                      │
│  ├── expiresAt: +24h                                            │
│  └── played: false → true  ← flips once on summon              │
│                                                                 │
│  SignalCardHookV2 (Uniswap v4 Hook)                             │
│  ├── beforeAddLiquidity:   enforce card recipe (ticks match)    │
│  ├── beforeRemoveLiquidity: verify card owner                   │
│  ├── beforeSwap:           return dynamic fee = (30+risk)×100   │
│  └── afterSwap:            track swap count per pool            │
│                                                                 │
│  SignalCardRouterV2 (User-facing)                               │
│  └── playCard(cardId) → unlock → modifyLiquidity → settle      │
│      User never sees a tick. Just plays the card.               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Is Novel (vs. every other v4 hook)

| Other hooks | Kinetic |
|---|---|
| Dynamic fee based on volatility | Dynamic fee based on **AI risk score per card** |
| Limit orders (port v3 pattern) | **New asset class**: NFT-as-LP-recipe |
| MEV protection (backend-only) | **Consumer UX**: card-game gesture opens LP |
| TWAMM (prior art, Paradigm 2021) | **Category creation**: Card-Summon DeFi |

The hook doesn't just customize a number — it encodes an entire AI thesis (direction, range, fee, expiry, rarity) into a single user gesture.

### Deployed on X Layer (Real Uniswap v4)

| Contract | Address (testnet 1952) | Explorer |
|---|---|---|
| PoolManager (real v4-core) | `0xD6486d23c8906f30Cc4dF92722E2749E8Ddc1286` | [View ↗](https://www.okx.com/web3/explorer/xlayer-test/address/0xD6486d23c8906f30Cc4dF92722E2749E8Ddc1286) |
| SignalCardNFT | `0xb8482B726001Aa7451A576fF6407593184fEDD96` | [View ↗](https://www.okx.com/web3/explorer/xlayer-test/address/0xb8482B726001Aa7451A576fF6407593184fEDD96) |
| SignalCardHookV2 | `0xa01b3450D9891074d78496133dB8952F17cb0AC0` | [View ↗](https://www.okx.com/web3/explorer/xlayer-test/address/0xa01b3450D9891074d78496133dB8952F17cb0AC0) |
| SignalCardRouterV2 | `0x47b9b7eF7d91F11232f38533e0F00F06b01F8cE5` | [View ↗](https://www.okx.com/web3/explorer/xlayer-test/address/0x47b9b7eF7d91F11232f38533e0F00F06b01F8cE5) |
| MockOKB (test token) | `0xF739a8aFfd096964A899B76F05a15293EDE0d0Ac` | [View ↗](https://www.okx.com/web3/explorer/xlayer-test/address/0xF739a8aFfd096964A899B76F05a15293EDE0d0Ac) |
| MockUSDC (test token) | `0x73BA01a4291aCccfaC2bad7470D6417643Ee9688` | [View ↗](https://www.okx.com/web3/explorer/xlayer-test/address/0x73BA01a4291aCccfaC2bad7470D6417643Ee9688) |
| OKB/USDC Pool | `fee=DYNAMIC, tickSpacing=60, hooks=HookV2` | initialized ✓ |

> **Verify the hook flags:** `python3 -c "print(hex(int('0xa01b3450D9891074d78496133dB8952F17cb0AC0', 16) & 0x3FFF))"` → `0xac0` (BEFORE_ADD_LIQUIDITY | BEFORE_REMOVE_LIQUIDITY | BEFORE_SWAP | AFTER_SWAP)

### Deployed on Somnia (Prediction Cards · v3 cross-chain via LiFi)

The prediction-card mode lives on **Somnia testnet 50312**. The validator-consensus AI verdict (Qwen3-30B subcommittee) runs through `SomniaSignalAgent`, settles into `SomniaCardExecutor`, and commits reputation via `ConvictionEngine`. The v3 cross-chain glue (`PredictionCardLiFiExecutor`) atomically composes "bridge USDC + run AI verdict + bind prophecy market" inside one destination-chain tx.

| Contract | Address (Somnia testnet 50312) | Explorer |
|---|---|---|
| ConvictionEngine | `0x11dd5247E7F1c5349E075BAff3CC37dFF74a56DB` | [View ↗](https://shannon-explorer.somnia.network/address/0x11dd5247E7F1c5349E075BAff3CC37dFF74a56DB) |
| ProofOfAlpha | `0x6a1061dc00B8D636000c2C2e95a28e40c1096A7d` | [View ↗](https://shannon-explorer.somnia.network/address/0x6a1061dc00B8D636000c2C2e95a28e40c1096A7d) |
| SomniaSignalAgent | `0x77C5cA799029991Ac8590BDa998ad1fDc2630426` | [View ↗](https://shannon-explorer.somnia.network/address/0x77C5cA799029991Ac8590BDa998ad1fDc2630426) |
| SomniaOracleAdapter | `0x3DaE79dbc6cbA441d0C67606e607a94Dd2ca2c6E` | [View ↗](https://shannon-explorer.somnia.network/address/0x3DaE79dbc6cbA441d0C67606e607a94Dd2ca2c6E) |
| **SomniaCardExecutor** | `0xF94bEBfC920990E284c28039A5359301578c6640` | [View ↗](https://shannon-explorer.somnia.network/address/0xF94bEBfC920990E284c28039A5359301578c6640) |
| **KineticProphecyBridge** | `0x754C83162976222A70Fc258CAf941aa892F225A9` | [View ↗](https://shannon-explorer.somnia.network/address/0x754C83162976222A70Fc258CAf941aa892F225A9) |
| **PredictionCardLiFiExecutor** | `0x0E97095455E7EC50bdD85C57D844C9610258af32` | [View ↗](https://shannon-explorer.somnia.network/address/0x0E97095455E7EC50bdD85C57D844C9610258af32) |
| MockLiFiCaller (testnet sim) | `0xad264Ed679cC871312e68C1B757D3Ad88414CA9e` | [View ↗](https://shannon-explorer.somnia.network/address/0xad264Ed679cC871312e68C1B757D3Ad88414CA9e) |
| MockUSDC (testnet, 6-dec) | `0x6f16cB586920ef5AF078F26F88C83F1943859152` | [View ↗](https://shannon-explorer.somnia.network/address/0x6f16cB586920ef5AF078F26F88C83F1943859152) |

Single source of truth: [`contracts/deployments/50312.json`](contracts/deployments/50312.json). Deploy + 3 wirings reproducible via `forge script script/06_DeployPredictionCardLiFi.s.sol`.

---

## The 10-Second User Journey

```
0s   Land on /feed → see a BTC card (Rare, 🐉, range 67k→71k)
3s   Swipe right (APE)
5s   "🔮 Summon BTC?" modal → confirm
8s   Wallet signs → tx confirms
10s  "🐉 Summoned! Earning fees while BTC trades 67k–71k."
```

**Zero DeFi vocabulary.** No ticks. No fee tiers. No sqrtPriceX96. Just cards.

---

## Architecture

```
contracts/   Foundry — SignalCardHookV2 + Router + NFT (X Layer v4)
             + SignalRegistry, ConvictionEngine, ProofOfAlpha (Initia EVM)
backend/     Python FastAPI — AI signal engine + card pipeline + x402 agent API
frontend/    Vite + React 19 — Tinder-style swipe + SummonRitual + CardHand
```

### Backend — Card Pipeline (5 stages)

```
Harvest → Analyze → Narrate → Visual → Assemble
   │         │         │         │         │
   ▼         ▼         ▼         ▼         ▼
DexScreener  EMA/RSI   AI copy   Rarity    Feed card
CoinGecko    SoSoValue  engine   + ticks   ready
Flap Portal  Sentiment           + risk
GoPlus       ETF flows
```

### Data Sources

| Source | What it feeds |
|---|---|
| **Flap Portal** (X Layer) | Gem cards — bonding curve progress, tax rate, holder count |
| **DexScreener** | Trending pairs, liquidity depth, volume spikes |
| **SoSoValue** | ETF flows, macro events, sector indices, BTC treasuries |
| **CoinGecko** | OHLC prices, market caps |
| **CryptoPanic** | News sentiment |
| **Slinky Oracle** | On-chain price resolution (Initia) |

---

## Track Record

| Metric | Value | Verifier |
|---|---|---|
| Resolved predictions | **5,816+** | `cast call ConvictionEngine.getConvictionCount()` on Initia evm-1 |
| Accuracy | **60.8%** | resolved-correct / resolved-total |
| Active swipes | **1,025+** | `signal_swipes` table |
| Paid x402 routes | **8** | `GET /agent-api/api/v2/agent/decisions` → 402 |
| Cards generated | **20,076+** | `cards` table |

---

## AI Agent API (x402 Pay-per-Request)

AI agents pay USDC per call. No API keys. No accounts.

```bash
# Hit the endpoint → get a 402 challenge
curl -i https://ai.overguild.com/agent-api/api/v2/agent/decisions

# Sign payment → get signals
curl -H "x-payment: <signed-payload>" \
     https://ai.overguild.com/agent-api/api/v2/agent/decisions
# → { decisions: [{ token: "BTC", action: "APE", confidence: 85, ... }] }
```

| Endpoint | Price | What |
|---|---|---|
| `/decisions` | $0.001 | APE/FADE verdicts + entry/target/stop |
| `/prices` | $0.001 | Aggregated prices |
| `/pools` | $0.005 | DeFi LP advisory |
| `/track-record` | $0.01 | Historical accuracy |
| `/context` | $0.01 | ETF flows, macro, sector rotation |

---

## Quick Start

```bash
# Full stack (one command)
./start.sh    # Backend :8001 + Frontend :5173

# Contracts only
cd contracts && forge build --via-ir && forge test --via-ir

# Deploy to X Layer testnet (real Uniswap v4)
cd contracts
PRIVATE_KEY=0x… \
MOCK_OKB=0xF739a8aFfd096964A899B76F05a15293EDE0d0Ac \
MOCK_USDC=0x73BA01a4291aCccfaC2bad7470D6417643Ee9688 \
forge script script/04_DeployRealV4.s.sol --rpc-url xlayer_testnet --broadcast --via-ir

# Sync env files from deployment JSON (single source of truth)
node scripts/sync-deployments.mjs
```

### Prediction-card mode (Prophecy.social on Somnia)

A 4th feed mode — 🔮 Predictions — reads Prophecy.social markets from Somnia
mainnet 5031 and lets users APE/FADE on Somnia testnet 50312 (paper PST).
Read-everywhere, write-Somnia: the deck renders on any chain; the chain
switch fires only on a deliberate swipe.

#### How a prediction card flows end-to-end

```
┌─ Somnia mainnet 5031 ──────────────────────────────────────────────┐
│ Prophecy.social MarketCreated / MarketResolved events              │
└──────┬─────────────────────────────────────────────────────────────┘
       │ (1) read-only RPC view + HTTP fallback (15-min cache)
       ▼
┌─ backend/app/prophecy_social_reader.py ────────────────────────────┐
│ Typed `ProphecyMarket` dataclasses · graceful degrade to HTTP      │
│ when RPC is unhappy · IPFS-resolved metadata for question text     │
└──────┬─────────────────────────────────────────────────────────────┘
       │ (2) APScheduler tick (every 5 min)
       ▼
┌─ backend/app/prophecy_card_pipeline.py ────────────────────────────┐
│ Filters: open + deadline > 15 min + question ≤ 280 chars           │
│ Synthesizes verdict (v1: deterministic crowd-follow heuristic)     │
│ Inserts `cards` row · UNIQUE (prophecy_market_id) → idempotent     │
└──────┬─────────────────────────────────────────────────────────────┘
       │ (3) bind market_id → cardHash on Somnia testnet 50312
       ▼
┌─ KineticProphecyBridge.bindMarketToCard ───────────────────────────┐
│ Authorized binders only · `cardHash = keccak256(cardId, marketId)` │
└──────┬─────────────────────────────────────────────────────────────┘
       │ (4) frontend Feed.tsx renders the prophecy card
       ▼
┌─ User swipes APE on `/?mode=prediction` ───────────────────────────┐
│ Wallet signs `ConvictionEngine.commitConviction(cardHash, 75, true)│
│ Tx hash + chain_id persisted in `swipes` table                     │
└──────┬─────────────────────────────────────────────────────────────┘
       │ (5) Prophecy market resolves on mainnet 5031 (24h-7d later)
       ▼
┌─ backend/app/prophecy_event_poller.py ─────────────────────────────┐
│ Sees `MarketResolved` → `KineticProphecyBridge.triggerResolution`  │
│ → `ConvictionEngine.resolveCard` → reputation updates for every    │
│ APE/FADE swiper · `lifi_intents.outcome_correct` filled for v3 rows│
└────────────────────────────────────────────────────────────────────┘
```

| Data point | Source |
|---|---|
| `prophecy_market_id`, deadline, YES/NO odds at gen | `ProphecyMarket` struct on mainnet 5031 (`prophecy_market_address`) |
| Market question text + image | IPFS metadata (3 gateway fallbacks) |
| Open-markets list | `ProphecyMarket.openMarkets()` view, 15-min in-process cache |
| Resolution outcome | `MarketResolved` event log scan, last 5,000 mainnet blocks |
| Settlement on Somnia testnet | `KineticProphecyBridge.triggerResolution` → `ConvictionEngine.resolveCard` |
| Cross-chain swipe outcome | `mark_lifi_intents_outcome_for_market` propagates per-intent rows |

```bash
# 1. Verify Prophecy.social contract addresses on browser.somnia.network
#    and populate backend/.env: PROPHECY_MARKET_ADDRESS, PROPHECY_PST_TOKEN_ADDRESS

# 2. Deploy the testnet bridge (assumes SOMNIA_CONVICTION_ENGINE_ADDRESS exists):
bash deploy-somnia-prophecy.sh

# 3. Restart backend; the prophecy_card_gen + prophecy_relay scheduler
#    jobs come up automatically via the kill-switch flip.
bash restart_signal.sh
```

Full architecture, env vars, and module map: see `product_context.md` §15.

### Cross-chain prediction-card (v3 · LiFi · Arbitrum → Somnia)

A 5th surface at **`/somnia/prediction`** lets a user holding USDC on Arbitrum
Sepolia (or mainnet, post-promotion) swipe a prophecy card with **one signature**.
The bet binds atomically on Somnia — bridge + verdict + prophecy-market binding
all happen inside a single `executeFromLiFi` transaction.

Every successful swipe persists three click-through proof URLs (Arbiscan +
Somnscan + prophecy market) so a Somnia core-team reviewer can verify the
entire flow on-chain without any local setup.

```bash
# 1. Deploy executor + (testnet) MockUSDC + MockLiFiCaller + 3 wirings:
cd contracts
PRIVATE_KEY=0x… SOMNIA_CARD_EXECUTOR=0x… KINETIC_PROPHECY_BRIDGE=0x… \
KINETIC_NETWORK=testnet \
forge script script/06_DeployPredictionCardLiFi.s.sol \
    --rpc-url https://api.infra.testnet.somnia.network --broadcast --via-ir

# 2. Backend env: LIFI_QUOTE_ENABLED=true, LIFI_RELAY_ENABLED=true,
#    PREDICTION_CARD_LIFI_EXECUTOR_ADDRESS=…, SOMNIA_USDC_ADDRESS=…

# 3. Frontend env: VITE_KINETIC_NETWORK=testnet, VITE_SOMNIA_USDC_ADDRESS=…

# 4. Restart and open https://ai.overguild.com/somnia/prediction
bash restart_signal.sh
```

Full reviewer playbook + mainnet-promotion gate:
[`docs/PRDs/v3-cross-chain-prediction-card/SMOKE-TESTNET.md`](docs/PRDs/v3-cross-chain-prediction-card/SMOKE-TESTNET.md).

---

## Why This Wins (Gstack)

| Layer | What Kinetic has |
|---|---|
| **Insight** | "Cards ARE LP recipes" — a non-DeFi user opens concentrated liquidity via a card-game gesture. Nobody else ships this. |
| **Mechanism** | Real Uniswap v4 hook on X Layer enforcing card recipes. 4 callbacks (add/remove/beforeSwap/afterSwap). Dynamic fee from AI risk score. |
| **Distribution** | 5,816 resolved predictions as social proof. x402 Bazaar auto-indexed. OKX Wallet + Flap ecosystem reach. |
| **Moat** | 12 months of prediction data no competitor can replicate. ConvictionEngine reputation primitive. Multi-rail agent payments (Base + Arbitrum Sepolia + X Layer). |

---

## Tech Stack

| Layer | Stack |
|---|---|
| Hook contracts | Solidity 0.8.26, Foundry, Uniswap v4-core, OpenZeppelin |
| Backend | Python 3.11+, FastAPI, APScheduler, web3.py, stellar-sdk |
| Frontend | React 19, TypeScript, Vite, TailwindCSS v4 |
| Wallet | OKX Wallet / MetaMask (X Layer) + InterwovenKit (Initia) |
| AI | AWS Bedrock (Nova Lite), multi-agent debate |
| Agent payments | x402 (USDC on Base + Arbitrum Sepolia) |
| Database | PostgreSQL (Supabase) |

---

## Deployment

| Service | URL |
|---|---|
| Live app | `https://ai.overguild.com` |
| Agent API (x402) | `https://ai.overguild.com/agent-api/api/v2/agent/*` |
| X Layer Explorer | `https://www.okx.com/web3/explorer/xlayer-test` |
| Contracts (testnet 1952) | See `contracts/deployments/1952.json` |

---

## License

MIT
