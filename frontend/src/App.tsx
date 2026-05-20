import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Feed from './pages/Feed';
import Portfolio from './pages/Portfolio';
import History from './pages/History';
import Profile from './pages/Profile';
import TradeSuccess from './pages/TradeSuccess';
import SettlementSuccess from './pages/SettlementSuccess';
import Agent from './pages/Agent';
import Marketplace from './pages/Marketplace';
import { useWallet } from './hooks/useWallet';

const ADMIN = '0x100690a32b562fd45e685bc2e63bbff566d452db';

function ComingSoon() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
      <span className="material-symbols-outlined text-6xl text-[#494847]">construction</span>
      <h2 className="text-xl font-headline font-bold text-white">Coming Soon</h2>
      <p className="text-[#adaaaa] font-label text-sm text-center">This feature is under development.</p>
    </div>
  );
}

function AdminGate({ children }: { children: React.ReactNode }) {
  const { address } = useWallet();
  return address.toLowerCase() === ADMIN ? <>{children}</> : <ComingSoon />;
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Feed />} />
        <Route path="/agent" element={<AdminGate><Agent /></AdminGate>} />
        <Route path="/marketplace" element={<AdminGate><Marketplace /></AdminGate>} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/history" element={<History />} />
        <Route path="/profile" element={<Profile />} />

        <Route path="/trade-success/:id" element={<TradeSuccess />} />
        <Route path="/session/:txHash" element={<SettlementSuccess />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
