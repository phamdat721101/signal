# Initia Signal (Ape or Fade)

Open-source AI-powered on-chain trading signal kit with **escrow-backed accountability** — pay for signals via escrow, get refunded if wrong.

Generate market signals from real price data, store them immutably on-chain, execute with one-click auto-signing, and access premium intelligence reports through Trustless Work escrow.

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Price Feeds (Slinky Oracle / CoinGecko OHLC)       │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  AI Signal Engine (Python)                           │
│  • Multi-agent debate (Technical + Sentiment + Fund) │
│  • EMA/RSI crossover + SoSoValue institutional data  │
│  • Confidence scoring + risk assessment              │
│  • Runs every 10 minutes via scheduler               │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  SignalRegistry Contract (Solidity / EVM)             │
│  • createSignal() — anyone can create                │
│  • resolveSignal() — owner resolves with exit price  │
│  • On-chain: asset, direction, confidence, prices    │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  Signal Marketplace (Trustless Work / Chain)        │
│  • Pay USDC to escrow → access premium signals       │
│  • Signal correct → provider paid automatically      │
│  • Signal wrong → user refunded automatically        │
│  • Premium reports via escrow-gated access           │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  Frontend (React + Privy + Freighter)                │
│  • Tinder-style swipe cards (APE / FADE)             │
│  • One-click execute via auto-signing                │
│  • Premium report pop-up with market intelligence    │
│  • Portfolio P&L + Trader Leaderboard                │
└──────────────────────────────────────────────────────┘
```

---

## Signal Marketplace — Escrow-Backed Premium Access

### The Problem

AI trading signals have zero accountability. Providers collect fees upfront and face no consequences when wrong. Users have no refund mechanism.

### The Solution

**Kinetic Signal Marketplace** uses [Trustless Work](https://trustlesswork.com) escrow on Stellar to create an **accountability layer**:

- Users pay USDC into an escrow to access premium signals
- Funds are only released to the provider if the signal is profitable
- If the signal fails, the user gets an automatic refund
- All outcomes are verifiable on-chain

### How Escrow Payment Works

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  1. USER browses Signal Marketplace                             │
│     └── Sees providers with win rates, avg PnL, track record   │
│                                                                 │
│  2. USER clicks "Back Signal — $5 USDC"                         │
│     └── Backend deploys escrow (platform signs server-side)     │
│     └── Escrow contract created on Stellar testnet              │
│     └── tx_hash returned → clickable Stellar Explorer link      │
│                                                                 │
│  3. USER funds escrow with Freighter wallet                     │
│     └── USDC locked in non-custodial Stellar escrow             │
│     └── Signal details unlocked (entry, target, stop, analysis) │
│                                                                 │
│  4. 24 HOURS PASS — Auto-resolution                             │
│     └── Backend fetches current price                           │
│     └── Compares to entry price + direction                     │
│                                                                 │
│  5a. SIGNAL CORRECT → Provider paid (90%), platform fee (10%)   │
│  5b. SIGNAL WRONG → User refunded automatically                 │
│                                                                 │
│  6. DISPUTE (optional) → Admin reviews and resolves             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Premium Intelligence Reports

Beyond individual signals, users can purchase **AI-generated market reports** via escrow:

| Report Type | Price | What You Get |
|-------------|-------|-------------|
| 🌐 Market Overview | $2 USDC | Top 5 signals, ETF flows, sentiment scores, macro events |
| 🔬 Token Deep Dive | $5 USDC | Multi-agent debate analysis on specific token |
| 💼 Portfolio Advisory | $10 USDC | Personalized allocation + risk assessment |

**Report Purchase Flow:**

```
User clicks "$2 Market Overview"
    │
    ├── 1. Backend deploys escrow on Stellar (platform signs)
    │      → Returns tx_hash + Stellar Explorer link ✓
    │
    ├── 2. User signs fund transaction with Freighter
    │      → USDC locked in escrow ✓
    │
    └── 3. Report generated inline (AI engine)
           → Pop-up modal with full market intelligence ✓
           → Escrow milestone marked "delivered"
           → Funds released to platform
```

### Trustless Work Integration

| API Endpoint | Usage |
|-------------|-------|
| `POST /deployer/single-release` | Deploy escrow with milestones + roles |
| `POST /helper/send-transaction` | Submit signed XDR to Stellar |
| `POST /escrow/single-release/fund-escrow` | Get fund XDR for user to sign |
| `POST /escrow/single-release/change-milestone-status` | Mark signal resolved |
| `POST /escrow/single-release/release-funds` | Release to provider on success |

### Escrow Configuration

```json
{
  "type": "Single-Release",
  "asset": "USDC on Stellar Testnet",
  "milestone": "Signal resolves profitably within 24h",
  "roles": {
    "approver": "Platform (auto-approves via oracle)",
    "serviceProvider": "Signal provider",
    "disputeResolver": "Platform admin",
    "receiver": "Signal provider"
  },
  "platformFee": "10%"
}
```

### Dual-Chain Architecture

| Chain | Wallet | Purpose |
|-------|--------|---------|
| **Initia (EVM)** | Interwoven Kit embedded wallet | Swipe cards, on-chain conviction, AI agent trading |
| **Stellar (Soroban)** | Freighter browser extension | Fund escrows, receive USDC payouts, view escrow status |

---

## SoSoValue Integration

Deeply integrates [SoSoValue](https://sosovalue.com) as the institutional intelligence layer:

```
SoSoValue API (9 modules, smart-cached, 18 req/min)
    │
    ├── ETF Flows ──────→ ETF_FLOW + ETF_MOMENTUM signals
    ├── Macro Events ───→ MACRO_CATALYST signals + Insight Cards
    ├── SSI Indices ────→ Index Cards (DeFi, AI, Meme, L1, L2...)
    ├── Sector Spotlight → SECTOR_ROTATION signals
    ├── BTC Treasuries ─→ Whale Cards with accumulation tracking
    ├── Analysis Reports → RESEARCH_CONVICTION scoring
    └── Full Context ───→ Multi-Agent Sentiment + Divergence detection
```

| Signal | Trigger |
|--------|---------|
| `ETF_FLOW` | BTC/ETH ETF net flow > $50M |
| `ETF_MOMENTUM` | 2-3 day inflow/outflow streak |
| `MACRO_CATALYST` | Scheduled macro event today |
| `SECTOR_ROTATION` | Sector 24h change > ±3% |
| `RESEARCH_CONVICTION` | Analysis keywords scoring |
| `SMART_MONEY_DIVERGENCE` | ETF flow contradicts price action |

---

## AI Agent API (x402 Pay-per-Request)

Pay-per-call market intelligence for AI agents. **No API keys. No accounts. Just USDC on Base.**

| | |
|---|---|
| **Live base URL** | `https://ai.overguild.com/agent-api/api/v2/agent/*` |
| **Network** | Base mainnet (`eip155:8453`) |
| **Asset** | USDC |
| **Receiver** | `0x100690a32B562fd45e685BC2E63bbfF566d452db` |
| **Track record** | **60.8% accuracy** across **5,816+ on-chain resolved predictions** |
| **Discovery** | [CDP Bazaar](https://docs.cdp.coinbase.com/x402/bazaar) (auto-indexed after first settle) |

### Paid Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| `GET /api/v2/agent/decisions` | $0.001 | APE/FADE verdicts with confidence, entry/target/stop, reasoning, per-token track record |
| `GET /api/v2/agent/prices` | $0.001 | Real-time aggregated prices (CoinGecko + DexScreener) with source attribution |
| `GET /api/v2/agent/pools` | $0.005 | DeFi LP advisory ranked by APY, TVL, IL risk |
| `GET /api/v2/agent/track-record` | $0.01 | Historical accuracy + per-token win rates |
| `GET /api/v2/agent/context` | $0.01 | Macro context: BTC/ETH ETF flows, macro events, sector rotation, oracle mood |

Full base URL is `https://ai.overguild.com/agent-api` — e.g. `https://ai.overguild.com/agent-api/api/v2/agent/decisions?limit=5`.

### Premium Report Endpoints (Stellar Escrow)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v2/agent/reports` | GET | List report types + pricing |
| `/api/v2/agent/reports/purchase` | POST | Deploy escrow, returns tx_hash + explorer link |
| `/api/v2/agent/reports/confirm` | POST | Fund escrow + generate report |
| `/api/v2/agent/reports/{id}` | GET | Retrieve purchased report |

### How an Agent Pays (the x402 flow)

```
Agent ──── GET /api/v2/agent/decisions ───→  Signal Agent API
      ←─── 402 Payment Required           ───
           {accepts: [{network: eip155:8453, asset: USDC, amount: "1000",
                       payTo: "0x1006..."}], extensions: {bazaar: {...}}}

      ──── GET ... + x-payment: <signed-payload> ───→
                                                       Signal Agent API
                                                       │ verify via CDP
                                                       │ deliver data
                                                       │ settle in background
      ←─── 200 OK + x-payment-response: <receipt> ────
           {decisions: [...]}
```

### Quickstart — TypeScript (canonical x402 SDK)

```bash
npm i x402-fetch viem
```

```ts
import { wrapFetchWithPayment } from "x402-fetch";
import { privateKeyToAccount } from "viem/accounts";

const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`);
const fetchWithPayment = wrapFetchWithPayment(fetch, account);

const r = await fetchWithPayment(
  "https://ai.overguild.com/agent-api/api/v2/agent/decisions?limit=5"
);
const { decisions } = await r.json();
console.log(decisions[0]);
// { token: "BTC", action: "APE", confidence: 85, entry: 67234.5,
//   target: 68243.0, stop: 66225.0, reasoning: "...",
//   track_record: { win_rate: 60.8, sample_size: 5816 } }
```

The wrapper handles 402 detection, payload signing, header attachment, and retry. Works in Node, Deno, and the browser.

### Quickstart — curl (the manual 402 dance)

```bash
# 1. Hit the endpoint with no payment — you get the challenge
curl -i https://ai.overguild.com/agent-api/api/v2/agent/decisions
# HTTP/2 402
# {"x402Version":2,
#  "resource":{"url":"https://ai.overguild.com/agent-api/api/v2/agent/decisions",...},
#  "accepts":[{"scheme":"exact","network":"eip155:8453","asset":"0x833...USDC",
#              "amount":"1000","payTo":"0x1006..."}],
#  "extensions":{"bazaar":{"info":{...},"schema":{...}}}}

# 2. Sign a PaymentPayload, base64 it, send back as the x-payment header
curl -H "x-payment: <base64-PaymentPayload>" \
     https://ai.overguild.com/agent-api/api/v2/agent/decisions
# HTTP/2 200
# x-payment-response: <base64-SettleResponse>
# {"decisions":[...]}
```

For the exact payload shape, see [x402.org](https://x402.org) or use the `x402-fetch` SDK to do it for you.

### Dual Rail — Base (CDP) + Morph Rails

The same paid endpoints are served on a **second, parallel rail** at
`https://ai.overguild.com/morph-api/api/v2/agent/*` settled on
[Morph Rails](https://docs.morph.network/docs/morph-rails/overview)
(Hoodi testnet, `eip155:2910`). Agents pick the rail that suits them:

| Rail | URL prefix | Network | Asset | Gas | Facilitator auth |
|---|---|---|---|---|---|
| **Base** | `/agent-api/*` | `eip155:8453` | USDC | ETH | CDP JWT |
| **Morph** | `/morph-api/*` | `eip155:2910` (Hoodi) | HoodiTestToken | **USDC via AltFee** — no ETH required | Morph HMAC |

Each Morph response carries:
- `x-payment-rail: morph`
- `x-morph-reference-key: SIGNAL-<12-hex>` — merchant order ID
- `x-payment-response: <base64-SettleResponse>`

Reconcile by Reference Key (free, no auth):
```bash
curl 'https://ai.overguild.com/morph-api/reconcile?key=SIGNAL-AB12CD34EF56'
# → { tx_hash, network, payer, amount, status, settled_at, explorer_url }
```

Skill Hub manifest (free): `GET /.well-known/morph-skill.json`.

```mermaid
flowchart LR
    A["Agent (USDC-only wallet)"] -->|GET /morph-api/...| C[Caddy]
    C --> P[FastAPI :8002<br/>agent_main.py]
    P -->|verify+settle HMAC| F[Morph Facilitator<br/>morph-rails.morph.network/x402]
    F -->|on-chain settle| S[Morph Hoodi sequencer<br/>AltFee deducts gas in USDC]
    P -->|x-morph-reference-key| A
    P -. ai.overguild.com/.well-known/morph-skill.json .-> SH[Morph Skill Hub]
```

Deploy guide: [`docs/MORPH-DEPLOY.md`](docs/MORPH-DEPLOY.md).

### Discover Through Bazaar

After the first paid call settles through the CDP Facilitator, this service is automatically indexed in the [CDP Bazaar](https://docs.cdp.coinbase.com/x402/bazaar) — no separate registration step.

```bash
# Semantic search (free, no auth)
curl 'https://api.cdp.coinbase.com/platform/v2/x402/discovery/search?query=trading+signals'

# Look up our merchant directly
curl 'https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant?payTo=0x100690a32B562fd45e685BC2E63bbfF566d452db'

# Browse the full catalog
curl 'https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources?limit=20'
```

For agent-native discovery, the Bazaar exposes an MCP server:

```
https://api.cdp.coinbase.com/platform/v2/x402/discovery/mcp
  search_resources({query: "AI trading"})    → ranked list of paid endpoints
  proxy_tool_call({toolName: "decisions"})   → call with payment automatic
```

See the Bazaar [MCP guide](https://docs.cdp.coinbase.com/x402/bazaar#bazaar-mcp-server).

### Response Schema

```json
{
  "decisions": [
    {
      "token": "BTC",
      "action": "APE",
      "confidence": 85,
      "entry": 67234.5,
      "target": 68243.0,
      "stop": 66225.0,
      "reasoning": "ETF 3-day inflow streak ($450M) + bullish divergence",
      "rarity": "rare",
      "track_record": { "win_rate": 60.8, "sample_size": 5816 }
    }
  ],
  "total": 1
}
```

### Premium Report Response

```json
{
  "status": "delivered",
  "escrow_id": 7,
  "fund_tx_hash": "b8a2bdc1deded5d12e900317725a94df...",
  "fund_explorer_url": "https://stellar.expert/explorer/testnet/tx/b8a2bdc1...",
  "report": {
    "type": "market_overview",
    "market_summary": {
      "btc_sentiment": 72,
      "btc_direction": "bullish",
      "eth_sentiment": 45,
      "eth_direction": "neutral"
    },
    "etf_flows": {
      "btc_net_flow": 186026106,
      "eth_net_flow": 67847011
    },
    "macro_events": ["FOMC Meeting", "Core PCE Price Index"],
    "top_signals": [
      {
        "token": "BTC",
        "direction": "APE",
        "confidence": 85,
        "entry": 67234.5,
        "target": 69500.0,
        "stop": 65800.0,
        "reasoning": "ETF inflow streak + breakout above 200 EMA"
      }
    ],
    "risk_level": "medium"
  }
}
```

### Free Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Service health check |
| `GET /SKILL.md` | Agent capability discovery |
| `GET /api/v2/agent/reports` | Report types + pricing (free to browse) |

---

## Architecture

```
contracts/   → Foundry (Solidity) — SignalRegistry, SessionVault, ConvictionEngine
backend/     → Python FastAPI — AI signal engine + REST API + Trustless Work client
frontend/    → Vite + React + TailwindCSS — Trading dashboard + Marketplace
```

### Backend Process Model (VPS)

```
┌─────────────────────────────────────────────────────┐
│  VPS (Single Machine)                                │
│                                                      │
│  Process 1: uvicorn (API)                            │
│  • All endpoints (signals, cards, reports, escrow)   │
│  • Async I/O only — zero background threads          │
│  • Report generation inline (max 30s)                │
│                                                      │
│  Process 2: scheduler_worker                         │
│  • Card generation (10min)                           │
│  • Position monitoring (10min)                       │
│  • Escrow resolution (30min)                         │
│  • Report retry (5min)                               │
│  • Sentiment + news refresh (10min)                  │
│                                                      │
│  Caddy: SSL + reverse proxy                          │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Stack |
|-------|-------|
| Contract | Solidity ^0.8.24, Foundry, OpenZeppelin |
| Backend | Python 3.11+, FastAPI, web3.py, APScheduler, stellar-sdk |
| Frontend | React 19, TypeScript, Vite, TailwindCSS v4 |
| Data | viem, TanStack Query, lightweight-charts |
| Wallet (EVM) | Privy (embedded + social login) |
| Wallet (Stellar) | Freighter (browser extension) |
| Escrow | Trustless Work REST API (Soroban on Stellar) |
| AI | AWS Bedrock (Nova Lite), multi-agent debate |
| Database | PostgreSQL (Supabase) |
| Agent Payment | x402 (USDC) |

## Deployment

| Service | URL |
|---------|-----|
| Backend API | `https://ai.overguild.com` |
| Backend API (alt) | `https://47-130-193-211.sslip.io/signal-api` |
| Stellar Explorer | `https://stellar.expert/explorer/testnet` |
| Trustless Work API | `https://dev.api.trustlesswork.com` |

## Initia-Native Features

| Feature | How It's Used |
|---------|---------------|
| **Privy Wallet** | Embedded wallet + social login for trading |
| **Auto-Signing** | One-click signal execution — no popups |
| **Slinky Oracle** | Primary price feed for signal generation |
| **On-chain Conviction** | User-signed trades stored on Initia EVM |

## Explorer

Stellar escrow transactions:
```bash
# View escrow contract
https://stellar.expert/explorer/testnet/contract/<CONTRACT_ID>

# View transaction
https://stellar.expert/explorer/testnet/tx/<TX_HASH>
```

Initia on-chain signals:
```bash
https://scan.testnet.initia.xyz/initia-signal-1/evm-contracts/0xc178dcA82a0E1EBaCa5EB373E73C97cd5a0cfADd
```

---

### Key Differentiators

1. **Real AI engine** — Multi-agent analysis with SoSoValue institutional data
2. **Automated resolution** — No manual approval (oracle-based price verification)
3. **Agent-to-agent commerce** — AI agents pay for signals via x402 + Stellar escrow
4. **On-chain proof** — Both Initia (conviction) and Stellar (escrow) records
5. **Data moat** — SoSoValue + CryptoPanic + DeFiLlama + DexScreener aggregation

---

## License

MIT
