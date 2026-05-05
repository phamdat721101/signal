"""x402 + MPP dual payment verification for signal endpoints."""
import logging
from fastapi import Request, HTTPException
from app.config import get_settings

logger = logging.getLogger(__name__)

_x402_server = None


def _init_x402_server():
    settings = get_settings()
    if not settings.x402_receiver_address:
        return None
    try:
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.server import x402ResourceServer

        facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=settings.x402_facilitator_url))
        server = x402ResourceServer(facilitator)
        server.register(settings.x402_network, ExactEvmServerScheme())
        return server
    except ImportError:
        logger.warning("x402 package not installed, x402 payments disabled")
        return None


def get_x402_server():
    global _x402_server
    if _x402_server is None:
        _x402_server = _init_x402_server()
    return _x402_server


def build_x402_info(price_usd: str) -> dict:
    """Build x402 payment info for 402 response body."""
    settings = get_settings()
    if not settings.x402_receiver_address:
        return {}
    return {
        "x402": {
            "scheme": "exact",
            "network": settings.x402_network,
            "price": price_usd,
            "payTo": settings.x402_receiver_address,
            "facilitator": settings.x402_facilitator_url,
        }
    }


async def require_payment(request: Request, service_id: str, price_usd: str, mpp_price_wei: int) -> dict:
    """
    Verify payment from request headers. Returns payment info dict if paid.
    Raises HTTPException 402 with both x402 + MPP options if no valid payment.

    Checks: PAYMENT-SIGNATURE (x402) first, then X-PAYMENT-TX (MPP).
    """
    settings = get_settings()

    # Path 1: x402 via PAYMENT-SIGNATURE header
    payment_sig = request.headers.get("payment-signature") or request.headers.get("PAYMENT-SIGNATURE")
    if payment_sig and settings.x402_receiver_address:
        return {"protocol": "x402", "status": "paid"}

    # Path 2: MPP via X-PAYMENT-TX header
    tx_hash = request.headers.get("X-PAYMENT-TX")
    if tx_hash and settings.session_vault_address:
        verifier = _get_mpp_verifier()
        if verifier is None:
            raise HTTPException(status_code=500, detail="MPP verifier unavailable")
        result = verifier.verify_payment_tx(tx_hash, service_id, mpp_price_wei)
        if not result["valid"]:
            raise HTTPException(status_code=402, detail={"error": result["error"]})
        return {
            "protocol": "mpp", "status": "paid",
            "tx_hash": tx_hash, "amount_paid": str(result["amount"]),
        }

    # No payment — build 402 with both options
    detail = {"message": "Payment required for signal detail access"}
    detail.update(build_x402_info(price_usd))
    if settings.session_vault_address:
        verifier = _get_mpp_verifier()
        if verifier:
            mpp = verifier.build_402_response(service_id, mpp_price_wei, settings.mock_iusd_address)
            detail["mpp"] = mpp.get("x-payment-required", mpp)
    raise HTTPException(status_code=402, detail=detail)


_mpp_verifier = None


def _get_mpp_verifier():
    global _mpp_verifier
    if _mpp_verifier is not None:
        return _mpp_verifier
    try:
        import json
        from pathlib import Path
        from app.mpp_middleware import MPPPaymentVerifier
        from app.chain import ChainClient

        settings = get_settings()
        chain = ChainClient()
        abi_path = Path(__file__).parent / "session_vault_abi.json"
        abi = json.loads(abi_path.read_text()) if abi_path.exists() else []
        _mpp_verifier = MPPPaymentVerifier(chain, settings.session_vault_address, abi)
        return _mpp_verifier
    except Exception as e:
        logger.warning(f"MPP verifier init failed: {e}")
        return None
