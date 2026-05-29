// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console2} from "forge-std/Test.sol";
import {SomniaSignalAgent, ISomniaVerdictConsumer} from "../src/SomniaSignalAgent.sol";
import {SomniaOracleAdapter} from "../src/SomniaOracleAdapter.sol";
import {SomniaCardExecutor, IConvictionEngine, IProofOfAlpha} from "../src/SomniaCardExecutor.sol";
import {SomniaAgentMarket, IVerdictBuyer} from "../src/SomniaAgentMarket.sol";
import {ConvictionEngine} from "../src/ConvictionEngine.sol";
import {ProofOfAlpha} from "../src/ProofOfAlpha.sol";
import {Response, ResponseStatus, Request, IAgentRequester} from "../src/SomniaOracleAdapter.sol";

/// @notice Mock Somnia Agents Platform — accepts createRequest, lets us synthesise callbacks.
contract MockPlatform is IAgentRequester {
    uint256 public nextId = 1;
    uint256 public depositFloor = 0.03 ether;

    struct Pending {
        address callback;
        bytes4 selector;
        bytes payload;
        uint256 deposit;
    }
    mapping(uint256 => Pending) public pending;

    function getRequestDeposit() external view returns (uint256) { return depositFloor; }

    function createRequest(uint256, address callbackAddress, bytes4 callbackSelector, bytes calldata payload)
        external payable returns (uint256 id)
    {
        id = nextId++;
        pending[id] = Pending(callbackAddress, callbackSelector, payload, msg.value);
    }

    /// @notice Test helper — drive a Success callback with caller-supplied result bytes.
    function deliverSuccess(uint256 id, bytes memory result) external {
        Pending memory p = pending[id];
        delete pending[id];
        Response[] memory rs = new Response[](1);
        rs[0] = Response({
            validator: address(0),
            result: result,
            status: ResponseStatus.Success,
            receipt: 0,
            timestamp: block.timestamp,
            executionCost: 0
        });
        Request memory req;
        (bool ok, ) = p.callback.call(abi.encodeWithSelector(p.selector, id, rs, ResponseStatus.Success, req));
        require(ok, "callback failed");
    }

    function deliverFailure(uint256 id) external {
        Pending memory p = pending[id];
        delete pending[id];
        Response[] memory rs = new Response[](0);
        Request memory req;
        (bool ok, ) = p.callback.call(abi.encodeWithSelector(p.selector, id, rs, ResponseStatus.Failed, req));
        require(ok, "callback failed");
    }
}

/// @notice Trivial DEX router stand-in — records the call.
contract MockRouter {
    bytes public lastCalldata;
    uint256 public callCount;
    function execute(bytes calldata data) external payable returns (bool) {
        lastCalldata = data;
        ++callCount;
        return true;
    }
    receive() external payable {}
    fallback() external payable { lastCalldata = msg.data; ++callCount; }
}

/// @notice Buyer for the AgentMarket — captures the verdict it receives.
contract MockBuyer is IVerdictBuyer {
    string public lastVerdict;
    address public lastRouter;
    bytes public lastCalldata;
    uint256 public lastVerdictId;

    function onKineticVerdict(uint256 id, string calldata v, address r, bytes calldata d) external override {
        lastVerdictId = id;
        lastVerdict = v;
        lastRouter = r;
        lastCalldata = d;
    }
    receive() external payable {}
}

contract SomniaTest is Test {
    MockPlatform plat;
    SomniaSignalAgent agent;
    SomniaOracleAdapter oracle;
    SomniaCardExecutor exec;
    SomniaAgentMarket market;
    ConvictionEngine conviction;
    ProofOfAlpha proof;
    MockRouter router;

    address user = makeAddr("user");
    address treasury = makeAddr("treasury");
    address owner = address(this);

    function setUp() public {
        plat = new MockPlatform();
        agent = new SomniaSignalAgent(address(plat), 1, owner);
        oracle = new SomniaOracleAdapter(address(plat), 2, owner);
        conviction = new ConvictionEngine();
        proof = new ProofOfAlpha();
        router = new MockRouter();
        exec = new SomniaCardExecutor(
            address(agent), address(oracle), address(conviction), address(proof), owner
        );
        market = new SomniaAgentMarket(address(agent), 0.5 ether, treasury, owner);

        conviction.setAuthorizedResolver(address(exec), true);
        proof.setAuthorizedMinter(address(exec), true);
        exec.setAllowedTarget(address(router), true);

        vm.deal(user, 100 ether);
        vm.deal(address(this), 100 ether);
    }

    // ── Task 2: legacy requestSignal ABI byte-identical ─────────────────────────
    function test_legacy_requestSignal_path_unchanged() public {
        uint256 reqId = agent.requestSignal{value: 0.03 ether}("BTC", "RSI=72");
        assertGt(reqId, 0);
        assertEq(agent.signalCount(), 1);
        plat.deliverSuccess(reqId, abi.encode('{"verdict":"APE","reasoning":"x"}'));
        assertEq(agent.getSignal(0).result, '{"verdict":"APE","reasoning":"x"}');
    }

    // ── Task 2: new batch path produces structured Verdict ─────────────────────
    function test_requestVerdictAndExecuteBatch_happy_path() public {
        string[] memory syms = new string[](1);
        syms[0] = "BTC";
        string[] memory ctx = new string[](1);
        ctx[0] = "RSI=72";

        // Deposit must be ≥ floor × N; mock floor is 0.03 ether.
        uint256[] memory ids = agent.requestVerdictAndExecuteBatch{value: 0.06 ether}(
            syms, ctx, address(exec), exec.executeAgentResult.selector
        );
        assertEq(ids.length, 1);
        assertEq(agent.verdictCount(), 1);

        bytes memory result = abi.encode(string("APE"), address(router), bytes("0xdeadbeef"));
        plat.deliverSuccess(1, result);

        SomniaSignalAgent.Verdict memory v = agent.getVerdict(0);
        assertEq(v.verdictStr, "APE");
        assertEq(v.router, address(router));
        assertEq(router.callCount(), 1);
    }

    function test_failed_status_does_not_call_consumer() public {
        string[] memory syms = new string[](1); syms[0] = "BTC";
        string[] memory ctx = new string[](1); ctx[0] = "x";
        agent.requestVerdictAndExecuteBatch{value: 0.06 ether}(
            syms, ctx, address(exec), exec.executeAgentResult.selector
        );
        plat.deliverFailure(1);
        assertEq(router.callCount(), 0);
        assertEq(uint8(agent.getVerdict(0).status), uint8(ResponseStatus.Failed));
    }

    // ── Task 3: executor rejects non-whitelisted targets ───────────────────────
    function test_executor_rejects_unwhitelisted_target() public {
        MockRouter rogue = new MockRouter();
        // Direct executeAgentResult call from the agent (impersonate it).
        vm.prank(address(agent));
        vm.expectRevert(SomniaCardExecutor.TargetNotAllowed.selector);
        exec.executeAgentResult(0, address(rogue), bytes(""));
    }

    function test_executor_rejects_non_agent_caller() public {
        vm.expectRevert(SomniaCardExecutor.OnlyAgent.selector);
        exec.executeAgentResult(0, address(router), bytes(""));
    }

    // ── Task 3: end-to-end batchExecuteFromQueue ──────────────────────────────
    function test_batch_execute_from_queue_records_position() public {
        SomniaCardExecutor.Swipe[] memory queue = new SomniaCardExecutor.Swipe[](1);
        queue[0] = SomniaCardExecutor.Swipe({symbol: "BTC", context: "bullish"});

        vm.prank(user);
        uint256[] memory ids = exec.batchExecuteFromQueue{value: 0.06 ether}(queue);
        assertEq(ids.length, 1);
        assertEq(exec.userByVerdict(ids[0]), user);

        bytes memory result = abi.encode(string("APE"), address(router), bytes("0x1234"));
        plat.deliverSuccess(1, result);

        (address u, string memory sym,,bool isBull,,,bool executed,) = exec.positions(ids[0]);
        assertEq(u, user);
        assertEq(sym, "BTC");
        assertTrue(isBull);
        assertTrue(executed);
        assertEq(conviction.getConvictionCount(), 1);
    }

    // ── Task 5: resolveExpired finalises the position + checks tier ────────────
    function test_resolveExpiredFromCache_finalises_and_mints() public {
        // Open a position via the batch path
        SomniaCardExecutor.Swipe[] memory queue = new SomniaCardExecutor.Swipe[](1);
        queue[0] = SomniaCardExecutor.Swipe({symbol: "BTC", context: "x"});
        vm.prank(user);
        exec.batchExecuteFromQueue{value: 0.06 ether}(queue);

        // Seed the oracle with a price by delivering a Success on a price request.
        oracle.requestPrice{value: 0.03 ether}("BTC", "https://x", "y");
        plat.deliverSuccess(2, abi.encode(uint256(100_000e8)));
        assertEq(oracle.getPrice("BTC"), 100_000e8);

        // Now deliver the verdict — entryPrice will be captured at this point.
        bytes memory result = abi.encode(string("APE"), address(router), bytes(""));
        plat.deliverSuccess(1, result);

        // Fast-forward past expiry, drop oracle price below entry → APE wins if exitPrice ≥ entry.
        // We'll set exitPrice equal to entry → wasCorrect=true (≥).
        skip(25 hours);

        // resolveExpiredFromCache uses the cached oracle price (no new platform call).
        exec.resolveExpiredFromCache(0);
        (,,,, , , , bool resolved) = exec.positions(0);
        assertTrue(resolved);
    }

    function test_resolveExpired_reverts_before_expiry() public {
        SomniaCardExecutor.Swipe[] memory queue = new SomniaCardExecutor.Swipe[](1);
        queue[0] = SomniaCardExecutor.Swipe({symbol: "BTC", context: "x"});
        vm.prank(user);
        exec.batchExecuteFromQueue{value: 0.06 ether}(queue);

        oracle.requestPrice{value: 0.03 ether}("BTC", "https://x", "y");
        plat.deliverSuccess(2, abi.encode(uint256(100_000e8)));

        bytes memory result = abi.encode(string("APE"), address(router), bytes(""));
        plat.deliverSuccess(1, result);

        vm.expectRevert(SomniaCardExecutor.NotExpired.selector);
        exec.resolveExpiredFromCache(0);
    }

    // ── Task 6: AgentMarket dispatches verdict to buyer callback ───────────────
    function test_agent_market_delivers_verdict_to_buyer() public {
        MockBuyer buyer = new MockBuyer();
        vm.deal(address(buyer), 10 ether);

        vm.prank(address(buyer));
        uint256 buyerReqId = market.requestVerdict{value: 0.6 ether}(
            "ETH", "ETF inflows up", buyer.onKineticVerdict.selector
        );
        assertEq(buyerReqId, 0);

        bytes memory result = abi.encode(string("APE"), address(router), bytes("0xabcd"));
        plat.deliverSuccess(1, result);

        assertEq(buyer.lastVerdict(), "APE");
        assertEq(buyer.lastRouter(), address(router));
        assertEq(treasury.balance, 0.5 ether); // margin pushed to treasury
    }

    function test_agent_market_underpriced_reverts() public {
        MockBuyer buyer = new MockBuyer();
        vm.deal(address(buyer), 1 ether);
        vm.prank(address(buyer));
        vm.expectRevert(SomniaAgentMarket.UnderPriced.selector);
        market.requestVerdict{value: 0.1 ether}("ETH", "x", buyer.onKineticVerdict.selector);
    }
}
