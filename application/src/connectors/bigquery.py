"""Google BigQuery database connector (SOURCE / TARGET tool)."""

from __future__ import annotations

import os
from typing import Any


class BigQueryConnector:
    tool_id = "bigquery"
    kind = "database"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        project_id: str,
        dataset: str = "",
        location: str = "US",
        credentials_path: str | None = None,
        tables: list[str] | None = None,
        # Aliases used by tool config forms
        database_id: str | None = None,
        schema: str | None = None,
        **_: Any,
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.project_id = project_id or database_id or ""
        self.dataset = (dataset or schema or "").strip()
        self.location = location
        self.credentials_path = (
            credentials_path
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or ""
        )
        self.tables = [str(t).strip().upper() for t in (tables or []) if str(t).strip()]

    def _client(self):
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-bigquery is required. pip install google-cloud-bigquery"
            ) from exc
        if self.credentials_path:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", self.credentials_path)
        return bigquery.Client(project=self.project_id or None, location=self.location)

    def test_connection(self) -> dict[str, Any]:
        try:
            client = self._client()
            list(client.list_datasets(max_results=1))
            return {
                "ok": True,
                "message": "BigQuery connection OK",
                "details": {"project_id": self.project_id},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def pull_state(self) -> list[dict]:
        client = self._client()
        envelopes: list[dict] = []
        datasets = []
        if self.dataset:
            datasets = [self.dataset]
        else:
            datasets = [d.dataset_id for d in client.list_datasets()]

        for ds_id in datasets:
            for table in client.list_tables(f"{self.project_id}.{ds_id}"):
                name = table.table_id
                if self.tables and name.upper() not in self.tables:
                    continue
                full = client.get_table(table)
                envelopes.append(
                    {
                        "source_system": "bigquery",
                        "tenant_id": self.tenant_id,
                        "connector_instance_id": self.connector_instance_id,
                        "raw": {
                            "event_type": "discovered",
                            "database": self.project_id,
                            "schema": ds_id,
                            "table": name,
                            "dataset_id": f"{self.project_id}.{ds_id}.{name}",
                            "row_count": getattr(full, "num_rows", None),
                            "size_bytes": getattr(full, "num_bytes", None),
                            "last_altered": (
                                full.modified.isoformat()
                                if getattr(full, "modified", None)
                                else None
                            ),
                        },
                    }
                )
        return envelopes

    def run_column_validation(
        self,
        *,
        dataset_id: str,
        column_name: str,
        check_type: str,
        custom_sql: str | None = None,
        expected_max: int = 0,
    ) -> dict[str, Any]:
        from application.src.connectors.validation import (
            build_observed_result,
            parse_dataset_fqn,
            quote_ident_bq,
        )

        project, ds, table = parse_dataset_fqn(dataset_id)
        parts = [project, ds, table]
        col = str(column_name or "").strip()
        if not col:
            raise ValueError("column_name is required")
        fqn = ".".join(quote_ident_bq(p) for p in parts)
        col_q = quote_ident_bq(col)
        kind = (check_type or "").lower()
        client = self._client()

        if kind == "custom_sql" and custom_sql:
            row = list(client.query(custom_sql).result())
            actual = int(row[0][0]) if row else 0
            return build_observed_result(
                check_type="CUSTOM_SQL",
                parts=parts,
                column_name=col,
                actual_value=actual,
                expected_max=expected_max,
            )

        if kind in {"null_check", "null_pct"}:
            sql = f"SELECT COUNT(*) AS total_rows, COUNT({col_q}) AS non_null_rows FROM {fqn}"
            row = list(client.query(sql).result())
            total = int(row[0][0] or 0) if row else 0
            non_null = int(row[0][1] or 0) if row else 0
            null_count = total - non_null
            return build_observed_result(
                check_type="NOT_NULL",
                parts=parts,
                column_name=col,
                actual_value=null_count,
                expected_max=expected_max,
            )

        if kind in {"unique_check", "unique_violation", "duplicate_check", "duplicate_count"}:
            sql = f"SELECT COUNT(*) - COUNT(DISTINCT {col_q}) AS dup_count FROM {fqn}"
            row = list(client.query(sql).result())
            dup_count = int(row[0][0] or 0) if row else 0
            ctype = "UNIQUE" if "unique" in kind else "DUPLICATE"
            return build_observed_result(
                check_type=ctype,
                parts=parts,
                column_name=col,
                actual_value=dup_count,
                expected_max=expected_max,
            )

        raise ValueError(f"Unsupported check_type: {check_type}")
