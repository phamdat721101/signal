// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/SignalRegistry.sol";
import "../src/MockIUSD.sol";
import "../src/SessionVault.sol";
import "../src/SignalPaymentGateway.sol";
import "../src/RewardEngine.sol";
import "../src/ProofOfAlpha.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerKey);
        vm.startBroadcast(deployerKey);

        SignalRegistry registry = new SignalRegistry();
        console.log("SignalRegistry:", address(registry));

        MockIUSD iusd = new MockIUSD();
        console.log("MockIUSD:", address(iusd));

        SessionVault vault = new SessionVault(address(iusd), deployer);
        vault.setAuthorizedOperator(deployer, true);
        console.log("SessionVault:", address(vault));

        SignalPaymentGateway gateway = new SignalPaymentGateway();
        console.log("SignalPaymentGateway:", address(gateway));

        RewardEngine rewards = new RewardEngine(address(iusd));
        rewards.setAuthorizedCaller(deployer, true);
        console.log("RewardEngine:", address(rewards));

        ProofOfAlpha alpha = new ProofOfAlpha();
        alpha.setAuthorizedMinter(deployer, true);
        console.log("ProofOfAlpha:", address(alpha));

        // Authorize backend as AI agent for signal publishing
        registry.setAuthorizedAgent(deployer, true);
        console.log("Deployer authorized as agent+operator+minter");

        vm.stopBroadcast();
    }
}
