"""MPP/x402 Payment Middleware for FastAPI"""
import base64
import json
import logging
from typing import Optional

from eth_account.messages import encode_defunct
from web3 import Web3

logger = logging.getLogger(__name__)


SERVICE_PRICING = {
    "signal-basic": {"price_wei": int(0.001 * 1e18), "description": "Latest 10 signals"},
    "signal-premium": {"price_wei": int(0.01 * 1e18), "description": "All signals + analytics + leaderboard"},
    "signal-single": {"price_wei": int(0.002 * 1e18), "description": "Individual signal detail"},
}


class MPPPaymentVerifier:
    """Verifies MPP session vouchers against the on-chain SessionVault."""

    def __init__(self, chain_client, session_vault_address: str, session_vault_abi: list):
        self.chain = chain_client
        self.vault = chain_client.w3.eth.contract(
            address=Web3.to_checksum_address(session_vault_address),
            abi=session_vault_abi,
        )
        self._pending_redemptions: list = []

    def build_402_response(self, service_id: str, price_wei: int, token_address: str) -> dict:
        return {
            "x-payment-required": {
                "version": "mpp-session-v1",
                "price": str(price_wei),
                "token": token_address,
                "network": "initia",
                "chainId": self.chain.w3.eth.chain_id,
                "sessionVault": self.vault.address,
                "accepts": ["mpp-session-v1", "x402-v1"],
                "serviceId": service_id,
            }
        }

    def verify_voucher(self, voucher_b64: str) -> dict:
        try:
            voucher = json.loads(base64.b64decode(voucher_b64))
        except Exception as e:
            return {"valid": False, "error": f"Invalid encoding: {e}"}

        for field in ["sessionId", "amount", "nonce", "serviceId", "signature"]:
            if field not in voucher:
                return {"valid": False, "error": f"Missing: {field}"}

        session_id = int(voucher["sessionId"])
        amount = int(voucher["amount"])
        nonce = int(voucher["nonce"])
        service_id = voucher["serviceId"]

        message_hash = Web3.solidity_keccak(
            ["uint256", "uint256", "uint256", "string"],
            [session_id, amount, nonce, service_id]
        )
        try:
            msg = encode_defunct(message_hash)
            signer = Web3().eth.account.recover_message(msg, signature=voucher["signature"])
        except Exception as e:
            return {"valid": False, "error": f"Signature failed: {e}"}

        try:
            session = self.vault.functions.getSession(session_id).call()
            depositor, _, remaining, _, _, _, _, is_active = session[0], session[1], session[2], session[3], session[4], session[5], session[6], session[7]
        except Exception as e:
            return {"valid": False, "error": f"On-chain lookup failed: {e}"}

        if signer.lower() != depositor.lower():
            return {"valid": False, "error": "Signer != depositor"}
        if not is_active:
            return {"valid": False, "error": "Session not active"}
        if remaining < amount:
            return {"valid": False, "error": f"Insufficient: {remaining} < {amount}"}

        return {"valid": True, "session_id": session_id, "depositor": depositor, "amount": amount, "nonce": nonce, "service_id": service_id}

    def redeem_voucher_onchain(self, voucher_b64: str) -> Optional[str]:
        voucher = json.loads(base64.b64decode(voucher_b64))
        self._pending_redemptions.append(voucher)
        if len(self._pending_redemptions) >= 10:
            return self._flush_batch()
        return None

    def _flush_batch(self) -> Optional[str]:
        if not self._pending_redemptions:
            return None
        vouchers = self._pending_redemptions
        self._pending_redemptions = []
        try:
            tuples = [(int(v["sessionId"]), int(v["amount"]), int(v["nonce"]), v["serviceId"], bytes.fromhex(v["signature"].replace("0x", ""))) for v in vouchers]
            fn = self.vault.functions.redeemBatch(tuples)
            tx = fn.build_transaction({"from": self.chain.account.address, "nonce": self.chain.w3.eth.get_transaction_count(self.chain.account.address), "gas": 1_000_000, "gasPrice": 0})
            signed = self.chain.account.sign_transaction(tx)
            tx_hash = self.chain.w3.eth.send_raw_transaction(signed.raw_transaction)
            self.chain.w3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(f"Batch settled: {len(vouchers)} vouchers, tx={tx_hash.hex()}")
            return tx_hash.hex()
        except Exception as e:
            logger.error(f"Batch failed: {e}")
            self._pending_redemptions.extend(vouchers)
            return None
