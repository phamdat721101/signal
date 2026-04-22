export default function BridgePrompt({ address }: { address: string }) {
  const bridgeUrl = `https://bridge.initia.xyz/?to=initia-signal-1&address=${address}`;
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 px-6 text-center">
      <span className="material-symbols-outlined text-6xl text-[#bf81ff]" style={{ fontVariationSettings: "'FILL' 1" }}>account_balance</span>
      <div>
        <h2 className="font-headline text-xl font-black text-white">Fund Your Wallet</h2>
        <p className="text-[#adaaaa] text-sm mt-2">Bridge INIT from Initia L1 to start trading</p>
      </div>
      <a href={bridgeUrl} target="_blank" rel="noopener noreferrer"
        className="ape-gradient px-8 py-3 rounded-lg text-[#0b5800] font-headline font-bold flex items-center gap-2">
        <span className="material-symbols-outlined">swap_horiz</span>
        Bridge INIT
      </a>
      <p className="text-[#494847] text-xs">You need INIT on the appchain to pay for gas</p>
    </div>
  );
}
