import { useEffect, useState } from 'react';

const API = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

interface Challenge {
  id: number; type: string; title: string; description: string;
  emoji: string; options: string[]; reward_xp: number; expires_at: string;
}

export default function Challenges() {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [submitted, setSubmitted] = useState<Set<number>>(new Set());

  useEffect(() => {
    fetch(`${API}/api/challenges`).then(r => r.json()).then(d => setChallenges(d.challenges || [])).catch(() => {});
  }, []);

  const submit = async (id: number) => {
    const answer = answers[id];
    if (!answer) return;
    await fetch(`${API}/api/challenges/${id}/enter`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user_address: '0x0', answer})
    });
    setSubmitted(s => new Set([...s, id]));
  };

  return (
    <div className="p-4 max-w-md mx-auto">
      <h1 className="text-2xl font-bold text-white mb-4">🎯 Daily Challenges</h1>
      {challenges.length === 0 && <p className="text-gray-500">No active challenges. Check back tomorrow!</p>}
      {challenges.map(c => (
        <div key={c.id} className="mb-4 p-4 rounded-2xl bg-[#1a1a1a] border border-gray-800">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-2xl">{c.emoji}</span>
            <h3 className="text-lg font-bold text-white">{c.title}</h3>
          </div>
          <p className="text-sm text-gray-400 mb-3">{c.description}</p>
          <p className="text-xs text-[#8eff71] mb-2">🏆 {c.reward_xp} XP</p>
          {submitted.has(c.id) ? (
            <p className="text-sm text-[#8eff71]">✅ Submitted!</p>
          ) : c.type === 'price_predict' ? (
            <div className="flex gap-2">
              <input type="number" placeholder="Your prediction..." className="flex-1 px-3 py-2 rounded-lg bg-[#0e0e0e] border border-gray-700 text-white text-sm" onChange={e => setAnswers({...answers, [c.id]: e.target.value})} />
              <button onClick={() => submit(c.id)} className="px-4 py-2 rounded-lg bg-[#bf81ff] text-white text-sm font-medium">Submit</button>
            </div>
          ) : (
            <div className="flex gap-2">
              {(c.options || []).map((opt, i) => (
                <button key={i} onClick={() => { setAnswers({...answers, [c.id]: opt}); submit(c.id); }} className="flex-1 px-3 py-2 rounded-lg bg-[#0e0e0e] border border-gray-700 text-white text-sm hover:border-[#bf81ff] transition">{opt}</button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
