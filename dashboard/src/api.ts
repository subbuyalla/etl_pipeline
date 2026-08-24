export type KpiDef = {
  id: string;
  title: string;
  meaning: string;
  formula: string;
  tables: string;
};

export type Kpi = {
  id: string;
  title: string;
  value: number | null;
  display: string;
  delta: number | null;
  delta_label: string | null;
  sparkline: number[];
  tone: "ok" | "warn" | "bad" | "neutral";
};

export type ObsMetric = {
  id: string;
  title: string;
  value: number | null;
  display: string;
  available: boolean;
};

export type OverviewPayload = {
  ok: boolean;
  range: string;
  generated_at: string;
  kpi_defs: KpiDef[];
  kpis: Kpi[];
  observability: ObsMetric[];
  series: {
    runs_over_time: { date: string; success: number; failed: number; total: number; running?: number; cancelled?: number }[];
    duration: { date: string; avg_duration_seconds: number; avg_duration_minutes: number }[];
    throughput: { date: string; rows_per_sec: number }[];
  };
  charts: {
    top_volume: { pipeline_name: string; target_row_count: number }[];
    failure_rate: {
      pipeline_name: string;
      failure_rate_pct: number;
      failed_count: number;
      total_runs: number;
      health_status: string;
    }[];
  };
  incidents: {
    pipeline_name: string;
    title: string;
    detail: string;
    severity: string;
    age: string | null;
    status: string;
    run_id: string;
  }[];
  lineage: {
    pipeline_name: string;
    source: string;
    etl: string;
    target: string;
    source_tool: string | null;
    source_schema: string | null;
    etl_tool: string | null;
    target_tool: string | null;
    target_schema: string | null;
  }[];
  impact: {
    pipeline_name: string;
    object_name: string;
    schema_name: string;
    database_name: string;
    impact: string;
  }[];
  system_health: {
    name: string;
    status: string;
    label: string;
    success_rate_pct: number | null;
    latest_status: string | null;
  }[];
  freshness_datasets: {
    pipeline_name: string;
    object_name: string;
    schema_name: string;
    last_updated_at: string | null;
    age: string | null;
    row_count: number | null;
  }[];
  runs: {
    run_id: string;
    pipeline_name: string;
    source_target: string;
    status: string;
    duration: string | null;
    duration_seconds: number | null;
    rows_read: number | null;
    rows_written: number | null;
    start_time: string | null;
    end_time: string | null;
    last_run: string | null;
    error_class: string | null;
  }[];
};

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

export async function fetchOverview(range: string): Promise<OverviewPayload> {
  const url = `${API_BASE}/v1/dashboard/overview?range=${encodeURIComponent(range)}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}
