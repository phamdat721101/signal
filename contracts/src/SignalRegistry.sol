// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract SignalRegistry is Ownable {
    struct Signal {
        address asset;
        bool isBull;
        uint8 confidence;
        uint256 targetPrice;
        uint256 entryPrice;
        uint256 exitPrice;
        uint256 timestamp;
        bool resolved;
        address creator;
        bytes32 dataHash;   // IPFS hash of AI card data
        bool wasCorrect;    // filled on resolution
    }

    Signal[] public signals;
    mapping(address => uint256[]) public userSignals;
    mapping(address => bool) public authorizedAgents;

    event SignalCreated(uint256 indexed id, address indexed creator, address asset, bool isBull, uint8 confidence);
    event SignalResolved(uint256 indexed id, uint256 exitPrice, bool profitable);

    constructor() Ownable(msg.sender) {}

    function createSignal(
        address asset, bool isBull, uint8 confidence,
        uint256 targetPrice, uint256 entryPrice
    ) external returns (uint256) {
        return _createSignal(asset, isBull, confidence, targetPrice, entryPrice, bytes32(0));
    }

    function publishSignal(
        address asset, bool isBull, uint8 confidence,
        uint256 targetPrice, uint256 entryPrice, bytes32 dataHash
    ) external returns (uint256) {
        require(authorizedAgents[msg.sender] || msg.sender == owner(), "Not authorized agent");
        return _createSignal(asset, isBull, confidence, targetPrice, entryPrice, dataHash);
    }

    function _createSignal(
        address asset, bool isBull, uint8 confidence,
        uint256 targetPrice, uint256 entryPrice, bytes32 dataHash
    ) internal returns (uint256) {
        require(confidence <= 100, "Invalid confidence");
        uint256 id = signals.length;
        signals.push(Signal({
            asset: asset, isBull: isBull, confidence: confidence,
            targetPrice: targetPrice, entryPrice: entryPrice, exitPrice: 0,
            timestamp: block.timestamp, resolved: false, creator: msg.sender,
            dataHash: dataHash, wasCorrect: false
        }));
        userSignals[msg.sender].push(id);
        emit SignalCreated(id, msg.sender, asset, isBull, confidence);
        return id;
    }

    function resolveSignal(uint256 id, uint256 exitPrice) external onlyOwner {
        require(id < signals.length, "Invalid id");
        Signal storage s = signals[id];
        require(!s.resolved, "Already resolved");
        s.exitPrice = exitPrice;
        s.resolved = true;
        s.wasCorrect = s.isBull ? exitPrice > s.entryPrice : exitPrice < s.entryPrice;
        emit SignalResolved(id, exitPrice, s.wasCorrect);
    }

    function getSignal(uint256 id) external view returns (Signal memory) {
        require(id < signals.length, "Invalid id");
        return signals[id];
    }

    function getSignalCount() external view returns (uint256) { return signals.length; }

    function getUserSignals(address user) external view returns (uint256[] memory) { return userSignals[user]; }

    function getSignals(uint256 offset, uint256 limit) external view returns (Signal[] memory) {
        uint256 total = signals.length;
        if (offset >= total) return new Signal[](0);
        uint256 count = limit;
        if (offset + count > total) count = total - offset;
        Signal[] memory result = new Signal[](count);
        for (uint256 i = 0; i < count; i++) result[i] = signals[offset + i];
        return result;
    }

    function setAuthorizedAgent(address agent, bool authorized) external onlyOwner {
        authorizedAgents[agent] = authorized;
    }
}
