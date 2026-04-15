// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract RewardEngine is Ownable {
    using SafeERC20 for IERC20;

    struct UserStats {
        uint256 totalTrades;
        uint256 wins;
        uint256 currentStreak;
        uint256 bestStreak;
        uint256 totalRewards;
    }

    IERC20 public immutable rewardToken;
    mapping(address => UserStats) public stats;
    mapping(address => bool) public authorizedCallers;

    uint256 public winRewardBps = 300; // 3% rebate
    uint256 public streakBonus = 5;    // bonus per streak trade (in token units)

    event TradeResolved(address indexed user, bool wasProfit, uint256 reward);
    event RewardClaimed(address indexed user, uint256 amount);
    event StreakUpdated(address indexed user, uint256 streak);

    constructor(address _rewardToken) Ownable(msg.sender) {
        rewardToken = IERC20(_rewardToken);
    }

    modifier onlyAuthorized() {
        require(authorizedCallers[msg.sender] || msg.sender == owner(), "Not authorized");
        _;
    }

    function onTradeResolved(address user, bool wasProfit, uint256 tradeAmount) external onlyAuthorized {
        UserStats storage s = stats[user];
        s.totalTrades++;

        uint256 reward = 0;
        if (wasProfit) {
            s.wins++;
            s.currentStreak++;
            if (s.currentStreak > s.bestStreak) s.bestStreak = s.currentStreak;
            reward = (tradeAmount * winRewardBps) / 10000;
            reward += s.currentStreak * streakBonus * 1e18;
            s.totalRewards += reward;
            emit StreakUpdated(user, s.currentStreak);
        } else {
            s.currentStreak = 0;
        }

        emit TradeResolved(user, wasProfit, reward);
    }

    function claimRewards() external {
        uint256 amount = stats[msg.sender].totalRewards;
        require(amount > 0, "No rewards");
        stats[msg.sender].totalRewards = 0;
        rewardToken.safeTransfer(msg.sender, amount);
        emit RewardClaimed(msg.sender, amount);
    }

    function getStats(address user) external view returns (UserStats memory) {
        return stats[user];
    }

    function setAuthorizedCaller(address caller, bool authorized) external onlyOwner {
        authorizedCallers[caller] = authorized;
    }

    function setRewardParams(uint256 _winBps, uint256 _streakBonus) external onlyOwner {
        require(_winBps <= 1000, "Max 10%");
        winRewardBps = _winBps;
        streakBonus = _streakBonus;
    }
}
