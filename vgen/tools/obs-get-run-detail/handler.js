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
  (typeof process !== "undefined" && process.env && process.env.DB_PASSWORD) ||
  "";
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
          error_message: r.error_message,
          triggered_by: r.triggered_by,
          execution_mode: r.execution_mode,
        },
        assets: { SOURCE: source, TARGET: target },
        lineage_hint: lineage_hint,
      },
      agentResponseContext:
        "Lead with status and error_message. Quote duration_display (SECONDS from duration_seconds). Include rows_added. Then SOURCE vs TARGET row counts. Never invent times.",
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
