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

/// @title 04_DeployRealV4 — deploy the full hook stack against real Uniswap v4
/// @notice Single responsibility: stand up a real-v4 OKB/USDC pool + hook on any EVM chain.
///         Same script works for testnet 1952 and mainnet 196 (env-driven).
///
///         Reuses existing token addresses if MOCK_OKB / MOCK_USDC env vars are set
///         (testnet preserves user balances); otherwise deploys fresh tokens.
///
///         Reuses canonical Uniswap v4 PoolManager if POOL_MANAGER env var is set
///         (mainnet 196 has one at 0x360e68fa...); otherwise deploys our own PoolManager
///         (testnet 1952 has no canonical v4 yet).
///
///         Writes deployments/<chainId>.json as the single source of truth.
///         FE/BE env files derive from this JSON via scripts/sync-deployments.mjs.
///
/// Usage:
///   forge script script/04_DeployRealV4.s.sol --rpc-url xlayer_testnet --broadcast --via-ir
contract DeployRealV4 is Script {
    int24 constant TICK_SPACING = 60;
    uint160 constant SQRT_PRICE_1_1 = 79228162514264337593543950336; // sqrt(1) * 2^96

    // SignalCardHookV2 advertises 4 callbacks; flag mask = 0x0AC0
    uint160 constant HOOK_FLAGS = uint160(
        Hooks.BEFORE_ADD_LIQUIDITY_FLAG
        | Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG
        | Hooks.BEFORE_SWAP_FLAG
        | Hooks.AFTER_SWAP_FLAG
    );

    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);

        vm.startBroadcast(pk);

        address poolManager = _resolveOrDeployPoolManager(deployer);
        address okb         = _resolveOrDeployToken("MOCK_OKB",  /*isUSDC*/ false);
        address usdc        = _resolveOrDeployToken("MOCK_USDC", /*isUSDC*/ true);

        SignalCardNFT nft = new SignalCardNFT(deployer, deployer);

        address hookAddr = _deployHookCreate2(poolManager, address(nft));
        nft.setHook(hookAddr);

        (Currency c0, Currency c1) = _sortCurrencies(okb, usdc);
        PoolKey memory key = PoolKey(c0, c1, LPFeeLibrary.DYNAMIC_FEE_FLAG, TICK_SPACING, IHooks(hookAddr));
        IPoolManager(poolManager).initialize(key, SQRT_PRICE_1_1);

        SignalCardRouterV2 router = new SignalCardRouterV2(
            IPoolManager(poolManager), nft, c0, c1, TICK_SPACING, IHooks(hookAddr)
        );

        _mintDemoCards(nft, deployer);

        vm.stopBroadcast();

        _writeDeploymentsJson(poolManager, okb, usdc, address(nft), hookAddr, address(router), key);
        _logSummary(poolManager, okb, usdc, address(nft), hookAddr, address(router));
    }

    // ── Resolution helpers ─────────────────────────────────────────────────

    /// @dev Reuse canonical PoolManager (mainnet 196) if POOL_MANAGER env is set,
    ///      else deploy our own (testnet 1952 has no canonical v4).
    function _resolveOrDeployPoolManager(address owner) internal returns (address pm) {
        pm = vm.envOr("POOL_MANAGER", address(0));
        if (pm == address(0)) {
            pm = address(new PoolManager(owner));
            console2.log("Deployed PoolManager:", pm);
        } else {
            console2.log("Reusing PoolManager:", pm);
        }
    }

    /// @dev Reuse existing test token if env var is set (preserves testnet balances),
    ///      else deploy a fresh one.
    function _resolveOrDeployToken(string memory envKey, bool isUSDC) internal returns (address token) {
        token = vm.envOr(envKey, address(0));
        if (token == address(0)) {
            token = isUSDC ? address(new MockUSDC()) : address(new MockOKB());
            console2.log(string.concat("Deployed ", envKey, ":"), token);
        } else {
            console2.log(string.concat("Reusing ",  envKey, ":"), token);
        }
    }

    // ── Hook mining + CREATE2 deploy ───────────────────────────────────────

    function _deployHookCreate2(address pm, address nft) internal returns (address hookAddr) {
        bytes memory creationCode  = type(SignalCardHookV2).creationCode;
        bytes memory ctorArgs      = abi.encode(pm, nft);
        bytes32 salt;
        (hookAddr, salt) = HookMiner.find(CREATE2_FACTORY, HOOK_FLAGS, creationCode, ctorArgs);
        console2.log("Mined hook address:", hookAddr);

        bytes memory initCode = abi.encodePacked(creationCode, ctorArgs);
        (bool ok,) = CREATE2_FACTORY.call(abi.encodePacked(salt, initCode));
        require(ok && hookAddr.code.length > 0, "CREATE2 deploy failed");

        require(
            (uint160(hookAddr) & 0x3FFF) == HOOK_FLAGS,
            "Hook address flags do not match"
        );
    }

    // ── Pool key construction ──────────────────────────────────────────────

    function _sortCurrencies(address a, address b) internal pure returns (Currency c0, Currency c1) {
        if (a < b) { c0 = Currency.wrap(a); c1 = Currency.wrap(b); }
        else       { c0 = Currency.wrap(b); c1 = Currency.wrap(a); }
    }

    // ── Demo cards (deterministic; ticks bracket sqrtPrice = 1.0) ──────────

    function _mintDemoCards(SignalCardNFT nft, address to) internal {
        uint64 expiresAt = uint64(block.timestamp + 1 days);
        nft.mint(1, to, _card("BTC", -120,  120, 58, 1, true,  expiresAt));
        nft.mint(2, to, _card("ETH",  -60,   60, 42, 0, true,  expiresAt));
        nft.mint(3, to, _card("SOL",   60,  180, 75, 2, true,  expiresAt));
        nft.mint(4, to, _card("BTC", -180,  -60, 30, 0, false, expiresAt));
        nft.mint(5, to, _card("ETH", -120,    0, 90, 1, false, expiresAt));
    }

    function _card(string memory sym, int24 lo, int24 hi, uint16 risk, uint8 rarity, bool bull, uint64 exp)
        internal pure returns (SignalCardNFT.CardData memory)
    {
        return SignalCardNFT.CardData(sym, lo, hi, risk, rarity, bull, exp, false);
    }

    // ── Single-source-of-truth deployments JSON ────────────────────────────

    function _writeDeploymentsJson(
        address pm, address okb, address usdc, address nft, address hook, address router, PoolKey memory key
    ) internal {
        string memory root = "deploy";
        vm.serializeUint   (root, "chainId",       block.chainid);
        vm.serializeAddress(root, "PoolManager",   pm);
        vm.serializeAddress(root, "MockOKB",       okb);
        vm.serializeAddress(root, "MockUSDC",      usdc);
        vm.serializeAddress(root, "SignalCardNFT", nft);
        vm.serializeAddress(root, "SignalCardHook",   hook);
        vm.serializeAddress(root, "SignalCardRouter", router);
        vm.serializeAddress(root, "currency0",     Currency.unwrap(key.currency0));
        vm.serializeAddress(root, "currency1",     Currency.unwrap(key.currency1));
        vm.serializeUint   (root, "tickSpacing",   uint256(int256(key.tickSpacing)));
        string memory json = vm.serializeUint(root, "fee", key.fee);

        string memory path = string.concat(
            "deployments/", vm.toString(block.chainid), ".json"
        );
        vm.writeJson(json, path);
        console2.log("Wrote deployments JSON:", path);
    }

    function _logSummary(address pm, address okb, address usdc, address nft, address hook, address router) internal pure {
        console2.log("\n=== DEPLOYMENT SUMMARY ===");
        console2.log("PoolManager:        ", pm);
        console2.log("MockOKB:            ", okb);
        console2.log("MockUSDC:           ", usdc);
        console2.log("SignalCardNFT:      ", nft);
        console2.log("SignalCardHookV2:   ", hook);
        console2.log("SignalCardRouterV2: ", router);
    }
}
