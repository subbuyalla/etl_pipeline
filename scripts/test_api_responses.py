"""Smoke-test Metadata + Assistants GET/list endpoints and sample responses."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

METADATA = "http://127.0.0.1:8000"
ASSISTANTS = "http://127.0.0.1:8001"
TENANT = "demo"


def get(base: str, path: str, params: dict | None = None) -> tuple[int, object]:
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            body = res.read().decode()
            return res.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def post(base: str, path: str, payload: dict) -> tuple[int, object]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read().decode()
            return res.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def keys_of(obj: object) -> list[str]:
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return sorted(obj[0].keys())
    return []


def main() -> int:
    results: list[dict] = []
    t = TENANT

    tests: list[tuple[str, str, str, dict | None]] = [
        ("metadata", "GET", "/health", None),
        ("metadata", "GET", "/v1/catalog", None),
        ("metadata", "GET", "/v1/pipelines", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/datasets", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/executions", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/incidents", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/alerts", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/monitors", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/check-results", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/lineage", {"tenant_id": t, "limit": 5}),
        ("metadata", "GET", "/v1/connectors", None),
        ("metadata", "GET", "/v1/connectors/catalog", None),
        ("metadata", "GET", "/v1/connectors/instances", {"tenant_id": t}),
        ("assistants", "GET", "/health", None),
    ]

    # First pass — collect sample IDs
    _, pipelines = get(METADATA, "/v1/pipelines", {"tenant_id": t, "limit": 1})
    _, datasets = get(METADATA, "/v1/datasets", {"tenant_id": t, "limit": 1})
    _, incidents = get(METADATA, "/v1/incidents", {"tenant_id": t, "limit": 1})
    _, lineage = get(METADATA, "/v1/lineage", {"tenant_id": t, "limit": 1})

    pipeline_id = (pipelines.get("items") or [{}])[0].get("pipeline_id") if isinstance(pipelines, dict) else None
    dataset_id = (datasets.get("items") or [{}])[0].get("dataset_id") if isinstance(datasets, dict) else None
    incident_key = (incidents.get("items") or [{}])[0].get("incident_key") if isinstance(incidents, dict) else None
    lineage_ds = (lineage.get("items") or [{}])[0].get("downstream_dataset_id") if isinstance(lineage, dict) else None
    if not dataset_id and lineage_ds:
        dataset_id = lineage_ds

    for layer, method, path, params in tests:
        base = METADATA if layer == "metadata" else ASSISTANTS
        status, data = get(base, path, params)
        item_keys = []
        if isinstance(data, dict) and "items" in data and data["items"]:
            item_keys = keys_of(data["items"])
        results.append(
            {
                "layer": layer,
                "path": path,
                "status": status,
                "top_keys": keys_of(data),
                "item_keys": item_keys,
                "count": len(data.get("items", [])) if isinstance(data, dict) else None,
                "sample": data if path == "/health" else _truncate(data),
            }
        )

    if pipeline_id:
        path = f"/v1/pipelines/{urllib.parse.quote(pipeline_id, safe='')}/dashboard"
        status, data = get(METADATA, path, {"tenant_id": t})
        results.append({"layer": "metadata", "path": path, "status": status, "top_keys": keys_of(data), "sample": _truncate(data)})

    if dataset_id:
        enc = urllib.parse.quote(dataset_id, safe="")
        for path, params in [
            (f"/v1/datasets/{enc}", {"tenant_id": t}),
            ("/v1/check-results", {"tenant_id": t, "asset_id": dataset_id, "limit": 3}),
            ("/v1/lineage/blast-radius", {"tenant_id": t, "dataset_id": dataset_id}),
        ]:
            status, data = get(METADATA, path, params)
            results.append(
                {
                    "layer": "metadata",
                    "path": path,
                    "status": status,
                    "top_keys": keys_of(data),
                    "item_keys": keys_of(data.get("items", [])) if isinstance(data, dict) else [],
                    "sample": _truncate(data),
                }
            )

    if incident_key:
        enc = urllib.parse.quote(incident_key, safe="")
        status, data = get(METADATA, f"/v1/incidents/{enc}", {"tenant_id": t})
        results.append({"layer": "metadata", "path": f"/v1/incidents/{{key}}", "status": status, "top_keys": keys_of(data), "sample": _truncate(data)})

    print(json.dumps(results, indent=2, default=str))
    failed = [r for r in results if r["status"] >= 400]
    print("\n--- SUMMARY ---", file=sys.stderr)
    print(f"Total: {len(results)}, Failed: {len(failed)}", file=sys.stderr)
    for r in failed:
        print(f"  FAIL {r['status']} {r['path']}", file=sys.stderr)
    return 1 if failed else 0


def _truncate(data: object, max_len: int = 600) -> object:
    s = json.dumps(data, default=str)
    if len(s) <= max_len:
        return data
    return {"_truncated": True, "preview": s[:max_len]}


if __name__ == "__main__":
    raise SystemExit(main())
