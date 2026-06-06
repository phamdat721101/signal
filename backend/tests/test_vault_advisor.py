"""Tests for app.vault_advisor — descriptor shape + card-row mapping."""
from __future__ import annotations

import re
from app import vault_advisor


def test_vaults_has_two_entries():
    assert len(vault_advisor.VAULTS) == 2


def test_vault_kinds_are_unique():
    kinds = [v["kind"] for v in vault_advisor.VAULTS]
    assert kinds == ["slp", "smag7"]
    assert len(set(kinds)) == 2


def test_target_urls_point_to_sodex():
    pattern = re.compile(r"^https://sodex\.com/")
    for v in vault_advisor.VAULTS:
        assert pattern.match(v["target_url"]), v["target_url"]


def test_accepted_assets_non_empty():
    for v in vault_advisor.VAULTS:
        assert isinstance(v["accepted_assets"], list)
        assert len(v["accepted_assets"]) >= 1


def test_vault_to_card_minimum_shape():
    """`generate_vault_cards` insert payload must satisfy the cards
    schema's required columns (card_type/source/token_symbol/chain).
    """
    for v in vault_advisor.VAULTS:
        card = vault_advisor._vault_to_card(v)
        assert card["card_type"] == "vault"
        assert card["source"] == "sodex"
        assert card["chain"] == "sodex"
        assert card["token_symbol"]
        assert card["dex_link"].startswith("https://sodex.com/")
        rs = card["research_summary"]
        assert rs["vault_kind"] in ("slp", "smag7")
        assert rs["min_deposit_usd"] >= 0
