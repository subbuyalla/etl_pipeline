/**
 * obs-fleet-health — health card for every registered pipeline (one FAAS call)
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
    return { failed_node_short: null, failed_node_project: null };
  }
  const s = String(uniqueId);
  const parts = s.split(".");
  if (parts.length >= 3) {
    return {
      failed_node_short: parts.slice(2).join("."),
      failed_node_project: parts[1],
    };
  }
  if (parts.length === 2) {
    return { failed_node_short: parts[1], failed_node_project: null };
  }
  return { failed_node_short: s, failed_node_project: null };
}

function parseRunDate(value) {
  const raw = (value || "").toString().trim();
  if (!raw) return null;
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (
    dt.getUTCFullYear() !== y ||
    dt.getUTCMonth() !== mo - 1 ||
    dt.getUTCDate() !== d
  ) {
    return null;
  }
  return m[1] + "-" + m[2] + "-" + m[3];
}

function resolveTimeWindow(timeWindow, runDate) {
  const explicitDate = parseRunDate(runDate);
  const twRaw = (timeWindow || "").toString().trim();
  const twLower = twRaw.toLowerCase();
  const twAsDate = parseRunDate(twRaw);
  const date = explicitDate || twAsDate;

  if (date) {
    return {
      time_window: date,
      clause: " AND DATE(start_time) = ?",
      clauseParams: [date],
      label: "calendar_day_" + date,
    };
  }
  if (twLower === "today") {
    return {
      time_window: "today",
      clause: " AND DATE(start_time) = UTC_DATE()",
      clauseParams: [],
      label: "today",
    };
  }
  if (twLower === "yesterday") {
    return {
      time_window: "yesterday",
      clause: " AND DATE(start_time) = DATE_SUB(UTC_DATE(), INTERVAL 1 DAY)",
      clauseParams: [],
      label: "yesterday",
    };
  }
  if (twLower === "last_24h" || twLower === "last24h") {
    return {
      time_window: "last_24h",
      clause: " AND start_time >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)",
      clauseParams: [],
      label: "last_24h",
    };
  }
  if (twLower === "last_7_days" || twLower === "last7days") {
    return {
      time_window: "last_7_days",
      clause: " AND start_time >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 7 DAY)",
      clauseParams: [],
      label: "last_7_days",
    };
  }
  return {
    time_window: null,
    clause: "",
    clauseParams: [],
    label: "lookback_runs",
  };
}

function clipMsg(v, maxLen) {
  if (v === null || v === undefined || v === "") return null;
  const s = String(v);
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen);
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

function parseMysqlDate(v) {
  if (!v) return null;
  if (v instanceof Date) return v;
  const s = String(v).replace(" ", "T");
  const d = new Date(s.endsWith("Z") ? s : s + "Z");
  return isNaN(d.getTime()) ? null : d;
}

async function summarizePipeline(pipe, window, lookback, slaHours, serverNowDate) {
  const pipelineId = pipe.pipeline_id;
  let runsSql =
    "SELECT id, status, start_time, end_time, duration, " +
    "rows_read, rows_written, rows_added, failure_stage, failed_node, error_class, error_message " +
    "FROM obs_pipeline_runs WHERE pipeline_id = ?" +
    window.clause +
    " ORDER BY start_time DESC";
  if (!window.time_window) {
    runsSql += " LIMIT " + lookback;
  } else {
    runsSql += " LIMIT 100";
  }
  const runParams = [pipelineId];
  if (window.clauseParams && window.clauseParams.length) {
    runParams.push.apply(runParams, window.clauseParams);
  }
  const runs = await runMysqlQuery(runsSql, runParams);
  const total = (runs || []).length;

  const latestRows = await runMysqlQuery(
    "SELECT id, status, start_time, end_time, duration, " +
      "rows_read, rows_written, rows_added, failure_stage, failed_node, error_class, error_message " +
      "FROM obs_pipeline_runs WHERE pipeline_id = ? ORDER BY start_time DESC LIMIT 1",
    [pipelineId]
  );
  const latest = latestRows && latestRows[0] ? latestRows[0] : null;

  let successCount = 0;
  let failedCount = 0;
  for (let i = 0; i < total; i++) {
    const st = (runs[i].status || "").toLowerCase();
    if (st === "success") successCount++;
    if (st === "failed") failedCount++;
  }
  const successRate = total ? successCount / total : null;
  const failureRate = total ? failedCount / total : null;

  let targetLagHours = null;
  let hasTargetAssets = false;
  if (latest) {
    const assets = await runMysqlQuery(
      "SELECT asset_role, last_updated_at FROM obs_run_assets WHERE run_id = ?",
      [latest.id]
    );
    let maxLag = null;
    for (let i = 0; i < (assets || []).length; i++) {
      if ((assets[i].asset_role || "").toUpperCase() !== "TARGET") continue;
      hasTargetAssets = true;
      const ts = parseMysqlDate(assets[i].last_updated_at);
      if (!ts || !serverNowDate) continue;
      const lag = (serverNowDate.getTime() - ts.getTime()) / 3600000;
      if (maxLag === null || lag > maxLag) maxLag = lag;
    }
    if (maxLag !== null) targetLagHours = Math.round(maxLag * 10) / 10;
    if (targetLagHours === null && (latest.status || "").toLowerCase() === "success") {
      const end = parseMysqlDate(latest.end_time);
      if (end && serverNowDate) {
        targetLagHours =
          Math.round(((serverNowDate.getTime() - end.getTime()) / 3600000) * 10) /
          10;
      }
    }
  }

  const latestStatus = latest ? (latest.status || "").toLowerCase() : null;
  const isFailedLatest = latestStatus === "failed";
  const isStale =
    targetLagHours === null ? null : targetLagHours > slaHours;
  const hasActiveIssue = Boolean(
    isFailedLatest ||
      (failureRate !== null && failureRate > 0) ||
      isStale === true
  );

  let health_status = "unknown";
  if (!latest) health_status = "no_runs";
  else if (isFailedLatest) health_status = "unhealthy";
  else if (isStale === true) health_status = "stale";
  else if (latestStatus === "success") health_status = "healthy";
  else health_status = latestStatus || "unknown";

  return {
    pipeline_id: pipelineId,
    pipeline_name: pipe.pipeline_name,
    is_active: Boolean(pipe.is_active),
    lineage_summary:
      (pipe.source_tool || "?") +
      "/" +
      (pipe.source_schema || "?") +
      " -> " +
      (pipe.etl_tool || "?") +
      " -> " +
      (pipe.target_tool || "?") +
      "/" +
      (pipe.target_schema || "?"),
    health_status: health_status,
    has_active_issue: hasActiveIssue,
    metrics: {
      runs_in_scope: total,
      success_count: successCount,
      failed_count: failedCount,
      success_rate: successRate,
      failure_rate: failureRate,
      has_run_metadata: total > 0 || Boolean(latest),
    },
    latest_run: latest
      ? (function () {
          const node = parseDbtUniqueId(latest.failed_node);
          return {
            run_id: latest.id,
            status: latest.status,
            start_time: latest.start_time,
            end_time: latest.end_time,
            duration_seconds: latest.duration,
            duration_display: formatDurationDisplay(latest.duration),
            rows_read: latest.rows_read,
            rows_written: latest.rows_written,
            rows_added: latest.rows_added,
            failure_stage: latest.failure_stage,
            error_class: latest.error_class,
            failed_node: latest.failed_node,
            failed_node_short: node.failed_node_short,
            failed_node_project: node.failed_node_project,
            error_message: clipMsg(latest.error_message, 500),
          };
        })()
      : null,
    freshness: {
      lag_hours: targetLagHours,
      is_stale: isStale,
      sla_hours: slaHours,
      has_target_assets: hasTargetAssets,
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
    let slaHours = Number(input.sla_hours != null ? input.sla_hours : 24);
    if (!isFinite(slaHours) || slaHours <= 0) slaHours = 24;
    let lookback = Number(
      input.lookback_runs != null ? input.lookback_runs : 10
    );
    if (!isFinite(lookback) || lookback < 1) lookback = 10;
    if (lookback > 100) lookback = 100;

    const window = resolveTimeWindow(input.time_window, input.run_date);
    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;
    const serverNowDate = parseMysqlDate(server_now) || new Date();

    const pipes = await runMysqlQuery(
      "SELECT pipeline_id, pipeline_name, source_tool, source_schema, " +
        "etl_tool, target_tool, target_schema, is_active " +
        "FROM obs_pipelines ORDER BY is_active DESC, pipeline_name ASC",
      []
    );

    const pipelines = [];
    for (let i = 0; i < (pipes || []).length; i++) {
      pipelines.push(
        await summarizePipeline(
          pipes[i],
          window,
          lookback,
          slaHours,
          serverNowDate
        )
      );
    }

    const withRates = pipelines
      .filter(function (p) {
        return p.metrics.failure_rate !== null;
      })
      .slice()
      .sort(function (a, b) {
        return (b.metrics.failure_rate || 0) - (a.metrics.failure_rate || 0);
      });

    const activeIssues = pipelines.filter(function (p) {
      return p.has_active_issue;
    });
    const noRuns = pipelines.filter(function (p) {
      return p.health_status === "no_runs";
    });

    const fleet_summary = {
      pipeline_count: pipelines.length,
      unhealthy_count: pipelines.filter(function (p) {
        return p.health_status === "unhealthy";
      }).length,
      healthy_count: pipelines.filter(function (p) {
        return p.health_status === "healthy";
      }).length,
      stale_count: pipelines.filter(function (p) {
        return p.health_status === "stale";
      }).length,
      no_runs_count: noRuns.length,
      active_issue_count: activeIssues.length,
      highest_failure_rate:
        withRates.length > 0
          ? {
              pipeline_name: withRates[0].pipeline_name,
              failure_rate: withRates[0].metrics.failure_rate,
              failed_count: withRates[0].metrics.failed_count,
              runs_in_scope: withRates[0].metrics.runs_in_scope,
            }
          : null,
      active_issue_pipelines: activeIssues.map(function (p) {
        return p.pipeline_name;
      }),
      no_run_pipelines: noRuns.map(function (p) {
        return p.pipeline_name;
      }),
    };

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        time_window: window.time_window,
        window_label: window.label,
        lookback_runs: window.time_window ? null : lookback,
        sla_hours: slaHours,
        fleet_summary: fleet_summary,
        pipelines: pipelines,
        ranked_by_failure_rate: withRates.map(function (p) {
          return {
            pipeline_name: p.pipeline_name,
            failure_rate: p.metrics.failure_rate,
            success_rate: p.metrics.success_rate,
            failed_count: p.metrics.failed_count,
            runs_in_scope: p.metrics.runs_in_scope,
            health_status: p.health_status,
          };
        }),
      },
      agentResponseContext:
        "Fleet tool — quote EVERY pipeline from data.pipelines. Prefer failed_node_short when quoting failures. For each: health_status, latest_run.status, rates with runs_in_scope, error snippet if failed. Use fleet_summary.highest_failure_rate and active_issue_pipelines. If no_runs say no runs recorded yet — NEVER invent 100% success. Never say metadata/Sync/MySQL to the user. Never write Evidence: 1. Answer: short summary then per-pipeline bullets.",
    });
  } catch (error) {
    console.error("obs-fleet-health error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
