"""Tests for prophecy_event_poller — kill-switch, dedupe, error containment."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app import prophecy_event_poller as poller
from app.prophecy_social_reader import (
    MarketStatus,
    ProphecyCategory,
    ProphecyMarket,
)


def _resolved_market(mid: int, outcome: bool = True) -> ProphecyMarket:
    return ProphecyMarket(
        id=mid,
        question=f"Q{mid}",
        creator="0xabc",
        category=ProphecyCategory.CRYPTO,
        deadline=int(time.time()) - 3600,
        resolution_criteria="r",
        status=MarketStatus.RESOLVED,
        yes_pool=100, no_pool=200, consensus_threshold=3,
        outcome=outcome,
        receipt_uri="ipfs://rcpt",
    )


def _open_market(mid: int) -> ProphecyMarket:
    return ProphecyMarket(
        id=mid, question=f"Q{mid}", creator="0xabc",
        category=ProphecyCategory.CRYPTO, deadline=int(time.time()) + 86400,
        resolution_criteria="r", status=MarketStatus.OPEN,
        yes_pool=10, no_pool=10, consensus_threshold=3,
        outcome=None, receipt_uri=None,
    )


# ─── kill-switches ─────────────────────────────────────────────────


def test_relay_skipped_when_disabled(monkeypatch):
    fake = MagicMock(prophecy_card_gen_enabled=False)
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    spy = MagicMock(side_effect=AssertionError("reader must not be called"))
    monkeypatch.setattr(poller.reader, "fetch_recent_resolutions", spy)
    assert poller.relay_recent_resolutions() == 0


def test_relay_skipped_when_bridge_unconfigured(monkeypatch):
    fake = MagicMock(prophecy_card_gen_enabled=True,
                     prophecy_bridge_address="", somnia_testnet_rpc="rpc",
                     private_key="0xkey")
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    assert poller.relay_recent_resolutions() == 0


def test_relay_skipped_when_mainnet_reader_unavailable(monkeypatch):
    fake = MagicMock(prophecy_card_gen_enabled=True,
                     prophecy_bridge_address="0xb",
                     somnia_testnet_rpc="rpc", private_key="0xkey")
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    monkeypatch.setattr(poller.reader, "_get_contract", lambda: (None, None))
    assert poller.relay_recent_resolutions() == 0


# ─── happy + dedupe paths ──────────────────────────────────────────


def test_relay_propagates_only_resolved_markets_with_outcome(monkeypatch):
    fake = MagicMock(prophecy_card_gen_enabled=True,
                     prophecy_bridge_address="0xb",
                     somnia_testnet_rpc="rpc", private_key="0xkey")
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    fake_w3 = MagicMock()
    fake_w3.eth.block_number = 1_000
    monkeypatch.setattr(poller.reader, "_get_contract", lambda: (fake_w3, MagicMock()))
    monkeypatch.setattr(
        poller.reader, "fetch_recent_resolutions",
        lambda since_block, limit=20: [
            _resolved_market(1, True),
            _open_market(2),                            # must be skipped
            _resolved_market(3, False),
        ],
    )
    monkeypatch.setattr(poller, "_card_id_for_market",
                        lambda mid: 100 + mid if mid in (1, 3) else None)
    triggers = []
    def _trigger(mid, outcome, uri):
        triggers.append((mid, outcome, uri))
        return f"0xtx{mid}"
    monkeypatch.setattr(poller, "_trigger_resolution", _trigger)
    out = poller.relay_recent_resolutions()
    assert out == 2
    assert {t[0] for t in triggers} == {1, 3}
    assert (1, True, "ipfs://rcpt") in triggers


def test_relay_skips_resolved_markets_with_no_card(monkeypatch):
    fake = MagicMock(prophecy_card_gen_enabled=True,
                     prophecy_bridge_address="0xb",
                     somnia_testnet_rpc="rpc", private_key="0xkey")
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    monkeypatch.setattr(poller.reader, "_get_contract",
                        lambda: (MagicMock(eth=MagicMock(block_number=10)), MagicMock()))
    monkeypatch.setattr(poller.reader, "fetch_recent_resolutions",
                        lambda since_block, limit=20: [_resolved_market(1)])
    monkeypatch.setattr(poller, "_card_id_for_market", lambda mid: None)
    spy = MagicMock(side_effect=AssertionError("trigger must not run when card missing"))
    monkeypatch.setattr(poller, "_trigger_resolution", spy)
    assert poller.relay_recent_resolutions() == 0


def test_relay_returns_zero_when_no_recent_resolutions(monkeypatch):
    fake = MagicMock(prophecy_card_gen_enabled=True,
                     prophecy_bridge_address="0xb",
                     somnia_testnet_rpc="rpc", private_key="0xkey")
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    monkeypatch.setattr(poller.reader, "_get_contract",
                        lambda: (MagicMock(eth=MagicMock(block_number=10)), MagicMock()))
    monkeypatch.setattr(poller.reader, "fetch_recent_resolutions",
                        lambda since_block, limit=20: [])
    assert poller.relay_recent_resolutions() == 0


def test_scheduled_wrapper_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(poller, "relay_recent_resolutions",
                        MagicMock(side_effect=RuntimeError("boom")))
    poller.scheduled_prophecy_relay()                       # must not raise


# ─── trigger helper graceful-degrade ───────────────────────────────


def test_trigger_resolution_swallows_already_propagated(monkeypatch):
    fake = MagicMock(prophecy_bridge_address="0xb",
                     somnia_testnet_rpc="rpc", private_key="0xkey")
    monkeypatch.setattr(poller, "get_settings", lambda: fake)
    # Force the web3 import path to raise an "AlreadyPropagated" error
    # the way the bridge would surface it.
    class _BoomW3:
        def __init__(*a, **k): raise RuntimeError("execution reverted: AlreadyPropagated")
    with patch("web3.Web3", _BoomW3):
        # The helper catches the AlreadyPropagated text and returns None
        # cleanly — no propagation, no log noise above debug.
        assert poller._trigger_resolution(42, True, "") is None
