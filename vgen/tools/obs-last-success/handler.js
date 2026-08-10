/**
 * obs-last-success — last successful run for one or many pipelines
 */
let mysqlModulePromise;
async function loadMysql2() {
  if (!mysqlModulePromise) {
    mysqlModulePromise = import("mysql2/promise");
  }
  const ns = await mysqlModulePromise;
  return ns.default;
}

const DB_HOST =
  (typeof process !== "undefined" && process.env && process.env.DB_HOST) ||
  "database-1.cbsuuwi6y4bg.eu-north-1.rds.amazonaws.com";
const DB_USER =
  (typeof process !== "undefined" && process.env && process.env.DB_USER) ||
  "admin";
const DB_PASSWORD =
  (typeof process !== "undefined" && process.env && process.env.DB_PASSWORD) || "";
const DB_NAME =
  (typeof process !== "undefined" && process.env && process.env.DB_NAME) ||
  "metadata";
const DB_PORT = Number(
  (typeof process !== "undefined" && process.env && process.env.DB_PORT) ||
    "3306"
);

function jsonSafeDeep(value) {
  if (value === null || value === undefined) return value;
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number" && !Number.isFinite(value)) return null;
  if (value instanceof Date) return value.toISOString();
  if (typeof Buffer !== "undefined" && Buffer.isBuffer && Buffer.isBuffer(value)) {
    return value.toString("base64");
  }
  if (Array.isArray(value)) return value.map(jsonSafeDeep);
  if (typeof value === "object") {
    const out = {};
    for (const k of Object.keys(value)) {
      out[k] = jsonSafeDeep(value[k]);
    }
    return out;
  }
  return value;
}

function reply(payload) {
  const safe = jsonSafeDeep(payload);
  try {
    JSON.stringify(safe);
  } catch (e) {
    return { success: false, error: "Tool output could not be serialized." };
  }
  return safe;
}

function formatDurationDisplay(seconds) {
  if (seconds === null || seconds === undefined || seconds === "") return null;
  const n = Number(seconds);
  if (!isFinite(n) || n < 0) return null;
  const s = Math.round(n);
  if (s < 60) return s + " seconds";
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) {
    return rem === 0 ? m + " minutes" : m + " minutes " + rem + " seconds";
  }
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return h + " hours " + remM + " minutes";
}

async function runMysqlQuery(sql, params) {
  if (!DB_PASSWORD) {
    throw new Error("Database password not configured");
  }
  let mysql;
  try {
    mysql = await loadMysql2();
  } catch (e) {
    throw new Error(
      "mysql2 failed to load: " +
        ((e && e.message) || e) +
        ". Check FAAS npm install and package.json."
    );
  }
  const conn = await mysql.createConnection({
    host: DB_HOST,
    port: DB_PORT,
    user: DB_USER,
    password: DB_PASSWORD,
    database: DB_NAME,
    multipleStatements: false,
    supportBigNumbers: true,
    bigNumberStrings: true,
    dateStrings: true,
  });
  try {
    const result = await conn.query(sql, params || []);
    return result[0];
  } finally {
    await conn.end();
  }
}

function parseNameList(input) {
  const raw =
    (input.pipeline_names != null && String(input.pipeline_names).trim()) ||
    (input.pipeline_name != null && String(input.pipeline_name).trim()) ||
    (input.pipeline_id != null && String(input.pipeline_id).trim()) ||
    "";
  if (!raw) return [];
  return raw
    .split(/[,|;]+/)
    .map(function (s) {
      return s.trim();
    })
    .filter(Boolean);
}

async function resolvePipelineName(ref) {
  const rows = await runMysqlQuery(
    "SELECT pipeline_id, pipeline_name FROM obs_pipelines " +
      "WHERE LOWER(pipeline_name) = LOWER(?) " +
      "ORDER BY is_active DESC, updated_at DESC LIMIT 1",
    [ref]
  );
  if (rows && rows[0]) {
    return {
      ok: true,
      pipeline_id: rows[0].pipeline_id,
      pipeline_name: rows[0].pipeline_name,
      resolved_from: "name",
    };
  }
  const fuzzy = await runMysqlQuery(
    "SELECT pipeline_id, pipeline_name FROM obs_pipelines " +
      "WHERE pipeline_name LIKE ? " +
      "ORDER BY is_active DESC, updated_at DESC LIMIT 5",
    ["%" + ref + "%"]
  );
  if (!fuzzy || fuzzy.length === 0) {
    return { ok: false, error: "No pipeline found for name: " + ref, requested: ref };
  }
  if (fuzzy.length > 1) {
    return {
      ok: false,
      error: "Multiple pipelines match '" + ref + "'",
      requested: ref,
      matches: fuzzy.map(function (r) {
        return {
          pipeline_id: r.pipeline_id,
          pipeline_name: r.pipeline_name,
        };
      }),
    };
  }
  return {
    ok: true,
    pipeline_id: fuzzy[0].pipeline_id,
    pipeline_name: fuzzy[0].pipeline_name,
    resolved_from: "name_fuzzy",
  };
}

async function lastSuccessForPipeline(pipelineId, pipelineName) {
  const rows = await runMysqlQuery(
    "SELECT id, pipeline_id, pipeline_name, status, " +
      "start_time, end_time, duration, " +
      "tool_name, rows_read, rows_written, rows_added, " +
      "triggered_by, execution_mode " +
      "FROM obs_pipeline_runs " +
      "WHERE pipeline_id = ? AND LOWER(status) = 'success' " +
      "ORDER BY COALESCE(end_time, start_time) DESC, id DESC LIMIT 1",
    [pipelineId]
  );
  if (!rows || !rows[0]) {
    return {
      pipeline_id: pipelineId,
      pipeline_name: pipelineName,
      found: false,
      last_success: null,
      message: "No successful run found in recorded history for this pipeline",
    };
  }
  const r = rows[0];
  const assets = await runMysqlQuery(
    "SELECT asset_role, object_name, schema_name, database_name, row_count, last_updated_at " +
      "FROM obs_run_assets WHERE run_id = ? ORDER BY asset_role, object_name",
    [r.id]
  );
  const source = [];
  const target = [];
  for (let i = 0; i < (assets || []).length; i++) {
    const a = assets[i];
    const item = {
      object_name: a.object_name,
      schema_name: a.schema_name,
      database_name: a.database_name,
      row_count: a.row_count,
      last_updated_at: a.last_updated_at,
    };
    if ((a.asset_role || "").toUpperCase() === "TARGET") target.push(item);
    else source.push(item);
  }
  return {
    pipeline_id: pipelineId,
    pipeline_name: pipelineName || r.pipeline_name,
    found: true,
    last_success: {
      run_id: r.id,
      status: r.status,
      start_time: r.start_time,
      end_time: r.end_time,
      duration_seconds: r.duration,
      duration_display: formatDurationDisplay(r.duration),
      duration_unit: "seconds",
      tool_name: r.tool_name,
      rows_read: r.rows_read,
      rows_written: r.rows_written,
      rows_added: r.rows_added,
      triggered_by: r.triggered_by,
      execution_mode: r.execution_mode,
      assets: { SOURCE: source, TARGET: target },
    },
  };
}

async function handler(event) {
  try {
    const context =
      event && typeof event === "object" && event.context != null
        ? event.context
        : event && typeof event === "object"
          ? event
          : null;

    if (!context || typeof context !== "object") {
      return reply({
        success: false,
        error: "Invalid FAAS event: expected event.context",
      });
    }

    const input = context.input || {};
    const names = parseNameList(input);
    if (!names.length) {
      return reply({
        success: false,
        error:
          "pipeline_names is required (e.g. ecommerce_etl,stock_etl) or pipeline_name",
      });
    }

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    const results = [];
    for (let i = 0; i < names.length; i++) {
      const resolved = await resolvePipelineName(names[i]);
      if (!resolved.ok) {
        results.push({
          requested: names[i],
          found: false,
          error: resolved.error,
          matches: resolved.matches || undefined,
          last_success: null,
        });
        continue;
      }
      const card = await lastSuccessForPipeline(
        resolved.pipeline_id,
        resolved.pipeline_name
      );
      card.requested = names[i];
      card.resolved_from = resolved.resolved_from;
      results.push(card);
    }

    const foundCount = results.filter(function (r) {
      return r.found;
    }).length;

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        requested_names: names,
        found_count: foundCount,
        missing_count: results.length - foundCount,
        results: results,
      },
      agentResponseContext:
        "Quote EACH requested pipeline. For found=true: run_id, start_time, end_time, duration_display, rows_read, rows_written, rows_added, and asset table names. For found=false: say no successful run was found in the recorded history — do NOT invent 100% success or invent timestamps. Never say metadata/Sync/MySQL to the user. Never answer about a different pipeline than requested. Never write Evidence: 1 or Evidence: 2. Never use compare-runs for this question.",
    });
  } catch (error) {
    console.error("obs-last-success error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
