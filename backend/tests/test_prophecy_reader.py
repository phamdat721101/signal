"""Tests for prophecy_social_reader — decoders, caching, fallback path.

Each test resets module-level caches via the `_reset_caches_for_test` hook.
We never hit a real RPC or HTTP endpoint — both are mocked.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app import prophecy_social_reader as r


# Sample raw tuples that mirror the ABI getMarket output.
_RPC_OPEN = (
    "Will BTC close above $200K by Friday?",
    "0x1111111111111111111111111111111111111111",
    1,                                             # category = CRYPTO
    int(time.time()) + 86_400,                     # deadline 24h ahead
    "Coinbase BTC-USD close 2026-06-13 23:59 UTC",
    0,                                             # status = OPEN
    1_000_000_000_000_000_000_000,                 # 1000 PST yes
    250_000_000_000_000_000_000,                   #  250 PST no
    3,                                             # threshold
    False,
    "",
)

_RPC_RESOLVED = (
    "Will ETH 2.0 launch ship Q2?",
    "0x2222222222222222222222222222222222222222",
    1, int(time.time()) - 1000, "Spec finalized + mainnet block emitted",
    2,                                             # status = RESOLVED
    100, 900, 3,
    True,                                          # outcome = YES
    "ipfs://QmTestReceiptCid",
)


@pytest.fixture(autouse=True)
def _reset():
    r._reset_caches_for_test()
    yield
    r._reset_caches_for_test()


# ─── decoders ───────────────────────────────────────────────────────


def test_decode_rpc_open_market():
    m = r._decode_rpc_market(_RPC_OPEN, market_id=42)
    assert m.id == 42
    assert m.category == r.ProphecyCategory.CRYPTO
    assert m.status == r.MarketStatus.OPEN
    assert m.outcome is None                          # OPEN means no outcome yet
    assert m.is_resolved is False
    assert m.total_pool == _RPC_OPEN[6] + _RPC_OPEN[7]
    assert 0.0 < m.yes_odds < 1.0
    assert m.time_remaining_seconds > 0


def test_decode_rpc_resolved_market_carries_outcome():
    m = r._decode_rpc_market(_RPC_RESOLVED, market_id=7)
    assert m.is_resolved
    assert m.outcome is True
    assert m.receipt_uri == "ipfs://QmTestReceiptCid"


# ─── fetch_market: cache + RPC + HTTP fallback ─────────────────────


def test_fetch_market_returns_cached_value(monkeypatch):
    cached = r._decode_rpc_market(_RPC_OPEN, market_id=1)
    r._cache_set_market(cached)
    monkeypatch.setattr(r, "_get_contract", lambda: (None, MagicMock(side_effect=AssertionError("RPC must not be called"))))
    out = r.fetch_market(1)
    assert out is cached


def test_fetch_market_rpc_path(monkeypatch):
    contract = MagicMock()
    contract.functions.getMarket.return_value.call.return_value = _RPC_OPEN
    monkeypatch.setattr(r, "_get_contract", lambda: (MagicMock(), contract))
    out = r.fetch_market(123)
    assert out is not None
    assert out.id == 123
    assert r._health["contract_reachable"] is True
    # Second call must hit the cache, not RPC.
    contract.functions.getMarket.return_value.call.assert_called_once()
    out2 = r.fetch_market(123)
    assert out2 is out


def test_fetch_market_falls_back_to_http_on_rpc_error(monkeypatch):
    contract = MagicMock()
    contract.functions.getMarket.return_value.call.side_effect = RuntimeError("boom")
    monkeypatch.setattr(r, "_get_contract", lambda: (MagicMock(), contract))

    fake_resp = MagicMock()
    fake_resp.text = _make_homepage_html(
        '[{"marketId":9,"question":"Q?","category":"crypto","status":"active",'
        '"yesPrice":0.5,"noPrice":0.5,"closeTs":"2027-01-01T00:00:00Z"}]'
    )
    with patch.object(r.http_client, "get", return_value=fake_resp) as http_get:
        out = r.fetch_market(9)
    assert out is not None
    assert out.id == 9
    http_get.assert_called_once()
    assert r._health["contract_reachable"] is False
    assert r._health["api_reachable"] is True


def test_fetch_market_returns_none_when_both_paths_fail(monkeypatch):
    monkeypatch.setattr(r, "_get_contract", lambda: (None, None))
    with patch.object(r.http_client, "get", return_value=None):
        out = r.fetch_market(1)
    assert out is None
    assert r._health["api_reachable"] is False


# ─── fetch_open_markets: filter, sort, limit, cache ────────────────


def test_fetch_open_markets_filters_sorts_and_limits(monkeypatch):
    later  = r._decode_rpc_market(_RPC_OPEN, market_id=10)
    sooner_raw = list(_RPC_OPEN); sooner_raw[3] = int(time.time()) + 3600
    sooner = r._decode_rpc_market(tuple(sooner_raw), market_id=11)
    sports_raw = list(_RPC_OPEN); sports_raw[2] = int(r.ProphecyCategory.SPORTS); sports_raw[3] = int(time.time()) + 7200
    sports = r._decode_rpc_market(tuple(sports_raw), market_id=12)
    monkeypatch.setattr(r, "_cache_get_open", lambda ttl: [later, sooner, sports])

    out = r.fetch_open_markets(category=r.ProphecyCategory.CRYPTO, limit=5)
    assert [m.id for m in out] == [11, 10]  # sooner first, sports filtered out

    out_all = r.fetch_open_markets(limit=2)
    assert len(out_all) == 2
    assert out_all[0].deadline <= out_all[1].deadline


def test_fetch_open_markets_uses_http_when_rpc_yields_nothing(monkeypatch):
    monkeypatch.setattr(r, "_get_contract", lambda: (None, None))
    fake_resp = MagicMock()
    fake_resp.text = _make_homepage_html(
        '[{"marketId":1,"question":"q1","category":"crypto","status":"active",'
        '"yesPrice":0.5,"noPrice":0.5,"closeTs":"2030-01-01T00:00:00Z"}]'
    )
    with patch.object(r.http_client, "get", return_value=fake_resp):
        out = r.fetch_open_markets(limit=5)
    assert len(out) == 1 and out[0].id == 1


# ─── receipt resolution ────────────────────────────────────────────


def test_resolution_receipt_skipped_when_market_not_resolved(monkeypatch):
    m = r._decode_rpc_market(_RPC_OPEN, market_id=1)
    monkeypatch.setattr(r, "fetch_market", lambda mid: m)
    assert r.fetch_resolution_receipt(1) is None


def test_resolution_receipt_resolves_via_ipfs_round_robin(monkeypatch):
    resolved = r._decode_rpc_market(_RPC_RESOLVED, market_id=7)
    monkeypatch.setattr(r, "fetch_market", lambda mid: resolved)

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "sources": ["news.example/abc"],
        "findings": ["consensus: YES"],
        "agent_votes": [{"agent_id": "a1", "vote": True}],
        "final_outcome": True,
    }
    with patch.object(r.http_client, "get", return_value=fake_resp) as http_get:
        receipt = r.fetch_resolution_receipt(7)
    assert receipt is not None
    assert receipt.final_outcome is True
    assert receipt.sources == ["news.example/abc"]
    # second call hits the receipt cache, no HTTP
    r.fetch_resolution_receipt(7)
    http_get.assert_called_once()


def test_health_check_shape():
    snap = r.health_check()
    assert set(snap.keys()) == {"contract_reachable", "api_reachable", "last_checked_at"}


# ─── homepage RSC parser ────────────────────────────────────────────


def _make_homepage_html(markets_json: str) -> str:
    """Build a minimal Next.js home-page-shaped HTML harness for tests."""
    # Each chunk is a JSON-encoded string; here we wrap one chunk that
    # contains a `"markets":[...]` payload.
    inner = '{"markets":' + markets_json + '}'
    chunk = json.dumps(inner)[1:-1]                      # strip outer quotes
    return f'<html><body><script>self.__next_f.push([1,"{chunk}"])</script></body></html>'


def test_parse_homepage_extracts_minimum_market_object():
    html = _make_homepage_html(
        '[{"id":"u1","marketId":42,"question":"Will BTC > $200K?","category":"crypto",'
        '"status":"active","yesPrice":0.7,"noPrice":0.3,'
        '"closeTs":"2026-12-31T23:59:00.000Z","creatorWallet":"0xabc"}]'
    )
    out = r._parse_homepage_markets(html)
    assert len(out) == 1
    m = out[0]
    assert m.id == 42
    assert m.category == r.ProphecyCategory.CRYPTO
    assert m.status == r.MarketStatus.OPEN
    assert abs(m.yes_odds - 0.7) < 1e-6
    assert m.deadline > 1_700_000_000


def test_parse_homepage_dedupes_across_multiple_arrays():
    """Home page renders the same market in `from-partners` AND `all-markets`."""
    inner = (
        '{"foo":1,"markets":[{"marketId":7,"question":"A?","category":"sport",'
        '"status":"active","yesPrice":0.5,"noPrice":0.5,"closeTs":"2027-01-01T00:00:00Z"}],'
        '"more":{"markets":[{"marketId":7,"question":"A?","category":"sport",'
        '"status":"active","yesPrice":0.6,"noPrice":0.4,"closeTs":"2027-01-01T00:00:00Z"}]}}'
    )
    html = '<script>self.__next_f.push([1,"' + json.dumps(inner)[1:-1] + '"])</script>'
    out = r._parse_homepage_markets(html)
    assert len(out) == 1                                  # deduped by marketId
    assert out[0].id == 7


def test_parse_homepage_skips_resolved_array_silently():
    """Other arrays in the page (e.g. recentlyResolved) lack `marketId`/`question`."""
    inner = (
        '{"recentlyResolved":[{"eventId":1,"name":"X","outcome":"YES"}],'
        '"markets":[{"marketId":99,"question":"Q?","category":"crypto",'
        '"status":"active","yesPrice":0.5,"noPrice":0.5,"closeTs":"2027-01-01T00:00:00Z"}]}'
    )
    html = '<script>self.__next_f.push([1,"' + json.dumps(inner)[1:-1] + '"])</script>'
    out = r._parse_homepage_markets(html)
    assert [m.id for m in out] == [99]


def test_homepage_decoder_composes_event_name_for_short_option_questions():
    """When the per-option `question` is just an option label, compose with eventName."""
    html = _make_homepage_html(
        '[{"marketId":1,"question":"Up","eventName":"Bitcoin: Up or Down in 20 Minutes?",'
        '"category":"crypto","status":"active","yesPrice":0.5,"noPrice":0.5,'
        '"closeTs":"2027-01-01T00:00:00Z"}]'
    )
    out = r._parse_homepage_markets(html)
    assert "Bitcoin: Up or Down in 20 Minutes?" in out[0].question
    assert "Up" in out[0].question


def test_homepage_decoder_handles_resolved_outcome_string():
    html = _make_homepage_html(
        '[{"marketId":2,"question":"Q?","category":"politics","status":"resolved",'
        '"yesPrice":1.0,"noPrice":0.0,"closeTs":"2024-01-01T00:00:00Z","dbOutcome":"YES"}]'
    )
    out = r._parse_homepage_markets(html)
    assert out[0].is_resolved
    assert out[0].outcome is True


def test_iter_market_arrays_handles_nested_brackets_and_strings():
    """Bracket walker must respect string-quoted ']' inside values."""
    blob = '"markets":[{"a":"]"},{"b":1}],"other":[]'
    chunks = list(r._iter_market_arrays(blob))
    assert len(chunks) == 1
    assert json.loads(chunks[0]) == [{"a": "]"}, {"b": 1}]
