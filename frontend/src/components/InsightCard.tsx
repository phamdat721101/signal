interface InsightCardProps {
  card: {
    id: number;
    hook: string;
    roast: string;
    metrics: Array<{ emoji: string; label: string; value: string }>;
    card_type: string;
    token_symbol?: string;
  };
  /** News-mode actions — when provided, replace the dismiss CTA with APE/FADE. */
  onApe?: () => void;
  onFade?: () => void;
  /** Legacy dismiss-only mode (Token-mode fallback / previous callers). */
  onDismiss?: (id: number) => void;
}

/**
 * InsightCard — institutional / market-intel card.
 *
 * Action footer is interface-driven: callers either pass {onApe,onFade}
 * (News-mode parity with TokenCard's conviction commit) OR {onDismiss}
 * (legacy passive read). Single Responsibility: render content + delegate
 * action semantics to the parent.
 */
export function InsightCard({ card, onApe, onFade, onDismiss }: InsightCardProps) {
  const hasActions = !!(onApe || onFade);
  return (
    <div className="rounded-2xl p-6 bg-gradient-to-br from-[#1a1a2e] to-[#16213e] border border-[#6366f1]/30">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-[#bf81ff] font-medium">💡 INSIGHT</div>
        <a
          href="https://sosovalue.com"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#6366f1]/15 hover:bg-[#6366f1]/25 transition-colors"
        >
          <span className="text-[9px] font-bold text-[#a5b4fc]">SoSoValue</span>
        </a>
      </div>
      <h3 className="text-xl font-bold text-white mb-2">{card.hook}</h3>
      <p className="text-gray-400 text-sm mb-4">{card.roast}</p>
      {card.metrics?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {card.metrics.map((m, i) => (
            <span key={i} className="px-3 py-1 rounded-full bg-[#bf81ff]/10 text-[#bf81ff] text-xs">
              {m.emoji} {m.label}: {m.value}
            </span>
          ))}
        </div>
      )}

      {hasActions ? (
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={onFade}
            className="bg-[#1a1a1a] border border-[#ff7166]/40 text-[#ff7166] font-bold py-2.5 rounded-xl text-sm active:scale-95 transition-transform"
          >
            💀 FADE
          </button>
          <button
            onClick={onApe}
            className="bg-gradient-to-r from-[#8eff71] to-[#4ade80] text-[#0b5800] font-black py-2.5 rounded-xl text-sm active:scale-95 transition-transform shadow-[0_0_15px_rgba(142,255,113,0.2)]"
          >
            🔥 APE
          </button>
        </div>
      ) : (
        <button
          onClick={() => onDismiss?.(card.id)}
          className="w-full py-2 rounded-xl bg-[#bf81ff]/20 text-[#bf81ff] text-sm font-medium hover:bg-[#bf81ff]/30 transition"
        >
          Got it 👍
        </button>
      )}
    </div>
  );
}
