"""Trustless Work Escrow Client + OWS Agent Wallet management."""
import logging
import httpx
from stellar_sdk import Keypair
from app.config import get_settings

logger = logging.getLogger(__name__)


PLATFORM_FEE_PCT = 10


def _headers():
    key = get_settings().trustless_api_key
    return {"x-api-key": key, "Content-Type": "application/json"}


def _api_url():
    return get_settings().trustless_api_url


# ─── Agent Wallet (OWS) ─────────────────────────────────────

def generate_agent_wallet() -> dict:
    """Generate a Stellar keypair for an agent. Returns {public_key, secret}."""
    kp = Keypair.random()
    return {"public_key": kp.public_key, "secret": kp.secret}


# ─── Trustless Work API ──────────────────────────────────────

async def deploy_escrow(subscriber_stellar: str, provider_stellar: str, amount_usdc: float, signal_id: int) -> dict:
    """Deploy a single-release escrow for a signal subscription."""
    s = get_settings()
    payload = {
        "signer": s.stellar_platform_address,
        "engagementId": f"signal-{signal_id}",
        "title": f"Signal #{signal_id} Subscription",
        "description": "Pay-per-alpha: funds released if signal is profitable within 24h",
        "amount": amount_usdc,
        "platformFee": PLATFORM_FEE_PCT,
        "roles": {
            "approver": s.stellar_platform_address,
            "serviceProvider": provider_stellar,
            "platformAddress": s.stellar_fee_address or s.stellar_platform_address,
            "releaseSigner": s.stellar_platform_address,
            "disputeResolver": s.stellar_admin_address or s.stellar_platform_address,
            "receiver": provider_stellar,
        },
        "milestones": [{"description": "Signal resolves profitably within 24h"}],
        "trustline": {
            "symbol": "USDC",
            "address": "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5",
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_api_url()}/deployer/single-release", json=payload, headers=_headers())
        if resp.status_code != 201:
            raise Exception(f"{resp.status_code}: {resp.text}")
        return resp.json()


async def fund_escrow(escrow_address: str, subscriber_stellar: str) -> dict:
    """Get unsigned XDR for funding an escrow."""
    payload = {"contractId": escrow_address, "signer": subscriber_stellar}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_api_url()}/escrow/single-release/fund-escrow", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def change_milestone_status(escrow_address: str, milestone_index: int, status: str, evidence: str = "") -> dict:
    """Mark milestone as completed or failed."""
    s = get_settings()
    payload = {
        "contractId": escrow_address,
        "milestoneIndex": milestone_index,
        "newStatus": status,
        "evidence": evidence,
        "signer": s.stellar_platform_address,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_api_url()}/escrow/single-release/change-milestone-status", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def release_funds(escrow_address: str) -> dict:
    """Release funds to receiver (provider won)."""
    s = get_settings()
    payload = {"contractId": escrow_address, "signer": s.stellar_platform_address}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_api_url()}/escrow/single-release/release-funds", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def get_escrows_by_role(stellar_address: str, role: str = "depositor") -> list:
    """Get escrows for a given address and role."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{_api_url()}/helper/get-escrows-by-role",
            params={"address": stellar_address, "role": role},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def submit_transaction(signed_xdr: str) -> dict:
    """Submit a signed XDR transaction to Stellar via Trustless Work helper."""
    payload = {"signedXdr": signed_xdr}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_api_url()}/helper/send-transaction", json=payload, headers=_headers())
        if resp.status_code not in (200, 201):
            raise Exception(f"{resp.status_code}: {resp.text}")
        return resp.json()


async def resolve_signal_escrow(escrow_address: str, profitable: bool, evidence: str) -> dict:
    """Full resolution: mark milestone + release/refund."""
    status = "completed" if profitable else "failed"
    await change_milestone_status(escrow_address, 0, status, evidence)
    if profitable:
        return await release_funds(escrow_address)
    # For failed signals, Trustless Work auto-refunds on failed milestone
    return {"status": "refunded", "evidence": evidence}
