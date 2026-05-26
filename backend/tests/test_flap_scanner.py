"""Flap scanner regression tests.

Covers the PRD spec as executable behavior:
  - CDPV2 progress math matches the docs example
  - score >= 50 floor
  - status != Tradable -> None
  - progress < 0.30 -> None
  - taxRate >= 1500 (15%) -> None
  - 6h dedupe via the existing helper
  - asyncio.run loop safety across multiple invocations
"""
from __future__ import annotations

import asyncio

import pytest

from app import flap_scanner
from app.flap_scanner import CDPV2, _score


ONE_E18 = 10**18


# ── CDPV2 math ──────────────────────────────────────────────────────────────

def test_cdpv2_progress_at_threshold_is_one():
    """When supply == dexSupplyThresh, progress should be 1.0."""
    c = CDPV2(r=16.0, h=0.0, k=1e9 * 16.0)
    p = c.progress(supply=8e8, dex_supply_thresh=8e8)
    assert abs(p - 1.0) < 1e-9


def test_cdpv2_progress_increases_monotonically():
    c = CDPV2(r=16.0, h=0.0, k=1e9 * 16.0)
    p_low = c.progress(supply=2e8, dex_supply_thresh=8e8)
    p_mid = c.progress(supply=5e8, dex_supply_thresh=8e8)
    p_hi = c.progress(supply=7.5e8, dex_supply_thresh=8e8)
    assert 0 < p_low < p_mid < p_hi <= 1


def test_cdpv2_progress_clamped_to_unit_interval():
    """Even if supply exceeds the threshold (post-graduation), progress is 1."""
    c = CDPV2(r=16.0, h=0.0, k=1e9 * 16.0)
    assert c.progress(supply=9e8, dex_supply_thresh=8e8) == 1.0


# ── _score: hard filters ────────────────────────────────────────────────────

def _state(**overrides) -> dict:
    """Build a baseline TokenStateV7 dict (all values in 1e18 fixed-point where appropriate)."""
    base = {
        "status": 1,                        # Tradable
        "progress": int(0.73 * ONE_E18),    # 73% to DEX
        "price": int(0.00084 * ONE_E18),    # in OKB
        "circulatingSupply": int(5e8 * ONE_E18),
        "taxRate": 100,                     # 1% (basis points)
        "address": "0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "symbol": "WUMBO",
        "name": "Wumbology Inc.",
    }
    base.update(overrides)
    return base


def test_score_accepts_well_progressed_low_tax():
    g = _score(_state(), age_hours=4, okb_usd=50.0)
    assert g is not None
    assert g.score >= 50
    assert g.progress == pytest.approx(0.73, rel=1e-3)


def test_score_rejects_staged_status():
    g = _score(_state(status=5), age_hours=4, okb_usd=50.0)  # Staged
    assert g is None


def test_score_rejects_killed_status():
    g = _score(_state(status=3), age_hours=4, okb_usd=50.0)  # Killed
    assert g is None


def test_score_rejects_low_progress():
    g = _score(_state(progress=int(0.20 * ONE_E18)), age_hours=4, okb_usd=50.0)
    assert g is None


def test_score_rejects_predatory_tax():
    g = _score(_state(taxRate=2000), age_hours=4, okb_usd=50.0)  # 20%
    assert g is None


# ── _score: soft scoring ────────────────────────────────────────────────────

def test_score_high_progress_band_gives_bigger_bonus():
    low = _score(_state(progress=int(0.50 * ONE_E18)), age_hours=4, okb_usd=50.0)
    high = _score(_state(progress=int(0.92 * ONE_E18)), age_hours=4, okb_usd=50.0)
    assert low and high and high.score > low.score


def test_score_penalizes_high_but_not_predatory_tax():
    low_tax = _score(_state(taxRate=100), age_hours=4, okb_usd=50.0)
    high_tax = _score(_state(taxRate=900), age_hours=4, okb_usd=50.0)
    assert low_tax and low_tax.score >= 50
    # 9% tax token may or may not pass the 50 floor, but if it does, must score lower
    if high_tax:
        assert high_tax.score < low_tax.score


# ── scan_for_flap_gems integration (mocked) ─────────────────────────────────

@pytest.mark.asyncio
async def test_scan_dedupes_recent_symbols(monkeypatch):
    async def fake_seed():
        return [{"address": "0xaaa", "age_hours": 4.0, "name": "Wumbo", "symbol": "WUMBO"}]

    def fake_state(addr):
        return _state(address=addr.lower())

    def fake_recent(hours: int = 6):
        return {"WUMBO"}

    monkeypatch.setattr(flap_scanner, "_seed_taxed_fun_board", fake_seed)
    monkeypatch.setattr(flap_scanner, "read_portal_state", fake_state)
    monkeypatch.setattr(flap_scanner, "_recent_gem_symbols", fake_recent)
    monkeypatch.setattr(flap_scanner, "_get_okb_usd", lambda: 50.0)
    monkeypatch.setattr(flap_scanner, "_get_portal", lambda: (object(), object()))

    gems = await flap_scanner.scan_for_flap_gems(limit=5)
    assert gems == [], "dedupe must skip recent symbols"


@pytest.mark.asyncio
async def test_scan_returns_top_n_sorted_by_score(monkeypatch):
    async def fake_seed():
        return [
            {"address": f"0x{i:040x}", "age_hours": 4.0, "name": f"T{i}", "symbol": f"T{i}"}
            for i in range(7)
        ]

    def fake_state(addr):
        i = int(addr, 16) % 100
        # Vary progress so scores differ
        return _state(
            address=addr.lower(),
            progress=int((0.30 + 0.10 * i) * ONE_E18),
            symbol=f"T{i}",
            name=f"T{i}",
        )

    monkeypatch.setattr(flap_scanner, "_seed_taxed_fun_board", fake_seed)
    monkeypatch.setattr(flap_scanner, "read_portal_state", fake_state)
    monkeypatch.setattr(flap_scanner, "_recent_gem_symbols", lambda hours=6: set())
    monkeypatch.setattr(flap_scanner, "_get_okb_usd", lambda: 50.0)
    monkeypatch.setattr(flap_scanner, "_get_portal", lambda: (object(), object()))

    gems = await flap_scanner.scan_for_flap_gems(limit=3)
    assert len(gems) == 3
    assert gems[0].score >= gems[1].score >= gems[2].score


def test_scan_safe_across_multiple_asyncio_run_calls(monkeypatch):
    """Regression for the closed-loop singleton bug we hit on gem_scanner."""
    async def fake_seed():
        return []
    monkeypatch.setattr(flap_scanner, "_seed_taxed_fun_board", fake_seed)
    monkeypatch.setattr(flap_scanner, "_get_portal", lambda: (object(), object()))
    monkeypatch.setattr(flap_scanner, "_recent_gem_symbols", lambda hours=6: set())

    for _ in range(3):
        from app import http_client
        http_client._async = None
        gems = asyncio.run(flap_scanner.scan_for_flap_gems(limit=1))
        assert gems == []
