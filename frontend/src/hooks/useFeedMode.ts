/**
 * useFeedMode — single hook owning the active feed mode + per-mode swipe index.
 *
 * Single Responsibility: state-management for which mode is active and where
 * each mode's swipe deck is positioned. No UI concerns, no fetch concerns.
 *
 * Persistence:
 *  - Active mode  → URL search param (`?mode=tokens|news`) — shareable, back/forward works
 *  - Per-mode idx → localStorage map  (`kinetic_feed_index_v1`)             — survives reloads
 *  - Last mode    → localStorage key  (`kinetic_feed_mode_v1`)              — fallback when URL is bare
 *
 * URL is the canonical truth for active mode. localStorage is fallback only.
 */
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FEED_MODES, getMode, type FeedMode } from '../config/cardModes';

const STORAGE_INDEX = 'kinetic_feed_index_v1';
const STORAGE_MODE = 'kinetic_feed_mode_v1';

function safeRead<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function safeWrite(key: string, value: unknown) {
  try {
    localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
  } catch {
    /* quota / private mode — non-fatal */
  }
}

function safeReadString(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function useFeedMode() {
  const [params, setParams] = useSearchParams();
  const [indices, setIndices] = useState<Record<string, number>>(() =>
    safeRead<Record<string, number>>(STORAGE_INDEX, {})
  );

  const urlMode = params.get('mode');
  const storedMode = safeReadString(STORAGE_MODE);
  const activeMode: FeedMode = getMode(urlMode ?? storedMode);

  // Reconcile URL with the resolved active mode (without polluting history).
  useEffect(() => {
    if (urlMode !== activeMode.id) {
      setParams(
        (prev) => {
          const sp = new URLSearchParams(prev);
          sp.set('mode', activeMode.id);
          return sp;
        },
        { replace: true }
      );
    }
  }, [activeMode.id, urlMode, setParams]);

  const setActiveMode = useCallback(
    (id: string) => {
      const next = getMode(id);
      setParams(
        (prev) => {
          const sp = new URLSearchParams(prev);
          sp.set('mode', next.id);
          return sp;
        },
        { replace: true }
      );
      safeWrite(STORAGE_MODE, next.id);
    },
    [setParams]
  );

  const currentIndex = indices[activeMode.id] ?? 0;

  const setCurrentIndex = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setIndices((prev) => {
        const old = prev[activeMode.id] ?? 0;
        const next = typeof updater === 'function' ? updater(old) : updater;
        if (next === old) return prev;
        const result = { ...prev, [activeMode.id]: next };
        safeWrite(STORAGE_INDEX, result);
        return result;
      });
    },
    [activeMode.id]
  );

  return {
    activeMode,
    setActiveMode,
    modes: FEED_MODES,
    currentIndex,
    setCurrentIndex,
  };
}
