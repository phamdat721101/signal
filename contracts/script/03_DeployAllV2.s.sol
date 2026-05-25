// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {PoolManager} from "v4-core/src/PoolManager.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {LPFeeLibrary} from "v4-core/src/libraries/LPFeeLibrary.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";

import {MockOKB} from "../src/MockOKB.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {SignalCardNFT} from "../src/SignalCardNFT.sol";
import {SignalCardHookV2} from "../src/SignalCardHookV2.sol";
import {SignalCardRouterV2} from "../src/SignalCardRouterV2.sol";
import {HookMiner} from "../src/base/HookMiner.sol";

/// @title 03_DeployAllV2 — full V2 stack (hook with remove-liquidity + afterSwap)
/// Usage: forge script script/03_DeployAllV2.s.sol --rpc-url xlayer_testnet --broadcast --via-ir
contract DeployAllV2 is Script {
    int24 constant TICK_SPACING = 60;
    // V2 flags: BEFORE_ADD_LIQUIDITY(11) | BEFORE_REMOVE_LIQUIDITY(9) | BEFORE_SWAP(7) | AFTER_SWAP(6)
    uint160 constant HOOK_FLAGS = uint160(
        Hooks.BEFORE_ADD_LIQUIDITY_FLAG | Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG |
        Hooks.BEFORE_SWAP_FLAG | Hooks.AFTER_SWAP_FLAG
    );

    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);
        address CREATE2_FACTORY = 0x4e59b44847b379578588920cA78FbF26c0B4956C;

        vm.startBroadcast(pk);

        // 1. Reuse existing PoolManager
        address poolManager = 0x21627d89bd86Be7F368bc7c9fd70F398595cc309;

        // 2. Reuse existing tokens (already minted)
        address okb = 0xF739a8aFfd096964A899B76F05a15293EDE0d0Ac;
        address usdc = 0x73BA01a4291aCccfaC2bad7470D6417643Ee9688;

        // 3. Fresh SignalCardNFT
        SignalCardNFT nft = new SignalCardNFT(deployer, deployer);
        console2.log("SignalCardNFT:", address(nft));

        // 4. Mine V2 hook address
        bytes memory creationCode = type(SignalCardHookV2).creationCode;
        bytes memory constructorArgs = abi.encode(poolManager, address(nft));
        (address hookAddr, bytes32 salt) = HookMiner.find(CREATE2_FACTORY, HOOK_FLAGS, creationCode, constructorArgs);
        console2.log("Mined hook address:", hookAddr);

        // 5. Deploy hook via CREATE2
        bytes memory initCode = abi.encodePacked(creationCode, constructorArgs);
        (bool ok,) = CREATE2_FACTORY.call(abi.encodePacked(salt, initCode));
        require(ok, "CREATE2 failed");
        require(hookAddr.code.length > 0, "Hook not deployed");
        console2.log("SignalCardHookV2:", hookAddr);
        nft.setHook(hookAddr);

        // 6. Sort currencies + initialize pool
        Currency c0;
        Currency c1;
        if (okb < usdc) { c0 = Currency.wrap(okb); c1 = Currency.wrap(usdc); }
        else { c0 = Currency.wrap(usdc); c1 = Currency.wrap(okb); }

        PoolKey memory key = PoolKey(c0, c1, LPFeeLibrary.DYNAMIC_FEE_FLAG, TICK_SPACING, IHooks(hookAddr));
        IPoolManager(poolManager).initialize(key, 79228162514264337593543950336); // sqrt(1) * 2^96
        console2.log("Pool initialized");

        // 7. Deploy RouterV2
        SignalCardRouterV2 router = new SignalCardRouterV2(
            IPoolManager(poolManager), nft, c0, c1, TICK_SPACING, IHooks(hookAddr)
        );
        console2.log("SignalCardRouterV2:", address(router));

        // 8. Mint 5 demo cards
        nft.mint(1, deployer, SignalCardNFT.CardData("BTC", -120, 120, 58, 1, true, uint64(block.timestamp + 1 days), false));
        nft.mint(2, deployer, SignalCardNFT.CardData("ETH", -60, 60, 42, 0, true, uint64(block.timestamp + 1 days), false));
        nft.mint(3, deployer, SignalCardNFT.CardData("SOL", 60, 180, 75, 2, true, uint64(block.timestamp + 1 days), false));
        nft.mint(4, deployer, SignalCardNFT.CardData("BTC", -180, -60, 30, 0, false, uint64(block.timestamp + 1 days), false));
        nft.mint(5, deployer, SignalCardNFT.CardData("ETH", -120, 0, 90, 1, false, uint64(block.timestamp + 1 days), false));
        console2.log("Minted 5 demo cards");

        vm.stopBroadcast();

        console2.log("\n=== V2 .env ===");
        console2.log("SIGNAL_CARD_NFT_ADDRESS=%s", address(nft));
        console2.log("SIGNAL_CARD_HOOK_ADDRESS=%s", hookAddr);
        console2.log("SIGNAL_CARD_ROUTER_ADDRESS=%s", address(router));
    }
}
