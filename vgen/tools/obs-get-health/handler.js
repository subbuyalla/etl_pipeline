/**
 * obs-get-health — FAAS handler (matches working mysql2 FAAS pattern)
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

/** Format duration for agents — values in DB are seconds, never invent minutes. */
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

function pctChange(curr, prev) {
  if (prev === null || prev === undefined || Number(prev) === 0) return null;
  if (curr === null || curr === undefined) return null;
  return ((Number(curr) - Number(prev)) / Number(prev)) * 100;
}

function parseMysqlDate(v) {
  if (!v) return null;
  if (v instanceof Date) return v;
  const d = new Date(String(v).replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return null;
  return d;
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

/** Accept pipeline_id (UUID) OR pipeline_name (e.g. stock_etl). Agents often pass name in pipeline_id. */
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

    let slaHours = Number(input.sla_hours != null ? input.sla_hours : 24);
    if (!isFinite(slaHours) || slaHours <= 0) slaHours = 24;

    let lookback = Number(
      input.lookback_runs != null ? input.lookback_runs : 10
    );
    if (!isFinite(lookback) || lookback < 1) lookback = 10;
    if (lookback > 100) lookback = 100;

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;
    const serverNowDate = parseMysqlDate(server_now) || new Date();
    const window = resolveTimeWindow(input.time_window);

    const pipes = await runMysqlQuery(
      "SELECT pipeline_id, pipeline_name, source_tool, source_schema, " +
        "etl_tool, target_tool, target_schema, is_active " +
        "FROM obs_pipelines WHERE pipeline_id = ? LIMIT 1",
      [pipelineId]
    );
    if (!pipes || pipes.length === 0) {
      return reply({
        success: false,
        error: "No pipeline found for pipeline_id=" + pipelineId,
        data: { server_now: server_now, timezone: "UTC" },
      });
    }
    const pipe = pipes[0];

    let runsSql =
      "SELECT id, status, start_time, end_time, duration, " +
      "rows_read, rows_written, rows_added, error_message " +
      "FROM obs_pipeline_runs WHERE pipeline_id = ?" +
      window.clause +
      " ORDER BY start_time DESC";
    if (!window.time_window) {
      runsSql += " LIMIT " + lookback;
    } else {
      runsSql += " LIMIT 100";
    }

    const runs = await runMysqlQuery(runsSql, [pipelineId]);
    const total = runs.length;
    let successCount = 0;
    let failedCount = 0;
    let rowsAddedSum = 0;
    let rowsAddedCount = 0;
    for (let i = 0; i < runs.length; i++) {
      const st = (runs[i].status || "").toLowerCase();
      if (st === "success") successCount++;
      if (st === "failed") failedCount++;
      if (runs[i].rows_added !== null && runs[i].rows_added !== undefined) {
        rowsAddedSum += Number(runs[i].rows_added);
        rowsAddedCount++;
      }
    }
    const successRate = total ? successCount / total : null;
    const latest = runs[0] || null;
    const previous = runs[1] || null;

    let latestAssets = [];
    let previousAssets = [];
    if (latest) {
      latestAssets = await runMysqlQuery(
        "SELECT asset_role, dataset_id, row_count, last_updated_at, schema_name, object_name " +
          "FROM obs_run_assets WHERE run_id = ?",
        [latest.id]
      );
    }
    if (previous) {
      previousAssets = await runMysqlQuery(
        "SELECT asset_role, dataset_id, row_count FROM obs_run_assets WHERE run_id = ?",
        [previous.id]
      );
    }

    const prevMap = {};
    for (let p = 0; p < (previousAssets || []).length; p++) {
      prevMap[previousAssets[p].dataset_id] = previousAssets[p].row_count;
    }

    const volume = (latestAssets || []).map(function (a) {
      return {
        dataset_id: a.dataset_id,
        asset_role: a.asset_role,
        row_count: a.row_count,
        previous_row_count:
          prevMap[a.dataset_id] !== undefined ? prevMap[a.dataset_id] : null,
        pct_change: pctChange(a.row_count, prevMap[a.dataset_id]),
      };
    });

    const targetAssets = [];
    const sourceTables = [];
    for (let t = 0; t < (latestAssets || []).length; t++) {
      const role = (latestAssets[t].asset_role || "").toUpperCase();
      if (role === "TARGET") targetAssets.push(latestAssets[t]);
      if (role === "SOURCE") sourceTables.push(latestAssets[t].dataset_id);
    }

    let maxLagHours = null;
    let freshestTarget = null;
    for (let j = 0; j < targetAssets.length; j++) {
      const ts = parseMysqlDate(targetAssets[j].last_updated_at);
      if (!ts) continue;
      const lagH = (serverNowDate - ts) / (1000 * 60 * 60);
      if (maxLagHours === null || lagH > maxLagHours) {
        maxLagHours = lagH;
        freshestTarget = targetAssets[j].dataset_id;
      }
    }

    if (maxLagHours === null) {
      let lastSuccess = null;
      for (let s = 0; s < runs.length; s++) {
        if ((runs[s].status || "").toLowerCase() === "success") {
          lastSuccess = runs[s];
          break;
        }
      }
      const ts2 = lastSuccess
        ? parseMysqlDate(lastSuccess.end_time || lastSuccess.start_time)
        : null;
      if (ts2) {
        maxLagHours = (serverNowDate - ts2) / (1000 * 60 * 60);
      }
    }

    let durationSum = 0;
    let durationCount = 0;
    for (let d = 0; d < runs.length; d++) {
      if (runs[d].duration !== null && runs[d].duration !== undefined) {
        durationSum += Number(runs[d].duration);
        durationCount++;
      }
    }

    let latest_run = null;
    if (latest) {
      latest_run = {
        run_id: latest.id,
        status: latest.status,
        start_time: latest.start_time,
        end_time: latest.end_time,
        duration_seconds: latest.duration,
        duration_display: formatDurationDisplay(latest.duration),
        rows_read: latest.rows_read,
        rows_written: latest.rows_written,
        rows_added: latest.rows_added,
        error_message: latest.error_message
          ? String(latest.error_message).slice(0, 500)
          : null,
      };
    }

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        time_window: window.time_window,
        window_start: window.window_start,
        window_end: window.window_end,
        pipeline: {
          pipeline_id: pipe.pipeline_id,
          pipeline_name: pipe.pipeline_name,
          resolved_from: resolved.resolved_from,
          is_active: Boolean(pipe.is_active),
          lineage_summary:
            pipe.source_tool +
            "/" +
            pipe.source_schema +
            " -> " +
            pipe.etl_tool +
            " -> " +
            pipe.target_tool +
            "/" +
            pipe.target_schema,
          source_schema: pipe.source_schema,
          etl_tool: pipe.etl_tool,
          target_schema: pipe.target_schema,
        },
        latest_run: latest_run,
        freshness: {
          sla_hours: slaHours,
          lag_hours:
            maxLagHours !== null ? Math.round(maxLagHours * 100) / 100 : null,
          is_stale: maxLagHours !== null ? maxLagHours > slaHours : null,
          reference_dataset_id: freshestTarget,
        },
        volume: volume,
        metrics: {
          runs_in_scope: total,
          success_count: successCount,
          failed_count: failedCount,
          success_rate:
            successRate !== null ? Math.round(successRate * 1000) / 1000 : null,
          avg_duration_seconds:
            durationCount > 0 ? Math.round(durationSum / durationCount) : null,
          avg_duration_display:
            durationCount > 0
              ? formatDurationDisplay(Math.round(durationSum / durationCount))
              : null,
          duration_unit: "seconds",
          total_rows_added:
            rowsAddedCount > 0 ? rowsAddedSum : null,
          latest_rows_added:
            latest && latest.rows_added != null ? latest.rows_added : null,
        },
        source_tables: sourceTables,
        target_tables: targetAssets.map(function (a) {
          return a.dataset_id;
        }),
      },
      agentResponseContext:
        "Quote ONLY tool numbers. avg_duration_seconds and duration_seconds are SECONDS — use avg_duration_display/duration_display when present. Never invent minutes. Include freshness, success rate, rows_added, lineage. Quote server_now.",
    });
  } catch (error) {
    console.error("obs-get-health error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
