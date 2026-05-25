// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HookMiner — finds a CREATE2 salt producing an address with EXACT flag bits
/// @notice v4's BaseHook.validateHookAddress requires the lower 14 bits of the
///         address to EQUAL the encoded permissions, no more, no less.
library HookMiner {
    uint160 constant ALL_HOOK_MASK = uint160((1 << 14) - 1);

    /// @notice Find a salt that produces a hook address with the required flags exactly.
    function find(
        address deployer,
        uint160 flags,
        bytes memory creationCode,
        bytes memory constructorArgs
    ) internal pure returns (address hookAddress, bytes32 salt) {
        bytes memory initCode = abi.encodePacked(creationCode, constructorArgs);
        bytes32 initCodeHash = keccak256(initCode);

        for (uint256 i = 0; i < 200_000; i++) {
            salt = bytes32(i);
            hookAddress = address(uint160(uint256(keccak256(
                abi.encodePacked(bytes1(0xff), deployer, salt, initCodeHash)
            ))));
            if (uint160(hookAddress) & ALL_HOOK_MASK == flags) {
                return (hookAddress, salt);
            }
        }
        revert("HookMiner: could not find salt");
    }
}
