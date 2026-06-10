// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable}          from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard}  from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20}           from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}        from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {SomniaCardExecutor}    from "./SomniaCardExecutor.sol";
import {KineticProphecyBridge} from "./KineticProphecyBridge.sol";

/// @title PredictionCardLiFiExecutor — atomic LiFi calls-on-delivery handler
/// @notice Receives `(usdc + somi-gas + calldata)` from a LiFi destination
///         caller on Somnia, then atomically:
///           1. validates the prophecy market is bound on KineticProphecyBridge
///           2. fires SomniaCardExecutor.batchExecuteFromQueueFor (validator-
///              consensus AI verdict, attributed to originalUser)
///           3. emits SwipeCompleted so the off-chain relay can correlate
///              `lifiOriginTxHash` -> verdictId -> cardHash for the user.
///
/// SOLID:
///   - SRP: validate-then-dispatch. Routing/whitelist policy lives downstream.
///   - OCP: caller allowlist + min-stake floor are owner-mutable; new callers
///          (mainnet LiFi caller, Solver Marketplace, etc.) = one tx.
///   - DIP: depends on `batchExecuteFromQueueFor` + `prophecyToCardHash`
///          interfaces — both immutable selectors on existing contracts.
///
/// Idempotency: the first 32 bytes of `lifiData` carry the user's origin-chain
/// tx hash. We reject duplicates via `processedOriginTx[originTxHash]`. The
/// flag is set BEFORE external calls (CEI), so a reentrant retry can't
/// double-swipe. On revert the entire tx unwinds — flag included — and LiFi
/// can retry safely.
///
/// Security:
///   - Reentrancy-guarded.
///   - Allowlisted msg.sender only (LiFi destination caller registry).
///   - 4096-byte lifiData cap (DoS antibody, mirrors SomniaCardExecutor).
///   - Stake floor (DoS antibody for tiny-amount griefing). Env-driven so
///     testnet ($0.10) and mainnet ($1.00) share one bytecode.
///   - No `delegatecall`, no `selfdestruct`. Owner has a `withdrawStuck`
///     escape hatch for accidental token sends only.
contract PredictionCardLiFiExecutor is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    SomniaCardExecutor    public immutable CARD_EXECUTOR;
    KineticProphecyBridge public immutable PROPHECY_BRIDGE;
    IERC20                public immutable USDC;

    /// @notice DoS antibody. Owner-mutable so testnet/mainnet share bytecode.
    uint256 public minSwipeStakeUsdc;

    /// @notice Calldata size cap. Mirrors SomniaCardExecutor.MAX_AGENT_CALLDATA.
    uint256 public constant MAX_LIFI_DATA_SIZE = 4_096;

    /// @notice LiFi-side caller allowlist (registry pattern, owner-mutable).
    mapping(address => bool) public allowedLifiCallers;

    /// @notice Idempotency: lifiOriginTxHash -> consumed.
    mapping(bytes32 => bool) public processedOriginTx;

    event LifiCallerWhitelisted(address indexed caller, bool allowed);
    event MinSwipeStakeChanged(uint256 oldAmount, uint256 newAmount);
    event SwipeCompleted(
        address indexed user,
        uint256 indexed prophecyMarketId,
        bytes32 cardHash,
        uint256 verdictId,
        bytes32 lifiOriginTxHash
    );
    event StuckTokenWithdrawn(address indexed token, address indexed to, uint256 amount);

    error ZeroAddress();
    error NotLifiCaller();
    error LifiDataTooLarge();
    error LifiDataTooShort();
    error InvalidAmount();
    error StakeBelowMinimum();
    error AlreadyProcessed();
    error UnknownProphecyMarket();
    error EmptyVerdict();

    constructor(
        address cardExecutor,
        address prophecyBridge,
        address usdc,
        uint256 initialMinStakeUsdc,
        address owner_
    ) Ownable(owner_) {
        if (cardExecutor   == address(0)) revert ZeroAddress();
        if (prophecyBridge == address(0)) revert ZeroAddress();
        if (usdc           == address(0)) revert ZeroAddress();
        if (owner_         == address(0)) revert ZeroAddress();
        if (initialMinStakeUsdc == 0)     revert InvalidAmount();
        CARD_EXECUTOR     = SomniaCardExecutor(payable(cardExecutor));
        PROPHECY_BRIDGE   = KineticProphecyBridge(prophecyBridge);
        USDC              = IERC20(usdc);
        minSwipeStakeUsdc = initialMinStakeUsdc;
    }

    // ── Owner setters ───────────────────────────────────────────────

    function setAllowedLifiCaller(address caller, bool allowed) external onlyOwner {
        if (caller == address(0)) revert ZeroAddress();
        allowedLifiCallers[caller] = allowed;
        emit LifiCallerWhitelisted(caller, allowed);
    }

    function setMinSwipeStakeUsdc(uint256 amount) external onlyOwner {
        if (amount == 0) revert InvalidAmount();
        emit MinSwipeStakeChanged(minSwipeStakeUsdc, amount);
        minSwipeStakeUsdc = amount;
    }

    /// @notice Defensive escape hatch for tokens accidentally sent to the
    ///         executor (this contract should never hold tokens at rest).
    function withdrawStuck(IERC20 token, address to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        token.safeTransfer(to, amount);
        emit StuckTokenWithdrawn(address(token), to, amount);
    }

    // ── Main execute path ───────────────────────────────────────────

    /// @notice Called by the LiFi destination caller after origin-chain Compact-lock
    ///         delivers funds + this calldata to Somnia.
    /// @param  lifiData First 32 bytes MUST be the user's origin-chain tx hash
    ///                  (idempotency key). Tail is opaque LiFi metadata.
    /// @param  prophecyMarketId The prophecy.social market id (must be bound on bridge).
    /// @param  symbol           Token symbol for the swipe context (e.g. "BTC").
    /// @param  context          Free-form context for the LLM verdict.
    /// @param  swipeStakeUsdc   USDC amount the user is staking (6-dec).
    /// @param  originalUser     User on the origin chain (for attribution).
    function executeFromLiFi(
        bytes  calldata lifiData,
        uint256          prophecyMarketId,
        string calldata symbol,
        string calldata context,
        uint256          swipeStakeUsdc,
        address          originalUser
    ) external payable nonReentrant {
        // ── ACL + bounds ───────────────────────────────────────────
        if (!allowedLifiCallers[msg.sender]) revert NotLifiCaller();
        if (lifiData.length < 32)            revert LifiDataTooShort();
        if (lifiData.length > MAX_LIFI_DATA_SIZE) revert LifiDataTooLarge();
        if (originalUser == address(0))      revert ZeroAddress();
        if (swipeStakeUsdc < minSwipeStakeUsdc) revert StakeBelowMinimum();

        // ── Idempotency (CEI: write before external calls) ─────────
        bytes32 originTxHash = bytes32(lifiData[:32]);
        if (processedOriginTx[originTxHash]) revert AlreadyProcessed();
        processedOriginTx[originTxHash] = true;

        // ── Validate prophecy binding pre-existence ────────────────
        // The card-gen pipeline binds the market at generation time; if
        // it isn't bound yet, we don't have a card to swipe on.
        if (PROPHECY_BRIDGE.prophecyToCardHash(prophecyMarketId) == bytes32(0))
            revert UnknownProphecyMarket();

        // ── Pull staked USDC from the LiFi solver (origin user funds) ──
        USDC.safeTransferFrom(msg.sender, address(this), swipeStakeUsdc);

        // ── Trigger validator-consensus AI verdict ─────────────────
        SomniaCardExecutor.Swipe[] memory queue = new SomniaCardExecutor.Swipe[](1);
        queue[0] = SomniaCardExecutor.Swipe({symbol: symbol, context: context});

        uint256[] memory verdictIds = CARD_EXECUTOR.batchExecuteFromQueueFor{value: msg.value}(
            originalUser, queue
        );
        if (verdictIds.length == 0) revert EmptyVerdict();
        uint256 verdictId = verdictIds[0];

        // The cardHash matches what `SomniaCardExecutor.executeAgentResult`
        // will derive once the LLM verdict lands. Off-chain relays use this
        // value to correlate `SwipeCompleted` -> ConvictionEngine state.
        bytes32 cardHash = keccak256(abi.encode(verdictId, symbol, originalUser));

        // ── Forward staked USDC into the card-executor for downstream use ──
        // Approve via SafeERC20.forceApprove so re-runs can't desync allowances.
        USDC.forceApprove(address(CARD_EXECUTOR), swipeStakeUsdc);

        emit SwipeCompleted(originalUser, prophecyMarketId, cardHash, verdictId, originTxHash);
    }

    receive() external payable {}
}
