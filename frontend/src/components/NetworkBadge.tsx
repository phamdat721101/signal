/**
 * NetworkBadge — declares a chain identity inline on any surface.
 *
 * Per the UPGRADE-Header-NetworkUX proposal: the chain belongs to the content,
 * not the page chrome. Cards mount this badge to surface "this lives on X."
 *
 * SOLID:
 *   - Single responsibility: render a chain identity pill. Nothing else.
 *   - Open/closed: add a chain by adding one row to META. Zero edits elsewhere.
 *   - Interface segregation: prop is `chainId: number | undefined`. No Card or
 *     Wallet coupling. Caller composes context.
 *   - Returns null for unknown chain ids — clean degrade, no error.
 */

interface Props {
  chainId: number | undefined;
  /** Compact pill (default) vs expanded with tier label. */
  size?: 'sm' | 'md';
}

const META: Record<number, { name: string; color: string; tier: string }> = {
  2124225178762456: { name: 'Initia evm-1', color: '#8eff71', tier: 'Testnet' },
  8453:             { name: 'Base',        color: '#0052ff', tier: 'Mainnet' },
  50312:            { name: 'Somnia',      color: '#00d4aa', tier: 'Testnet' },
  421614:           { name: 'Arb Sepolia', color: '#28a0f0', tier: 'Testnet' },
};

export default function NetworkBadge({ chainId, size = 'sm' }: Props) {
  const m = META[chainId ?? 0];
  if (!m) return null;
  return (
    <span className="inline-flex items-center gap-1.5 bg-[#262626] px-2 py-0.5 rounded">
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: m.color }} />
      <span className="font-label text-[10px] font-bold uppercase tracking-widest text-white">
        {m.name}
      </span>
      {size === 'md' && (
        <span className="text-[#494847] text-[9px] font-label uppercase">{m.tier}</span>
      )}
    </span>
  );
}
