/**
 * obs-schema-diff — SOURCE vs TARGET columns from Metadata MySQL
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

function buildMaps(cols) {
  // column_name(upper) -> [{table, data_type, role}]
  const byName = {};
  for (let i = 0; i < (cols || []).length; i++) {
    const c = cols[i];
    const name = String(c.column_name || "").toUpperCase();
    if (!name) continue;
    if (!byName[name]) byName[name] = [];
    byName[name].push({
      table: c.object_name,
      schema: c.schema_name,
      data_type: c.data_type,
      dataset_id: c.dataset_id,
    });
  }
  return byName;
}

function primaryType(entries) {
  if (!entries || !entries.length) return null;
  return String(entries[0].data_type || "").toUpperCase();
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

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    let runId = (input.run_id || "").toString().trim();
    let pipelineName = resolved.pipeline_name;
    if (!runId) {
      const runs = await runMysqlQuery(
        "SELECT r.id, r.pipeline_name FROM obs_pipeline_runs r " +
          "WHERE r.pipeline_id = ? AND EXISTS (" +
          "  SELECT 1 FROM obs_run_columns c WHERE c.run_id = r.id" +
          ") ORDER BY COALESCE(r.end_time, r.start_time) DESC LIMIT 1",
        [resolved.pipeline_id]
      );
      if (!runs || !runs[0]) {
        // fallback latest run even without columns
        const any = await runMysqlQuery(
          "SELECT id, pipeline_name FROM obs_pipeline_runs " +
            "WHERE pipeline_id = ? ORDER BY COALESCE(end_time, start_time) DESC LIMIT 1",
          [resolved.pipeline_id]
        );
        if (!any || !any[0]) {
          return reply({
            success: false,
            error:
              "No runs stored for this pipeline. Run Sync after executions.",
            data: { server_now: server_now, timezone: "UTC" },
          });
        }
        runId = any[0].id;
        pipelineName = any[0].pipeline_name || pipelineName;
      } else {
        runId = runs[0].id;
        pipelineName = runs[0].pipeline_name || pipelineName;
      }
    }

    const cols = await runMysqlQuery(
      "SELECT asset_role, database_name, schema_name, object_name, " +
        "column_name, data_type, ordinal_position, dataset_id " +
        "FROM obs_run_columns WHERE run_id = ? ORDER BY asset_role, object_name, ordinal_position",
      [runId]
    );

    const sourceCols = (cols || []).filter(function (c) {
      return (c.asset_role || "").toUpperCase() === "SOURCE";
    });
    const targetCols = (cols || []).filter(function (c) {
      return (c.asset_role || "").toUpperCase() === "TARGET";
    });

    const srcMap = buildMaps(sourceCols);
    const tgtMap = buildMaps(targetCols);
    const srcNames = Object.keys(srcMap);
    const tgtNames = Object.keys(tgtMap);

    const only_in_source = [];
    const only_in_target = [];
    const type_mismatches = [];
    const in_both = [];

    for (let i = 0; i < srcNames.length; i++) {
      const n = srcNames[i];
      if (!tgtMap[n]) {
        only_in_source.push({
          column_name: n,
          source_tables: srcMap[n].map(function (x) {
            return x.table;
          }),
          source_type: primaryType(srcMap[n]),
        });
      } else {
        const st = primaryType(srcMap[n]);
        const tt = primaryType(tgtMap[n]);
        if (st && tt && st !== tt) {
          type_mismatches.push({
            column_name: n,
            source_type: st,
            target_type: tt,
          });
        } else {
          in_both.push({ column_name: n, data_type: st || tt });
        }
      }
    }
    for (let i = 0; i < tgtNames.length; i++) {
      const n = tgtNames[i];
      if (!srcMap[n]) {
        only_in_target.push({
          column_name: n,
          target_tables: tgtMap[n].map(function (x) {
            return x.table;
          }),
          target_type: primaryType(tgtMap[n]),
        });
      }
    }

    const hasMeta = (cols || []).length > 0;
    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        pipeline_id: resolved.pipeline_id,
        pipeline_name: pipelineName,
        run_id: runId,
        has_column_metadata: hasMeta,
        source_column_count: sourceCols.length,
        target_column_count: targetCols.length,
        source_tables: Array.from(
          new Set(
            sourceCols.map(function (c) {
              return c.object_name;
            })
          )
        ),
        target_tables: Array.from(
          new Set(
            targetCols.map(function (c) {
              return c.object_name;
            })
          )
        ),
        diff: {
          only_in_source: only_in_source,
          only_in_target: only_in_target,
          type_mismatches: type_mismatches,
          in_both_count: in_both.length,
        },
      },
      agentResponseContext: hasMeta
        ? "Quote pipeline_name and run_id. List only_in_source, only_in_target, type_mismatches with column names and types. Comparison is by column name across SOURCE vs TARGET tables. Do not invent columns. Never say metadata/Sync/MySQL to the user."
        : "Schema column details are not available for this run yet. Say that clearly in plain language — do not invent schema diffs. Never say metadata/Sync/MySQL to the user.",
    });
  } catch (error) {
    console.error("obs-schema-diff error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
