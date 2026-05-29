// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {SomniaOracleAdapter, IAgentRequester, Response, ResponseStatus, Request} from "./SomniaOracleAdapter.sol";

/// @title LLM Agent — string inference selector (legacy path)
interface ILlmAgent {
    function infer(string calldata prompt) external returns (string memory);
}

/// @title LLM Agent — inferToolsChat selector (Agentathon path)
/// @notice Subcommittee runs Qwen3-30B with fixed seed; consensus on tool-call output.
interface ILlmToolsAgent {
    function inferToolsChat(string calldata systemPrompt, string calldata userPrompt, string calldata toolSchema)
        external returns (bytes memory);
}

/// @title Consumer interface that the Agentathon batch path forwards results to
/// @notice Implemented by SomniaCardExecutor + SomniaAgentMarket. SRP: this contract
///         emits + decodes; it does NOT decide whether the router is allowed.
interface ISomniaVerdictConsumer {
    function executeAgentResult(uint256 verdictId, address target, bytes calldata data) external;
}

/// @title SomniaSignalAgent — on-chain AI signal generation via Somnia LLM Agent
/// @notice Two paths, single contract:
///         1. Legacy `requestSignal(symbol, context)` returns a JSON string verdict (unchanged).
///         2. Batch `requestVerdictAndExecuteBatch` returns structured (verdict, router, calldata)
///            via `inferToolsChat` and forwards to a consumer for atomic execution.
///         SRP: this contract emits + decodes; it does NOT validate routers (consumer's job).
contract SomniaSignalAgent is Ownable {
    IAgentRequester public immutable PLATFORM;
    uint256 public immutable AGENT_ID;

    // ── Legacy path (preserved byte-identical) ────────────────────────────
    struct Signal {
        string symbol;
        string result; // JSON: {"verdict":"APE","reasoning":"..."}
        uint256 timestamp;
    }
    Signal[] public signals;
    mapping(uint256 => uint256) internal _pending; // requestId → signal index

    event SignalRequested(string symbol, uint256 requestId);
    event SignalGenerated(uint256 indexed index, string symbol);

    // ── Batch / inferToolsChat path (Agentathon) ──────────────────────────
    struct Verdict {
        address requester;       // who called requestVerdictAndExecuteBatch
        string symbol;
        string verdictStr;       // "APE" | "FADE"
        address router;          // tool-call target the LLM emitted
        bytes routerCalldata;    // calldata the LLM emitted
        ResponseStatus status;
        uint256 timestamp;
    }
    Verdict[] public verdicts;
    mapping(uint256 => uint256) internal _pendingVerdict; // requestId → verdict index
    mapping(uint256 => address) internal _verdictConsumer; // verdict index → consumer
    mapping(uint256 => bytes4)  internal _verdictSelector; // verdict index → consumer selector

    event VerdictRequested(uint256 indexed verdictId, string symbol, uint256 requestId);
    event VerdictReceived(uint256 indexed verdictId, string verdictStr, address router, bytes routerCalldata);
    event VerdictFailed(uint256 indexed verdictId, ResponseStatus status);

    // Tool-schema constant — single tool, one verdict-string, one router, one calldata blob.
    string internal constant TOOL_SCHEMA =
        '{"name":"executeOnRouter","verdict":["APE","FADE"],"args":["address router","bytes data"]}';

    constructor(address platform, uint256 agentId, address owner_) Ownable(owner_) {
        PLATFORM = IAgentRequester(platform);
        AGENT_ID = agentId;
    }

    // ─────────────────────────── Legacy: requestSignal ─────────────────────
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

    // ─────────────────────── Agentathon: batch verdicts ────────────────────
    /// @notice Request N verdicts in a single call. Each becomes one async LLM call.
    /// @dev Caller must overfund: msg.value ≥ N × (getRequestDeposit() + pricePerAgent × subcommitteeSize).
    ///      The deposit floor is read on-chain so this stays correct under Somnia pricing changes.
    /// @param symbols One token symbol per card (e.g. "BTC")
    /// @param contexts Free-form context strings, same length as `symbols`
    /// @param consumer Contract that implements ISomniaVerdictConsumer (e.g. SomniaCardExecutor)
    /// @param consumerSelector The selector to invoke on the consumer when the verdict lands
    function requestVerdictAndExecuteBatch(
        string[] calldata symbols,
        string[] calldata contexts,
        address consumer,
        bytes4 consumerSelector
    ) external payable returns (uint256[] memory verdictIds) {
        require(symbols.length == contexts.length, "length mismatch");
        require(symbols.length > 0, "empty batch");
        require(consumer != address(0), "no consumer");

        uint256 floor = PLATFORM.getRequestDeposit();
        uint256 perCall = msg.value / symbols.length;
        require(perCall >= floor, "insufficient per-call deposit");

        verdictIds = new uint256[](symbols.length);
        for (uint256 i = 0; i < symbols.length; ++i) {
            verdictIds[i] = _enqueueVerdict(symbols[i], contexts[i], consumer, consumerSelector, perCall);
        }
    }

    function _enqueueVerdict(
        string calldata symbol,
        string calldata context,
        address consumer,
        bytes4 consumerSelector,
        uint256 deposit
    ) internal returns (uint256 verdictId) {
        verdictId = verdicts.length;
        verdicts.push(Verdict({
            requester: msg.sender,
            symbol: symbol,
            verdictStr: "",
            router: address(0),
            routerCalldata: "",
            status: ResponseStatus.Pending,
            timestamp: block.timestamp
        }));
        _verdictConsumer[verdictId] = consumer;
        _verdictSelector[verdictId] = consumerSelector;

        string memory systemPrompt =
            "You are a crypto trading agent. Reply with one tool call: executeOnRouter(verdict, router, data). "
            "verdict is 'APE' or 'FADE'. router is the whitelisted DEX router address. "
            "data is ABI-encoded calldata against that router. No prose.";
        string memory userPrompt = string.concat("Symbol=", symbol, ". Context=", context);

        bytes memory payload = abi.encodeWithSelector(
            ILlmToolsAgent.inferToolsChat.selector, systemPrompt, userPrompt, TOOL_SCHEMA
        );

        uint256 requestId = PLATFORM.createRequest{value: deposit}(
            AGENT_ID, address(this), this.onVerdictResponse.selector, payload
        );
        _pendingVerdict[requestId] = verdictId;
        emit VerdictRequested(verdictId, symbol, requestId);
    }

    function onVerdictResponse(uint256 requestId, Response[] memory responses, ResponseStatus status, Request memory)
        external
    {
        require(msg.sender == address(PLATFORM), "only platform");
        uint256 verdictId = _pendingVerdict[requestId];
        delete _pendingVerdict[requestId];

        Verdict storage v = verdicts[verdictId];
        v.status = status;

        // Clean degrade on failure — never decode a non-Success response.
        if (status != ResponseStatus.Success || responses.length == 0) {
            emit VerdictFailed(verdictId, status);
            return;
        }

        // Tool-call shape: abi.encode(string verdictStr, address router, bytes data).
        // Subcommittee consensus guarantees byte-identical decode across validators.
        (string memory verdictStr, address router, bytes memory routerCalldata) =
            abi.decode(responses[0].result, (string, address, bytes));

        v.verdictStr = verdictStr;
        v.router = router;
        v.routerCalldata = routerCalldata;
        emit VerdictReceived(verdictId, verdictStr, router, routerCalldata);

        // Forward to consumer atomically inside the callback frame.
        // The consumer (executor / market) owns the router whitelist + execution policy.
        address consumer = _verdictConsumer[verdictId];
        bytes4 selector = _verdictSelector[verdictId];
        if (consumer != address(0)) {
            (bool ok, ) = consumer.call(abi.encodeWithSelector(selector, verdictId, router, routerCalldata));
            // Don't bubble — let consumer log its own failure. Verdict is still on-chain.
            ok;
        }
    }

    function getVerdict(uint256 verdictId) external view returns (Verdict memory) { return verdicts[verdictId]; }
    function verdictCount() external view returns (uint256) { return verdicts.length; }

    receive() external payable {}
}
