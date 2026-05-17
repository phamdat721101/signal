# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Initia Signal (codename **KINETIC** / "Ape or Fade") is a Tinder-style swipe trading-card app for crypto, plus an agent-API marketplace. Users swipe APE/FADE on AI-generated cards; every swipe is an on-chain prediction (Initia EVM) resolved 24h later. AI agents consume the same data via a paid `/api/v2/agent/*` surface (x402 / USDC on Base). Premium reports flow through Stellar escrow (Trustless Work). Two chains: **Initia EVM** for cards/conviction (InterwovenKit wallet), **Stellar** for escrow funding (Freighter wallet).

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

**contracts/** — Foundry. Multiple contracts: `SignalRegistry` (predictions), `SessionVault` (premium-swipe deposits), `RewardEngine` (streaks/wins), `ProofOfAlpha` (soulbound achievement NFTs), `ConvictionEngine` (per-wallet on-chain reputation). Use `--via-ir`. Deploy to Initia minitia via `minitiad tx evm create`.

**backend/** — FastAPI app (`app/main.py`). Key modules grouped by concern:

- *Foundation*: `config.py` (Pydantic Settings), `error_tracker.py` (CircuitBreaker + persistent crash log), `http_client.py` (shared sync+async retry+breaker; **all external HTTP must go through this**), `db_async.py` (asyncpg pool for hot API endpoints), `db.py` (legacy sync psycopg2; used by scheduler + writes), `chain.py` (web3.py wrapper).
- *Card pipeline*: `content_engine.py` (5-stage CoinGecko→signals→narrative→assemble), `token_harvester.py`, `lp_advisory.py`, `insight_engine.py`, `degen_oracle.py`, `signal_engine.py`.
- *Data sources*: `sosovalue_client.py` (institutional ETF flows + macro + indices, routes through http_client), `news_aggregator.py`, `sentiment_engine.py`, `price_feed.py` (DexScreener+CoinGecko aggregator).
- *Agent surface*: `agent_api.py` exposes `/api/v2/agent/{decisions,prices,pools,context,track-record,my-agent,marketplace,reports}` — paid via `x402_payment.py` (USDC on Base) or `mpp_middleware.py` (session-vault payments). Hot endpoints are async + asyncpg + per-handler TTL cache.
- *Stellar / escrow*: `trustless_escrow.py` (Trustless Work API), `report_generator.py`.
- *Autonomous trader*: `agent_runner.py` (per-user agent that swipes on its behalf, every 10 min via scheduler).
- *Scheduler*: `scheduler.py` runs ~12 jobs (card_gen 5min, position_monitor 5min, expire 10min, backfill_charts 30min, sosovalue 10min, oracle 30min, lp_advisory 15min, user_agents 10min, news 10min, sentiment 10min, prediction_resolve 30min, etc.).

**frontend/** — Vite + React 19 + TypeScript SPA. Wallet via **InterwovenKit only** (`useWallet.ts` is the unified hook; Privy is fully removed). Stellar via **Freighter** (`useStellarWallet.ts`) for Trustless Work flows on `/marketplace`.
- `hooks/useWallet.ts` — single source of truth for EVM auth (`useInterwovenKit` + wagmi `useAccount`/`useSendTransaction`). Every page consumes this; never call `usePrivy`.
- `hooks/useApeTransaction.ts`, `hooks/useSession.ts`, `hooks/useIUSDBalance.ts` — built on top of `useWallet`.
- `components/Layout.tsx` — header with InterwovenKit connect, bottom nav (Feed/Market/Agent/Portfolio/Profile).
- `pages/Feed.tsx` — swipe UX with conviction overlay, rare-card reveal, resolution modal, daily-swipes paywall.
- `pages/Marketplace.tsx` — Stellar/Trustless Work escrow flow.
- `main.tsx` — `InterwovenKitProvider` + `WagmiProvider` with `initiaPrivyWalletConnector` and auto-sign for `MsgCall`.
- TanStack Query 15s stale/refetch.

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

## Performance & Scaling Patterns (avoid repeating mistakes)

These are settled patterns — extending them is fine, replacing them with ad-hoc code is not.

- **All outbound HTTP** must go through `app/http_client.py` (`get`/`post`/`aget`/`apost`, with a `service=` tag). It centralizes retry (429/5xx, exponential backoff, honors `Retry-After`), reuses `error_tracker.CircuitBreaker` per service, and returns `None` on permanent failure (callers degrade gracefully). Do **not** add new `httpx.get(...)` + `try/except` patterns in integrations.
- **Hot API endpoints** (`/api/v2/agent/*`) use `app/db_async.py` (asyncpg pool) — never open a `psycopg2` connection per request inside a handler. The legacy sync `db._get_conn()` path stays for the scheduler and writes.
- **`async def` handlers must not call sync external libs directly** — wrap with `asyncio.to_thread()` (see `/api/v2/agent/{prices,context}` for the pattern). Otherwise you block the event loop.
- **Per-handler TTL caches** are inline (4 lines: `_cache_get/_cache_set` in `agent_api.py`). Promote to a shared module only when ≥3 modules need it. Redis is deferred — when adopted, replace these inline caches uniformly.
- **Request observability**: every request gets a `request_id` (echoed in `x-request-id` response header and in the `[%(request_id)s]` log prefix). Add it to your log lines if you emit context — don't reinvent.
- **Health & circuits**: `/api/health` reports `db_async` pool state and any `open_circuits`. Use this as the canonical "is the system OK" probe.
- **N+1 elimination**: when fetching per-row data in a list endpoint, batch with `WHERE col = ANY($1::text[])` (see `_batch_track_record` in `agent_api.py`).
- **Don't add Redis-dependent code yet** — rate-limiting, distributed cache, and Prometheus metrics are deferred until Redis is provisioned.

## x402 Agent Surface (Bazaar-ready)

Two FastAPI processes share the same data layer; they cannot crash each other.

| Process | Port | Module | URL prefix | Audience | Gating |
|---------|------|--------|-----------|----------|--------|
| Consumer + admin | 8001 | `app.main:app` | `https://ai.overguild.com/api/*` | Frontend (KINETIC) | None / session-vault |
| Agent (paid) | 8002 | `app.agent_main:app` | `https://ai.overguild.com/agent-api/api/v2/agent/*` | AI agents via x402 | x402 / USDC on Base mainnet |

- **Single new file owns the agent surface**: `app/agent_main.py` — lifespan inits db_async pool + x402 server, runs reconciler asyncio task, mounts the gating middleware, and includes `agent_api.router`. No duplication of data-layer code.
- **Single new file owns settlement**: `app/x402_settler.py` — record-pending → settle-async → mark-settled/failed → reconcile. Idempotency key = SHA256 of the `x-payment` header bytes (DB UNIQUE on `payload_hash` in table `x402_settlements`). Survives crash via pending rows; reconciler abandons rows older than 60s with retries < 3.
- **Route prices + Bazaar extensions** live in `app/x402_payment.py`. **Route descriptions matter** for Bazaar semantic-search ranking — write natural-language with cited stats (e.g., "60.8% accuracy across 5,816+ predictions"), not bare endpoint names.
- **Bazaar listing is automatic.** No registration step exists. The CDP Facilitator catalogs the resource on first successful **settle** with `paymentPayload.resource` set. Indexing arrives in the catalog within ~10 min; quality ranking signals (buyer reach, transaction volume, recency) recompute every 6 h. To verify a listing: `GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant?payTo=<x402_receiver_address>`.
- **All facilitator HTTP** is invoked through the SDK's own `HTTPFacilitatorClient`. Wrap sync SDK calls with `asyncio.to_thread` from inside async handlers. Don't call `verify_payment` / `settle_payment` synchronously inside an `async def` — it blocks the event loop.
- **Settle is fire-and-forget** post-response (asyncio task). Buyer gets data immediately; the settle outcome lands in `x402_settlements`. Crash window is bounded by the reconciler.
- **Restart pattern on VPS**: `restart_signal.sh` on `/home/bitnami/signal-backend` runs three nohup processes (consumer 8001, agent 8002, scheduler). Caddy at `47-130-193-211.sslip.io` and `ai.overguild.com` exposes `/agent-api/*` to the agent process.
- **Don't bolt x402 onto `:8001`.** Different SLA, different audience. The split is the architecture.
