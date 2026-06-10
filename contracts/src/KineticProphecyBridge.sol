// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title IConvictionEngine — minimal subset this bridge depends on.
interface IConvictionEngine {
    function resolveCard(bytes32 cardHash, bool outcomePositive) external;
}

/// @title KineticProphecyBridge — testnet 50312 settlement adapter for prophecy.social
///
/// Cross-chain split (mainnet 5031 read, testnet 50312 write):
///   Prophecy markets emit `MarketResolved` on Somnia mainnet. A backend
///   relay scans those logs and calls `triggerResolution` here. We then
///   propagate to `ConvictionEngine.resolveCard` on testnet.
///
/// SOLID:
///   - SRP: bind a Prophecy market id to a Kinetic card hash, then propagate
///     the YES/NO outcome ONCE. Nothing else.
///   - OCP: ACL is two simple sets (binders + relays). Adding a new caller
///     is a single tx, no contract change.
///   - DIP: depends only on the `IConvictionEngine.resolveCard` selector;
///     the engine implementation can evolve as long as the selector stays.
///
/// Idempotency:
///   - `bindMarketToCard` reverts on duplicate.
///   - `triggerResolution` short-circuits via `resolutionPropagated` so a
///     retried relay tick is a no-op.
///   - The downstream `resolveCard` runs in a try/catch; a single failing
///     card flips `resolutionPropagated` back to false to allow a retry,
///     while emitting `PropagationFailed` for off-chain observability.
contract KineticProphecyBridge is Ownable {
    IConvictionEngine public immutable CONVICTION;

    /// @notice prophecyMarketId → keccak256-derived Kinetic cardHash.
    /// @dev    cardHash = keccak256(abi.encode(uint256 cardId, uint256 marketId)).
    mapping(uint256 => bytes32) public prophecyToCardHash;
    /// @notice prophecyMarketId → settlement-once flag.
    mapping(uint256 => bool) public resolutionPropagated;

    /// @notice Backend hot wallets that bind cards at generation time.
    mapping(address => bool) public authorizedBinders;
    /// @notice Backend hot wallets that relay mainnet resolutions.
    mapping(address => bool) public authorizedRelays;

    event Bound(uint256 indexed prophecyMarketId, bytes32 cardHash, address indexed binder);
    event ResolutionPropagated(uint256 indexed prophecyMarketId, bool outcome, string receiptUri);
    event PropagationFailed(uint256 indexed prophecyMarketId, bytes reason);
    event BinderAuthorized(address indexed binder, bool authorized);
    event RelayAuthorized(address indexed relay, bool authorized);

    error ZeroAddress();
    error NotAuthorized();
    error AlreadyBound();
    error ZeroCardHash();
    error UnknownMarket();
    error AlreadyPropagated();

    constructor(address conviction, address owner_) Ownable(owner_) {
        if (conviction == address(0) || owner_ == address(0)) revert ZeroAddress();
        CONVICTION = IConvictionEngine(conviction);
        // Owner is implicitly trusted for bootstrap; explicit grants follow.
        authorizedBinders[owner_] = true;
        authorizedRelays[owner_] = true;
    }

    // ─── Owner setters ────────────────────────────────────────────

    function setBinder(address binder, bool authorized) external onlyOwner {
        if (binder == address(0)) revert ZeroAddress();
        authorizedBinders[binder] = authorized;
        emit BinderAuthorized(binder, authorized);
    }

    function setRelay(address relay, bool authorized) external onlyOwner {
        if (relay == address(0)) revert ZeroAddress();
        authorizedRelays[relay] = authorized;
        emit RelayAuthorized(relay, authorized);
    }

    // ─── Binding ──────────────────────────────────────────────────

    /// @notice Backend calls this after a Kinetic card row is inserted in
    ///         Postgres. The cardHash is the same value the swiper signs
    ///         in `ConvictionEngine.commitConviction`, so the resolution
    ///         path settles every swipe on this market in one shot.
    function bindMarketToCard(uint256 prophecyMarketId, bytes32 cardHash) external {
        if (!authorizedBinders[msg.sender]) revert NotAuthorized();
        if (cardHash == bytes32(0)) revert ZeroCardHash();
        if (prophecyToCardHash[prophecyMarketId] != bytes32(0)) revert AlreadyBound();
        prophecyToCardHash[prophecyMarketId] = cardHash;
        emit Bound(prophecyMarketId, cardHash, msg.sender);
    }

    // ─── Settlement ──────────────────────────────────────────────

    /// @notice Backend relay calls this for every mainnet `MarketResolved`
    ///         event. Idempotent on retry. A failing downstream call
    ///         re-opens the slot for the relay's next tick.
    function triggerResolution(
        uint256 prophecyMarketId,
        bool outcome,
        string calldata receiptUri
    ) external {
        if (!authorizedRelays[msg.sender]) revert NotAuthorized();
        if (resolutionPropagated[prophecyMarketId]) revert AlreadyPropagated();
        bytes32 cardHash = prophecyToCardHash[prophecyMarketId];
        if (cardHash == bytes32(0)) revert UnknownMarket();

        // Optimistic flip — prevents a re-entrancy from double-settling
        // even though `IConvictionEngine` is a known contract.
        resolutionPropagated[prophecyMarketId] = true;
        try CONVICTION.resolveCard(cardHash, outcome) {
            emit ResolutionPropagated(prophecyMarketId, outcome, receiptUri);
        } catch (bytes memory reason) {
            // Allow the relay to retry on next tick (e.g. transient error).
            resolutionPropagated[prophecyMarketId] = false;
            emit PropagationFailed(prophecyMarketId, reason);
        }
    }
}
