// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {BaseHook} from "./base/BaseHook.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "v4-core/src/types/BeforeSwapDelta.sol";
import {LPFeeLibrary} from "v4-core/src/libraries/LPFeeLibrary.sol";
import {SignalCardNFT} from "./SignalCardNFT.sol";

/// @title SignalCardHook — gates addLiquidity by card recipe + dynamic fee from risk
/// @notice CREATE2-mined to address with flags BEFORE_ADD_LIQUIDITY | BEFORE_SWAP (0x880).
///         beforeAddLiquidity: validates card ownership, expiry, tick match, marks played.
///         beforeSwap: returns dynamic fee = (30 + lastCardRisk) bps.
contract SignalCardHook is BaseHook {
    using PoolIdLibrary for PoolKey;

    SignalCardNFT public immutable NFT;
    mapping(PoolId => uint16) public lastCardRisk;

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
            beforeRemoveLiquidity: false,
            afterRemoveLiquidity: false,
            beforeSwap: true,
            afterSwap: false,
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

    function _beforeSwap(
        address,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata,
        bytes calldata
    ) internal override returns (bytes4, BeforeSwapDelta, uint24) {
        uint16 risk = lastCardRisk[key.toId()];
        if (risk > 100) risk = 100;
        uint24 fee = uint24(30 + risk) * 100; // bps × 100 for v4 encoding
        return (
            BaseHook.beforeSwap.selector,
            BeforeSwapDeltaLibrary.ZERO_DELTA,
            fee | LPFeeLibrary.OVERRIDE_FEE_FLAG
        );
    }
}
