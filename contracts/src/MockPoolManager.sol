// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {Currency} from "v4-core/src/types/Currency.sol";

/// @title MockPoolManager — minimal v4 PoolManager for X Layer testnet demo
/// @notice Implements only initialize() + modifyLiquidity() with hook dispatch.
///         NOT a real AMM — just enough to trigger hook callbacks for the hackathon.
contract MockPoolManager {
    using PoolIdLibrary for PoolKey;

    mapping(PoolId => uint160) public sqrtPriceX96;
    mapping(PoolId => bool) public initialized;

    event PoolInitialized(PoolId indexed id, uint160 sqrtPriceX96);
    event LiquidityAdded(PoolId indexed id, address sender, int24 tickLower, int24 tickUpper);

    function initialize(PoolKey calldata key, uint160 _sqrtPriceX96) external returns (int24) {
        PoolId id = key.toId();
        require(!initialized[id], "already initialized");
        // Validate hook address has correct flags
        // (simplified — just check hook is non-zero)
        require(address(key.hooks) != address(0), "hook required");
        initialized[id] = true;
        sqrtPriceX96[id] = _sqrtPriceX96;
        emit PoolInitialized(id, _sqrtPriceX96);
        return 0; // tick
    }

    /// @notice Simplified modifyLiquidity that just calls the hook's beforeAddLiquidity
    function addLiquidity(
        PoolKey calldata key,
        int24 tickLower,
        int24 tickUpper,
        int256 liquidityDelta,
        bytes calldata hookData
    ) external {
        PoolId id = key.toId();
        require(initialized[id], "pool not initialized");
        require(liquidityDelta > 0, "only add liquidity");

        // Call hook's beforeAddLiquidity
        IPoolManager.ModifyLiquidityParams memory params = IPoolManager.ModifyLiquidityParams({
            tickLower: tickLower,
            tickUpper: tickUpper,
            liquidityDelta: liquidityDelta,
            salt: bytes32(0)
        });

        // The hook validates the card recipe and marks it played
        IHooks(address(key.hooks)).beforeAddLiquidity(msg.sender, key, params, hookData);

        emit LiquidityAdded(id, msg.sender, tickLower, tickUpper);
    }
}
