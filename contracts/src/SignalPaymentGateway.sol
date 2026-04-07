// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract SignalPaymentGateway is Ownable {
    struct AccessRecord {
        address agent;
        uint256 sessionId;
        uint256 voucherNonce;
        uint256 amountPaid;
        string serviceId;
        uint256 signalIdFrom;
        uint256 signalIdTo;
        uint256 timestamp;
    }

    struct ServiceTier {
        string serviceId;
        uint256 pricePerCall;
        uint256 pricePerSignal;
        bool active;
    }

    AccessRecord[] public accessRecords;
    mapping(string => ServiceTier) public serviceTiers;
    mapping(address => uint256) public agentAccessCount;

    event AccessGranted(address indexed agent, string serviceId, uint256 amountPaid, uint256 signalCount);

    constructor() Ownable(msg.sender) {
        serviceTiers["signal-basic"] = ServiceTier("signal-basic", 0.001 ether, 0, true);
        serviceTiers["signal-premium"] = ServiceTier("signal-premium", 0.01 ether, 0, true);
        serviceTiers["signal-single"] = ServiceTier("signal-single", 0, 0.002 ether, true);
    }

    function recordAccess(address agent, uint256 sessionId, uint256 voucherNonce, uint256 amountPaid, string calldata serviceId, uint256 signalIdFrom, uint256 signalIdTo) external onlyOwner {
        accessRecords.push(AccessRecord(agent, sessionId, voucherNonce, amountPaid, serviceId, signalIdFrom, signalIdTo, block.timestamp));
        agentAccessCount[agent]++;
        emit AccessGranted(agent, serviceId, amountPaid, signalIdTo - signalIdFrom + 1);
    }

    function getServicePrice(string calldata serviceId) external view returns (uint256, uint256) {
        ServiceTier storage t = serviceTiers[serviceId];
        return (t.pricePerCall, t.pricePerSignal);
    }

    function setServiceTier(string calldata serviceId, uint256 pricePerCall, uint256 pricePerSignal, bool active) external onlyOwner {
        serviceTiers[serviceId] = ServiceTier(serviceId, pricePerCall, pricePerSignal, active);
    }

    function getAccessRecordCount() external view returns (uint256) { return accessRecords.length; }
}
