"""LiFi cross-chain service — merged quote endpoint + intent relay + timeout watcher.

SOLID:
  - SRP: three logical surfaces in one module to share a single aiohttp
    session + Web3 provider + DB connection style.
      * `LifiQuoteHandler`  — paid GET /somnia-api/lifi-quote (x402 settled)
      * `LifiIntentRelay`   — polls SwipeCompleted events on Somnia and
        flips lifi_intents rows PENDING -> EXECUTED with proof URLs
      * `LifiTimeoutWatcher` — 60s tick, flips stale PENDING -> FAILED_REFUNDED
  - OCP: status-state-machine is enforced at the DB CHECK constraint.
    Adding new states = append-only DDL.
  - DIP: DB helpers in `app.db` (sync), HTTP via aiohttp, RPC via web3.py.
    Frontend reads status via REST (`GET /api/v3/lifi-intent/{id}`) which
    keeps the deploy stack simple — no WebSocket framework required.

Deploy posture:
  - All three components soft-disable via env flags. With LIFI_*_ENABLED=false
    the existing rails are byte-identical.
  - The relay is HTTP-polling (existing prophecy_event_poller pattern) — no
    WebSocket extra dep, works behind any proxy.

Testnet: paired with `MockLiFiCaller`. Mainnet: paired with the real LiFi
destination caller (DevRel-confirmed). One env flag (`KINETIC_NETWORK`) flips
all RPC + chain-id + URL bases.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from typing import Any, Optional

import aiohttp
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from web3 import Web3

from app import db
from app.config import get_settings

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────────────
SWIPE_COMPLETED_EVENT = (
    "SwipeCompleted(address,uint256,bytes32,uint256,bytes32)"
)
SWIPE_COMPLETED_TOPIC = Web3.keccak(text=SWIPE_COMPLETED_EVENT).hex()
EXECUTOR_ABI = [{
    "type": "event",
    "name": "SwipeCompleted",
    "anonymous": False,
    "inputs": [
        {"indexed": True,  "name": "user",             "type": "address"},
        {"indexed": True,  "name": "prophecyMarketId", "type": "uint256"},
        {"indexed": False, "name": "cardHash",         "type": "bytes32"},
        {"indexed": False, "name": "verdictId",        "type": "uint256"},
        {"indexed": False, "name": "lifiOriginTxHash", "type": "bytes32"},
    ],
}]
EXECUTE_FROM_LIFI_SELECTOR = Web3.keccak(
    text="executeFromLiFi(bytes,uint256,string,string,uint256,address)"
).hex()[:10]   # 0x + 4 bytes


# ─────────────────────────────────────────────────────────────────────
#  Pydantic response models
# ─────────────────────────────────────────────────────────────────────
class RouteSummary(BaseModel):
    provider: str
    estimated_seconds: int
    fees_usd: float
    slippage_bps: int


class TransactionRequest(BaseModel):
    to: str
    data: str
    value: str
    gas_limit: str


class LifiQuoteResponse(BaseModel):
    intent_id: str
    from_chain: int
    from_token: str
    to_chain: int
    to_token: str
    route_summary: RouteSummary
    transaction_request: TransactionRequest
    kinetic_destination_calldata: str


class LifiIntentStatusResponse(BaseModel):
    intent_id: str
    status: str
    verdict_id: Optional[int]
    verdict_str: Optional[str]
    card_hash: Optional[str]
    lifi_origin_tx_hash: Optional[str]
    dest_tx_hash: Optional[str]
    arbiscan_url: Optional[str]
    somnscan_url: Optional[str]
    prophecy_market_url: Optional[str]
    outcome_resolved: bool
    outcome_correct: Optional[bool]


# ─────────────────────────────────────────────────────────────────────
#  FastAPI router (LifiQuoteHandler + status read)
# ─────────────────────────────────────────────────────────────────────
router = APIRouter()
_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    return _session


@router.get("/somnia-api/lifi-quote", response_model=LifiQuoteResponse)
async def lifi_quote(
    fromChain: int = Query(..., gt=0),
    fromToken: str = Query(..., min_length=42, max_length=42),
    swipeStakeUsdc: int = Query(..., gt=0),
    prophecyMarketId: int = Query(..., gt=0),
    userAddress: str = Query(..., min_length=42, max_length=42),
    symbol: str = Query(..., min_length=1, max_length=20),
    context: str = Query(..., min_length=1, max_length=500),
) -> LifiQuoteResponse:
    """Paid endpoint ($0.001 via x402 somnia rail). Returns a signed-ready tx."""
    s = get_settings()
    if not s.lifi_quote_enabled:
        raise HTTPException(503, detail={"code": "RELAY_DISABLED"})

    if swipeStakeUsdc < s.default_min_swipe_stake_usdc:
        raise HTTPException(400, detail={
            "code": "STAKE_BELOW_MINIMUM",
            "minimum": s.default_min_swipe_stake_usdc,
        })

    bound = await asyncio.to_thread(db.is_prophecy_market_bound, prophecyMarketId)
    if not bound:
        raise HTTPException(404, detail={"code": "UNKNOWN_PROPHECY_MARKET"})

    if not s.prediction_card_lifi_executor_address:
        raise HTTPException(503, detail={"code": "EXECUTOR_NOT_DEPLOYED"})

    # Build the destination calldata. The first 32-byte slot is reserved for
    # the origin tx hash — LiFi populates it at delivery time, but for
    # simulator-driven testnet flows we keep a deterministic slot here.
    kinetic_calldata = _encode_destination_calldata(
        prophecy_market_id=prophecyMarketId,
        symbol=symbol,
        context=context,
        swipe_stake_usdc=swipeStakeUsdc,
        original_user=userAddress,
    )

    lifi_payload, used_stub = await _fetch_lifi_quote(
        from_chain=fromChain,
        from_token=fromToken,
        to_amount=swipeStakeUsdc,
        from_address=userAddress,
        to_address=s.prediction_card_lifi_executor_address,
        destination_calldata=kinetic_calldata,
    )

    intent_id = await asyncio.to_thread(
        db.insert_lifi_intent_pending,
        user_address=userAddress,
        prophecy_market_id=prophecyMarketId,
        origin_chain_id=fromChain,
        swipe_stake_usdc=swipeStakeUsdc,
        used_stub_quote=used_stub,
    )
    if intent_id is None:
        raise HTTPException(500, detail={"code": "DB_INSERT_FAILED"})

    return LifiQuoteResponse(
        intent_id=intent_id,
        from_chain=fromChain,
        from_token=fromToken,
        to_chain=50312 if s.kinetic_network == "testnet" else 5031,
        to_token=s.somnia_usdc_address or "0x0",
        route_summary=RouteSummary(
            provider=lifi_payload.get("tool", "stub"),
            estimated_seconds=int(lifi_payload.get("estimate", {}).get("executionDuration", 60)),
            fees_usd=_extract_fees_usd(lifi_payload),
            slippage_bps=int(lifi_payload.get("estimate", {}).get("slippageBps", 0)),
        ),
        transaction_request=TransactionRequest(
            to=lifi_payload.get("transactionRequest", {}).get("to", ""),
            data=lifi_payload.get("transactionRequest", {}).get("data", "0x"),
            value=str(lifi_payload.get("transactionRequest", {}).get("value", "0")),
            gas_limit=str(lifi_payload.get("transactionRequest", {}).get("gasLimit", "300000")),
        ),
        kinetic_destination_calldata=kinetic_calldata,
    )


@router.get("/api/v3/lifi-intent/{intent_id}", response_model=LifiIntentStatusResponse)
async def get_lifi_intent_status(intent_id: str) -> LifiIntentStatusResponse:
    """Frontend polls this every 2s until status is EXECUTED|FAILED_REFUNDED."""
    intent = await asyncio.to_thread(db.get_lifi_intent, intent_id)
    if intent is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    # JIT verdict resolver — same lazy population as the history endpoint.
    if intent.verdict_str is None and intent.verdict_id is not None and intent.status == "EXECUTED":
        verdict = await asyncio.to_thread(_read_verdict_str_from_chain, int(intent.verdict_id))
        if verdict:
            await asyncio.to_thread(db.update_lifi_intent_verdict_str, intent.intent_id, verdict)
            intent.verdict_str = verdict
    return LifiIntentStatusResponse(
        intent_id=intent.intent_id,
        status=intent.status,
        verdict_id=intent.verdict_id,
        verdict_str=intent.verdict_str,
        card_hash=intent.card_hash,
        lifi_origin_tx_hash=intent.lifi_origin_tx_hash,
        dest_tx_hash=intent.dest_tx_hash,
        arbiscan_url=intent.arbiscan_url,
        somnscan_url=intent.somnscan_url,
        prophecy_market_url=intent.prophecy_market_url,
        outcome_resolved=intent.outcome_resolved,
        outcome_correct=intent.outcome_correct,
    )


@router.post("/api/v3/lifi-intent/{intent_id}/origin-tx")
async def report_origin_tx(intent_id: str, tx_hash: str = Query(..., min_length=66, max_length=66)) -> dict:
    """Frontend reports the user-signed origin tx hash so the relay can correlate.

    Testnet auto-sim: if the intent used a stub-quote (LiFi has no route on
    testnet), fire `MockLiFiCaller.simulateLifiDelivery` server-side so the
    end-to-end UX completes without manual intervention. Mainnet path is
    untouched — the real LiFi solver delivers and the relay watches events.
    """
    s = get_settings()
    arbiscan_url = f"{s.arbiscan_tx_base_url}{tx_hash}"
    await asyncio.to_thread(db.set_lifi_intent_origin_tx, intent_id, tx_hash, arbiscan_url)

    # Auto-sim guard: testnet + stub-quote intent + simulator + signing key all set.
    intent = await asyncio.to_thread(db.get_lifi_intent, intent_id)
    if (
        intent is not None
        and intent.used_stub_quote
        and s.kinetic_network == "testnet"
        and s.mock_lifi_caller_address
        and s.private_key
    ):
        try:
            await asyncio.to_thread(_trigger_mock_lifi_delivery, intent, tx_hash)
        except Exception as e:                                    # noqa: BLE001
            log.warning("auto-sim trigger for %s failed: %s", intent_id, e)

    return {"intent_id": intent_id, "tx_hash": tx_hash, "arbiscan_url": arbiscan_url}


@router.get("/api/v3/lifi-intents/by-user/{user_address}")
async def list_lifi_intents_by_user(user_address: str, limit: int = Query(default=50, le=100)) -> dict:
    """Cross-chain swipe history surface. JIT-fills `verdict_str` from chain
    for any executed intent that doesn't have it yet (lazy population).
    """
    rows = await asyncio.to_thread(db.find_lifi_intents_by_user, user_address, limit)
    out = []
    for r in rows:
        if r.verdict_str is None and r.verdict_id is not None and r.status == "EXECUTED":
            verdict = await asyncio.to_thread(_read_verdict_str_from_chain, int(r.verdict_id))
            if verdict:
                await asyncio.to_thread(db.update_lifi_intent_verdict_str, r.intent_id, verdict)
                r.verdict_str = verdict
        out.append({
            "intent_id":           r.intent_id,
            "prophecy_market_id":  r.prophecy_market_id,
            "swipe_stake_usdc":    r.swipe_stake_usdc,
            "status":              r.status,
            "verdict_id":          r.verdict_id,
            "verdict_str":         r.verdict_str,
            "outcome_resolved":    r.outcome_resolved,
            "outcome_correct":     r.outcome_correct,
            "card_hash":           r.card_hash,
            "lifi_origin_tx_hash": r.lifi_origin_tx_hash,
            "dest_tx_hash":        r.dest_tx_hash,
            "arbiscan_url":        r.arbiscan_url,
            "somnscan_url":        r.somnscan_url,
            "prophecy_market_url": r.prophecy_market_url,
            "created_at":          r.created_at.isoformat() if r.created_at else None,
            "executed_at":         r.executed_at.isoformat() if r.executed_at else None,
            "outcome_resolved_at": r.outcome_resolved_at.isoformat() if r.outcome_resolved_at else None,
        })
    return {"intents": out, "total": len(out)}


# ─────────────────────────────────────────────────────────────────────
#  Auto-sim + JIT verdict helpers (sync — wrapped via asyncio.to_thread)
# ─────────────────────────────────────────────────────────────────────
_SIMULATE_ABI = [{
    "type": "function",
    "name": "simulateLifiDelivery",
    "stateMutability": "payable",
    "inputs": [
        {"name": "lifiOriginTxHash",  "type": "bytes32"},
        {"name": "extraLifiData",     "type": "bytes"},
        {"name": "prophecyMarketId",  "type": "uint256"},
        {"name": "symbol",            "type": "string"},
        {"name": "context",           "type": "string"},
        {"name": "swipeStakeUsdc",    "type": "uint256"},
        {"name": "originalUser",      "type": "address"},
    ],
    "outputs": [],
}]
_GET_VERDICT_ABI = [{
    "type": "function",
    "name": "getVerdict",
    "stateMutability": "view",
    "inputs": [{"name": "verdictId", "type": "uint256"}],
    "outputs": [{
        "name": "",
        "type": "tuple",
        "components": [
            {"name": "requester",      "type": "address"},
            {"name": "symbol",         "type": "string"},
            {"name": "verdictStr",     "type": "string"},
            {"name": "router",         "type": "address"},
            {"name": "routerCalldata", "type": "bytes"},
            {"name": "status",         "type": "uint8"},
            {"name": "timestamp",      "type": "uint256"},
        ],
    }],
}]


def _trigger_mock_lifi_delivery(intent: db.LifiIntent, origin_tx_hash: str) -> None:
    """Backend-signed call into MockLiFiCaller. Testnet only — guarded by caller."""
    s = get_settings()
    rpc_url = s.somnia_testnet_rpc
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))
    account = w3.eth.account.from_key(s.private_key)
    mock = w3.eth.contract(
        address=Web3.to_checksum_address(s.mock_lifi_caller_address),
        abi=_SIMULATE_ABI,
    )
    # Per-card platform deposit (~0.12 STT — read-tolerant default)
    deposit_wei = w3.to_wei(0.12, "ether")
    # Need card details — read from DB by intent
    card_row = _fetch_intent_swipe_payload(intent)
    if card_row is None:
        log.warning("auto-sim: no card row for intent %s — skipping", intent.intent_id)
        return
    tx = mock.functions.simulateLifiDelivery(
        bytes.fromhex(origin_tx_hash[2:]),
        b"",
        int(intent.prophecy_market_id),
        card_row["symbol"],
        card_row["context"],
        int(intent.swipe_stake_usdc),
        Web3.to_checksum_address(intent.user_address),
    ).build_transaction({
        "from":     account.address,
        "nonce":    w3.eth.get_transaction_count(account.address, "pending"),
        "chainId":  50312,
        "gas":      600_000,
        "gasPrice": w3.eth.gas_price or 1_000_000_000,
        "value":    deposit_wei,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    log.info("auto-sim fired for intent=%s mock_tx=%s", intent.intent_id, tx_hash[:12])


def _fetch_intent_swipe_payload(intent: db.LifiIntent) -> Optional[dict]:
    """Read the original swipe symbol+context from the bound card row."""
    if intent.card_id is None:
        # Fall back to using the prophecy market id as symbol (rare path)
        return {"symbol": "BTC", "context": f"prophecy:{intent.prophecy_market_id}"}
    conn = db._get_conn()
    if not conn:
        return None
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT token_symbol, hook FROM cards WHERE id = %s",
                (int(intent.card_id),),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"symbol": row["token_symbol"], "context": (row.get("hook") or "")[:200]}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _read_verdict_str_from_chain(verdict_id: int) -> Optional[str]:
    """View-call SomniaSignalAgent.getVerdict(verdictId).verdictStr.
    Returns "APE"|"FADE"|None. Used by the history endpoint for JIT lookups."""
    s = get_settings()
    rpc_url = s.somnia_testnet_rpc if s.kinetic_network == "testnet" else s.somnia_mainnet_rpc
    if not s.somnia_signal_agent_address:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        agent = w3.eth.contract(
            address=Web3.to_checksum_address(s.somnia_signal_agent_address),
            abi=_GET_VERDICT_ABI,
        )
        verdict = agent.functions.getVerdict(int(verdict_id)).call()
        # Tuple shape: (requester, symbol, verdictStr, router, calldata, status, timestamp)
        verdict_str = verdict[2]
        if verdict_str in ("APE", "FADE"):
            return verdict_str
    except Exception as e:                                            # noqa: BLE001
        log.debug("getVerdict(%d) RPC view failed: %s", verdict_id, e)
    return None


# ─────────────────────────────────────────────────────────────────────
#  LiFi /v1/quote helpers
# ─────────────────────────────────────────────────────────────────────
def _encode_destination_calldata(
    *,
    prophecy_market_id: int,
    symbol: str,
    context: str,
    swipe_stake_usdc: int,
    original_user: str,
) -> str:
    """Encode the executor's executeFromLiFi(...) calldata. The first 32 bytes
    of `lifiData` are reserved for the origin tx hash; LiFi (or the simulator)
    fills them at delivery time."""
    from eth_abi import encode as abi_encode

    lifi_data_placeholder = b"\x00" * 32
    encoded = abi_encode(
        ["bytes", "uint256", "string", "string", "uint256", "address"],
        [lifi_data_placeholder, prophecy_market_id, symbol, context,
         swipe_stake_usdc, Web3.to_checksum_address(original_user)],
    )
    return EXECUTE_FROM_LIFI_SELECTOR + encoded.hex()


def _extract_fees_usd(payload: dict) -> float:
    fee_costs = payload.get("estimate", {}).get("feeCosts", []) or []
    if not fee_costs:
        return 0.0
    try:
        return float(fee_costs[0].get("amountUSD", 0.0))
    except (TypeError, ValueError):
        return 0.0


async def _fetch_lifi_quote(
    *,
    from_chain: int,
    from_token: str,
    to_amount: int,
    from_address: str,
    to_address: str,
    destination_calldata: str,
) -> tuple[dict, bool]:
    """Returns (payload, used_stub_quote). The flag drives auto-sim on testnet."""
    s = get_settings()
    to_chain = 50312 if s.kinetic_network == "testnet" else 5031
    params = {
        "fromChain": from_chain,
        "toChain": to_chain,
        "fromToken": from_token,
        "toToken": s.somnia_usdc_address or "USDC",
        "fromAddress": from_address,
        "toAddress": to_address,
        "toAmount": str(to_amount),
        "destinationCallData": destination_calldata,
        "order": "FASTEST",
    }
    session = await _get_session()
    try:
        async with session.get(f"{s.lifi_api_base}/quote", params=params) as resp:
            if resp.status == 404:
                if s.kinetic_network == "testnet":
                    return _stub_quote(to_address, destination_calldata), True
                raise HTTPException(404, detail={"code": "NO_LIFI_ROUTE"})
            if resp.status != 200:
                body = await resp.text()
                log.warning("LiFi non-2xx %d: %s", resp.status, body[:200])
                if s.kinetic_network == "testnet":
                    return _stub_quote(to_address, destination_calldata), True
                raise HTTPException(502, detail={"code": "LIFI_UPSTREAM_ERROR"})
            return await resp.json(), False
    except aiohttp.ClientError as e:
        log.warning("LiFi /quote network error: %s", e)
        if s.kinetic_network == "testnet":
            return _stub_quote(to_address, destination_calldata), True
        raise HTTPException(502, detail={"code": "LIFI_UPSTREAM_ERROR"})


def _stub_quote(to_address: str, destination_calldata: str) -> dict:
    """Fallback shape for testnet when LiFi has no route coverage. The
    transactionRequest points to the destination address with the kinetic
    calldata so the simulator can exercise the same UX path on real RPC."""
    return {
        "tool": "kinetic-testnet-stub",
        "estimate": {"executionDuration": 30, "feeCosts": [{"amountUSD": 0.0}], "slippageBps": 0},
        "transactionRequest": {
            "to": to_address,
            "data": destination_calldata,
            "value": "0",
            "gasLimit": "300000",
        },
    }


# ─────────────────────────────────────────────────────────────────────
#  LifiIntentRelay — HTTP-poll on Somnia for SwipeCompleted events
# ─────────────────────────────────────────────────────────────────────
class LifiIntentRelay:
    """Single-instance background task. Polls SwipeCompleted logs from the
    deployed PredictionCardLiFiExecutor every `lifi_relay_poll_seconds` and
    flips matching `lifi_intents` rows to EXECUTED with proof URLs."""

    def __init__(self) -> None:
        s = get_settings()
        self.executor_address = s.prediction_card_lifi_executor_address
        self.rpc_url = (
            s.somnia_testnet_rpc if s.kinetic_network == "testnet" else s.somnia_mainnet_rpc
        )
        self.poll_seconds = max(2, s.lifi_relay_poll_seconds)
        self._w3: Optional[Web3] = None
        self._last_block: Optional[int] = None

    def _web3(self) -> Web3:
        if self._w3 is None:
            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 8}))
        return self._w3

    async def run(self) -> None:
        s = get_settings()
        if not s.lifi_relay_enabled or not self.executor_address:
            log.info("LifiIntentRelay disabled or executor address unset")
            return
        log.info("LifiIntentRelay running on %s (executor=%s)", self.rpc_url, self.executor_address)
        while True:
            try:
                await asyncio.to_thread(self._poll_once)
            except Exception as e:                                          # noqa: BLE001
                log.warning("LifiIntentRelay tick failed: %s", e)
            await asyncio.sleep(self.poll_seconds)

    def _poll_once(self) -> None:
        w3 = self._web3()
        head = w3.eth.block_number
        if self._last_block is None:
            self._last_block = max(0, head - 200)   # backfill ~200 blocks on cold start
        from_block = self._last_block + 1
        if from_block > head:
            return
        executor = w3.eth.contract(
            address=Web3.to_checksum_address(self.executor_address),
            abi=EXECUTOR_ABI,
        )
        events = executor.events.SwipeCompleted.get_logs(
            from_block=from_block, to_block=head
        )
        for ev in events:
            self._process_event(ev)
        self._last_block = head

    def _process_event(self, ev: Any) -> None:
        s = get_settings()
        args = ev["args"]
        origin_tx = "0x" + args["lifiOriginTxHash"].hex() if isinstance(
            args["lifiOriginTxHash"], (bytes, bytearray)
        ) else args["lifiOriginTxHash"]
        intent = db.find_lifi_intent_by_origin_tx(origin_tx)
        if intent is None:
            log.info("SwipeCompleted for unknown origin_tx %s — skipping", origin_tx[:12])
            return
        if intent.status == "EXECUTED":
            return
        dest_tx_hash = ev["transactionHash"].hex() if hasattr(ev["transactionHash"], "hex") else str(ev["transactionHash"])
        if not dest_tx_hash.startswith("0x"):
            dest_tx_hash = "0x" + dest_tx_hash
        somnscan_url = f"{s.somnscan_tx_base_url}{dest_tx_hash}"
        prophecy_url = s.prophecy_market_url_template.format(id=int(args["prophecyMarketId"]))
        card_hash = "0x" + args["cardHash"].hex() if isinstance(
            args["cardHash"], (bytes, bytearray)
        ) else args["cardHash"]
        db.update_lifi_intent_executed(
            intent_id=intent.intent_id,
            verdict_id=int(args["verdictId"]),
            card_hash=card_hash,
            dest_tx_hash=dest_tx_hash,
            somnscan_url=somnscan_url,
            prophecy_market_url=prophecy_url,
        )
        log.info("Intent %s EXECUTED (verdict=%d, dest_tx=%s)",
                 intent.intent_id, int(args["verdictId"]), dest_tx_hash[:12])


# ─────────────────────────────────────────────────────────────────────
#  LifiTimeoutWatcher — flip stale PENDING -> FAILED_REFUNDED
# ─────────────────────────────────────────────────────────────────────
class LifiTimeoutWatcher:
    def __init__(self) -> None:
        self.tick_seconds = 60

    async def run(self) -> None:
        s = get_settings()
        if not s.lifi_relay_enabled:
            return
        log.info("LifiTimeoutWatcher running (timeout=%ds, tick=%ds)",
                 s.lifi_timeout_seconds, self.tick_seconds)
        while True:
            try:
                stale = await asyncio.to_thread(
                    db.find_lifi_intents_stale_pending, s.lifi_timeout_seconds
                )
                for intent in stale:
                    await asyncio.to_thread(
                        db.update_lifi_intent_status, intent.intent_id, "FAILED_REFUNDED"
                    )
                    log.warning("Intent %s timed out -> FAILED_REFUNDED", intent.intent_id)
            except Exception as e:                                          # noqa: BLE001
                log.warning("TimeoutWatcher tick failed: %s", e)
            await asyncio.sleep(self.tick_seconds)


# ─────────────────────────────────────────────────────────────────────
#  Lifecycle hooks (mounted from main.py)
# ─────────────────────────────────────────────────────────────────────
_relay: Optional[LifiIntentRelay] = None
_watcher: Optional[LifiTimeoutWatcher] = None
_relay_task: Optional[asyncio.Task] = None
_watcher_task: Optional[asyncio.Task] = None


def start_background() -> None:
    """Idempotent. Spawns the relay + timeout watcher tasks."""
    global _relay, _watcher, _relay_task, _watcher_task
    s = get_settings()
    if not s.lifi_relay_enabled:
        return
    if _relay is None:
        _relay = LifiIntentRelay()
    if _watcher is None:
        _watcher = LifiTimeoutWatcher()
    if _relay_task is None or _relay_task.done():
        _relay_task = asyncio.create_task(_relay.run(), name="lifi-relay")
    if _watcher_task is None or _watcher_task.done():
        _watcher_task = asyncio.create_task(_watcher.run(), name="lifi-timeout")


async def shutdown_background() -> None:
    global _session
    for t in (_relay_task, _watcher_task):
        if t is not None and not t.done():
            t.cancel()
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None
