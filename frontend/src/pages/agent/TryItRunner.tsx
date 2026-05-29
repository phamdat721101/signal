/**
 * Try-It runner — non-custodial Morph Hoodi paid call from the browser.
 *
 * Flow (rendered inside <ChainGate chainId={2910}>):
 *   1. GET endpoint → 402 with payment-required envelope
 *   2. Build EIP-3009 authorization, sign typed data via wagmi WalletClient
 *      (tokenName='USDC' to match Hoodi USDC on-chain — see Task 4 notes)
 *   3. POST /v2/settle to facilitator → sponsor pays gas, USDC is transferred
 *   4. Retry endpoint with x-payment-tx headers → response renders
 *
 * SOLID: single responsibility = one bundle execution. No state outside.
 */
import { useState } from 'react';
import { useAccount, useWalletClient } from 'wagmi';
import { config, explorerTxUrl } from '../../config';
import { type Bundle, endpointUrl } from './bundles';

// ─── EIP-3009 helpers (inlined) ────────────────────────────────────────────
// n-payment 0.18 is Node-targeted (top-level `process` reads break in the
// browser). The three helpers we need are <40 lines of pure code, so we
// inline them here rather than ship a fat polyfilled SDK to the browser.
// SOLID: this file owns the buyer flow end-to-end, helpers are scoped to it.
const TRANSFER_AUTH_TYPES = {
  TransferWithAuthorization: [
    { name: 'from', type: 'address' },
    { name: 'to', type: 'address' },
    { name: 'value', type: 'uint256' },
    { name: 'validAfter', type: 'uint256' },
    { name: 'validBefore', type: 'uint256' },
    { name: 'nonce', type: 'bytes32' },
  ],
} as const;

interface EipAuthorization {
  from: `0x${string}`;
  to: `0x${string}`;
  value: bigint;
  validAfter: bigint;
  validBefore: bigint;
  nonce: `0x${string}`;
}

function buildTransferAuthTypedData(args: {
  verifyingContract: `0x${string}`;
  chainId: number;
  tokenName: string;
  tokenVersion: string;
  authorization: EipAuthorization;
}) {
  return {
    domain: {
      name: args.tokenName,
      version: args.tokenVersion,
      chainId: args.chainId,
      verifyingContract: args.verifyingContract,
    },
    types: TRANSFER_AUTH_TYPES,
    primaryType: 'TransferWithAuthorization' as const,
    message: args.authorization,
  };
}

function encodeAuth(a: EipAuthorization) {
  return {
    from: a.from,
    to: a.to,
    value: a.value.toString(),
    validAfter: a.validAfter.toString(),
    validBefore: a.validBefore.toString(),
    nonce: a.nonce,
  };
}

function randomNonce32(): `0x${string}` {
  const arr = new Uint8Array(32);
  crypto.getRandomValues(arr);
  return ('0x' + Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('')) as `0x${string}`;
}

const FACILITATOR_URL =
  (import.meta.env.VITE_FACILITATOR_URL as string | undefined) ?? 'http://127.0.0.1:4040/x402';
const NETWORK_CAIP2 = `eip155:${config.morphHoodi.chainId}`;

interface RunState {
  status: 'idle' | 'signing' | 'settling' | 'fetching' | 'ok' | 'err';
  txHash?: string;
  payer?: string;
  ms?: number;
  data?: unknown;
  error?: string;
}

export default function TryItRunner({ bundle, values, disabled }: {
  bundle: Bundle;
  values: Record<string, string>;
  disabled?: boolean;
}) {
  const { address } = useAccount();
  const { data: walletClient } = useWalletClient({ chainId: config.morphHoodi.chainId });
  const [state, setState] = useState<RunState>({ status: 'idle' });

  const run = async () => {
    if (!walletClient || !address) {
      setState({ status: 'err', error: 'Wallet not ready' });
      return;
    }
    const t0 = performance.now();
    try {
      // 1. Trigger 402.
      const url = endpointUrl(bundle, values);
      const r402 = await fetch(url);
      if (r402.status !== 402) throw new Error(`expected 402, got ${r402.status}`);
      const envB64 = r402.headers.get('payment-required') ?? r402.headers.get('x-payment-required');
      if (!envB64) throw new Error('no payment-required header');
      const envelope = JSON.parse(atob(envB64));
      const accept = envelope.accepts?.[0];
      if (!accept || accept.network !== NETWORK_CAIP2 || accept.scheme !== 'eip3009') {
        throw new Error('unsupported envelope');
      }

      // 2. Sign EIP-3009 typed data.
      setState({ status: 'signing' });
      const now = Math.floor(Date.now() / 1000);
      const authorization = {
        from: address,
        to: accept.payTo as `0x${string}`,
        value: BigInt(accept.maxAmountRequired),
        validAfter: 0n,
        validBefore: BigInt(now + 300),
        nonce: randomNonce32(),
      };
      const td = buildTransferAuthTypedData({
        verifyingContract: accept.asset as `0x${string}`,
        chainId: config.morphHoodi.chainId,
        tokenName: 'USDC',
        tokenVersion: '2',
        authorization,
      });
      const signature = await walletClient.signTypedData({
        account: address,
        domain: td.domain,
        types: td.types,
        primaryType: 'TransferWithAuthorization',
        message: td.message as never,
      });

      // 3. Settle via facilitator (sponsor pays gas).
      setState({ status: 'settling' });
      const settleRes = await fetch(`${FACILITATOR_URL}/v2/settle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          x402Version: 2,
          paymentPayload: {
            x402Version: 2,
            scheme: 'eip3009',
            network: NETWORK_CAIP2,
            authorization: encodeAuth(authorization),
            signature,
          },
          paymentRequirements: accept,
        }),
      });
      const settleJson: any = await settleRes.json();
      if (!settleRes.ok || !settleJson.success) {
        throw new Error(settleJson.errorReason ?? `settle ${settleRes.status}`);
      }
      const txHash = settleJson.transaction as string;

      // 4. Retry with proof.
      setState({ status: 'fetching', txHash });
      const r = await fetch(url, {
        headers: {
          'x-payment-tx': txHash,
          'x-payment-network': NETWORK_CAIP2,
          'x-payment-payer': address,
        },
      });
      const text = await r.text();
      if (!r.ok) throw new Error(`upstream ${r.status}: ${text.slice(0, 200)}`);
      const data = text ? JSON.parse(text) : {};
      setState({ status: 'ok', txHash, payer: address, ms: Math.round(performance.now() - t0), data });
    } catch (e) {
      setState({ status: 'err', error: e instanceof Error ? e.message : String(e), ms: Math.round(performance.now() - t0) });
    }
  };

  const busy = state.status === 'signing' || state.status === 'settling' || state.status === 'fetching';
  const label =
    state.status === 'signing' ? 'Signing…' :
    state.status === 'settling' ? 'Settling on-chain…' :
    state.status === 'fetching' ? 'Fetching…' : '▶ Try It';

  return (
    <div className="font-cyber text-xs">
      <button onClick={run} disabled={disabled || busy}
        className="bg-cyber-green text-cyber-carbon font-cyber-display font-bold uppercase px-4 py-2 hover:bg-cyber-green-dim active:scale-95 transition disabled:opacity-40 disabled:cursor-not-allowed">
        {label}
      </button>

      {state.status === 'ok' && (
        <div className="mt-3 border border-cyber-outline bg-cyber-carbon p-3">
          <div className="flex items-center justify-between mb-2 text-[10px] uppercase tracking-widest">
            <span className="text-cyber-green">200 OK · {state.ms}ms</span>
            {state.txHash && (
              <a href={explorerTxUrl(state.txHash, config.morphHoodi.chainId)} target="_blank" rel="noopener noreferrer"
                 className="text-cyber-cyan hover:underline">
                tx {state.txHash.slice(0, 10)}…
              </a>
            )}
          </div>
          <pre className="text-white/80 overflow-x-auto whitespace-pre text-[11px] leading-relaxed max-h-64 overflow-y-auto">
            {JSON.stringify(state.data, null, 2)}
          </pre>
        </div>
      )}

      {state.status === 'err' && (
        <div className="mt-3 border border-cyber-pink/40 bg-cyber-carbon p-3 text-cyber-pink text-[11px]">
          {state.error}
        </div>
      )}
    </div>
  );
}
