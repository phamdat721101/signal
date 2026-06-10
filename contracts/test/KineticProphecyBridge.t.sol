// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {KineticProphecyBridge} from "../src/KineticProphecyBridge.sol";

/// @notice Minimal mock — records calls and can be flipped to revert.
contract MockConvictionEngine {
    struct Call { bytes32 cardHash; bool outcome; }
    Call[] public calls;
    bool public shouldRevert;

    function setRevert(bool r) external { shouldRevert = r; }
    function callCount() external view returns (uint256) { return calls.length; }

    function resolveCard(bytes32 cardHash, bool outcome) external {
        if (shouldRevert) revert("conviction: boom");
        calls.push(Call(cardHash, outcome));
    }
}

contract KineticProphecyBridgeTest is Test {
    KineticProphecyBridge bridge;
    MockConvictionEngine conviction;
    address owner = address(this);
    address binder = address(0xB1);
    address relay  = address(0xB2);
    address rando  = address(0x9999);

    bytes32 internal constant CH1 = keccak256(abi.encode(uint256(1), uint256(42)));
    bytes32 internal constant CH2 = keccak256(abi.encode(uint256(2), uint256(99)));

    function setUp() public {
        conviction = new MockConvictionEngine();
        bridge = new KineticProphecyBridge(address(conviction), owner);
        bridge.setBinder(binder, true);
        bridge.setRelay(relay, true);
    }

    // ─── construction ──────────────────────────────────────────────

    function test_zero_address_constructor_reverts() public {
        vm.expectRevert(KineticProphecyBridge.ZeroAddress.selector);
        new KineticProphecyBridge(address(0), owner);
    }

    function test_owner_is_default_binder_and_relay() public view {
        assertTrue(bridge.authorizedBinders(owner));
        assertTrue(bridge.authorizedRelays(owner));
    }

    // ─── bind ───────────────────────────────────────────────────────

    function test_bind_happy_path() public {
        vm.prank(binder);
        bridge.bindMarketToCard(42, CH1);
        assertEq(bridge.prophecyToCardHash(42), CH1);
    }

    function test_bind_reverts_when_unauthorized() public {
        vm.prank(rando);
        vm.expectRevert(KineticProphecyBridge.NotAuthorized.selector);
        bridge.bindMarketToCard(42, CH1);
    }

    function test_bind_rejects_zero_hash() public {
        vm.prank(binder);
        vm.expectRevert(KineticProphecyBridge.ZeroCardHash.selector);
        bridge.bindMarketToCard(42, bytes32(0));
    }

    function test_bind_reverts_on_duplicate() public {
        vm.prank(binder);
        bridge.bindMarketToCard(42, CH1);
        vm.prank(binder);
        vm.expectRevert(KineticProphecyBridge.AlreadyBound.selector);
        bridge.bindMarketToCard(42, CH2);
    }

    // ─── trigger ────────────────────────────────────────────────────

    function test_trigger_settles_via_conviction() public {
        vm.prank(binder);
        bridge.bindMarketToCard(42, CH1);
        vm.prank(relay);
        bridge.triggerResolution(42, true, "ipfs://r");
        assertEq(conviction.callCount(), 1);
        (bytes32 ch, bool outcome) = conviction.calls(0);
        assertEq(ch, CH1);
        assertTrue(outcome);
        assertTrue(bridge.resolutionPropagated(42));
    }

    function test_trigger_reverts_when_not_relay() public {
        vm.prank(binder);
        bridge.bindMarketToCard(42, CH1);
        vm.prank(rando);
        vm.expectRevert(KineticProphecyBridge.NotAuthorized.selector);
        bridge.triggerResolution(42, true, "");
    }

    function test_trigger_reverts_for_unbound_market() public {
        vm.prank(relay);
        vm.expectRevert(KineticProphecyBridge.UnknownMarket.selector);
        bridge.triggerResolution(99, true, "");
    }

    function test_trigger_is_idempotent_on_second_call() public {
        vm.prank(binder);
        bridge.bindMarketToCard(42, CH1);
        vm.prank(relay);
        bridge.triggerResolution(42, true, "");
        vm.prank(relay);
        vm.expectRevert(KineticProphecyBridge.AlreadyPropagated.selector);
        bridge.triggerResolution(42, true, "");
    }

    function test_failed_propagation_reopens_slot_for_retry() public {
        conviction.setRevert(true);
        vm.prank(binder);
        bridge.bindMarketToCard(42, CH1);

        vm.prank(relay);
        bridge.triggerResolution(42, true, "");
        // After the catch path, the slot is re-opened.
        assertFalse(bridge.resolutionPropagated(42));
        assertEq(conviction.callCount(), 0);

        // Conviction recovers; relay retries; settlement lands.
        conviction.setRevert(false);
        vm.prank(relay);
        bridge.triggerResolution(42, true, "");
        assertTrue(bridge.resolutionPropagated(42));
        assertEq(conviction.callCount(), 1);
    }

    // ─── ACL ────────────────────────────────────────────────────────

    function test_only_owner_can_set_binder_and_relay() public {
        vm.prank(rando);
        vm.expectRevert();
        bridge.setBinder(rando, true);
        vm.prank(rando);
        vm.expectRevert();
        bridge.setRelay(rando, true);
    }

    function test_revoking_binder_blocks_subsequent_binds() public {
        bridge.setBinder(binder, false);
        vm.prank(binder);
        vm.expectRevert(KineticProphecyBridge.NotAuthorized.selector);
        bridge.bindMarketToCard(7, CH2);
    }
}
