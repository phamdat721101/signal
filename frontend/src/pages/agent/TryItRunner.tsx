/**
 * Try-It runner — non-custodial paid call from the browser.
 *
 * Rail-aware: branches on `rail.kind`:
 *   • 'eip3009'        — sign EIP-3009 typed-data + writeContract
 *                        transferWithAuthorization (Arbitrum Sepolia /
 *                        any USDC chain). Server reads the resulting
 *                        Transfer log.
 *   • 'erc20-transfer' — plain ERC-20 transfer to payTo (GOAT testnet,
 *                        WGBTC; matches agent-payment/scripts/x402-pay.mjs).
 *
 * Both rails share:
 *   - 402 → parse `payment-required` envelope (asset, payTo, value)
 *   - on-chain step (above) → wait for receipt
 *   - GET retry with `X-Payment-Tx: <hash>` → server verifies + serves JSON
 *
 * SOLID: single responsibility = one bundle execution on one rail. The
 * payment-protocol logic is the only branch; everything else is shared.
 */
import { useState } from 'react';
import { useAccount, usePublicClient, useWalletClient } from 'wagmi';
import { explorerTxUrl } from '../../config';
import { type Bundle, endpointUrl, type RailConfig } from './bundles';

// ─── EIP-3009 typed data + ABI ────────────────────────────────────────────
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

const TRANSFER_AUTH_ABI = [{
  type: 'function', name: 'transferWithAuthorization', stateMutability: 'nonpayable',
  inputs: [
    { name: 'from', type: 'address' },
    { name: 'to', type: 'address' },
    { name: 'value', type: 'uint256' },
    { name: 'validAfter', type: 'uint256' },
    { name: 'validBefore', type: 'uint256' },
    { name: 'nonce', type: 'bytes32' },
    { name: 'v', type: 'uint8' },
    { name: 'r', type: 'bytes32' },
    { name: 's', type: 'bytes32' },
  ],
  outputs: [],
}] as const;

const ERC20_TRANSFER_ABI = [{
  type: 'function', name: 'transfer', stateMutability: 'nonpayable',
  inputs: [
    { name: 'to', type: 'address' },
    { name: 'amount', type: 'uint256' },
  ],
  outputs: [{ type: 'bool' }],
}] as const;

interface EipAuthorization {
  from: `0x${string}`;
  to: `0x${string}`;
  value: bigint;
  validAfter: bigint;
  validBefore: bigint;
  nonce: `0x${string}`;
}

function randomNonce32(): `0x${string}` {
  const arr = new Uint8Array(32);
  crypto.getRandomValues(arr);
  return ('0x' + Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('')) as `0x${string}`;
}

function splitSignature(sig: `0x${string}`): { r: `0x${string}`; s: `0x${string}`; v: number } {
  const clean = sig.startsWith('0x') ? sig.slice(2) : sig;
  if (clean.length !== 130) throw new Error(`bad sig length ${clean.length}`);
  const r = `0x${clean.slice(0, 64)}` as `0x${string}`;
  const s = `0x${clean.slice(64, 128)}` as `0x${string}`;
  let v = parseInt(clean.slice(128), 16);
  if (v < 27) v += 27;
  return { r, s, v };
}

// Submit timeout — wallet popup or programmatic signer must respond within this
// window or we surface a clear error. Privy embedded wallets (via InterwovenKit)
// tend to silently no-op on arbitrary EVM chains.
const SUBMIT_TIMEOUT_MS = 90_000;

interface RunState {
  status: 'idle' | 'preflight' | 'signing' | 'submitting' | 'fetching' | 'ok' | 'err';
  txHash?: string;
  payer?: string;
  ms?: number;
  data?: unknown;
  error?: string;
  hint?: 'need_gas' | 'need_external_wallet';
}

export default function TryItRunner({ bundle, values, rail, disabled }: {
  bundle: Bundle;
  values: Record<string, string>;
  rail: RailConfig;
  disabled?: boolean;
}) {
  const { address } = useAccount();
  const { data: walletClient } = useWalletClient({ chainId: rail.chainId });
  const publicClient = usePublicClient({ chainId: rail.chainId });
  const [state, setState] = useState<RunState>({ status: 'idle' });

  const run = async () => {
    if (!walletClient || !publicClient || !address) {
      setState({ status: 'err', error: 'Wallet not ready' });
      return;
    }
    const t0 = performance.now();
    const network = `eip155:${rail.chainId}`;
    try {
      // 0. Pre-flight gas balance.
      setState({ status: 'preflight' });
      const gasBalance = await publicClient.getBalance({ address });
      if (gasBalance < rail.minGasWei) {
        setState({
          status: 'err',
          error: `Need a tiny amount of ${rail.gasSymbol} on ${rail.name} for gas.`,
          hint: 'need_gas',
        });
        return;
      }

      // 1. Trigger 402 + read envelope (authoritative payTo + amount).
      const url = endpointUrl(rail, bundle, values);
      const r402 = await fetch(url);
      if (r402.status !== 402) throw new Error(`expected 402, got ${r402.status}`);
      const envB64 = r402.headers.get('payment-required');
      if (!envB64) throw new Error('no payment-required header');
      const envelope = JSON.parse(atob(envB64));
      // The server returns one accepts[] entry per supported rail. Pick the
      // entry whose network matches the wallet's active rail — that's how
      // the buyer signals which rail they're paying on (per x402 spec).
      const accept = (envelope.accepts as Array<{ scheme: string; network: string; payTo: string; maxAmountRequired: string }> | undefined)
        ?.find((a) => a.network === network && a.scheme === 'exact');
      if (!accept) throw new Error(`no accepts entry for network ${network} in 402 envelope`);
      const payTo = accept.payTo as `0x${string}`;
      const amount = BigInt(accept.maxAmountRequired);

      // 2. On-chain payment — branch by rail kind.
      let txHash: `0x${string}`;
      try {
        if (rail.kind === 'eip3009') {
          if (!rail.token.domain) throw new Error('eip3009 rail missing token.domain');
          setState({ status: 'signing' });
          const auth: EipAuthorization = {
            from: address,
            to: payTo,
            value: amount,
            validAfter: 0n,
            validBefore: BigInt(Math.floor(Date.now() / 1000) + 600),
            nonce: randomNonce32(),
          };
          const signature = await walletClient.signTypedData({
            account: address,
            domain: {
              ...rail.token.domain,
              chainId: rail.chainId,
              verifyingContract: rail.token.address,
            },
            types: TRANSFER_AUTH_TYPES,
            primaryType: 'TransferWithAuthorization',
            message: auth as never,
          });
          const { r, s, v } = splitSignature(signature);
          setState({ status: 'submitting' });
          txHash = await raceWithTimeout(walletClient.writeContract({
            address: rail.token.address,
            abi: TRANSFER_AUTH_ABI,
            functionName: 'transferWithAuthorization',
            args: [auth.from, auth.to, auth.value, auth.validAfter, auth.validBefore, auth.nonce, v, r, s],
          }));
        } else {
          // 'erc20-transfer' — plain transfer to payTo.
          setState({ status: 'submitting' });
          txHash = await raceWithTimeout(walletClient.writeContract({
            address: rail.token.address,
            abi: ERC20_TRANSFER_ABI,
            functionName: 'transfer',
            args: [payTo, amount],
          }));
        }
      } catch (e) {
        if (e instanceof Error && e.message === 'SUBMIT_TIMEOUT') {
          setState({
            status: 'err',
            error: 'Wallet did not respond within 90 s.',
            hint: 'need_external_wallet',
            ms: Math.round(performance.now() - t0),
          });
          return;
        }
        throw e;
      }
      await publicClient.waitForTransactionReceipt({ hash: txHash, timeout: 60_000 });

      // 3. Retry the original GET with proof of payment.
      setState({ status: 'fetching', txHash });
      const apiResp = await fetch(url, {
        headers: {
          'x-payment-tx': txHash,
          'x-payment-network': network,
          'x-payment-payer': address,
        },
      });
      const text = await apiResp.text();
      if (!apiResp.ok) throw new Error(`upstream ${apiResp.status}: ${text.slice(0, 200)}`);
      const data = text ? JSON.parse(text) : {};
      setState({
        status: 'ok',
        txHash,
        payer: address,
        ms: Math.round(performance.now() - t0),
        data,
      });
    } catch (e) {
      setState({
        status: 'err',
        error: e instanceof Error ? e.message : String(e),
        ms: Math.round(performance.now() - t0),
      });
    }
  };

  const busy = state.status === 'preflight' || state.status === 'signing' || state.status === 'submitting' || state.status === 'fetching';
  const label =
    state.status === 'preflight' ? 'Preflight…' :
    state.status === 'signing' ? 'Signing…' :
    state.status === 'submitting' ? 'Submitting on-chain…' :
    state.status === 'fetching' ? 'Fetching…' : '▶ Try It';

  return (
    <div className="font-cyber text-xs">
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={disabled || busy}
          className="bg-cyber-green text-cyber-carbon font-cyber-display font-bold uppercase px-4 py-2 hover:bg-cyber-green-dim active:scale-95 transition disabled:opacity-40 disabled:cursor-not-allowed">
          {label}
        </button>
        {state.status === 'err' && (
          <button onClick={() => setState({ status: 'idle' })}
            className="border border-cyber-outline text-white/70 px-3 py-2 hover:bg-cyber-surface-high uppercase tracking-widest text-[10px]">
            Reset
          </button>
        )}
      </div>

      {state.status === 'ok' && (
        <div className="mt-3 border border-cyber-outline bg-cyber-carbon p-3">
          <div className="flex items-center justify-between mb-2 text-[10px] uppercase tracking-widest">
            <span className="text-cyber-green">200 OK · {state.ms}ms</span>
            {state.txHash && (
              <a href={explorerTxUrl(state.txHash, rail.chainId)} target="_blank" rel="noopener noreferrer"
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
          <div className="font-cyber-display uppercase tracking-widest">{state.error}</div>
          {state.hint === 'need_gas' && (
            <p className="mt-2 text-white/70 text-[10px] leading-relaxed">
              The buyer pays a few millionths of {rail.gasSymbol} for the on-chain payment.{' '}
              <a className="text-cyber-cyan hover:underline" href={rail.gasFaucetUrl}
                 target="_blank" rel="noopener noreferrer">
                Get test {rail.gasSymbol} →
              </a>
            </p>
          )}
          {state.hint === 'need_external_wallet' && (
            <p className="mt-2 text-white/70 text-[10px] leading-relaxed">
              The InterwovenKit embedded wallet does not surface a transaction-approval modal
              for non-Initia EVM contract calls. Connect <strong>MetaMask</strong> or <strong>Rabby</strong> on{' '}
              {rail.name} and retry.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** Race a wallet-submit promise against a 90 s timeout (rejects with SUBMIT_TIMEOUT). */
function raceWithTimeout<T>(p: Promise<T>): Promise<T> {
  return Promise.race([
    p,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('SUBMIT_TIMEOUT')), SUBMIT_TIMEOUT_MS),
    ),
  ]);
}
