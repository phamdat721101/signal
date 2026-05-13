"""Trustless Work Escrow Client + OWS Agent Wallet management."""
import os
import logging
import secrets
import httpx
from stellar_sdk import Keypair

logger = logging.getLogger(__name__)

TRUSTLESS_API = os.getenv("TRUSTLESS_API_URL", "https://dev.api.trustlesswork.com")
TRUSTLESS_API_KEY = os.getenv("TRUSTLESS_API_KEY", "")
PLATFORM_ADDRESS = os.getenv("STELLAR_PLATFORM_ADDRESS", "")
FEE_ADDRESS = os.getenv("STELLAR_FEE_ADDRESS", "")
ADMIN_ADDRESS = os.getenv("STELLAR_ADMIN_ADDRESS", "")
PLATFORM_FEE_PCT = 10


def _headers():
    return {"Authorization": f"Bearer {TRUSTLESS_API_KEY}", "Content-Type": "application/json"}


# ─── Agent Wallet (OWS) ─────────────────────────────────────

def generate_agent_wallet() -> dict:
    """Generate a Stellar keypair for an agent. Returns {public_key, secret}."""
    kp = Keypair.random()
    return {"public_key": kp.public_key, "secret": kp.secret}


# ─── Trustless Work API ──────────────────────────────────────

async def deploy_escrow(subscriber_stellar: str, provider_stellar: str, amount_usdc: float, signal_id: int) -> dict:
    """Deploy a single-release escrow for a signal subscription."""
    payload = {
        "engagementId": f"signal-{signal_id}",
        "title": f"Signal #{signal_id} Subscription",
        "description": f"Pay-per-alpha: funds released if signal is profitable within 24h",
        "amount": str(amount_usdc),
        "platformFee": str(PLATFORM_FEE_PCT),
        "receiverMemo": 0,
        "roles": {
            "depositor": subscriber_stellar,
            "receiver": provider_stellar,
            "serviceProvider": PLATFORM_ADDRESS,
            "approver": PLATFORM_ADDRESS,
            "releaseSigner": PLATFORM_ADDRESS,
            "platformAddress": FEE_ADDRESS,
            "disputeResolver": ADMIN_ADDRESS,
        },
        "milestones": [{"description": "Signal resolves profitably within 24h", "status": "pending"}],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{TRUSTLESS_API}/deployer/single-release", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def fund_escrow(escrow_address: str, subscriber_stellar: str) -> dict:
    """Get unsigned XDR for funding an escrow."""
    payload = {"contractId": escrow_address, "signer": subscriber_stellar}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{TRUSTLESS_API}/escrow/single-release/fund-escrow", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def change_milestone_status(escrow_address: str, milestone_index: int, status: str, evidence: str = "") -> dict:
    """Mark milestone as completed or failed."""
    payload = {
        "contractId": escrow_address,
        "milestoneIndex": milestone_index,
        "newStatus": status,
        "evidence": evidence,
        "signer": PLATFORM_ADDRESS,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{TRUSTLESS_API}/escrow/single-release/change-milestone-status", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def release_funds(escrow_address: str) -> dict:
    """Release funds to receiver (provider won)."""
    payload = {"contractId": escrow_address, "signer": PLATFORM_ADDRESS}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{TRUSTLESS_API}/escrow/single-release/release-funds", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def get_escrows_by_role(stellar_address: str, role: str = "depositor") -> list:
    """Get escrows for a given address and role."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{TRUSTLESS_API}/helper/get-escrows-by-role",
            params={"address": stellar_address, "role": role},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def resolve_signal_escrow(escrow_address: str, profitable: bool, evidence: str) -> dict:
    """Full resolution: mark milestone + release/refund."""
    status = "completed" if profitable else "failed"
    await change_milestone_status(escrow_address, 0, status, evidence)
    if profitable:
        return await release_funds(escrow_address)
    # For failed signals, Trustless Work auto-refunds on failed milestone
    return {"status": "refunded", "evidence": evidence}
