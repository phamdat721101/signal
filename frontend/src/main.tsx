import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createConfig, http, WagmiProvider } from 'wagmi';
import {
  initiaPrivyWalletConnector,
  injectStyles,
  InterwovenKitProvider,
  TESTNET,
} from '@initia/interwovenkit-react';
import interwovenKitStyles from '@initia/interwovenkit-react/styles.js';
import { config, localChain, testnetChain, xlayerTestnet, xlayerMainnet } from './config';
import App from './App';
import './index.css';

// Multi-chain wagmi config — single connector (InterwovenKit's Privy wallet),
// multiple chains. Privy embedded wallet is chain-agnostic, so a wagmi
// switchChainAsync({ chainId: 1952 }) routes through it transparently.
//
// Per project decision (2026-05-24): no separate `injected` / WalletConnect
// connectors. InterwovenKit owns the wallet UX end-to-end.
//
// Both Initia chains (local + testnet) are registered so the transports map
// satisfies the inferred `config.chain.id` union — only one is active at runtime.
const wagmiConfig = createConfig({
  connectors: [initiaPrivyWalletConnector],
  chains: [localChain, testnetChain, xlayerTestnet, xlayerMainnet],
  transports: {
    [localChain.id]: http(),
    [testnetChain.id]: http(),
    [xlayerTestnet.id]: http(),
    [xlayerMainnet.id]: http(),
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
