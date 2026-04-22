import { useState } from 'react';

const steps = [
  { icon: 'rocket_launch', title: 'Swipe Right = APE', sub: 'Go long on tokens you believe in', color: '#8eff71' },
  { icon: 'close', title: 'Swipe Left = FADE', sub: 'Pass on tokens you don\'t trust', color: '#ff7166' },
  { icon: 'verified', title: 'Your Alpha Has Receipts', sub: 'Every call is recorded on-chain', color: '#bf81ff' },
];

export default function Onboarding({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const s = steps[step];

  return (
    <div className="fixed inset-0 z-50 bg-[#0e0e0e] flex flex-col items-center justify-center px-8">
      <span className="material-symbols-outlined text-7xl mb-6" style={{ color: s.color }}>{s.icon}</span>
      <h1 className="font-headline text-2xl text-white mb-2" style={{ color: s.color }}>{s.title}</h1>
      <p className="font-body text-[#adaaaa] text-sm mb-10">{s.sub}</p>

      {step < 2 ? (
        <button onClick={() => setStep(step + 1)} className="font-label text-sm uppercase tracking-widest text-white border border-[#494847] rounded-full px-8 py-3">
          Next
        </button>
      ) : (
        <button onClick={onComplete} className="font-label text-sm uppercase tracking-widest rounded-full px-8 py-3 text-[#0e0e0e]" style={{ backgroundColor: s.color }}>
          Connect Wallet &amp; Start
        </button>
      )}

      <div className="flex gap-2 mt-10">
        {steps.map((_, i) => (
          <div key={i} className="w-2 h-2 rounded-full" style={{ backgroundColor: i === step ? s.color : '#494847' }} />
        ))}
      </div>
    </div>
  );
}
