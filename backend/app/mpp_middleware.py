"""MPP Payment Middleware — tx receipt verification for FastAPI"""
import json
import logging
from pathlib import Path

import httpx
from web3 import Web3
from eth_abi import decode

from app.config import get_settings

logger = logging.getLogger(__name__)

SERVICE_PRICING = {
    "signal-basic": {"price_wei": int(0.001 * 1e18), "description": "Latest 10 signals"},
    "signal-premium": {"price_wei": int(0.01 * 1e18), "description": "All signals + analytics + reports"},
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
        """Verify payment via EVM receipt, falling back to Cosmos LCD for MsgCall txs."""
        tx_hash = tx_hash.strip()
        if tx_hash in self._used_tx_hashes:
            return {"valid": False, "error": "Transaction already used"}

        # Try EVM receipt first, then Cosmos LCD (InterwovenKit sends Cosmos tx hashes)
        logs = self._get_evm_logs(tx_hash)
        if logs is None:
            logs = self._get_cosmos_evm_logs(tx_hash)
        if logs is None:
            return {"valid": False, "error": f"Transaction {tx_hash[:16]}... not found on EVM or Cosmos"}

        return self._verify_logs(tx_hash, logs, service_id, min_amount)

    def _get_evm_logs(self, tx_hash: str) -> list | None:
        try:
            receipt = self.chain.w3.eth.get_transaction_receipt(tx_hash)
            if receipt["status"] != 1:
                return None
            return receipt["logs"]
        except Exception:
            return None

    def _get_cosmos_evm_logs(self, tx_hash: str) -> list | None:
        """Fetch tx from Cosmos LCD and extract EVM logs from events."""
        settings = get_settings()
        bare_hash = tx_hash.replace("0x", "").upper()
        try:
            resp = httpx.get(f"{settings.lcd_url}/cosmos/tx/v1beta1/txs/{bare_hash}", timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            tx_resp = data.get("tx_response", {})
            if tx_resp.get("code", -1) != 0:
                return None
            # Extract EVM logs from events
            logs = []
            for ev in tx_resp.get("events", []):
                if ev.get("type") != "evm":
                    continue
                for attr in ev.get("attributes", []):
                    if attr.get("key") != "log":
                        continue
                    raw = attr["value"]
                    parsed = json.loads(f"[{raw}]") if not raw.startswith("[") else json.loads(raw)
                    for log_entry in parsed:
                        logs.append(log_entry)
            return logs if logs else None
        except Exception as e:
            logger.warning(f"Cosmos LCD lookup failed: {e}")
            return None

    def _verify_logs(self, tx_hash: str, logs: list, service_id: str, min_amount: int) -> dict:
        """Check logs for a valid ServicePaid event."""
        topic_hex = SERVICE_PAID_TOPIC.hex()
        if not topic_hex.startswith("0x"):
            topic_hex = "0x" + topic_hex

        for log in logs:
            # Normalize: support both web3 Receipt logs and raw Cosmos JSON logs
            addr = log.get("address", "")
            if addr.lower() != self.vault_address.lower():
                continue
            topics = log.get("topics", [])
            if len(topics) < 3:
                continue
            t0 = topics[0] if isinstance(topics[0], str) else topics[0].hex()
            if not t0.startswith("0x"):
                t0 = "0x" + t0
            if t0.lower() != topic_hex.lower():
                continue

            try:
                # Try web3 process_log first (works for EVM receipts)
                decoded = self.vault.events.ServicePaid().process_log(log)
                amount = decoded["args"]["amount"]
                svc = decoded["args"]["serviceId"]
                session_id = decoded["args"]["sessionId"]
                payer = decoded["args"]["payer"]
            except Exception:
                # Manual decode for Cosmos LCD raw logs
                try:
                    data_hex = log.get("data", "0x")
                    if isinstance(data_hex, str):
                        data_bytes = bytes.fromhex(data_hex.replace("0x", ""))
                    else:
                        data_bytes = bytes(data_hex)
                    amount, svc = decode(["uint256", "string"], data_bytes)
                    t1 = topics[1] if isinstance(topics[1], str) else topics[1].hex()
                    t2 = topics[2] if isinstance(topics[2], str) else topics[2].hex()
                    session_id = int(t1, 16) if isinstance(t1, str) else int(t1.hex(), 16)
                    payer = Web3.to_checksum_address("0x" + t2[-40:] if isinstance(t2, str) else "0x" + t2.hex()[-40:])
                except Exception as e:
                    logger.warning(f"Failed to decode ServicePaid log: {e}")
                    continue

            if amount < min_amount:
                return {"valid": False, "error": f"Paid {amount} < required {min_amount}"}
            if svc != service_id:
                return {"valid": False, "error": f"Service mismatch: {svc} != {service_id}"}

            self._used_tx_hashes.add(tx_hash)
            return {
                "valid": True,
                "tx_hash": tx_hash,
                "amount": amount,
                "service_id": svc,
                "session_id": session_id,
                "payer": payer,
            }

        return {"valid": False, "error": "No ServicePaid event found in transaction"}
