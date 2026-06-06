"""vault_advisor.py — SoDex vault descriptors + idempotent card upsert.

Single Responsibility: turn the static SoDex vault catalog into
`card_type='vault'` rows that flow through the same Feed/History
plumbing as pool and trading-signal cards.

Live metrics (NAV, 24h change, multi-period ROI) come from the
SoSoValue index-snapshot endpoint — both vaults are denominated in
MAG7.ssi / sMAG7.ssi, so a single snapshot covers both. The fetcher
inherits the http_client retry + circuit breaker, and the result is
already 60-s cached upstream in `sosovalue_client._cache`.

Wave-2 demo posture: vault deposits are wallet-signed via SoDex's web
UI (no programmatic API exists), so each card carries a `target_url`
deep-link. Frontend opens it in a new tab; user finishes the deposit
there. We record `vault_allocations.intent` and let the user mark the
row CONFIRMED on return — same UX shape as the LP "OPEN ON DEX" path.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# SoSoValue index ticker that backs both vaults.
_INDEX_TICKER = "ssiMAG7"

# Source of truth — keep in lock-step with sodex.com/documentation/vault-overview.
VAULTS: list[dict[str, Any]] = [
    {
        "kind": "slp",
        "name": "SoDEX Liquidity Provider",
        "short_name": "SLP",
        "display_symbol": "SLP",
        "accepted_assets": ["MAG7.ssi", "sMAG7.ssi"],
        "lockup_label": "Instant for sMAG7.ssi · 14-day for MAG7.ssi",
        "lockup_days_for_mag7": 14,
        "yield_sources": [
            "Index staking yield",
            "Market-making fee rebate",
            "SOSO airdrop eligibility",
        ],
        "min_deposit_usd": 50.0,
        "risk_score": 35,                              # lower-mid: passive MM, not directional
        "rarity": "epic",
        "narrative": "Earn dual yield by providing liquidity to SoDEX's onchain order book.",
        "target_url": "https://sodex.com/vault/slp",
        "index_ticker": _INDEX_TICKER,
    },
    {
        "kind": "smag7",
        "name": "sMAG7.ssi Vault",
        "short_name": "sMAG7",
        "display_symbol": "sMAG7",
        "accepted_assets": ["sMAG7.ssi"],
        "lockup_label": "Instant withdrawal in sMAG7.ssi",
        "lockup_days_for_mag7": 0,
        "yield_sources": [
            "MAG7 index exposure",
            "Passive market-making rebate",
            "SOSO airdrop eligibility",
        ],
        "min_deposit_usd": 50.0,
        "risk_score": 30,
        "rarity": "rare",
        "narrative": "Stake sMAG7.ssi to earn market-making fees on top of your index exposure.",
        "target_url": "https://sodex.com/vault/smag7",
        "index_ticker": _INDEX_TICKER,
    },
]


def fetch_live_metrics(ticker: str = _INDEX_TICKER) -> dict[str, Any]:
    """Pull live NAV + multi-period ROI for the index that backs the vault.

    Graceful empty dict on failure — vault cards still render, just
    without the live block. Cached 60-s upstream in sosovalue_client.
    """
    try:
        from app.sosovalue_client import get_index_snapshot, _is_enabled
        if not _is_enabled():
            return {}
        snap = get_index_snapshot(ticker)
        if not isinstance(snap, dict):
            return {}
        # Whitelist + rename to FE-friendly keys; values are floats.
        return {
            "nav_usd": float(snap.get("price") or 0.0),
            "change_24h_pct": float(snap.get("change_pct_24h") or 0.0) * 100.0,
            "roi_7d_pct":  float(snap.get("roi_7d") or 0.0) * 100.0,
            "roi_1m_pct":  float(snap.get("roi_1m") or 0.0) * 100.0,
            "roi_3m_pct":  float(snap.get("roi_3m") or 0.0) * 100.0,
            "roi_1y_pct":  float(snap.get("roi_1y") or 0.0) * 100.0,
            "ytd_pct":     float(snap.get("ytd") or 0.0) * 100.0,
        }
    except Exception as e:
        logger.warning("vault_advisor: live metrics fetch failed: %s", e)
        return {}


def _vault_to_card(v: dict[str, Any], live: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map a vault descriptor → cards-table row payload.

    Reuses existing nullable LP-card columns so no schema change is
    required: `dex_link` carries the SoDex deep-link, `chain` = 'sodex',
    `token0_symbol/token1_symbol` carry accepted assets, and
    `research_summary` (JSONB) carries the structured vault metadata
    that the FE configurator and `/allocate-vault` route both need.
    """
    accepted = v["accepted_assets"]
    live = live or {}
    return {
        "token_symbol": v["display_symbol"],
        "token_name":   v["name"],
        "chain":        "sodex",
        "hook":         v["narrative"],
        "roast":        v["lockup_label"],
        "metrics": [
            {"emoji": "💎", "label": "Yield",  "value": " + ".join(v["yield_sources"]),
             "sentiment": "bullish"},
            {"emoji": "🔒", "label": "Lockup", "value": v["lockup_label"], "sentiment": "neutral"},
        ],
        "card_type":   "vault",
        "source":      "sodex",
        "verdict":     "APE",
        "risk_score":  v["risk_score"],
        "rarity":      v["rarity"],
        "token0_symbol": accepted[0],
        "token1_symbol": accepted[1] if len(accepted) > 1 else accepted[0],
        "chain_id":      138565,                       # SoDex testnet domain id
        "dex_link":      v["target_url"],              # consumed by FE deep-link CTA
        "research_summary": {
            "vault_kind":      v["kind"],
            "accepted_assets": v["accepted_assets"],
            "lockup_label":    v["lockup_label"],
            "lockup_days_for_mag7": v["lockup_days_for_mag7"],
            "yield_sources":   v["yield_sources"],
            "min_deposit_usd": v["min_deposit_usd"],
            "target_url":      v["target_url"],
            "short_name":      v["short_name"],
            "index_ticker":    v["index_ticker"],
            # Live metrics block. Frontend renders any present field; an
            # empty `live` dict just means we render the static card.
            "live":            live,
        },
        "price": live.get("nav_usd") or 0,             # surfaces NAV in the standard `price` column for sort/filter
        "price_change_24h": live.get("change_24h_pct") or 0,
        "volume_24h": 0,
        "market_cap": 0,
    }


def generate_vault_cards() -> int:
    """Idempotently upsert the 2 vault cards. Returns rows touched.

    One live-metrics fetch per refresh (single SoSoValue call covers
    both vaults since they share the ssiMAG7 index). Dedupe key:
    (card_type='vault', source='sodex', token_symbol).
    """
    from app import db
    from psycopg2.extras import Json

    conn = db._get_conn()
    if not conn:
        logger.warning("vault_advisor: no db connection; skipping")
        return 0

    live = fetch_live_metrics()                        # one upstream call
    touched = 0
    with conn.cursor() as cur:
        for v in VAULTS:
            row = _vault_to_card(v, live)
            cur.execute(
                "SELECT id FROM cards "
                "WHERE card_type = 'vault' AND source = 'sodex' AND token_symbol = %s "
                "LIMIT 1",
                (row["token_symbol"],),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """UPDATE cards SET
                          token_name = %s, hook = %s, roast = %s,
                          metrics = %s, risk_score = %s,
                          dex_link = %s, research_summary = %s,
                          token0_symbol = %s, token1_symbol = %s,
                          chain_id = %s, status = 'active',
                          price = %s, price_change_24h = %s,
                          expires_at = NOW() + INTERVAL '7 days'
                       WHERE id = %s""",
                    (row["token_name"], row["hook"], row["roast"],
                     Json(row["metrics"]), row["risk_score"],
                     row["dex_link"], Json(row["research_summary"]),
                     row["token0_symbol"], row["token1_symbol"],
                     row["chain_id"], row["price"], row["price_change_24h"],
                     existing[0]),
                )
            else:
                db.insert_card(row)
            touched += 1
    logger.info("vault_advisor: %d vault cards refreshed (live=%s)", touched, bool(live))
    return touched
