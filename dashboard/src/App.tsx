import { useCallback, useEffect, useState } from "react";
import { fetchOverview, type OverviewPayload } from "./api";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";

export default function App() {
  const [range, setRange] = useState("all");
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchOverview(range);
      setData(payload);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Layout range={range} onRangeChange={setRange} onRefresh={load} generatedAt={data?.generated_at}>
      <OverviewPage data={data} loading={loading} error={error} />
    </Layout>
  );
}
