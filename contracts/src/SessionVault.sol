// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

contract SessionVault is Ownable {
    using SafeERC20 for IERC20;
    using ECDSA for bytes32;
    using MessageHashUtils for bytes32;

    struct Session {
        address depositor;
        uint256 depositAmount;
        uint256 remainingBalance;
        uint256 totalRedeemed;
        uint256 voucherCount;
        uint256 createdAt;
        uint256 expiresAt;
        bool active;
    }

    struct Voucher {
        uint256 sessionId;
        uint256 amount;
        uint256 nonce;
        string serviceId;
        bytes signature;
    }

    IERC20 public immutable iUSD;
    Session[] public sessions;
    mapping(address => uint256[]) public userSessions;
    mapping(uint256 => mapping(uint256 => bool)) public redeemedNonces;
    mapping(address => bool) public authorizedOperators;
    address public treasury;
    uint256 public platformFeeBps = 100;

    event SessionCreated(uint256 indexed sessionId, address indexed depositor, uint256 amount, uint256 expiresAt);
    event VoucherRedeemed(uint256 indexed sessionId, uint256 nonce, uint256 amount, string serviceId);
    event SessionClosed(uint256 indexed sessionId, uint256 refunded, uint256 totalRedeemed);
    event BatchSettled(uint256 totalAmount, uint256 platformFee, uint256 operatorAmount);

    constructor(address _iUSD, address _treasury) Ownable(msg.sender) {
        iUSD = IERC20(_iUSD);
        treasury = _treasury;
    }

    function createSession(uint256 amount, uint256 durationSeconds) external returns (uint256 sessionId) {
        require(amount > 0, "Amount must be > 0");
        require(durationSeconds >= 3600, "Min duration: 1 hour");
        require(durationSeconds <= 30 days, "Max duration: 30 days");
        iUSD.safeTransferFrom(msg.sender, address(this), amount);
        sessionId = sessions.length;
        sessions.push(Session(msg.sender, amount, amount, 0, 0, block.timestamp, block.timestamp + durationSeconds, true));
        userSessions[msg.sender].push(sessionId);
        emit SessionCreated(sessionId, msg.sender, amount, block.timestamp + durationSeconds);
    }

    function topUpSession(uint256 sessionId, uint256 amount) external {
        Session storage s = sessions[sessionId];
        require(s.depositor == msg.sender, "Not session owner");
        require(s.active && block.timestamp < s.expiresAt, "Session not active");
        iUSD.safeTransferFrom(msg.sender, address(this), amount);
        s.depositAmount += amount;
        s.remainingBalance += amount;
    }

    function closeSession(uint256 sessionId) external {
        Session storage s = sessions[sessionId];
        require(s.depositor == msg.sender, "Not session owner");
        require(s.active, "Session not active");
        s.active = false;
        uint256 refund = s.remainingBalance;
        s.remainingBalance = 0;
        if (refund > 0) iUSD.safeTransfer(msg.sender, refund);
        emit SessionClosed(sessionId, refund, s.totalRedeemed);
    }

    function redeemVoucher(Voucher calldata v) external returns (bool) {
        require(authorizedOperators[msg.sender], "Not authorized operator");
        Session storage s = sessions[v.sessionId];
        require(s.active && block.timestamp < s.expiresAt, "Session not active");
        require(s.remainingBalance >= v.amount, "Insufficient balance");
        require(!redeemedNonces[v.sessionId][v.nonce], "Nonce already redeemed");
        bytes32 messageHash = keccak256(abi.encodePacked(v.sessionId, v.amount, v.nonce, v.serviceId));
        address signer = messageHash.toEthSignedMessageHash().recover(v.signature);
        require(signer == s.depositor, "Invalid signature");
        redeemedNonces[v.sessionId][v.nonce] = true;
        s.remainingBalance -= v.amount;
        s.totalRedeemed += v.amount;
        s.voucherCount += 1;
        emit VoucherRedeemed(v.sessionId, v.nonce, v.amount, v.serviceId);
        return true;
    }

    function redeemBatch(Voucher[] calldata vouchers) external returns (uint256 redeemed) {
        require(authorizedOperators[msg.sender], "Not authorized operator");
        for (uint256 i = 0; i < vouchers.length; i++) {
            Session storage s = sessions[vouchers[i].sessionId];
            if (!s.active || block.timestamp >= s.expiresAt) continue;
            if (s.remainingBalance < vouchers[i].amount) continue;
            if (redeemedNonces[vouchers[i].sessionId][vouchers[i].nonce]) continue;
            bytes32 messageHash = keccak256(abi.encodePacked(vouchers[i].sessionId, vouchers[i].amount, vouchers[i].nonce, vouchers[i].serviceId));
            address signer = messageHash.toEthSignedMessageHash().recover(vouchers[i].signature);
            if (signer != s.depositor) continue;
            redeemedNonces[vouchers[i].sessionId][vouchers[i].nonce] = true;
            s.remainingBalance -= vouchers[i].amount;
            s.totalRedeemed += vouchers[i].amount;
            s.voucherCount += 1;
            redeemed++;
            emit VoucherRedeemed(vouchers[i].sessionId, vouchers[i].nonce, vouchers[i].amount, vouchers[i].serviceId);
        }
    }

    function settle(uint256 amount) external onlyOwner {
        uint256 available = iUSD.balanceOf(address(this));
        uint256 reserved = _totalReserved();
        uint256 settleable = available > reserved ? available - reserved : 0;
        require(amount <= settleable, "Amount exceeds settleable");
        uint256 fee = (amount * platformFeeBps) / 10000;
        if (fee > 0) iUSD.safeTransfer(treasury, fee);
        if (amount - fee > 0) iUSD.safeTransfer(owner(), amount - fee);
        emit BatchSettled(amount, fee, amount - fee);
    }

    function getSession(uint256 sessionId) external view returns (Session memory) { return sessions[sessionId]; }
    function getSessionCount() external view returns (uint256) { return sessions.length; }
    function getUserSessions(address user) external view returns (uint256[] memory) { return userSessions[user]; }

    function isVoucherValid(Voucher calldata v) external view returns (bool) {
        if (v.sessionId >= sessions.length) return false;
        Session storage s = sessions[v.sessionId];
        if (!s.active || block.timestamp >= s.expiresAt) return false;
        if (s.remainingBalance < v.amount || redeemedNonces[v.sessionId][v.nonce]) return false;
        bytes32 messageHash = keccak256(abi.encodePacked(v.sessionId, v.amount, v.nonce, v.serviceId));
        return messageHash.toEthSignedMessageHash().recover(v.signature) == s.depositor;
    }

    function setAuthorizedOperator(address operator, bool authorized) external onlyOwner { authorizedOperators[operator] = authorized; }
    function setTreasury(address _treasury) external onlyOwner { treasury = _treasury; }
    function setPlatformFee(uint256 _feeBps) external onlyOwner { require(_feeBps <= 500, "Fee too high"); platformFeeBps = _feeBps; }

    function _totalReserved() internal view returns (uint256 total) {
        for (uint256 i = 0; i < sessions.length; i++) {
            if (sessions[i].active && block.timestamp < sessions[i].expiresAt) total += sessions[i].remainingBalance;
        }
    }
}
