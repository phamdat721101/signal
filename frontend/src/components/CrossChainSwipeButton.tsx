/**
 * CrossChainSwipeButton — 2-stage cross-chain swipe with LiFi route preview.
 *
 * Stage 1 (REVIEW): user clicks `APE` / `FADE`.
 *   - Fetches `/somnia-api/lifi-quote` → receives `routeSummary` + tx data.
 *   - Renders a route panel: provider, ETA, fees, slippage.
 *   - Button switches to "Confirm — sign once".
 *
 * Stage 2 (SIGN): user clicks Confirm.
 *   - wagmi `sendTransactionAsync` triggers wallet.
 *   - On signature, the Arbiscan link is rendered immediately (we have the
 *     origin tx hash as soon as the wallet returns) and we report it back to
 *     the backend so the relay can correlate.
 *
 * Stage 3 (POLL): the status query runs at 2s cadence. EXECUTED → also shows
 *     destination Somnscan link + prophecy market link.
 *
 * SOLID:
 *   - SRP: one card-swipe interaction owned here. Page-layout + deck rendering
 *     stays in the page.
 *   - OCP: the route renderer is a pure function of `routeSummary`; new fields
 *     (slippage warnings, MEV-safe badge, …) drop in without touching state.
 */
import { useEffect, useState } from 'react';
import { useSendTransaction } from 'wagmi';
import {
  useLifiQuote, useLifiIntentStatus, reportOriginTx,
  type IntentStatus, type LifiQuoteResponse,
} from '../hooks/useLifi';

export interface CrossChainSwipeButtonProps {
  cardId: number;
  prophecyMarketId: number;
  symbol: string;
  context: string;
  swipeStakeUsdc: bigint;
  fromChain: number;
  fromToken: `0x${string}`;
  userAddress: `0x${string}` | undefined;
  verdict: 'APE' | 'FADE';
  onCompleted?: (verdictId: number) => void;
}

type Stage = 'IDLE' | 'QUOTING' | 'REVIEW' | 'SIGNING' | 'TRACKING';

export default function CrossChainSwipeButton(props: CrossChainSwipeButtonProps) {
  const [stage, setStage] = useState<Stage>('IDLE');
  const [quote, setQuote] = useState<LifiQuoteResponse | null>(null);
  const [intentId, setIntentId] = useState<string | null>(null);
  const [originTx, setOriginTx] = useState<`0x${string}` | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  const { mutateAsync: getQuote } = useLifiQuote();
  const { sendTransactionAsync } = useSendTransaction();
  const status = useLifiIntentStatus(intentId);
  const data = status.data;

  useEffect(() => {
    const term: IntentStatus | undefined = data?.status === 'EXECUTED' || data?.status === 'FAILED_REFUNDED'
      ? data.status : undefined;
    if (term === 'EXECUTED' && data?.verdict_id != null && props.onCompleted) {
      props.onCompleted(data.verdict_id);
    }
  }, [data?.status, data?.verdict_id]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function startQuote() {
    setErrorText(null);
    if (!props.userAddress) { setErrorText('Connect wallet first'); return; }
    setStage('QUOTING');
    try {
      const q = await getQuote({
        fromChain: props.fromChain,
        fromToken: props.fromToken,
        swipeStakeUsdc: Number(props.swipeStakeUsdc),
        prophecyMarketId: props.prophecyMarketId,
        userAddress: props.userAddress,
        symbol: props.symbol,
        context: `${props.context} | swipe=${props.verdict}`,
      });
      setQuote(q);
      setIntentId(q.intent_id);
      setStage('REVIEW');
    } catch (e: unknown) {
      setErrorText(e instanceof Error ? e.message : 'Quote failed');
      setStage('IDLE');
    }
  }

  async function confirmAndSign() {
    if (!quote || !intentId) return;
    setStage('SIGNING');
    setErrorText(null);
    try {
      const txHash = await sendTransactionAsync({
        to:    quote.transaction_request.to,
        data:  quote.transaction_request.data,
        value: BigInt(quote.transaction_request.value || '0'),
        gas:   BigInt(quote.transaction_request.gas_limit || '300000'),
        chainId: props.fromChain,
      });
      setOriginTx(txHash);
      // Fire-and-forget: tells backend so the relay (or testnet auto-sim) can pick up.
      reportOriginTx(intentId, txHash).catch(() => undefined);
      setStage('TRACKING');
    } catch (e: unknown) {
      setErrorText(e instanceof Error ? e.message : 'Signature rejected');
      setStage('REVIEW');
    }
  }

  function reset() {
    setStage('IDLE'); setQuote(null); setIntentId(null); setOriginTx(null); setErrorText(null);
  }

  const verdictBg   = props.verdict === 'APE' ? 'bg-emerald-500' : 'bg-rose-500';
  const verdictIcon = props.verdict === 'APE' ? '🦍' : '🚫';

  // ── Render ───────────────────────────────────────────────────────
  return (
    <div className="space-y-3">
      {stage === 'IDLE' && (
        <button
          type="button"
          onClick={startQuote}
          disabled={!props.userAddress}
          aria-label={`${props.verdict} — get LiFi route preview`}
          className={`${verdictBg} text-white font-bold py-2.5 px-4 rounded-lg w-full transition disabled:opacity-50`}
        >
          {verdictIcon}  {props.verdict} — preview route
        </button>
      )}

      {stage === 'QUOTING' && (
        <button disabled className="bg-zinc-700 text-zinc-300 py-2.5 px-4 rounded-lg w-full">
          Building LiFi route…
        </button>
      )}

      {stage === 'REVIEW' && quote && (
        <RoutePanel
          quote={quote}
          stakeUsdc={props.swipeStakeUsdc}
          onConfirm={confirmAndSign}
          onCancel={reset}
          confirmBg={verdictBg}
          verdictLabel={`${verdictIcon} ${props.verdict}`}
        />
      )}

      {stage === 'SIGNING' && (
        <button disabled className="bg-zinc-700 text-zinc-300 py-2.5 px-4 rounded-lg w-full">
          Sign in wallet…
        </button>
      )}

      {(stage === 'TRACKING' || stage === 'SIGNING') && intentId && (
        <SwipeStatusPanel
          intentId={intentId}
          originTx={originTx}
          arbiscanBase={(import.meta.env.VITE_ARBISCAN_TX_BASE_URL as string) || 'https://sepolia.arbiscan.io/tx/'}
          status={data?.status}
          payload={data}
        />
      )}

      {errorText && <p role="alert" className="text-xs text-rose-400 break-words">{errorText}</p>}
    </div>
  );
}

// ── Route preview panel (Stage REVIEW) ──────────────────────────────
function RoutePanel({
  quote, stakeUsdc, onConfirm, onCancel, confirmBg, verdictLabel,
}: {
  quote: LifiQuoteResponse;
  stakeUsdc: bigint;
  onConfirm: () => void;
  onCancel: () => void;
  confirmBg: string;
  verdictLabel: string;
}) {
  const r = quote.route_summary;
  const isStub = r.provider === 'kinetic-testnet-stub';
  const stake = (Number(stakeUsdc) / 1_000_000).toFixed(2);

  return (
    <div className="rounded-lg border border-white/10 bg-zinc-900 p-3 space-y-3">
      <div className="flex justify-between items-center">
        <p className="text-[11px] uppercase tracking-widest text-zinc-400">LiFi route preview</p>
        {isStub && (
          <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300" title="LiFi has no testnet route — backend will simulate the bridge so the demo flow completes end-to-end.">
            TESTNET SIM
          </span>
        )}
      </div>

      <div className="text-sm grid grid-cols-2 gap-y-1 text-zinc-200 font-mono">
        <span className="text-zinc-500">via</span>      <span className="text-right">{r.provider}</span>
        <span className="text-zinc-500">stake</span>    <span className="text-right">${stake}</span>
        <span className="text-zinc-500">eta</span>      <span className="text-right">~{r.estimated_seconds}s</span>
        <span className="text-zinc-500">fee</span>      <span className="text-right">${r.fees_usd.toFixed(3)}</span>
        <span className="text-zinc-500">slippage</span> <span className="text-right">{r.slippage_bps} bps</span>
      </div>

      <div className="flex gap-2 pt-1">
        <button
          onClick={onConfirm}
          className={`${confirmBg} text-white text-sm font-bold py-2 px-3 rounded flex-1`}
          aria-label={`Confirm ${verdictLabel} — sign once to bridge USDC and lock verdict on Somnia`}
        >
          Confirm — sign once
        </button>
        <button
          onClick={onCancel}
          className="bg-zinc-700 text-zinc-200 text-sm font-medium py-2 px-3 rounded"
          aria-label="Cancel and close route preview"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Status panel (Stage SIGNING + TRACKING) ─────────────────────────
function SwipeStatusPanel({
  intentId, originTx, arbiscanBase, status, payload,
}: {
  intentId: string;
  originTx: `0x${string}` | null;
  arbiscanBase: string;
  status: IntentStatus | undefined;
  payload: ReturnType<typeof useLifiIntentStatus>['data'];
}) {
  const lines: Record<IntentStatus, string> = {
    PENDING:          'Bridging your USDC to Somnia…',
    DELIVERED:        'Funds delivered. Generating verdict…',
    EXECUTED:         payload?.verdict_str
      ? `Verdict locked: ${payload.verdict_str}`
      : (payload?.verdict_id ? `Verdict locked (verdict #${payload.verdict_id})` : 'Verdict locked'),
    FAILED_REFUNDED:  'Bridge failed. Funds refund to origin (~30 min via LiFi reverse-intent).',
  };
  const text = (status && lines[status]) || lines.PENDING;
  // Surface Arbiscan link as soon as we have the origin tx — don't wait for EXECUTED.
  const arbiscan = payload?.arbiscan_url
    || (originTx ? `${arbiscanBase}${originTx}` : null);

  return (
    <div className="rounded-lg border border-white/10 bg-zinc-900 p-3 text-sm space-y-2">
      <p className="font-mono text-zinc-200">{text}</p>
      <p className="text-[11px] text-zinc-500">Intent: {intentId}</p>

      <div className="flex flex-col gap-1 pt-1">
        {arbiscan && (
          <a href={arbiscan} target="_blank" rel="noopener noreferrer"
             className="text-xs text-sky-400 hover:underline"
             aria-label="View origin transaction on Arbiscan">
            🔗 View origin tx on Arbiscan
          </a>
        )}
        {status === 'EXECUTED' && payload?.somnscan_url && (
          <a href={payload.somnscan_url} target="_blank" rel="noopener noreferrer"
             className="text-xs text-sky-400 hover:underline"
             aria-label="View destination transaction on Somnscan">
            🔗 View destination tx on Somnscan
          </a>
        )}
        {status === 'EXECUTED' && payload?.prophecy_market_url && (
          <a href={payload.prophecy_market_url} target="_blank" rel="noopener noreferrer"
             className="text-xs text-sky-400 hover:underline"
             aria-label="View prophecy market">
            🔗 View prophecy market
          </a>
        )}
      </div>
    </div>
  );
}
