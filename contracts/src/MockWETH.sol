// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title MockWETH — generic 18-decimal testnet ERC20 (wrapped-ETH stand-in).
/// @notice Used as the volatile pair leg in the SignalCardHookV2 demo pool.
///         Chain-neutral: the deploy script picks the real WETH on the target
///         chain via the TOKEN_VOLATILE env var; this mock is only used when
///         that env var is empty (fresh testnet bring-up).
contract MockWETH is ERC20 {
    constructor() ERC20("Mock Wrapped Ether", "mWETH") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
