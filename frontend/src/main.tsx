import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createConfig, http, WagmiProvider } from 'wagmi';
import { injectStyles, InterwovenKitProvider, TESTNET } from '@initia/interwovenkit-react';
import InterwovenKitStyles from '@initia/interwovenkit-react/styles.js';
import { config as appConfig, customChain } from './config';
import App from './App';
import './index.css';

injectStyles(InterwovenKitStyles);

const wagmiConfig = createConfig({
  chains: [appConfig.chain],
  transports: { [appConfig.chain.id]: http() },
  ssr: false,
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchInterval: 15_000,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        <InterwovenKitProvider
          {...TESTNET}
          defaultChainId={customChain.chain_id}
          customChain={customChain}
          enableAutoSign={{ [customChain.chain_id]: ['/minievm.evm.v1.MsgCall'] }}
        >
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </InterwovenKitProvider>
      </QueryClientProvider>
    </WagmiProvider>
  </StrictMode>,
);
