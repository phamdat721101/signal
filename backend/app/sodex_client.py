"""SoDex REST Client with EIP-712 typed signature auth."""
import json, logging, time
import httpx
from eth_account import Account
from web3 import Web3
from app.config import get_settings

logger = logging.getLogger(__name__)

SYMBOL_MAP = {
    "BTC": "vBTC_vUSDC", "ETH": "vETH_vUSDC", "INIT": "vINIT_vUSDC",
    "SOL": "vSOL_vUSDC", "AVAX": "vAVAX_vUSDC", "ATOM": "vATOM_vUSDC",
}


def map_symbol(symbol: str) -> str:
    sym = symbol.upper().replace("/USD", "").replace("/USDC", "")
    return SYMBOL_MAP.get(sym, f"v{sym}_vUSDC")


class SoDexClient:
    def __init__(self):
        s = get_settings()
        self._enabled = s.sodex_enabled
        self._key = s.sodex_private_key
        self._chain_id = s.sodex_chain_id
        self._max_usd = s.sodex_max_order_usd
        self._account_id = s.sodex_account_id
        is_mainnet = self._chain_id == 286623
        self._base = "https://mainnet-gw.sodex.dev/api/v1/spot" if is_mainnet else "https://testnet-gw.sodex.dev/api/v1/spot"
        self._acct = Account.from_key(self._key) if self._key else None

    def _domain(self):
        return {"name": "spot", "version": "1", "chainId": self._chain_id,
                "verifyingContract": "0x0000000000000000000000000000000000000000"}

    def _sign(self, payload: dict) -> tuple[str, int]:
        ordered = json.dumps(payload, separators=(",", ":"))
        payload_hash = Web3.keccak(text=ordered)
        nonce = int(time.time() * 1000)
        full_msg = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                                 {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
                "ExchangeAction": [{"name": "payloadHash", "type": "bytes32"}, {"name": "nonce", "type": "uint64"}],
            },
            "primaryType": "ExchangeAction",
            "domain": self._domain(),
            "message": {"payloadHash": payload_hash, "nonce": nonce},
        }
        signed = Account.sign_typed_data(self._key, full_msg=full_msg)
        return "0x01" + signed.signature.hex(), nonce

    def _auth_headers(self, payload: dict) -> dict:
        sig, nonce = self._sign(payload)
        return {"X-API-Key": self._acct.address, "X-API-Sign": sig, "X-API-Nonce": str(nonce)}

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        try:
            r = httpx.get(f"{self._base}{path}", params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"SoDex GET {path}: {e}")
            return None

    def _signed_request(self, method: str, path: str, payload: dict) -> dict | None:
        if not self._acct:
            logger.error("SoDex: no private key configured")
            return None
        headers = self._auth_headers(payload)
        try:
            r = httpx.request(method, f"{self._base}{path}", json=payload, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"SoDex {method} {path}: {e}")
            return None

    # --- Public ---
    def get_symbols(self): return self._get("/markets/symbols")
    def get_tickers(self): return self._get("/markets/tickers")
    def get_orderbook(self, symbol: str, limit: int = 20): return self._get(f"/markets/{symbol}/orderbook", {"limit": limit})
    def get_balances(self, address: str): return self._get(f"/accounts/{address}/balances")
    def get_open_orders(self, address: str): return self._get(f"/accounts/{address}/orders")
    def get_order_history(self, address: str): return self._get(f"/accounts/{address}/orders/history")

    # --- Signed ---
    def place_market_order(self, account_id: str, symbol_id: str, side: int, quantity: str, price: str | None = None) -> dict | None:
        order = {"clOrdID": f"sig_{int(time.time()*1000)}", "modifier": 0, "side": side,
                 "type": 2, "timeInForce": "IOC", "price": price or "0", "quantity": quantity,
                 "funds": "0", "stopPrice": "0", "stopType": 0, "triggerType": 0,
                 "reduceOnly": False, "positionSide": 0}
        payload = {"accountId": account_id, "symbolId": symbol_id, "orders": [order]}
        return self._signed_request("POST", "/trade/orders/batch", payload)

    def cancel_order(self, account_id: str, cl_ord_id: str) -> dict | None:
        payload = {"accountId": account_id, "clOrdIDs": [cl_ord_id]}
        return self._signed_request("DELETE", "/trade/orders/batch", payload)


_client: SoDexClient | None = None


def get_sodex_client() -> SoDexClient | None:
    global _client
    if not get_settings().sodex_enabled:
        return None
    if _client is None:
        _client = SoDexClient()
    return _client
