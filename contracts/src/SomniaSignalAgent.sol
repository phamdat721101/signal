// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {SomniaOracleAdapter, IAgentRequester, Response, ResponseStatus, Request} from "./SomniaOracleAdapter.sol";

/// @title LLM Agent method selector
interface ILlmAgent {
    function infer(string calldata prompt) external returns (string memory);
}

/// @title SomniaSignalAgent — on-chain AI signal generation via Somnia LLM Agent
/// @notice Generates APE/FADE verdicts using deterministic on-chain LLM inference.
///         Single responsibility: request AI signal → store result → expose via getSignal().
contract SomniaSignalAgent is Ownable {
    IAgentRequester public immutable PLATFORM;
    uint256 public immutable AGENT_ID;

    struct Signal {
        string symbol;
        string result; // JSON: {"verdict":"APE","reasoning":"..."}
        uint256 timestamp;
    }

    Signal[] public signals;
    mapping(uint256 => uint256) internal _pending; // requestId → signal index

    event SignalRequested(string symbol, uint256 requestId);
    event SignalGenerated(uint256 indexed index, string symbol);

    constructor(address platform, uint256 agentId, address owner_) Ownable(owner_) {
        PLATFORM = IAgentRequester(platform);
        AGENT_ID = agentId;
    }

    function requestSignal(string calldata symbol, string calldata context) external payable returns (uint256) {
        string memory prompt = string.concat(
            "Crypto analyst. For ", symbol, " given: ", context,
            ". Reply JSON only: {\"verdict\":\"APE\" or \"FADE\",\"reasoning\":\"<1 sentence>\"}"
        );
        bytes memory payload = abi.encodeWithSelector(ILlmAgent.infer.selector, prompt);
        uint256 deposit = PLATFORM.getRequestDeposit();
        require(msg.value >= deposit, "insufficient deposit");
        uint256 requestId = PLATFORM.createRequest{value: deposit}(
            AGENT_ID, address(this), this.onSignalResponse.selector, payload
        );
        signals.push(Signal(symbol, "", block.timestamp));
        _pending[requestId] = signals.length - 1;
        emit SignalRequested(symbol, requestId);
        return requestId;
    }

    function onSignalResponse(uint256 requestId, Response[] memory responses, ResponseStatus status, Request memory)
        external
    {
        require(msg.sender == address(PLATFORM), "only platform");
        uint256 idx = _pending[requestId];
        delete _pending[requestId];
        if (status == ResponseStatus.Success && responses.length > 0) {
            signals[idx].result = abi.decode(responses[0].result, (string));
            emit SignalGenerated(idx, signals[idx].symbol);
        }
    }

    function getSignal(uint256 index) external view returns (Signal memory) { return signals[index]; }
    function signalCount() external view returns (uint256) { return signals.length; }

    receive() external payable {}
}
