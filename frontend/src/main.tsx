import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createConfig, http, WagmiProvider, injected } from 'wagmi';
import {
  initiaPrivyWalletConnector,
  injectStyles,
  InterwovenKitProvider,
  TESTNET,
} from '@initia/interwovenkit-react';
import interwovenKitStyles from '@initia/interwovenkit-react/styles.js';
import { config, localChain, testnetChain, somniaTestnet, arbitrumSepolia, goatTestnet } from './config';
import App from './App';
import './index.css';

// Multi-chain wagmi config — TWO connectors:
//   1. initiaPrivyWalletConnector — InterwovenKit's Privy embedded wallet,
//      used for the Initia signal flow (auto-signs MsgCall on chain 'evm-1').
//   2. injected() — MetaMask / Rabby / any browser-extension wallet.
//      Required for the /agent paid flow on Arbitrum Sepolia: the Privy
//      embedded wallet does not surface a transaction-approval modal for
//      arbitrary EVM contract calls, so writeContract hangs. External
//      wallets handle this natively.
//
// Adding a chain here is a one-row edit in this array + one row in
// NetworkBadge META + one row in Layout FAUCETS (if testnet).
const wagmiConfig = createConfig({
  connectors: [initiaPrivyWalletConnector, injected({ shimDisconnect: true })],
  chains: [localChain, testnetChain, somniaTestnet, arbitrumSepolia, goatTestnet],
  transports: {
    [localChain.id]: http(),
    [testnetChain.id]: http(),
    [somniaTestnet.id]: http(),
    [arbitrumSepolia.id]: http(),
    [goatTestnet.id]: http(),
  },
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, refetchInterval: 15_000 },
  },
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => { injectStyles(interwovenKitStyles); }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <WagmiProvider config={wagmiConfig}>
        <InterwovenKitProvider
          {...TESTNET}
          defaultChainId={config.chainId}
          enableAutoSign={{ [config.chainId]: ['/minievm.evm.v1.MsgCall'] }}
        >
          {children}
        </InterwovenKitProvider>
      </WagmiProvider>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Providers>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </Providers>
  </StrictMode>,
);

// Tell the pre-React splash bootstrap (in index.html) we're done loading.
// Two RAFs guarantees the first React paint has flushed before fade.
requestAnimationFrame(() => requestAnimationFrame(() => {
  window.dispatchEvent(new CustomEvent('app-ready'));
}));
