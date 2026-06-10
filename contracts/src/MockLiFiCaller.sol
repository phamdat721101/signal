// SPDX-License-Identifier: MIT
//
// ════════════════════════════════════════════════════════════════════
//  TESTNET ONLY — DO NOT DEPLOY TO MAINNET.
//
//  MockLiFiCaller stands in for the real LiFi destination caller while
//  Kinetic v3 is being demoed on Somnia testnet 50312, before the
//  mainnet LiFi caller is allowlisted via DevRel coordination.
//
//  The deploy script (06_DeployPredictionCardLiFi.s.sol) skips this
//  contract when KINETIC_NETWORK=mainnet.
// ════════════════════════════════════════════════════════════════════
pragma solidity ^0.8.24;

import {Ownable}    from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}     from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}  from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {PredictionCardLiFiExecutor} from "./PredictionCardLiFiExecutor.sol";

/// @title MockLiFiCaller — simulates LiFi calls-on-delivery on Somnia testnet.
/// @notice Pre-funded with MockUSDC at deploy. A backend script invokes
///         `simulateLifiDelivery` once it has observed the user's origin-chain
///         Compact-lock tx; this contract then forwards into the executor as
///         if it were the real LiFi destination caller.
contract MockLiFiCaller is Ownable {
    using SafeERC20 for IERC20;

    PredictionCardLiFiExecutor public immutable EXECUTOR;
    IERC20                     public immutable USDC;

    event Simulated(bytes32 indexed lifiOriginTxHash, address indexed user, uint256 amount);

    constructor(address executor, address usdc, address owner_) Ownable(owner_) {
        require(executor != address(0) && usdc != address(0) && owner_ != address(0), "zero");
        EXECUTOR = PredictionCardLiFiExecutor(payable(executor));
        USDC     = IERC20(usdc);
    }

    /// @notice Forward a "delivery" into the executor. Owner-gated so random
    ///         testnet wallets can't drain the pre-funded USDC.
    function simulateLifiDelivery(
        bytes32  lifiOriginTxHash,
        bytes    calldata extraLifiData,   // appended after the origin-tx-hash header
        uint256  prophecyMarketId,
        string   calldata symbol,
        string   calldata context,
        uint256  swipeStakeUsdc,
        address  originalUser
    ) external payable onlyOwner {
        // Header (32 bytes origin tx hash) || tail (opaque LiFi-side metadata)
        bytes memory lifiData = abi.encodePacked(lifiOriginTxHash, extraLifiData);

        USDC.forceApprove(address(EXECUTOR), swipeStakeUsdc);
        EXECUTOR.executeFromLiFi{value: msg.value}(
            lifiData, prophecyMarketId, symbol, context, swipeStakeUsdc, originalUser
        );
        emit Simulated(lifiOriginTxHash, originalUser, swipeStakeUsdc);
    }

    /// @notice Recover any leftover USDC after testnet drills.
    function sweep(address to) external onlyOwner {
        USDC.safeTransfer(to, USDC.balanceOf(address(this)));
    }

    receive() external payable {}
}
