"""Signal Agent Client — Reference SDK for AI agents"""
import base64
import json
import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


class SignalAgentClient:
    def __init__(self, backend_url: str, private_key: str, session_id: int):
        self.backend_url = backend_url.rstrip("/")
        self.account = Account.from_key(private_key)
        self.session_id = session_id
        self._nonce = 0
        self.http = httpx.Client(timeout=30)

    def _sign_voucher(self, amount_wei: int, service_id: str) -> str:
        nonce = self._nonce
        self._nonce += 1
        message_hash = Web3.solidity_keccak(
            ["uint256", "uint256", "uint256", "string"],
            [self.session_id, amount_wei, nonce, service_id]
        )
        signed = self.account.sign_message(encode_defunct(message_hash))
        voucher = {"sessionId": self.session_id, "amount": amount_wei, "nonce": nonce, "serviceId": service_id, "signature": signed.signature.hex()}
        return base64.b64encode(json.dumps(voucher).encode()).decode()

    def get_pricing(self) -> dict:
        return self.http.get(f"{self.backend_url}/api/payment/pricing").json()

    def get_premium_signals(self, offset: int = 0, limit: int = 100) -> dict:
        pricing = self.get_pricing()
        price_wei = int(pricing["pricing"]["signal-premium"]["price_wei"])
        resp = self.http.get(f"{self.backend_url}/api/signals/premium", params={"offset": offset, "limit": limit}, headers={"X-PAYMENT": self._sign_voucher(price_wei, "signal-premium")})
        if resp.status_code == 402:
            return {"error": "Payment required", "details": resp.json()}
        resp.raise_for_status()
        return resp.json()

    def get_single_signal(self, signal_id: int) -> dict:
        pricing = self.get_pricing()
        price_wei = int(pricing["pricing"]["signal-single"]["price_wei"])
        resp = self.http.get(f"{self.backend_url}/api/signals/single/{signal_id}", headers={"X-PAYMENT": self._sign_voucher(price_wei, "signal-single")})
        resp.raise_for_status()
        return resp.json()

    def get_session_info(self) -> dict:
        return self.http.get(f"{self.backend_url}/api/payment/session/{self.session_id}").json()

    def get_free_signals(self) -> dict:
        return self.http.get(f"{self.backend_url}/api/signals").json()
