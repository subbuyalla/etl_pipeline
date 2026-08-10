/**
 * obs-get-run-detail — FAAS handler (matches working mysql2 FAAS pattern)
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

function parseDbtUniqueId(uniqueId) {
  if (uniqueId === null || uniqueId === undefined || uniqueId === "") {
    return {
      failed_node_short: null,
      failed_node_resource: null,
      failed_node_project: null,
    };
  }
  const s = String(uniqueId);
  const parts = s.split(".");
  if (parts.length >= 3) {
    return {
      failed_node_short: parts.slice(2).join("."),
      failed_node_resource: parts[0],
      failed_node_project: parts[1],
    };
  }
  if (parts.length === 2) {
    return {
      failed_node_short: parts[1],
      failed_node_resource: parts[0],
      failed_node_project: null,
    };
  }
  return {
    failed_node_short: s,
    failed_node_resource: null,
    failed_node_project: null,
  };
}

function withFailedNodeFields(node) {
  const parsed = parseDbtUniqueId(node);
  return {
    failed_node: node || null,
    failed_node_short: parsed.failed_node_short,
    failed_node_resource: parsed.failed_node_resource,
    failed_node_project: parsed.failed_node_project,
    failed_node_note:
      parsed.failed_node_project
        ? "Prefer failed_node_short in answers; dbt project slug '" +
          parsed.failed_node_project +
          "' may differ from pipeline_name"
        : null,
  };
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
    const runId = (input.run_id || "").toString().trim();
    if (!runId) {
      return reply({ success: false, error: "run_id is required" });
    }

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    const runs = await runMysqlQuery(
      "SELECT id, pipeline_id, pipeline_name, status, " +
        "start_time, end_time, duration, " +
        "tool_name, rows_read, rows_written, rows_added, " +
        "failure_stage, failed_node, failed_message, " +
        "failed_nodes_json, error_class, " +
        "error_message, triggered_by, execution_mode " +
        "FROM obs_pipeline_runs WHERE id = ? LIMIT 1",
      [runId]
    );

    if (!runs || runs.length === 0) {
      return reply({
        success: false,
        error: "No run found for run_id=" + runId,
        data: { server_now: server_now, timezone: "UTC" },
      });
    }

    const r = runs[0];
    const assets = await runMysqlQuery(
      "SELECT asset_role, system_name, system_type, " +
        "database_name, schema_name, object_name, object_type, " +
        "row_count, last_updated_at, observed_at, dataset_id " +
        "FROM obs_run_assets WHERE run_id = ? " +
        "ORDER BY asset_role, dataset_id",
      [runId]
    );

    const source = [];
    const target = [];
    for (let i = 0; i < (assets || []).length; i++) {
      const a = assets[i];
      const item = {
        dataset_id: a.dataset_id,
        database_name: a.database_name,
        schema_name: a.schema_name,
        object_name: a.object_name,
        row_count: a.row_count,
        last_updated_at: a.last_updated_at,
        observed_at: a.observed_at,
        system_name: a.system_name,
      };
      if ((a.asset_role || "").toUpperCase() === "TARGET") {
        target.push(item);
      } else {
        source.push(item);
      }
    }

    let lineage_hint = "No assets stored for this run yet";
    if (source.length || target.length) {
      lineage_hint =
        "SOURCE tables (" +
        source.length +
        ") -> pipeline run -> TARGET tables (" +
        target.length +
        ")";
    }

    let failedNodes = [];
    if (r.failed_nodes_json) {
      try {
        const parsed = JSON.parse(String(r.failed_nodes_json));
        if (Array.isArray(parsed)) failedNodes = parsed;
      } catch (e) {
        failedNodes = [];
      }
    }
    failedNodes = failedNodes.map(function (n) {
      const uid = n && n.unique_id != null ? n.unique_id : null;
      const parsed = parseDbtUniqueId(uid);
      return Object.assign({}, n, {
        unique_id_short: parsed.failed_node_short,
        unique_id_project: parsed.failed_node_project,
      });
    });

    function clipMsg(v, maxLen) {
      if (v === null || v === undefined || v === "") return null;
      const s = String(v);
      if (s.length <= maxLen) return s;
      return s.slice(0, maxLen);
    }

    const nodeFields = withFailedNodeFields(r.failed_node);

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        run: {
          run_id: r.id,
          pipeline_id: r.pipeline_id,
          pipeline_name: r.pipeline_name,
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
          failure_stage: r.failure_stage,
          error_class: r.error_class,
          failed_node: nodeFields.failed_node,
          failed_node_short: nodeFields.failed_node_short,
          failed_node_resource: nodeFields.failed_node_resource,
          failed_node_project: nodeFields.failed_node_project,
          failed_node_note: nodeFields.failed_node_note,
          failed_message: clipMsg(r.failed_message, 8000),
          failed_nodes: failedNodes,
          error_message: clipMsg(r.error_message, 8000),
          triggered_by: r.triggered_by,
          execution_mode: r.execution_mode,
        },
        assets: { SOURCE: source, TARGET: target },
        lineage_hint: lineage_hint,
      },
      agentResponseContext:
        "Lead with pipeline_name + status. If failed: quote failure_stage, error_class, prefer failed_node_short (e.g. stg_employees), then full failed_message. failed_node_project may differ from pipeline_name — do not claim wrong pipeline. List other failed_nodes unique_id_short if more than one. Include duration_display and rows. If TARGET empty and rows_written null, no target materialized. Never invent failure location or volumes.",
    });
  } catch (error) {
    console.error("obs-get-run-detail error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
