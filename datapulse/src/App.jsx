import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import './styles/index.css';
import Sidebar from './components/Sidebar';

import Overview from './pages/Overview';
import Pipelines from './pages/Pipelines';
import Integrations from './pages/Integrations';
import ObsOverview from './pages/DataObservability/ObsOverview';
import Assets from './pages/DataObservability/Assets';
import Freshness from './pages/DataObservability/Freshness';
import Volume from './pages/DataObservability/Volume';
import DataQuality from './pages/DataObservability/DataQuality';
import Schema from './pages/DataObservability/Schema';
import Lineage from './pages/Lineage';
import Incidents from './pages/Incidents';
import Metrics from './pages/Metrics';
import Alerts from './pages/Alerts';
import Logs from './pages/Logs';
import Settings from './pages/Settings';
import MaturityAssessment from './pages/MaturityAssessment';
import DataOpsMaturity from './pages/DataOpsMaturity';

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <div className="app-layout">
          <Sidebar />
          <main className="main-content">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/pipelines" element={<Pipelines />} />
              <Route path="/integrations" element={<Integrations />} />
              <Route path="/observability" element={<ObsOverview />} />
              <Route path="/observability/assets" element={<Assets />} />
              <Route path="/assets" element={<Navigate to="/observability/assets" replace />} />
              <Route path="/observability/freshness" element={<Freshness />} />
              <Route path="/observability/volume" element={<Volume />} />
              <Route path="/observability/data-quality" element={<DataQuality />} />
              <Route path="/observability/schema" element={<Schema />} />
              <Route path="/observability/lineage" element={<Lineage />} />
              <Route path="/observability/maturity" element={<MaturityAssessment />} />
              <Route path="/maturity" element={<Navigate to="/observability/maturity" replace />} />
              <Route path="/data-quality" element={<Navigate to="/observability/data-quality" replace />} />
              <Route path="/lineage" element={<Navigate to="/observability/lineage" replace />} />
              <Route path="/dataops/pipelines" element={<Navigate to="/pipelines" replace />} />
              <Route path="/dataops/integrations" element={<Navigate to="/integrations" replace />} />
              <Route path="/dataops/maturity" element={<DataOpsMaturity />} />
              <Route path="/dataops" element={<Navigate to="/dataops/maturity" replace />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/metrics" element={<Metrics />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/observability/metrics" element={<Navigate to="/metrics" replace />} />
              <Route path="/observability/logs" element={<Navigate to="/logs" replace />} />
              <Route path="/observability/incidents" element={<Navigate to="/incidents" replace />} />
              <Route path="/observability/alerts" element={<Navigate to="/alerts" replace />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </ThemeProvider>
  );
}
