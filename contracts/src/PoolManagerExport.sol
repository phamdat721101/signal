// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// Re-export PoolManager from v4-core so `forge create src/...` works
// (forge create has a bug with lib/ paths + --rpc-url flag)
import {PoolManager} from "v4-core/src/PoolManager.sol";
