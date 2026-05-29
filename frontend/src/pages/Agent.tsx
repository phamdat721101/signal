/**
 * /agent — cyber-terminal command center for paid Morph Hoodi services.
 *
 * Layout:
 *   [hero]                                — system status strip, public
 *   [pre-flight]   inside <ChainGate>     — wallet + USDC balance + faucets
 *   [bundle grid]                         — copy-only prompt cards (any chain)
 *      └─ <TryItRunner>  inside <ChainGate>  — non-custodial paid call
 *
 * Read-only stays public; mutating actions are gated to chain 2910 only.
 */
import { useMemo, useState } from 'react';
import { useAccount, useReadContract } from 'wagmi';
import { erc20Abi, formatUnits } from 'viem';
import ChainGate from '../components/ChainGate';
import { config, MORPH_HOODI_USDC_ADDRESS } from '../config';
import { BUNDLES, type Bundle, fillVars, formatPrice } from './agent/bundles';
import TryItRunner from './agent/TryItRunner';

const PERSONA_COLOR: Record<Bundle['persona'], string> = {
  analyst: 'text-cyber-green border-cyber-green',
  oracle:  'text-cyber-cyan border-cyber-cyan',
  forensic:'text-cyber-pink border-cyber-pink',
};

function PreflightStrip() {
  const { address } = useAccount();
  const { data: bal, isLoading } = useReadContract({
    chainId: config.morphHoodi.chainId,
    address: MORPH_HOODI_USDC_ADDRESS,
    abi: erc20Abi,
    functionName: 'balanceOf',
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 15_000 },
  });
  const usdc = bal ? Number(formatUnits(bal as bigint, 6)) : 0;
  const usdcFaucet = config.morphHoodi.usdcFaucetUrl;

  return (
    <div className="border border-cyber-outline bg-cyber-carbon p-4 font-cyber text-xs flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-cyber-green animate-pulse" />
        <span className="uppercase tracking-widest text-white/60">Connected</span>
        <span className="text-cyber-green">{address ? `${address.slice(0, 6)}…${address.slice(-4)}` : '—'}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="uppercase tracking-widest text-white/60">USDC</span>
        <span className="text-cyber-green">{isLoading ? '…' : usdc.toFixed(3)}</span>
      </div>
      {usdcFaucet ? (
        <a href={usdcFaucet} target="_blank" rel="noopener noreferrer"
           className="text-cyber-cyan hover:underline uppercase tracking-widest">
          Get test USDC →
        </a>
      ) : (
        <span className="text-white/40 uppercase tracking-widest">USDC faucet · operator-supplied</span>
      )}
    </div>
  );
}

function BundleCard({ bundle }: { bundle: Bundle }) {
  const [vars, setVars] = useState<Record<string, string>>(
    () => Object.fromEntries(bundle.vars.map((v) => [v.key, v.default])),
  );
  const filledPrompt = useMemo(() => fillVars(bundle.prompt, vars), [bundle.prompt, vars]);
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    await navigator.clipboard.writeText(filledPrompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Token-aware highlighting of `{{VAR}}` slots in the prompt block.
  const segments = filledPrompt.split(/(\b\d+(?:\.\d+)?\s*USDC\b|https?:\/\/[^\s]+|morph-hoodi-testnet)/g);

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
        <span className="text-cyber-green font-cyber text-sm whitespace-nowrap">{formatPrice(bundle.priceUsdc)}</span>
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
        {segments.map((seg, i) => /^https?|USDC|morph-hoodi-testnet/.test(seg)
          ? <span key={i} className="text-cyber-green">{seg}</span>
          : <span key={i}>{seg}</span>)}
      </pre>

      <footer className="px-4 py-3 border-t border-cyber-outline flex items-center justify-between gap-3">
        <button onClick={onCopy}
          className="border border-cyber-green text-cyber-green font-cyber-display text-[11px] uppercase tracking-widest px-3 py-1.5 hover:bg-cyber-green/10 active:scale-95 transition">
          {copied ? '✓ Copied' : '⧉ Copy Bundle'}
        </button>
        <ChainGate chainId={config.morphHoodi.chainId}>
          <TryItRunner bundle={bundle} values={vars} />
        </ChainGate>
      </footer>
    </div>
  );
}

export default function Agent() {
  return (
    <div className="min-h-full bg-cyber-carbon text-white">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Hero */}
        <header className="border border-cyber-outline bg-cyber-surface p-6">
          <p className="text-cyber-green font-cyber text-[11px] uppercase tracking-widest">Agent Command Center</p>
          <h1 className="font-cyber-display font-bold text-3xl uppercase mt-1">Pay-per-call agent data</h1>
          <p className="text-white/60 text-sm mt-2 font-cyber max-w-2xl">
            Five paid endpoints on <span className="text-cyber-green">Morph Hoodi Testnet</span>.
            Copy a one-line prompt for any external LLM, or run it in-app — wallet pays USDC,
            sponsor pays gas (EIP-3009), 0 ETH required from you.
          </p>
        </header>

        {/* Gated zone — preflight + runners */}
        <ChainGate chainId={config.morphHoodi.chainId}>
          <PreflightStrip />
        </ChainGate>

        {/* Bundle grid — copy works on any chain. Try-It (inside each card footer) is gated. */}
        <section className="grid gap-5 md:grid-cols-2">
          {BUNDLES.map((b) => <BundleCard key={b.id} bundle={b} />)}
        </section>
      </div>
    </div>
  );
}
