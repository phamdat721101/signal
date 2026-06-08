"""Tests for the GOAT testnet x402 rail.

Unit tests (Tasks 2-4): pure price math, envelope shape, verifier branches
with mocked Web3, factory enable/disable behavior.

E2E tests (Tasks 5-6): TestClient against agent_main exercising the
402 → x-payment-tx → 200 flow and verifying the existing Base/Somnia
rails are not regressed.
"""
from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import goat_payment
from app.goat_payment import (
    GoatPaywallVerifier,
    VerifyResult,
    build_challenge_envelope,
    get_goat_x402_middleware_args,
    usd_to_token_wei,
)


# ─── Task 2 — Pure utilities ───────────────────────────────────────────────

def test_usd_to_token_wei_basic_btc_18dec():
    # $0.001 / $65000 * 1e18 = 15_384_615_384.615… → floor → 15_384_615_384
    # ($0.001 = 1e-8 BTC at $65k; 1e-8 BTC = 1e10 wei at 18 dec)
    wei = usd_to_token_wei("$0.001", 65000.0, 18)
    assert 15_384_615_383 <= wei <= 15_384_615_385


def test_usd_to_token_wei_strips_dollar_sign_and_whitespace():
    assert usd_to_token_wei("$0.01", 65000.0, 18) == usd_to_token_wei(" 0.01 ", 65000.0, 18)


def test_usd_to_token_wei_floors_to_at_least_one_wei():
    # Tiny price * huge token price → fractional wei → must floor to >= 1
    assert usd_to_token_wei("$0.0000000000000001", 1e18, 6) == 1


def test_usd_to_token_wei_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        usd_to_token_wei("$0.001", 0.0, 18)
    with pytest.raises(ValueError):
        usd_to_token_wei("", 65000.0, 18)


def test_build_challenge_envelope_shape():
    env_b64 = build_challenge_envelope(
        network="eip155:48816",
        asset="0xbC10000000000000000000000000000000000000",
        pay_to="0x100690a32B562fd45e685BC2E63bbfF566d452db",
        max_amount_wei=15_384_615_384_615,
        token_symbol="WGBTC",
    )
    decoded = json.loads(base64.b64decode(env_b64))
    assert decoded["x402Version"] == 2
    assert decoded["accepts"][0]["scheme"] == "exact"
    assert decoded["accepts"][0]["network"] == "eip155:48816"
    assert decoded["accepts"][0]["maxAmountRequired"] == "15384615384615"  # stringified
    assert decoded["accepts"][0]["tokenSymbol"] == "WGBTC"


# ─── Task 3 — GoatPaywallVerifier ──────────────────────────────────────────

PAY_TO = "0x100690a32B562fd45e685BC2E63bbfF566d452db"
PAYER = "0xAaBbCcDdEeFf00112233445566778899AaBbCcDd"
TOKEN = "0xbC10000000000000000000000000000000000000"
ROUTE = "GET /goat-api/api/v2/agent/decisions"
GOOD_TX = "0x" + "a" * 64
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _topic_addr(addr: str) -> bytes:
    return bytes.fromhex(addr.lower().replace("0x", "").rjust(64, "0"))


def _make_topic_hex(hexstr: str):
    """Return an object with .hex() returning the given hex string (mimics web3 HexBytes)."""
    obj = MagicMock()
    obj.hex.return_value = hexstr
    return obj


def _make_data_hex(value_wei: int):
    obj = MagicMock()
    obj.hex.return_value = hex(value_wei)
    return obj


def _make_receipt(*, status=1, logs=None) -> dict:
    return {"status": status, "logs": logs or []}


def _transfer_log(*, from_addr=PAYER, to_addr=PAY_TO, value_wei=20_000_000_000_000, token=TOKEN):
    return {
        "address": token,
        "topics": [
            _make_topic_hex(TRANSFER_TOPIC0),
            _make_topic_hex("0x" + _topic_addr(from_addr).hex()),
            _make_topic_hex("0x" + _topic_addr(to_addr).hex()),
        ],
        "data": _make_data_hex(value_wei),
    }


def _make_verifier() -> GoatPaywallVerifier:
    w3 = MagicMock()
    return GoatPaywallVerifier(w3, TOKEN, PAY_TO)


@pytest.mark.asyncio
async def test_verify_invalid_txhash_format():
    v = _make_verifier()
    result = await v.verify("not-a-tx", ROUTE, 1)
    assert result == VerifyResult(ok=False, reason="invalid_tx_hash")
    v._w3.eth.get_transaction_receipt.assert_not_called()


@pytest.mark.asyncio
async def test_verify_success_then_cache_hit():
    v = _make_verifier()
    receipt = _make_receipt(logs=[_transfer_log(value_wei=20_000_000_000_000)])
    v._w3.eth.get_transaction_receipt = MagicMock(return_value=receipt)

    r1 = await v.verify(GOOD_TX, ROUTE, 15_384_615_384_615)
    assert r1.ok and r1.payer.lower() == PAYER.lower() and r1.value_wei == 20_000_000_000_000

    # Second call within window → cache hit, no RPC.
    v._w3.eth.get_transaction_receipt.reset_mock()
    r2 = await v.verify(GOOD_TX, ROUTE, 15_384_615_384_615)
    assert r2.ok
    v._w3.eth.get_transaction_receipt.assert_not_called()


@pytest.mark.asyncio
async def test_verify_cache_route_mismatch_blocks_reuse():
    v = _make_verifier()
    receipt = _make_receipt(logs=[_transfer_log(value_wei=20_000_000_000_000)])
    v._w3.eth.get_transaction_receipt = MagicMock(return_value=receipt)
    await v.verify(GOOD_TX, ROUTE, 1)

    other_route = "GET /goat-api/api/v2/agent/pools"
    r = await v.verify(GOOD_TX, other_route, 1)
    assert not r.ok and r.reason == "tx_already_spent_on_other_route"


@pytest.mark.asyncio
async def test_verify_receipt_unavailable():
    v = _make_verifier()
    v._w3.eth.get_transaction_receipt = MagicMock(side_effect=Exception("rpc down"))
    # Patch sleep so the test isn't slow.
    with patch.object(goat_payment.asyncio, "sleep", AsyncMock()):
        r = await v.verify(GOOD_TX, ROUTE, 1)
    assert not r.ok and r.reason == "receipt_unavailable"


@pytest.mark.asyncio
async def test_verify_tx_reverted():
    v = _make_verifier()
    receipt = _make_receipt(status=0, logs=[_transfer_log()])
    v._w3.eth.get_transaction_receipt = MagicMock(return_value=receipt)
    r = await v.verify(GOOD_TX, ROUTE, 1)
    assert not r.ok and r.reason == "tx_reverted"


@pytest.mark.asyncio
async def test_verify_no_matching_transfer_wrong_token():
    v = _make_verifier()
    receipt = _make_receipt(logs=[_transfer_log(token="0x000000000000000000000000000000000000bEEF")])
    v._w3.eth.get_transaction_receipt = MagicMock(return_value=receipt)
    r = await v.verify(GOOD_TX, ROUTE, 1)
    assert not r.ok and r.reason == "no_matching_transfer_to_pay_to"


@pytest.mark.asyncio
async def test_verify_no_matching_transfer_underpayment():
    v = _make_verifier()
    receipt = _make_receipt(logs=[_transfer_log(value_wei=100)])  # tiny
    v._w3.eth.get_transaction_receipt = MagicMock(return_value=receipt)
    r = await v.verify(GOOD_TX, ROUTE, 1_000_000_000_000)
    assert not r.ok and r.reason == "no_matching_transfer_to_pay_to"


@pytest.mark.asyncio
async def test_verify_wrong_recipient():
    v = _make_verifier()
    other_recipient = "0x" + "1" * 40
    receipt = _make_receipt(logs=[_transfer_log(to_addr=other_recipient)])
    v._w3.eth.get_transaction_receipt = MagicMock(return_value=receipt)
    r = await v.verify(GOOD_TX, ROUTE, 1)
    assert not r.ok and r.reason == "no_matching_transfer_to_pay_to"


# ─── Task 4 — Factory ──────────────────────────────────────────────────────

def _stub_settings(monkeypatch, **overrides):
    """Reset the Settings cache and override env to control get_settings()."""
    from app import config

    monkeypatch.setattr(config, "_settings", None)
    for k, v in {
        "GOAT_X402_ENABLED": "false",
        "GOAT_X402_RECEIVER_ADDRESS": "",
        "GOAT_X402_TOKEN_ADDRESS": "0xbC10000000000000000000000000000000000000",
        "GOAT_X402_TOKEN_SYMBOL": "WGBTC",
        "GOAT_X402_TOKEN_DECIMALS": "18",
        "GOAT_X402_TOKEN_USD_PRICE": "65000.0",
        "GOAT_X402_NETWORK": "eip155:48816",
        "GOAT_X402_RPC_URL": "https://rpc.testnet3.goat.network",
        **overrides,
    }.items():
        monkeypatch.setenv(k, v)


def test_factory_disabled_returns_none(monkeypatch):
    _stub_settings(monkeypatch, GOAT_X402_ENABLED="false")
    routes, verifier = get_goat_x402_middleware_args()
    assert routes is None and verifier is None


def test_factory_enabled_no_receiver_returns_none(monkeypatch, caplog):
    _stub_settings(monkeypatch, GOAT_X402_ENABLED="true", GOAT_X402_RECEIVER_ADDRESS="")
    with caplog.at_level("WARNING"):
        routes, verifier = get_goat_x402_middleware_args()
    assert routes is None and verifier is None
    assert any("RECEIVER_ADDRESS" in r.message for r in caplog.records)


def test_factory_enabled_returns_priced_routes(monkeypatch):
    _stub_settings(
        monkeypatch,
        GOAT_X402_ENABLED="true",
        GOAT_X402_RECEIVER_ADDRESS=PAY_TO,
    )
    routes, verifier = get_goat_x402_middleware_args(prefix="/goat-api")
    assert verifier is not None
    assert "GET /goat-api/api/v2/agent/decisions" in routes
    assert "GET /goat-api/api/v2/agent/track-record" in routes

    decisions = routes["GET /goat-api/api/v2/agent/decisions"]
    track = routes["GET /goat-api/api/v2/agent/track-record"]
    # Parity with Base/Somnia rails (Decision 3=a)
    assert decisions.price_usd == "$0.001"
    assert track.price_usd == "$0.01"
    # $0.01 > $0.001 → wei amount should also be 10x larger.
    assert track.price_wei >= decisions.price_wei * 9


# ─── Task 5/6 — E2E TestClient (rail wiring + /api/health) ─────────────────

def _build_app(monkeypatch, *, goat_enabled: bool):
    """Build a fresh agent_main app with overridden settings.

    We import lazily after env is set so the module-level get_settings() and
    the lifespan see the right values. We also stub out heavy startup deps.
    """
    _stub_settings(
        monkeypatch,
        GOAT_X402_ENABLED="true" if goat_enabled else "false",
        GOAT_X402_RECEIVER_ADDRESS=PAY_TO if goat_enabled else "",
        # Keep Base+Somnia rails off so they don't try to dial CDP during tests.
        X402_RECEIVER_ADDRESS="",
        SOMNIA_X402_ENABLED="false",
    )
    # Prevent db_async from trying to connect during lifespan.
    from app import db_async as _db
    monkeypatch.setattr(_db, "init_pool", AsyncMock())
    monkeypatch.setattr(_db, "close_pool", AsyncMock())
    monkeypatch.setattr(_db, "is_ready", lambda: False)
    monkeypatch.setattr(_db, "health", AsyncMock(return_value={"status": "skipped"}))

    # Reload agent_main so the new env takes effect.
    import importlib
    from app import agent_main as _am
    importlib.reload(_am)
    return _am


def test_e2e_goat_disabled_returns_404(monkeypatch):
    am = _build_app(monkeypatch, goat_enabled=False)
    from fastapi.testclient import TestClient
    with TestClient(am.app) as client:
        r = client.get("/goat-api/api/v2/agent/decisions")
    assert r.status_code == 404


def test_e2e_goat_enabled_no_payment_tx_returns_402(monkeypatch):
    am = _build_app(monkeypatch, goat_enabled=True)
    from fastapi.testclient import TestClient
    with TestClient(am.app) as client:
        r = client.get("/goat-api/api/v2/agent/decisions")
    assert r.status_code == 402
    assert "payment-required" in {k.lower() for k in r.headers.keys()}
    assert r.headers.get("x-payment-rail") == "goat"
    decoded = json.loads(base64.b64decode(r.headers["payment-required"]))
    accept = decoded["accepts"][0]
    assert accept["network"] == "eip155:48816"
    assert accept["asset"].lower() == TOKEN.lower()
    assert accept["payTo"].lower() == PAY_TO.lower()
    assert int(accept["maxAmountRequired"]) > 0  # priced wei amount


def test_e2e_goat_invalid_txhash_returns_402_with_reason(monkeypatch):
    am = _build_app(monkeypatch, goat_enabled=True)
    from fastapi.testclient import TestClient
    with TestClient(am.app) as client:
        r = client.get("/goat-api/api/v2/agent/decisions",
                       headers={"x-payment-tx": "not-hex"})
    assert r.status_code == 402
    assert r.json().get("reason") == "invalid_tx_hash"


def test_e2e_goat_valid_txhash_passes_through(monkeypatch):
    am = _build_app(monkeypatch, goat_enabled=True)
    from fastapi.testclient import TestClient
    with TestClient(am.app) as client:
        # Lifespan has now run → _goat_verifier is set. Stub its verify()
        # to avoid hitting the real RPC.
        assert am._goat_verifier is not None
        am._goat_verifier.verify = AsyncMock(return_value=VerifyResult(
            ok=True, payer=PAYER, value_wei=20_000_000_000_000,
        ))
        r = client.get("/goat-api/api/v2/agent/decisions",
                       headers={"x-payment-tx": GOOD_TX})
    # Underlying agent_router should respond — db_async is stubbed so the
    # handler returns either a 200 with empty/fallback shape, or a 5xx if
    # the route hard-requires the DB. Either way, it is NOT 402, and the
    # paywall headers must indicate the rail acknowledged the payment.
    assert r.status_code != 402
    assert r.headers.get("x-payment-rail") == "goat"
    assert (r.headers.get("x-payment-payer") or "").lower() == PAYER.lower()


def test_e2e_health_reports_goat_rail(monkeypatch):
    am = _build_app(monkeypatch, goat_enabled=True)
    from fastapi.testclient import TestClient
    with TestClient(am.app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["goat_x402_configured"] is True
    assert any("/goat-api/api/v2/agent/decisions" in k for k in body["goat_routes"])


def test_e2e_base_rail_unchanged_when_goat_enabled(monkeypatch):
    """Regression guard: enabling GOAT must not touch the existing Base path.

    With X402_RECEIVER_ADDRESS empty (Base rail off), a GET on the Base
    surface stays a normal pass-through (200 or whatever the underlying
    handler returns), never a GOAT 402.
    """
    am = _build_app(monkeypatch, goat_enabled=True)
    from fastapi.testclient import TestClient
    with TestClient(am.app) as client:
        r = client.get("/api/v2/agent/decisions")
    # Crucial: must NOT carry the GOAT rail marker.
    assert r.headers.get("x-payment-rail") != "goat"
