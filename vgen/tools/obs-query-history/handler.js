/**
 * obs-query-history — Snowflake query history snippets from Metadata MySQL
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
    for (const k of Object.keys(value)) out[k] = jsonSafeDeep(value[k]);
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

async function runMysqlQuery(sql, params) {
  if (!DB_PASSWORD) throw new Error("Database password not configured");
  const mysql = await loadMysql2();
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

var UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function resolvePipelineRef(input) {
  const idRaw = (input.pipeline_id || "").toString().trim();
  const nameRaw = (input.pipeline_name || "").toString().trim();
  const ref = idRaw || nameRaw;
  if (!ref) return { error: "pipeline_id or pipeline_name is required" };
  if (UUID_RE.test(ref)) {
    return { pipeline_id: ref, pipeline_name: null, resolved_from: "uuid" };
  }
  const rows = await runMysqlQuery(
    "SELECT pipeline_id, pipeline_name FROM obs_pipelines " +
      "WHERE LOWER(pipeline_name) = LOWER(?) " +
      "ORDER BY is_active DESC, updated_at DESC LIMIT 1",
    [ref]
  );
  if (!rows || !rows[0]) {
    return { error: "No pipeline found for name: " + ref };
  }
  return {
    pipeline_id: rows[0].pipeline_id,
    pipeline_name: rows[0].pipeline_name,
    resolved_from: "name",
  };
}

function clip(s, n) {
  const t = (s == null ? "" : String(s)).trim();
  if (!t) return null;
  if (t.length <= n) return t;
  return t.slice(0, n) + "…";
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
    const resolved = await resolvePipelineRef(input);
    if (resolved.error) {
      return reply({ success: false, error: resolved.error });
    }

    let limit = Number(input.limit);
    if (!Number.isFinite(limit) || limit <= 0) limit = 20;
    if (limit > 50) limit = 50;

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    let runId = (input.run_id || "").toString().trim();
    let pipelineName = resolved.pipeline_name;
    let runStatus = null;
    let errorMessage = null;
    let failedNode = null;
    let runStartTime = null;
    let runEndTime = null;

    function applyRunRow(row) {
      if (!row) return;
      pipelineName = row.pipeline_name || pipelineName;
      runStatus = row.status;
      errorMessage = row.error_message;
      failedNode = row.failed_node;
      runStartTime = row.start_time || null;
      runEndTime = row.end_time || null;
    }

    if (!runId) {
      const withQh = await runMysqlQuery(
        "SELECT r.id, r.pipeline_name, r.status, r.error_message, r.failed_node, " +
          "r.start_time, r.end_time " +
          "FROM obs_pipeline_runs r " +
          "WHERE r.pipeline_id = ? AND UPPER(COALESCE(r.status,'')) = 'FAILED' " +
          "AND EXISTS (SELECT 1 FROM obs_run_query_history q WHERE q.run_id = r.id) " +
          "ORDER BY COALESCE(r.end_time, r.start_time) DESC LIMIT 1",
        [resolved.pipeline_id]
      );
      if (withQh && withQh[0]) {
        runId = withQh[0].id;
        applyRunRow(withQh[0]);
      } else {
        const failed = await runMysqlQuery(
          "SELECT id, pipeline_name, status, error_message, failed_node, " +
            "start_time, end_time " +
            "FROM obs_pipeline_runs WHERE pipeline_id = ? " +
            "AND UPPER(COALESCE(status,'')) = 'FAILED' " +
            "ORDER BY COALESCE(end_time, start_time) DESC LIMIT 1",
          [resolved.pipeline_id]
        );
        if (!failed || !failed[0]) {
          return reply({
            success: false,
            error:
              "No failed runs found for this pipeline. Query history is only available after a failed run is recorded.",
            data: { server_now: server_now, timezone: "UTC" },
          });
        }
        runId = failed[0].id;
        applyRunRow(failed[0]);
      }
    } else {
      const runRows = await runMysqlQuery(
        "SELECT id, pipeline_name, status, error_message, failed_node, " +
          "start_time, end_time " +
          "FROM obs_pipeline_runs WHERE id = ? LIMIT 1",
        [runId]
      );
      applyRunRow(runRows && runRows[0]);
    }

    const qh = await runMysqlQuery(
      "SELECT query_id, start_time, end_time, warehouse_name, user_name, " +
        "database_name, schema_name, execution_status, error_code, " +
        "error_message, query_text " +
        "FROM obs_run_query_history WHERE run_id = ? " +
        "ORDER BY COALESCE(start_time, end_time) DESC LIMIT ?",
      [runId, limit]
    );

    const queries = (qh || []).map(function (row) {
      return {
        query_id: row.query_id,
        start_time: row.start_time,
        end_time: row.end_time,
        warehouse_name: row.warehouse_name,
        user_name: row.user_name,
        database_name: row.database_name,
        schema_name: row.schema_name,
        execution_status: row.execution_status,
        error_code: row.error_code,
        error_message: clip(row.error_message, 800),
        query_text: clip(row.query_text, 600),
      };
    });

    const hasMeta = queries.length > 0;
    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        pipeline_id: resolved.pipeline_id,
        pipeline_name: pipelineName,
        run_id: runId,
        run_status: runStatus,
        run_start_time: runStartTime,
        run_end_time: runEndTime,
        run_error_message: clip(errorMessage, 800),
        failed_node: failedNode,
        has_query_history: hasMeta,
        query_count: queries.length,
        queries: queries,
      },
      agentResponseContext: hasMeta
        ? "Quote pipeline_name, run_id, run_start_time/run_end_time (NOT server_now), failed_node, and the top failed query error_message + query_text snippet. Prefer FAILED execution_status rows. Do not invent SQL. Never say metadata/Sync/MySQL/INFO_SCHEMA/ACCOUNT_USAGE to the user."
        : "Snowflake query details are not available for this run. Quote run_id, run_start_time/run_end_time (NOT server_now), run_error_message, failed_node. Do not invent SQL or treat server_now as the run time. Never say metadata/Sync/MySQL/INFO_SCHEMA/ACCOUNT_USAGE to the user.",
    });
  } catch (error) {
    console.error("obs-query-history error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
