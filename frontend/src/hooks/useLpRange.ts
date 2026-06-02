/**
 * useLpRange — pure preset-to-(min,max) helper.
 *
 * Mirrors `backend/app/lp_math.range_for_preset` exactly so the FE preview
 * (chart range overlay, LpBattleCard) shows the same band the backend will
 * return from `/api/cards/{id}/lp-recipe`. Pure function, no I/O.
 *
 * Single Responsibility: range math + fixed-band fallback. No hooks state,
 * no React; this is a `use*` name only by convention. Keeps it trivially
 * unit-testable.
 */
export type LpPreset = 'conservative' | 'balanced' | 'aggressive';

export const LP_PRESET_K: Record<LpPreset, number> = {
  conservative: 2.0,
  balanced: 1.0,
  aggressive: 0.5,
};

const FIXED_BANDS: Record<LpPreset, [number, number]> = {
  conservative: [0.85, 1.15],
  balanced: [0.93, 1.07],
  aggressive: [0.97, 1.03],
};

export function useLpRange(
  priceCurr: number,
  sigma7d: number | null | undefined,
  preset: LpPreset
): { min: number; max: number; usingFallback: boolean } {
  if (priceCurr <= 0) return { min: 0, max: 0, usingFallback: true };
  if (sigma7d && sigma7d > 0) {
    const k = LP_PRESET_K[preset];
    const s = Math.min(sigma7d, 0.5); // clamp — matches backend
    return {
      min: priceCurr * (1 - k * s),
      max: priceCurr * (1 + k * s),
      usingFallback: false,
    };
  }
  const [lo, hi] = FIXED_BANDS[preset];
  return { min: priceCurr * lo, max: priceCurr * hi, usingFallback: true };
}
