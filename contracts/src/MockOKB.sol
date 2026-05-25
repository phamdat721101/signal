// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title MockOKB — testnet stand-in for OKB on X Layer
/// @notice Mint is permissionless on testnet. Replace with real OKB on mainnet.
contract MockOKB is ERC20 {
    constructor() ERC20("Mock OKB", "mOKB") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
