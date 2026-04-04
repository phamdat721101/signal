# Initia Signal

Open-source AI-powered on-chain trading signal kit for Initia EVM appchains.

Generate market signals from real price data, store them immutably on-chain, execute with one-click auto-signing, and track verifiable performance history — all on your own appchain.

## Initia Hackathon Submission

- **Project Name**: Initia Signal

### Project Overview

Initia Signal is an AI-powered trading intelligence platform that generates verifiable buy/sell signals using technical analysis (EMA crossover + RSI) on real-time market data, stores every signal immutably on-chain via a Solidity smart contract, and lets users execute signals with one-click auto-signing. It solves the problem of unverifiable trading calls — every signal's entry price, target, confidence, and outcome is recorded on-chain, creating transparent and provable track records for signal providers and traders.

### Implementation Detail

- **The Custom Implementation**: An AI signal engine that fetches real prices from Initia's Slinky oracle (with CoinGecko OHLC fallback), runs EMA(5)/EMA(10) crossover detection with RSI(14) confirmation to generate directional signals with confidence scoring, submits them on-chain to a SignalRegistry contract with realistic ±1.5% targets, and auto-resolves after 24h with the actual market price. The frontend reads signals directly from the EVM contract via viem, displays candlestick charts with entry/TP/SL levels, and shows a trader leaderboard with verifiable P&L.
- **The Native Feature**: **Auto-signing** via InterwovenKit's ghost wallet enables one-click signal execution — users approve a session once and all subsequent `MsgCall` transactions are signed automatically without wallet popups, creating a seamless trading UX. The **Interwoven Bridge** button in the header lets users fund their appchain wallet directly from Initia L1.

### How to Run Locally

1. Launch an EVM appchain: `weave init` (select EVM, enable oracle) → `weave opinit start executor -d` → `weave relayer start -d`
2. Import keys: `MNEMONIC=$(jq -r '.common.gas_station.mnemonic' ~/.weave/config.json) && minitiad keys add gas-station --recover --keyring-backend test --coin-type 60 --key-type eth_secp256k1 --source <(echo -n "$MNEMONIC")`
3. Deploy contract: `cd contracts && forge build --via-ir && ./deploy.sh` (or manually via `minitiad tx evm create`)
4. Start the app: `./start.sh` — backend on http://localhost:8000, frontend on http://localhost:5173

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
