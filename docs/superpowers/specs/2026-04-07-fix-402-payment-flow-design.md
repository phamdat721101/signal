# Fix 402 Payment Flow — On-Chain Payment via SessionVault

**Date:** 2026-04-07
**Status:** Approved

## Problem

The "Generate Signal" button returns 402 because `ENABLE_PAYMENT_GATING=true` but the frontend sends no payment proof. Two bugs stacked:

1. Backend requires an `X-PAYMENT` header with a signed voucher, but the frontend never sends one.
2. Frontend doesn't check `resp.ok` — it parses the 402 JSON body, finds no `error` key (it's under `detail`), and falls through to the success branch showing "Generated 0 new signal(s)".

The voucher system requires EIP-191 `personal_sign`, which InterwovenKit does not expose. Only `requestTxBlock` (MsgCall) is available.

## Solution

Replace off-chain voucher signing with on-chain payment via a new `payFromSession` function on SessionVault. The depositor calls it directly — `msg.sender` proves authorization.

## Changes

### 1. Contract: SessionVault.sol

Add one function and one event:

```solidity
event ServicePaid(uint256 indexed sessionId, address indexed payer, uint256 amount, string serviceId);

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

Requires contract recompilation and redeployment. ABI must be updated in `backend/app/session_vault_abi.json`.

### 2. Backend: mpp_middleware.py

Replace `MPPPaymentVerifier` internals:

- Remove `verify_voucher(voucher_b64)` and `redeem_voucher_onchain(voucher_b64)` and `_flush_batch()`.
- Add `verify_payment_tx(tx_hash, service_id, min_amount)`:
  1. Fetch tx receipt via `w3.eth.get_transaction_receipt(tx_hash)`.
  2. Decode logs for `ServicePaid` event from the SessionVault address.
  3. Verify: event exists, `amount >= min_amount`, `serviceId` matches.
  4. Check tx_hash not in `_used_tx_hashes` set (replay protection).
  5. Add tx_hash to the set on success.
- Update `build_402_response` to indicate tx-based payment (change `accepts` to `["pay-from-session-v1"]`).

### 3. Backend: main.py

All three payment-gated endpoints (`/api/signals/generate`, `/api/signals/premium`, `/api/signals/single/:id`):

- Read `X-PAYMENT-TX` header instead of `X-PAYMENT`.
- Call `verify_payment_tx(tx_hash, service_id, price_wei)`.
- Return 402 with payment info if header missing or verification fails.
- On success, proceed with the original logic.

### 4. Frontend: useSession.ts

Add to the existing hook:

- ABI entries for `getUserSessions(address)`, `getSession(uint256)`, `payFromSession(uint256, uint256, string)`.
- `findActiveSession(evmAddress)`: read user's sessions from contract, return the first active session with sufficient balance.
- `payForService(sessionId, amount, serviceId)`: send MsgCall to `payFromSession` via InterwovenKit, return txHash.

### 5. Frontend: Dashboard.tsx

Replace `handleGenerate`:

1. Fetch pricing from `GET /api/payment/pricing`.
2. Find user's active session via contract read.
3. If no session or insufficient balance, show message instead of calling the API.
4. Send MsgCall to `payFromSession(sessionId, price, "signal-premium")`.
5. On success, POST `/api/signals/generate` with `X-PAYMENT-TX: txHash` header.
6. Check `resp.ok` before treating response as success.
7. Display result or appropriate error.

## Error States

| State | UI behavior |
|-------|------------|
| Wallet not connected | Disable button, show "Connect wallet first" |
| No active session | Show "Deposit iUSD first" |
| Insufficient session balance | Show "Top up session — balance too low" |
| Payment tx fails | Show MsgCall error from InterwovenKit |
| Backend 402 (txHash invalid/replayed) | Show "Payment verification failed" |
| Backend 500 | Show the error detail |
| 200 with 0 signals | Show "No new signals — market conditions unchanged" |

## Data Flow

```
User clicks "Generate Signal"
  -> Frontend reads pricing (GET /api/payment/pricing)
  -> Frontend reads user's active session from contract
  -> Frontend sends MsgCall: payFromSession(sessionId, price, "signal-premium")
  -> InterwovenKit auto-signs (MsgCall is in enableAutoSign list)
  -> Gets txHash
  -> POST /api/signals/generate with X-PAYMENT-TX header
  -> Backend verifies ServicePaid event in tx receipt
  -> Backend runs signal_engine.run_signal_cycle()
  -> Frontend shows result
```

## Replay Protection

Backend keeps an in-memory `set()` of used txHashes. A txHash can only pay for one API call. Acceptable because backend restarts are rare and replaying a used hash on-chain would fail anyway (session balance already deducted).

## Files Modified

- `contracts/src/SessionVault.sol` — add `payFromSession` + `ServicePaid` event
- `backend/app/session_vault_abi.json` — updated ABI after recompilation
- `backend/app/mpp_middleware.py` — replace voucher verification with tx verification
- `backend/app/main.py` — switch `X-PAYMENT` to `X-PAYMENT-TX` in all gated endpoints
- `frontend/src/hooks/useSession.ts` — add session lookup + `payForService`
- `frontend/src/pages/Dashboard.tsx` — pay-then-generate flow + error handling fix
