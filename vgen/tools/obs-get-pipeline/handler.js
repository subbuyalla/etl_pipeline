/**
 * obs-get-pipeline — FAAS handler (matches working mysql2 FAAS pattern)
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

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    const rows = await runMysqlQuery(
      "SELECT pipeline_id, pipeline_name, tenant_id, description, " +
        "source_tool, source_instance_id, source_schema, " +
        "etl_tool, etl_instance_id, " +
        "target_tool, target_instance_id, target_schema, " +
        "is_active, created_at, updated_at " +
        "FROM obs_pipelines WHERE pipeline_id = ? LIMIT 1",
      [pipelineId]
    );

    if (!rows || rows.length === 0) {
      return reply({
        success: false,
        error: "No pipeline found for pipeline_id=" + pipelineId,
        data: { server_now: server_now, timezone: "UTC" },
      });
    }

    const r = rows[0];
    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        pipeline: {
          pipeline_id: r.pipeline_id,
          pipeline_name: r.pipeline_name,
          tenant_id: r.tenant_id,
          description: r.description,
          is_active: Boolean(r.is_active),
          source: {
            tool: r.source_tool,
            instance_id: r.source_instance_id,
            schema: r.source_schema,
          },
          etl: {
            tool: r.etl_tool,
            instance_id: r.etl_instance_id,
          },
          target: {
            tool: r.target_tool,
            instance_id: r.target_instance_id,
            schema: r.target_schema,
          },
          lineage_summary:
            r.source_tool +
            "/" +
            r.source_schema +
            " -> " +
            r.etl_tool +
            " -> " +
            r.target_tool +
            "/" +
            r.target_schema,
          created_at: r.created_at,
          updated_at: r.updated_at,
        },
      },
      agentResponseContext:
        "Present lineage_summary clearly. Do not expose passwords.",
    });
  } catch (error) {
    console.error("obs-get-pipeline error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
