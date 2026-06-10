// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test}                from "forge-std/Test.sol";
import {Vm}                  from "forge-std/Vm.sol";
import {MockUSDC}            from "../src/MockUSDC.sol";
import {MockLiFiCaller}      from "../src/MockLiFiCaller.sol";
import {SomniaCardExecutor}  from "../src/SomniaCardExecutor.sol";
import {KineticProphecyBridge} from "../src/KineticProphecyBridge.sol";
import {PredictionCardLiFiExecutor} from "../src/PredictionCardLiFiExecutor.sol";

/// @notice Reentrancy attacker: when called via the LiFi flow, attempts to
///         re-enter `executeFromLiFi`. The ReentrancyGuard must trip.
contract ReentrantAttacker {
    PredictionCardLiFiExecutor public target;
    bool public didReenter;

    function arm(PredictionCardLiFiExecutor t) external { target = t; }

    /// @dev Stub of `SomniaCardExecutor.batchExecuteFromQueueFor` — reverts
    ///      via reentry attempt. Called via `vm.mockCall` is not enough
    ///      because we need real EVM execution; this contract is the
    ///      `cardExecutor` address in the reentrancy test.
    function batchExecuteFromQueueFor(address, SomniaCardExecutor.Swipe[] calldata)
        external
        payable
        returns (uint256[] memory ids)
    {
        didReenter = true;
        // Re-enter executeFromLiFi while the original call is still on-stack.
        bytes memory header = abi.encode(bytes32(uint256(0xdeadbeef)));
        target.executeFromLiFi{value: 0}(header, 1, "BTC", "ctx", 1_000_000, address(0xbeef));
        ids = new uint256[](1);
        ids[0] = 7;
    }
}

contract PredictionCardLiFiExecutorTest is Test {
    PredictionCardLiFiExecutor exec;
    MockUSDC usdc;
    address constant LIFI_CALLER     = address(0xCA11);
    address constant USER            = address(0xBEEF);
    address constant CARD_EXECUTOR   = address(0xC1A55);
    address constant PROPHECY_BRIDGE = address(0xB81D6E);

    uint256 constant MIN_STAKE = 100_000;        // $0.10 testnet floor
    uint256 constant STAKE     = 1_000_000;      // $1.00 swipe
    uint256 constant DEPOSIT   = 0.12 ether;     // SomniaSignalAgent platform deposit
    uint256 constant MARKET_ID = 12_345;
    bytes32 constant ORIGIN_TX = bytes32(uint256(0xfeed));

    function setUp() public {
        usdc = new MockUSDC();
        exec = new PredictionCardLiFiExecutor(
            CARD_EXECUTOR, PROPHECY_BRIDGE, address(usdc), MIN_STAKE, address(this)
        );
        exec.setAllowedLifiCaller(LIFI_CALLER, true);
        // Default: prophecy market is bound (non-zero hash)
        vm.mockCall(
            PROPHECY_BRIDGE,
            abi.encodeWithSignature("prophecyToCardHash(uint256)", MARKET_ID),
            abi.encode(bytes32(uint256(0x1234)))
        );
        // Default: card executor returns verdictId 42
        uint256[] memory ids = new uint256[](1);
        ids[0] = 42;
        vm.mockCall(
            CARD_EXECUTOR,
            abi.encodeWithSelector(SomniaCardExecutor.batchExecuteFromQueueFor.selector),
            abi.encode(ids)
        );
        // Fund the LiFi caller with USDC + ETH for swipes + gas
        usdc.mint(LIFI_CALLER, 100 * 1_000_000);
        vm.deal(LIFI_CALLER, 10 ether);
        vm.prank(LIFI_CALLER);
        usdc.approve(address(exec), type(uint256).max);
    }

    function _payload() internal pure returns (bytes memory) {
        return abi.encodePacked(ORIGIN_TX, bytes("opaque-lifi-tail"));
    }

    function _execute() internal {
        vm.prank(LIFI_CALLER);
        exec.executeFromLiFi{value: DEPOSIT}(
            _payload(), MARKET_ID, "BTC", "ctx", STAKE, USER
        );
    }

    // ── 1. Happy path ──────────────────────────────────────────────
    function test_HappyPath_SingleSwipe() public {
        vm.recordLogs();
        _execute();
        // SwipeCompleted is the last event
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bool found;
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].topics[0] == keccak256("SwipeCompleted(address,uint256,bytes32,uint256,bytes32)")) {
                assertEq(address(uint160(uint256(logs[i].topics[1]))), USER, "user");
                assertEq(uint256(logs[i].topics[2]), MARKET_ID, "marketId");
                found = true;
            }
        }
        assertTrue(found, "SwipeCompleted not emitted");
        assertTrue(exec.processedOriginTx(ORIGIN_TX), "idempotency flag");
    }

    // ── 2. ACL ─────────────────────────────────────────────────────
    function test_Revert_NotLifiCaller() public {
        vm.expectRevert(PredictionCardLiFiExecutor.NotLifiCaller.selector);
        exec.executeFromLiFi{value: DEPOSIT}(_payload(), MARKET_ID, "BTC", "ctx", STAKE, USER);
    }

    // ── 3. Bounds ──────────────────────────────────────────────────
    function test_Revert_LifiDataTooShort() public {
        vm.prank(LIFI_CALLER);
        vm.expectRevert(PredictionCardLiFiExecutor.LifiDataTooShort.selector);
        exec.executeFromLiFi{value: DEPOSIT}(hex"deadbeef", MARKET_ID, "BTC", "ctx", STAKE, USER);
    }

    function test_Revert_LifiDataTooLarge() public {
        bytes memory big = new bytes(4097);
        for (uint256 i; i < 32; i++) big[i] = bytes1(uint8(i));
        vm.prank(LIFI_CALLER);
        vm.expectRevert(PredictionCardLiFiExecutor.LifiDataTooLarge.selector);
        exec.executeFromLiFi{value: DEPOSIT}(big, MARKET_ID, "BTC", "ctx", STAKE, USER);
    }

    // ── 4. Idempotency ─────────────────────────────────────────────
    function test_Revert_AlreadyProcessed() public {
        _execute();
        vm.prank(LIFI_CALLER);
        vm.expectRevert(PredictionCardLiFiExecutor.AlreadyProcessed.selector);
        exec.executeFromLiFi{value: DEPOSIT}(_payload(), MARKET_ID, "BTC", "ctx", STAKE, USER);
    }

    // ── 5. Stake floor ─────────────────────────────────────────────
    function test_Revert_StakeBelowMinimum() public {
        vm.prank(LIFI_CALLER);
        vm.expectRevert(PredictionCardLiFiExecutor.StakeBelowMinimum.selector);
        exec.executeFromLiFi{value: DEPOSIT}(_payload(), MARKET_ID, "BTC", "ctx", MIN_STAKE - 1, USER);
    }

    // ── 6. Prophecy not bound ──────────────────────────────────────
    function test_Revert_UnknownProphecyMarket() public {
        vm.mockCall(
            PROPHECY_BRIDGE,
            abi.encodeWithSignature("prophecyToCardHash(uint256)", uint256(99999)),
            abi.encode(bytes32(0))
        );
        vm.prank(LIFI_CALLER);
        vm.expectRevert(PredictionCardLiFiExecutor.UnknownProphecyMarket.selector);
        exec.executeFromLiFi{value: DEPOSIT}(_payload(), 99999, "BTC", "ctx", STAKE, USER);
    }

    // ── 7. Zero user ───────────────────────────────────────────────
    function test_Revert_ZeroUser() public {
        vm.prank(LIFI_CALLER);
        vm.expectRevert(PredictionCardLiFiExecutor.ZeroAddress.selector);
        exec.executeFromLiFi{value: DEPOSIT}(_payload(), MARKET_ID, "BTC", "ctx", STAKE, address(0));
    }

    // ── 8. Owner setters ───────────────────────────────────────────
    function test_OwnerSetters() public {
        exec.setMinSwipeStakeUsdc(200_000);
        assertEq(exec.minSwipeStakeUsdc(), 200_000);
        exec.setAllowedLifiCaller(address(0x1234), true);
        assertTrue(exec.allowedLifiCallers(address(0x1234)));
        exec.setAllowedLifiCaller(address(0x1234), false);
        assertFalse(exec.allowedLifiCallers(address(0x1234)));
    }

    // ── 9. Gas budget ──────────────────────────────────────────────
    function test_Gas_HappyPath_Under300k() public {
        vm.prank(LIFI_CALLER);
        uint256 gasBefore = gasleft();
        exec.executeFromLiFi{value: DEPOSIT}(_payload(), MARKET_ID, "BTC", "ctx", STAKE, USER);
        uint256 used = gasBefore - gasleft();
        emit log_named_uint("gas used", used);
        assertLt(used, 300_000, "gas budget exceeded");
    }

    // ── 10. Reentrancy ─────────────────────────────────────────────
    function test_Revert_Reentrancy() public {
        ReentrantAttacker attacker = new ReentrantAttacker();
        // Redeploy executor pointing at the attacker as the card-executor address.
        PredictionCardLiFiExecutor reExec = new PredictionCardLiFiExecutor(
            address(attacker), PROPHECY_BRIDGE, address(usdc), MIN_STAKE, address(this)
        );
        reExec.setAllowedLifiCaller(LIFI_CALLER, true);
        attacker.arm(reExec);
        vm.mockCall(
            PROPHECY_BRIDGE,
            abi.encodeWithSignature("prophecyToCardHash(uint256)", MARKET_ID),
            abi.encode(bytes32(uint256(0x1234)))
        );
        vm.prank(LIFI_CALLER);
        usdc.approve(address(reExec), type(uint256).max);
        // The attacker's batchExecuteFromQueueFor re-enters; ReentrancyGuard reverts.
        vm.prank(LIFI_CALLER);
        vm.expectRevert();   // bubbles the reentrancy revert up through the failing reentry
        reExec.executeFromLiFi{value: DEPOSIT}(_payload(), MARKET_ID, "BTC", "ctx", STAKE, USER);
    }
}

/// @notice Task 3 — single integration test that the mock simulator forwards
///         calldata into the executor as if it were a real LiFi caller.
contract MockLiFiCallerTest is Test {
    MockLiFiCaller mock;
    PredictionCardLiFiExecutor exec;
    MockUSDC usdc;
    address constant USER            = address(0xBEEF);
    address constant CARD_EXECUTOR   = address(0xC1A55);
    address constant PROPHECY_BRIDGE = address(0xB81D6E);
    uint256 constant MARKET_ID = 12_345;

    function setUp() public {
        usdc = new MockUSDC();
        exec = new PredictionCardLiFiExecutor(
            CARD_EXECUTOR, PROPHECY_BRIDGE, address(usdc), 100_000, address(this)
        );
        mock = new MockLiFiCaller(address(exec), address(usdc), address(this));
        exec.setAllowedLifiCaller(address(mock), true);

        usdc.mint(address(mock), 50 * 1_000_000);
        vm.mockCall(
            PROPHECY_BRIDGE,
            abi.encodeWithSignature("prophecyToCardHash(uint256)", MARKET_ID),
            abi.encode(bytes32(uint256(0x1234)))
        );
        uint256[] memory ids = new uint256[](1);
        ids[0] = 100;
        vm.mockCall(
            CARD_EXECUTOR,
            abi.encodeWithSelector(SomniaCardExecutor.batchExecuteFromQueueFor.selector),
            abi.encode(ids)
        );
        vm.deal(address(this), 1 ether);
    }

    function test_MockCaller_ForwardsToExecutor_HappyPath() public {
        bytes32 origin = bytes32(uint256(0xc0ffee));
        mock.simulateLifiDelivery{value: 0.12 ether}(
            origin, hex"00", MARKET_ID, "BTC", "ctx", 1_000_000, USER
        );
        assertTrue(exec.processedOriginTx(origin), "origin tx flagged");
    }
}
