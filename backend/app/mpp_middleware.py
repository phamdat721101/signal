"""MPP Payment Middleware — tx receipt verification for FastAPI"""
import json
import logging
from pathlib import Path

from web3 import Web3

logger = logging.getLogger(__name__)

SERVICE_PRICING = {
    "signal-basic": {"price_wei": int(0.001 * 1e18), "description": "Latest 10 signals"},
    "signal-premium": {"price_wei": int(0.01 * 1e18), "description": "All signals + analytics + leaderboard"},
    "signal-single": {"price_wei": int(0.002 * 1e18), "description": "Individual signal detail"},
}

# ServicePaid(uint256 indexed sessionId, address indexed payer, uint256 amount, string serviceId)
SERVICE_PAID_TOPIC = Web3.keccak(text="ServicePaid(uint256,address,uint256,string)")


class MPPPaymentVerifier:
    """Verifies payment by checking tx receipts for ServicePaid events."""

    def __init__(self, chain_client, session_vault_address: str, session_vault_abi: list):
        self.chain = chain_client
        self.vault_address = Web3.to_checksum_address(session_vault_address)
        self.vault = chain_client.w3.eth.contract(
            address=self.vault_address,
            abi=session_vault_abi,
        )
        self._used_tx_hashes: set[str] = set()

    def build_402_response(self, service_id: str, price_wei: int, token_address: str) -> dict:
        return {
            "x-payment-required": {
                "version": "pay-from-session-v1",
                "price": str(price_wei),
                "token": token_address,
                "network": "initia",
                "chainId": self.chain.w3.eth.chain_id,
                "sessionVault": self.vault_address,
                "accepts": ["pay-from-session-v1"],
                "serviceId": service_id,
            }
        }

    def verify_payment_tx(self, tx_hash: str, service_id: str, min_amount: int) -> dict:
        """Verify a payment tx contains a valid ServicePaid event."""
        tx_hash = tx_hash.strip()
        if tx_hash in self._used_tx_hashes:
            return {"valid": False, "error": "Transaction already used"}

        try:
            receipt = self.chain.w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            return {"valid": False, "error": f"Cannot fetch receipt: {e}"}

        if receipt["status"] != 1:
            return {"valid": False, "error": "Transaction failed"}

        # Find ServicePaid event from our vault contract
        for log in receipt["logs"]:
            if log["address"].lower() != self.vault_address.lower():
                continue
            if len(log["topics"]) < 3:
                continue
            if log["topics"][0].hex() != SERVICE_PAID_TOPIC.hex():
                continue

            # Decode: topics[1] = sessionId, topics[2] = payer
            # data = abi.encode(amount, serviceId)
            try:
                decoded = self.vault.events.ServicePaid().process_log(log)
                event_amount = decoded["args"]["amount"]
                event_service = decoded["args"]["serviceId"]
            except Exception:
                continue

            if event_amount < min_amount:
                return {"valid": False, "error": f"Paid {event_amount} < required {min_amount}"}
            if event_service != service_id:
                return {"valid": False, "error": f"Service mismatch: {event_service} != {service_id}"}

            self._used_tx_hashes.add(tx_hash)
            return {
                "valid": True,
                "tx_hash": tx_hash,
                "amount": event_amount,
                "service_id": event_service,
                "session_id": decoded["args"]["sessionId"],
                "payer": decoded["args"]["payer"],
            }

        return {"valid": False, "error": "No ServicePaid event found in transaction"}
