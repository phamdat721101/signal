import type { Card } from '../hooks/useCards';

/**
 * PredictionCard — feed surface for Prophecy.social prediction markets.
 *
 * SOLID:
 *  - SRP: render-only. Swipe handlers are owned by the parent `Feed.tsx`.
 *  - OCP: card data model (Card) is shared with every other feed card; we
 *    just opt into the prediction-specific fields. New display sections
 *    can be added without touching Feed.tsx or the swipe pipeline.
 *
 * Read-everywhere, write-Somnia: this component renders identically on
 * any chain. The "🟢 Locks on Somnia" footer sets expectations so the
 * wallet switch popup that fires on swipe is never a surprise.
 */
const CATEGORY_PALETTE: Record<string, { tint: string; ring: string; label: string; gradient: string; emoji: string }> = {
  sports:   { tint: 'bg-blue-500/15',    ring: 'ring-blue-400/40',    label: 'SPORTS',   gradient: 'from-blue-600/40   via-sky-700/30    to-indigo-900/50',  emoji: '⚽' },
  crypto:   { tint: 'bg-orange-500/15',  ring: 'ring-orange-400/40',  label: 'CRYPTO',   gradient: 'from-orange-600/40 via-amber-700/30   to-rose-900/50',    emoji: '₿' },
  politics: { tint: 'bg-red-500/15',     ring: 'ring-red-400/40',     label: 'POLITICS', gradient: 'from-red-600/40    via-rose-700/30    to-purple-900/50',  emoji: '🗳' },
  culture:  { tint: 'bg-purple-500/15',  ring: 'ring-purple-400/40',  label: 'CULTURE',  gradient: 'from-purple-600/40 via-fuchsia-700/30 to-indigo-900/50',  emoji: '🎬' },
  general:  { tint: 'bg-zinc-500/15',    ring: 'ring-zinc-400/40',    label: 'MARKET',   gradient: 'from-zinc-700/40   via-slate-800/30   to-neutral-900/50', emoji: '🔮' },
};

// Topic glyph extraction — pure function. Pattern table is the only thing
// to extend when adding a new event class. Order matters: more-specific
// patterns (token tickers, sport names) win over generic category fallbacks.
const TOPIC_GLYPHS: Array<[RegExp, string]> = [
  // Crypto tickers — match standalone tokens or "$XYZ" mentions.
  [/\b(?:\$)?BTC\b|\bbitcoin\b/i,    '₿'],
  [/\b(?:\$)?ETH\b|\bethereum\b/i,   'Ξ'],
  [/\b(?:\$)?SOL\b|\bsolana\b/i,     '◎'],
  [/\b(?:\$)?XRP\b|\bripple\b/i,     '✕'],
  [/\b(?:\$)?DOGE\b|\bdogecoin\b/i,  'Ð'],
  [/\b(?:\$)?ADA\b|\bcardano\b/i,    '₳'],
  [/\b(?:\$)?BNB\b/i,                '🅱'],
  [/\b(?:\$)?MATIC\b|\bpolygon\b/i,  '🟣'],
  // Sports
  [/\bworld cup\b|\bsoccer\b|\bfootball\b|\bpremier league\b|\bla liga\b/i, '⚽'],
  [/\bnba\b|\bbasketball\b/i,        '🏀'],
  [/\bnfl\b|\bsuper bowl\b/i,        '🏈'],
  [/\btennis\b|\bwimbledon\b|\bus open\b/i, '🎾'],
  [/\bf1\b|\bformula 1\b|\bgrand prix\b/i,  '🏎'],
  [/\bolympics?\b/i,                 '🏅'],
  // Politics / events
  [/\belection\b|\bpresident\b|\bcongress\b|\bsenate\b/i, '🗳'],
  [/\bsupreme court\b|\bjudge\b/i,   '⚖'],
  // Culture
  [/\boscar\b|\bemmys?\b|\boscars?\b/i, '🏆'],
  [/\bgrammy\b|\balbum\b|\bsong\b/i, '🎵'],
  [/\bmovie\b|\bfilm\b|\bbox office\b/i, '🎬'],
  // Tech / business
  [/\bAI\b|\bchatgpt\b|\bopenai\b/i, '🧠'],
  [/\bSpaceX\b|\brocket\b|\blaunch\b/i, '🚀'],
];

function pickTopicGlyph(question: string, category: string): string {
  for (const [rx, glyph] of TOPIC_GLYPHS) {
    if (rx.test(question)) return glyph;
  }
  return CATEGORY_PALETTE[category]?.emoji ?? '🔮';
}

function categoryLabel(card: Card): string {
  const m = (card.metrics || []).find(
    (x): x is { emoji: string; label: string; value: string; sentiment: string } =>
      typeof x === 'object' && x?.label === 'category',
  );
  const v = (m?.value || 'general').toString();
  return CATEGORY_PALETTE[v] ? v : 'general';
}

function formatTimeRemaining(deadlineIso?: string): string {
  if (!deadlineIso) return '—';
  const ms = new Date(deadlineIso).getTime() - Date.now();
  if (Number.isNaN(ms) || ms <= 0) return 'Resolving';
  const mins = Math.floor(ms / 60_000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  if (days >= 1) return `${days}d ${hrs % 24}h`;
  if (hrs >= 1) return `${hrs}h ${mins % 60}m`;
  return `${mins}m`;
}

export default function PredictionCard({
  card,
  onApe,
  onFade,
}: {
  card: Card;
  onApe: () => void;
  onFade: () => void;
}) {
  const yesOdds = typeof card.prophecy_yes_odds_at_gen === 'number'
    ? card.prophecy_yes_odds_at_gen
    : 0.5;
  const yesPct = Math.round(yesOdds * 100);
  const noPct = 100 - yesPct;
  const cat = categoryLabel(card);
  const palette = CATEGORY_PALETTE[cat];
  const verdict = (card.verdict || 'WATCH').toUpperCase();
  const verdictColor = verdict === 'APE' ? 'text-[#8eff71]' : verdict === 'FADE' ? 'text-[#ff7166]' : 'text-white';
  const confidence = card.confidence ?? 0;

  return (
    <div className={`absolute inset-0 rounded-xl bg-[#1a1a1a] border border-white/10 ring-1 ${palette.ring} flex flex-col p-5`}>
      {/* Top row — category badge + countdown */}
      <div className="flex items-center justify-between">
        <span className={`px-2.5 py-1 text-[10px] font-cyber-display font-bold tracking-widest rounded ${palette.tint} text-white/90`}>
          🔮 {palette.label}
        </span>
        <span className="text-[11px] font-cyber text-white/60">
          ⏱ {formatTimeRemaining(card.prophecy_deadline)}
        </span>
      </div>

      {/* Hero illustration — image_url wins when set (e.g. OG scrape from
          prophecy.social); otherwise a deterministic gradient + topic glyph
          derived from the question. Graceful upgrade path: ship the
          illustration now, swap to images later without touching this file. */}
      <div className={`mt-3 h-24 rounded-lg overflow-hidden bg-gradient-to-br ${palette.gradient} relative ring-1 ${palette.ring}`}>
        {card.image_url ? (
          <img
            src={card.image_url}
            alt=""
            className="w-full h-full object-cover"
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
            loading="lazy"
          />
        ) : (
          <>
            {/* Soft bokeh dots — pure CSS, zero asset weight */}
            <div className="absolute -top-4 -left-4 w-20 h-20 rounded-full bg-white/5 blur-xl" />
            <div className="absolute -bottom-6 -right-2 w-24 h-24 rounded-full bg-white/5 blur-2xl" />
            {/* Centered topic glyph */}
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-6xl drop-shadow-[0_0_24px_rgba(255,255,255,0.18)]" aria-hidden>
                {pickTopicGlyph(card.token_name || card.hook || '', cat)}
              </span>
            </div>
          </>
        )}
      </div>

      {/* Question */}
      <h2 className="mt-3 text-lg leading-snug font-headline font-bold text-white line-clamp-4">
        {card.token_name || card.hook}
      </h2>

      {/* Hook line */}
      {card.hook && card.token_name && card.hook !== card.token_name && (
        <p className="mt-2 text-xs text-white/70 font-cyber line-clamp-3">{card.hook}</p>
      )}

      {/* Odds bar (inline; intentionally a single component to keep the
          file count low — extract to its own component only if we add a
          third use site). */}
      <div className="mt-auto">
        <div className="flex items-center justify-between text-[10px] font-cyber-display text-white/70 uppercase tracking-widest">
          <span className="text-[#8eff71]">YES {yesPct}%</span>
          <span className="text-[#ff7166]">NO {noPct}%</span>
        </div>
        <div className="mt-1 h-2 w-full rounded-full bg-white/10 overflow-hidden flex">
          <div className="h-full bg-[#8eff71]" style={{ width: `${yesPct}%` }} />
          <div className="h-full bg-[#ff7166]" style={{ width: `${noPct}%` }} />
        </div>

        {/* Verdict overlay */}
        <div className="mt-4 flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-white/50 font-cyber">Kinetic verdict</p>
            <p className={`text-lg font-headline font-black ${verdictColor}`}>
              {verdict}
              {confidence > 0 && <span className="ml-2 text-xs font-cyber text-white/60">{confidence}%</span>}
            </p>
          </div>
          <span className="text-[10px] text-white/50 font-cyber whitespace-nowrap">
            🟢 APE locks on Somnia · FADE off-chain
          </span>
        </div>

        {/* Action row */}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button
            onClick={onFade}
            className="py-3 rounded-lg border border-[#ff7166]/40 bg-[#ff7166]/10 text-[#ff7166] font-cyber-display font-bold uppercase tracking-widest text-sm active:scale-95 transition"
          >
            FADE 💨
          </button>
          <button
            onClick={onApe}
            className="py-3 rounded-lg border border-[#8eff71]/40 bg-[#8eff71]/10 text-[#8eff71] font-cyber-display font-bold uppercase tracking-widest text-sm active:scale-95 transition"
          >
            APE 🦍
          </button>
        </div>
      </div>
    </div>
  );
}
