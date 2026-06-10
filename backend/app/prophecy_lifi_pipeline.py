"""Prophecy-aware LiFi pipeline — adds cross_chain_ready flag to cards.

SOLID:
  - SRP: a card row -> decide cross_chain_ready -> persist. Nothing else.
  - OCP: `is_cross_chain_ready` is the swap-point. v4 might add LiFi-route
    availability per origin chain; today the predicate is purely temporal.
  - DIP: depends on `app.db` helpers + `app.config`. Pure side-effect-free
    predicate makes the unit-test set trivial (no DB / RPC mocks).

Background task: re-evaluates cards aged < 24h every 60s, since deadlines
move with wall time. Failure-tolerant: a tick exception logs + continues.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import db
from app.config import get_settings

log = logging.getLogger(__name__)

RECHECK_INTERVAL_SECONDS = 60


def is_cross_chain_ready(
    *,
    deadline_at: Optional[datetime],
    prophecy_market_id: Optional[int],
    is_market_bound_on_bridge: bool,
    now: Optional[datetime] = None,
    buffer_minutes: Optional[int] = None,
) -> bool:
    """Pure predicate. True iff the card is safe to surface to a cross-chain user.

    Three constraints:
      - Market id is set + positive
      - Market is bound on KineticProphecyBridge (caller-supplied for purity)
      - Deadline is at least `buffer_minutes` ahead (default 20 min: 5 min
        bridge + 15 min swipe runway)
    """
    if not prophecy_market_id or prophecy_market_id <= 0:
        return False
    if not is_market_bound_on_bridge:
        return False
    if deadline_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    buffer = buffer_minutes if buffer_minutes is not None else (
        get_settings().cross_chain_deadline_buffer_minutes
    )
    minutes_left = (deadline_at - now).total_seconds() / 60
    return minutes_left >= buffer


def evaluate_and_update_card(card_id: int) -> bool:
    """Synchronous helper used by the card-gen pipeline + the refresher.
    Returns the new `cross_chain_ready` value."""
    s = get_settings()
    rows = _fetch_card(card_id)
    if not rows:
        return False
    row = rows
    market_id = row.get("prophecy_market_id")
    deadline = row.get("prophecy_deadline")
    if market_id is None:
        return False
    bound = db.is_prophecy_market_bound(int(market_id))
    ready = is_cross_chain_ready(
        deadline_at=deadline,
        prophecy_market_id=int(market_id),
        is_market_bound_on_bridge=bound,
    )
    db.update_card_lifi_flags(
        card_id, cross_chain_ready=ready,
        min_swipe_stake_usdc=row.get("min_swipe_stake_usdc") or s.default_min_swipe_stake_usdc,
    )
    return ready


def generate_card_with_lifi_metadata(market_id: int) -> Optional[int]:
    """Wraps `prophecy_card_pipeline.generate_card_from_prophecy_market` and
    immediately tags the new card with cross_chain_ready + min_stake."""
    from app.prophecy_card_pipeline import generate_card_from_prophecy_market

    card_id = generate_card_from_prophecy_market(market_id)
    if card_id is None:
        return None
    try:
        evaluate_and_update_card(card_id)
    except Exception as e:                                              # noqa: BLE001
        log.warning("evaluate_and_update_card(%d) failed: %s", card_id, e)
    return card_id


# ─────────────────────────────────────────────────────────────────────
#  Background refresher (mounted from main.py startup)
# ─────────────────────────────────────────────────────────────────────
async def run_lifi_metadata_refresher() -> None:
    s = get_settings()
    if not s.lifi_metadata_refresher_enabled:
        return
    log.info("prophecy_lifi_refresher running (every %ds)", RECHECK_INTERVAL_SECONDS)
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            cards = await asyncio.to_thread(db.find_cards_with_prophecy_market_since, cutoff)
            flipped = 0
            for c in cards:
                bound = await asyncio.to_thread(
                    db.is_prophecy_market_bound, int(c["prophecy_market_id"])
                )
                ready = is_cross_chain_ready(
                    deadline_at=c.get("prophecy_deadline"),
                    prophecy_market_id=int(c["prophecy_market_id"]),
                    is_market_bound_on_bridge=bound,
                )
                if ready != bool(c.get("cross_chain_ready")):
                    await asyncio.to_thread(
                        db.update_card_lifi_flags,
                        int(c["id"]),
                        cross_chain_ready=ready,
                        min_swipe_stake_usdc=int(
                            c.get("min_swipe_stake_usdc") or s.default_min_swipe_stake_usdc
                        ),
                    )
                    flipped += 1
            if flipped:
                log.info("prophecy_lifi_refresher: flipped %d card(s)", flipped)
        except Exception as e:                                          # noqa: BLE001
            log.warning("prophecy_lifi_refresher tick failed: %s", e)
        await asyncio.sleep(RECHECK_INTERVAL_SECONDS)


def _fetch_card(card_id: int) -> Optional[dict]:
    """Single-row read. Reuses the db read connection pattern."""
    conn = db._get_read_conn() if hasattr(db, "_get_read_conn") else db._get_conn()
    if not conn:
        return None
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, prophecy_market_id, prophecy_deadline, "
                "cross_chain_ready, min_swipe_stake_usdc FROM cards WHERE id = %s",
                (card_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        try:
            conn.close()
        except Exception:
            pass
