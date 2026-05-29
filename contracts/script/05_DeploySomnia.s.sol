// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {SignalRegistry} from "../src/SignalRegistry.sol";
import {ConvictionEngine} from "../src/ConvictionEngine.sol";
import {ProofOfAlpha} from "../src/ProofOfAlpha.sol";
import {RewardEngine} from "../src/RewardEngine.sol";
import {SessionVault} from "../src/SessionVault.sol";
import {SignalPaymentGateway} from "../src/SignalPaymentGateway.sol";
import {SomniaOracleAdapter} from "../src/SomniaOracleAdapter.sol";
import {SomniaSignalAgent} from "../src/SomniaSignalAgent.sol";
import {SomniaCardExecutor} from "../src/SomniaCardExecutor.sol";
import {SomniaAgentMarket} from "../src/SomniaAgentMarket.sol";

/// @title 05_DeploySomnia — deploy full Kinetic stack + Somnia-native agents to chain 50312
/// @notice Env vars:
///         PRIVATE_KEY                — deployer key
///         SOMNIA_AGENTS_PLATFORM     — defaults 0x037Bb9...6776
///         JSON_API_AGENT_ID          — Somnia JSON API agent id
///         LLM_AGENT_ID               — Somnia LLM Inference agent id
///         LIFI_ROUTER (optional)     — whitelisted as agent target if set; else MockUSDC used as a placeholder
///         AGENT_MARKET_PRICE (opt)   — default 0.5 STT
///         Usage: forge script script/05_DeploySomnia.s.sol --rpc-url somnia_testnet --broadcast --via-ir
contract DeploySomnia is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(pk);
        address platform = vm.envOr("SOMNIA_AGENTS_PLATFORM", address(0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776));
        uint256 jsonAgentId = vm.envOr("JSON_API_AGENT_ID", uint256(1));
        uint256 llmAgentId = vm.envOr("LLM_AGENT_ID", uint256(2));
        uint256 marketPrice = vm.envOr("AGENT_MARKET_PRICE", uint256(0.5 ether));

        vm.startBroadcast(pk);

        // 1. Payment token (clean ERC20, no Initia precompile deps)
        MockUSDC mockSTT = new MockUSDC();
        mockSTT.mint(deployer, 1_000_000e6);

        // 2. Core contracts (unchanged Solidity, EVM-compatible)
        SignalRegistry registry = new SignalRegistry();
        ConvictionEngine conviction = new ConvictionEngine();
        ProofOfAlpha proofOfAlpha = new ProofOfAlpha();
        RewardEngine rewards = new RewardEngine(address(mockSTT));
        SessionVault vault = new SessionVault(address(mockSTT), deployer);
        SignalPaymentGateway gateway = new SignalPaymentGateway();

        // 3. Somnia-native agents
        SomniaOracleAdapter oracle = new SomniaOracleAdapter(platform, jsonAgentId, deployer);
        SomniaSignalAgent signalAgent = new SomniaSignalAgent(platform, llmAgentId, deployer);

        // 4. Agentathon additions: executor + B2B market.
        SomniaCardExecutor executor = new SomniaCardExecutor(
            address(signalAgent),
            address(oracle),
            address(conviction),
            address(proofOfAlpha),
            deployer
        );
        SomniaAgentMarket market = new SomniaAgentMarket(
            address(signalAgent),
            marketPrice,
            deployer, // treasury
            deployer
        );

        // 5. Wire cross-references
        registry.setAuthorizedAgent(deployer, true);
        // Executor must be allowed to commit + resolve convictions and mint tiers.
        conviction.setAuthorizedResolver(address(executor), true);
        proofOfAlpha.setAuthorizedMinter(address(executor), true);
        // Whitelist a default agent target. If LIFI_ROUTER not provided, fall back to
        // MockUSDC as a placeholder so end-to-end demo runs without depending on
        // third-party launch timing. Swap to LI.FI via setAllowedTarget post-deploy.
        address routerWhitelist = vm.envOr("LIFI_ROUTER", address(mockSTT));
        executor.setAllowedTarget(routerWhitelist, true);

        vm.stopBroadcast();

        // 6. Write deployments JSON
        string memory root = "deploy";
        vm.serializeUint(root, "chainId", block.chainid);
        vm.serializeAddress(root, "MockSTT", address(mockSTT));
        vm.serializeAddress(root, "SignalRegistry", address(registry));
        vm.serializeAddress(root, "ConvictionEngine", address(conviction));
        vm.serializeAddress(root, "ProofOfAlpha", address(proofOfAlpha));
        vm.serializeAddress(root, "RewardEngine", address(rewards));
        vm.serializeAddress(root, "SessionVault", address(vault));
        vm.serializeAddress(root, "SignalPaymentGateway", address(gateway));
        vm.serializeAddress(root, "SomniaOracleAdapter", address(oracle));
        vm.serializeAddress(root, "SomniaSignalAgent", address(signalAgent));
        vm.serializeAddress(root, "SomniaCardExecutor", address(executor));
        string memory json = vm.serializeAddress(root, "SomniaAgentMarket", address(market));
        vm.writeJson(json, string.concat("deployments/", vm.toString(block.chainid), ".json"));

        console2.log("\n=== SOMNIA DEPLOYMENT ===");
        console2.log("MockSTT:             ", address(mockSTT));
        console2.log("SignalRegistry:      ", address(registry));
        console2.log("ConvictionEngine:    ", address(conviction));
        console2.log("ProofOfAlpha:        ", address(proofOfAlpha));
        console2.log("RewardEngine:        ", address(rewards));
        console2.log("SessionVault:        ", address(vault));
        console2.log("SignalPaymentGateway:", address(gateway));
        console2.log("SomniaOracleAdapter: ", address(oracle));
        console2.log("SomniaSignalAgent:   ", address(signalAgent));
        console2.log("SomniaCardExecutor:  ", address(executor));
        console2.log("SomniaAgentMarket:   ", address(market));
        console2.log("Whitelisted target:  ", routerWhitelist);
    }
}
