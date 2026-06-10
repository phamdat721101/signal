// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {MockUSDC}                   from "../src/MockUSDC.sol";
import {MockLiFiCaller}             from "../src/MockLiFiCaller.sol";
import {SomniaSignalAgent}          from "../src/SomniaSignalAgent.sol";
import {SomniaOracleAdapter}        from "../src/SomniaOracleAdapter.sol";
import {SomniaCardExecutor}         from "../src/SomniaCardExecutor.sol";
import {KineticProphecyBridge}      from "../src/KineticProphecyBridge.sol";
import {PredictionCardLiFiExecutor} from "../src/PredictionCardLiFiExecutor.sol";

/// @title 06_DeployPredictionCardLiFi — Kinetic v3 cross-chain glue
/// @notice Env vars:
///         PRIVATE_KEY                  — deployer key (also receives owner role)
///         SOMNIA_CARD_EXECUTOR         — already-deployed SomniaCardExecutor address
///         KINETIC_PROPHECY_BRIDGE      — already-deployed KineticProphecyBridge address
///         SOMNIA_USDC (optional)       — if unset on testnet, deploys MockUSDC and uses it
///         KINETIC_NETWORK              — "testnet" (default) | "mainnet"
///         LIFI_DESTINATION_CALLER (opt)— mainnet LiFi caller; testnet uses MockLiFiCaller
///         MIN_SWIPE_STAKE_USDC (opt)   — default 100_000 testnet ($0.10), 1_000_000 mainnet ($1.00)
///
/// Wirings performed (one tx each):
///   1. KineticProphecyBridge.setBinder(executor, true)         — currently a no-op since v3 doesn't re-bind, but keeps the surface ready for v3.1
///   2. SomniaCardExecutor.setDelegatedExecutor(executor, true) — required so batchExecuteFromQueueFor accepts our msg.sender
///   3. executor.setAllowedLifiCaller(LIFI_CALLER, true)        — Mock on testnet; real LiFi caller on mainnet
///
/// Usage:
///   PRIVATE_KEY=0x... \
///   SOMNIA_CARD_EXECUTOR=0x... KINETIC_PROPHECY_BRIDGE=0x... \
///   forge script script/06_DeployPredictionCardLiFi.s.sol \
///       --rpc-url somnia_testnet --broadcast --via-ir
contract DeployPredictionCardLiFi is Script {
    function run() external {
        uint256 pk        = vm.envUint("PRIVATE_KEY");
        address deployer  = vm.addr(pk);
        string memory net = vm.envOr("KINETIC_NETWORK", string("testnet"));
        bool isTestnet    = keccak256(bytes(net)) == keccak256(bytes("testnet"));
        uint256 minStake  = vm.envOr(
            "MIN_SWIPE_STAKE_USDC",
            isTestnet ? uint256(100_000) : uint256(1_000_000)
        );

        vm.startBroadcast(pk);

        // ── 0. Resolve / deploy v2 prerequisites (testnet bootstrap) ─
        // KineticProphecyBridge constructor needs ConvictionEngine addr.
        // SomniaCardExecutor constructor needs (signalAgent, oracle, conviction, proofOfAlpha, owner).
        address cardExec   = vm.envOr("SOMNIA_CARD_EXECUTOR", address(0));
        address propBridge = vm.envOr("KINETIC_PROPHECY_BRIDGE", address(0));
        if (cardExec == address(0)) {
            require(isTestnet, "mainnet must supply SOMNIA_CARD_EXECUTOR");
            address signalAgent  = vm.envAddress("SOMNIA_SIGNAL_AGENT");
            address oracle       = vm.envAddress("SOMNIA_ORACLE_ADAPTER");
            address conviction   = vm.envAddress("SOMNIA_CONVICTION_ENGINE");
            address proofOfAlpha = vm.envAddress("SOMNIA_PROOF_OF_ALPHA");
            cardExec = address(new SomniaCardExecutor(
                signalAgent, oracle, conviction, proofOfAlpha, deployer
            ));
            console.log("SomniaCardExecutor deployed:", cardExec);
        }
        if (propBridge == address(0)) {
            require(isTestnet, "mainnet must supply KINETIC_PROPHECY_BRIDGE");
            address conviction = vm.envAddress("SOMNIA_CONVICTION_ENGINE");
            propBridge = address(new KineticProphecyBridge(conviction, deployer));
            console.log("KineticProphecyBridge deployed:", propBridge);
        }

        // ── 1. Resolve / deploy USDC ─────────────────────────────────
        address usdcAddr  = vm.envOr("SOMNIA_USDC", address(0));
        if (usdcAddr == address(0)) {
            require(isTestnet, "mainnet must supply SOMNIA_USDC");
            MockUSDC mock = new MockUSDC();
            mock.mint(deployer, 1_000_000e6);   // 1M mUSDC for the deployer
            usdcAddr = address(mock);
            console.log("MockUSDC deployed (testnet):", usdcAddr);
        }

        // ── 2. Deploy executor ───────────────────────────────────────
        PredictionCardLiFiExecutor executor = new PredictionCardLiFiExecutor(
            cardExec, propBridge, usdcAddr, minStake, deployer
        );
        console.log("PredictionCardLiFiExecutor:", address(executor));

        // ── 3. Resolve / deploy LiFi destination caller ──────────────
        address lifiCaller = vm.envOr("LIFI_DESTINATION_CALLER", address(0));
        if (lifiCaller == address(0)) {
            require(isTestnet, "mainnet must supply LIFI_DESTINATION_CALLER");
            MockLiFiCaller mockCaller = new MockLiFiCaller(address(executor), usdcAddr, deployer);
            // Pre-fund the mock caller with 10K mUSDC for simulated deliveries
            MockUSDC(usdcAddr).mint(address(mockCaller), 10_000e6);
            lifiCaller = address(mockCaller);
            console.log("MockLiFiCaller deployed (testnet):", lifiCaller);
        }

        // ── 4. Three wirings ─────────────────────────────────────────
        SomniaCardExecutor(payable(cardExec)).setDelegatedExecutor(address(executor), true);
        // setBinder is idempotent + harmless even if v3 doesn't bind today;
        // keeps surface ready for v3.1 multi-card batched binding.
        try KineticProphecyBridge(propBridge).setBinder(address(executor), true) {}
        catch { console.log("setBinder skipped (deployer != bridge owner)"); }
        executor.setAllowedLifiCaller(lifiCaller, true);

        vm.stopBroadcast();

        // ── 5. Summary ───────────────────────────────────────────────
        console.log("=== Kinetic v3 deploy summary ===");
        console.log("network:           ", net);
        console.log("USDC:              ", usdcAddr);
        console.log("SomniaCardExecutor:", cardExec);
        console.log("KineticProphBridge:", propBridge);
        console.log("PredCardLiFiExec:  ", address(executor));
        console.log("LiFi caller:       ", lifiCaller);
        console.log("min stake usdc:    ", minStake);
        console.log("Append to contracts/deployments/<chainId>.json:");
        console.log('  "MockUSDC":                       "%s",', usdcAddr);
        console.log('  "SomniaCardExecutor":             "%s",', cardExec);
        console.log('  "KineticProphecyBridge":          "%s",', propBridge);
        console.log('  "PredictionCardLiFiExecutor":     "%s",', address(executor));
        console.log('  "MockLiFiCaller":                 "%s"',  lifiCaller);
    }
}
