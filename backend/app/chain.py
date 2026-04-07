import json
import logging
from pathlib import Path
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from app.config import get_settings
from app.error_tracker import error_tracker

logger = logging.getLogger(__name__)

ABI_PATH = Path(__file__).parent / "abi.json"


def _load_abi() -> list:
    with open(ABI_PATH) as f:
        return json.load(f)


class ChainClient:
    def __init__(self):
        settings = get_settings()
        self.w3 = Web3(Web3.HTTPProvider(settings.json_rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.account = self.w3.eth.account.from_key(settings.private_key)
        abi = _load_abi()
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.contract_address),
            abi=abi,
        )
        self._nonce = self.w3.eth.get_transaction_count(self.account.address)

    def _send_tx(self, fn, _retry: bool = True):
        try:
            tx = fn.build_transaction({
                "from": self.account.address,
                "nonce": self._nonce,
                "gas": 500_000,
                "gasPrice": 0,
            })
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            self._nonce += 1
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(f"TX {tx_hash.hex()} status={receipt['status']}")
            return receipt
        except Exception as e:
            err_str = str(e).lower()
            if _retry and ("nonce" in err_str or "already known" in err_str):
                logger.warning(f"Nonce error, resyncing: {e}")
                self._nonce = self.w3.eth.get_transaction_count(self.account.address)
                error_tracker.track("NONCE_RESYNC", f"Resynced nonce to {self._nonce}", {"error": str(e)})
                return self._send_tx(fn, _retry=False)
            error_tracker.track("TX_SEND_FAILED", str(e))
            raise

    def create_signal(self, asset: str, is_bull: bool, confidence: int,
                      target_price: int, entry_price: int) -> tuple[int, str]:
        fn = self.contract.functions.createSignal(
            Web3.to_checksum_address(asset), is_bull, confidence, target_price, entry_price
        )
        receipt = self._send_tx(fn)
        logs = self.contract.events.SignalCreated().process_receipt(receipt)
        signal_id = logs[0]["args"]["id"] if logs else -1
        tx_hash = receipt["transactionHash"].hex()
        return signal_id, tx_hash

    def resolve_signal(self, signal_id: int, exit_price: int) -> str:
        fn = self.contract.functions.resolveSignal(signal_id, exit_price)
        receipt = self._send_tx(fn)
        return receipt["transactionHash"].hex()

    def get_signal(self, signal_id: int) -> dict:
        raw = self.contract.functions.getSignal(signal_id).call()
        return self._parse_signal(signal_id, raw)

    def get_signal_count(self) -> int:
        return self.contract.functions.getSignalCount().call()

    def get_signals(self, offset: int = 0, limit: int = 100) -> list[dict]:
        raw_list = self.contract.functions.getSignals(offset, limit).call()
        return [self._parse_signal(offset + i, s) for i, s in enumerate(raw_list)]

    def get_user_signals(self, user: str) -> list[int]:
        return self.contract.functions.getUserSignals(
            Web3.to_checksum_address(user)
        ).call()

    @staticmethod
    def _parse_signal(idx: int, raw) -> dict:
        return {
            "id": idx,
            "asset": raw[0],
            "isBull": raw[1],
            "confidence": raw[2],
            "targetPrice": str(raw[3]),
            "entryPrice": str(raw[4]),
            "exitPrice": str(raw[5]),
            "timestamp": raw[6],
            "resolved": raw[7],
            "creator": raw[8],
        }
