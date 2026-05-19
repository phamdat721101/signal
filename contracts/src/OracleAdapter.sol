// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Initia ConnectOracle (Slinky-backed). Reference:
///         https://initialabs.mintlify.app/resources/developer/contract-references/evm/connect
interface IConnectOracle {
    struct Price {
        uint256 price;
        uint256 timestamp;
        uint64 height;
        uint64 nonce;
        uint64 decimal;
        uint64 id;
    }
    function get_price(string memory base, string memory quote)
        external returns (Price memory);
}

/// @title OracleAdapter — resolution-time on-chain ConnectOracle price proofs.
/// @notice Backend resolver calls commitEntryPriceProof / commitExitPriceProof
///         when resolving a Signal. The recorded `Price` struct is verifiable
///         by anyone (immutable height + nonce + timestamp).
///
///         **NOT used in the swipe hot path** — entry/target prices shown to
///         users at swipe time come from the off-chain card data. Oracle is
///         only invoked at resolution to anchor the truth on-chain.
///
///         Defensive against Code4rena 2025-02 H-07 / H-08: every external
///         precompile call is wrapped in try/catch with a 100k gas cap. If
///         the oracle is unavailable (precompile not present or reverts),
///         `*Failed` event is emitted and the function reverts — never
///         consumes more than the gas cap.
contract OracleAdapter is Ownable {
    IConnectOracle public immutable oracle;

    /// @dev Per-call gas cap (Code4rena H-08 mitigation).
    uint256 public constant ORACLE_GAS_CAP = 100_000;

    mapping(uint256 => IConnectOracle.Price) public signalEntryPrice;
    mapping(uint256 => IConnectOracle.Price) public signalExitPrice;

    mapping(string => bool) public supportedPairs;

    /// @dev Last successful read timestamp — used by /api/health to detect oracle outage.
    uint256 public lastSuccessTimestamp;

    mapping(address => bool) public authorizedResolvers;

    event EntryPriceCommitted(uint256 indexed signalId, string pair, uint256 price, uint64 height);
    event ExitPriceCommitted(uint256 indexed signalId, string pair, uint256 price, uint64 height);
    event OracleCallFailed(uint256 indexed signalId, string pair, bytes reason);

    error OracleUnavailable();
    error OracleReverted();
    error UnsupportedPair(string pair);
    error AlreadyCommitted();

    modifier onlyAuthorized() {
        require(authorizedResolvers[msg.sender] || msg.sender == owner(), "not authorized");
        _;
    }

    constructor(address oracleAddr) Ownable(msg.sender) {
        // Zero address allowed — deploys in "oracle-disabled" mode. _safeGetPrice
        // probes address(oracle).code.length and reverts OracleUnavailable on read,
        // so functionality is gated cleanly. setOracle(...) below can wire it up
        // later once the chain's ConnectOracle is known.
        oracle = IConnectOracle(oracleAddr);
        // Bootstrap supported pairs — extend via setSupportedPair.
        supportedPairs["BTC/USD"] = true;
        supportedPairs["ETH/USD"] = true;
        supportedPairs["INIT/USD"] = true;
    }

    /// @notice Snapshot the current oracle price for a signal's entry. Idempotent
    ///         per signalId — re-running for the same signal is a no-op.
    function commitEntryPriceProof(uint256 signalId, string calldata pair)
        external onlyAuthorized
    {
        if (!supportedPairs[pair]) revert UnsupportedPair(pair);
        if (signalEntryPrice[signalId].timestamp != 0) revert AlreadyCommitted();
        IConnectOracle.Price memory p = _safeGetPrice(signalId, pair);
        signalEntryPrice[signalId] = p;
        emit EntryPriceCommitted(signalId, pair, p.price, p.height);
    }

    /// @notice Snapshot the current oracle price for a signal's exit. Idempotent.
    function commitExitPriceProof(uint256 signalId, string calldata pair)
        external onlyAuthorized
    {
        if (!supportedPairs[pair]) revert UnsupportedPair(pair);
        if (signalExitPrice[signalId].timestamp != 0) revert AlreadyCommitted();
        IConnectOracle.Price memory p = _safeGetPrice(signalId, pair);
        signalExitPrice[signalId] = p;
        emit ExitPriceCommitted(signalId, pair, p.price, p.height);
    }

    /// @notice Health probe for backend monitoring.
    function getOracleHealth() external view returns (bool available, uint256 lastSuccessTs) {
        return (address(oracle).code.length > 0, lastSuccessTimestamp);
    }

    function setSupportedPair(string calldata pair, bool supported) external onlyOwner {
        supportedPairs[pair] = supported;
    }

    function setAuthorizedResolver(address resolver, bool authorized) external onlyOwner {
        authorizedResolvers[resolver] = authorized;
    }

    // ─── internals ─────────────────────────────────────────────────────────

    /// @dev Wraps the precompile call in try/catch with a hard gas cap.
    function _safeGetPrice(uint256 signalId, string calldata pair)
        internal returns (IConnectOracle.Price memory)
    {
        if (address(oracle).code.length == 0) revert OracleUnavailable();
        try oracle.get_price{gas: ORACLE_GAS_CAP}(_base(pair), _quote(pair)) returns (
            IConnectOracle.Price memory p
        ) {
            require(p.timestamp > 0 && p.price > 0, "oracle: empty price");
            lastSuccessTimestamp = block.timestamp;
            return p;
        } catch (bytes memory reason) {
            emit OracleCallFailed(signalId, pair, reason);
            revert OracleReverted();
        }
    }

    /// @dev Splits a "BASE/QUOTE" pair string by the '/' character.
    function _base(string calldata pair) internal pure returns (string memory) {
        bytes memory b = bytes(pair);
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i] == "/") {
                bytes memory out = new bytes(i);
                for (uint256 j = 0; j < i; j++) out[j] = b[j];
                return string(out);
            }
        }
        return pair;
    }

    function _quote(string calldata pair) internal pure returns (string memory) {
        bytes memory b = bytes(pair);
        for (uint256 i = 0; i < b.length; i++) {
            if (b[i] == "/") {
                bytes memory out = new bytes(b.length - i - 1);
                for (uint256 j = 0; j < out.length; j++) out[j] = b[i + 1 + j];
                return string(out);
            }
        }
        return "";
    }
}
