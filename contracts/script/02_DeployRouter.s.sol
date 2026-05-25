// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {SignalCardNFT} from "../src/SignalCardNFT.sol";
import {SignalCardRouter} from "../src/SignalCardRouter.sol";

/// @title 02_DeployRouter — companion to 01_DeployAll
/// @notice Deploys SignalCardRouter only. Reads existing addresses from env.
/// Usage:
///   POOL_MANAGER=0x... MOCK_OKB=0x... MOCK_USDC=0x... \
///   SIGNAL_CARD_NFT=0x... SIGNAL_CARD_HOOK=0x... \
///   PRIVATE_KEY=0x... \
///   forge script script/02_DeployRouter.s.sol --rpc-url xlayer_testnet --broadcast --via-ir
contract DeployRouter is Script {
    int24 constant TICK_SPACING = 60;

    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address poolManager = vm.envAddress("POOL_MANAGER");
        address okb = vm.envAddress("MOCK_OKB");
        address usdc = vm.envAddress("MOCK_USDC");
        address nft = vm.envAddress("SIGNAL_CARD_NFT");
        address hook = vm.envAddress("SIGNAL_CARD_HOOK");

        // Sort currencies the same way the pool was initialized.
        Currency c0;
        Currency c1;
        if (okb < usdc) {
            c0 = Currency.wrap(okb);
            c1 = Currency.wrap(usdc);
        } else {
            c0 = Currency.wrap(usdc);
            c1 = Currency.wrap(okb);
        }

        vm.startBroadcast(pk);

        SignalCardRouter router = new SignalCardRouter(
            IPoolManager(poolManager),
            SignalCardNFT(nft),
            c0,
            c1,
            TICK_SPACING,
            IHooks(hook)
        );
        console2.log("SignalCardRouter:", address(router));

        vm.stopBroadcast();

        console2.log("\n=== copy into .env ===");
        console2.log("VITE_XLAYER_ROUTER_ADDRESS=%s", address(router));
        console2.log("SIGNAL_CARD_ROUTER_ADDRESS=%s", address(router));
    }
}
