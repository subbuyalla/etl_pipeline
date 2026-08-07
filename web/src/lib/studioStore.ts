/**
 * Local studio store — connector instances + local pipelines.
 * Secrets stay in memory/config blobs for demo; not sent to git.
 */

export type ConnectorKind = "database" | "etl";
export type ConnectorTool = "snowflake" | "mysql" | "dbt";
export type ConnectorStatus = "draft" | "connected" | "error";

export type ConnectorInstance = {
  id: string;
  kind: ConnectorKind;
  tool: ConnectorTool;
  name: string;
  config: Record<string, string>;
  status: ConnectorStatus;
  created_at: string;
};

export type PipelineAttach = {
  tool: string;
  schema?: string;
  connector_id?: string;
  connector_name?: string;
};

export type PipelineView = {
  pipeline_id: string;
  pipeline_name: string;
  description?: string;
  is_active?: boolean;
  source?: PipelineAttach;
  etl?: PipelineAttach;
  target?: PipelineAttach;
  source_local?: boolean;
};

const CONNECTORS_KEY = "etl_studio_connectors_v1";
const PIPELINES_KEY = "etl_studio_pipelines_v1";

function uid(): string {
  return crypto.randomUUID();
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  localStorage.setItem(key, JSON.stringify(value));
}

export function listConnectors(): ConnectorInstance[] {
  return readJson<ConnectorInstance[]>(CONNECTORS_KEY, []);
}

export function saveConnector(
  input: Omit<ConnectorInstance, "id" | "created_at" | "status"> & {
    id?: string;
    status?: ConnectorStatus;
  },
): ConnectorInstance {
  const all = listConnectors();
  const now = new Date().toISOString();
  if (input.id) {
    const idx = all.findIndex((c) => c.id === input.id);
    if (idx >= 0) {
      const updated: ConnectorInstance = {
        ...all[idx],
        ...input,
        id: input.id,
        status: input.status ?? "connected",
      };
      all[idx] = updated;
      writeJson(CONNECTORS_KEY, all);
      return updated;
    }
  }
  const created: ConnectorInstance = {
    id: uid(),
    kind: input.kind,
    tool: input.tool,
    name: input.name,
    config: input.config,
    status: input.status ?? "connected",
    created_at: now,
  };
  all.unshift(created);
  writeJson(CONNECTORS_KEY, all);
  return created;
}

export function deleteConnector(id: string): void {
  writeJson(
    CONNECTORS_KEY,
    listConnectors().filter((c) => c.id !== id),
  );
}

export function listLocalPipelines(): PipelineView[] {
  return readJson<PipelineView[]>(PIPELINES_KEY, []);
}

export function saveLocalPipeline(pipeline: PipelineView): PipelineView {
  const all = listLocalPipelines();
  const idx = all.findIndex((p) => p.pipeline_id === pipeline.pipeline_id);
  const next = { ...pipeline, source_local: true };
  if (idx >= 0) all[idx] = next;
  else all.unshift(next);
  writeJson(PIPELINES_KEY, all);
  return next;
}

export function deleteLocalPipeline(pipelineId: string): void {
  writeJson(
    PIPELINES_KEY,
    listLocalPipelines().filter((p) => p.pipeline_id !== pipelineId),
  );
}

export const FALLBACK_PIPELINES: PipelineView[] = [
  {
    pipeline_id: "af2a8939-a176-46df-becd-566e189a3bbc",
    pipeline_name: "stock_etl",
    description: "Snowflake RAW source → dbt Cloud → Snowflake staging target",
    is_active: true,
    source: { tool: "snowflake", schema: "RAW" },
    etl: { tool: "dbt" },
    target: { tool: "snowflake", schema: "STAGING_STAGING" },
  },
  {
    pipeline_id: "3b726bf0-2892-49de-bab4-819365ba0d30",
    pipeline_name: "ecommerce_etl",
    description: "Snowflake ECOMMERCE.SRC_DATA → dbt Cloud → ECOMMERCE.CLEAN_DATA",
    is_active: false,
    source: { tool: "snowflake", schema: "SRC_DATA" },
    etl: { tool: "dbt" },
    target: { tool: "snowflake", schema: "CLEAN_DATA" },
  },
];

export function lineageSummary(p: PipelineView): string {
  const src = p.source
    ? `${p.source.tool}${p.source.schema ? "/" + p.source.schema : ""}`
    : "?";
  const etl = p.etl?.tool || "?";
  const tgt = p.target
    ? `${p.target.tool}${p.target.schema ? "/" + p.target.schema : ""}`
    : "?";
  return `${src} → ${etl} → ${tgt}`;
}

export function newPipelineId(): string {
  return uid();
}
