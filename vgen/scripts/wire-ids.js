/**
 * After vgen tool/agent push, copy platform ids into agent/assistant YAMLs.
 * Usage from vgen/: node scripts/wire-ids.js
 */
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");

function readYamlId(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const m = text.match(/^id:\s*["']?([^"'\s#]+)/m);
  return m ? m[1].trim() : "";
}

function replaceListBlock(filePath, key, ids) {
  let text = fs.readFileSync(filePath, "utf8");
  const block = [key + ":"].concat(ids.map((id) => '  - "' + id + '"')).join("\n");
  // Match list items with optional indent (YAML allows "- id" or "  - id").
  const reMulti = new RegExp(
    "^" + key + ":\\n(?:[ \\t]*-[^\\n]*\\n)*",
    "m"
  );
  const reEmpty = new RegExp("^" + key + ":\\s*\\[\\s*\\]\\s*$", "m");
  if (reMulti.test(text)) {
    text = text.replace(reMulti, block + "\n");
  } else if (reEmpty.test(text)) {
    text = text.replace(reEmpty, block);
  } else {
    throw new Error("Could not find " + key + " block in " + filePath);
  }
  fs.writeFileSync(filePath, text);
  console.log("Updated " + key + " in " + path.relative(root, filePath));
}

const toolOrderObs = [
  "obs-list-pipelines",
  "obs-get-pipeline",
  "obs-list-runs",
  "obs-get-run-detail",
  "obs-get-health",
  "obs-compare-runs",
  "obs-fleet-health",
  "obs-last-success",
  "obs-schema-diff",
  "obs-query-history",
];
const toolOrderRca = [
  "obs-list-pipelines",
  "obs-list-runs",
  "obs-get-run-detail",
  "obs-get-health",
  "obs-compare-runs",
  "obs-schema-diff",
  "obs-query-history",
];

const toolIds = {};
for (const name of [...new Set([...toolOrderObs, ...toolOrderRca])]) {
  const id = readYamlId(path.join(root, "tools", name, "tool.yaml"));
  if (!id || id === '""') {
    console.warn("WARN: tools/" + name + "/tool.yaml has empty id");
  }
  toolIds[name] = id;
}

const obsSkills = toolOrderObs.map((n) => toolIds[n]).filter(Boolean);
const rcaSkills = toolOrderRca.map((n) => toolIds[n]).filter(Boolean);

if (obsSkills.length) {
  replaceListBlock(path.join(root, "agents", "observability-agent.yaml"), "skills", obsSkills);
}
if (rcaSkills.length) {
  replaceListBlock(path.join(root, "agents", "rca-agent.yaml"), "skills", rcaSkills);
}

const obsAgentId = readYamlId(path.join(root, "agents", "observability-agent.yaml"));
const rcaAgentId = readYamlId(path.join(root, "agents", "rca-agent.yaml"));
const agentIds = [obsAgentId, rcaAgentId].filter((id) => id && id !== '""');

if (agentIds.length) {
  replaceListBlock(
    path.join(root, "assistants", "etl-observability-assistant.yaml"),
    "agents",
    agentIds
  );
}

console.log("Done. Re-push agents and assistant after wiring.");
