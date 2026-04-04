# Initia Signal

Open-source AI-powered on-chain trading signal kit for Initia EVM appchains.

Generate market signals from real price data, store them immutably on-chain, execute with one-click auto-signing, and track verifiable performance history — all on your own appchain.

## What It Does

Initia Signal is a full-stack trading intelligence platform that:

1. **Fetches real market data** from Initia's Slinky oracle (with CoinGecko fallback) for BTC, ETH, and INIT
2. **Generates buy/sell signals** using a momentum-based algorithm that detects clean price trends with confidence scoring
3. **Stores signals on-chain** via a Solidity smart contract — every signal is immutable and verifiable
4. **Auto-resolves signals** after 24 hours by comparing entry price to current market price
5. **Tracks performance** with win rates, P&L calculations, and a trader leaderboard

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Price Feeds (Slinky Oracle / CoinGecko)            │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  Signal Engine (Python)                              │
│  • Momentum analysis: 3-point trend, >2% movement   │
│  • Confidence scoring: 50-95% based on magnitude     │
│  • Runs every 5 minutes via scheduler                │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  SignalRegistry Contract (Solidity)                   │
│  • createSignal() — anyone can create                │
│  • resolveSignal() — owner resolves with exit price  │
│  • On-chain: asset, direction, confidence, prices    │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  Frontend (React + InterwovenKit)                    │
│  • Dashboard with live stats                         │
│  • Signal feed with filters                          │
│  • One-click execute via auto-signing                │
│  • Portfolio P&L + Leaderboard                       │
│  • Price charts (lightweight-charts)                 │
└──────────────────────────────────────────────────────┘
```

## Architecture

```
contracts/   → Foundry (Solidity) — SignalRegistry smart contract
backend/     → Python FastAPI — AI signal engine + REST API
frontend/    → Vite + React + TailwindCSS — Trading dashboard
```

## Quick Start

### Prerequisites

- [Go 1.22+](https://go.dev/doc/install) + [Docker](https://www.docker.com/products/docker-desktop/)
- [Foundry](https://book.getfoundry.sh/getting-started/installation) (forge, cast)
- [Node.js 18+](https://nodejs.org/) + Python 3.11+

### 1. Launch Appchain

```bash
weave init
# Select: EVM → chain ID: your-chain-id → Enable oracle
weave opinit start executor -d
weave relayer start -d
```

### 2. Import Keys

```bash
MNEMONIC=$(jq -r '.common.gas_station.mnemonic' ~/.weave/config.json)
minitiad keys add gas-station --recover --keyring-backend test \
  --coin-type 60 --key-type eth_secp256k1 --source <(echo -n "$MNEMONIC")
```

### 3. Deploy Contract

```bash
cd contracts
forge build --via-ir
jq -r '.bytecode.object' out/SignalRegistry.sol/SignalRegistry.json \
  | sed 's/^0x//' | tr -d '\n' > SignalRegistry.bin
minitiad tx evm create SignalRegistry.bin \
  --from gas-station --keyring-backend test \
  --chain-id <YOUR_CHAIN_ID> --gas auto --gas-adjustment 1.4 --yes
rm SignalRegistry.bin
```

### 4. Configure & Run

```bash
# Set contract address and private key in backend/.env and frontend/.env
# Then:
./start.sh
```

Backend runs on http://localhost:8000, frontend on http://localhost:5173.

### 5. Seed Demo Data

```bash
curl -X POST http://localhost:8000/api/seed
```

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
| POST | `/api/seed` | Create demo signals for testing |

## Signal Algorithm

The momentum engine analyzes the last 3 price points per asset:

- **Bullish signal**: 3 consecutive ascending prices with >2% total movement
- **Bearish signal**: 3 consecutive descending prices with >2% total movement
- **Confidence**: `clamp(abs(pct_change) × 1000, 50, 95)`
- **Target**: Entry price ± 5%
- **Resolution**: Auto-resolved after 24h with current market price

## Smart Contract

`SignalRegistry.sol` — Ownable EVM contract storing an append-only array of signals:

```solidity
struct Signal {
    address asset;      // Tracked asset identifier
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

- **InterwovenKit** — Wallet connection + social login
- **Auto-Signing** — One-click signal execution via ghost wallet
- **Interwoven Bridge** — Fund appchain from L1
- **Oracle Price Feed** — Real-time data from Slinky oracle

## Tech Stack

| Layer | Stack |
|-------|-------|
| Contract | Solidity ^0.8.24, Foundry, OpenZeppelin |
| Backend | Python 3.11+, FastAPI, web3.py, APScheduler |
| Frontend | React 19, TypeScript, Vite, TailwindCSS v4 |
| Data | viem, TanStack Query, lightweight-charts |
| Wallet | InterwovenKit, wagmi |

## Explorer

Transaction history is available via the API:

```bash
curl http://localhost:8000/api/tx-history | jq '.transactions[:3]'
```

When your rollup is indexed on Initia Scan:
- Transactions: `https://scan.testnet.initia.xyz/<chain-id>/txs/<hash>`
- Contract: `https://scan.testnet.initia.xyz/<chain-id>/evm-contracts/<address>`

## License

MIT
