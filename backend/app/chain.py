import json
import logging
import threading
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
        self._tx_lock = threading.Lock()

    def _estimate_gas_with_floor(self, fn) -> int:
        """Estimate gas + 20% buffer, never below the network floor.

        Initia evm-1 quirk (per product_context.md): the estimator under-counts
        ~60k of Cosmos-layer fee accounting on CALL txs. The floor closes that gap.
        """
        settings = get_settings()
        try:
            estimated = fn.estimate_gas({"from": self.account.address})
            return max(settings.evm_min_gas_limit, int(estimated * 1.2))
        except Exception as e:
            logger.debug(f"gas estimate failed, using floor: {e}")
            return max(settings.evm_min_gas_limit, 500_000)

    def _send_tx(self, fn, _retry: int = 2):
        breaker = error_tracker.get_breaker("chain_tx", threshold=3, cooldown=300.0)
        if breaker.is_open:
            logger.warning("Chain TX circuit open — skipping")
            return None
        settings = get_settings()
        with self._tx_lock:
            try:
                # Always re-fetch the live pending nonce. The deployer key is shared
                # across api / agent_api / scheduler / operator CLI, so any in-memory
                # cache drifts (Cosmos error: "account sequence mismatch, expected X,
                # got Y"). Cost: one RPC per tx — cheap vs the tx submission itself.
                self._nonce = self.w3.eth.get_transaction_count(
                    self.account.address, "pending"
                )
                tx = fn.build_transaction({
                    "from": self.account.address,
                    "nonce": self._nonce,
                    "gas": self._estimate_gas_with_floor(fn),
                    "gasPrice": settings.evm_gas_price_wei,
                })
                signed = self.account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                self._nonce += 1
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
                logger.info(f"TX {tx_hash.hex()} status={receipt['status']} gas={receipt.get('gasUsed', 0)}")
                breaker.record_success()
                return receipt
            except Exception as e:
                err_str = str(e).lower()
                # Nonce/sequence drift — covers both EVM-style ("nonce too low",
                # "already known") AND Cosmos-layer ("sequence mismatch",
                # "incorrect account sequence") forms. Same drift class either way.
                if _retry > 0 and (
                    "nonce" in err_str
                    or "already known" in err_str
                    or "sequence mismatch" in err_str
                    or "account sequence" in err_str
                ):
                    logger.warning(f"Nonce/sequence drift, retry: {e}")
                    return self._send_tx(fn, _retry=_retry - 1)
                # Replacement underpriced — same nonce already in mempool; retry
                # picks up next pending nonce on the next iteration.
                if _retry > 0 and "underpriced" in err_str:
                    logger.warning(f"Tx underpriced, retry: {e}")
                    return self._send_tx(fn, _retry=_retry - 1)
                breaker.record_failure()
                error_tracker.track("TX_SEND_FAILED", str(e))
                raise

    def create_signal(self, asset: str, is_bull: bool, confidence: int,
                      target_price: int, entry_price: int) -> tuple[int, str]:
        fn = self.contract.functions.createSignal(
            Web3.to_checksum_address(asset), is_bull, confidence, target_price, entry_price
        )
        receipt = self._send_tx(fn)
        if not receipt:
            return -1, ""
        logs = self.contract.events.SignalCreated().process_receipt(receipt)
        signal_id = logs[0]["args"]["id"] if logs else -1
        tx_hash = receipt["transactionHash"].hex()
        return signal_id, tx_hash

    def resolve_signal(self, signal_id: int, exit_price: int) -> str:
        fn = self.contract.functions.resolveSignal(signal_id, exit_price)
        receipt = self._send_tx(fn)
        if not receipt:
            return ""
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
        if not receipt:
            return -1, ""
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


    # ═══════════════════════════════════════════════════════════════════════
    # Initia-Native helpers (PRD-Initia-Native-Upgrade)
    # All write methods route through chain_ops.submit() for crash-safe
    # idempotency. Read methods are best-effort; callers handle empty values.
    # ═══════════════════════════════════════════════════════════════════════

    _ORACLE_ADAPTER_ABI = [
        {"type":"function","name":"commitEntryPriceProof","inputs":[{"name":"signalId","type":"uint256"},{"name":"pair","type":"string"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"commitExitPriceProof","inputs":[{"name":"signalId","type":"uint256"},{"name":"pair","type":"string"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"signalEntryPrice","inputs":[{"name":"","type":"uint256"}],"outputs":[{"name":"price","type":"uint256"},{"name":"timestamp","type":"uint256"},{"name":"height","type":"uint64"},{"name":"nonce","type":"uint64"},{"name":"decimal","type":"uint64"},{"name":"id","type":"uint64"}],"stateMutability":"view"},
        {"type":"function","name":"signalExitPrice","inputs":[{"name":"","type":"uint256"}],"outputs":[{"name":"price","type":"uint256"},{"name":"timestamp","type":"uint256"},{"name":"height","type":"uint64"},{"name":"nonce","type":"uint64"},{"name":"decimal","type":"uint64"},{"name":"id","type":"uint64"}],"stateMutability":"view"},
        {"type":"function","name":"getOracleHealth","inputs":[],"outputs":[{"name":"available","type":"bool"},{"name":"lastSuccessTs","type":"uint256"}],"stateMutability":"view"},
    ]

    _COSMOS_UTILS_ABI = [
        {"type":"function","name":"isAddressSanctioned","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"bool"}],"stateMutability":"view"},
        {"type":"function","name":"isModuleAddress","inputs":[{"name":"account","type":"address"}],"outputs":[{"name":"","type":"bool"}],"stateMutability":"view"},
    ]

    _COSMOS_DISPATCHER_ABI = [
        {"type":"function","name":"mintNFTToCosmosCollection","inputs":[{"name":"msgJson","type":"string"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"sendIBCTransfer","inputs":[{"name":"msgJson","type":"string"}],"outputs":[],"stateMutability":"nonpayable"},
    ]

    _VIP_SCORE_ABI = [
        {"type":"function","name":"scoreUser","inputs":[{"name":"user","type":"address"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"scoreBatch","inputs":[{"name":"users","type":"address[]"}],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"finalizeEpoch","inputs":[],"outputs":[],"stateMutability":"nonpayable"},
        {"type":"function","name":"scoreOf","inputs":[{"name":"","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
        {"type":"function","name":"currentEpoch","inputs":[],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
    ]

    def _helper_contract(self, address_attr: str, abi: list):
        """DRY helper for contract instantiation by Settings address attribute."""
        addr = getattr(get_settings(), address_attr, "") or ""
        if not addr:
            return None
        return self.w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)

    # ─── OracleAdapter (resolution-time ConnectOracle proofs) ──────────────

    def commit_entry_price_proof(self, signal_id: int, pair: str) -> str:
        from app import chain_ops
        oa = self._helper_contract("oracle_adapter_address", self._ORACLE_ADAPTER_ABI)
        if not oa:
            return ""
        fn = oa.functions.commitEntryPriceProof(signal_id, pair)
        return chain_ops.submit(
            "oracle_entry_price",
            {"signal_id": signal_id, "pair": pair},
            fn=lambda: self._send_tx(fn)["transactionHash"].hex(),
        )

    def commit_exit_price_proof(self, signal_id: int, pair: str) -> str:
        from app import chain_ops
        oa = self._helper_contract("oracle_adapter_address", self._ORACLE_ADAPTER_ABI)
        if not oa:
            return ""
        fn = oa.functions.commitExitPriceProof(signal_id, pair)
        return chain_ops.submit(
            "oracle_exit_price",
            {"signal_id": signal_id, "pair": pair},
            fn=lambda: self._send_tx(fn)["transactionHash"].hex(),
        )

    def get_oracle_entry_price(self, signal_id: int) -> dict:
        oa = self._helper_contract("oracle_adapter_address", self._ORACLE_ADAPTER_ABI)
        if not oa:
            return {}
        try:
            r = oa.functions.signalEntryPrice(signal_id).call()
            return {"price": str(r[0]), "timestamp": r[1], "height": r[2],
                    "nonce": r[3], "decimal": r[4], "id": r[5]}
        except Exception:
            return {}

    def get_oracle_health(self) -> dict:
        oa = self._helper_contract("oracle_adapter_address", self._ORACLE_ADAPTER_ABI)
        if not oa:
            return {"available": False, "last_success_ts": 0}
        try:
            available, ts = oa.functions.getOracleHealth().call()
            return {"available": bool(available), "last_success_ts": int(ts)}
        except Exception:
            return {"available": False, "last_success_ts": 0}

    # ─── CosmosUtils (sanctions check, address conversions) ────────────────

    def is_blocked_address(self, user: str) -> bool:
        cu = self._helper_contract("cosmos_utils_view_address", self._COSMOS_UTILS_ABI)
        if not cu:
            return False  # fail-open if helper not deployed
        try:
            return bool(cu.functions.isAddressSanctioned(Web3.to_checksum_address(user)).call())
        except Exception as e:
            logger.warning(f"is_blocked_address read failed: {e}")
            return False

    # ─── CosmosDispatcher (NFT mirror, IBC transfer) ───────────────────────

    def mint_nft_cosmos(self, recipient: str, tier: int) -> str:
        """Mirror an EVM tier mint to the Cosmos NFT module. Best-effort.

        EVM mint via ProofOfAlpha is authoritative; this mirror just makes the
        NFT show up in InterwovenKit / Initia explorer. chain_ops.submit ensures
        we never double-mirror.
        """
        from app import chain_ops
        cd = self._helper_contract("cosmos_dispatcher_address", self._COSMOS_DISPATCHER_ABI)
        if not cd:
            return ""
        # Backend constructs the JSON; on-chain we just dispatch it. Class id +
        # token id naming is a Signal convention — easy to grep + audit.
        msg_json = json.dumps({
            "@type": "/cosmos.nft.v1beta1.MsgSend",
            "class_id": "signal-proof-of-alpha",
            "id": f"tier-{tier}-{recipient.lower()}",
            "sender":   self.account.address,
            "receiver": recipient,
        }, separators=(",", ":"))
        fn = cd.functions.mintNFTToCosmosCollection(msg_json)
        return chain_ops.submit(
            "cosmos_nft_mirror",
            {"recipient": recipient.lower(), "tier": tier},
            fn=lambda: self._send_tx(fn)["transactionHash"].hex(),
        )

    # ─── VIPScoreAdapter ──────────────────────────────────────────────────

    def vip_score_user(self, user: str) -> str:
        from app import chain_ops
        vs = self._helper_contract("vip_score_adapter_address", self._VIP_SCORE_ABI)
        if not vs:
            return ""
        fn = vs.functions.scoreUser(Web3.to_checksum_address(user))
        return chain_ops.submit(
            "vip_score_user",
            {"user": user.lower()},
            fn=lambda: self._send_tx(fn)["transactionHash"].hex(),
        )

    def vip_score_batch(self, users: list[str]) -> str:
        from app import chain_ops
        vs = self._helper_contract("vip_score_adapter_address", self._VIP_SCORE_ABI)
        if not vs or not users:
            return ""
        addrs = [Web3.to_checksum_address(u) for u in users]
        fn = vs.functions.scoreBatch(addrs)
        # Idempotency key includes the epoch so repeated batches across epochs
        # don't dedup; within an epoch the same set of users is a no-op.
        epoch = self.vip_current_epoch()
        return chain_ops.submit(
            "vip_score_batch",
            {"epoch": epoch, "users": sorted(u.lower() for u in users)},
            fn=lambda: self._send_tx(fn)["transactionHash"].hex(),
        )

    def vip_finalize_epoch(self) -> str:
        from app import chain_ops
        vs = self._helper_contract("vip_score_adapter_address", self._VIP_SCORE_ABI)
        if not vs:
            return ""
        epoch = self.vip_current_epoch()
        fn = vs.functions.finalizeEpoch()
        return chain_ops.submit(
            "vip_finalize_epoch",
            {"epoch": epoch},   # one finalize per epoch — idempotent
            fn=lambda: self._send_tx(fn)["transactionHash"].hex(),
        )

    def vip_score_of(self, user: str) -> int:
        vs = self._helper_contract("vip_score_adapter_address", self._VIP_SCORE_ABI)
        if not vs:
            return 0
        try:
            return int(vs.functions.scoreOf(Web3.to_checksum_address(user)).call())
        except Exception:
            return 0

    def vip_current_epoch(self) -> int:
        vs = self._helper_contract("vip_score_adapter_address", self._VIP_SCORE_ABI)
        if not vs:
            return 0
        try:
            return int(vs.functions.currentEpoch().call())
        except Exception:
            return 0
