/**
 * /agent — pay-per-call agent data terminal.
 *
 * Rail-aware: works on any chain registered in `bundles.ts::RAILS`. The hero,
 * preflight balance, prompt, URL, and Try-It runner all derive from the
 * rail of the currently connected chain. Adding a new rail is a one-row
 * edit in `RAILS` — no UI changes here.
 *
 * Layout:
 *   [hero]                                    — public, lists supported rails
 *   [pre-flight]      inside <ChainGate>      — wallet + token balance
 *   [bundle grid]                             — copy + Try-It (rail-driven)
 */
import { useMemo, useState } from 'react';
import { useAccount, useChainId, useReadContract } from 'wagmi';
import { erc20Abi, formatUnits } from 'viem';
import ChainGate from '../components/ChainGate';
import {
  BUNDLES, type Bundle, fillVars, getRail, renderPrompt, RAILS, SUPPORTED_RAIL_IDS,
  type RailConfig,
} from './agent/bundles';
import TryItRunner from './agent/TryItRunner';

const PERSONA_COLOR: Record<Bundle['persona'], string> = {
  analyst: 'text-cyber-green border-cyber-green',
  oracle:  'text-cyber-cyan border-cyber-cyan',
  forensic:'text-cyber-pink border-cyber-pink',
};

/** Rail picked from the connected chain; falls back to the first registered rail. */
function useActiveRail(): RailConfig {
  const chainId = useChainId();
  return getRail(chainId) ?? RAILS[SUPPORTED_RAIL_IDS[0]];
}

function PreflightStrip({ rail }: { rail: RailConfig }) {
  const { address } = useAccount();
  const { data: bal, isLoading } = useReadContract({
    chainId: rail.chainId,
    address: rail.token.address,
    abi: erc20Abi,
    functionName: 'balanceOf',
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 15_000 },
  });
  const balance = bal ? Number(formatUnits(bal as bigint, rail.token.decimals)) : 0;
  const balDigits = rail.token.decimals >= 18 ? 8 : 3;

  return (
    <div className="border border-cyber-outline bg-cyber-carbon p-4 font-cyber text-xs flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-cyber-green animate-pulse" />
        <span className="uppercase tracking-widest text-white/60">Connected</span>
        <span className="text-cyber-green">{address ? `${address.slice(0, 6)}…${address.slice(-4)}` : '—'}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="uppercase tracking-widest text-white/60">{rail.token.symbol}</span>
        <span className="text-cyber-green">{isLoading ? '…' : balance.toFixed(balDigits)}</span>
      </div>
      {rail.tokenFaucetUrl ? (
        <a href={rail.tokenFaucetUrl} target="_blank" rel="noopener noreferrer"
           className="text-cyber-cyan hover:underline uppercase tracking-widest">
          Get test {rail.token.symbol} →
        </a>
      ) : (
        <a href={rail.gasFaucetUrl} target="_blank" rel="noopener noreferrer"
           className="text-cyber-cyan hover:underline uppercase tracking-widest">
          Get test {rail.gasSymbol} →
        </a>
      )}
    </div>
  );
}

function BundleCard({ bundle, rail }: { bundle: Bundle; rail: RailConfig }) {
  const [vars, setVars] = useState<Record<string, string>>(
    () => Object.fromEntries(bundle.vars.map((v) => [v.key, v.default])),
  );
  const filledPrompt = useMemo(() => fillVars(renderPrompt(rail, bundle, vars), vars), [rail, bundle, vars]);
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    await navigator.clipboard.writeText(filledPrompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Token-aware highlighting: USDC|<symbol>|<chain key>|http URL.
  const tokenWord = rail.token.symbol;
  const chainWord = rail.nPaymentKey;
  // Build a regex with the rail-specific tokens. Escape regex-meaningful chars.
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const splitRe = new RegExp(`(\\b\\d+(?:\\.\\d+)?\\s*${esc(tokenWord)}\\b|https?:\\/\\/[^\\s]+|${esc(chainWord)})`, 'g');
  const segments = filledPrompt.split(splitRe);

  return (
    <div className="border border-cyber-outline bg-cyber-surface flex flex-col">
      <header className="bg-cyber-surface-high border-b border-cyber-outline px-4 py-3 flex items-start justify-between gap-3">
        <div>
          <span className={`text-[10px] uppercase tracking-widest border px-1.5 py-0.5 ${PERSONA_COLOR[bundle.persona]}`}>
            {bundle.persona}
          </span>
          <h3 className="font-cyber-display font-bold uppercase text-white mt-2">{bundle.title}</h3>
          <p className="text-white/60 text-xs font-cyber mt-1">{bundle.tagline}</p>
        </div>
        <span className="text-cyber-green font-cyber text-sm whitespace-nowrap">{bundle.priceUsd}</span>
      </header>

      {bundle.vars.length > 0 && (
        <div className="px-4 py-3 border-b border-cyber-outline flex flex-wrap gap-3">
          {bundle.vars.map((v) => (
            <label key={v.key} className="flex flex-col gap-1 font-cyber text-[11px] text-white/60">
              <span className="uppercase tracking-widest">{v.label}</span>
              <input
                value={vars[v.key]}
                onChange={(e) => setVars((s) => ({ ...s, [v.key]: e.target.value }))}
                placeholder={v.placeholder}
                className="bg-cyber-carbon border border-cyber-outline text-white px-2 py-1 w-32 focus:border-cyber-green outline-none"
              />
            </label>
          ))}
        </div>
      )}

      <pre className="bg-cyber-carbon p-4 font-cyber text-[11px] leading-relaxed text-white/80 whitespace-pre-wrap overflow-x-auto">
        {segments.map((seg, i) =>
          new RegExp(`^https?|${esc(tokenWord)}|${esc(chainWord)}`).test(seg)
            ? <span key={i} className="text-cyber-green">{seg}</span>
            : <span key={i}>{seg}</span>)}
      </pre>

      <footer className="px-4 py-3 border-t border-cyber-outline flex items-center justify-between gap-3">
        <button onClick={onCopy}
          className="border border-cyber-green text-cyber-green font-cyber-display text-[11px] uppercase tracking-widest px-3 py-1.5 hover:bg-cyber-green/10 active:scale-95 transition">
          {copied ? '✓ Copied' : '⧉ Copy Bundle'}
        </button>
        <ChainGate chainIds={SUPPORTED_RAIL_IDS}>
          <TryItRunner bundle={bundle} values={vars} rail={rail} />
        </ChainGate>
      </footer>
    </div>
  );
}

export default function Agent() {
  const rail = useActiveRail();
  // Hero supported-rails copy lists every registered rail name.
  const railNames = SUPPORTED_RAIL_IDS.map((id) => RAILS[id].name);

  return (
    <div className="min-h-full bg-cyber-carbon text-white">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Hero */}
        <header className="border border-cyber-outline bg-cyber-surface p-6">
          <p className="text-cyber-green font-cyber text-[11px] uppercase tracking-widest">Agent Command Center</p>
          <h1 className="font-cyber-display font-bold text-3xl uppercase mt-1">Pay-per-call agent data</h1>
          <p className="text-white/60 text-sm mt-2 font-cyber max-w-2xl">
            Five paid endpoints on{' '}
            <span className="text-cyber-green">{railNames.join(' or ')} testnet</span>.
            Copy a one-line prompt for any external LLM, or run it in-app — the wallet pays{' '}
            <span className="text-cyber-green">{rail.token.symbol}</span> on{' '}
            <span className="text-cyber-green">{rail.name}</span>.
          </p>
        </header>

        {/* Gated zone — preflight + runners. Allowed on any registered rail. */}
        <ChainGate chainIds={SUPPORTED_RAIL_IDS}>
          <PreflightStrip rail={rail} />
        </ChainGate>

        {/* Bundle grid — copy works on any chain (renders for the active rail).
            Try-It (inside each card footer) is gated to a supported rail. */}
        <section className="grid gap-5 md:grid-cols-2">
          {BUNDLES.map((b) => <BundleCard key={b.id} bundle={b} rail={rail} />)}
        </section>
      </div>
    </div>
  );
}
