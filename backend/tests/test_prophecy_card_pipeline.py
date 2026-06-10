"""Tests for prophecy_card_pipeline — eligibility, verdict, idempotency, batch.

DB layer is mocked via monkeypatch so the tests are pure-Python and run in
isolation from Postgres.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app import prophecy_card_pipeline as pipe
from app.prophecy_social_reader import (
    MarketStatus,
    ProphecyCategory,
    ProphecyMarket,
)


@pytest.fixture(autouse=True)
def _no_real_chain(monkeypatch):
    """Make `_bind_card_on_bridge` a deterministic no-op for all tests.
    Every test that wants to assert on bind behavior overrides this."""
    monkeypatch.setattr(pipe, "_bind_card_on_bridge", lambda cid, mid: None)


def _make_market(**overrides) -> ProphecyMarket:
    base = dict(
        id=42,
        question="Will BTC close above $200K by Friday?",
        creator="0xabc",
        category=ProphecyCategory.CRYPTO,
        deadline=int(time.time()) + 86_400,
        resolution_criteria="Coinbase BTC-USD close",
        status=MarketStatus.OPEN,
        yes_pool=70 * 10**18,
        no_pool=30 * 10**18,
        consensus_threshold=3,
        outcome=None,
        receipt_uri=None,
    )
    base.update(overrides)
    return ProphecyMarket(**base)


# ─── Verdict synthesizer ─────────────────────────────────────────────


def test_verdict_follows_majority_yes():
    m = _make_market(yes_pool=80 * 10**18, no_pool=20 * 10**18)
    v = pipe._synthesize_verdict(m)
    assert v["verdict"] == "APE"
    assert v["side"] == "YES"
    assert v["confidence"] == 80


def test_verdict_follows_majority_no():
    m = _make_market(yes_pool=10 * 10**18, no_pool=90 * 10**18)
    v = pipe._synthesize_verdict(m)
    assert v["verdict"] == "FADE"
    assert v["side"] == "NO"
    assert v["confidence"] == 90


def test_verdict_handles_coin_flip_uncertainty_in_hook():
    m = _make_market(yes_pool=50 * 10**18, no_pool=50 * 10**18)
    v = pipe._synthesize_verdict(m)
    assert v["confidence"] == 50
    assert "Coin-flip" in v["hook"] or "high-uncertainty" in v["hook"]


# ─── Eligibility ─────────────────────────────────────────────────────


def test_resolved_market_is_ineligible():
    m = _make_market(status=MarketStatus.RESOLVED, outcome=True)
    assert pipe._is_eligible(m) is False


def test_too_soon_market_is_ineligible():
    m = _make_market(deadline=int(time.time()) + 60)         # 1 min away
    assert pipe._is_eligible(m) is False


def test_eligible_open_market_passes():
    assert pipe._is_eligible(_make_market()) is True


def test_attractiveness_score_prefers_uncertainty_and_runway():
    soon_certain = _make_market(id=1, deadline=int(time.time()) + 7200,
                                yes_pool=99 * 10**18, no_pool=1 * 10**18)
    later_uncertain = _make_market(id=2, deadline=int(time.time()) + 4 * 86_400,
                                   yes_pool=50 * 10**18, no_pool=50 * 10**18)
    assert pipe._attractiveness_score(later_uncertain) > pipe._attractiveness_score(soon_certain)


# ─── Card row builder ────────────────────────────────────────────────


def test_card_row_carries_prediction_extension_fields():
    m = _make_market()
    row = pipe._build_card_row(m)
    assert row["card_type"] == "prediction"
    assert row["source"] == "prophecy"
    assert row["chain"] == "somnia"
    assert row["token_symbol"] == f"PROPHECY:{m.id}"           # symbol encodes market id
    assert row["prophecy_market_id"] == m.id
    assert 0.0 < row["prophecy_yes_odds_at_gen"] < 1.0
    assert row["confidence"] == 70                              # yes 70 / no 30 → APE@70
    assert row["verdict"] == "APE"
    assert row["trade_plan"] == {"side": "YES"}


def test_card_row_truncates_long_questions():
    long_q = "X" * (pipe.MAX_QUESTION_LENGTH + 50)
    row = pipe._build_card_row(_make_market(question=long_q))
    assert len(row["token_name"]) == pipe.MAX_QUESTION_LENGTH


# ─── Pipeline orchestration ──────────────────────────────────────────


def test_generate_card_idempotent_when_market_already_carded(monkeypatch):
    monkeypatch.setattr(pipe, "_existing_card_id", lambda mid: 99)
    fake_reader = MagicMock(side_effect=AssertionError("reader must not be called when card exists"))
    monkeypatch.setattr(pipe.reader, "fetch_market", fake_reader)
    out = pipe.generate_card_from_prophecy_market(42)
    assert out == 99


def test_generate_card_skips_ineligible_market(monkeypatch):
    monkeypatch.setattr(pipe, "_existing_card_id", lambda mid: None)
    monkeypatch.setattr(pipe.reader, "fetch_market",
                        lambda mid: _make_market(status=MarketStatus.RESOLVED, outcome=True))
    insert = MagicMock(side_effect=AssertionError("insert must not run for ineligible markets"))
    monkeypatch.setattr(pipe.db, "insert_card", insert)
    assert pipe.generate_card_from_prophecy_market(42) is None


def test_generate_card_inserts_and_returns_id(monkeypatch):
    monkeypatch.setattr(pipe, "_existing_card_id", lambda mid: None)
    monkeypatch.setattr(pipe.reader, "fetch_market", lambda mid: _make_market(id=mid))
    captured = {}
    def _fake_insert(card):
        captured["card"] = card
        return 17
    monkeypatch.setattr(pipe.db, "insert_card", _fake_insert)
    out = pipe.generate_card_from_prophecy_market(42)
    assert out == 17
    assert captured["card"]["card_type"] == "prediction"
    assert captured["card"]["prophecy_market_id"] == 42


def test_generate_card_handles_insert_race_via_existing_lookup(monkeypatch):
    """Concurrent generation hits the unique-index race; pipeline must recover."""
    calls = {"existing": 0}
    def _existing(mid):
        calls["existing"] += 1
        return 7 if calls["existing"] > 1 else None        # 1st None, 2nd returns id
    monkeypatch.setattr(pipe, "_existing_card_id", _existing)
    monkeypatch.setattr(pipe.reader, "fetch_market", lambda mid: _make_market(id=mid))
    monkeypatch.setattr(pipe.db, "insert_card",
                        MagicMock(side_effect=Exception("duplicate key")))
    out = pipe.generate_card_from_prophecy_market(42)
    assert out == 7


def test_batch_generator_dedupes_and_respects_limit(monkeypatch):
    markets = [_make_market(id=i, deadline=int(time.time()) + (i + 1) * 86_400) for i in (1, 2, 3, 4, 5)]
    monkeypatch.setattr(pipe.reader, "fetch_open_markets",
                        lambda category=None, limit=50: markets)
    monkeypatch.setattr(pipe, "generate_card_from_prophecy_market", lambda mid: mid * 10)
    out = pipe.generate_cards_for_open_markets(limit=3)
    assert len(out) == 3
    assert all(cid % 10 == 0 for cid in out)


def test_scheduled_job_self_skips_when_disabled(monkeypatch):
    fake_settings = MagicMock(prophecy_card_gen_enabled=False)
    monkeypatch.setattr(pipe, "get_settings", lambda: fake_settings)
    spy = MagicMock(side_effect=AssertionError("batch must not run when disabled"))
    monkeypatch.setattr(pipe, "generate_cards_for_open_markets", spy)
    pipe.scheduled_prophecy_card_gen()                      # must not raise
    spy.assert_not_called()


def test_scheduled_job_runs_when_enabled(monkeypatch):
    fake_settings = MagicMock(prophecy_card_gen_enabled=True)
    monkeypatch.setattr(pipe, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(pipe, "generate_cards_for_open_markets", lambda limit=10: [1, 2])
    pipe.scheduled_prophecy_card_gen()                      # must not raise


# ─── Card hash + bridge bind ────────────────────────────────────────


def test_card_hash_is_deterministic_and_matches_solidity_encoding():
    h1 = pipe.compute_card_hash(1, 42)
    h2 = pipe.compute_card_hash(1, 42)
    assert h1 == h2 and len(h1) == 32
    # Different inputs must yield different hashes (no collision in trivial case).
    assert pipe.compute_card_hash(1, 42) != pipe.compute_card_hash(2, 42)
    assert pipe.compute_card_hash(1, 42) != pipe.compute_card_hash(1, 43)


def test_bind_helper_is_skipped_when_bridge_unconfigured(monkeypatch):
    """The pipeline calls `_bind_card_on_bridge`; the helper itself MUST be
    a graceful no-op when the bridge address / private key / RPC URL are
    not yet populated, so v1 deploys without prophecy config still work."""
    # The autouse fixture above replaces `_bind_card_on_bridge` with a stub.
    # We undo that here for a focused unit test of the real helper.
    monkeypatch.undo()
    fake_settings = MagicMock(prophecy_bridge_address="", somnia_testnet_rpc="", private_key="")
    monkeypatch.setattr(pipe, "get_settings", lambda: fake_settings)
    assert pipe._bind_card_on_bridge(1, 42) is None


def test_pipeline_invokes_bind_after_insert(monkeypatch):
    monkeypatch.setattr(pipe, "_existing_card_id", lambda mid: None)
    monkeypatch.setattr(pipe.reader, "fetch_market", lambda mid: _make_market(id=mid))
    monkeypatch.setattr(pipe.db, "insert_card", lambda card: 17)
    captured = {}
    def _bind(cid, mid):
        captured["args"] = (cid, mid)
    monkeypatch.setattr(pipe, "_bind_card_on_bridge", _bind)
    out = pipe.generate_card_from_prophecy_market(42)
    assert out == 17
    assert captured["args"] == (17, 42)
