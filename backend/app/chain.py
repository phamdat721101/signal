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

    def publish_signal(self, asset: str, is_bull: bool, confidence: int,
                       target_price: int, entry_price: int, data_hash: bytes) -> tuple[int, str]:
        fn = self.contract.functions.publishSignal(
            Web3.to_checksum_address(asset), is_bull, confidence, target_price, entry_price, data_hash
        )
        receipt = self._send_tx(fn)
        logs = self.contract.events.SignalCreated().process_receipt(receipt)
        signal_id = logs[0]["args"]["id"] if logs else -1
        return signal_id, receipt["transactionHash"].hex()

    # ─── RewardEngine ────────────────────────────────────
    _REWARD_ABI = [
        {"type":"function","name":"onTradeResolved","inputs":[{"name":"user","type":"address"},{"name":"wasProfit","type":"bool"},{"name":"tradeAmount","type":"uint256"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"getStats","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"tuple","components":[{"name":"totalTrades","type":"uint256"},{"name":"wins","type":"uint256"},{"name":"currentStreak","type":"uint256"},{"name":"bestStreak","type":"uint256"},{"name":"totalRewards","type":"uint256"}]}],"stateMutability":"view"},
    ]

    def _reward_contract(self):
        settings = get_settings()
        if not settings.reward_engine_address:
            return None
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.reward_engine_address),
            abi=self._REWARD_ABI,
        )

    def on_trade_resolved(self, user: str, was_profit: bool, trade_amount_wei: int) -> str:
        rc = self._reward_contract()
        if not rc:
            return ""
        fn = rc.functions.onTradeResolved(Web3.to_checksum_address(user), was_profit, trade_amount_wei)
        receipt = self._send_tx(fn)
        return receipt["transactionHash"].hex()

    def get_user_stats(self, user: str) -> dict:
        rc = self._reward_contract()
        if not rc:
            return {"totalTrades": 0, "wins": 0, "currentStreak": 0, "bestStreak": 0, "totalRewards": 0}
        raw = rc.functions.getStats(Web3.to_checksum_address(user)).call()
        return {"totalTrades": raw[0], "wins": raw[1], "currentStreak": raw[2], "bestStreak": raw[3], "totalRewards": raw[4]}

    # ─── ProofOfAlpha ────────────────────────────────────
    _ALPHA_ABI = [
        {"type":"function","name":"mintAchievement","inputs":[{"name":"to","type":"address"},{"name":"tier","type":"uint8"},{"name":"wins","type":"uint256"},{"name":"winRate","type":"uint256"},{"name":"bestStreak","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable"},
        {"type":"function","name":"hasTier","inputs":[{"name":"","type":"address"},{"name":"","type":"uint8"}],"outputs":[{"name":"","type":"bool"}],"stateMutability":"view"},
    ]

    def _alpha_contract(self):
        settings = get_settings()
        if not settings.proof_of_alpha_address:
            return None
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.proof_of_alpha_address),
            abi=self._ALPHA_ABI,
        )

    def mint_achievement(self, to: str, tier: int, wins: int, win_rate: int, best_streak: int) -> str:
        ac = self._alpha_contract()
        if not ac:
            return ""
        fn = ac.functions.mintAchievement(Web3.to_checksum_address(to), tier, wins, win_rate, best_streak)
        receipt = self._send_tx(fn)
        return receipt["transactionHash"].hex()

    def has_tier(self, user: str, tier: int) -> bool:
        ac = self._alpha_contract()
        if not ac:
            return False
        return ac.functions.hasTier(Web3.to_checksum_address(user), tier).call()

    # ─── ConvictionEngine ─────────────────────────────
    _CONVICTION_ABI = [
        {"type":"function","name":"commitConviction","inputs":[{"name":"cardHash","type":"bytes32"},{"name":"score","type":"uint8"},{"name":"isBull","type":"bool"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"nonpayable"},
        {"type":"function","name":"resolveCard","inputs":[{"name":"cardHash","type":"bytes32"},{"name":"outcomePositive","type":"bool"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"getReputation","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"tuple","components":[{"name":"totalConvictions","type":"uint256"},{"name":"correctCalls","type":"uint256"},{"name":"reputationScore","type":"int256"},{"name":"currentStreak","type":"uint256"},{"name":"bestStreak","type":"uint256"},{"name":"totalConvictionPoints","type":"uint256"}]}],"stateMutability":"view"},
        {"type":"function","name":"getConvictionCount","inputs":[],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
        {"type":"function","name":"getTopUsers","inputs":[{"name":"offset","type":"uint256"},{"name":"limit","type":"uint256"}],"outputs":[{"name":"users","type":"address[]"},{"name":"scores","type":"int256[]"}],"stateMutability":"view"},
    ]

    def _conviction_contract(self):
        settings = get_settings()
        if not settings.conviction_engine_address:
            return None
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.conviction_engine_address),
            abi=self._CONVICTION_ABI,
        )

    def commit_conviction(self, card_hash: bytes, score: int, is_bull: bool) -> tuple[int, str]:
        cc = self._conviction_contract()
        if not cc:
            return -1, ""
        fn = cc.functions.commitConviction(card_hash, score, is_bull)
        receipt = self._send_tx(fn)
        logs = cc.events.ConvictionCommitted().process_receipt(receipt)
        cid = logs[0]["args"]["id"] if logs else -1
        return cid, receipt["transactionHash"].hex()

    def resolve_card_conviction(self, card_hash: bytes, outcome_positive: bool) -> str:
        cc = self._conviction_contract()
        if not cc:
            return ""
        fn = cc.functions.resolveCard(card_hash, outcome_positive)
        receipt = self._send_tx(fn)
        return receipt["transactionHash"].hex()

    def get_reputation(self, user: str) -> dict:
        cc = self._conviction_contract()
        if not cc:
            return {"totalConvictions": 0, "correctCalls": 0, "reputationScore": 0,
                    "currentStreak": 0, "bestStreak": 0, "totalConvictionPoints": 0}
        raw = cc.functions.getReputation(Web3.to_checksum_address(user)).call()
        return {"totalConvictions": raw[0], "correctCalls": raw[1], "reputationScore": raw[2],
                "currentStreak": raw[3], "bestStreak": raw[4], "totalConvictionPoints": raw[5]}

    def get_conviction_leaderboard(self, offset: int = 0, limit: int = 50) -> list[dict]:
        cc = self._conviction_contract()
        if not cc:
            return []
        users, scores = cc.functions.getTopUsers(offset, limit).call()
        return [{"address": u, "reputationScore": s} for u, s in zip(users, scores)]

    def get_conviction_count(self) -> int:
        cc = self._conviction_contract()
        return cc.functions.getConvictionCount().call() if cc else 0

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

    # ─── Tucana DEX ──────────────────────────────────────
    _TUCANA_ABI = [
        {"type":"function","name":"swapExactTokensForTokens","inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"outputs":[{"name":"","type":"uint256[]"}],"stateMutability":"nonpayable"},
    ]

    def swap_via_tucana(self, token_in: str, token_out: str, amount_in: int, min_amount_out: int) -> str:
        settings = get_settings()
        if not settings.tucana_router_address:
            return ""
        router = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.tucana_router_address),
            abi=self._TUCANA_ABI,
        )
        import time as _time
        deadline = int(_time.time()) + 300
        fn = router.functions.swapExactTokensForTokens(
            amount_in, min_amount_out,
            [Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out)],
            self.account.address, deadline,
        )
        receipt = self._send_tx(fn)
        return receipt["transactionHash"].hex()
