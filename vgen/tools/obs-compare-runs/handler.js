/**
 * obs-compare-runs — last success vs latest failed for RCA
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

function clipMsg(v, maxLen) {
  if (v === null || v === undefined || v === "") return null;
  const s = String(v);
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen);
}

function toNum(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function delta(a, b) {
  const x = toNum(a);
  const y = toNum(b);
  if (x === null || y === null) return null;
  return y - x;
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

const RUN_SELECT =
  "SELECT id, pipeline_id, pipeline_name, status, " +
  "start_time, end_time, duration, " +
  "tool_name, rows_read, rows_written, rows_added, " +
  "failure_stage, failed_node, failed_message, " +
  "failed_nodes_json, error_class, " +
  "error_message, triggered_by, execution_mode " +
  "FROM obs_pipeline_runs ";

async function loadRunById(runId) {
  const rows = await runMysqlQuery(RUN_SELECT + "WHERE id = ? LIMIT 1", [runId]);
  return rows && rows[0] ? rows[0] : null;
}

async function loadAssets(runId) {
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
  return { SOURCE: source, TARGET: target };
}

function parseFailedNodes(raw) {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(String(raw));
    if (!Array.isArray(parsed)) return [];
    return parsed.map(function (n) {
      const uid = n && n.unique_id != null ? n.unique_id : null;
      const p = parseDbtUniqueId(uid);
      return Object.assign({}, n, {
        unique_id_short: p.failed_node_short,
        unique_id_project: p.failed_node_project,
      });
    });
  } catch (e) {
    return [];
  }
}

function shapeRun(r) {
  if (!r) return null;
  const node = parseDbtUniqueId(r.failed_node);
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
    failure_stage: r.failure_stage,
    error_class: r.error_class,
    failed_node: r.failed_node || null,
    failed_node_short: node.failed_node_short,
    failed_node_resource: node.failed_node_resource,
    failed_node_project: node.failed_node_project,
    failed_node_note: node.failed_node_project
      ? "Prefer failed_node_short; dbt project slug may differ from pipeline_name"
      : null,
    failed_message: clipMsg(r.failed_message, 8000),
    failed_nodes: parseFailedNodes(r.failed_nodes_json),
    error_message: clipMsg(r.error_message, 8000),
    triggered_by: r.triggered_by,
    execution_mode: r.execution_mode,
  };
}

function assetTotals(assets) {
  const src = (assets && assets.SOURCE) || [];
  const tgt = (assets && assets.TARGET) || [];
  let srcSum = 0;
  let tgtSum = 0;
  let srcN = 0;
  let tgtN = 0;
  for (let i = 0; i < src.length; i++) {
    const n = toNum(src[i].row_count);
    if (n !== null) {
      srcSum += n;
      srcN += 1;
    }
  }
  for (let i = 0; i < tgt.length; i++) {
    const n = toNum(tgt[i].row_count);
    if (n !== null) {
      tgtSum += n;
      tgtN += 1;
    }
  }
  return {
    source_table_count: src.length,
    target_table_count: tgt.length,
    source_row_sum: srcN ? srcSum : null,
    target_row_sum: tgtN ? tgtSum : null,
  };
}

function buildVolumeHints(success, failed, successAssets, failedAssets) {
  const hints = [];
  const sRead = toNum(success && success.rows_read);
  const fRead = toNum(failed && failed.rows_read);
  const sWrite = toNum(success && success.rows_written);
  const fWrite = toNum(failed && failed.rows_written);
  const fAssets = assetTotals(failedAssets);
  const sAssets = assetTotals(successAssets);

  if (fRead !== null && fWrite !== null && fRead > fWrite) {
    hints.push(
      "On failed run, rows_read (" +
        fRead +
        ") > rows_written (" +
        fWrite +
        ") — possible mid-run fail, empty/missing target, or transform drop."
    );
  }
  if (fAssets.target_table_count === 0 && fAssets.source_table_count > 0) {
    hints.push(
      "Failed run has SOURCE assets but no TARGET assets — target table may be missing or filter found nothing."
    );
  }
  if (
    sWrite !== null &&
    fWrite !== null &&
    fWrite < sWrite
  ) {
    hints.push(
      "Target volume dropped vs last success (rows_written " +
        sWrite +
        " → " +
        fWrite +
        ")."
    );
  }
  if (
    sAssets.target_row_sum !== null &&
    fAssets.target_row_sum !== null &&
    fAssets.target_row_sum < sAssets.target_row_sum
  ) {
    hints.push(
      "TARGET asset row_sum dropped (" +
        sAssets.target_row_sum +
        " → " +
        fAssets.target_row_sum +
        ")."
    );
  }
  if (failed && (failed.failure_stage || failed.error_class || failed.failed_node)) {
    hints.push(
      "Stored failure points to stage=" +
        (failed.failure_stage || "unknown") +
        ", class=" +
        (failed.error_class || "unknown") +
        ", model=" +
        (failed.failed_node_short || failed.failed_node || "unknown") +
        "."
    );
  }
  return hints;
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

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    const pipelineId = resolved.pipeline_id;
    let failedRow = null;
    let successRow = null;

    const failedRunId = (input.failed_run_id || "").toString().trim();
    const successRunId = (input.success_run_id || "").toString().trim();

    if (failedRunId) {
      failedRow = await loadRunById(failedRunId);
      if (!failedRow) {
        return reply({
          success: false,
          error: "No run found for failed_run_id=" + failedRunId,
          data: { server_now: server_now, timezone: "UTC" },
        });
      }
      if (
        failedRow.pipeline_id &&
        String(failedRow.pipeline_id) !== String(pipelineId)
      ) {
        return reply({
          success: false,
          error:
            "failed_run_id does not belong to pipeline_id=" + pipelineId,
        });
      }
    } else {
      const failedRows = await runMysqlQuery(
        RUN_SELECT +
          "WHERE pipeline_id = ? AND LOWER(status) = 'failed' " +
          "ORDER BY COALESCE(end_time, start_time) DESC, id DESC LIMIT 1",
        [pipelineId]
      );
      failedRow = failedRows && failedRows[0] ? failedRows[0] : null;
    }

    if (successRunId) {
      successRow = await loadRunById(successRunId);
      if (!successRow) {
        return reply({
          success: false,
          error: "No run found for success_run_id=" + successRunId,
          data: { server_now: server_now, timezone: "UTC" },
        });
      }
    } else if (failedRow) {
      const before = await runMysqlQuery(
        RUN_SELECT +
          "WHERE pipeline_id = ? AND LOWER(status) = 'success' " +
          "AND COALESCE(end_time, start_time) < COALESCE(?, start_time, end_time) " +
          "ORDER BY COALESCE(end_time, start_time) DESC, id DESC LIMIT 1",
        [pipelineId, failedRow.end_time || failedRow.start_time]
      );
      successRow = before && before[0] ? before[0] : null;
      if (!successRow) {
        const anyOk = await runMysqlQuery(
          RUN_SELECT +
            "WHERE pipeline_id = ? AND LOWER(status) = 'success' " +
            "ORDER BY COALESCE(end_time, start_time) DESC, id DESC LIMIT 1",
          [pipelineId]
        );
        successRow = anyOk && anyOk[0] ? anyOk[0] : null;
      }
    } else {
      const anyOk = await runMysqlQuery(
        RUN_SELECT +
          "WHERE pipeline_id = ? AND LOWER(status) = 'success' " +
          "ORDER BY COALESCE(end_time, start_time) DESC, id DESC LIMIT 1",
        [pipelineId]
      );
      successRow = anyOk && anyOk[0] ? anyOk[0] : null;
    }

    if (!failedRow && !successRow) {
      return reply({
        success: false,
        error:
          "No success or failed runs stored for this pipeline yet. Run Sync after executions.",
        data: {
          server_now: server_now,
          timezone: "UTC",
          pipeline_id: pipelineId,
          pipeline_name: resolved.pipeline_name,
        },
      });
    }

    const successAssets = successRow
      ? await loadAssets(successRow.id)
      : { SOURCE: [], TARGET: [] };
    const failedAssets = failedRow
      ? await loadAssets(failedRow.id)
      : { SOURCE: [], TARGET: [] };

    const success = shapeRun(successRow);
    const failed = shapeRun(failedRow);

    const deltas = {
      duration_seconds: delta(
        success && success.duration_seconds,
        failed && failed.duration_seconds
      ),
      rows_read: delta(success && success.rows_read, failed && failed.rows_read),
      rows_written: delta(
        success && success.rows_written,
        failed && failed.rows_written
      ),
      rows_added: delta(
        success && success.rows_added,
        failed && failed.rows_added
      ),
    };

    const volume_hints = buildVolumeHints(
      success,
      failed,
      successAssets,
      failedAssets
    );

    const compare_summary = {
      has_success: Boolean(success),
      has_failed: Boolean(failed),
      status_flip:
        success && failed
          ? "success → failed"
          : failed
            ? "failed (no prior success in recorded history)"
            : "success only (no failed run in recorded history)",
      failure_stage: failed ? failed.failure_stage : null,
      error_class: failed ? failed.error_class : null,
      failed_node: failed ? failed.failed_node : null,
      failed_node_short: failed ? failed.failed_node_short : null,
      volume_hints: volume_hints,
    };

    let agentResponseContext =
      "Compare last success vs latest failed under tool pipeline_name. Prefer failed_node_short in Evidence/Fix. Quote run_ids, status_flip, deltas, failure_stage, error_class, failed_message, volume_hints. failed_node_project may differ from pipeline_name. If no prior success, say so. If TARGET empty on failed run, no target materialized. Do not invent causes.";
    if (!failed) {
      agentResponseContext =
        "No failed run found. Report last success only and say there is no failed run in the recorded history to compare. Never say metadata/Sync/MySQL to the user.";
    } else if (!success) {
      agentResponseContext =
        "No success run found to compare in recorded history. Lead with failed run using failed_node_short, failure_stage, error_class, message, SOURCE vs TARGET. Do not claim wrong pipeline from dbt project slug. If TARGET empty, no target materialized. Never say metadata/Sync/MySQL to the user.";
    }

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        pipeline_id: pipelineId,
        pipeline_name:
          resolved.pipeline_name ||
          (failed && failed.pipeline_name) ||
          (success && success.pipeline_name),
        resolved_from: resolved.resolved_from,
        compare_summary: compare_summary,
        deltas: deltas,
        last_success: success
          ? { run: success, assets: successAssets }
          : null,
        latest_failed: failed
          ? { run: failed, assets: failedAssets }
          : null,
      },
      agentResponseContext: agentResponseContext,
    });
  } catch (error) {
    console.error("obs-compare-runs error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
