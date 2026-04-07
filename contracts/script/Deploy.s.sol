// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/SignalRegistry.sol";
import "../src/MockIUSD.sol";
import "../src/SessionVault.sol";
import "../src/SignalPaymentGateway.sol";

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
        console.log("SessionVault:", address(vault));

        // Authorize deployer as operator (backend wallet)
        vault.setAuthorizedOperator(deployer, true);
        console.log("Operator authorized:", deployer);

        SignalPaymentGateway gateway = new SignalPaymentGateway();
        console.log("SignalPaymentGateway:", address(gateway));

        vm.stopBroadcast();
    }
}
