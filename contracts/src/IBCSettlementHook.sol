// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "./CosmosUtils.sol";

/// @notice Minimal SessionVault surface this hook needs.
interface ISessionVault {
    function payFromSession(uint256 sessionId, uint256 amount, string calldata serviceId) external;
}

/// @title IBCSettlementHook — entrypoint for EVM IBC Hooks ICS-20 packets.
/// @notice Cosmos-chain users (Osmosis, Neutron, Initia L1, …) buy premium
///         reports by sending an ICS-20 transfer with an EVM-execution memo:
///         {"evm": {"contract": "0xHOOK", "method": "payReport",
///                   "args": ["sessionId", "reportId"]}}
///
///         The IBC Hooks module on evm-1 decodes the memo, verifies ACL, and
///         calls payReport(...) here. We sanity-check sanctions, then forward
///         to SessionVault.payFromSession with the report price.
///
///         Cross-chain E2E demo is deferred (governance-gated ACL on mainnet);
///         testnet ACL can be configured via deployer key per Initia docs.
contract IBCSettlementHook is Ownable, Pausable {
    ISessionVault public immutable sessionVault;

    mapping(string => uint256) public reportPrices;          // serviceId → wei
    mapping(address => bool)   public authorizedHookCallers; // IBC Hooks module addr (or test deployer)

    event ReportPaid(address indexed buyer, string reportId, uint256 amount, uint256 sessionId);
    event ReportRejected(address indexed buyer, string reportId, string reason);

    error NotAuthorized();
    error UnknownReport(string reportId);
    error BuyerSanctioned(address buyer);

    constructor(address sessionVaultAddr) Ownable(msg.sender) {
        require(sessionVaultAddr != address(0), "vault=0");
        sessionVault = ISessionVault(sessionVaultAddr);
    }

    /// @notice Called by EVM IBC Hooks module (or stub deployer key in tests).
    /// @dev    msg.sender at entry is the IBC Hooks module address; tx.origin
    ///         carries the bridged-token sender on some implementations. We
    ///         use authorizedHookCallers ACL to enforce the trust boundary.
    function payReport(uint256 sessionId, string calldata reportId)
        external whenNotPaused
    {
        if (!authorizedHookCallers[msg.sender] && msg.sender != owner()) revert NotAuthorized();

        // Sanctions check via ICosmos precompile (read-only, fail-open on precompile error).
        if (CosmosUtils.isAddressSanctioned(tx.origin)) {
            emit ReportRejected(tx.origin, reportId, "sanctioned");
            revert BuyerSanctioned(tx.origin);
        }

        uint256 price = reportPrices[reportId];
        if (price == 0) {
            emit ReportRejected(tx.origin, reportId, "unknown report");
            revert UnknownReport(reportId);
        }

        sessionVault.payFromSession(sessionId, price, reportId);
        emit ReportPaid(tx.origin, reportId, price, sessionId);
    }

    // ─── admin ──────────────────────────────────────────────────────────────

    function setReportPrice(string calldata reportId, uint256 priceWei) external onlyOwner {
        reportPrices[reportId] = priceWei;
    }

    function setAuthorizedHookCaller(address caller, bool authorized) external onlyOwner {
        authorizedHookCallers[caller] = authorized;
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }
}
