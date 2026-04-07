# Fix 402 Payment Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace off-chain voucher signing with on-chain `payFromSession` so the "Generate Signal" button works with InterwovenKit.

**Architecture:** Add `payFromSession` to SessionVault contract (depositor pays directly via `msg.sender`). Backend verifies payment by reading the tx receipt for a `ServicePaid` event instead of verifying a signed voucher. Frontend sends MsgCall to pay, then passes the txHash to the backend.

**Tech Stack:** Solidity 0.8.24 (Foundry), Python FastAPI (web3.py), React 19 + viem + InterwovenKit

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `contracts/src/SessionVault.sol` | Add `payFromSession` function + `ServicePaid` event |
| Create | `contracts/test/SessionVault.t.sol` | Tests for `payFromSession` |
| Modify | `backend/app/mpp_middleware.py` | Replace voucher verification with tx receipt verification |
| Modify | `backend/app/main.py` | Switch `X-PAYMENT` to `X-PAYMENT-TX` header in gated endpoints |
| Modify | `backend/app/session_vault_abi.json` | Updated ABI after contract rebuild |
| Modify | `frontend/src/hooks/useSession.ts` | Add session lookup + `payForService` |
| Modify | `frontend/src/pages/Dashboard.tsx` | Pay-then-generate flow + error handling fix |

---

### Task 1: Contract — Add `payFromSession` to SessionVault

**Files:**
- Modify: `contracts/src/SessionVault.sol:42-46` (add event after existing events)
- Modify: `contracts/src/SessionVault.sol:131` (add function after `getSession`)
- Create: `contracts/test/SessionVault.t.sol`

- [ ] **Step 1: Add `ServicePaid` event and `payFromSession` function**

In `contracts/src/SessionVault.sol`, add the event after line 45 (after `event BatchSettled`):

```solidity
    event ServicePaid(uint256 indexed sessionId, address indexed payer, uint256 amount, string serviceId);
```

Add the function after `getUserSessions` (after line 132):

```solidity
    function payFromSession(uint256 sessionId, uint256 amount, string calldata serviceId) external {
        Session storage s = sessions[sessionId];
        require(s.depositor == msg.sender, "Not session owner");
        require(s.active && block.timestamp < s.expiresAt, "Session not active");
        require(s.remainingBalance >= amount, "Insufficient balance");
        s.remainingBalance -= amount;
        s.totalRedeemed += amount;
        s.voucherCount += 1;
        emit ServicePaid(sessionId, msg.sender, amount, serviceId);
    }
```

- [ ] **Step 2: Write test file**

Create `contracts/test/SessionVault.t.sol`:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/SessionVault.sol";
import "../src/MockIUSD.sol";

contract SessionVaultTest is Test {
    SessionVault public vault;
    MockIUSD public iusd;
    address public owner;
    address public user1;

    function setUp() public {
        owner = address(this);
        user1 = makeAddr("user1");
        iusd = new MockIUSD();
        vault = new SessionVault(address(iusd), owner);
        vault.setAuthorizedOperator(owner, true);

        // Fund user1
        iusd.mint(user1, 100 ether);
    }

    function _createSession(address user, uint256 amount, uint256 duration) internal returns (uint256) {
        vm.startPrank(user);
        iusd.approve(address(vault), amount);
        uint256 sid = vault.createSession(amount, duration);
        vm.stopPrank();
        return sid;
    }

    function test_PayFromSession() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);

        vm.prank(user1);
        vault.payFromSession(sid, 0.01 ether, "signal-premium");

        SessionVault.Session memory s = vault.getSession(sid);
        assertEq(s.remainingBalance, 10 ether - 0.01 ether);
        assertEq(s.totalRedeemed, 0.01 ether);
        assertEq(s.voucherCount, 1);
    }

    function test_PayFromSession_EmitsEvent() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);

        vm.expectEmit(true, true, false, true);
        emit SessionVault.ServicePaid(sid, user1, 0.01 ether, "signal-premium");

        vm.prank(user1);
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_NotOwner() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);

        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert("Not session owner");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_Expired() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);

        vm.warp(block.timestamp + 2 hours);
        vm.prank(user1);
        vm.expectRevert("Session not active");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_InsufficientBalance() public {
        uint256 sid = _createSession(user1, 0.005 ether, 1 hours);

        vm.prank(user1);
        vm.expectRevert("Insufficient balance");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_ClosedSession() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);

        vm.prank(user1);
        vault.closeSession(sid);

        vm.prank(user1);
        vm.expectRevert("Session not active");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
    }

    function test_PayFromSession_MultiplePays() public {
        uint256 sid = _createSession(user1, 10 ether, 1 hours);

        vm.startPrank(user1);
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
        vault.payFromSession(sid, 0.002 ether, "signal-single");
        vault.payFromSession(sid, 0.01 ether, "signal-premium");
        vm.stopPrank();

        SessionVault.Session memory s = vault.getSession(sid);
        assertEq(s.remainingBalance, 10 ether - 0.022 ether);
        assertEq(s.totalRedeemed, 0.022 ether);
        assertEq(s.voucherCount, 3);
    }
}
```

- [ ] **Step 3: Run tests**

Run: `cd contracts && forge test --match-contract SessionVaultTest -v`
Expected: All 7 tests PASS

- [ ] **Step 4: Build and extract ABI**

Run:
```bash
cd contracts && forge build --via-ir
jq '.abi' out/SessionVault.sol/SessionVault.json > ../backend/app/session_vault_abi.json
```
Expected: Build succeeds, `backend/app/session_vault_abi.json` updated with `payFromSession` function and `ServicePaid` event.

- [ ] **Step 5: Commit**

```bash
git add contracts/src/SessionVault.sol contracts/test/SessionVault.t.sol backend/app/session_vault_abi.json
git commit -m "feat(contract): add payFromSession to SessionVault

On-chain payment from session without off-chain signing.
Depositor calls directly — msg.sender proves authorization."
```

---

### Task 2: Backend — Replace voucher verification with tx receipt verification

**Files:**
- Modify: `backend/app/mpp_middleware.py` (full rewrite of `MPPPaymentVerifier`)

- [ ] **Step 1: Rewrite `mpp_middleware.py`**

Replace the entire file content of `backend/app/mpp_middleware.py` with:

```python
"""MPP Payment Middleware — tx receipt verification for FastAPI"""
import json
import logging
from pathlib import Path

from web3 import Web3

logger = logging.getLogger(__name__)

SERVICE_PRICING = {
    "signal-basic": {"price_wei": int(0.001 * 1e18), "description": "Latest 10 signals"},
    "signal-premium": {"price_wei": int(0.01 * 1e18), "description": "All signals + analytics + leaderboard"},
    "signal-single": {"price_wei": int(0.002 * 1e18), "description": "Individual signal detail"},
}

# ServicePaid(uint256 indexed sessionId, address indexed payer, uint256 amount, string serviceId)
SERVICE_PAID_TOPIC = Web3.keccak(text="ServicePaid(uint256,address,uint256,string)")


class MPPPaymentVerifier:
    """Verifies payment by checking tx receipts for ServicePaid events."""

    def __init__(self, chain_client, session_vault_address: str, session_vault_abi: list):
        self.chain = chain_client
        self.vault_address = Web3.to_checksum_address(session_vault_address)
        self.vault = chain_client.w3.eth.contract(
            address=self.vault_address,
            abi=session_vault_abi,
        )
        self._used_tx_hashes: set[str] = set()

    def build_402_response(self, service_id: str, price_wei: int, token_address: str) -> dict:
        return {
            "x-payment-required": {
                "version": "pay-from-session-v1",
                "price": str(price_wei),
                "token": token_address,
                "network": "initia",
                "chainId": self.chain.w3.eth.chain_id,
                "sessionVault": self.vault_address,
                "accepts": ["pay-from-session-v1"],
                "serviceId": service_id,
            }
        }

    def verify_payment_tx(self, tx_hash: str, service_id: str, min_amount: int) -> dict:
        """Verify a payment tx contains a valid ServicePaid event."""
        tx_hash = tx_hash.strip()
        if tx_hash in self._used_tx_hashes:
            return {"valid": False, "error": "Transaction already used"}

        try:
            receipt = self.chain.w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            return {"valid": False, "error": f"Cannot fetch receipt: {e}"}

        if receipt["status"] != 1:
            return {"valid": False, "error": "Transaction failed"}

        # Find ServicePaid event from our vault contract
        for log in receipt["logs"]:
            if log["address"].lower() != self.vault_address.lower():
                continue
            if len(log["topics"]) < 3:
                continue
            if log["topics"][0].hex() != SERVICE_PAID_TOPIC.hex():
                continue

            # Decode: topics[1] = sessionId, topics[2] = payer
            # data = abi.encode(amount, serviceId)
            try:
                decoded = self.vault.events.ServicePaid().process_log(log)
                event_amount = decoded["args"]["amount"]
                event_service = decoded["args"]["serviceId"]
            except Exception:
                continue

            if event_amount < min_amount:
                return {"valid": False, "error": f"Paid {event_amount} < required {min_amount}"}
            if event_service != service_id:
                return {"valid": False, "error": f"Service mismatch: {event_service} != {service_id}"}

            self._used_tx_hashes.add(tx_hash)
            return {
                "valid": True,
                "tx_hash": tx_hash,
                "amount": event_amount,
                "service_id": event_service,
                "session_id": decoded["args"]["sessionId"],
                "payer": decoded["args"]["payer"],
            }

        return {"valid": False, "error": "No ServicePaid event found in transaction"}
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && python -c "from app.mpp_middleware import MPPPaymentVerifier, SERVICE_PRICING; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/mpp_middleware.py
git commit -m "refactor(backend): replace voucher verification with tx receipt verification

Verify ServicePaid events from on-chain tx receipts instead of
off-chain signed vouchers. Tracks used txHashes for replay protection."
```

---

### Task 3: Backend — Update payment-gated endpoints in main.py

**Files:**
- Modify: `backend/app/main.py:189-227` (`trigger_signal_generation`)
- Modify: `backend/app/main.py:270-312` (`get_premium_signals`, `get_paid_signal`)

- [ ] **Step 1: Update `/api/signals/generate` endpoint**

Replace the `trigger_signal_generation` function (lines 189-227) in `backend/app/main.py`:

```python
@app.post("/api/signals/generate")
async def trigger_signal_generation(request: Request):
    """Generate signals. Requires on-chain payment when gating is enabled."""
    settings = get_settings()
    payment_info = None

    if settings.enable_payment_gating and settings.session_vault_address:
        tx_hash = request.headers.get("X-PAYMENT-TX")
        if not tx_hash:
            from app.mpp_middleware import SERVICE_PRICING
            verifier = _get_payment_verifier()
            raise HTTPException(status_code=402, detail=verifier.build_402_response(
                "signal-premium", SERVICE_PRICING["signal-premium"]["price_wei"], settings.mock_iusd_address))
        verifier = _get_payment_verifier()
        result = verifier.verify_payment_tx(tx_hash, "signal-premium",
                                            SERVICE_PRICING["signal-premium"]["price_wei"])
        if not result["valid"]:
            raise HTTPException(status_code=402, detail={"error": result["error"]})
        payment_info = {"status": "paid", "tx_hash": tx_hash,
                        "session_id": result["session_id"], "amount_paid": str(result["amount"])}

    from app.signal_engine import run_signal_cycle, price_history, recent_signal_txs
    try:
        before = len(recent_signal_txs)
        run_signal_cycle()
        after = len(recent_signal_txs)
        new_signals = after - before
        history_depth = {k: len(v) for k, v in price_history.items()}
        _cache.clear()
        result = {
            "status": "ok",
            "newSignals": new_signals,
            "priceHistory": history_depth,
            "recentTxs": [t for t in recent_signal_txs[-new_signals:]] if new_signals > 0 else [],
        }
        if payment_info:
            result["payment"] = payment_info
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 2: Update `/api/signals/premium` endpoint**

Replace the `get_premium_signals` function (lines 270-291):

```python
@app.get("/api/signals/premium")
async def get_premium_signals(request: Request, offset: int = 0, limit: int = Query(default=100, le=100)):
    settings = get_settings()
    if not settings.enable_payment_gating or not settings.session_vault_address:
        return await get_signals(offset, limit)
    tx_hash = request.headers.get("X-PAYMENT-TX")
    if not tx_hash:
        from app.mpp_middleware import SERVICE_PRICING
        verifier = _get_payment_verifier()
        raise HTTPException(status_code=402, detail=verifier.build_402_response(
            "signal-premium", SERVICE_PRICING["signal-premium"]["price_wei"], settings.mock_iusd_address))
    from app.mpp_middleware import SERVICE_PRICING
    verifier = _get_payment_verifier()
    result = verifier.verify_payment_tx(tx_hash, "signal-premium",
                                        SERVICE_PRICING["signal-premium"]["price_wei"])
    if not result["valid"]:
        raise HTTPException(status_code=402, detail={"error": result["error"]})
    try:
        chain = get_chain()
        total = chain.get_signal_count()
        signals = chain.get_signals(offset, limit) if total > 0 else []
        return {"signals": signals, "total": total,
                "payment": {"status": "paid", "tx_hash": tx_hash, "amount_paid": str(result["amount"])}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: Update `/api/signals/single/:id` endpoint**

Replace the `get_paid_signal` function (lines 294-312):

```python
@app.get("/api/signals/single/{signal_id}")
async def get_paid_signal(signal_id: int, request: Request):
    settings = get_settings()
    if not settings.enable_payment_gating or not settings.session_vault_address:
        return await get_signal(signal_id)
    tx_hash = request.headers.get("X-PAYMENT-TX")
    if not tx_hash:
        from app.mpp_middleware import SERVICE_PRICING
        verifier = _get_payment_verifier()
        raise HTTPException(status_code=402, detail=verifier.build_402_response(
            "signal-single", SERVICE_PRICING["signal-single"]["price_wei"], settings.mock_iusd_address))
    from app.mpp_middleware import SERVICE_PRICING
    verifier = _get_payment_verifier()
    result = verifier.verify_payment_tx(tx_hash, "signal-single",
                                        SERVICE_PRICING["signal-single"]["price_wei"])
    if not result["valid"]:
        raise HTTPException(status_code=402, detail={"error": result["error"]})
    try:
        return {"signal": get_chain().get_signal(signal_id),
                "payment": {"status": "paid", "tx_hash": tx_hash, "amount_paid": str(result["amount"])}}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
```

- [ ] **Step 4: Add missing import**

At the top of the payment-gated section (around line 195 inside `trigger_signal_generation`), the `SERVICE_PRICING` import is already a local import. Verify the `_get_payment_verifier` function still works — it reads the ABI from `session_vault_abi.json` which now includes the new `payFromSession` function and `ServicePaid` event. No changes needed to `_get_payment_verifier`.

- [ ] **Step 5: Verify backend starts**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py
git commit -m "refactor(backend): switch payment-gated endpoints from X-PAYMENT to X-PAYMENT-TX

All three gated endpoints now verify on-chain ServicePaid events
from tx receipts instead of off-chain signed vouchers."
```

---

### Task 4: Frontend — Add session lookup and payForService to useSession

**Files:**
- Modify: `frontend/src/hooks/useSession.ts`

- [ ] **Step 1: Add bech32-to-hex utility and session vault read ABI**

Replace the full content of `frontend/src/hooks/useSession.ts`:

```typescript
import { useState, useCallback } from 'react';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { createPublicClient, encodeFunctionData, http, parseEther } from 'viem';
import { config, customChain } from '../config';
import { useQueryClient } from '@tanstack/react-query';

const MOCK_IUSD_ABI = [
  { name: 'approve', type: 'function', inputs: [{ name: 'spender', type: 'address' }, { name: 'amount', type: 'uint256' }], outputs: [{ type: 'bool' }], stateMutability: 'nonpayable' },
  { name: 'balanceOf', type: 'function', inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }], stateMutability: 'view' },
  { name: 'faucet', type: 'function', inputs: [], outputs: [], stateMutability: 'nonpayable' },
] as const;

const SESSION_VAULT_ABI = [
  { name: 'createSession', type: 'function', inputs: [{ name: 'amount', type: 'uint256' }, { name: 'durationSeconds', type: 'uint256' }], outputs: [{ name: 'sessionId', type: 'uint256' }], stateMutability: 'nonpayable' },
  { name: 'closeSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [], stateMutability: 'nonpayable' },
  { name: 'getUserSessions', type: 'function', inputs: [{ name: 'user', type: 'address' }], outputs: [{ name: '', type: 'uint256[]' }], stateMutability: 'view' },
  { name: 'getSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }], outputs: [{ name: '', type: 'tuple', components: [{ name: 'depositor', type: 'address' }, { name: 'depositAmount', type: 'uint256' }, { name: 'remainingBalance', type: 'uint256' }, { name: 'totalRedeemed', type: 'uint256' }, { name: 'voucherCount', type: 'uint256' }, { name: 'createdAt', type: 'uint256' }, { name: 'expiresAt', type: 'uint256' }, { name: 'active', type: 'bool' }] }], stateMutability: 'view' },
  { name: 'payFromSession', type: 'function', inputs: [{ name: 'sessionId', type: 'uint256' }, { name: 'amount', type: 'uint256' }, { name: 'serviceId', type: 'string' }], outputs: [], stateMutability: 'nonpayable' },
] as const;

export type TxStep = {
  label: string;
  status: 'pending' | 'success' | 'error' | 'idle';
  txHash?: string;
  error?: string;
};

type SessionInfo = {
  sessionId: number;
  remainingBalance: bigint;
  expiresAt: bigint;
  active: boolean;
};

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

/** Decode bech32 initia address to 0x hex address. */
function bech32ToHex(addr: string): `0x${string}` {
  const CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  const sepIdx = addr.lastIndexOf('1');
  const data = addr.slice(sepIdx + 1);
  const values = [...data].map(c => CHARSET.indexOf(c));
  const words = values.slice(0, -6); // drop checksum
  let bits = 0, value = 0;
  const bytes: number[] = [];
  for (const w of words) {
    value = (value << 5) | w;
    bits += 5;
    while (bits >= 8) {
      bits -= 8;
      bytes.push((value >> bits) & 0xff);
    }
  }
  return `0x${bytes.map(b => b.toString(16).padStart(2, '0')).join('')}` as `0x${string}`;
}

export function useSession() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<TxStep[]>([]);
  const { initiaAddress, requestTxBlock } = useInterwovenKit();
  const queryClient = useQueryClient();

  const evmAddress = initiaAddress ? bech32ToHex(initiaAddress) : undefined;

  const updateStep = (index: number, update: Partial<TxStep>) => {
    setSteps(prev => prev.map((s, i) => i === index ? { ...s, ...update } : s));
  };

  const sendTx = useCallback(async (contractAddr: string, data: string): Promise<string | undefined> => {
    if (!initiaAddress) throw new Error('Wallet not connected');
    const result = await requestTxBlock({
      chainId: customChain.chain_id,
      messages: [{ typeUrl: '/minievm.evm.v1.MsgCall', value: { sender: initiaAddress.toLowerCase(), contractAddr, input: data, value: '0', accessList: [], authList: [] } }],
    });
    return result?.transactionHash;
  }, [initiaAddress, requestTxBlock]);

  const findActiveSession = useCallback(async (minBalance: bigint): Promise<SessionInfo | null> => {
    if (!evmAddress) return null;
    try {
      const sessionIds = await publicClient.readContract({
        address: config.sessionVaultAddress,
        abi: SESSION_VAULT_ABI,
        functionName: 'getUserSessions',
        args: [evmAddress],
      }) as bigint[];
      // Check sessions in reverse (newest first)
      for (let i = sessionIds.length - 1; i >= 0; i--) {
        const session = await publicClient.readContract({
          address: config.sessionVaultAddress,
          abi: SESSION_VAULT_ABI,
          functionName: 'getSession',
          args: [sessionIds[i]],
        }) as any;
        const now = BigInt(Math.floor(Date.now() / 1000));
        if (session.active && session.expiresAt > now && session.remainingBalance >= minBalance) {
          return {
            sessionId: Number(sessionIds[i]),
            remainingBalance: session.remainingBalance,
            expiresAt: session.expiresAt,
            active: true,
          };
        }
      }
    } catch (e) {
      console.error('[Session] Failed to find active session:', e);
    }
    return null;
  }, [evmAddress]);

  const payForService = useCallback(async (sessionId: number, amountWei: bigint, serviceId: string): Promise<string | undefined> => {
    const data = encodeFunctionData({
      abi: SESSION_VAULT_ABI,
      functionName: 'payFromSession',
      args: [BigInt(sessionId), amountWei, serviceId],
    });
    return sendTx(config.sessionVaultAddress, data);
  }, [sendTx]);

  const claimFaucet = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSteps([{ label: 'Claim 1000 iUSD from faucet', status: 'pending' }]);
    try {
      const hash = await sendTx(config.mockIUSDAddress, encodeFunctionData({ abi: MOCK_IUSD_ABI, functionName: 'faucet', args: [] }));
      updateStep(0, { status: 'success', txHash: hash });
    } catch (e: any) {
      const msg = e.message || 'Faucet failed';
      setError(msg);
      updateStep(0, { status: 'error', error: msg });
    } finally {
      setLoading(false);
    }
  }, [sendTx]);

  const approveAndDeposit = useCallback(async (amountIUSD: string, durationHours: number) => {
    setLoading(true);
    setError(null);
    setSteps([
      { label: `Approve ${amountIUSD} iUSD`, status: 'pending' },
      { label: `Deposit ${amountIUSD} iUSD (${durationHours}h session)`, status: 'idle' },
    ]);
    try {
      const amountWei = parseEther(amountIUSD);
      const approveHash = await sendTx(config.mockIUSDAddress, encodeFunctionData({ abi: MOCK_IUSD_ABI, functionName: 'approve', args: [config.sessionVaultAddress, amountWei] }));
      updateStep(0, { status: 'success', txHash: approveHash });
      updateStep(1, { status: 'pending' });
      const depositHash = await sendTx(config.sessionVaultAddress, encodeFunctionData({ abi: SESSION_VAULT_ABI, functionName: 'createSession', args: [amountWei, BigInt(durationHours * 3600)] }));
      updateStep(1, { status: 'success', txHash: depositHash });
      queryClient.invalidateQueries({ queryKey: ['session'] });
    } catch (e: any) {
      const msg = e.message || 'Transaction failed';
      setError(msg);
      setSteps(prev => prev.map(s => s.status === 'pending' ? { ...s, status: 'error', error: msg } : s));
    } finally {
      setLoading(false);
    }
  }, [sendTx, queryClient]);

  const clearSteps = useCallback(() => { setSteps([]); setError(null); }, []);

  return { approveAndDeposit, claimFaucet, clearSteps, findActiveSession, payForService, loading, error, steps, connected: !!initiaAddress, evmAddress };
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors (or only pre-existing ones)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useSession.ts
git commit -m "feat(frontend): add session lookup and payForService to useSession

Reads user sessions from contract via viem, finds active session
with sufficient balance, sends payFromSession via InterwovenKit MsgCall.
Includes bech32-to-hex address conversion utility."
```

---

### Task 5: Frontend — Fix handleGenerate flow and error handling in Dashboard

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx:49-61` (handleGenerate)
- Modify: `frontend/src/pages/Dashboard.tsx:147-169` (genResult display)

- [ ] **Step 1: Update imports and destructure new session methods**

In `frontend/src/pages/Dashboard.tsx`, the existing line 5 destructures from `useSession`:

```typescript
  const { claimFaucet, approveAndDeposit, clearSteps, loading: sessionLoading, steps, connected } = useSession();
```

Replace with:

```typescript
  const { claimFaucet, approveAndDeposit, clearSteps, findActiveSession, payForService, loading: sessionLoading, steps, connected } = useSession();
```

- [ ] **Step 2: Replace handleGenerate function**

Replace the `handleGenerate` function (lines 49-61):

```typescript
  const handleGenerate = async () => {
    setGenLoading(true);
    setGenResult(null);
    try {
      const headers: Record<string, string> = {};

      if (config.paymentEnabled) {
        if (!connected) {
          setGenResult({ error: 'Connect wallet first.' });
          return;
        }

        // 1. Get pricing
        const pricingResp = await fetch(`${config.backendUrl}/api/payment/pricing`);
        const pricing = await pricingResp.json();
        const priceWei = BigInt(pricing.pricing['signal-premium'].price_wei);

        // 2. Find active session
        const session = await findActiveSession(priceWei);
        if (!session) {
          setGenResult({ error: 'No active session with sufficient balance. Deposit iUSD first.' });
          return;
        }

        // 3. Pay on-chain
        const txHash = await payForService(session.sessionId, priceWei, 'signal-premium');
        if (!txHash) {
          setGenResult({ error: 'Payment transaction failed.' });
          return;
        }
        headers['X-PAYMENT-TX'] = txHash;
      }

      // 4. Call backend
      const resp = await fetch(`${config.backendUrl}/api/signals/generate`, {
        method: 'POST',
        headers,
      });
      const data = await resp.json();
      if (!resp.ok) {
        setGenResult({ error: data.detail?.error || data.detail?.['x-payment-required']?.serviceId
          ? 'Payment verification failed. Try again.'
          : `Server error: ${JSON.stringify(data.detail)}` });
        return;
      }
      setGenResult(data);
    } catch (e: any) {
      setGenResult({ error: e.message || 'Generation failed' });
    } finally {
      setGenLoading(false);
    }
  };
```

- [ ] **Step 3: Fix the genResult display block**

Replace the genResult display block (lines 147-169):

```tsx
      {genResult && (
        <div className={`rounded-lg p-4 mb-8 text-sm ${genResult.error ? 'bg-red-500/10 border border-red-500/20' : 'bg-green-500/10 border border-green-500/20'}`}>
          {genResult.error ? (
            <div className="text-red-400">{genResult.error}</div>
          ) : (
            <div>
              <div className="text-green-400 font-semibold mb-2">
                {genResult.newSignals > 0
                  ? `Generated ${genResult.newSignals} new signal(s)`
                  : 'No new signals — market conditions unchanged'}
              </div>
              {genResult.recentTxs?.map((tx: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs mt-1">
                  <span className="text-white">{tx.symbol} {tx.isBull ? '\u{1F4C8}' : '\u{1F4C9}'} {tx.confidence}%</span>
                  <a href={explorerTxUrl(tx.txHash)} target="_blank" rel="noopener noreferrer"
                    className="font-mono text-[var(--color-accent)] hover:underline">{tx.txHash?.slice(0, 16)}...</a>
                </div>
              ))}
              {genResult.payment && (
                <div className="text-xs text-[var(--color-muted)] mt-2">
                  Paid: {(Number(genResult.payment.amount_paid) / 1e18).toFixed(4)} iUSD | Session #{genResult.payment.session_id} | <a href={explorerTxUrl(genResult.payment.tx_hash)} target="_blank" rel="noopener noreferrer" className="text-[var(--color-accent)] hover:underline">tx</a>
                </div>
              )}
            </div>
          )}
          <button onClick={() => setGenResult(null)} className="text-xs text-[var(--color-muted)] hover:text-white mt-2">Dismiss</button>
        </div>
      )}
```

- [ ] **Step 4: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "fix(frontend): pay-then-generate flow with proper error handling

Generate Signal now: finds active session, pays on-chain via
payFromSession MsgCall, then sends txHash to backend. Properly
handles 402, empty results, and all error states."
```

---

### Task 6: Deploy — Build contracts, deploy to testnet, update VPS

**Files:**
- No code changes. Uses existing `deploy-testnet.sh` and SSH.

- [ ] **Step 1: Deploy contracts to testnet**

Run:
```bash
cd /Users/phamdat/initia/signal
./deploy-testnet.sh
```
Expected: All 4 contracts deployed, addresses printed, `.env` files updated, ABIs extracted.

Note the new `SESSION_VAULT_ADDRESS` from the output — it will differ from the old one since the contract has changed.

- [ ] **Step 2: Build frontend for production**

Run:
```bash
cd frontend && npm run build
```
Expected: Build succeeds with no errors.

- [ ] **Step 3: SSH to VPS and deploy backend**

Run:
```bash
scp -i nim-claw.pem -r backend/app backend/.env bitnami@13.212.80.72:~/signal/backend/
ssh -i nim-claw.pem bitnami@13.212.80.72 'cd ~/signal && cat backend/.env | grep -E "CONTRACT|VAULT|IUSD|GATEWAY"'
```
Expected: Shows updated contract addresses on VPS.

- [ ] **Step 4: Restart backend on VPS**

Run:
```bash
ssh -i nim-claw.pem bitnami@13.212.80.72 'cd ~/signal && ./restart.sh'
```
If `restart.sh` doesn't exist, find the running process:
```bash
ssh -i nim-claw.pem bitnami@13.212.80.72 'pkill -f "uvicorn app.main" && cd ~/signal/backend && source .venv/bin/activate && nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 &'
```

- [ ] **Step 5: Get backend API URL and verify health**

Run:
```bash
ssh -i nim-claw.pem bitnami@13.212.80.72 'curl -s http://localhost:8000/api/health | python3 -m json.tool'
```
Expected: `{"status": "ok", "chain_connected": true, ...}`

The public backend URL is already set in `frontend/.env`:
```
VITE_BACKEND_URL=https://13-212-80-72.sslip.io/signal-api
```

Verify externally:
```bash
curl -s https://13-212-80-72.sslip.io/signal-api/api/health | python3 -m json.tool
```

- [ ] **Step 6: Deploy frontend to VPS**

Run:
```bash
scp -i nim-claw.pem -r frontend/dist/* bitnami@13.212.80.72:~/signal/frontend/dist/
```
Or if the frontend is served from a different location, check:
```bash
ssh -i nim-claw.pem bitnami@13.212.80.72 'ls ~/signal/frontend/'
```

- [ ] **Step 7: Verify end-to-end**

Open the frontend URL in a browser. Test:
1. Connect wallet via InterwovenKit
2. Claim iUSD from faucet
3. Approve + deposit 10 iUSD for 24h session
4. Click "Generate Signal" — should pay on-chain, then show signal result or "No new signals"
5. Check that no 402 errors appear

- [ ] **Step 8: Commit deployment state**

```bash
git add backend/.env frontend/.env backend/app/session_vault_abi.json
git commit -m "deploy: update contract addresses and ABI after testnet redeploy"
```
