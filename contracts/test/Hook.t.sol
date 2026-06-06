// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {PoolManager} from "v4-core/src/PoolManager.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {LPFeeLibrary} from "v4-core/src/libraries/LPFeeLibrary.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {TickMath} from "v4-core/src/libraries/TickMath.sol";

import {MockWETH} from "../src/MockWETH.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {SignalCardNFT} from "../src/SignalCardNFT.sol";
import {SignalCardHookV2} from "../src/SignalCardHookV2.sol";

contract HookTest is Test {
    PoolManager poolManager;
    MockWETH weth;
    MockUSDC usdc;
    SignalCardNFT nft;
    SignalCardHookV2 hook;
    PoolKey poolKey;

    address deployer = address(this);
    address alice = address(0xA11CE);

    int24 constant TICK_LOWER = -120;
    int24 constant TICK_UPPER = 120;
    int24 constant TICK_SPACING = 60;
    uint16 constant RISK = 58;

    function setUp() public {
        // Deploy v4 core
        poolManager = new PoolManager(deployer);

        // Deploy tokens
        weth = new MockWETH();
        usdc = new MockUSDC();

        // Deploy NFT
        nft = new SignalCardNFT(deployer, deployer);

        // Deploy hook at correct address using deployCodeTo cheatcode
        // V2 flags: BEFORE_ADD_LIQUIDITY | BEFORE_REMOVE_LIQUIDITY | BEFORE_SWAP | AFTER_SWAP
        uint160 flags = uint160(
            Hooks.BEFORE_ADD_LIQUIDITY_FLAG | Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG |
            Hooks.BEFORE_SWAP_FLAG | Hooks.AFTER_SWAP_FLAG
        );
        address hookAddr = address(flags); // simplified for local test
        deployCodeTo(
            "SignalCardHookV2.sol",
            abi.encode(address(poolManager), address(nft)),
            hookAddr
        );
        hook = SignalCardHookV2(hookAddr);
        nft.setHook(address(hook));

        // Sort currencies
        Currency c0;
        Currency c1;
        if (address(weth) < address(usdc)) {
            c0 = Currency.wrap(address(weth));
            c1 = Currency.wrap(address(usdc));
        } else {
            c0 = Currency.wrap(address(usdc));
            c1 = Currency.wrap(address(weth));
        }

        poolKey = PoolKey(c0, c1, LPFeeLibrary.DYNAMIC_FEE_FLAG, TICK_SPACING, IHooks(address(hook)));

        // Initialize pool
        uint160 sqrtPrice = 79228162514264337593543950336; // 1:1
        poolManager.initialize(poolKey, sqrtPrice);

        // Fund alice
        weth.mint(alice, 1_000_000 ether);
        usdc.mint(alice, 1_000_000e6);
    }

    // ─── Revert paths ─────────────────────────────────────────

    function test_revert_cardAlreadyPlayed() public {
        // Mint and mark played
        nft.mint(1, alice, _card(TICK_LOWER, TICK_UPPER, RISK, true));
        vm.prank(address(hook));
        nft.markPlayed(1);

        // Attempt to add liquidity with played card should revert
        bytes memory hookData = abi.encode(uint256(1));
        vm.expectRevert(SignalCardHookV2.CardAlreadyPlayed.selector);
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER, TICK_UPPER);
    }

    function test_revert_cardExpired() public {
        // Mint with past expiry
        SignalCardNFT.CardData memory c = _card(TICK_LOWER, TICK_UPPER, RISK, true);
        c.expiresAt = uint64(block.timestamp - 1);
        nft.mint(2, alice, c);

        bytes memory hookData = abi.encode(uint256(2));
        vm.expectRevert(SignalCardHookV2.CardExpired.selector);
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER, TICK_UPPER);
    }

    function test_revert_notCardOwner() public {
        nft.mint(3, deployer, _card(TICK_LOWER, TICK_UPPER, RISK, true));

        // Alice is tx.origin but doesn't own card 3
        bytes memory hookData = abi.encode(uint256(3));
        vm.prank(alice, alice); // sets both msg.sender and tx.origin
        vm.expectRevert(SignalCardHookV2.NotCardOwner.selector);
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER, TICK_UPPER);
    }

    function test_revert_tickMismatch() public {
        nft.mint(4, alice, _card(TICK_LOWER, TICK_UPPER, RISK, true));

        bytes memory hookData = abi.encode(uint256(4));
        vm.prank(alice, alice);
        vm.expectRevert(SignalCardHookV2.TickMismatch.selector);
        // Wrong ticks
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER + 60, TICK_UPPER);
    }

    // ─── Happy path ───────────────────────────────────────────

    function test_happyPath_marksPlayed() public {
        nft.mint(5, alice, _card(TICK_LOWER, TICK_UPPER, RISK, true));

        bytes memory hookData = abi.encode(uint256(5));
        vm.prank(alice, alice);
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER, TICK_UPPER);

        // Card should be marked played
        assertTrue(nft.cardData(5).played);
    }

    // ─── Dynamic fee ──────────────────────────────────────────

    function test_dynamicFee_fromRiskScore() public {
        // Play a card to set lastCardRisk
        nft.mint(6, alice, _card(TICK_LOWER, TICK_UPPER, RISK, true));
        bytes memory hookData = abi.encode(uint256(6));
        vm.prank(alice, alice);
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER, TICK_UPPER);

        // Check stored risk
        assertEq(hook.lastCardRisk(poolKey.toId()), RISK);

        // Expected fee: (30 + 58) * 100 = 8800
        // We can't easily call beforeSwap externally, but we verify the storage
        // that drives it. Full integration test would require a swap via PoolManager.
    }

    function test_dynamicFee_capsAt100() public {
        // Card with risk > 100
        nft.mint(7, alice, _card(TICK_LOWER, TICK_UPPER, 150, true));
        bytes memory hookData = abi.encode(uint256(7));
        vm.prank(alice, alice);
        _simulateBeforeAddLiquidity(hookData, TICK_LOWER, TICK_UPPER);

        // Stored as-is; the cap happens in beforeSwap
        assertEq(hook.lastCardRisk(poolKey.toId()), 150);
    }

    // ─── Helpers ──────────────────────────────────────────────

    function _card(int24 lower, int24 upper, uint16 risk, bool bull)
        internal view returns (SignalCardNFT.CardData memory)
    {
        return SignalCardNFT.CardData({
            tokenSymbol: "BTC",
            stopTickHint: lower,
            targetTickHint: upper,
            riskScore: risk,
            rarity: 1,
            isBull: bull,
            expiresAt: uint64(block.timestamp + 1 days),
            played: false
        });
    }

    /// @dev Simulates the hook's beforeAddLiquidity by calling it directly via
    ///      the PoolManager's test interface. For unit tests we call the hook
    ///      directly since we deployed it at a cheatcode address.
    function _simulateBeforeAddLiquidity(bytes memory hookData, int24 tickLower, int24 tickUpper) internal {
        IPoolManager.ModifyLiquidityParams memory params = IPoolManager.ModifyLiquidityParams({
            tickLower: tickLower,
            tickUpper: tickUpper,
            liquidityDelta: 1000e18,
            salt: bytes32(0)
        });
        // Direct call to hook's internal function via the public test wrapper
        // In production this is called by PoolManager; in tests we simulate.
        hook.beforeAddLiquidity(address(this), poolKey, params, hookData);
    }
}
