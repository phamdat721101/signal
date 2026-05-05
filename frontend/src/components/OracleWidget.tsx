import { useEffect, useState } from 'react';

const API = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

export function OracleWidget() {
  const [mood, setMood] = useState<{mood: string; emoji: string; take: string} | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/oracle/mood`).then(r => r.json()).then(setMood).catch(() => {});
  }, []);

  if (!mood || !mood.mood) return null;

  return (
    <div className="mb-4">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-2 rounded-xl bg-[#1a1a1a] border border-gray-800 hover:border-[#bf81ff]/50 transition"
      >
        <span className="text-lg">{mood.emoji}</span>
        <span className="text-sm text-gray-400">Oracle is feeling</span>
        <span className="text-sm font-bold text-white capitalize">{mood.mood}</span>
        <span className="ml-auto text-xs text-gray-600">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="mt-2 px-4 py-3 rounded-xl bg-[#1a1a1a] border border-gray-800">
          <p className="text-sm text-gray-300 italic">"{mood.take}"</p>
          <p className="text-xs text-gray-600 mt-1">— The Degen Oracle 🔮</p>
        </div>
      )}
    </div>
  );
}
