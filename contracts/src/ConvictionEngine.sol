// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

/// @title ConvictionEngine — On-chain reputation via conviction-weighted predictions
/// @notice Users commit conviction scores on cards; resolution computes reputation on-chain
contract ConvictionEngine is Ownable {
    struct Conviction {
        address user;
        bytes32 cardHash;
        uint8 score; // 1-100
        bool isBull;
        uint256 timestamp;
        bool resolved;
        bool wasCorrect;
    }

    struct Reputation {
        uint256 totalConvictions;
        uint256 correctCalls;
        int256 reputationScore; // can go negative
        uint256 currentStreak;
        uint256 bestStreak;
        uint256 totalConvictionPoints;
    }

    Conviction[] public convictions;
    mapping(address => Reputation) public reputations;
    mapping(bytes32 => uint256[]) public cardConvictions;
    mapping(address => uint256[]) public userConvictions;
    mapping(bytes32 => bool) public cardResolved;
    mapping(address => bool) public authorizedResolvers;

    address[] public topUsers;
    mapping(address => bool) public isTracked;

    event ConvictionCommitted(uint256 indexed id, address indexed user, bytes32 cardHash, uint8 score, bool isBull);
    event CardResolved(bytes32 indexed cardHash, bool outcomePositive, uint256 convictionCount);
    event ReputationUpdated(address indexed user, int256 newScore, uint256 streak);

    constructor() Ownable(msg.sender) {}

    function commitConviction(bytes32 cardHash, uint8 score, bool isBull) external returns (uint256) {
        require(score >= 1 && score <= 100, "Score 1-100");
        require(!cardResolved[cardHash], "Already resolved");

        uint256 id = convictions.length;
        convictions.push(Conviction(msg.sender, cardHash, score, isBull, block.timestamp, false, false));
        cardConvictions[cardHash].push(id);
        userConvictions[msg.sender].push(id);

        if (!isTracked[msg.sender]) {
            topUsers.push(msg.sender);
            isTracked[msg.sender] = true;
        }

        emit ConvictionCommitted(id, msg.sender, cardHash, score, isBull);
        return id;
    }

    function resolveCard(bytes32 cardHash, bool outcomePositive) external {
        require(authorizedResolvers[msg.sender] || msg.sender == owner(), "Not authorized");
        require(!cardResolved[cardHash], "Already resolved");
        cardResolved[cardHash] = true;

        uint256[] storage ids = cardConvictions[cardHash];
        for (uint256 i = 0; i < ids.length; i++) {
            Conviction storage c = convictions[ids[i]];
            c.resolved = true;
            bool correct = (c.isBull == outcomePositive);
            c.wasCorrect = correct;

            Reputation storage r = reputations[c.user];
            r.totalConvictions++;
            r.totalConvictionPoints += c.score;

            if (correct) {
                r.correctCalls++;
                r.currentStreak++;
                if (r.currentStreak > r.bestStreak) r.bestStreak = r.currentStreak;
                uint256 streakMul = r.currentStreak > 5 ? 3 : (r.currentStreak > 2 ? 2 : 1);
                r.reputationScore += int256(uint256(c.score) * 2 * streakMul);
            } else {
                r.currentStreak = 0;
                r.reputationScore -= int256(uint256(c.score));
            }

            emit ReputationUpdated(c.user, r.reputationScore, r.currentStreak);
        }

        emit CardResolved(cardHash, outcomePositive, ids.length);
    }

    function getReputation(address user) external view returns (Reputation memory) {
        return reputations[user];
    }

    function getConviction(uint256 id) external view returns (Conviction memory) {
        return convictions[id];
    }

    function getCardConvictionCount(bytes32 cardHash) external view returns (uint256) {
        return cardConvictions[cardHash].length;
    }

    function getConvictionCount() external view returns (uint256) {
        return convictions.length;
    }

    function getTopUsers(uint256 offset, uint256 limit) external view returns (address[] memory users, int256[] memory scores) {
        uint256 total = topUsers.length;
        if (offset >= total) return (new address[](0), new int256[](0));
        uint256 count = limit;
        if (offset + count > total) count = total - offset;
        users = new address[](count);
        scores = new int256[](count);
        for (uint256 i = 0; i < count; i++) {
            users[i] = topUsers[offset + i];
            scores[i] = reputations[topUsers[offset + i]].reputationScore;
        }
    }

    function setAuthorizedResolver(address resolver, bool authorized) external onlyOwner {
        authorizedResolvers[resolver] = authorized;
    }
}
