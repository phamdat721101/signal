import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import SignalFeed from './pages/SignalFeed';
import SignalDetail from './pages/SignalDetail';
import Portfolio from './pages/Portfolio';
import Report from './pages/Report';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/signals" element={<SignalFeed />} />
        <Route path="/signal/:id" element={<SignalDetail />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/report" element={<Report />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
