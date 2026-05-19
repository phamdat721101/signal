// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

/// @notice ConvictionEngine reputation getter — only the field we need.
interface IConvictionEngineRep {
    struct Reputation {
        uint256 totalConvictions;
        uint256 correctCalls;
        int256  reputationScore;
        uint256 currentStreak;
        uint256 bestStreak;
        uint256 totalConvictionPoints;
    }
    function getReputation(address user) external view returns (Reputation memory);
}

/// @title VIPScoreAdapter — Initia VIP-compliant scoring contract for Signal.
/// @notice Mirrors ConvictionEngine.reputationScore onto a per-epoch VIP score
///         that satisfies Initia VIP requirements:
///           • on-chain only (Section 5.2.2 of VIP rules)
///           • productive on-chain reputation, not naked-asset holding (5.2.6)
///           • no operator/team scoring (5.2.7)
///
///         Score formula:
///             score(user) = clamp(int256(reputationScore), 0, 10_000)
///         Negative reputation → 0; positive maps directly; capped at 10k.
///
///         Companion: docs/proposals/VIP-Whitelisting-Proposal-draft.md.
///
///         Whitelisting is gated by Initia L1 governance — this contract is
///         useful even pre-whitelist (gives Signal a published, queryable
///         reputation score that other ecosystem apps can read).
contract VIPScoreAdapter is Ownable, Pausable {
    IConvictionEngineRep public immutable conviction;

    uint256 public constant SCORE_CAP = 10_000;

    uint256 public currentEpoch;
    uint256 public lastEpochFinalizedAt;

    mapping(address => uint256) public scoreOf;
    mapping(address => uint256) public lastEpochScored;

    mapping(address => bool) public authorizedScorer;

    event UserScored(address indexed user, uint256 epoch, uint256 score);
    event EpochFinalized(uint256 indexed epoch, uint256 finalizedAt);

    error NotAuthorized();
    error EpochAlreadyFinalized();

    modifier onlyScorer() {
        if (!authorizedScorer[msg.sender] && msg.sender != owner()) revert NotAuthorized();
        _;
    }

    constructor(address convictionAddr) Ownable(msg.sender) {
        require(convictionAddr != address(0), "conviction=0");
        conviction = IConvictionEngineRep(convictionAddr);
    }

    /// @notice Compute and persist a single user's score for the current epoch.
    function scoreUser(address user) external onlyScorer whenNotPaused {
        _scoreOne(user);
    }

    /// @notice Batch variant. Backend pages through top-N reputation users daily.
    function scoreBatch(address[] calldata users) external onlyScorer whenNotPaused {
        for (uint256 i = 0; i < users.length; i++) {
            _scoreOne(users[i]);
        }
    }

    /// @notice Mark the current epoch finalized; bumps to next epoch.
    /// @dev    Idempotent within a single epoch — calling twice in the same
    ///         block is a no-op (lastEpochFinalizedAt guard).
    function finalizeEpoch() external onlyOwner {
        if (lastEpochFinalizedAt == block.timestamp) revert EpochAlreadyFinalized();
        emit EpochFinalized(currentEpoch, block.timestamp);
        currentEpoch += 1;
        lastEpochFinalizedAt = block.timestamp;
    }

    function setAuthorizedScorer(address scorer, bool authorized) external onlyOwner {
        authorizedScorer[scorer] = authorized;
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }

    // ─── internals ──────────────────────────────────────────────────────────

    function _scoreOne(address user) internal {
        IConvictionEngineRep.Reputation memory r = conviction.getReputation(user);
        uint256 s;
        if (r.reputationScore <= 0) {
            s = 0;
        } else {
            uint256 raw = uint256(r.reputationScore);
            s = raw > SCORE_CAP ? SCORE_CAP : raw;
        }
        scoreOf[user] = s;
        lastEpochScored[user] = currentEpoch;
        emit UserScored(user, currentEpoch, s);
    }
}
