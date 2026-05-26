"""Gem scanner regression tests.

Encodes the PRD spec as executable behavior:
  - score >= 50 gate
  - mc < 50_000_000 hard ceiling
  - mc=0 escape hatch only when volume_24h > $200k
  - age window: 24h <= age <= 30d (when known)
  - 6-hour symbol dedupe
  - Honeypot/unverified rejection
  - Multiple sequential asyncio.run() calls do not crash on closed event loop

Run: cd backend && .venv/bin/pytest tests/ -v
"""
from __future__ import annotations

import asyncio

import pytest

from app import gem_scanner


# ── Fixtures ────────────────────────────────────────────────────────────────

def _safe(verified: bool = True) -> dict:
    return {"safe": True, "verified": verified}


def _token(**overrides) -> dict:
    base = {
        "symbol": "POND",
        "name": "Marlin",
        "address": "0x57b946008913b82e4df85f501cbaed910e58d26c",
        "chain": "ethereum",
        "price": 0.00257,
        "market_cap": 21_080_333,
        "volume_24h": 45_109_567,
        "liquidity": 0,
        "price_change_24h": 84.0,
        "age_hours": 240,  # 10 days
    }
    base.update(overrides)
    return base


# ── _score: market cap gating ───────────────────────────────────────────────

def test_score_accepts_low_cap_with_signals():
    """POND-shaped: low mc, high vol/mc, real momentum -> gem."""
    g = gem_scanner._score(_token(), _safe())
    assert g is not None
    assert g.gem_score >= 50
    assert g.market_cap < 50_000_000


def test_score_rejects_mid_cap_above_ceiling():
    """NEAR-shaped: $3.7B mcap is not a hidden gem, ever."""
    g = gem_scanner._score(
        _token(symbol="NEAR", market_cap=3_706_932_856, volume_24h=1_325_669_119, price_change_24h=18.0),
        _safe(),
    )
    assert g is None, "mid/large-cap must be rejected by the $50M ceiling"


def test_score_rejects_just_above_ceiling():
    """Boundary: $50M+1 should be rejected (PRD: mc < 50_000_000)."""
    g = gem_scanner._score(_token(market_cap=50_000_001), _safe())
    assert g is None


# ── _score: zero-mc handling (PRD edge case) ────────────────────────────────

def test_score_rejects_zero_mc_without_meaningful_volume():
    """Brand-new token, mc=0, $10k volume -> not enough signal."""
    g = gem_scanner._score(_token(market_cap=0, volume_24h=10_000, price_change_24h=0), _safe())
    assert g is None


def test_score_accepts_zero_mc_with_strong_volume():
    """Brand-new token, mc=0, $300k volume -> emerging-token escape hatch."""
    g = gem_scanner._score(_token(market_cap=0, volume_24h=300_000), _safe())
    assert g is not None, "emerging tokens with proven volume must surface"


# ── _score: age window ──────────────────────────────────────────────────────

def test_score_rejects_too_new_token():
    """<24h old: still in launch-day rug zone."""
    g = gem_scanner._score(_token(age_hours=12), _safe())
    assert g is None


def test_score_rejects_too_old_token():
    """>30d old: not 'hidden' anymore."""
    g = gem_scanner._score(_token(age_hours=24 * 31), _safe())
    assert g is None


def test_score_accepts_when_age_unknown():
    """If age_hours is missing, don't reject — DEXScreener doesn't always supply pairCreatedAt."""
    tok = _token()
    tok.pop("age_hours", None)
    g = gem_scanner._score(tok, _safe())
    assert g is not None


# ── _score: safety gate ─────────────────────────────────────────────────────

def test_score_rejects_honeypot():
    g = gem_scanner._score(_token(), {"safe": False})
    assert g is None


# ── scan_for_gems: 6h dedupe ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedupe_skips_recently_seen_symbol(monkeypatch):
    async def fake_dex():
        return [
            {"symbol": "POND", "tokenAddress": "0xpond", "description": "Marlin",
             "chainId": "ethereum", "totalAmount": 50_000_000},
        ]

    async def fake_cg():
        return []

    async def fake_safety(addr, chain_id="1"):
        return _safe()

    def fake_recent_symbols(hours: int):
        return {"POND"}  # already seen in last 6h

    monkeypatch.setattr(gem_scanner, "_fetch_dexscreener_boosts", fake_dex)
    monkeypatch.setattr(gem_scanner, "_fetch_coingecko_trending", fake_cg)
    monkeypatch.setattr(gem_scanner, "_check_safety", fake_safety)
    monkeypatch.setattr(gem_scanner, "_recent_gem_symbols", fake_recent_symbols)

    gems = await gem_scanner.scan_for_gems(limit=5)
    assert all(g.symbol != "POND" for g in gems), "dedupe must skip recently-seen symbols"


# ── scan_for_gems: event-loop reuse safety (regression for the closed-loop bug) ─

def test_scan_safe_across_multiple_asyncio_run_calls(monkeypatch):
    """Calling scan_for_gems via asyncio.run() three times must not raise
    'Event loop is closed' from a stale httpx singleton."""
    async def fake_dex():
        return []

    async def fake_cg():
        return []

    monkeypatch.setattr(gem_scanner, "_fetch_dexscreener_boosts", fake_dex)
    monkeypatch.setattr(gem_scanner, "_fetch_coingecko_trending", fake_cg)
    monkeypatch.setattr(gem_scanner, "_recent_gem_symbols", lambda hours: set())

    for _ in range(3):
        # _gem_scan_job in scheduler resets http_client._async; emulate that contract here.
        from app import http_client
        http_client._async = None
        gems = asyncio.run(gem_scanner.scan_for_gems(limit=1))
        assert gems == []
