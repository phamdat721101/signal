// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title Somnia Agent platform interface (minimal — only what we call)
interface IAgentRequester {
    function createRequest(uint256 agentId, address callbackAddress, bytes4 callbackSelector, bytes calldata payload)
        external payable returns (uint256 requestId);
    function getRequestDeposit() external view returns (uint256);
}

/// @title JSON API Agent method selector
interface IJsonApiAgent {
    function fetchUint(string calldata url, string calldata selector, uint8 decimals) external returns (uint256);
}

enum ResponseStatus { None, Pending, Success, Failed, TimedOut }

struct Response {
    address validator;
    bytes result;
    ResponseStatus status;
    uint256 receipt;
    uint256 timestamp;
    uint256 executionCost;
}

struct Request {
    uint256 id;
    address requester;
    address callbackAddress;
    bytes4 callbackSelector;
    address[] subcommittee;
    Response[] responses;
    uint256 responseCount;
    uint256 failureCount;
    uint256 threshold;
    uint256 createdAt;
    uint256 deadline;
    ResponseStatus status;
    uint8 consensusType;
    uint256 remainingBudget;
    uint256 perAgentBudget;
}

/// @title SomniaOracleAdapter — consensus-validated price feeds via Somnia Agents
/// @notice Fetches prices from any JSON API, validated by Somnia validator subcommittee.
///         Single responsibility: request price → store price → expose via getPrice().
contract SomniaOracleAdapter is Ownable {
    IAgentRequester public immutable PLATFORM;
    uint256 public immutable AGENT_ID;

    mapping(string => uint256) public prices; // symbol → price (8 decimals)
    mapping(uint256 => string) internal _pending; // requestId → symbol

    event PriceRequested(string symbol, uint256 requestId);
    event PriceUpdated(string symbol, uint256 price);

    constructor(address platform, uint256 agentId, address owner_) Ownable(owner_) {
        PLATFORM = IAgentRequester(platform);
        AGENT_ID = agentId;
    }

    function requestPrice(string calldata symbol, string calldata apiUrl, string calldata jsonPath)
        external payable returns (uint256 requestId)
    {
        bytes memory payload = abi.encodeWithSelector(IJsonApiAgent.fetchUint.selector, apiUrl, jsonPath, uint8(8));
        uint256 deposit = PLATFORM.getRequestDeposit();
        require(msg.value >= deposit, "insufficient deposit");
        requestId = PLATFORM.createRequest{value: deposit}(AGENT_ID, address(this), this.onPriceResponse.selector, payload);
        _pending[requestId] = symbol;
        emit PriceRequested(symbol, requestId);
    }

    function onPriceResponse(uint256 requestId, Response[] memory responses, ResponseStatus status, Request memory)
        external
    {
        require(msg.sender == address(PLATFORM), "only platform");
        string memory symbol = _pending[requestId];
        delete _pending[requestId];
        if (status == ResponseStatus.Success && responses.length > 0) {
            prices[symbol] = abi.decode(responses[0].result, (uint256));
            emit PriceUpdated(symbol, prices[symbol]);
        }
    }

    function getPrice(string calldata symbol) external view returns (uint256) { return prices[symbol]; }

    receive() external payable {}
}
