/**
 * Feed mode configuration — single source of truth for the header mode picker.
 *
 * SOLID: Open/Closed — add a new mode by appending one entry. No code changes
 * elsewhere required (Layout, ModePicker, Feed all consume FEED_MODES). When
 * the taxonomy stabilizes we'll move this to a backend endpoint
 * (`GET /api/feed/modes`) and keep the same shape.
 *
 * `cardTypes` must reference real `card_type` values produced by the backend
 * pipeline (see backend/app/content_engine.py + scheduler.py).
 *
 * `hidden` — mode is reachable via `?mode=<id>` deep-link but is omitted from
 * the picker UI. Used for QA-only or sunsetting modes whose backend data
 * still feeds the paid agent API but is no longer surfaced to consumers.
 */
export type FeedMode = {
  readonly id: string;
  readonly label: string;
  readonly emoji: string;
  readonly description: string;
  readonly cardTypes: readonly string[];
  readonly hidden?: boolean;
  /**
   * Optional chain id required to execute on-chain transactions for this
   * mode. Reading the deck is unrestricted; only the swipe handler enforces
   * the chain. Modes without `executionChainId` run on the app's default
   * chain (Initia testnet) just like every other mode.
   *
   * Set to 50312 for the prediction mode so users on Initia / Base can
   * still browse Prophecy.social cards and only get a switch popup when
   * they intentionally APE/FADE.
   */
  readonly executionChainId?: number;
};

export const FEED_MODES: readonly FeedMode[] = [
  {
    id: 'tokens',
    label: 'Tokens',
    emoji: '🪙',
    description: 'Predict price moves on tradeable tokens',
    cardTypes: ['trading', 'gem'],
  },
  {
    id: 'liquidity_pools',
    label: 'Liquidity Pools',
    emoji: '🌊',
    description: 'Read-only LP positions with AI-suggested ranges — opens on the host DEX',
    cardTypes: ['pool'],
  },
  {
    id: 'vaults',
    label: 'Vaults',
    emoji: '⚓',
    description: 'SoDex passive-yield vaults — live MAG7 NAV, click through to deposit',
    cardTypes: ['vault'],
  },
  {
    id: 'trading_signal',
    label: 'Trading Signals',
    emoji: '⚡',
    description: 'AI verdicts you can execute on SoDex perps testnet',
    cardTypes: ['trading_signal'],
  },
  {
    // Prophecy.social prediction-card mode. Reads sourced from Somnia
    // mainnet 5031 by the backend pipeline; swipes lock on testnet 50312
    // (existing Kinetic surface). Browse-anywhere / write-Somnia is
    // intentional — the chain switch fires only on a deliberate swipe.
    id: 'prediction',
    label: 'Predictions',
    emoji: '🔮',
    description: 'Prophecy.social markets — sports, crypto, politics, culture. Swipes lock on Somnia.',
    cardTypes: ['prediction'],
    executionChainId: 50312,
  },
  {
    // News mode is hidden from the picker (consumer feed) but still resolves
    // via `?mode=news` so QA / dev links keep working. Backend continues to
    // generate insight/macro_desk/whale_alert cards for the paid agent API.
    id: 'news',
    label: 'News',
    emoji: '📰',
    description: 'Macro, ETF flows, whale alerts & insights',
    cardTypes: [
      'insight',
      'macro_desk',
      'whale_alert',
      'index',
      'index_battle',
      'sector',
      'whale',
    ],
    hidden: true,
  },
] as const;

export const DEFAULT_MODE = FEED_MODES[0];

/** Resolve a mode id string (from URL/storage) to a valid FeedMode. */
export function getMode(id?: string | null): FeedMode {
  if (!id) return DEFAULT_MODE;
  return FEED_MODES.find((m) => m.id === id) ?? DEFAULT_MODE;
}

/** Modes shown in the picker UI. Hidden modes are still reachable via URL. */
export const VISIBLE_FEED_MODES: readonly FeedMode[] = FEED_MODES.filter((m) => !m.hidden);
