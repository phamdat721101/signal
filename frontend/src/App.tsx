import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Feed from './pages/Feed';
import Portfolio from './pages/Portfolio';
import History from './pages/History';
import Profile from './pages/Profile';
import TradeSuccess from './pages/TradeSuccess';
import SettlementSuccess from './pages/SettlementSuccess';
import Agent from './pages/Agent';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Feed />} />
        <Route path="/agent" element={<Agent />} />
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
