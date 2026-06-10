"""Unit tests for v3 cross-chain LiFi backend (lifi_service + prophecy_lifi_pipeline).

Pattern: monkey-patch the sync `app.db` helpers — the modules' DIP boundary —
so we don't need a live Postgres for these tests. The schema-side migration
helpers are exercised separately via `_ensure_runtime_columns` integration.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


# ─── prophecy_lifi_pipeline.is_cross_chain_ready (pure predicate) ─────
def test_predicate_happy_path():
    from app.prophecy_lifi_pipeline import is_cross_chain_ready
    now = datetime.now(timezone.utc)
    assert is_cross_chain_ready(
        deadline_at=now + timedelta(minutes=30),
        prophecy_market_id=1,
        is_market_bound_on_bridge=True,
        now=now,
        buffer_minutes=20,
    ) is True


def test_predicate_rejects_close_deadline():
    from app.prophecy_lifi_pipeline import is_cross_chain_ready
    now = datetime.now(timezone.utc)
    assert is_cross_chain_ready(
        deadline_at=now + timedelta(minutes=10),
        prophecy_market_id=1,
        is_market_bound_on_bridge=True,
        now=now,
        buffer_minutes=20,
    ) is False


def test_predicate_rejects_unbound_market():
    from app.prophecy_lifi_pipeline import is_cross_chain_ready
    now = datetime.now(timezone.utc)
    assert is_cross_chain_ready(
        deadline_at=now + timedelta(hours=2),
        prophecy_market_id=1,
        is_market_bound_on_bridge=False,
        now=now,
    ) is False


def test_predicate_rejects_invalid_market_id():
    from app.prophecy_lifi_pipeline import is_cross_chain_ready
    now = datetime.now(timezone.utc)
    assert is_cross_chain_ready(
        deadline_at=now + timedelta(hours=2),
        prophecy_market_id=0,
        is_market_bound_on_bridge=True,
        now=now,
    ) is False


def test_predicate_rejects_missing_deadline():
    from app.prophecy_lifi_pipeline import is_cross_chain_ready
    assert is_cross_chain_ready(
        deadline_at=None,
        prophecy_market_id=1,
        is_market_bound_on_bridge=True,
    ) is False


# ─── lifi_service: calldata encoder ───────────────────────────────────
def test_encode_destination_calldata_starts_with_selector():
    from app.lifi_service import _encode_destination_calldata, EXECUTE_FROM_LIFI_SELECTOR
    cd = _encode_destination_calldata(
        prophecy_market_id=12345,
        symbol="BTC",
        context="ctx",
        swipe_stake_usdc=1_000_000,
        original_user="0x000000000000000000000000000000000000bEEF",
    )
    assert cd.startswith(EXECUTE_FROM_LIFI_SELECTOR)
    assert len(cd) > 200    # selector + 6 abi-encoded args is non-trivial


def test_extract_fees_usd_handles_empty_and_present():
    from app.lifi_service import _extract_fees_usd
    assert _extract_fees_usd({"estimate": {"feeCosts": []}}) == 0.0
    assert _extract_fees_usd({"estimate": {"feeCosts": [{"amountUSD": "0.42"}]}}) == 0.42
    assert _extract_fees_usd({}) == 0.0


def test_stub_quote_shape():
    from app.lifi_service import _stub_quote
    payload = _stub_quote("0xExec", "0xCalldata")
    assert payload["transactionRequest"]["to"] == "0xExec"
    assert payload["transactionRequest"]["data"] == "0xCalldata"
    assert payload["estimate"]["executionDuration"] == 30


# ─── lifi_service: status endpoint via monkey-patch ───────────────────
@pytest.mark.asyncio
async def test_status_endpoint_404_on_unknown(monkeypatch):
    from app import lifi_service, db
    monkeypatch.setattr(db, "get_lifi_intent", lambda _id: None)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await lifi_service.get_lifi_intent_status("lifi-int-nope")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_endpoint_returns_intent(monkeypatch):
    from app import lifi_service, db
    intent = db.LifiIntent(
        intent_id="lifi-int-abc",
        user_address="0x" + "a" * 40,
        prophecy_market_id=1,
        card_id=10,
        origin_chain_id=421614,
        swipe_stake_usdc=100_000,
        status="EXECUTED",
        verdict_id=42,
        card_hash="0x" + "b" * 64,
        somnscan_url="https://example/tx/0xabc",
        arbiscan_url="https://example/tx/0xdef",
        prophecy_market_url="https://prophecy.social/market/1",
    )
    monkeypatch.setattr(db, "get_lifi_intent", lambda _id: intent)
    resp = await lifi_service.get_lifi_intent_status("lifi-int-abc")
    assert resp.status == "EXECUTED"
    assert resp.verdict_id == 42
    assert resp.somnscan_url == "https://example/tx/0xabc"
    assert resp.prophecy_market_url == "https://prophecy.social/market/1"


@pytest.mark.asyncio
async def test_quote_endpoint_disabled_returns_503(monkeypatch):
    from app import lifi_service
    from app.config import get_settings
    s = get_settings()
    s.lifi_quote_enabled = False
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await lifi_service.lifi_quote(
            fromChain=421614,
            fromToken="0x" + "a" * 40,
            swipeStakeUsdc=100_000,
            prophecyMarketId=1,
            userAddress="0x" + "b" * 40,
            symbol="BTC",
            context="ctx",
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_quote_endpoint_stake_below_minimum(monkeypatch):
    from app import lifi_service
    from app.config import get_settings
    s = get_settings()
    s.lifi_quote_enabled = True
    s.default_min_swipe_stake_usdc = 100_000
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await lifi_service.lifi_quote(
            fromChain=421614,
            fromToken="0x" + "a" * 40,
            swipeStakeUsdc=50,
            prophecyMarketId=1,
            userAddress="0x" + "b" * 40,
            symbol="BTC",
            context="ctx",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "STAKE_BELOW_MINIMUM"
