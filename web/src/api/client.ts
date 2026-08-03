const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const ASSISTANTS_BASE = import.meta.env.VITE_ASSISTANTS_API_BASE ?? "http://127.0.0.1:8001";

export type TenantId = string;

async function getJson<T>(
  path: string,
  params: Record<string, string | number | undefined>,
  base: string = API_BASE,
): Promise<T> {
  const url = new URL(path, base);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  });
  const res = await fetch(url.toString());
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown, base: string = API_BASE): Promise<T> {
  const url = new URL(path, base);
  const res = await fetch(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

async function putJson<T>(path: string, body: unknown, base: string = API_BASE): Promise<T> {
  const url = new URL(path, base);
  const res = await fetch(url.toString(), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

async function deleteJson<T>(
  path: string,
  params: Record<string, string | number | undefined>,
  base: string = API_BASE,
): Promise<T> {
  const url = new URL(path, base);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  });
  const res = await fetch(url.toString(), { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJson<{ status: string }>("/health", {}),
  pipelines: (tenant_id: TenantId) =>
    getJson<{ items: Pipeline[] }>("/v1/pipelines", { tenant_id, limit: 200 }),
  pipelineDashboard: (tenant_id: TenantId, pipeline_id: string) =>
    getJson<PipelineDashboard>(`/v1/pipelines/${encodeURIComponent(pipeline_id)}/dashboard`, {
      tenant_id,
    }),
  datasets: (tenant_id: TenantId) =>
    getJson<{ items: Dataset[] }>("/v1/datasets", { tenant_id, limit: 200 }),
  executions: (tenant_id: TenantId, pipeline_id?: string) =>
    getJson<{ items: Execution[] }>("/v1/executions", { tenant_id, pipeline_id, limit: 200 }),
  incidents: (tenant_id: TenantId, status?: string) =>
    getJson<{ items: Incident[] }>("/v1/incidents", { tenant_id, status, limit: 200 }),
  incident: (tenant_id: TenantId, incident_key: string) =>
    getJson<IncidentDetail>(`/v1/incidents/${encodeURIComponent(incident_key)}`, { tenant_id }),
  incidentRca: (tenant_id: TenantId, incident_key: string) =>
    postJson<RcaResult>("/v1/rca/incident", { tenant_id, incident_key }, ASSISTANTS_BASE),
  startRcaChat: (tenant_id: TenantId, incident_key: string, opening_question?: string) =>
    postJson<ChatSession>(
      "/v1/chat/sessions",
      { tenant_id, incident_key, opening_question },
      ASSISTANTS_BASE,
    ),
  sendRcaChatMessage: (session_id: string, message: string) =>
    postJson<ChatTurn>(
      `/v1/chat/sessions/${encodeURIComponent(session_id)}/messages`,
      { message },
      ASSISTANTS_BASE,
    ),
  getRcaChat: (session_id: string) =>
    getJson<ChatSession>(`/v1/chat/sessions/${encodeURIComponent(session_id)}`, {}, ASSISTANTS_BASE),
  startDqChat: (tenant_id: TenantId, dataset_id: string, opening_question?: string) =>
    postJson<ChatSession>(
      "/v1/dq/chat/sessions",
      { tenant_id, dataset_id, opening_question },
      ASSISTANTS_BASE,
    ),
  sendDqChatMessage: (session_id: string, message: string) =>
    postJson<DqChatTurn>(
      `/v1/dq/chat/sessions/${encodeURIComponent(session_id)}/messages`,
      { message },
      ASSISTANTS_BASE,
    ),
  getDqChat: (session_id: string) =>
    getJson<ChatSession>(`/v1/dq/chat/sessions/${encodeURIComponent(session_id)}`, {}, ASSISTANTS_BASE),
  startObservabilityChat: (tenant_id: TenantId, opening_question?: string) =>
    postJson<ChatSession>(
      "/v1/observability/chat/sessions",
      { tenant_id, opening_question },
      ASSISTANTS_BASE,
    ),
  sendObservabilityChatMessage: (session_id: string, message: string) =>
    postJson<ChatTurn>(
      `/v1/observability/chat/sessions/${encodeURIComponent(session_id)}/messages`,
      { message },
      ASSISTANTS_BASE,
    ),
  getObservabilityChat: (session_id: string) =>
    getJson<ChatSession>(
      `/v1/observability/chat/sessions/${encodeURIComponent(session_id)}`,
      {},
      ASSISTANTS_BASE,
    ),
  dqDataset: (tenant_id: TenantId, dataset_id: string) =>
    postJson<DqResult>("/v1/dq/dataset", { tenant_id, dataset_id }, ASSISTANTS_BASE),
  alerts: (tenant_id: TenantId) =>
    getJson<{ items: Alert[] }>("/v1/alerts", { tenant_id, limit: 200 }),
  monitors: (tenant_id: TenantId) =>
    getJson<{ items: Monitor[] }>("/v1/monitors", { tenant_id, limit: 200 }),
  checkResults: (tenant_id: TenantId, asset_id?: string) =>
    getJson<{ items: CheckResult[] }>("/v1/check-results", { tenant_id, asset_id, limit: 200 }),
  metrics: (tenant_id: TenantId, opts?: { asset_id?: string; name?: string; limit?: number }) =>
    getJson<{ items: MetricPoint[] }>("/v1/metrics", {
      tenant_id,
      asset_id: opts?.asset_id,
      name: opts?.name,
      limit: opts?.limit ?? 200,
    }),
  lineage: (tenant_id: TenantId, dataset_id?: string) =>
    getJson<{ items: LineageEdge[] }>("/v1/lineage", { tenant_id, dataset_id, limit: 500 }),
  blastRadius: (tenant_id: TenantId, dataset_id: string) =>
    getJson<{ dataset_id: string; downstream: string[]; count: number }>(
      "/v1/lineage/blast-radius",
      { tenant_id, dataset_id },
    ),
  connectors: () => getJson<{ items: ConnectorInfo[] }>("/v1/connectors", {}),
  connectorCatalog: () => getJson<{ items: ConnectorCatalogItem[] }>("/v1/connectors/catalog", {}),
  connectorInstances: (tenant_id: TenantId) =>
    getJson<{ items: ConnectorInstance[] }>("/v1/connectors/instances", { tenant_id, limit: 200 }),
  createConnectorInstance: (body: {
    tenant_id: string;
    tool_id: string;
    name: string;
    config: Record<string, string>;
    secrets_ref?: Record<string, string>;
    instance_id?: string;
  }) => postJson<ConnectorInstance>("/v1/connectors/instances", body),
  updateConnectorInstance: (
    instance_id: string,
    body: {
      tenant_id: string;
      name?: string;
      config?: Record<string, string>;
      secrets_ref?: Record<string, string>;
    },
  ) =>
    putJson<ConnectorInstance>(
      `/v1/connectors/instances/${encodeURIComponent(instance_id)}`,
      body,
    ),
  deleteConnectorInstance: (tenant_id: TenantId, instance_id: string) =>
    deleteJson<{ deleted: boolean; instance_id: string }>(
      `/v1/connectors/instances/${encodeURIComponent(instance_id)}`,
      { tenant_id },
    ),
  testConnectorInstance: (tenant_id: TenantId, instance_id: string) =>
    postJson<{ instance_id: string; result: { ok: boolean; message: string; details?: Record<string, unknown> } }>(
      `/v1/connectors/instances/${encodeURIComponent(instance_id)}/test?tenant_id=${encodeURIComponent(tenant_id)}`,
      {},
    ),
  syncConnectorInstance: (tenant_id: TenantId, instance_id: string) =>
    postJson<ConnectorSyncResult>(
      `/v1/connectors/instances/${encodeURIComponent(instance_id)}/sync?tenant_id=${encodeURIComponent(tenant_id)}`,
      {},
    ),
  ingestConnectorCsv: async (tool: string, tenant_id: string, file: File) => {
    const url = new URL("/v1/connectors/ingest-csv", API_BASE);
    const body = new FormData();
    body.append("tool", tool);
    body.append("tenant_id", tenant_id);
    body.append("file", file);
    const res = await fetch(url.toString(), { method: "POST", body });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 300)}`);
    }
    return res.json() as Promise<ConnectorIngestResult>;
  },
};

export type Pipeline = {
  pipeline_id: string;
  name: string;
  source_tool: string;
  status: string | null;
};

export type Dataset = {
  dataset_id: string;
  name: string;
  database: string | null;
  schema: string | null;
  platform: string;
  row_count: number | null;
  last_updated_at: string | null;
};

export type Execution = {
  execution_id: string;
  pipeline_id: string;
  task_id: string | null;
  status: string;
  attempt: number;
  error_message: string | null;
  source_tool: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  triggered_by?: string | null;
  deep_link?: string | null;
  deep_link_label?: string | null;
};

export type PipelineDashboard = {
  pipeline: Pipeline & {
    tags?: string[];
    updated_at?: string | null;
    created_at?: string | null;
  };
  metrics: {
    total_runs: number;
    succeeded: number;
    failed: number;
    running: number;
    success_rate_pct: number | null;
    failure_rate_pct: number | null;
    avg_duration_ms: number | null;
    max_duration_ms: number | null;
    retry_count: number;
    task_count: number;
    open_incident_count: number;
    alert_count: number;
  };
  tasks: { task_id: string; name: string; source_tool: string }[];
  task_stats: { task_id: string; total: number; failed: number; succeeded: number }[];
  executions: Execution[];
  incidents: {
    incident_key: string;
    title: string;
    status: string;
    severity: string;
    root_asset_id: string | null;
    blast_radius_count: number;
    summary: string | null;
  }[];
  alerts: {
    alert_key: string;
    title: string;
    severity: string;
    status: string;
    monitor_type: string | null;
    asset_id: string | null;
  }[];
  related_datasets: string[];
  lineage_edges: {
    upstream_dataset_id: string;
    downstream_dataset_id: string;
    confidence: string;
    transform: string | null;
  }[];
  metric_points: { name: string; value: number; unit: string | null; recorded_at: string | null }[];
};

export type Incident = {
  incident_key: string;
  title: string;
  status: string;
  severity: string;
  root_asset_type: string | null;
  root_asset_id: string | null;
  monitor_type?: string | null;
  blast_radius_count: number;
  summary: string | null;
  error_message?: string | null;
  opened_at?: string | null;
  resolved_at?: string | null;
};

export type IncidentDetail = Incident & {
  alerts: {
    alert_key: string;
    title: string;
    severity: string;
    status: string;
    asset_type: string | null;
    asset_id: string | null;
    monitor_type: string | null;
    message: string | null;
    raised_at: string | null;
    resolved_at: string | null;
  }[];
  latest_failure: Execution | null;
};

export type RcaResult = {
  incident_key: string;
  summary: string;
  likely_cause: string;
  timeline: { at: string; event: string; citation: string | null }[];
  blast_radius: string[];
  recommended_actions: string[];
  citations: string[];
  model: string;
  grounded: boolean;
  invented_ids_dropped?: string[];
};

export type ChatMessage = {
  role: "user" | "assistant" | "system" | string;
  content: string;
  created_at: string;
  meta?: Record<string, unknown>;
};

export type ChatSession = {
  session_id: string;
  tenant_id: string;
  kind?: string;
  incident_key: string;
  dataset_id?: string | null;
  incident_title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages: ChatMessage[];
};

export type ChatTurn = {
  session_id: string;
  reply: string;
  incident_key: string;
  tenant_id: string;
  messages: ChatMessage[];
  model: string;
};

export type DqChatTurn = {
  session_id: string;
  reply: string;
  dataset_id: string | null;
  tenant_id: string;
  kind?: string;
  messages: ChatMessage[];
  model: string;
};

export type DqResult = {
  dataset_id: string;
  summary: string;
  quality_issues: {
    monitor_type: string;
    status: string;
    detail: string;
    citation: string | null;
  }[];
  lineage_impact: string;
  blast_radius: string[];
  recommended_actions: string[];
  citations: string[];
  model: string;
  grounded: boolean;
  invented_ids_dropped?: string[];
};

export type CheckResult = {
  id: number;
  monitor_id: number | null;
  monitor_type: string;
  asset_type: string;
  asset_id: string;
  status: string;
  metric_value: number | null;
  baseline_value: number | null;
  severity: string | null;
  details: Record<string, unknown>;
  checked_at: string | null;
};

export type MetricPoint = {
  name: string;
  asset_type?: string | null;
  asset_id: string;
  value: number;
  unit?: string | null;
  recorded_at?: string | null;
  labels?: Record<string, unknown>;
};

export type ConnectorInfo = {
  tool: string;
  input: string;
  description: string;
  sample_columns: string[];
};

export type ConnectorCatalogItem = {
  tool_id: string;
  display_name: string;
  description: string;
  auth_kinds: string[];
  capabilities: string[];
  config_schema: {
    type?: string;
    required?: string[];
    properties?: Record<
      string,
      { title?: string; description?: string; enum?: string[]; type?: string; default?: unknown }
    >;
  };
  secret_fields: string[];
  input_modes: string[];
};

export type ConnectorInstance = {
  instance_id: string;
  tool_id: string;
  name: string;
  config: Record<string, unknown>;
  secrets_ref: Record<string, unknown>;
  status: string;
  last_sync_at: string | null;
  last_error: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ConnectorSyncResult = {
  run_id: string;
  instance_id: string;
  tool: string;
  envelopes: number;
  ingested: number;
  duplicates: number;
  dead_letters: number;
  discover?: unknown[];
};

export type ConnectorIngestResult = {
  tool: string;
  envelopes: number;
  canonical_events: number;
  ingested: number;
  duplicates: number;
  dead_letters: number;
  filename?: string;
  discover?: { dataset_id?: string; pipeline_id?: string; task_id?: string }[];
  errors?: unknown[];
};

export type Alert = {
  alert_key: string;
  title: string;
  severity: string;
  status: string;
  asset_type: string | null;
  asset_id: string | null;
  monitor_type: string | null;
  message?: string | null;
  raised_at?: string | null;
  resolved_at?: string | null;
};

export type Monitor = {
  monitor_key: string;
  monitor_type: string;
  asset_type: string;
  asset_id: string;
  enabled: boolean;
  name?: string;
  config?: Record<string, unknown>;
};

export type LineageEdge = {
  upstream_dataset_id: string;
  downstream_dataset_id: string;
  confidence: string;
  transform: string | null;
  platform: string | null;
};
