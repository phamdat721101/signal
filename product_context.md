# Initia Signal — Product Context (Agent Onboarding)

> **Updated 2026-05-18** after fresh redeploy to Initia testnet `evm-1`.
> This is the canonical context document for AI agents and developers working on this codebase.

---

## 1. Product One-Liner

**Initia Signal** (codename **KINETIC** / "Ape or Fade") is a dual-chain AI trading-signal platform:
- **For humans** — Tinder-style swipe app on Initia EVM appchain (APE = buy, FADE = skip). Every swipe is an on-chain prediction resolved 24h later.
- **For AI agents** — pay-per-call market intelligence API on Base (USDC via x402). Premium reports purchasable via Stellar escrow (Trustless Work).

Two chains, two wallets, one product surface.

| Layer | Chain | Wallet | Purpose |
|---|---|---|---|
| Conviction / signals / cards | Initia EVM (`evm-1` testnet) | InterwovenKit (Initia L1 `initiation-2`) | On-chain prediction record, reputation, rewards |
| Premium-report escrow | Stellar (Soroban testnet) | Freighter | Pay-on-success premium content |
| Agent payments | Base mainnet | x402 PaymentPayload (USDC) | Pay-per-request agent API |

---

## 2. Live Deployment (testnet `evm-1`)

Chain id **2124225178762456** — RPC `https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz`

| Contract | Address |
|---|---|
| `SignalRegistry` | `0xc6069073DA915917eb34f85a4e6CcD01987ABa37` |
| `MockIUSD` | `0xbbA5349A0Ff2bDFb5ecDA3FC341dE48462106444` |
| `SessionVault` | `0x28F170E6f3C3216482F8d8BF0A936844076B0A63` |
| `SignalPaymentGateway` | `0x6bD4B0bd3985Da64DEDb64b618ac7625E167B3b3` |
| `RewardEngine` | `0x08C41Dc0e1B0fD4E36e61b8325b29C01e677619e` |
| `ProofOfAlpha` | `0x11dd5247E7F1c5349E075BAff3CC37dFF74a56DB` |
| `ConvictionEngine` | `0xB446112a5080dE73aFC6C68412633CfE220DF3B5` |

Deployer / agent / x402 receiver: `0x100690a32B562fd45e685BC2E63bbfF566d452db`.

Scan explorer: `https://scan.testnet.initia.xyz/evm-1/evm-contracts/<address>`

---

## 3. Architecture (3 layers)

```
contracts/   Foundry · Solidity 0.8.24 · 7 contracts on Initia EVM
backend/     Python 3.11 · FastAPI · 3 processes (main / agent_main / scheduler_worker)
frontend/    Vite · React 19 · TS · TailwindCSS v4 · 6 pages
```

### 3.1 Smart Contracts

| Contract | Role | Status |
|---|---|---|
| `SignalRegistry` | `publishSignal()` for AI agents; on-chain dataHash + wasCorrect | Working |
| `MockIUSD` | ERC20 testnet token w/ 1h faucet. Code-size guard around Initia ERC20Registry precompile (chain-portable) | Working |
| `SessionVault` | iUSD session deposits + voucher micropayments + onlyOwner ops | Working |
| `SignalPaymentGateway` | Logs `ServicePaid` events for MPP-style pay-per-signal | Working |
| `RewardEngine` | 3% rebate on wins + streak bonus | Wired via scheduler |
| `ProofOfAlpha` | Soulbound ERC-721 (5 tiers: Bronze→Sage) | Wired via scheduler |
| `ConvictionEngine` | On-chain reputation: `commitConviction()` + `resolveCard()` | Working |

#### Initia-Native Helpers (PRD-Initia-Native-Upgrade — additive, no redeploys above)

| Contract | Role | Status |
|---|---|---|
| `OracleAdapter` | Resolution-time ConnectOracle price proofs; idempotent `commitEntryPriceProof`/`commitExitPriceProof` with try/catch + 100k gas cap | Code merged; deploy via `deploy-initia-native.sh` |
| `CosmosUtilsView` | Read-only `ICosmos` wrapper (`isAddressSanctioned`, address/denom conversion) | Code merged |
| `CosmosDispatcher` | Owner-gated `execute_cosmos`: NFT mirror to Cosmos NFT module + IBC transfer | Code merged |
| `IBCSettlementHook` | EVM IBC Hooks entry → `SessionVault.payFromSession` for cross-chain report buyers | Code merged; cross-chain demo deferred |
| `VIPScoreAdapter` | Mirrors `ConvictionEngine.reputationScore` onto VIP-compliant scoring contract | Code merged; whitelisting via L1 governance |

**Reliability layer:** `backend/app/chain_ops.py` + `chain_operations` table +
60s reconciler. SHA256 idempotency keys. State machine
`pending→sent→confirmed→final` / `failed_retryable→failed_terminal`. Re-runs
are no-ops. `/api/health` reports `chain_ops_pending_count`. See
`docs/AGENT-ONCHAIN-CONTEXT.md` §7.

**Swipe ritual:** `frontend/src/hooks/useSwipeSession.ts` queues swipes locally,
settles via InterwovenKit `requestTxBlock` (one Cosmos tx, N atomic
`MsgCall` messages). Backend mirror tables `swipe_sessions` + `swipe_session_queue`.
`atomicMode` feature flag falls back to sequential `sendTx` if needed.

**Deploy:** `./deploy-initia-native.sh` — pure-additive, smoke-tested at end.

### 3.2 Backend — 3-process split

| Process | Port | Module | Audience |
|---|---|---|---|
| Consumer + admin API | 8001 | `app.main:app` | Frontend SPA |
| Agent x402 paid API | 8002 | `app.agent_main:app` | AI agents (USDC-on-Base) |
| Background jobs | n/a | `app.scheduler_worker` | ~12 cron-like jobs |

VPS layout: `bitnami@47.130.193.211:~/signal-backend/` (Caddy → `:8001` and `/agent-api/*` → `:8002`).

#### Backend modules — current

*Foundation*
- `config.py` — Pydantic Settings, `network=local|testnet` switch, `@lru_cache` singleton.
- `error_tracker.py` — CircuitBreaker + persistent crash log.
- `http_client.py` — **All outbound HTTP must go through this**. Centralized retry (429/5xx, exp backoff, honors `Retry-After`), per-service `CircuitBreaker`, returns `None` on permanent failure.
- `db_async.py` — asyncpg pool for hot endpoints.
- `db.py` — legacy psycopg2 sync, used by scheduler + writes.
- `chain.py` — web3.py wrapper, RPC switching by `network`.

*Card pipeline (5 stages: harvest→analyze→narrate→visual→assemble)*
- `content_engine.py` (61KB — biggest module)
- `token_harvester.py`, `lp_advisory.py`, `insight_engine.py`, `degen_oracle.py`, `signal_engine.py`.

*Data sources*
- `sosovalue_client.py` — institutional ETF flows + macro + sector indices, smart-cached (18 req/min ceiling).
- `news_aggregator.py`, `sentiment_engine.py`, `price_feed.py` (DexScreener + CoinGecko aggregator).

*Agent surface (paid)*
- `agent_api.py` — routes: `decisions`, `prices`, `pools`, `track-record`, `context`, `my-agent`, `marketplace`, `reports`.
- `x402_payment.py` — route prices + Bazaar extensions. Route descriptions matter for semantic search ranking.
- `x402_settler.py` — record-pending → settle-async → mark-settled/failed → reconciler. Idempotency via SHA256 of `x-payment` header. Asyncio-task settle is fire-and-forget post-response.
- `mpp_middleware.py` — session-vault payment verification via `ServicePaid` event parsing.

*Stellar / escrow*
- `trustless_escrow.py` — Trustless Work REST client.
- `report_generator.py` — premium report inline generation (≤30s).

*Autonomous trader*
- `agent_runner.py` — per-user autonomous swiper, runs every 10min via scheduler.
- `agent_engine.py`, `agent_memory.py`, `agent_client.py`.

*Scheduler (~12 jobs)*: card_gen 5min, position_monitor 5min, expire 10min, backfill_charts 30min, sosovalue 10min, oracle 30min, lp_advisory 15min, user_agents 10min, news 10min, sentiment 10min, prediction_resolve 30min, escrow_resolve 30min, report_retry 5min.

### 3.3 Frontend — 6 pages

```
/             → Feed.tsx          (swipe APE/FADE, conviction overlay, paywall)
/agent        → Agent.tsx         (autonomous trader UI)
/marketplace  → Marketplace.tsx   (Stellar escrow flow for premium reports)
/portfolio    → Portfolio.tsx
/history      → History.tsx
/profile      → Profile.tsx
/trade-success/:id → TradeSuccess.tsx
```

Wallet:
- **EVM** via `hooks/useWallet.ts` — single source of truth (`useInterwovenKit` + wagmi `useAccount`/`useSendTransaction`/`useChainId`/`useSwitchChain`). Privy is fully removed. Every page uses this hook; never call `usePrivy`. Exposes chain status (`isCorrectChain`, `switchToCorrect`) consumed by the global `ChainSwitchBanner` in `Layout.tsx`.
- **Stellar** via `hooks/useStellarWallet.ts` — Freighter for Trustless Work escrow flows.
- `main.tsx` — `InterwovenKitProvider` with `defaultChainId="initiation-2"` (Initia L1 testnet) + auto-sign for `MsgCall`.

Other hooks: `useApeTransaction`, `useSession`, `useIUSDBalance`, `useCards`, `useSignals`, `useSignalActions`, `usePrices`, `useAgent`. `useSession` exposes `iusdCooldownSeconds` + `mockIUSDConfigured` so `/profile` can disable the iUSD faucet button when ineligible (not connected, wrong chain, in 5-min cooldown, or MockIUSD unconfigured).

### Funding flow

New users with low INIT (< 0.01) see a Bridge banner on `/feed` linking to `https://bridge.initia.xyz/?to=initia-signal-1`. The previous `Get 1 INIT Gas` faucet (`POST /api/faucet/gas`) was removed 2026-05-18 — the route now returns 410 Gone with a bridge URL in the detail.

---

## 4. Performance & Scaling Patterns (settled — extend, don't replace)

These exist because we hit the bug; do not re-introduce.

- **All outbound HTTP** → `app/http_client.py` (`get`/`post`/`aget`/`apost`, `service=` tag). Never `httpx.get(...) + try/except` ad-hoc.
- **Hot endpoints** (`/api/v2/agent/*`) → `app/db_async.py` asyncpg pool. Never `psycopg2` per request inside an async handler.
- **`async def` handlers must not call sync libs directly** — wrap with `asyncio.to_thread()` (see `/api/v2/agent/{prices,context}`).
- **Per-handler TTL caches** are inline 4-line `_cache_get/_cache_set` in `agent_api.py`. Promote to shared module only when ≥3 modules need it. Redis is deferred.
- **Request observability**: every request gets a `request_id` echoed in `x-request-id` header and `[%(request_id)s]` log prefix.
- **N+1 elimination**: batch with `WHERE col = ANY($1::text[])` (see `_batch_track_record`).
- **Don't add Redis-dependent code yet** — rate-limiting, distributed cache, Prometheus deferred until Redis is provisioned.
- **`/api/health`** is the canonical liveness probe — reports `db_async` pool state + `open_circuits[]`.

---

## 5. x402 Agent Surface (Bazaar-ready)

Live: `https://ai.overguild.com/agent-api/api/v2/agent/*` — 60.8% accuracy, 5,816+ resolved predictions.

Receiver `0x100690a32B562fd45e685BC2E63bbfF566d452db` on Base (`eip155:8453`). USDC.

| Route | Price | What you get |
|---|---|---|
| `GET /decisions` | $0.001 | APE/FADE verdicts + entry/target/stop |
| `GET /prices` | $0.001 | Aggregated CoinGecko + DexScreener |
| `GET /pools` | $0.005 | DeFi LP advisory |
| `GET /track-record` | $0.01 | Historical accuracy |
| `GET /context` | $0.01 | ETF flows, macro, sector rotation |
| `POST /reports/purchase` + `/confirm` | $2/$5/$10 | Stellar-escrowed premium reports |

Bazaar listing is automatic — first successful settle indexes the resource at the CDP Facilitator. Verify with `GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant?payTo=0x100690…`.

---

## 6. Database (Supabase / Postgres)

Tables: `signals`, `cards`, `swipes`, `trades`, `daily_swipes`, `x402_settlements`, `agent_memory`, `escrow_records`, `reports`.

DB is shared across deployments (historical metrics persist across redeploys; on-chain state is fresh per deploy).

---

## 7. Critical Conventions (must-know)

- `forge build --via-ir` is required (foundry.toml).
- Foundry remapping: `@openzeppelin/contracts/` → `lib/openzeppelin-contracts/contracts/`.
- Prices stored on-chain as uint256 in 18-decimal wei (`65000 * 1e18` for $65,000).
- Slinky oracle prices come in 8-decimal — converted in `signal_engine.py`.
- Tracked-asset placeholder addresses: `0x...0001` BTC, `0x...0002` ETH, `0x...0003` INIT.
- ABIs must stay in sync between `backend/app/*_abi.json` and `frontend/src/abi/*` (frontend currently inlines via `useSignals.ts` etc.).
- Backend Pydantic Settings keys are lower_snake_case; `.env` file is UPPER_SNAKE_CASE; Pydantic auto-converts.
- **Initia testnet `evm-1` quirk**: `forge`'s gas estimator under-counts ~60K of Cosmos-layer fee accounting. For CALL txs, set `--gas-limit ≥ 250000` and `--gas-price 100000000` (0.1 gwei) explicitly via `cast send`.

---

## 8. Live Telemetry (2026-05-18)

```
{"signals":175,"cards":20076,"swipes":1025,"trades":19,"unique_users":11,"total_transactions":1219}
```

(Historical DB cumulative across all chain deploys.)

---

## 9. Quick Operational Checks

```bash
# Backend health (testnet)
curl -sf https://ai.overguild.com/api/health | jq

# Agent API (x402 challenge response)
curl -i https://ai.overguild.com/agent-api/api/v2/agent/decisions | head -5

# Smoke test on-chain
cast call 0xc6069073DA915917eb34f85a4e6CcD01987ABa37 'authorizedAgents(address)(bool)' \
  0x100690a32B562fd45e685BC2E63bbfF566d452db \
  --rpc-url https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz
```

VPS access:
```bash
ssh -i ~/Downloads/nim-claw.pem bitnami@47.130.193.211
# restart: bash ~/signal-backend/restart_signal.sh   (main + scheduler; agent_main started separately)
```
