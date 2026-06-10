"""Prophecy-aware card pipeline — turns prophecy.social markets into Kinetic cards.

SOLID:
- SRP: this module is the orchestrator. It reads typed `ProphecyMarket`
  objects from `prophecy_social_reader`, runs a deterministic verdict
  synthesizer, and persists via `db.insert_card`. Nothing else.
- OCP: `_synthesize_verdict` is the swap-point. v1 ships a deterministic
  rule (crowd-following). v2 will swap it for a Somnia LLM Inference
  call without touching any other function.
- DIP: depends on the reader's `ProphecyMarket` dataclass + the existing
  `db.insert_card` contract. No HTTP, no chain writes here. The on-chain
  bind to `KineticProphecyBridge` lands in Task 6 — gated by
  `settings.prophecy_bridge_address`, so this module remains usable
  pre-bridge-deploy.

Idempotency: a card already-generated for a `prophecy_market_id` is a
no-op (returns the existing id). Enforced at the DB layer via
`UNIQUE INDEX cards_prophecy_market_id_idx`.

Validation: the pipeline rejects RESOLVED / RESOLVING markets and any
market with deadline closer than `MIN_DEADLINE_HOURS` so swipers always
have time to react.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app import db, prophecy_social_reader as reader
from app.config import get_settings
from app.prophecy_social_reader import (
    MarketStatus,
    ProphecyCategory,
    ProphecyMarket,
)

log = logging.getLogger(__name__)

MIN_DEADLINE_MINUTES = 15
MAX_QUESTION_LENGTH = 280
DEFAULT_BATCH_LIMIT = 10

# Bridge ABI — only the function we actually call. Keeping the surface
# tiny avoids drift if the Solidity gains unrelated functions later.
_BRIDGE_BIND_ABI = [
    {
        "type": "function",
        "name": "bindMarketToCard",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "prophecyMarketId", "type": "uint256"},
            {"name": "cardHash", "type": "bytes32"},
        ],
        "outputs": [],
    }
]

_CATEGORY_LABELS = {
    ProphecyCategory.SPORTS:   "sports",
    ProphecyCategory.CRYPTO:   "crypto",
    ProphecyCategory.POLITICS: "politics",
    ProphecyCategory.CULTURE:  "culture",
}


# ─── Public API ──────────────────────────────────────────────────────


def generate_card_from_prophecy_market(market_id: int) -> Optional[int]:
    """Generate one Kinetic prediction card for a Prophecy market.

    Returns the cards.id (existing or new) on success, None if the market
    is not eligible (resolved, too soon, missing) or persistence failed.
    """
    existing = _existing_card_id(market_id)
    if existing is not None:
        return existing

    market = reader.fetch_market(market_id)
    if market is None or not _is_eligible(market):
        return None

    card = _build_card_row(market)
    try:
        cid = db.insert_card(card)
    except Exception as e:                            # noqa: BLE001
        # The unique index races a concurrent insert into a duplicate-key
        # error. Treat that as "someone beat us to it" and look it up.
        log.info("prophecy_card_pipeline: insert race for market %d (%s)", market_id, e)
        return _existing_card_id(market_id)
    if cid <= 0:
        return None
    log.info("prophecy_card_pipeline: generated card_id=%d for market_id=%d", cid, market_id)
    _bind_card_on_bridge(cid, market_id)
    return cid


def generate_cards_for_open_markets(
    category: Optional[ProphecyCategory] = None,
    limit: int = DEFAULT_BATCH_LIMIT,
) -> list[int]:
    """Batch-generate cards for the next N most-attractive open Prophecy markets.

    Returns the list of cards.id (deduped). Invariants:
    - Pipeline always re-validates per market before insert (deadlines drift).
    - Errors on a single market never abort the batch.
    """
    candidates = reader.fetch_open_markets(category=category, limit=limit * 2)
    candidates.sort(key=_attractiveness_score, reverse=True)

    out: list[int] = []
    for m in candidates:
        if len(out) >= limit:
            break
        cid = generate_card_from_prophecy_market(m.id)
        if cid is not None:
            out.append(cid)
    return out


def is_card_generated_for_market(market_id: int) -> Optional[int]:
    """Public alias for the existence check — useful for ops scripts."""
    return _existing_card_id(market_id)


# ─── Scheduler entrypoint (wired from app.scheduler) ─────────────────


def scheduled_prophecy_card_gen() -> None:
    """Cron job target. Honors `settings.prophecy_card_gen_enabled`."""
    s = get_settings()
    if not s.prophecy_card_gen_enabled:
        return
    try:
        ids = generate_cards_for_open_markets(limit=DEFAULT_BATCH_LIMIT)
        log.info("prophecy_card_gen: produced %d card(s)", len(ids))
    except Exception as e:                            # noqa: BLE001 — never break the scheduler
        log.warning("prophecy_card_gen failed: %s", e)


# ─── Internals ───────────────────────────────────────────────────────


def _existing_card_id(market_id: int) -> Optional[int]:
    conn = db._get_read_conn() if hasattr(db, "_get_read_conn") else db._get_conn()
    if not conn:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM cards WHERE prophecy_market_id = %s LIMIT 1",
            (int(market_id),),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def _is_eligible(m: ProphecyMarket) -> bool:
    if m.status != MarketStatus.OPEN:
        return False
    if m.time_remaining_seconds < MIN_DEADLINE_MINUTES * 60:
        return False
    if not m.question.strip():
        return False
    return True


def _attractiveness_score(m: ProphecyMarket) -> float:
    """Higher = more interesting. Three components, all in [0, 1]:

      - longer time-to-resolve (more swipe runway)
      - larger total pool (active market)
      - lower pool imbalance (genuine uncertainty)
    """
    horizon = min(m.time_remaining_seconds, 7 * 86_400) / (7 * 86_400)
    pool = min(m.total_pool, 10**24) / 10**24
    uncertainty = 1.0 - abs(m.yes_odds - 0.5) * 2
    return 0.4 * horizon + 0.3 * pool + 0.3 * uncertainty


# ─── Stage 3: verdict synthesizer (deterministic for v1) ─────────────


def _synthesize_verdict(m: ProphecyMarket) -> dict:
    """v1 verdict: crowd-following with confidence = max(yes,no) odds.

    Replace with `agent_engine_somnia.run_debate(market)` when the v2
    sister-sprint lands the Somnia LLM Inference path. The shape of this
    return value is the contract the pipeline depends on — keep it stable.
    """
    if m.yes_odds >= 0.5:
        verdict, dominant = "APE", m.yes_odds
        side_label = "YES"
    else:
        verdict, dominant = "FADE", m.no_odds
        side_label = "NO"
    confidence = round(dominant * 100)
    yes_pct = round(m.yes_odds * 100)
    no_pct = 100 - yes_pct
    hook = (
        f"Crowd says {yes_pct}% YES / {no_pct}% NO — Kinetic agrees with {side_label}."
        if confidence >= 60
        else f"Coin-flip market: {yes_pct}% YES / {no_pct}% NO — high-uncertainty swipe."
    )
    return {
        "verdict": verdict,
        "confidence": confidence,
        "side": side_label,
        "hook": hook,
        "reasoning": f"Pool imbalance {abs(m.yes_odds - 0.5):.2f}; {m.consensus_threshold}-agent consensus required.",
    }


# ─── Stage 5: Card row builder ───────────────────────────────────────


def _build_card_row(m: ProphecyMarket) -> dict:
    v = _synthesize_verdict(m)
    question = m.question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        question = question[: MAX_QUESTION_LENGTH - 1].rstrip() + "…"
    deadline_iso = datetime.fromtimestamp(m.deadline, tz=timezone.utc)
    category_label = _CATEGORY_LABELS.get(m.category, "general")
    return {
        # Reuse generic Card columns; FE renders by card_type='prediction'.
        "token_symbol": f"PROPHECY:{m.id}",                # encodes market id for swipe queue
        "token_name": question,                              # used as title in feed
        "chain": "somnia",
        "hook": v["hook"],
        "roast": v["reasoning"],
        "metrics": [
            {"label": "category", "value": category_label},
            {"label": "yes_odds", "value": round(m.yes_odds, 4)},
            {"label": "no_odds",  "value": round(m.no_odds, 4)},
            {"label": "consensus_threshold", "value": m.consensus_threshold},
        ],
        "image_url": "",
        "ai_image_prompt": "",
        "price": 0,
        "price_change_24h": 0,
        "volume_24h": 0,
        "market_cap": 0,
        "coingecko_id": "",
        "verdict": v["verdict"],
        "verdict_reason": v["reasoning"],
        "risk_level": "MID",
        "risk_score": 50,
        "notification_hook": "",
        "signals": [],
        "sparkline": [],
        "patterns": [],
        "ohlc": [],
        "source": "prophecy",                              # distinguishes from 'ai' / 'sodex' / etc.
        "provider": "prophecy.social",
        "signal_id": None,
        "institutional_context": [],
        "card_type": "prediction",                         # FE feed mode key
        "research_summary": {},
        "token_address": "",
        "confidence": v["confidence"],
        "trade_plan": {"side": v["side"]},
        # Prediction-card extension columns.
        "prophecy_market_id": int(m.id),
        "prophecy_yes_odds_at_gen": round(m.yes_odds, 4),
        "prophecy_deadline": deadline_iso,
    }


# ─── Card-hash + bridge bind (Somnia testnet 50312) ──────────────────


def compute_card_hash(card_id: int, market_id: int) -> bytes:
    """keccak256(abi.encode(uint256 cardId, uint256 marketId)).

    The same formula MUST be used by:
      - this module (when binding the bridge),
      - the frontend (when calling ConvictionEngine.commitConviction),
      - the bridge contract (implicit — it just stores whatever bytes32
        we hand it via `bindMarketToCard`).

    Public so tests + tooling can verify symmetry across the three sites.
    """
    from eth_abi import encode as abi_encode
    from web3 import Web3
    return Web3.keccak(abi_encode(["uint256", "uint256"], [int(card_id), int(market_id)]))


def _bind_card_on_bridge(card_id: int, market_id: int) -> Optional[str]:
    """Submit `bindMarketToCard` on Somnia testnet 50312. Best-effort, idempotent.

    Returns the tx hash on success, None on any failure (including the
    contract's `AlreadyBound` revert — which is the success-equivalent
    on retry). Pipeline never raises; the card row stays inserted even
    if the bridge bind fails. A backfill script (`prophecy_event_poller`
    in Task 7 owns the cursor; an ops command can re-bind from the
    cards table if needed) catches up later.
    """
    s = get_settings()
    if not s.prophecy_bridge_address or not s.somnia_testnet_rpc or not s.private_key:
        log.info("prophecy_bind: missing config; skipping bind for market_id=%d", market_id)
        return None
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(s.somnia_testnet_rpc, request_kwargs={"timeout": 10}))
        account = w3.eth.account.from_key(s.private_key)
        bridge = w3.eth.contract(
            address=Web3.to_checksum_address(s.prophecy_bridge_address),
            abi=_BRIDGE_BIND_ABI,
        )
        card_hash = compute_card_hash(card_id, market_id)
        tx = bridge.functions.bindMarketToCard(int(market_id), card_hash).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": 50312,
            "gas": 250_000,
            "gasPrice": w3.eth.gas_price or 1_000_000_000,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
        log.info("prophecy_bind: market_id=%d → tx=%s", market_id, tx_hash)
        return tx_hash
    except Exception as e:                                # noqa: BLE001 — best-effort
        msg = str(e)
        if "AlreadyBound" in msg or "already bound" in msg.lower():
            log.info("prophecy_bind: market_id=%d already bound (no-op)", market_id)
            return None
        log.warning("prophecy_bind failed for market_id=%d: %s", market_id, e)
        return None
