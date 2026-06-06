"""vault_advisor.py — SoDex vault descriptors + idempotent card upsert.

Single Responsibility: turn the static SoDex vault catalog into
`card_type='vault'` rows that flow through the same Feed/History
plumbing as pool and trading-signal cards.

Why static: SoDex has not yet exposed a public vault-catalog API. The
two vaults documented at https://sodex.com/documentation/vault-overview/
are stable across testnet/mainnet — when more vaults launch, append a
new dict to `VAULTS`. No code change elsewhere is required.

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
        "target_url": "https://sodex.com/portfolio?vault=slp",
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
        "target_url": "https://sodex.com/portfolio?vault=smag7",
    },
]


def _vault_to_card(v: dict[str, Any]) -> dict[str, Any]:
    """Map a vault descriptor → cards-table row payload.

    Reuses existing nullable LP-card columns so no schema change is
    required: `dex_link` carries the SoDex deep-link, `chain` = 'sodex',
    `token0_symbol/token1_symbol` carry accepted assets, and
    `research_summary` (JSONB) carries the structured vault metadata
    that the FE configurator and `/allocate-vault` route both need.
    """
    accepted = v["accepted_assets"]
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
        # LP-column reuse — vault metadata lives where pool metadata would.
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
        },
        # Price/volume are not meaningful for vaults; keep nullable.
        "price": 0,
        "price_change_24h": 0,
        "volume_24h": 0,
        "market_cap": 0,
    }


def generate_vault_cards() -> int:
    """Idempotently upsert the 2 vault cards. Returns rows touched.

    Dedupe key: (card_type='vault', source='sodex', token_symbol). Avoids
    a fresh row on every 30-min tick — the existing card stays current
    via its `updated_at`, while history-derived swipes/allocations remain
    valid (FK-style by id, but we never delete; just refresh the row).
    """
    from app import db
    from psycopg2.extras import Json

    conn = db._get_conn()
    if not conn:
        logger.warning("vault_advisor: no db connection; skipping")
        return 0

    touched = 0
    with conn.cursor() as cur:
        for v in VAULTS:
            row = _vault_to_card(v)
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
                          chain_id = %s, status = 'active'
                       WHERE id = %s""",
                    (row["token_name"], row["hook"], row["roast"],
                     Json(row["metrics"]), row["risk_score"],
                     row["dex_link"], Json(row["research_summary"]),
                     row["token0_symbol"], row["token1_symbol"],
                     row["chain_id"], existing[0]),
                )
            else:
                db.insert_card(row)
            touched += 1
    logger.info("vault_advisor: %d vault cards refreshed", touched)
    return touched
