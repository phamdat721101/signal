"""Tests for app.sodex_links — pure URL builder + composite payload."""
from __future__ import annotations

import pytest

from app import sodex_links


# ── URL builders ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("BTC",        "BTC_USDC"),
    ("btc",        "BTC_USDC"),
    ("BTC/USD",    "BTC_USDC"),
    ("BTC-USD",    "BTC_USDC"),
    ("BTC_USDC",   "BTC_USDC"),
    ("vBTC_vUSDC", "BTC_USDC"),
    ("",           ""),
])
def test_normalize_symbol(inp, expected):
    assert sodex_links._normalize_symbol(inp) == expected


def test_symbol_url_perps_default():
    assert sodex_links.symbol_url("BTC") == "https://sodex.com/trade/futures/BTC_USDC"


def test_symbol_url_spot():
    assert sodex_links.symbol_url("ETH", "spot") == "https://sodex.com/trade/spot/ETH_USDC"


def test_symbol_url_unknown_kind_falls_back_to_perps():
    assert sodex_links.symbol_url("SOL", "garbage") == "https://sodex.com/trade/futures/SOL_USDC"


def test_portfolio_url():
    assert sodex_links.portfolio_url() == "https://sodex.com/portfolio"


def test_explorer_url():
    assert sodex_links.explorer_url("perps") == "https://sodex.com/explorer?blocktype=futures"
    assert sodex_links.explorer_url("spot")  == "https://sodex.com/explorer?blocktype=spot"


def test_build_links_keys():
    out = sodex_links.build_links("BTC", "perps")
    assert set(out) == {"symbol_url", "portfolio_url", "explorer_url"}
    assert out["symbol_url"].endswith("/trade/futures/BTC_USDC")


# ── Composite payload ────────────────────────────────────────────────────

def test_build_links_payload_paper_trade_has_no_fills_call():
    """Non-sodex trades return empty fills WITHOUT invoking the fetcher."""
    called = {"n": 0}

    def stub(order_id):
        called["n"] += 1
        return [{"price": "100"}]

    row = {"token_symbol": "BTC", "execution_type": "paper", "sodex_order_id": None}
    out = sodex_links.build_links_payload(row, fills_fetcher=stub)
    assert out["fills"] == []
    assert called["n"] == 0
    assert out["symbol_url"].endswith("/trade/futures/BTC_USDC")


def test_build_links_payload_sodex_with_order_calls_fetcher():
    expected_fills = [
        {"price": "104500.00", "qty": "0.001", "fee": "0.025", "ts": 1700000000, "side": "buy"},
    ]

    def stub(order_id):
        assert order_id == 12345
        return expected_fills

    row = {"token_symbol": "BTC", "execution_type": "sodex_perps", "sodex_order_id": 12345}
    out = sodex_links.build_links_payload(row, fills_fetcher=stub)
    assert out["fills"] == expected_fills


def test_build_links_payload_fetcher_failure_returns_empty():
    """Graceful degrade — never raise on fetcher exceptions."""
    def boom(order_id):
        raise RuntimeError("network down")

    row = {"token_symbol": "ETH", "execution_type": "sodex_perps", "sodex_order_id": 99}
    out = sodex_links.build_links_payload(row, fills_fetcher=boom)
    assert out["fills"] == []
    assert "explorer_url" in out
