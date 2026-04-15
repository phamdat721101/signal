import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Feed from './pages/Feed';
import Leaderboard from './pages/Leaderboard';
import Portfolio from './pages/Portfolio';
import History from './pages/History';
import TradeSuccess from './pages/TradeSuccess';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Feed />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/history" element={<History />} />
        <Route path="/trade-success/:id" element={<TradeSuccess />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
