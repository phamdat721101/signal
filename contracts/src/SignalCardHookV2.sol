// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseHook} from "./base/BaseHook.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "v4-core/src/types/BeforeSwapDelta.sol";
import {LPFeeLibrary} from "v4-core/src/libraries/LPFeeLibrary.sol";
import {SignalCardNFT} from "./SignalCardNFT.sol";

/// @title SignalCardHookV2 — full lifecycle: add LP, remove LP, swap fee, swap tracking
/// @notice Flags: BEFORE_ADD_LIQUIDITY | BEFORE_REMOVE_LIQUIDITY | BEFORE_SWAP | AFTER_SWAP
///         Address must have lower 14 bits = 0x0AC0.
contract SignalCardHookV2 is BaseHook {
    using PoolIdLibrary for PoolKey;

    SignalCardNFT public immutable NFT;
    mapping(PoolId => uint16) public lastCardRisk;
    mapping(PoolId => uint256) public swapCount;

    error CardAlreadyPlayed();
    error CardExpired();
    error NotCardOwner();
    error TickMismatch();

    constructor(IPoolManager pm, SignalCardNFT nft) BaseHook(pm) {
        NFT = nft;
    }

    function getHookPermissions() public pure override returns (Hooks.Permissions memory) {
        return Hooks.Permissions({
            beforeInitialize: false,
            afterInitialize: false,
            beforeAddLiquidity: true,
            afterAddLiquidity: false,
            beforeRemoveLiquidity: true,
            afterRemoveLiquidity: false,
            beforeSwap: true,
            afterSwap: true,
            beforeDonate: false,
            afterDonate: false,
            beforeSwapReturnDelta: false,
            afterSwapReturnDelta: false,
            afterAddLiquidityReturnDelta: false,
            afterRemoveLiquidityReturnDelta: false
        });
    }

    function _beforeAddLiquidity(
        address,
        PoolKey calldata key,
        IPoolManager.ModifyLiquidityParams calldata params,
        bytes calldata hookData
    ) internal override returns (bytes4) {
        uint256 cardId = abi.decode(hookData, (uint256));
        SignalCardNFT.CardData memory c = NFT.cardData(cardId);

        if (c.played) revert CardAlreadyPlayed();
        if (c.expiresAt <= block.timestamp) revert CardExpired();
        if (NFT.ownerOf(cardId) != tx.origin) revert NotCardOwner();
        if (params.tickLower != c.stopTickHint || params.tickUpper != c.targetTickHint)
            revert TickMismatch();

        NFT.markPlayed(cardId);
        lastCardRisk[key.toId()] = c.riskScore;

        return BaseHook.beforeAddLiquidity.selector;
    }

    function _beforeRemoveLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        bytes calldata hookData
    ) internal override returns (bytes4) {
        uint256 cardId = abi.decode(hookData, (uint256));
        if (NFT.ownerOf(cardId) != tx.origin) revert NotCardOwner();
        return BaseHook.beforeRemoveLiquidity.selector;
    }

    function _beforeSwap(
        address,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata,
        bytes calldata
    ) internal override returns (bytes4, BeforeSwapDelta, uint24) {
        uint16 risk = lastCardRisk[key.toId()];
        if (risk > 100) risk = 100;
        uint24 fee = uint24(30 + risk) * 100;
        return (
            BaseHook.beforeSwap.selector,
            BeforeSwapDeltaLibrary.ZERO_DELTA,
            fee | LPFeeLibrary.OVERRIDE_FEE_FLAG
        );
    }

    function _afterSwap(
        address,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata,
        BalanceDelta,
        bytes calldata
    ) internal override returns (bytes4, int128) {
        swapCount[key.toId()]++;
        return (BaseHook.afterSwap.selector, 0);
    }
}
