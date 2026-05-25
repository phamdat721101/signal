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
import {SignalCardHook} from "../src/SignalCardHook.sol";
import {HookMiner} from "../src/base/HookMiner.sol";

/// @title 01_DeployAll — single-command bring-up on X Layer testnet
/// @notice Deploys: PoolManager, MockOKB, MockUSDC, SignalCardNFT, SignalCardHook
///         (CREATE2-mined for correct flag bits), initializes pool, mints 5 demo cards.
/// Usage:
///   forge script script/01_DeployAll.s.sol --rpc-url xlayer_testnet --broadcast --via-ir
contract DeployAll is Script {
    int24 constant TICK_SPACING = 60;

    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);

        vm.startBroadcast(pk);

        // 1. PoolManager
        PoolManager poolManager = new PoolManager(deployer);
        console2.log("PoolManager:", address(poolManager));

        // 2. Mock tokens
        MockOKB okb = new MockOKB();
        MockUSDC usdc = new MockUSDC();
        okb.mint(deployer, 1_000_000 ether);
        usdc.mint(deployer, 1_000_000e6);
        console2.log("MockOKB:", address(okb));
        console2.log("MockUSDC:", address(usdc));

        // 3. SignalCardNFT
        SignalCardNFT nft = new SignalCardNFT(deployer, deployer);
        console2.log("SignalCardNFT:", address(nft));

        // 4. Mine hook address with correct flag bits via standard CREATE2 factory
        address CREATE2_FACTORY = 0x4e59b44847b379578588920cA78FbF26c0B4956C;
        uint160 flags = uint160(Hooks.BEFORE_ADD_LIQUIDITY_FLAG | Hooks.BEFORE_SWAP_FLAG);
        bytes memory creationCode = type(SignalCardHook).creationCode;
        bytes memory constructorArgs = abi.encode(address(poolManager), address(nft));
        (address hookAddr, bytes32 salt) = HookMiner.find(CREATE2_FACTORY, flags, creationCode, constructorArgs);
        console2.log("Mined hook address:", hookAddr);

        // 5. Deploy hook via CREATE2 factory
        bytes memory initCode = abi.encodePacked(creationCode, constructorArgs);
        (bool success,) = CREATE2_FACTORY.call(abi.encodePacked(salt, initCode));
        require(success, "CREATE2 deploy failed");
        SignalCardHook hook = SignalCardHook(hookAddr);
        require(address(hook).code.length > 0, "Hook not deployed");
        console2.log("SignalCardHook:", address(hook));
        nft.setHook(address(hook));

        // 6. Sort currencies + initialize pool
        Currency c0;
        Currency c1;
        if (address(okb) < address(usdc)) {
            c0 = Currency.wrap(address(okb));
            c1 = Currency.wrap(address(usdc));
        } else {
            c0 = Currency.wrap(address(usdc));
            c1 = Currency.wrap(address(okb));
        }

        PoolKey memory key = PoolKey(c0, c1, LPFeeLibrary.DYNAMIC_FEE_FLAG, TICK_SPACING, IHooks(address(hook)));
        uint160 sqrtPriceX96 = 79228162514264337593543950336; // sqrt(1) * 2^96
        poolManager.initialize(key, sqrtPriceX96);
        console2.log("Pool initialized");

        // 7. Mint 5 demo cards
        nft.mint(1, deployer, SignalCardNFT.CardData("BTC", -120, 120, 58, 1, true, uint64(block.timestamp + 1 days), false));
        nft.mint(2, deployer, SignalCardNFT.CardData("ETH", -60, 60, 42, 0, true, uint64(block.timestamp + 1 days), false));
        nft.mint(3, deployer, SignalCardNFT.CardData("SOL", 60, 180, 75, 2, true, uint64(block.timestamp + 1 days), false));
        nft.mint(4, deployer, SignalCardNFT.CardData("BTC", -180, -60, 30, 0, false, uint64(block.timestamp + 1 days), false));
        nft.mint(5, deployer, SignalCardNFT.CardData("ETH", -120, 0, 90, 1, false, uint64(block.timestamp + 1 days), false));
        console2.log("Minted 5 demo cards");

        vm.stopBroadcast();

        console2.log("\n=== .env.testnet ===");
        console2.log("POOL_MANAGER=%s", address(poolManager));
        console2.log("MOCK_OKB=%s", address(okb));
        console2.log("MOCK_USDC=%s", address(usdc));
        console2.log("SIGNAL_CARD_NFT=%s", address(nft));
        console2.log("SIGNAL_CARD_HOOK=%s", address(hook));
    }
}
