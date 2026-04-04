// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SignalRegistry.sol";

contract SignalRegistryTest is Test {
    SignalRegistry public registry;
    address public owner;
    address public user1;
    address public asset1;

    function setUp() public {
        owner = address(this);
        user1 = makeAddr("user1");
        asset1 = makeAddr("asset1");
        registry = new SignalRegistry();
    }

    function test_CreateSignal() public {
        vm.prank(user1);
        uint256 id = registry.createSignal(asset1, true, 85, 1500e18, 1400e18);
        assertEq(id, 0);
        assertEq(registry.getSignalCount(), 1);

        SignalRegistry.Signal memory s = registry.getSignal(0);
        assertEq(s.asset, asset1);
        assertTrue(s.isBull);
        assertEq(s.confidence, 85);
        assertEq(s.targetPrice, 1500e18);
        assertEq(s.entryPrice, 1400e18);
        assertEq(s.exitPrice, 0);
        assertFalse(s.resolved);
        assertEq(s.creator, user1);
    }

    function test_CreateSignal_InvalidConfidence() public {
        vm.expectRevert("Invalid confidence");
        registry.createSignal(asset1, true, 101, 1500e18, 1400e18);
    }

    function test_ResolveSignal_Profitable() public {
        registry.createSignal(asset1, true, 80, 1500e18, 1400e18);
        registry.resolveSignal(0, 1600e18);

        SignalRegistry.Signal memory s = registry.getSignal(0);
        assertTrue(s.resolved);
        assertEq(s.exitPrice, 1600e18);
    }

    function test_ResolveSignal_OnlyOwner() public {
        registry.createSignal(asset1, true, 80, 1500e18, 1400e18);
        vm.prank(user1);
        vm.expectRevert();
        registry.resolveSignal(0, 1600e18);
    }

    function test_ResolveSignal_AlreadyResolved() public {
        registry.createSignal(asset1, true, 80, 1500e18, 1400e18);
        registry.resolveSignal(0, 1600e18);
        vm.expectRevert("Already resolved");
        registry.resolveSignal(0, 1700e18);
    }

    function test_GetUserSignals() public {
        vm.startPrank(user1);
        registry.createSignal(asset1, true, 80, 1500e18, 1400e18);
        registry.createSignal(asset1, false, 70, 1300e18, 1400e18);
        vm.stopPrank();

        uint256[] memory ids = registry.getUserSignals(user1);
        assertEq(ids.length, 2);
        assertEq(ids[0], 0);
        assertEq(ids[1], 1);
    }

    function test_GetSignals_Pagination() public {
        for (uint256 i = 0; i < 5; i++) {
            registry.createSignal(asset1, true, uint8(50 + i), 1500e18, 1400e18);
        }

        SignalRegistry.Signal[] memory page = registry.getSignals(1, 3);
        assertEq(page.length, 3);
        assertEq(page[0].confidence, 51);
        assertEq(page[2].confidence, 53);
    }

    function test_GetSignals_OffsetBeyondTotal() public {
        registry.createSignal(asset1, true, 80, 1500e18, 1400e18);
        SignalRegistry.Signal[] memory page = registry.getSignals(5, 10);
        assertEq(page.length, 0);
    }

    function test_GetSignal_InvalidId() public {
        vm.expectRevert("Invalid id");
        registry.getSignal(0);
    }

    function test_ResolveSignal_InvalidId() public {
        vm.expectRevert("Invalid id");
        registry.resolveSignal(0, 1600e18);
    }
}
