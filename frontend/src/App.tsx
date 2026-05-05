import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Feed from './pages/Feed';
import Portfolio from './pages/Portfolio';
import History from './pages/History';
import Profile from './pages/Profile';
import TradeSuccess from './pages/TradeSuccess';
import ProviderDashboard from './pages/ProviderDashboard';
import Challenges from './pages/Challenges';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Feed />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/history" element={<History />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/provider" element={<ProviderDashboard />} />
        <Route path="/challenges" element={<Challenges />} />
        <Route path="/trade-success/:id" element={<TradeSuccess />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
