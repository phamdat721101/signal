// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {KineticProphecyBridge} from "../src/KineticProphecyBridge.sol";
import {ConvictionEngine} from "../src/ConvictionEngine.sol";

/// @title 06_DeployProphecyBridge — deploys + wires KineticProphecyBridge on testnet 50312
/// @notice Cross-chain split: this contract lives on the same chain as
///         the existing ConvictionEngine (Somnia testnet 50312). The
///         backend relay reads `MarketResolved` from Somnia mainnet 5031.
///
/// Required env:
///         PRIVATE_KEY                 — deployer + owner
///         CONVICTION_ENGINE_ADDRESS   — testnet 50312 address (read from deployments)
///
/// Optional env:
///         BACKEND_HOT_WALLET          — if set, granted binder + relay roles
///                                        in the same broadcast (one-shot deploy)
///
/// Usage: forge script script/06_DeployProphecyBridge.s.sol \
///        --rpc-url somnia_testnet --broadcast --via-ir
contract DeployProphecyBridge is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);
        address conviction = vm.envAddress("CONVICTION_ENGINE_ADDRESS");
        address backend = vm.envOr("BACKEND_HOT_WALLET", address(0));

        require(conviction != address(0), "CONVICTION_ENGINE_ADDRESS missing");

        vm.startBroadcast(pk);

        KineticProphecyBridge bridge = new KineticProphecyBridge(conviction, deployer);

        // Authorize the bridge to call resolveCard on the existing engine.
        // Idempotent: setAuthorizedResolver(true) is a no-op if already true.
        ConvictionEngine(conviction).setAuthorizedResolver(address(bridge), true);

        // Grant the backend hot wallet bind + relay rights up front so the
        // operator only needs PRIVATE_KEY in env to ship a working stack.
        if (backend != address(0)) {
            bridge.setBinder(backend, true);
            bridge.setRelay(backend, true);
        }

        vm.stopBroadcast();

        console.log("KineticProphecyBridge:", address(bridge));
        console.log("ConvictionEngine     :", conviction);
        console.log("Deployer / owner     :", deployer);
        if (backend != address(0)) console.log("Backend (binder+relay):", backend);
    }
}
