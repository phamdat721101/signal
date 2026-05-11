# Initia Signal

Open-source AI-powered on-chain trading signal kit for EVM appchains.

Generate market signals from real price data, store them immutably on-chain, execute with one-click auto-signing, and track verifiable performance history — all on your own appchain.

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Price Feeds (Slinky Oracle / CoinGecko OHLC)       │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  AI Signal Engine (Python)                           │
│  • EMA(5) vs EMA(10) crossover for direction         │
│  • RSI(14) filter: skip overbought/oversold          │
│  • Confidence: EMA strength + RSI distance           │
│  • Runs every 2 minutes via scheduler                │
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
│  Frontend (React + InterwovenKit)                    │
│  • Candlestick charts with Entry/TP/SL levels        │
│  • One-click execute via auto-signing                │
│  • AI workflow visualization                         │
│  • Portfolio P&L + Trader Leaderboard                │
└──────────────────────────────────────────────────────┘
```

## SoSoValue Integration

Ape or Fade deeply integrates [SoSoValue](https://sosovalue.com) as its institutional intelligence layer — giving retail traders access to the same data hedge funds use, delivered as swipeable cards.

### Data Flow

```
SoSoValue API (9 modules, smart-cached, 18 req/min)
    │
    ├── ETF Flows ──────→ ETF_FLOW + ETF_MOMENTUM signals on BTC/ETH cards
    ├── Macro Events ───→ MACRO_CATALYST signals + Insight Cards
    ├── SSI Indices ────→ Index Cards (DeFi, AI, Meme, L1, L2...)
    ├── Sector Spotlight → Sector Cards + SECTOR_ROTATION signals
    ├── BTC Treasuries ─→ Whale Cards with accumulation delta tracking
    ├── Currency Snapshots → Per-token enrichment for top candidates
    ├── Analysis Reports → AI Research section + RESEARCH_CONVICTION score
    └── Full Context ───→ Multi-Agent AI Sentiment Agent + Divergence detection
```

### SoSoValue-Powered Features

| Feature | Data Source | User Value |
|---------|-----------|------------|
| Smart Money Intel | ETF flows + whale treasuries | See what institutions are doing |
| Sector Rotation | Sector spotlight | Detect capital flowing between sectors |
| Whale Alerts | BTC treasuries (delta tracking) | Know when whales accumulate |
| Macro Alerts | Macro events calendar | Never miss FOMC, CPI, employment data |
| Index Cards | SSI indices (Mag7, DeFi, AI, Meme) | Diversified basket plays |
| AI Research | Per-token analysis reports | Research-grade conviction scoring |
| Divergence Signals | ETF flows vs price action | Institutions buying while price drops |

### Signal Types from SoSoValue

| Signal | Trigger |
|--------|---------|
| `ETF_FLOW` | BTC/ETH ETF net flow > $50M |
| `ETF_MOMENTUM` | 2-3 day inflow/outflow streak |
| `MACRO_CATALYST` | Scheduled macro event today |
| `SECTOR_ROTATION` | Sector 24h change > ±3% |
| `RESEARCH_CONVICTION` | Analysis keywords scoring |
| `SMART_MONEY_DIVERGENCE` | ETF flow contradicts price action |

---

## AI Agent API (x402 Pay-per-Request on Base Bazaar)

The Signal API is published on **Base Bazaar** — AI agents discover and pay for trading intelligence using the x402 protocol. No API keys, no accounts — just USDC on Base.

### Discovery

```bash
# Bazaar semantic search
npx awal@latest x402 bazaar search "trading signals"

# Direct SKILL.md
curl https://13-212-80-72.sslip.io/signal-api/SKILL.md
```

### Paid Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| `GET /api/v2/agent/decisions` | $0.001 | AI trading decisions with confidence + track record |
| `GET /api/v2/agent/prices` | $0.001 | Real-time aggregated prices |
| `GET /api/v2/agent/pools` | $0.005 | LP pool advisory with yield analysis |
| `GET /api/v2/agent/context` | $0.01 | Market macro context (ETF flows, sectors) |
| `GET /api/v2/agent/track-record` | $0.01 | Historical prediction accuracy per token |

### How Agents Pay (x402 Protocol)

```
Agent Request ──→ 402 Payment Required (payment options in header)
       │
       ├── Agent signs USDC payment on Base
       │
       └── Agent retries with X-PAYMENT header ──→ 200 OK + data
```

**Payment Config:**
- Network: Base (`eip155:8453`)
- Token: USDC
- Facilitator: CDP x402
- Receiver: `0x100690a32B562fd45e685BC2E63bbfF566d452db`

### Agent Integration Example

```python
# Using CDP AgentKit with x402
from cdp_agentkit import Agent

agent = Agent(wallet="base-mainnet")
response = agent.x402_request(
    "https://13-212-80-72.sslip.io/signal-api/api/v2/agent/decisions?limit=5"
)
# Agent automatically handles 402 → pay → retry flow
decisions = response.json()["decisions"]
```

```bash
# CLI usage
npx awal@latest x402 pay \
  "https://13-212-80-72.sslip.io/signal-api/api/v2/agent/decisions?limit=5"
```

### Response Schema

```json
{
  "decisions": [
    {
      "token": "BTC",
      "action": "APE",
      "confidence": 85,
      "entry": 104250.5,
      "target": 105814.3,
      "stop": 102686.7,
      "reasoning": "ETF 3-day inflow streak ($450M) + bullish divergence",
      "track_record": { "win_rate": 68.5, "sample_size": 42 }
    }
  ]
}
```

### Free Endpoints (No Payment)

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Service health check |
| `GET /SKILL.md` | Agent capability discovery |
| `GET /.well-known/SKILL.md` | Standard discovery path |

---

## Architecture

```
contracts/   → Foundry (Solidity) — SignalRegistry smart contract
backend/     → Python FastAPI — AI signal engine + REST API
frontend/    → Vite + React + TailwindCSS — Trading dashboard
```

## Signal Algorithm

The AI engine uses standard technical indicators on real market data:

| Indicator | Usage |
|-----------|-------|
| EMA(5) / EMA(10) | Crossover detection for trend direction |
| RSI(14) | Overbought (>75) / oversold (<25) filter |
| Confidence | Composite score: EMA strength + RSI distance (50-95%) |
| Target | Entry ± 1.5% (realistic 24h target) |
| Stop-Loss | Entry ∓ 1.5% (1:1 risk/reward) |
| Resolution | Auto-resolved after 24h with current market price |

## Smart Contract

`SignalRegistry.sol` — Ownable EVM contract storing an append-only array of signals:

```solidity
struct Signal {
    address asset;      // Tracked asset (BTC, ETH, INIT)
    bool isBull;        // Bull (buy) or Bear (sell)
    uint8 confidence;   // 0-100 confidence score
    uint256 targetPrice;
    uint256 entryPrice;
    uint256 exitPrice;  // Set on resolution
    uint256 timestamp;
    bool resolved;
    address creator;
}
```

- `createSignal()` — open to anyone
- `resolveSignal()` — owner only (backend wallet)
- All prices in 18-decimal wei format

## Initia-Native Features

| Feature | How It's Used |
|---------|---------------|
| **InterwovenKit** | Wallet connection + social login for the trading dashboard |
| **Auto-Signing** | One-click signal execution via ghost wallet — no popups after first approval |
| **Interwoven Bridge** | Header button to fund appchain wallet from Initia L1 |
| **Slinky Oracle** | Primary price feed for signal generation (CoinGecko OHLC fallback) |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Backend health + chain connection status |
| GET | `/api/signals` | All signals (paginated) |
| GET | `/api/signals/:id` | Single signal detail |
| GET | `/api/prices` | Current market prices |
| GET | `/api/prices/:symbol/history` | Price history for charting |
| GET | `/api/leaderboard` | Trader rankings by P&L |
| GET | `/api/tx-history` | AI signal tx hashes with explorer URLs |
| POST | `/api/signals/generate` | Trigger signal generation cycle |

## Tech Stack

| Layer | Stack |
|-------|-------|
| Contract | Solidity ^0.8.24, Foundry, OpenZeppelin |
| Backend | Python 3.11+, FastAPI, web3.py, APScheduler |
| Frontend | React 19, TypeScript, Vite, TailwindCSS v4 |
| Data | viem, TanStack Query, lightweight-charts |
| Wallet | InterwovenKit, wagmi |
| Indexer | Rollytics (Postgres-backed) |

## Explorer

Transaction history via API:

```bash
curl http://localhost:8000/api/tx-history | jq '.transactions[:3]'
```

Initia Scan (when rollup is indexed):
- Transactions: `https://scan.testnet.initia.xyz/initia-signal-1/txs/<hash>`
- Contract: `https://scan.testnet.initia.xyz/initia-signal-1/evm-contracts/0x4A17D58C328158FAF35f1E9a8C6E474Bf37A8513`

## License

MIT
