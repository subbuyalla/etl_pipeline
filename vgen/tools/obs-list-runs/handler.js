/**
 * obs-list-runs — FAAS handler (matches working mysql2 FAAS pattern)
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

function resolveTimeWindow(timeWindow) {
  const raw = (timeWindow || "").toString().trim().toLowerCase();
  if (!raw) {
    return {
      clause: "",
      window_start: null,
      window_end: null,
      time_window: null,
    };
  }
  if (raw === "today") {
    return {
      clause: " AND DATE(start_time) = CURDATE()",
      window_start: "CURDATE() 00:00:00",
      window_end: "CURDATE() + 1 day",
      time_window: "today",
    };
  }
  if (raw === "yesterday") {
    return {
      clause: " AND DATE(start_time) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)",
      window_start: "yesterday 00:00:00",
      window_end: "today 00:00:00",
      time_window: "yesterday",
    };
  }
  if (raw === "last_24h" || raw === "last24h") {
    return {
      clause: " AND start_time >= (UTC_TIMESTAMP() - INTERVAL 24 HOUR)",
      window_start: "UTC_TIMESTAMP() - 24h",
      window_end: "UTC_TIMESTAMP()",
      time_window: "last_24h",
    };
  }
  if (raw === "last_7_days" || raw === "last7days" || raw === "last_7d") {
    return {
      clause: " AND start_time >= (UTC_TIMESTAMP() - INTERVAL 7 DAY)",
      window_start: "UTC_TIMESTAMP() - 7d",
      window_end: "UTC_TIMESTAMP()",
      time_window: "last_7_days",
    };
  }
  throw new Error(
    "Unsupported time_window. Use: today, yesterday, last_24h, last_7_days, or omit."
  );
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

var UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function resolvePipelineRef(input) {
  const idRaw = (input.pipeline_id || "").toString().trim();
  const nameRaw = (input.pipeline_name || "").toString().trim();
  const ref = idRaw || nameRaw;
  if (!ref) {
    return { error: "pipeline_id or pipeline_name is required" };
  }
  if (UUID_RE.test(ref)) {
    return {
      pipeline_id: ref,
      pipeline_name: null,
      resolved_from: "uuid",
    };
  }
  const rows = await runMysqlQuery(
    "SELECT pipeline_id, pipeline_name FROM obs_pipelines " +
      "WHERE LOWER(pipeline_name) = LOWER(?) " +
      "ORDER BY is_active DESC, updated_at DESC LIMIT 1",
    [ref]
  );
  if (!rows || rows.length === 0) {
    const fuzzy = await runMysqlQuery(
      "SELECT pipeline_id, pipeline_name FROM obs_pipelines " +
        "WHERE pipeline_name LIKE ? " +
        "ORDER BY is_active DESC, updated_at DESC LIMIT 5",
      ["%" + ref + "%"]
    );
    if (!fuzzy || fuzzy.length === 0) {
      return { error: "No pipeline found for name: " + ref };
    }
    if (fuzzy.length > 1) {
      return {
        error:
          "Multiple pipelines match '" +
          ref +
          "'. Use exact pipeline_name or pipeline_id UUID.",
        matches: fuzzy.map(function (r) {
          return {
            pipeline_id: r.pipeline_id,
            pipeline_name: r.pipeline_name,
          };
        }),
      };
    }
    return {
      pipeline_id: fuzzy[0].pipeline_id,
      pipeline_name: fuzzy[0].pipeline_name,
      resolved_from: "name_fuzzy",
    };
  }
  return {
    pipeline_id: rows[0].pipeline_id,
    pipeline_name: rows[0].pipeline_name,
    resolved_from: "name",
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
    const resolved = await resolvePipelineRef(input);
    if (resolved.error) {
      return reply({
        success: false,
        error: resolved.error,
        matches: resolved.matches || undefined,
      });
    }
    const pipelineId = resolved.pipeline_id;

    let limit = Number(input.limit != null ? input.limit : 20);
    if (!isFinite(limit) || limit < 1) limit = 20;
    if (limit > 100) limit = 100;

    const statusRaw = (input.status || "").toString().trim().toLowerCase();
    const status = statusRaw ? statusRaw : null;

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;
    const window = resolveTimeWindow(input.time_window);

    const params = [pipelineId];
    let sql =
      "SELECT id, pipeline_id, pipeline_name, status, " +
      "start_time, end_time, duration, " +
      "tool_name, rows_read, rows_written, rows_added, " +
      "LEFT(error_message, 500) AS error_message, " +
      "triggered_by FROM obs_pipeline_runs WHERE pipeline_id = ?";

    if (status) {
      sql += " AND LOWER(status) = ?";
      params.push(status);
    }
    sql += window.clause;
    sql += " ORDER BY start_time DESC LIMIT " + limit;

    const rows = await runMysqlQuery(sql, params);
    const runs = (rows || []).map(function (r) {
      return {
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
      };
    });

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        time_window: window.time_window,
        window_start: window.window_start,
        window_end: window.window_end,
        pipeline_id: pipelineId,
        pipeline_name: resolved.pipeline_name,
        count: runs.length,
        runs: runs,
      },
      agentResponseContext:
        runs.length === 0
          ? "No runs in this window. Say so using server_now from the tool. Do not invent runs or durations."
          : "Quote duration_display or duration_seconds (SECONDS) for each run. Never invent minutes or times not in this response.",
    });
  } catch (error) {
    console.error("obs-list-runs error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
