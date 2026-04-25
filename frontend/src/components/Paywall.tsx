import { useNavigate } from 'react-router-dom';

export default function Paywall({ onDismiss }: { onDismiss: () => void }) {
  const navigate = useNavigate();
  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6">
      <div className="bg-[#131313] rounded-xl p-6 max-w-sm w-full text-center space-y-4 border border-[#494847]/20">
        <span className="material-symbols-outlined text-5xl text-[#bf81ff]" style={{ fontVariationSettings: "'FILL' 1" }}>lock</span>
        <h2 className="font-headline text-xl font-black text-white">Free Swipes Used</h2>
        <p className="text-[#adaaaa] text-sm">You've used your 5 free swipes today. Unlock unlimited swipes + full trading patterns.</p>
        <div className="bg-[#262626] p-3 rounded-lg">
          <div className="font-headline font-bold text-[#8eff71]">10 iUSD / day</div>
          <div className="font-label text-[10px] text-[#adaaaa]">Via SessionVault deposit</div>
        </div>
        <div className="flex gap-3">
          <button onClick={onDismiss} className="flex-1 bg-[#262626] text-[#adaaaa] font-headline font-bold py-3 rounded-lg">Maybe Later</button>
          <button onClick={() => { onDismiss(); navigate('/profile'); }} className="flex-1 ape-gradient text-[#0b5800] font-headline font-bold py-3 rounded-lg">Deposit</button>
        </div>
      </div>
    </div>
  );
}
