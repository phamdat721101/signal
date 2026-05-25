// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IUnlockCallback} from "v4-core/src/interfaces/callback/IUnlockCallback.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {Currency, CurrencyLibrary} from "v4-core/src/types/Currency.sol";
import {LPFeeLibrary} from "v4-core/src/libraries/LPFeeLibrary.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {BalanceDelta, BalanceDeltaLibrary} from "v4-core/src/types/BalanceDelta.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SignalCardNFT} from "./SignalCardNFT.sol";

/// @title SignalCardRouterV2 — playCard (open LP) + closeCard (remove LP)
contract SignalCardRouterV2 is IUnlockCallback {
    using CurrencyLibrary for Currency;
    using BalanceDeltaLibrary for BalanceDelta;

    IPoolManager public immutable POOL_MANAGER;
    SignalCardNFT public immutable NFT;
    PoolKey public poolKey;

    event Summon(uint256 indexed cardId, address indexed player, int24 tickLower, int24 tickUpper, uint128 liquidity);
    event Close(uint256 indexed cardId, address indexed player, uint256 amount0, uint256 amount1);

    error NotOwner();
    error DeadlinePassed();
    error OnlyPoolManager();
    error AmountExceedsMax();
    error AmountBelowMin();

    struct CallbackData {
        uint256 cardId;
        int256 liquidityDelta; // positive = add, negative = remove
        uint256 amount0Limit;  // max for add, min for remove
        uint256 amount1Limit;
        address sender;
        int24 tickLower;
        int24 tickUpper;
    }

    constructor(IPoolManager _pm, SignalCardNFT _nft, Currency _c0, Currency _c1, int24 _tickSpacing, IHooks _hook) {
        POOL_MANAGER = _pm;
        NFT = _nft;
        poolKey = PoolKey({currency0: _c0, currency1: _c1, fee: LPFeeLibrary.DYNAMIC_FEE_FLAG, tickSpacing: _tickSpacing, hooks: _hook});
    }

    function playCard(uint256 cardId, uint128 liquidity, uint256 amount0Max, uint256 amount1Max, uint256 deadline) external {
        if (block.timestamp > deadline) revert DeadlinePassed();
        if (NFT.ownerOf(cardId) != msg.sender) revert NotOwner();
        SignalCardNFT.CardData memory c = NFT.cardData(cardId);

        address t0 = Currency.unwrap(poolKey.currency0);
        address t1 = Currency.unwrap(poolKey.currency1);
        if (amount0Max > 0) IERC20(t0).transferFrom(msg.sender, address(this), amount0Max);
        if (amount1Max > 0) IERC20(t1).transferFrom(msg.sender, address(this), amount1Max);

        POOL_MANAGER.unlock(abi.encode(CallbackData({
            cardId: cardId,
            liquidityDelta: int256(uint256(liquidity)),
            amount0Limit: amount0Max,
            amount1Limit: amount1Max,
            sender: msg.sender,
            tickLower: c.stopTickHint,
            tickUpper: c.targetTickHint
        })));

        _refund(t0, msg.sender);
        _refund(t1, msg.sender);
        emit Summon(cardId, msg.sender, c.stopTickHint, c.targetTickHint, liquidity);
    }

    function closeCard(uint256 cardId, uint128 liquidity, uint256 amount0Min, uint256 amount1Min, uint256 deadline) external {
        if (block.timestamp > deadline) revert DeadlinePassed();
        if (NFT.ownerOf(cardId) != msg.sender) revert NotOwner();
        SignalCardNFT.CardData memory c = NFT.cardData(cardId);

        POOL_MANAGER.unlock(abi.encode(CallbackData({
            cardId: cardId,
            liquidityDelta: -int256(uint256(liquidity)),
            amount0Limit: amount0Min,
            amount1Limit: amount1Min,
            sender: msg.sender,
            tickLower: c.stopTickHint,
            tickUpper: c.targetTickHint
        })));

        // Transfer received tokens to user
        address t0 = Currency.unwrap(poolKey.currency0);
        address t1 = Currency.unwrap(poolKey.currency1);
        uint256 bal0 = IERC20(t0).balanceOf(address(this));
        uint256 bal1 = IERC20(t1).balanceOf(address(this));
        if (bal0 > 0) IERC20(t0).transfer(msg.sender, bal0);
        if (bal1 > 0) IERC20(t1).transfer(msg.sender, bal1);
        emit Close(cardId, msg.sender, bal0, bal1);
    }

    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        if (msg.sender != address(POOL_MANAGER)) revert OnlyPoolManager();
        CallbackData memory cb = abi.decode(data, (CallbackData));

        IPoolManager.ModifyLiquidityParams memory params = IPoolManager.ModifyLiquidityParams({
            tickLower: cb.tickLower,
            tickUpper: cb.tickUpper,
            liquidityDelta: cb.liquidityDelta,
            salt: bytes32(0)
        });
        (BalanceDelta delta,) = POOL_MANAGER.modifyLiquidity(poolKey, params, abi.encode(cb.cardId));

        int128 d0 = delta.amount0();
        int128 d1 = delta.amount1();

        if (cb.liquidityDelta > 0) {
            // Add liquidity: settle what we owe
            if (d0 < 0) {
                uint256 owed = uint256(uint128(-d0));
                if (owed > cb.amount0Limit) revert AmountExceedsMax();
                POOL_MANAGER.sync(poolKey.currency0);
                IERC20(Currency.unwrap(poolKey.currency0)).transfer(address(POOL_MANAGER), owed);
                POOL_MANAGER.settle();
            }
            if (d1 < 0) {
                uint256 owed = uint256(uint128(-d1));
                if (owed > cb.amount1Limit) revert AmountExceedsMax();
                POOL_MANAGER.sync(poolKey.currency1);
                IERC20(Currency.unwrap(poolKey.currency1)).transfer(address(POOL_MANAGER), owed);
                POOL_MANAGER.settle();
            }
        } else {
            // Remove liquidity: take what pool owes us
            if (d0 > 0) {
                uint256 received = uint256(uint128(d0));
                if (received < cb.amount0Limit) revert AmountBelowMin();
                POOL_MANAGER.take(poolKey.currency0, address(this), received);
            }
            if (d1 > 0) {
                uint256 received = uint256(uint128(d1));
                if (received < cb.amount1Limit) revert AmountBelowMin();
                POOL_MANAGER.take(poolKey.currency1, address(this), received);
            }
        }
        return "";
    }

    function _refund(address token, address to) internal {
        uint256 bal = IERC20(token).balanceOf(address(this));
        if (bal > 0) IERC20(token).transfer(to, bal);
    }
}
