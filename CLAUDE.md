# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Initia Signal is an AI-powered on-chain trading intelligence platform deployed as an EVM appchain on Initia. Users receive AI-generated market signals (buy/sell), execute with one-click auto-signing, and all signals are stored on-chain for verifiable track records.

## Commands

### Smart Contracts (Foundry)
```bash
cd contracts
forge build --via-ir          # Build (via-ir required by foundry.toml)
forge test                     # Run all tests
forge test --match-test test_CreateSignal  # Run single test
forge fmt                      # Format Solidity
forge script script/Deploy.s.sol --rpc-url $RPC_URL --broadcast --private-key $PRIVATE_KEY  # Deploy (generic EVM)
# Deploy to Initia minitia appchain:
jq -r '.bytecode.object' out/SignalRegistry.sol/SignalRegistry.json | tr -d '\n' | sed 's/^0x//' > signalregistry.bin
minitiad tx evm create signalregistry.bin --from gas-station --keyring-backend test --chain-id $CHAIN_ID --node http://localhost:26657 --gas auto --gas-adjustment 1.4 --yes
```

### Full-Stack (one command)
```bash
./start.sh    # Starts backend (port 8000) + frontend (port 5173), Ctrl+C to stop
```

### Backend (Python FastAPI)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000  # Run dev server
```

### Frontend (Vite + React + TypeScript)
```bash
cd frontend
npm install
npm run dev       # Dev server
npm run build     # Type-check + production build
npm run lint      # ESLint
```

## Architecture

Three independent services that communicate via on-chain state and REST:

**contracts/** — Single `SignalRegistry.sol` contract (Ownable). Stores an array of Signal structs. Anyone can `createSignal()`; only the owner can `resolveSignal()`. Uses OpenZeppelin Ownable and requires `--via-ir` compilation.

**backend/** — FastAPI app (`app/main.py`) with these key modules:
- `config.py` — Pydantic Settings loading from `.env`, switches between `local` and `testnet` network via `NETWORK` env var
- `chain.py` — `ChainClient` wraps web3.py to interact with the SignalRegistry contract. Uses POA middleware. Sends txs with `gasPrice: 0` (gasless local chain)
- `signal_engine.py` — Fetches prices from Initia Slinky oracle (LCD endpoint), falls back to CoinGecko. Runs a momentum-based signal generation algorithm. Auto-resolves signals older than the configured timeout
- `scheduler.py` — APScheduler runs `run_signal_cycle()` on a configurable interval (default 5 min)

**frontend/** — React 19 SPA with react-router-dom and InterwovenKit wallet integration. Key patterns:
- `hooks/useSignals.ts` — Reads contract state directly via viem `publicClient.readContract()` (not through the backend)
- `hooks/usePrices.ts` — Fetches prices and leaderboard from the backend REST API
- `hooks/useSignalActions.ts` — Sends transactions via InterwovenKit `requestTxBlock` with `/minievm.evm.v1.MsgCall` message type
- `config/index.ts` — viem chain definitions, InterwovenKit `customChain` definition, asset metadata, price formatting
- `main.tsx` — InterwovenKitProvider wraps the app with auto-signing enabled for MsgCall
- `components/Layout.tsx` — Header with wallet connect + bridge buttons via `useInterwovenKit()`
- TanStack Query with 15s stale/refetch interval for real-time updates

## Data Flow

1. Signal reads: Frontend → viem → RPC → SignalRegistry contract (direct on-chain reads)
2. Prices & leaderboard: Frontend → Backend REST API → Oracle/CoinGecko + contract
3. Signal creation (AI): Backend scheduler → signal_engine → ChainClient → contract
4. Signal creation (user): Frontend → InterwovenKit (requestTxBlock + MsgCall) → contract
5. Signal resolution: Backend only (onlyOwner)

## Initia Appchain Setup

The app runs on a custom Initia EVM appchain (minitia) created via `weave init` with chain ID `initia-signal-1` and denom `umin`. Local endpoints:
- EVM JSON-RPC: `http://localhost:8545` (viem contract reads)
- Cosmos RPC: `http://localhost:26657` (InterwovenKit, minitiad deployment)
- REST/LCD: `http://localhost:1317` (oracle prices, InterwovenKit)

Contract deployment uses `minitiad tx evm create` (not forge script) on the appchain.

## Environment Configuration

Backend uses `NETWORK=local|testnet` with Pydantic Settings loading from `backend/.env`. Frontend uses `VITE_` prefixed env vars in `frontend/.env`. Key vars include `VITE_CHAIN_ID` (Cosmos chain ID from weave init), `VITE_COSMOS_RPC_URL`, `VITE_REST_URL`, and `VITE_CONTRACT_ADDRESS`. The contract ABI must be kept in sync between `backend/app/abi.json` and `frontend/src/abi/SignalRegistry.ts`.

## Key Conventions

- Prices are stored on-chain as uint256 in 18-decimal wei format (e.g., `65000 * 1e18` for $65,000)
- Oracle prices from Slinky use 8-decimal format and are converted in `signal_engine.py`
- Tracked assets use placeholder addresses (`0x...0001` for BTC, `0x...0002` for ETH, `0x...0003` for INIT)
- Backend settings use `pydantic-settings` with `@lru_cache` singleton pattern
- Foundry remapping: `@openzeppelin/contracts/` → `lib/openzeppelin-contracts/contracts/`
