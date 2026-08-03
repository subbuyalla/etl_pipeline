import { useMemo, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AssistantsPage } from "./pages/AssistantsPage";
import { ConnectorsPage } from "./pages/ConnectorsPage";
import { DatasetsPage } from "./pages/DatasetsPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { LineagePage } from "./pages/LineagePage";
import { MonitorsPage } from "./pages/MonitorsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { PipelinesPage } from "./pages/PipelinesPage";

const TENANT_KEY = "etl_obs_tenant";

export default function App() {
  const [tenantId, setTenantId] = useState(() => localStorage.getItem(TENANT_KEY) || "demo");

  const onTenantChange = useMemo(
    () => (v: string) => {
      setTenantId(v);
      localStorage.setItem(TENANT_KEY, v);
    },
    [],
  );

  return (
    <BrowserRouter>
      <Layout tenantId={tenantId} onTenantChange={onTenantChange}>
        <Routes>
          <Route path="/" element={<OverviewPage tenantId={tenantId} />} />
          <Route path="/observability" element={<ObservabilityPage tenantId={tenantId} />} />
          <Route path="/assistants" element={<AssistantsPage />} />
          <Route path="/incidents" element={<IncidentsPage tenantId={tenantId} />} />
          <Route path="/pipelines" element={<PipelinesPage tenantId={tenantId} />} />
          <Route path="/datasets" element={<DatasetsPage tenantId={tenantId} />} />
          <Route path="/monitors" element={<MonitorsPage tenantId={tenantId} />} />
          <Route path="/lineage" element={<LineagePage tenantId={tenantId} />} />
          <Route path="/connectors" element={<ConnectorsPage tenantId={tenantId} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
