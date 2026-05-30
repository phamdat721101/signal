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
 */
export type FeedMode = {
  readonly id: string;
  readonly label: string;
  readonly emoji: string;
  readonly description: string;
  readonly cardTypes: readonly string[];
};

export const FEED_MODES: readonly FeedMode[] = [
  {
    id: 'tokens',
    label: 'Tokens',
    emoji: '🪙',
    description: 'Predict price moves on tradeable tokens',
    cardTypes: ['trading', 'gem', 'pool'],
  },
  {
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
  },
] as const;

export const DEFAULT_MODE = FEED_MODES[0];

/** Resolve a mode id string (from URL/storage) to a valid FeedMode. */
export function getMode(id?: string | null): FeedMode {
  if (!id) return DEFAULT_MODE;
  return FEED_MODES.find((m) => m.id === id) ?? DEFAULT_MODE;
}
