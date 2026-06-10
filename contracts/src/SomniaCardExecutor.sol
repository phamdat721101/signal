// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {SomniaSignalAgent, ISomniaVerdictConsumer} from "./SomniaSignalAgent.sol";
import {SomniaOracleAdapter} from "./SomniaOracleAdapter.sol";

/// @title ConvictionEngine read/write surface (subset we depend on)
interface IConvictionEngine {
    struct Reputation {
        uint256 totalConvictions;
        uint256 correctCalls;
        int256  reputationScore;
        uint256 currentStreak;
        uint256 bestStreak;
        uint256 totalConvictionPoints;
    }
    function commitConviction(bytes32 cardHash, uint8 score, bool isBull) external returns (uint256);
    function resolveCard(bytes32 cardHash, bool outcomePositive) external;
    function getReputation(address user) external view returns (Reputation memory);
}

/// @title ProofOfAlpha mint surface (subset we depend on)
interface IProofOfAlpha {
    enum Tier { BRONZE_APE, SILVER_APE, GOLD_APE, DIAMOND_HANDS, SIGNAL_SAGE }
    function hasTier(address user, Tier tier) external view returns (bool);
    function mintAchievement(address to, Tier tier, uint256 wins, uint256 winRate, uint256 bestStreak)
        external returns (uint256);
}

/// @title SomniaCardExecutor — safety wall between LLM-emitted calldata and DeFi routers
/// @notice Single responsibility: validate, dispatch, record. The LLM (via SomniaSignalAgent)
///         is the brain; this contract is the wall. Routers must be owner-whitelisted.
///         Lives on Somnia chain 50312. Other chains run their own SignalCardHook variants —
///         this contract is purely additive.
contract SomniaCardExecutor is Ownable, ISomniaVerdictConsumer {
    SomniaSignalAgent   public immutable SIGNAL_AGENT;
    SomniaOracleAdapter public immutable ORACLE;
    IConvictionEngine   public immutable CONVICTION;
    IProofOfAlpha       public immutable PROOF_OF_ALPHA;

    /// @notice Default conviction score recorded for a swipe APE (1-100 per ConvictionEngine).
    uint8 public constant DEFAULT_CONVICTION_SCORE = 75;
    /// @notice Default time after execute before `resolveExpired` is callable.
    uint256 public constant DEFAULT_EXPIRY_SECONDS = 24 hours;
    /// @notice Recipe bound — agent calldata can't exceed this (DoS antibody).
    uint256 public constant MAX_AGENT_CALLDATA = 4096;

    /// @notice Whitelisted DEX routers the LLM is allowed to emit calldata against.
    ///         OCP: adding a router = one tx; no contract change.
    mapping(address => bool) public allowedAgentTargets;

    /// @notice Cross-chain executors (e.g. PredictionCardLiFiExecutor) authorised to
    ///         attribute a swipe to an arbitrary `user` address rather than `msg.sender`.
    ///         SRP: keeps the LiFi-side contract decoupled from this contract's
    ///         storage layout — only the explicit hook below grants attribution.
    mapping(address => bool) public delegatedExecutors;

    struct Position {
        address user;          // who settled the swipe (filled in batchExecuteFromQueue)
        string  symbol;
        bytes32 cardHash;      // keccak256(verdictId, symbol, user) — ConvictionEngine key
        bool    isBull;        // true if verdict was APE
        uint256 entryPrice;    // captured at execute via oracle (8 decimals)
        uint256 expiresAt;
        bool    executed;      // routed call returned ok
        bool    resolved;
    }

    /// @dev verdictId → Position. Verdicts that fail mid-flight stay in `Pending` state.
    mapping(uint256 => Position) public positions;
    /// @dev verdictId → user (filled at batch time, before the verdict callback lands).
    mapping(uint256 => address) public userByVerdict;
    /// @dev verdictId → symbol (filled at batch time so we can derive cardHash without re-reading).
    mapping(uint256 => string)  internal _symbolByVerdict;
    /// @dev oracle requestId → verdictId (resolution path correlation).
    mapping(uint256 => uint256) internal _resolvingVerdict;

    event TargetWhitelisted(address indexed target, bool allowed);
    event DelegatedExecutorSet(address indexed executor, bool allowed);
    event CardExecuted(uint256 indexed verdictId, address indexed user, string symbol, address target, bool ok);
    event CardResolved(uint256 indexed verdictId, address indexed user, bool wasCorrect);
    event TierMinted(address indexed user, IProofOfAlpha.Tier tier);

    error TargetNotAllowed();
    error CalldataTooLarge();
    error OnlyAgent();
    error NotExpired();
    error AlreadyResolved();
    error EmptyBatch();
    error LengthMismatch();
    error NotDelegatedExecutor();
    error ZeroUser();

    constructor(
        address signalAgent,
        address oracle,
        address conviction,
        address proofOfAlpha,
        address owner_
    ) Ownable(owner_) {
        SIGNAL_AGENT   = SomniaSignalAgent(payable(signalAgent));
        ORACLE         = SomniaOracleAdapter(payable(oracle));
        CONVICTION     = IConvictionEngine(conviction);
        PROOF_OF_ALPHA = IProofOfAlpha(proofOfAlpha);
    }

    // ──────────────────────────── Owner setters ────────────────────────────
    function setAllowedTarget(address target, bool allowed) external onlyOwner {
        allowedAgentTargets[target] = allowed;
        emit TargetWhitelisted(target, allowed);
    }

    /// @notice Whitelist a cross-chain executor that may attribute swipes
    ///         to an arbitrary user (used by `PredictionCardLiFiExecutor`).
    function setDelegatedExecutor(address executor, bool allowed) external onlyOwner {
        delegatedExecutors[executor] = allowed;
        emit DelegatedExecutorSet(executor, allowed);
    }

    // ─────────────────────── Batch path (the swipe surface) ───────────────
    struct Swipe { string symbol; string context; }

    /// @notice Settle N swipes in one tx. Each becomes one async LLM call;
    ///         `executeAgentResult` lands per card via the agent's callback.
    /// @dev    msg.value must cover N × per-call platform deposit (read on-chain).
    function batchExecuteFromQueue(Swipe[] calldata queue) external payable returns (uint256[] memory verdictIds) {
        return _batchExecute(msg.sender, queue);
    }

    /// @notice Cross-chain entry point: attribute the swipe to `attributedUser`
    ///         instead of `msg.sender`. Only callable by a whitelisted delegated
    ///         executor (`setDelegatedExecutor`). The downstream LLM verdict
    ///         lands as if `attributedUser` had submitted directly.
    /// @dev    SRP: no router-policy change — only attribution differs.
    function batchExecuteFromQueueFor(address attributedUser, Swipe[] calldata queue)
        external
        payable
        returns (uint256[] memory verdictIds)
    {
        if (!delegatedExecutors[msg.sender]) revert NotDelegatedExecutor();
        if (attributedUser == address(0))    revert ZeroUser();
        return _batchExecute(attributedUser, queue);
    }

    function _batchExecute(address attributedUser, Swipe[] calldata queue)
        internal
        returns (uint256[] memory verdictIds)
    {
        if (queue.length == 0) revert EmptyBatch();

        // Split into parallel arrays for the agent ABI.
        string[] memory symbols  = new string[](queue.length);
        string[] memory contexts = new string[](queue.length);
        for (uint256 i; i < queue.length; ++i) {
            symbols[i]  = queue[i].symbol;
            contexts[i] = queue[i].context;
        }

        verdictIds = SIGNAL_AGENT.requestVerdictAndExecuteBatch{value: msg.value}(
            symbols, contexts, address(this), this.executeAgentResult.selector
        );

        for (uint256 i; i < verdictIds.length; ++i) {
            userByVerdict[verdictIds[i]]    = attributedUser;
            _symbolByVerdict[verdictIds[i]] = queue[i].symbol;
        }
    }

    // ─────────────────── Callback from SomniaSignalAgent ──────────────────
    /// @notice Validates the LLM-emitted target + calldata, executes the routed call,
    ///         records the position, commits conviction.
    /// @dev    msg.sender must be the SomniaSignalAgent (the only authorised caller).
    function executeAgentResult(uint256 verdictId, address target, bytes calldata data) external override {
        if (msg.sender != address(SIGNAL_AGENT)) revert OnlyAgent();
        if (!allowedAgentTargets[target])         revert TargetNotAllowed();
        if (data.length > MAX_AGENT_CALLDATA)     revert CalldataTooLarge();

        SomniaSignalAgent.Verdict memory v = SIGNAL_AGENT.getVerdict(verdictId);
        address user = userByVerdict[verdictId];
        if (user == address(0)) user = v.requester;

        // Verdict string came from the LLM under consensus — keccak compare with allowed values.
        bool isBull = (keccak256(bytes(v.verdictStr)) == keccak256(bytes("APE")));

        // The actual on-chain action — low-level call so we don't couple to a router ABI.
        // If the call fails, position is still recorded for accountability (executed=false).
        (bool ok, ) = target.call(data);

        bytes32 cardHash = keccak256(abi.encode(verdictId, v.symbol, user));
        positions[verdictId] = Position({
            user: user,
            symbol: v.symbol,
            cardHash: cardHash,
            isBull: isBull,
            entryPrice: ORACLE.getPrice(v.symbol),
            expiresAt: block.timestamp + DEFAULT_EXPIRY_SECONDS,
            executed: ok,
            resolved: false
        });

        // ConvictionEngine records msg.sender as the convicter (== this contract on-chain).
        // Per-user attribution lives in the off-chain `swipes` table keyed by `userByVerdict`.
        // Upgrading ConvictionEngine to `commitConvictionFor(user, ...)` is a future PR
        // (out of Agentathon scope to keep this purely additive).
        CONVICTION.commitConviction(cardHash, DEFAULT_CONVICTION_SCORE, isBull);

        emit CardExecuted(verdictId, user, v.symbol, target, ok);
    }

    // ───────────────────────── Resolution loop ────────────────────────────
    /// @notice Anyone can call after expiry. Triggers an oracle price request;
    ///         `onResolutionPrice` lands the result and updates state.
    /// @dev    msg.value must cover the oracle's platform deposit (0.12 STT typical).
    function resolveExpired(uint256 verdictId, string calldata apiUrl, string calldata jsonPath)
        external payable
    {
        Position storage p = positions[verdictId];
        if (block.timestamp < p.expiresAt) revert NotExpired();
        if (p.resolved)                    revert AlreadyResolved();

        uint256 oracleReqId = ORACLE.requestPrice{value: msg.value}(p.symbol, apiUrl, jsonPath);
        _resolvingVerdict[oracleReqId] = verdictId;
    }

    /// @notice Convenience: resolve using the most recent on-chain price already cached
    ///         in the oracle (no new agent request). Free, but requires a fresh `prices[symbol]`.
    function resolveExpiredFromCache(uint256 verdictId) external {
        Position storage p = positions[verdictId];
        if (block.timestamp < p.expiresAt) revert NotExpired();
        if (p.resolved)                    revert AlreadyResolved();

        uint256 exitPrice = ORACLE.getPrice(p.symbol);
        require(exitPrice > 0, "stale oracle");
        _finalize(verdictId, exitPrice);
    }

    function _finalize(uint256 verdictId, uint256 exitPrice) internal {
        Position storage p = positions[verdictId];
        p.resolved = true;

        bool wasCorrect = p.isBull ? (exitPrice >= p.entryPrice) : (exitPrice < p.entryPrice);
        CONVICTION.resolveCard(p.cardHash, p.isBull == wasCorrect);
        emit CardResolved(verdictId, p.user, wasCorrect);

        if (wasCorrect) _maybeMintTiers(p.user);
    }

    /// @notice Reads the user's reputation and mints any tier they qualify for and don't yet hold.
    ///         Idempotent: re-mints are blocked by ProofOfAlpha.hasTier.
    function _maybeMintTiers(address user) internal {
        IConvictionEngine.Reputation memory r = CONVICTION.getReputation(user);
        if (r.totalConvictions == 0) return;
        uint256 winRateBps = (r.correctCalls * 10_000) / r.totalConvictions;

        if (r.correctCalls >= 10 && !PROOF_OF_ALPHA.hasTier(user, IProofOfAlpha.Tier.BRONZE_APE)) {
            PROOF_OF_ALPHA.mintAchievement(user, IProofOfAlpha.Tier.BRONZE_APE, r.correctCalls, winRateBps, r.bestStreak);
            emit TierMinted(user, IProofOfAlpha.Tier.BRONZE_APE);
        }
        if (winRateBps >= 5_000 && r.totalConvictions >= 50
            && !PROOF_OF_ALPHA.hasTier(user, IProofOfAlpha.Tier.SILVER_APE)) {
            PROOF_OF_ALPHA.mintAchievement(user, IProofOfAlpha.Tier.SILVER_APE, r.correctCalls, winRateBps, r.bestStreak);
            emit TierMinted(user, IProofOfAlpha.Tier.SILVER_APE);
        }
        if (r.correctCalls >= 100 && !PROOF_OF_ALPHA.hasTier(user, IProofOfAlpha.Tier.GOLD_APE)) {
            PROOF_OF_ALPHA.mintAchievement(user, IProofOfAlpha.Tier.GOLD_APE, r.correctCalls, winRateBps, r.bestStreak);
            emit TierMinted(user, IProofOfAlpha.Tier.GOLD_APE);
        }
        if (r.bestStreak >= 10 && !PROOF_OF_ALPHA.hasTier(user, IProofOfAlpha.Tier.DIAMOND_HANDS)) {
            PROOF_OF_ALPHA.mintAchievement(user, IProofOfAlpha.Tier.DIAMOND_HANDS, r.correctCalls, winRateBps, r.bestStreak);
            emit TierMinted(user, IProofOfAlpha.Tier.DIAMOND_HANDS);
        }
        if (winRateBps >= 8_000 && !PROOF_OF_ALPHA.hasTier(user, IProofOfAlpha.Tier.SIGNAL_SAGE)) {
            PROOF_OF_ALPHA.mintAchievement(user, IProofOfAlpha.Tier.SIGNAL_SAGE, r.correctCalls, winRateBps, r.bestStreak);
            emit TierMinted(user, IProofOfAlpha.Tier.SIGNAL_SAGE);
        }
    }

    /// @notice Oracle callback. msg.sender check is delegated to the oracle's own gating.
    function onOracleResolution(uint256 oracleRequestId) external {
        require(msg.sender == address(ORACLE), "only oracle");
        uint256 verdictId = _resolvingVerdict[oracleRequestId];
        delete _resolvingVerdict[oracleRequestId];
        Position storage p = positions[verdictId];
        if (p.resolved) return;
        uint256 exitPrice = ORACLE.getPrice(p.symbol);
        if (exitPrice == 0) return;
        _finalize(verdictId, exitPrice);
    }

    receive() external payable {}
}
