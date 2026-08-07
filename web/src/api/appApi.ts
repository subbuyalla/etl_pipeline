/**
 * App API client for the FastAPI ETL Observability App
 * (application/src/app.py) — pipelines stored in Metadata MySQL.
 */
import type { PipelineView } from "../lib/studioStore";

const APP_API_BASE =
  import.meta.env.VITE_API_BASE ?? "http://18.61.29.231:2222";

export type AppPipelineRow = {
  pipeline_id: string;
  pipeline_name: string;
  source_tool?: string | null;
  source_schema?: string | null;
  etl_tool?: string | null;
  target_tool?: string | null;
  target_schema?: string | null;
  is_active?: number | boolean | null;
  updated_at?: string | null;
  description?: string | null;
};

function mapRow(row: AppPipelineRow): PipelineView {
  return {
    pipeline_id: row.pipeline_id,
    pipeline_name: row.pipeline_name,
    description: row.description || undefined,
    is_active: Boolean(row.is_active),
    source: row.source_tool
      ? { tool: String(row.source_tool), schema: row.source_schema || undefined }
      : undefined,
    etl: row.etl_tool ? { tool: String(row.etl_tool) } : undefined,
    target: row.target_tool
      ? { tool: String(row.target_tool), schema: row.target_schema || undefined }
      : undefined,
  };
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = new URL(path, APP_API_BASE);
  const res = await fetch(url.toString(), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 240)}`);
  }
  return res.json() as Promise<T>;
}

export const appApi = {
  base: APP_API_BASE,

  health: () =>
    fetchJson<{
      ok: boolean;
      templates?: string[];
      active_pipeline?: { pipeline_name?: string } | null;
      webhook_urls?: unknown;
    }>("/health"),

  listPipelines: async (): Promise<PipelineView[]> => {
    const data = await fetchJson<{ ok: boolean; pipelines: AppPipelineRow[] }>(
      "/v1/pipelines",
    );
    return (data.pipelines || []).map(mapRow);
  },

  createPipeline: async (body: {
    pipeline_name: string;
    pipeline_id?: string;
    make_active?: boolean;
  }): Promise<{ ok: boolean; pipeline_id?: string; pipeline?: unknown }> => {
    return fetchJson("/v1/pipelines", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
};
