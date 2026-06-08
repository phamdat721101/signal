# Initia Signal — Product Context (Agent Onboarding)

> **Updated 2026-05-21** — Oracle UI removed, Feed CLS eliminated, agent-provider sidecar documented.
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

### 3.2 Backend — 3-process split + Node sidecar

| Process | Port | Module | Audience |
|---|---|---|---|
| Consumer + admin API | 8001 | `app.main:app` | Frontend SPA |
| Agent x402 paid API | 8002 | `app.agent_main:app` | AI agents (USDC-on-Base) |
| Background jobs | n/a | `app.scheduler_worker` | ~12 cron-like jobs |
| Agent Provider (Node) | 8003 | `backend/agent-provider/src/server.ts` | n-payment SDK streaming + payment gate |

#### Agent Provider Sidecar (added 2026-05-20)

TypeScript Node.js service using n-payment SDK. Handles streaming payment sessions,
settlement via `settler.ts`, and exposes MCP-compatible tools (`tools.ts`).
Managed via PM2 (`ecosystem.config.cjs`). Shares the same Postgres DB.

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
- `goat_payment.py` — GOAT testnet x402 rail (chain 48816, prefix `/goat-api/*`). Buyer-direct **verify-only** paywall: buyer signs+broadcasts the ERC-20 transfer themselves, retries with `X-Payment-Tx: <hash>`, verifier reads receipt and matches the Transfer log. **No facilitator dependency.** Default token = WGBTC (`0xbC10…0000`) since USDC isn't issued on goat-testnet3; configurable via `GOAT_X402_TOKEN_*`. USD prices converted to token wei via static `GOAT_X402_TOKEN_USD_PRICE`. Mirrors the proven `agent-provider/src/paywall.ts` Arb Sepolia pattern in pure Python.
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

### GOAT testnet rail (additive, verify-only)

When `GOAT_X402_ENABLED=true`, the same routes are exposed under `/goat-api/api/v2/agent/*` on goat-testnet3 (chainId 48816). Same USD prices, settled in **WGBTC** (`0xbC10000000000000000000000000000000000000`) by default since USDC is not issued on goat-testnet3. Override the token via `GOAT_X402_TOKEN_ADDRESS` / `_SYMBOL` / `_DECIMALS` if Circle ships USDC there.

The protocol is buyer-direct, no facilitator: buyers fetch a `payment-required` envelope, broadcast the ERC-20 transfer themselves, then retry the request with header `X-Payment-Tx: <hash>`. Reference buyer flow ships in [`payment/agent-payment/scripts/x402-pay.mjs`](../../payment/agent-payment/scripts/x402-pay.mjs).

Smoke: `bash scripts/smoke-goat-x402.sh https://ai.overguild.com/agent-api`.
Live e2e (requires funded WGBTC wallet): `node /path/to/agent-payment/scripts/x402-pay.mjs https://ai.overguild.com/agent-api/goat-api/api/v2/agent/decisions <wallet>`.

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

---

## 10. Design Principles (UX Invariants)

These are hard rules. Violating them re-introduces the CLS and broken-copy bugs we fixed 2026-05-21.

1. **No naked empty states.** Every loading/empty surface must either show a skeleton of the same dimensions or render nothing (not a partial element that later grows). System status ("Oracle hasn't woken up") must never leak to users as personality copy.

2. **Reserve space for async content.** Any element that depends on a network fetch must occupy its final dimensions from first paint. Use fixed-height slots, skeletons, or `min-h-[Xpx]` containers. Never let a resolved fetch push surrounding content.

3. **Single root container per route.** Each page has ONE root layout shell. Card-type-specific content renders inside a fixed-size slot within that shell. Never use multiple `return` branches with different root containers — that causes CLS on content-type transitions.

4. **Expand/disclosure UIs overlay, not push.** When the user taps to see more detail (analysis panels, expanded cards), the detail renders as a bottom-sheet or modal overlay (`position: fixed`). It must NOT grow the parent element in normal document flow.

5. **Persona-first copy.** User-facing text must sound intentional and on-brand. If a backend state is "no data yet", the frontend either hides the element entirely or shows a brand-consistent placeholder — never a developer-facing status message.

---

## 11. Deleted UI Components (2026-05-21)

| Component | Reason | Backend impact |
|---|---|---|
| `OracleWidget` | Awkward copy ("Oracle is feeling Sleeping"), CLS source, low user value | None — `degen_oracle.py` still powers paid `/api/v2/agent/context`. Consumer endpoints `/api/oracle/mood` and `/api/oracle/takes` removed from `:8001`. |


---

## 12. LP Cards — Liquidity Pools mode (added 2026-06-01)

**Wedge:** the swipe primitive turns prediction-only cards into composable on-chain *positions*. LP cards are the first persistent asset Kinetic mints into the user's wallet (predictions are ephemeral; LP NFTs sit there earning fees).

**Feed picker.** `FEED_MODES` now exposes `tokens` + `liquidity_pools`; the legacy `news` mode is `hidden: true` — it's still reachable via `?mode=news` for QA but is filtered out of the picker UI by `VISIBLE_FEED_MODES`. News cards keep generating (insight/macro_desk/whale_alert/index/etc.) and continue to feed the paid agent API on Base unchanged.

**LP card pipeline.** `lp_advisory.py` runs every 15 min and writes `card_type='pool'` rows. Each pool card is enriched (via `pool_enrichment(p)`) with 10 new columns:

| Column | Source |
|---|---|
| `token0_address`, `token1_address` | DefiLlama `underlyingTokens[0..1]` |
| `token0_symbol`, `token1_symbol` | DefiLlama `symbol` split on `-` / `/` |
| `token0_decimals`, `token1_decimals` | `_KNOWN_DECIMALS` map (USDC/USDT=6, WBTC=8, else 18) |
| `pool_address` | DefiLlama `pool` |
| `chain_id` | `dex_links._CHAIN_ID` map (DefiLlama chain string → numeric) |
| `dex_link` | `dex_links.build_dex_link(p)` — top-5 DEX templates + DefiLlama fallback |
| `volatility_7d_sigma` | `volatility.compute_sigma_7d(symbol)` — daily σ of log-returns from CoinGecko hourly market_chart, 30-min cache |

**Range presets.** `[Pₘᵢₙ, Pₘₐₓ] = [P · (1 − k·σ), P · (1 + k·σ)]` with k ∈ {2.0, 1.0, 0.5} (Conservative / Balanced / Aggressive). When σ is unavailable, fixed bands ±15/7/3% are used. Clamped at σ ≤ 0.5 to bound degenerate inputs. Both backend (`lp_math.range_for_preset`) and frontend (`useLpRange`) implement the same constants — keep them in sync if you change one.

**Endpoints.**

| Route | Auth | Notes |
|---|---|---|
| `GET /api/cards/{id}/lp-recipe?amount_a=&preset=` | none | Consumer endpoint used by `LpConfigurator`. |
| `GET /api/v2/agent/lp-recipes?pool_card_id=&amount_a=&preset=` | x402 | Paid mirror, $0.005, `type: liquidity_recipe`. Bazaar-indexed via `x402_payment.RESOURCE_DESCRIPTIONS`. |

**ZAP path.** `xlayer.is_pair_supported(token0, token1, chain_id)` decides between two CTAs:
- **Supported (today: only `OKB/USDC` on chain 1952/196)** → "ZAP INTO POOL" calls `useSummonTransaction.summon(card)` which posts to `/api/cards/{id}/play` and executes the existing approve+approve+playCard bundle on X Layer V4. Tick conversion uses `xlayer.compute_range_ticks(min_price, max_price)` — tick-spacing 60.
- **Unsupported** → "OPEN ON DEX" opens `card.dex_link` in a new tab. Uniswap V3 / PancakeSwap V3 / Aerodrome / Curve / Balancer V2 deep-links are pre-built; everything else falls back to `https://defillama.com/yields/pool/{pool_id}`.

**Module map.**

```
backend/app/
  volatility.py    pure σ_7d helper, http_client routed, 30-min cache
  dex_links.py     top-5 DEX templates + DefiLlama fallback + _CHAIN_ID map
  lp_math.py       pure quote math (derive_token_b, range_for_preset, PRESETS, FIXED_BANDS)
  lp_advisory.py   pool_enrichment(p) + generate_lp_advisories (scheduler 15-min job)
  lp_recipe.py     glue: build_recipe(card, amount_a, preset) — used by both routes
  xlayer.py        + is_pair_supported, + compute_range_ticks
  agent_api.py     + /lp-recipes route ($0.005)
  x402_payment.py  + RESOURCE_PRICES["GET /api/v2/agent/lp-recipes"]
  db.py            + 10 nullable cards columns; insert_card persists them
  content_engine.py harvest_pools merges pool_enrichment lazily

frontend/src/
  config/cardModes.ts          + hidden flag, + liquidity_pools mode, + VISIBLE_FEED_MODES
  components/ModePicker.tsx    filters by VISIBLE_FEED_MODES
  components/LpBattleCard.tsx  feed-style pool card (token-pair header + range overlay)
  components/LpConfigurator.tsx full-screen sheet (Token-A input → Token-B readout → ZAP/DEX)
  hooks/useLpRange.ts          pure preset → {min, max} (mirrors lp_math)
  hooks/useLpQuote.ts          react-query → /api/cards/{id}/lp-recipe
  hooks/useERC20Balance.ts     chain-aware balanceOf reader (10 chain RPC table)
  hooks/useCards.ts            Card type extended with the 10 LP fields
  pages/Feed.tsx               pool branch → LpBattleCard; LpConfigurator portal
```

**Growth metric.** LP positions opened / week. Leading indicators: % of LP-mode swipes that reach the Configurator, % of Configurator opens that ZAP. Track via the same `agent_predictions` table with a future `position_kind='lp'` column.

**Out of scope for v1.** Position monitoring (handled by existing `position_monitor` job for trading cards; LP positions can reuse it once the v4 Position NFT is queried), IL alerts, multi-chain ZAP (only X Layer for now), in-app rebalancing, "BATTLE RANK" — pool cards order by `created_at DESC` like every other mode.

---

## 13. Trading Signal Cards — SoDex perps mode (added 2026-06-02)

**Wedge:** the SoSoValue Buildathon competitor field (16 projects) all builds the same loop (SoSoValue → AI → SoDex). None has a track record. Trading-Signal cards expose Kinetic's 5,816-prediction track record as a closed loop: AI verdict → tap → real testnet perps order on SoDex.

**Feed picker.** `FEED_MODES` adds a third visible mode `trading_signal` (`⚡ Trading Signals`). News mode remains hidden.

**Card pipeline.** `trading_signal_engine.py` runs every 10 min and writes `card_type='trading_signal'` rows for 10 curated assets:

| Asset | SoDex perps pair |
|---|---|
| BTC | vBTC_vUSDC |
| ETH | vETH_vUSDC |
| SOL | vSOL_vUSDC |
| AVAX | vAVAX_vUSDC |
| SUI | vSUI_vUSDC |
| ARB | vARB_vUSDC |
| OP | vOP_vUSDC |
| LINK | vLINK_vUSDC |
| INIT | vINIT_vUSDC |
| ATOM | vATOM_vUSDC |

Each card carries verdict + confidence + entry/target/stop where target = mark · (1 + 2σ_7d) and stop = mark · (1 − σ_7d), flipped for shorts. σ clamped 0.5–20% daily; fallback 3% when CoinGecko has no data.

**Endpoints.**

| Route | Auth | Notes |
|---|---|---|
| `GET /api/cards?card_type=trading_signal` | none | Standard list query (already supported). |
| `POST /api/cards/{id}/execute` | none | Body `{address}`. Thin HTTP adapter over `trading_signal_engine.safe_execute`. On success: writes a `trades` row (with `side`, `sodex_order_id`, `execution_type='sodex_perps'`) AND a `swipes` row with `action='execute'`. |
| `GET /api/positions/{address}` | none | **Per-user** open SoDex positions, sourced from `trades` (where `sodex_order_id IS NOT NULL AND resolved=FALSE`), enriched with live mark for unrealized PnL. **NEVER pass a user wallet address to SoDex's `/accounts/{addr}/state` — that endpoint only knows the master signer.** |
| `GET /api/sodex/pool` | none | SoDex master-account vUSDC + free margin via the **public** `/accounts/{addr}/state` (no auth, no signing). Independent of `sodex_enabled` — the master address comes from `settings.sodex_master_address` (default = the testnet master `0x100690a32B562fd45e685BC2E63bbfF566d452db`). 30-s in-memory cache. Powers the Profile "SoDex Trading Pool" panel. |

> **Address invariant — every endpoint that reads or writes by user address MUST call `normalize_address` first.** Backend `normalize_address` returns EIP-55 checksummed hex (`Web3.to_checksum_address`); FE `normalizeAddress` returns lowercase hex; the backend is the canonical store, so the backend converts inbound lowercase → checksummed before hitting the DB. The earlier "trade not visible in Portfolio" bug was caused by `/api/cards/{id}/execute` skipping this step. `_ensure_runtime_columns` now back-fills any rows still stuck in lowercase, idempotently, on every startup.

**5-layer guards in `safe_execute`** (defense in depth):
1. `SODEX_TRADING_ENABLED=true` (global kill-switch).
2. `card_type == 'trading_signal'`.
3. Symbol ∈ `TARGET_ASSETS` (SoDex pair whitelist).
4. Idempotency — one `(card_id, user_address)` execute ever (existing `trades.sodex_order_id`).
5. Daily cap — `SODEX_DAILY_EXECUTES_PER_USER` (default 5) within 24h.

**Risk caps** (Wave-2 demo posture): notional ≤ `SODEX_MAX_ORDER_USD` ($25), leverage ≤ `SODEX_MAX_LEVERAGE` (2x), order is always IOC market `type=2 timeInForce=3`.

**SoDex spec compliance.** `sodex_client.py` follows the latest published spec exactly:
- `X-API-Key` carries the API-key **NAME** string (not address).
- `payloadHash = keccak256(json.Marshal({"type": <action>, "params": {...}}))` — full envelope, compact JSON, struct-field order preserved.
- Casing: `accountID`, `symbolID`. DecimalString fields are JSON strings; enum fields are ints.
- Domain: `name="futures"` for perps; testnet `chainId=138565`, mainnet `286623`.
- `0x01` typed-signature prefix.

**Module map.**

```
backend/app/
  sodex_client.py            REWRITTEN  EIP-712 signing per latest spec; pure mechanism
  trading_signal_engine.py   NEW        build_signal_card + safe_execute (5 guards)
  scheduler.py               +5 LOC     trading_signal_gen 10-min job
  main.py                    +25 LOC    POST /api/cards/{id}/execute
  config.py                  +9 LOC     sodex_api_key_name/_privkey/_max_leverage/_daily/_trading_enabled/_target_assets
  db.py                      0          reuses existing trades.sodex_order_id + .execution_type cols

frontend/src/
  config/cardModes.ts        +6 LOC     trading_signal mode entry
  components/TradingSignalCard.tsx  NEW  118 LOC  feed-style card; LONG/SHORT badge + entry/target/stop grid + ⚡EXECUTE CTA
  hooks/useExecuteSignal.ts  NEW        52 LOC   react-query mutation
  pages/Feed.tsx             +12 LOC    one branch in card-type switch + handleExecute
```

**Resolution.** Reuses the existing `position_monitor` 10-min scheduler job and `update_trade_pnl` — SoDex trades hit the same `trades` table so the standard 24h close path covers them. Portfolio + History pages show them automatically:

- **Portfolio** — "Live SoDex Positions" panel renders rows from `GET /api/positions/{address}` (per-user, DB-derived).
- **Profile** — "SoDex Trading Pool" panel renders from `GET /api/sodex/pool` (master, cached 30 s).
- **History** — `swipes.action='execute'` rows render with a purple ⚡ badge alongside ape/fade.
- **Cache invalidation** — `Feed.handleExecute` invalidates `['trades', address]`, `['sodex-positions', address]`, `['sodex-pool']`, `['history', address]` on success so the surfaces refresh without a manual reload.

**Telemetry.** `/api/health.circuits` auto-includes `"sodex"` when its breaker opens (all SoDex HTTP routes through `http_client` with `service="sodex"`).

**Out of scope for v1.** Per-card leverage (fixed 2x), short execution (long-only via APE; FADE just records the prediction without an order), TP/SL orders (we resolve client-side via 24h horizon), Privy MPC client-side signing (Day-9 of the 14-day sprint), multi-rail execution beyond SoDex (deferred to LiFi integration).

**Wave-2 deploy checklist.**
```bash
# 1. Backend env (essential):
SODEX_ENABLED=true
SODEX_TRADING_ENABLED=false     # flip to true only during live demo
SODEX_API_KEY_NAME=kinetic-bot-01
SODEX_API_KEY_PRIVKEY=0x...     # API-key signer; NOT master wallet
SODEX_ACCOUNT_ID=12345
SODEX_CHAIN_ID=138565           # testnet
SODEX_MAX_ORDER_USD=25
SODEX_MAX_LEVERAGE=2
SODEX_DAILY_EXECUTES_PER_USER=5

# 2. Smoke (optional — gated):
RUN_SODEX_LIVE=1 pytest backend/tests/

# 3. Restart backend:
bash ~/signal-backend/restart_signal.sh
```


---

## 14. Verifiable Trade History + Vault Strategy Cards (added 2026-06-06)

**Wedge.** Two complementary upgrades shipping together:
1. Every executed SoDex trade now exposes click-through proof links — pair page, user portfolio, on-chain explorer, plus the live fills list pulled from SoDex's own API.
2. A new `card_type='vault'` rides inside the existing 🌊 Liquidity Pools mode (no fourth feed mode) so users can swipe to allocate funding to SoDex's two yield vaults (SLP + sMAG7.ssi).

### 14.1 Verifiable links

`backend/app/sodex_links.py` — pure URL builder + composite payload (uses an injected fills fetcher; no I/O for URL pieces). `sodex_client.fetch_fills_for_order` calls SoDex's unsigned `/accounts/{master}/trades?orderID=` and prunes to public-safe fields (`price`, `qty`, `fee`, `ts`, `side`), 60-s in-process cached. `GET /api/trades/{id}/sodex-links` (404 for non-SoDex trades) and `GET /api/v2/agent/decisions[*].sodex_url` (paid agent surface) both consume it.

URL truth table (`https://sodex.com/...`):
- pair (perps): `/trade/futures/{BASE}_USDC`
- pair (spot):  `/trade/spot/{BASE}_USDC`
- portfolio:    `/portfolio` (login-gated, per-user)
- explorer:     `/explorer?blocktype={futures|spot}` (ValueChain native)

FE primitive `frontend/src/components/SodexLinks.tsx` — three icon-buttons + lazy fills toggle, builds a symbol-only payload offline so position rows render instantly without a backend round-trip. Wired into `History.tsx` (per ⚡ EXECUTE row, with `trade_id` for fills) and `Portfolio.tsx` (per Live SoDex Position row, symbol-only mode). `db.get_user_swipes` was extended with a LEFT JOIN to `trades` so each swipe row carries the matching `trade_id` + `execution_type` + `sodex_order_id` for FE wiring.

### 14.2 Vault Strategy Cards

`backend/app/vault_advisor.py` — static descriptors for SoDex's 2 vaults (SLP and sMAG7.ssi) plus an idempotent `generate_vault_cards()` upsert keyed on `(card_type='vault', source='sodex', token_symbol)`. Scheduler runs it every 30 min. Per the SoDex Trading API spec, vaults have **no programmatic deposit endpoint** — the only honest mechanism is a deep-link to `https://sodex.com/portfolio?vault={kind}` that the user finishes with a wallet-signed deposit on SoDex's UI.

| Field | SLP | sMAG7.ssi |
|---|---|---|
| Accepted | MAG7.ssi · sMAG7.ssi | sMAG7.ssi |
| Lockup | Instant for sMAG7.ssi · 14-day for MAG7.ssi | Instant |
| Yield sources | Index staking + MM rebate + SOSO airdrop | MAG7 index exposure + MM rebate + SOSO airdrop |
| Min deposit | $50 | $50 |
| Risk score | 35 | 30 |

Routes:
- `POST /api/cards/{id}/allocate-vault` body `{address, intent_amount_usd}` → returns `{allocation_id, target_url, vault_kind, status:"pending"}`. Validates `card_type=='vault'` + min deposit. 409 on duplicate per UTC day.
- `POST /api/vault-allocations/{id}/confirm` body `{address}` → flips `pending → confirmed` only when owned by the calling address.
- `GET /api/cards/user/{address}` (existing) now merges `vault_allocations` rows with synthetic `action='allocate'` so they appear in the History timeline next to ape/fade/execute.

Schema — single new table, auto-created at startup via `init_lp_transactions_table` (same pattern as `lp_transactions`):

```sql
CREATE TABLE vault_allocations (
  id SERIAL PRIMARY KEY,
  user_address       TEXT NOT NULL,
  card_id            INTEGER NOT NULL,
  vault_kind         TEXT NOT NULL,                 -- 'slp' | 'smag7'
  intent_amount_usd  NUMERIC(18,2) NOT NULL,
  target_url         TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'pending',
  created_at         TIMESTAMPTZ DEFAULT NOW(),
  confirmed_at       TIMESTAMPTZ
);
CREATE UNIQUE INDEX vault_alloc_user_card_day_idx
  ON vault_allocations (user_address, card_id, ((created_at AT TIME ZONE 'UTC')::date));
```

FE pieces:
- `frontend/src/components/VaultStrategyCard.tsx` — feed card (⚓ VAULT pill, dual-yield labels, lockup banner, "ALLOCATE TO VAULT" CTA). Same fixed height as `LpBattleCard` to preserve CLS budget.
- `frontend/src/components/VaultConfigurator.tsx` — full-screen sheet, single USD input + summary + "OPEN ON SODEX" CTA.
- `frontend/src/hooks/useAllocateVault.ts` — `useAllocateVault` (POST + auto-`window.open(target_url)` on success) and `useConfirmAllocation`.
- `frontend/src/config/cardModes.ts` — `liquidity_pools.cardTypes = ['pool','vault']` (same mode picker, no fourth entry).
- `frontend/src/pages/Feed.tsx` — `card_type === 'vault'` branch + `vaultConfigCard` state.
- `frontend/src/pages/History.tsx` — ⚓ ALLOCATE row branch (PENDING/CONFIRMED pill + inline "Mark as deposited" button + "Open SoDex →" link).

**Module map (additions only).**

```
backend/app/
  sodex_links.py          NEW   pure URL builder + composite payload (DI fills fetcher)
  sodex_client.py         +     fetch_fills_for_order (60s cache, graceful empty)
  main.py                 +     /api/trades/{id}/sodex-links · /api/cards/{id}/allocate-vault · /api/vault-allocations/{id}/confirm · history merge
  agent_api.py            +     decisions[*].sodex_url
  db.py                   +     vault_allocations DDL · insert/confirm/list helpers · swipes JOIN trades
  vault_advisor.py        NEW   2 vault descriptors + idempotent generate_vault_cards
  scheduler.py            +     vault_advisor 30-min cron
backend/tests/
  test_sodex_links.py     NEW   16 cases (URL norm + composite payload graceful-degrade)
  test_vault_advisor.py   NEW   5 cases (descriptors + card-row mapping)

frontend/src/
  components/SodexLinks.tsx        NEW   3 icon-buttons + lazy fills toggle
  components/VaultStrategyCard.tsx NEW   feed card with ⚓ VAULT pill
  components/VaultConfigurator.tsx NEW   amount input + OPEN ON SODEX CTA
  hooks/useAllocateVault.ts        NEW   useAllocateVault + useConfirmAllocation
  pages/Feed.tsx                   +     vault branch + VaultConfigurator portal
  pages/History.tsx                +     ⚓ ALLOCATE row + confirm button
  pages/Portfolio.tsx              +     SodexLinks per Live SoDex Position
  config/cardModes.ts              +     liquidity_pools cardTypes includes 'vault'
```

**Out of scope for v1.** Programmatic vault deposit/withdraw (blocked on SoDex Trading API), automated MAG7.ssi acquisition, vault APR ingestion (no public API), in-app withdrawal flow, paid agent SKU for vault listings (rides on existing `/lp-recipes` mirror later), 14-day unstake countdown surface (Phase 2).
