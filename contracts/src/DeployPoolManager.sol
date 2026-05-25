// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {PoolManager} from "v4-core/src/PoolManager.sol";
contract DeployPoolManager {
    PoolManager public pm;
    constructor(address owner) { pm = new PoolManager(owner); }
}
