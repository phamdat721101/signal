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

/// @title SignalCardRouter — converts cardId → v4 LP position via direct PoolManager.unlock
/// @notice No v4-periphery PositionManager dependency. Uses the canonical
///         v4 unlock-and-callback pattern: playCard → poolManager.unlock →
///         unlockCallback (this contract) → modifyLiquidity (hook fires) →
///         settle/take to close balances. Same hook recipe enforcement applies
///         because hookData = abi.encode(cardId).
///
/// SOLID single-responsibility: convert one cardId into one LP position.
/// All policy lives in the hook; this contract is plumbing.
contract SignalCardRouter is IUnlockCallback {
    using CurrencyLibrary for Currency;
    using BalanceDeltaLibrary for BalanceDelta;

    IPoolManager public immutable POOL_MANAGER;
    SignalCardNFT public immutable NFT;
    PoolKey public poolKey;

    event Summon(
        uint256 indexed cardId,
        address indexed player,
        int24 tickLower,
        int24 tickUpper,
        uint128 liquidity
    );

    error NotOwner();
    error AlreadyPlayed();
    error Expired();
    error DeadlinePassed();
    error OnlyPoolManager();
    error AmountExceedsMax();

    struct CallbackData {
        uint256 cardId;
        uint128 liquidity;
        uint256 amount0Max;
        uint256 amount1Max;
        address sender;
        int24 tickLower;
        int24 tickUpper;
    }

    constructor(
        IPoolManager _pm,
        SignalCardNFT _nft,
        Currency _currency0,
        Currency _currency1,
        int24 _tickSpacing,
        IHooks _hook
    ) {
        POOL_MANAGER = _pm;
        NFT = _nft;
        poolKey = PoolKey({
            currency0: _currency0,
            currency1: _currency1,
            fee: LPFeeLibrary.DYNAMIC_FEE_FLAG,
            tickSpacing: _tickSpacing,
            hooks: _hook
        });
    }

    /// @notice Summon a card → opens an LP at the card's pre-computed range.
    /// User must approve OKB and USDC to this contract (amount0Max + amount1Max).
    function playCard(
        uint256 cardId,
        uint128 liquidity,
        uint256 amount0Max,
        uint256 amount1Max,
        uint256 deadline
    ) external {
        if (block.timestamp > deadline) revert DeadlinePassed();
        if (NFT.ownerOf(cardId) != msg.sender) revert NotOwner();
        SignalCardNFT.CardData memory c = NFT.cardData(cardId);
        if (c.played) revert AlreadyPlayed();
        if (c.expiresAt <= block.timestamp) revert Expired();

        // Pull tokens up-front. Settled to PoolManager inside unlockCallback.
        address t0 = Currency.unwrap(poolKey.currency0);
        address t1 = Currency.unwrap(poolKey.currency1);
        if (amount0Max > 0) IERC20(t0).transferFrom(msg.sender, address(this), amount0Max);
        if (amount1Max > 0) IERC20(t1).transferFrom(msg.sender, address(this), amount1Max);

        POOL_MANAGER.unlock(abi.encode(CallbackData({
            cardId: cardId,
            liquidity: liquidity,
            amount0Max: amount0Max,
            amount1Max: amount1Max,
            sender: msg.sender,
            tickLower: c.stopTickHint,
            tickUpper: c.targetTickHint
        })));

        // Refund any leftover (router holds nothing between calls).
        _refund(t0, msg.sender);
        _refund(t1, msg.sender);

        emit Summon(cardId, msg.sender, c.stopTickHint, c.targetTickHint, liquidity);
    }

    /// @inheritdoc IUnlockCallback
    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        if (msg.sender != address(POOL_MANAGER)) revert OnlyPoolManager();
        CallbackData memory cb = abi.decode(data, (CallbackData));

        // Add liquidity. hookData=cardId so SignalCardHook.beforeAddLiquidity
        // can verify recipe + mark played + record lastCardRisk.
        IPoolManager.ModifyLiquidityParams memory params = IPoolManager.ModifyLiquidityParams({
            tickLower: cb.tickLower,
            tickUpper: cb.tickUpper,
            liquidityDelta: int256(uint256(cb.liquidity)),
            salt: bytes32(0)
        });
        (BalanceDelta delta, ) = POOL_MANAGER.modifyLiquidity(poolKey, params, abi.encode(cb.cardId));

        // Settle balances. Negative delta = router owes PoolManager (we sync+transfer+settle).
        // Positive delta = router takes tokens out for the user (rare for add-liquidity).
        int128 d0 = delta.amount0();
        int128 d1 = delta.amount1();

        if (d0 < 0) {
            uint256 owed = uint256(uint128(-d0));
            if (owed > cb.amount0Max) revert AmountExceedsMax();
            POOL_MANAGER.sync(poolKey.currency0);
            IERC20(Currency.unwrap(poolKey.currency0)).transfer(address(POOL_MANAGER), owed);
            POOL_MANAGER.settle();
        } else if (d0 > 0) {
            POOL_MANAGER.take(poolKey.currency0, cb.sender, uint256(uint128(d0)));
        }

        if (d1 < 0) {
            uint256 owed = uint256(uint128(-d1));
            if (owed > cb.amount1Max) revert AmountExceedsMax();
            POOL_MANAGER.sync(poolKey.currency1);
            IERC20(Currency.unwrap(poolKey.currency1)).transfer(address(POOL_MANAGER), owed);
            POOL_MANAGER.settle();
        } else if (d1 > 0) {
            POOL_MANAGER.take(poolKey.currency1, cb.sender, uint256(uint128(d1)));
        }

        return "";
    }

    function _refund(address token, address to) internal {
        uint256 bal = IERC20(token).balanceOf(address(this));
        if (bal > 0) IERC20(token).transfer(to, bal);
    }
}
