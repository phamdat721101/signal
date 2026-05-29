// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {SomniaSignalAgent, ISomniaVerdictConsumer} from "./SomniaSignalAgent.sol";

/// @title Buyer callback shape — invoked when a paid verdict is delivered.
/// @notice Buyers implement this selector. Selector is provided at request time so
///         the buyer can route different verdict streams to different handlers.
interface IVerdictBuyer {
    function onKineticVerdict(
        uint256 buyerRequestId,
        string calldata verdictStr,
        address router,
        bytes calldata routerCalldata
    ) external;
}

/// @title SomniaAgentMarket — on-chain B2B verdict marketplace
/// @notice Other Somnia contracts pay STT to consume Kinetic verdicts directly on-chain.
///         Single responsibility: pricing + buyer dispatch. Verdict semantics live in
///         SomniaSignalAgent; execution policy lives in SomniaCardExecutor.
///         B2B-only — humans never interact with this contract.
contract SomniaAgentMarket is Ownable, ISomniaVerdictConsumer {
    SomniaSignalAgent public immutable SIGNAL_AGENT;

    /// @notice Margin charged on top of the platform deposit. Owner-tunable.
    uint256 public pricePerVerdict;
    /// @notice Where margin accrues. Owner-tunable.
    address public treasury;

    struct Buyer {
        address buyerAddr;
        bytes4  callbackSelector;
        uint256 paid;       // gross STT received
        bool    delivered;
    }

    /// @dev verdictId → buyer record (verdictId is allocated by SomniaSignalAgent).
    mapping(uint256 => Buyer) public buyers;
    uint256 public nextBuyerRequestId;

    event PricingUpdated(uint256 newPrice, address newTreasury);
    event VerdictPurchased(uint256 indexed verdictId, address indexed buyer, uint256 paid);
    event VerdictDelivered(
        uint256 indexed verdictId,
        address indexed buyer,
        string verdictStr,
        bytes32 dataHash
    );
    event BuyerCallbackFailed(uint256 indexed verdictId, address indexed buyer);

    error UnderPriced();
    error OnlyAgent();
    error InvalidCallback();

    constructor(address signalAgent, uint256 initialPrice, address treasury_, address owner_) Ownable(owner_) {
        SIGNAL_AGENT    = SomniaSignalAgent(payable(signalAgent));
        pricePerVerdict = initialPrice;
        treasury        = treasury_ == address(0) ? owner_ : treasury_;
    }

    // ─────────────────────────── Owner setters ────────────────────────────
    function setPricing(uint256 newPrice, address newTreasury) external onlyOwner {
        pricePerVerdict = newPrice;
        if (newTreasury != address(0)) treasury = newTreasury;
        emit PricingUpdated(newPrice, treasury);
    }

    // ─────────────────────────── Buyer-facing API ─────────────────────────
    /// @notice Pay STT to receive a Kinetic verdict via callback.
    /// @dev    msg.value must cover pricePerVerdict + the platform's per-call deposit floor
    ///         (read on-chain by the agent). Underfunded calls revert; overfunded refunds
    ///         flow through `receive()` rebates.
    function requestVerdict(string calldata symbol, string calldata context, bytes4 callbackSelector)
        external payable returns (uint256 buyerRequestId)
    {
        if (callbackSelector == bytes4(0)) revert InvalidCallback();
        if (msg.value < pricePerVerdict)   revert UnderPriced();

        // Margin to treasury, rest forwards to the platform via the agent.
        uint256 deposit = msg.value - pricePerVerdict;
        (bool sent, ) = treasury.call{value: pricePerVerdict}("");
        require(sent, "treasury push failed");

        // Single-element batch — the agent batch entry handles N internally.
        string[] memory symbols  = new string[](1);
        string[] memory contexts = new string[](1);
        symbols[0]  = symbol;
        contexts[0] = context;

        uint256[] memory verdictIds = SIGNAL_AGENT.requestVerdictAndExecuteBatch{value: deposit}(
            symbols, contexts, address(this), this.executeAgentResult.selector
        );

        buyerRequestId = nextBuyerRequestId++;
        buyers[verdictIds[0]] = Buyer({
            buyerAddr: msg.sender,
            callbackSelector: callbackSelector,
            paid: msg.value,
            delivered: false
        });
        emit VerdictPurchased(verdictIds[0], msg.sender, msg.value);
    }

    // ─────────────────── Callback from SomniaSignalAgent ──────────────────
    function executeAgentResult(uint256 verdictId, address router, bytes calldata data) external override {
        if (msg.sender != address(SIGNAL_AGENT)) revert OnlyAgent();

        Buyer storage b = buyers[verdictId];
        if (b.buyerAddr == address(0) || b.delivered) return; // unknown / already delivered

        SomniaSignalAgent.Verdict memory v = SIGNAL_AGENT.getVerdict(verdictId);
        b.delivered = true;

        // Forward to buyer's callback. Use call (not delegatecall) so failures don't take us down.
        (bool ok, ) = b.buyerAddr.call(
            abi.encodeWithSelector(b.callbackSelector, verdictId, v.verdictStr, router, data)
        );
        if (ok) {
            emit VerdictDelivered(verdictId, b.buyerAddr, v.verdictStr, keccak256(data));
        } else {
            emit BuyerCallbackFailed(verdictId, b.buyerAddr);
        }
    }

    // ─────────────────────────── Views ────────────────────────────────────
    function getBuyer(uint256 verdictId) external view returns (Buyer memory) { return buyers[verdictId]; }

    receive() external payable {}
}
