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
import { config } from './config';
import App from './App';
import './index.css';

// --- Privy (commented out) ---
// import { PrivyProvider } from '@privy-io/react-auth';

const wagmiConfig = createConfig({
  connectors: [initiaPrivyWalletConnector],
  chains: [config.chain],
  transports: { [config.chain.id]: http() } as any,
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
          defaultChainId="initiation-2"
          enableAutoSign={{ 'initiation-2': ['/minievm.evm.v1.MsgCall'] }}
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
