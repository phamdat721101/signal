import { useNavigate } from 'react-router-dom';

export default function Paywall({ onDismiss, isConnected, onConnect }: { onDismiss: () => void; isConnected?: boolean; onConnect?: () => void }) {
  const navigate = useNavigate();
  const hoursLeft = 24 - new Date().getUTCHours();
  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6">
      <div className="bg-[#131313] rounded-xl p-6 max-w-sm w-full text-center space-y-4 border border-[#494847]/20">
        <span className="text-5xl">⚡</span>
        <h2 className="font-headline text-xl font-black text-white">Out of Energy</h2>
        <p className="text-[#adaaaa] text-sm">Every prediction builds your permanent on-chain reputation. Keep your streak alive.</p>
        <div className="bg-[#262626] p-3 rounded-lg space-y-1">
          <div className="font-headline font-bold text-[#8eff71]">⚡ Unlimited Energy</div>
          <div className="font-label text-xs text-[#adaaaa]">10 iUSD / day via SessionVault</div>
        </div>
        <div className="text-[10px] text-[#494847]">⏰ Free refill in ~{hoursLeft}h</div>
        <div className="flex gap-3">
          <button onClick={onDismiss} className="flex-1 bg-[#262626] text-[#adaaaa] font-headline font-bold py-3 rounded-lg">Later</button>
          {!isConnected ? (
            <button onClick={() => { onDismiss(); onConnect?.(); }} className="flex-1 ape-gradient text-[#0b5800] font-headline font-bold py-3 rounded-lg">Connect Wallet</button>
          ) : (
            <button onClick={() => { onDismiss(); navigate('/profile'); }} className="flex-1 ape-gradient text-[#0b5800] font-headline font-bold py-3 rounded-lg">⚡ Recharge</button>
          )}
        </div>
      </div>
    </div>
  );
}
