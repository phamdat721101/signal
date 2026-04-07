// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SessionVault.sol";
import "../src/MockIUSD.sol";

contract SessionVaultTest is Test {
    SessionVault public vault;
    MockIUSD public iusd;
    address public owner;
    address public user1;

    function setUp() public {
        owner = address(this);
        user1 = makeAddr("user1");
        iusd = new MockIUSD();
        vault = new SessionVault(address(iusd), owner);
        vault.setAuthorizedOperator(owner, true);
        iusd.mint(user1, 100 ether);
    }

    function _createSession(address user, uint256 amount, uint256 duration) internal returns (uint256) {
        vm.startPrank(user);
        iusd.approve(address(vault), amount);
        uint256 sid = vault.createSession(amount, duration);
        vm.stopPrank();
        return sid;
    }

    function test_PayFromSession() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);
        vm.prank(user1);
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
        SessionVault.Session memory s = vault.getSession(sid);
        assertEq(s.remainingBalance, 10 ether - 0.01 ether);
        assertEq(s.totalRedeemed, 0.01 ether);
        assertEq(s.voucherCount, 1);
    }

    function test_PayFromSession_EmitsEvent() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);
        vm.expectEmit(true, true, false, true);
        emit SessionVault.ServicePaid(sid, user1, 0.01 ether, "signal-premium");
        vm.prank(user1);
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_NotOwner() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert("Not session owner");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_Expired() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);
        vm.warp(block.timestamp + 2 hours);
        vm.prank(user1);
        vm.expectRevert("Session not active");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_InsufficientBalance() public {
        uint256 sid = _createSession(user1, 0.005 ether, 1 hours);
        vm.prank(user1);
        vm.expectRevert("Insufficient balance");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_ClosedSession() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);
        vm.prank(user1);
        vault.closeSession(sid);
        vm.prank(user1);
        vm.expectRevert("Session not active");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_MultiplePays() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);
        vm.startPrank(user1);
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
        vault.payFromSession(sid, 0.002 ether, "signal-single");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
        vm.stopPrank();
        SessionVault.Session memory s = vault.getSession(sid);
        assertEq(s.remainingBalance, 10 ether - 0.022 ether);
        assertEq(s.totalRedeemed, 0.022 ether);
        assertEq(s.voucherCount, 3);
    }
}
