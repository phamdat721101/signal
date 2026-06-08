/**
 * Try-It runner — non-custodial Arbitrum Sepolia paid call from the browser.
 *
 * Flow (rendered inside <ChainGate chainId={421614}>):
 *   1. GET endpoint → 402 with payment-required envelope (asset, payTo, value)
 *   2. Buyer signs EIP-3009 transferWithAuthorization (USDC EIP-712 typed data)
 *   3. Buyer submits the authorization tx via writeContract — pays the gas
 *      themselves (~$0.0001 testnet ETH on Arb Sepolia)
 *   4. Wait for tx receipt
 *   5. GET retry with `x-payment-tx: <hash>` header → server verifies the
 *      receipt on-chain and serves the JSON response
 *
 * Why buyer-direct settlement: x402.org/facilitator does not support Arb
 * Sepolia (verified via /supported endpoint), CDP requires server-side
 * auth. This flow needs zero external facilitator and zero sponsor wallet
 * — keeps deploy simple while honoring the chain choice.
 *
 * SOLID: single responsibility = one bundle execution. No state outside.
 */
import { useState } from 'react';
import { useAccount, useWalletClient, usePublicClient } from 'wagmi';
import { config, explorerTxUrl, ARBITRUM_SEPOLIA_USDC_ADDRESS } from '../../config';
import { type Bundle, endpointUrl } from './bundles';

// ─── EIP-3009 transferWithAuthorization typed data + ABI ──────────────────
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
  type: 'function',
  name: 'transferWithAuthorization',
  stateMutability: 'nonpayable',
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

/** Split a 65-byte 0x... signature into r, s, v. */
function splitSignature(sig: `0x${string}`): { r: `0x${string}`; s: `0x${string}`; v: number } {
  const clean = sig.startsWith('0x') ? sig.slice(2) : sig;
  if (clean.length !== 130) throw new Error(`bad sig length ${clean.length}`);
  const r = `0x${clean.slice(0, 64)}` as `0x${string}`;
  const s = `0x${clean.slice(64, 128)}` as `0x${string}`;
  let v = parseInt(clean.slice(128), 16);
  if (v < 27) v += 27;
  return { r, s, v };
}

const NETWORK_CAIP2 = `eip155:${config.arbitrumSepolia.chainId}`;
/** Minimum native ETH to pay one writeContract on Arb Sepolia.
 *  Empirically gas ~ 50k × 0.1 gwei ≈ 5e9 wei. Pad to 5e13 (5 × 10⁻⁵ ETH)
 *  so the buyer has slack for a few retries. */
const MIN_GAS_WEI = 50_000_000_000_000n;
/** writeContract timeout — wallet popup or programmatic signer must respond
 *  within this window or we surface a clear error. Privy embedded wallets
 *  (via InterwovenKit) tend to silently no-op on arbitrary EVM chains. */
const SUBMIT_TIMEOUT_MS = 90_000;

interface RunState {
  status: 'idle' | 'preflight' | 'signing' | 'submitting' | 'fetching' | 'ok' | 'err';
  txHash?: string;
  payer?: string;
  ms?: number;
  data?: unknown;
  error?: string;
  hint?: 'need_eth' | 'need_external_wallet';
}

export default function TryItRunner({ bundle, values, disabled }: {
  bundle: Bundle;
  values: Record<string, string>;
  disabled?: boolean;
}) {
  const { address } = useAccount();
  const { data: walletClient } = useWalletClient({ chainId: config.arbitrumSepolia.chainId });
  const publicClient = usePublicClient({ chainId: config.arbitrumSepolia.chainId });
  const [state, setState] = useState<RunState>({ status: 'idle' });

  const run = async () => {
    if (!walletClient || !publicClient || !address) {
      setState({ status: 'err', error: 'Wallet not ready' });
      return;
    }
    const t0 = performance.now();
    try {
      // 0. Pre-flight: native ETH gas check. The InterwovenKit embedded
      //    wallet doesn't reliably surface "insufficient funds" when 0;
      //    catching it here gives the buyer a clear faucet hint instead of
      //    a stuck "submitting…" spinner.
      setState({ status: 'preflight' });
      const gasBalance = await publicClient.getBalance({ address });
      if (gasBalance < MIN_GAS_WEI) {
        setState({
          status: 'err',
          error: 'Need a tiny amount of Arb Sepolia ETH for gas.',
          hint: 'need_eth',
        });
        return;
      }

      // 1. Trigger 402 + read the envelope so we use the authoritative `payTo`.
      const url = endpointUrl(bundle, values);
      const r402 = await fetch(url);
      if (r402.status !== 402) throw new Error(`expected 402, got ${r402.status}`);
      const envB64 = r402.headers.get('payment-required');
      if (!envB64) throw new Error('no payment-required header');
      const envelope = JSON.parse(atob(envB64));
      const accept = envelope.accepts?.[0];
      if (!accept || accept.network !== NETWORK_CAIP2 || accept.scheme !== 'exact') {
        throw new Error('unsupported envelope');
      }

      // 2. Sign EIP-3009 typed data.
      //    Domain MUST match the on-chain values exactly. Circle's canonical
      //    USDC on Arb Sepolia (0x75faf114…46AA4d) reports name()="USD Coin"
      //    and version()="2". Always pin the domain to the exact contract
      //    metadata of the asset the buyer is actually paying with —
      //    mismatched name/version makes the contract recover a different
      //    signer and revert with "invalid signature".
      setState({ status: 'signing' });
      const now = Math.floor(Date.now() / 1000);
      const auth: EipAuthorization = {
        from: address,
        to: accept.payTo as `0x${string}`,
        value: BigInt(accept.maxAmountRequired),
        validAfter: 0n,
        validBefore: BigInt(now + 600),
        nonce: randomNonce32(),
      };
      const signature = await walletClient.signTypedData({
        account: address,
        domain: {
          name: 'USD Coin',
          version: '2',
          chainId: config.arbitrumSepolia.chainId,
          verifyingContract: ARBITRUM_SEPOLIA_USDC_ADDRESS,
        },
        types: TRANSFER_AUTH_TYPES,
        primaryType: 'TransferWithAuthorization',
        message: auth as never,
      });
      const { r, s, v } = splitSignature(signature);

      // 3. Submit transferWithAuthorization. Race against a 90-s timeout
      //    so a non-responsive wallet (e.g. embedded wallet without an
      //    approval modal for non-Initia chains) surfaces as a clean
      //    error rather than a perpetual spinner.
      setState({ status: 'submitting' });
      const submitPromise = walletClient.writeContract({
        address: ARBITRUM_SEPOLIA_USDC_ADDRESS,
        abi: TRANSFER_AUTH_ABI,
        functionName: 'transferWithAuthorization',
        args: [auth.from, auth.to, auth.value, auth.validAfter, auth.validBefore, auth.nonce, v, r, s],
      });
      const timeoutPromise = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('SUBMIT_TIMEOUT')), SUBMIT_TIMEOUT_MS),
      );
      let txHash: `0x${string}`;
      try {
        txHash = await Promise.race([submitPromise, timeoutPromise]);
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

      // 4. Retry the original GET with the proof of payment.
      setState({ status: 'fetching', txHash });
      const apiResp = await fetch(url, {
        headers: {
          'x-payment-tx': txHash,
          'x-payment-network': NETWORK_CAIP2,
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
              <a href={explorerTxUrl(state.txHash, config.arbitrumSepolia.chainId)} target="_blank" rel="noopener noreferrer"
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
          {state.hint === 'need_eth' && (
            <p className="mt-2 text-white/70 text-[10px] leading-relaxed">
              The buyer pays a few millionths of an ETH for the transferWithAuthorization tx.{' '}
              <a className="text-cyber-cyan hover:underline"
                 href="https://www.alchemy.com/faucets/arbitrum-sepolia"
                 target="_blank" rel="noopener noreferrer">
                Get test ETH from Alchemy →
              </a>
            </p>
          )}
          {state.hint === 'need_external_wallet' && (
            <p className="mt-2 text-white/70 text-[10px] leading-relaxed">
              The InterwovenKit embedded wallet does not surface a transaction-approval modal
              for non-Initia EVM contract calls. Connect <strong>MetaMask</strong> or <strong>Rabby</strong> on
              Arbitrum Sepolia and retry.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
