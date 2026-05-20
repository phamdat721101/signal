// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @dev Initia ERC20Registry precompile at 0xF2
interface IERC20Registry {
    function register_erc20() external returns (bool);
    function register_erc20_store(address account) external returns (bool);
    function is_erc20_store_registered(address account) external view returns (bool);
}

IERC20Registry constant ERC20_REGISTRY = IERC20Registry(0x00000000000000000000000000000000000000F2);

contract MockIUSD is ERC20, Ownable {
    uint256 public constant FAUCET_AMOUNT = 1000 * 1e18;
    uint256 public constant FAUCET_COOLDOWN = 1 hours;
    mapping(address => uint256) public lastFaucetClaim;

    event FaucetClaimed(address indexed user, uint256 amount);

    constructor() ERC20("Mock iUSD", "iUSD") Ownable(msg.sender) {
        // Register with Initia ERC20Registry precompile only when present.
        // On chains without the precompile (e.g. evm-1 testnet), behave as a vanilla ERC20.
        if (address(ERC20_REGISTRY).code.length > 0) {
            try ERC20_REGISTRY.register_erc20() returns (bool) {} catch {}
        }
        _mint(msg.sender, 1_000_000 * 1e18);
    }

    /// @dev Hook called on every mint/transfer/burn. Registers recipient's ERC20 store
    ///      when the precompile is available; otherwise behaves like a vanilla ERC20.
    function _update(address from, address to, uint256 value) internal override {
        if (to != address(0) && address(ERC20_REGISTRY).code.length > 0) {
            try ERC20_REGISTRY.is_erc20_store_registered(to) returns (bool registered) {
                if (!registered) {
                    try ERC20_REGISTRY.register_erc20_store(to) returns (bool) {} catch {}
                }
            } catch {}
        }
        super._update(from, to, value);
    }

    function faucet() external {
        require(block.timestamp - lastFaucetClaim[msg.sender] >= FAUCET_COOLDOWN, "Faucet: cooldown active");
        lastFaucetClaim[msg.sender] = block.timestamp;
        _mint(msg.sender, FAUCET_AMOUNT);
        emit FaucetClaimed(msg.sender, FAUCET_AMOUNT);
    }

    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /// @notice Re-register this token with the Initia ERC20Registry precompile.
    ///         Call once after deploy if the initial registration was skipped.
    function registerToken() external onlyOwner {
        require(address(ERC20_REGISTRY).code.length > 0, "ERC20Registry not available");
        ERC20_REGISTRY.register_erc20();
    }

    function batchMint(address[] calldata recipients, uint256 amount) external onlyOwner {
        for (uint256 i = 0; i < recipients.length; i++) {
            _mint(recipients[i], amount);
        }
    }
}
