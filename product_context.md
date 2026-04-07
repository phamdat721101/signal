# Initia Signal — Product Context & Architecture

Primary context document for AI agents and developers working on the `Initia Signal` project.

## 1. Product Overview

**Initia Signal** is an AI-powered trading intelligence platform for Initia EVM appchains. It tracks `BTC/USD`, `ETH/USD`, `INIT/USD` prices, generates bullish/bearish signals using EMA crossover + RSI technical analysis, stores them immutably on-chain, and provides a React dashboard for viewing/executing signals with one-click auto-signing.

Every signal is recorded on-chain with entry price, target, confidence, and resolution outcome — solving the "unverifiable trading calls" problem with provable track records. Premium features are token-gated via an MPP (Micropayment Protocol) Session Vault using mock iUSD.

---

## 2. Architecture

```
contracts/   → Foundry (Solidity ^0.8.24) — 4 smart contracts
backend/     → Python 3.11+ FastAPI — AI signal engine + REST API + MPP payment
frontend/    → Vite + React 19 + TailwindCSS v4 — Trading dashboard
```

### 2.1 Smart Contracts (`/contracts`)

Built with Foundry (`--via-ir` required) + OpenZeppelin. Deployed via `minitiad tx evm create` (local) or `forge script` (testnet).

| Contract | Purpose |
|----------|---------|
| `SignalRegistry.sol` | Core data layer. Append-only `Signal[]` array with `createSignal()` (anyone) and `resolveSignal()` (owner only). Events: `SignalCreated`, `SignalResolved`. |
| `SessionVault.sol` | MPP payment channels. Users deposit iUSD → open time-limited sessions → sign off-chain vouchers → backend redeems in batches. Supports `createSession`, `topUpSession`, `closeSession`, `redeemVoucher`, `redeemBatch`, `settle`. |
| `MockIUSD.sol` | ERC20 test token with `faucet()` (1000 iUSD, 1h cooldown) and owner `mint`/`batchMint`. |
| `SignalPaymentGateway.sol` | Access record logging. Tracks which agents accessed which signals and how much they paid. Service tier pricing. |

Signal struct: `{asset, isBull, confidence(0-100), targetPrice, entryPrice, exitPrice, timestamp, resolved, creator}` — all prices in 18-decimal wei.

### 2.2 Backend (`/backend`)

FastAPI app entry: `app/main.py`. Key modules:

| Module | Role |
|--------|------|
| `config.py` | Pydantic Settings from `.env`. Switches `local`/`testnet` via `NETWORK`. Properties: `json_rpc_url`, `lcd_url`. |
| `chain.py` | `ChainClient` — web3.py wrapper with POA middleware. `gasPrice: 0` for gasless local chain. Manages nonce internally. |
| `signal_engine.py` | Price fetching (Slinky Oracle → CoinGecko OHLC fallback), EMA(5)/EMA(10) crossover + RSI(14) filter, confidence scoring, signal submission, auto-resolution after configurable timeout (default 24h). Tracks recent TX hashes. |
| `scheduler.py` | APScheduler runs `run_signal_cycle()` every N minutes (default 2). |
| `mpp_middleware.py` | `MPPPaymentVerifier` — verifies signed vouchers against on-chain SessionVault, batches redemptions (flush at 10). Builds 402 responses with `x-payment-required` header. |
| `agent_client.py` | Reference SDK (`SignalAgentClient`) for AI agents to consume paid signals via voucher signing. |

API endpoints:
- `GET /api/health` — status + chain connection
- `GET /api/signals` — paginated signals (free, reads from contract)
- `GET /api/signals/:id` — single signal
- `GET /api/prices` — current market prices
- `GET /api/prices/:symbol/history` — price history for charting
- `GET /api/leaderboard` — trader rankings by P&L
- `GET /api/tx-history` — AI signal TX hashes with explorer URLs
- `POST /api/signals/generate` — trigger signal cycle (payment-gated when enabled)
- `GET /api/signals/premium` — all signals (payment required)
- `GET /api/signals/single/:id` — single signal (payment required)
- `GET /api/payment/session/:id` — session info
- `GET /api/payment/pricing` — service tier prices
- `POST /api/payment/faucet?address=` — mint 1000 iUSD (owner only)

### 2.3 Frontend (`/frontend`)

React 19 SPA with Vite, TailwindCSS v4, react-router-dom.

| Dependency | Usage |
|------------|-------|
| `@initia/interwovenkit-react` | Wallet connect, social login, bridge, auto-signing ghost wallet |
| `wagmi` + `viem` | EVM chain config, contract reads via `publicClient.readContract()` |
| `@tanstack/react-query` | Data fetching with 15s stale/refetch |
| `lightweight-charts` | Candlestick charts with Entry/TP/SL price lines |

Pages: Dashboard, SignalFeed, SignalDetail, Portfolio, Leaderboard.

Hooks:
- `useSignals.ts` — reads contract directly via viem (not backend)
- `usePrices.ts` — fetches from backend REST API
- `useSignalActions.ts` — executes `createSignal` via InterwovenKit `requestTxBlock` with `/minievm.evm.v1.MsgCall`
- `useSession.ts` — MPP flow: faucet claim → approve iUSD → deposit to SessionVault. Multi-step TX progress UI.

Config (`config/index.ts`): viem chain definitions (local chain ID 1, testnet 7891), InterwovenKit `customChain`, asset metadata for 3 tracked assets, price formatting, explorer URL builders.

Auto-signing: `enableAutoSign: { [chainId]: ['/minievm.evm.v1.MsgCall'] }` — users approve once, subsequent txs sign automatically.

---

## 3. Data Flow

1. **Signal reads**: Frontend → viem `readContract()` → EVM RPC → SignalRegistry (direct on-chain)
2. **Prices & leaderboard**: Frontend → Backend REST → Oracle/CoinGecko + contract
3. **AI signal creation**: Scheduler → `signal_engine` → `ChainClient.create_signal()` → contract
4. **User signal execution**: Frontend → InterwovenKit `requestTxBlock` (MsgCall) → contract
5. **Signal resolution**: Backend only (`onlyOwner`) — fetches current price, calls `resolveSignal()`
6. **MPP payment**: User deposits iUSD → signs voucher off-chain → backend verifies + redeems on-chain in batches

## 4. Signal Algorithm

| Step | Detail |
|------|--------|
| Price fetch | Slinky Oracle (`/slinky/oracle/v1/prices` via LCD), fallback to CoinGecko |
| Bootstrap | CoinGecko OHLC (last 20 candles of 1-day data) on startup |
| Direction | EMA(5) crosses above EMA(10) = bullish; below = bearish. Also triggers on strong trend (>0.1% divergence) |
| Filter | RSI(14) > 75 blocks bullish signals; RSI < 25 blocks bearish |
| Confidence | `25 + EMA_strength(0-40) + RSI_distance(0-30)`, clamped to 50-95% |
| Target | Entry ± 1.5% (realistic 24h target, 1:1 risk/reward) |
| Resolution | Auto after `SIGNAL_RESOLVE_TIMEOUT_HOURS` (default 24h) with actual market price |

## 5. Deployment

| Method | Command |
|--------|---------|
| Local appchain | `weave init` (EVM + oracle) → `deploy.sh` (minitiad tx evm create) |
| Testnet | `deploy-testnet.sh` (forge script to Initia testnet RPC) |
| Full stack | `start.sh` — backend :8000 + frontend :5173 |

Local endpoints: EVM RPC `:8545`, Cosmos RPC `:26657`, LCD `:1317`, Indexer `:8080`.

## 6. Key Conventions

- Prices: uint256 in 18-decimal wei on-chain; Oracle uses 8-decimal (converted in signal_engine)
- Asset addresses: `0x...0001` (BTC), `0x...0002` (ETH), `0x...0003` (INIT) — placeholder addresses
- Backend settings: `pydantic-settings` with `@lru_cache` singleton
- Foundry: `--via-ir` required, remapping `@openzeppelin/contracts/` → `lib/openzeppelin-contracts/contracts/`
- ABI sync: `backend/app/abi.json` ↔ `frontend/src/abi/SignalRegistry.ts` must match
- Gasless: local chain uses `gasPrice: 0`

## 7. Environment Variables

Backend (`backend/.env`): `NETWORK`, `PRIVATE_KEY`, `CONTRACT_ADDRESS`, `SESSION_VAULT_ADDRESS`, `MOCK_IUSD_ADDRESS`, `PAYMENT_GATEWAY_ADDRESS`, `ENABLE_PAYMENT_GATING`, `SIGNAL_INTERVAL_MINUTES`, `SIGNAL_RESOLVE_TIMEOUT_HOURS`.

Frontend (`frontend/.env`): `VITE_NETWORK`, `VITE_CONTRACT_ADDRESS`, `VITE_CHAIN_ID`, `VITE_COSMOS_RPC_URL`, `VITE_REST_URL`, `VITE_BACKEND_URL`, `VITE_MOCK_IUSD_ADDRESS`, `VITE_SESSION_VAULT_ADDRESS`, `VITE_PAYMENT_GATEWAY_ADDRESS`, `VITE_PAYMENT_ENABLED`.

---
*Updated 2026-04-07 — Full source analysis including MPP payment system, agent SDK, and testnet deployment.*
