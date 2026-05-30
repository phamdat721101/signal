/**
 * ModePicker — responsive picker for the feed mode.
 *
 * Single Responsibility: present a list of FEED_MODES, fire onSelect on tap,
 * close itself. No state ownership beyond "is open?". Parent owns activeId.
 *
 * Responsiveness (no extra deps):
 *  - Mobile (<md):  bottom-sheet rising from the bottom, full-width.
 *  - Desktop (≥md): popover anchored to anchorRef element.
 *
 * Renders into document.body via a portal so the overlay isn't trapped by
 * z-index of the sticky header.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FEED_MODES, type FeedMode } from '../config/cardModes';

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  activeId: string;
  onSelect: (id: string) => void;
  /** Element to anchor the desktop popover under. Mobile ignores this. */
  anchorRef?: React.RefObject<HTMLElement | null>;
}

/** Tiny inline media-query hook — avoids the transitive usehooks-ts dep. */
function useIsDesktop(): boolean {
  const [matches, setMatches] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : false
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(min-width: 768px)');
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);
  return matches;
}

export default function ModePicker({ open, onOpenChange, activeId, onSelect, anchorRef }: Props) {
  const isDesktop = useIsDesktop();
  const sheetRef = useRef<HTMLDivElement>(null);

  // Esc closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);

  if (!open) return null;

  // Desktop popover position — anchored under the trigger, clamped to viewport.
  let desktopStyle: React.CSSProperties | undefined;
  if (isDesktop && anchorRef?.current) {
    const r = anchorRef.current.getBoundingClientRect();
    const sheetW = 296;
    desktopStyle = {
      top: r.bottom + 8,
      left: Math.min(r.left, window.innerWidth - sheetW - 8),
    };
  }

  const sheetClass = isDesktop
    ? 'fixed bg-[#131313] border border-[#494847]/30 rounded-xl shadow-2xl w-[296px] p-2 z-[60]'
    : 'fixed left-0 right-0 bottom-0 bg-[#131313] rounded-t-2xl border-t border-[#494847]/30 p-3 pb-6 z-[60] animate-[slideUp_0.25s_ease-out]';

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[55] bg-black/60"
        onClick={() => onOpenChange(false)}
        aria-hidden
      />
      {/* Sheet */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label="Choose feed mode"
        className={sheetClass}
        style={desktopStyle}
        onClick={(e) => e.stopPropagation()}
      >
        {!isDesktop && <div className="w-10 h-1 bg-[#494847] rounded-full mx-auto mb-3" />}
        <div className="px-2 py-1 text-[10px] font-label uppercase tracking-widest text-[#494847]">
          Feed Mode
        </div>
        <div className="space-y-1">
          {FEED_MODES.map((m: FeedMode) => {
            const isActive = m.id === activeId;
            return (
              <button
                key={m.id}
                onClick={() => {
                  onSelect(m.id);
                  onOpenChange(false);
                }}
                className={`w-full text-left flex items-start gap-3 px-3 py-2.5 rounded-xl transition-colors ${
                  isActive ? 'bg-[#262626]' : 'hover:bg-[#1a1a1a] active:bg-[#1a1a1a]'
                }`}
              >
                <span className="text-2xl shrink-0 leading-none">{m.emoji}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-headline font-bold text-white text-sm">{m.label}</div>
                  <div className="text-[11px] text-[#adaaaa] mt-0.5 leading-snug">
                    {m.description}
                  </div>
                </div>
                {isActive && (
                  <span className="text-[#8eff71] shrink-0 mt-1 font-bold" aria-label="active">
                    ✓
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </>,
    document.body
  );
}
