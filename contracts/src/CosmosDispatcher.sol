// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "./CosmosUtils.sol";

/// @title CosmosDispatcher — owner-gated dispatcher for Cosmos-side messages.
/// @notice Single responsibility: dispatch JSON-encoded Cosmos SDK messages
///         (IBC transfer, NFT module mint, etc.) via the ICosmos precompile.
///
///         Authorized callers (RewardEngine, ProofOfAlpha integration, backend
///         resolver) submit pre-built JSON message strings; this contract
///         enforces auth + safety wrapping (try/catch + 200k gas cap) and
///         emits canonical events for the backend ibc_listener / monitoring.
///
///         Building Cosmos messages on-chain is gas-expensive — backend
///         constructs the JSON, this contract just signs/dispatches it.
contract CosmosDispatcher is Ownable, Pausable {
    /// @dev Higher gas cap for write-side execute_cosmos (Code4rena H-08).
    uint256 public constant DISPATCH_GAS_CAP = 200_000;

    mapping(address => bool) public authorizedCallers;

    event CosmosMessageDispatched(string indexed kind, string msgJson, address indexed caller);
    event CosmosDispatchFailed(string indexed kind, bytes reason);

    error CosmosUnavailable();
    error DispatchReverted();
    error NotAuthorized();

    modifier onlyAuthorized() {
        if (!authorizedCallers[msg.sender] && msg.sender != owner()) revert NotAuthorized();
        _;
    }

    constructor() Ownable(msg.sender) {}

    // ─── public dispatch surface ────────────────────────────────────────────

    /// @notice Mint an NFT in the Cosmos-side NFT module mirroring an EVM tier mint.
    /// @param  msgJson Pre-built /cosmos.nft.v1beta1.MsgSend (or MsgMint) JSON.
    function mintNFTToCosmosCollection(string calldata msgJson)
        external onlyAuthorized whenNotPaused
    {
        _dispatch("nft_mint", msgJson);
    }

    /// @notice Send an IBC fungible-token transfer.
    /// @param  msgJson Pre-built /ibc.applications.transfer.v1.MsgTransfer JSON.
    function sendIBCTransfer(string calldata msgJson)
        external onlyAuthorized whenNotPaused
    {
        _dispatch("ibc_transfer", msgJson);
    }

    /// @notice Generic escape hatch for any other whitelisted Cosmos message.
    /// @dev    Owner-only — keep `kind` short (used for logs + monitoring).
    function dispatchRaw(string calldata kind, string calldata msgJson)
        external onlyOwner whenNotPaused
    {
        _dispatch(kind, msgJson);
    }

    // ─── admin ──────────────────────────────────────────────────────────────

    function setAuthorizedCaller(address caller, bool authorized) external onlyOwner {
        authorizedCallers[caller] = authorized;
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }

    // ─── internals ──────────────────────────────────────────────────────────

    function _dispatch(string memory kind, string memory msgJson) internal {
        if (!CosmosUtils.isPrecompileAvailable()) revert CosmosUnavailable();
        try COSMOS.execute_cosmos{gas: DISPATCH_GAS_CAP}(msgJson) returns (bool) {
            emit CosmosMessageDispatched(kind, msgJson, msg.sender);
        } catch (bytes memory reason) {
            emit CosmosDispatchFailed(kind, reason);
            revert DispatchReverted();
        }
    }
}
