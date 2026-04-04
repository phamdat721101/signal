// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/SignalRegistry.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(deployerKey);

        SignalRegistry registry = new SignalRegistry();
        console.log("SignalRegistry deployed at:", address(registry));

        vm.stopBroadcast();
    }
}
