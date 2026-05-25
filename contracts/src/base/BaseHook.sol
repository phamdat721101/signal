// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {BeforeSwapDelta} from "v4-core/src/types/BeforeSwapDelta.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";

/// @title BaseHook — minimal abstract base for Uniswap v4 hooks
/// @notice Subclasses override _beforeAddLiquidity, _beforeSwap, etc.
///         Public IHooks functions delegate to internal virtuals.
abstract contract BaseHook is IHooks {
    IPoolManager public immutable poolManager;

    constructor(IPoolManager _pm) { poolManager = _pm; }

    /// @dev Subclass must implement to declare which hooks are active.
    function getHookPermissions() public pure virtual returns (Hooks.Permissions memory);

    // ─── IHooks interface (delegate to internal virtuals) ─────────

    function beforeInitialize(address, PoolKey calldata, uint160) external virtual returns (bytes4) {
        return IHooks.beforeInitialize.selector;
    }
    function afterInitialize(address, PoolKey calldata, uint160, int24) external virtual returns (bytes4) {
        return IHooks.afterInitialize.selector;
    }
    function beforeAddLiquidity(
        address sender, PoolKey calldata key, IPoolManager.ModifyLiquidityParams calldata params, bytes calldata hookData
    ) external virtual returns (bytes4) {
        return _beforeAddLiquidity(sender, key, params, hookData);
    }
    function afterAddLiquidity(
        address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata, BalanceDelta, BalanceDelta, bytes calldata
    ) external virtual returns (bytes4, BalanceDelta) {
        return (IHooks.afterAddLiquidity.selector, BalanceDelta.wrap(0));
    }
    function beforeRemoveLiquidity(
        address sender, PoolKey calldata key, IPoolManager.ModifyLiquidityParams calldata params, bytes calldata hookData
    ) external virtual returns (bytes4) {
        return _beforeRemoveLiquidity(sender, key, params, hookData);
    }
    function afterRemoveLiquidity(
        address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata, BalanceDelta, BalanceDelta, bytes calldata
    ) external virtual returns (bytes4, BalanceDelta) {
        return (IHooks.afterRemoveLiquidity.selector, BalanceDelta.wrap(0));
    }
    function beforeSwap(
        address sender, PoolKey calldata key, IPoolManager.SwapParams calldata params, bytes calldata hookData
    ) external virtual returns (bytes4, BeforeSwapDelta, uint24) {
        return _beforeSwap(sender, key, params, hookData);
    }
    function afterSwap(
        address sender, PoolKey calldata key, IPoolManager.SwapParams calldata params, BalanceDelta delta, bytes calldata hookData
    ) external virtual returns (bytes4, int128) {
        return _afterSwap(sender, key, params, delta, hookData);
    }
    function beforeDonate(address, PoolKey calldata, uint256, uint256, bytes calldata) external virtual returns (bytes4) {
        return IHooks.beforeDonate.selector;
    }
    function afterDonate(address, PoolKey calldata, uint256, uint256, bytes calldata) external virtual returns (bytes4) {
        return IHooks.afterDonate.selector;
    }

    // ─── Internal virtuals for subclass override ──────────────────

    function _beforeAddLiquidity(address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata, bytes calldata)
        internal virtual returns (bytes4)
    {
        return IHooks.beforeAddLiquidity.selector;
    }

    function _beforeSwap(address, PoolKey calldata, IPoolManager.SwapParams calldata, bytes calldata)
        internal virtual returns (bytes4, BeforeSwapDelta, uint24)
    {
        return (IHooks.beforeSwap.selector, BeforeSwapDelta.wrap(0), 0);
    }

    function _beforeRemoveLiquidity(address, PoolKey calldata, IPoolManager.ModifyLiquidityParams calldata, bytes calldata)
        internal virtual returns (bytes4)
    {
        return IHooks.beforeRemoveLiquidity.selector;
    }

    function _afterSwap(address, PoolKey calldata, IPoolManager.SwapParams calldata, BalanceDelta, bytes calldata)
        internal virtual returns (bytes4, int128)
    {
        return (IHooks.afterSwap.selector, 0);
    }
}
