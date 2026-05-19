// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Initia ICosmos precompile interface (verbatim from Initia docs).
///         https://initialabs.mintlify.app/resources/developer/contract-references/evm/cosmos
interface ICosmos {
    function execute_cosmos(string memory msgJson) external returns (bool);
    function query_cosmos(string memory path, string memory req)
        external returns (string memory);
    function to_cosmos_address(address evm) external returns (string memory);
    function to_evm_address(string memory cosmos) external returns (address);
    function to_denom(address erc20) external returns (string memory);
    function to_erc20(string memory denom) external returns (address);
    function is_blocked_address(address account) external view returns (bool);
    function is_module_address(address account) external view returns (bool);
}

ICosmos constant COSMOS = ICosmos(0x00000000000000000000000000000000000000f1);

/// @title CosmosUtils — read-only wrapper over the ICosmos precompile.
/// @notice Single responsibility: provide chain-portable, gas-capped helpers
///         for address/denom conversion and sanctions checks. No state, no auth.
///
///         Every external call to the precompile is wrapped in try/catch with
///         a hard gas cap (Code4rena 2025-02 H-07/H-08 mitigation). Returns
///         empty/zero on failure so callers can fail-open or fail-closed at
///         their discretion.
library CosmosUtils {
    uint256 internal constant PRECOMPILE_GAS_CAP = 100_000;

    function isPrecompileAvailable() internal view returns (bool) {
        return address(COSMOS).code.length > 0;
    }

    function isAddressSanctioned(address user) internal view returns (bool) {
        if (!isPrecompileAvailable()) return false;
        try COSMOS.is_blocked_address(user) returns (bool blocked) {
            return blocked;
        } catch {
            return false; // fail-open on read; caller chooses fail-closed at their own discretion
        }
    }

    function isModuleAddress(address account) internal view returns (bool) {
        if (!isPrecompileAvailable()) return false;
        try COSMOS.is_module_address(account) returns (bool m) {
            return m;
        } catch {
            return false;
        }
    }

    function toCosmosAddress(address evmAddr) internal returns (string memory) {
        if (!isPrecompileAvailable()) return "";
        try COSMOS.to_cosmos_address{gas: PRECOMPILE_GAS_CAP}(evmAddr)
            returns (string memory cosmosAddr) {
            return cosmosAddr;
        } catch {
            return "";
        }
    }

    function toEvmAddress(string memory cosmosAddr) internal returns (address) {
        if (!isPrecompileAvailable()) return address(0);
        try COSMOS.to_evm_address{gas: PRECOMPILE_GAS_CAP}(cosmosAddr)
            returns (address evmAddr) {
            return evmAddr;
        } catch {
            return address(0);
        }
    }

    function lookupERC20ForDenom(string memory denom) internal returns (address) {
        if (!isPrecompileAvailable()) return address(0);
        try COSMOS.to_erc20{gas: PRECOMPILE_GAS_CAP}(denom) returns (address erc20) {
            return erc20;
        } catch {
            return address(0);
        }
    }

    function lookupDenomForERC20(address erc20) internal returns (string memory) {
        if (!isPrecompileAvailable()) return "";
        try COSMOS.to_denom{gas: PRECOMPILE_GAS_CAP}(erc20) returns (string memory d) {
            return d;
        } catch {
            return "";
        }
    }
}

/// @notice Thin contract exposing CosmosUtils functions as a callable surface.
///         Other contracts can either:
///           (a) `using CosmosUtils for *;` and call the library directly, or
///           (b) deploy this contract and call its public functions.
///         The contract form is also useful for backend `chain.py` to read
///         e.g. is_blocked_address via web3.py without deploying its own ABI.
contract CosmosUtilsView {
    function isAddressSanctioned(address user) external view returns (bool) {
        return CosmosUtils.isAddressSanctioned(user);
    }

    function isModuleAddress(address account) external view returns (bool) {
        return CosmosUtils.isModuleAddress(account);
    }

    function toCosmosAddress(address evmAddr) external returns (string memory) {
        return CosmosUtils.toCosmosAddress(evmAddr);
    }

    function toEvmAddress(string memory cosmosAddr) external returns (address) {
        return CosmosUtils.toEvmAddress(cosmosAddr);
    }

    function lookupERC20ForDenom(string memory denom) external returns (address) {
        return CosmosUtils.lookupERC20ForDenom(denom);
    }

    function lookupDenomForERC20(address erc20) external returns (string memory) {
        return CosmosUtils.lookupDenomForERC20(erc20);
    }
}
