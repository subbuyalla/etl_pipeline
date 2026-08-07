import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ConnectorsPage } from "./pages/ConnectorsPage";
import { PipelinesPage } from "./pages/PipelinesPage";

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<PipelinesPage />} />
          <Route path="/connectors" element={<ConnectorsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
