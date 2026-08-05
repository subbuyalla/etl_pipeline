/**
 * obs-list-pipelines — FAAS handler (matches working mysql2 FAAS pattern)
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
    return {
      success: false,
      error: "Tool output could not be serialized.",
    };
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
    const nameFilter = (input.name_filter || "").toString().trim();

    const nowRows = await runMysqlQuery(
      "SELECT UTC_TIMESTAMP() AS server_now",
      []
    );
    const server_now =
      nowRows && nowRows[0] ? nowRows[0].server_now : null;

    let rows;
    if (nameFilter) {
      rows = await runMysqlQuery(
        "SELECT pipeline_id, pipeline_name, tenant_id, description, " +
          "source_tool, source_schema, etl_tool, " +
          "target_tool, target_schema, is_active, updated_at " +
          "FROM obs_pipelines WHERE pipeline_name LIKE ? " +
          "ORDER BY is_active DESC, updated_at DESC",
        ["%" + nameFilter + "%"]
      );
    } else {
      rows = await runMysqlQuery(
        "SELECT pipeline_id, pipeline_name, tenant_id, description, " +
          "source_tool, source_schema, etl_tool, " +
          "target_tool, target_schema, is_active, updated_at " +
          "FROM obs_pipelines ORDER BY is_active DESC, updated_at DESC",
        []
      );
    }

    const pipelines = (rows || []).map(function (r) {
      return {
        pipeline_id: r.pipeline_id,
        pipeline_name: r.pipeline_name,
        is_active: Boolean(r.is_active),
        description: r.description,
        lineage_summary:
          (r.source_tool || "?") +
          "/" +
          (r.source_schema || "?") +
          " -> " +
          (r.etl_tool || "?") +
          " -> " +
          (r.target_tool || "?") +
          "/" +
          (r.target_schema || "?"),
        source_tool: r.source_tool,
        source_schema: r.source_schema,
        etl_tool: r.etl_tool,
        target_tool: r.target_tool,
        target_schema: r.target_schema,
        updated_at: r.updated_at,
      };
    });

    let agentResponseContext;
    if (pipelines.length === 0) {
      agentResponseContext =
        "No pipelines found. Tell the user none are registered yet.";
    } else if (pipelines.length === 1) {
      agentResponseContext =
        "Only one pipeline exists. You may use it and tell the user which one.";
    } else {
      agentResponseContext =
        "Multiple pipelines. List name + lineage_summary + id and ask which one.";
    }

    return reply({
      success: true,
      data: {
        server_now: server_now,
        timezone: "UTC",
        count: pipelines.length,
        pipelines: pipelines,
      },
      agentResponseContext: agentResponseContext,
    });
  } catch (error) {
    console.error("obs-list-pipelines error:", error);
    return reply({
      success: false,
      error: (error && error.message) || String(error),
    });
  }
}

export default handler;
export { handler };
