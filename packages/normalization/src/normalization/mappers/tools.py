from __future__ import annotations

from typing import Any

from normalization.mappers.bi import BiMapper
from normalization.mappers.orchestration import OrchestrationMapper
from normalization.mappers.warehouse import WarehouseMapper
from normalization.utils import first, normalize_status, task_event_type


# --- ETL / Orchestration ---


class AirflowMapper(OrchestrationMapper):
    tool_id = "airflow"
    pipeline_keys = ("dag_id", "pipeline_id")
    run_keys = ("dag_run_id", "run_id", "execution_id")
    status_keys = ("state", "status")
    task_keys = ("task_id",)
    start_keys = ("start_date", "start_time")
    end_keys = ("end_date", "end_time")
    time_keys = ("execution_date", "logical_date", "data_interval_start", "end_date")


class GlueMapper(OrchestrationMapper):
    tool_id = "glue"
    pipeline_keys = ("JobName", "jobName", "job_name", "pipeline_id", "name")
    run_keys = ("Id", "id", "job_run_id", "run_id")
    status_keys = ("JobRunState", "jobRunState", "state", "status")
    start_keys = ("StartedOn", "start_time")
    end_keys = ("CompletedOn", "end_time")
    error_keys = ("ErrorMessage", "error_message", "error")


class InformaticaMapper(OrchestrationMapper):
    tool_id = "informatica"
    pipeline_keys = ("workflow_name", "mapping_name", "pipeline_id", "name", "taskFederatedId")
    run_keys = ("run_id", "session_id", "execution_id", "id")
    status_keys = ("status", "run_status", "state")
    task_keys = ("session_name", "task_name", "task_id")


class AdfMapper(OrchestrationMapper):
    tool_id = "adf"
    pipeline_keys = ("pipelineName", "pipeline_name", "pipeline", "pipeline_id", "name")
    run_keys = ("runId", "run_id", "pipeline_run_id", "activityRunId")
    status_keys = ("status", "state")
    task_keys = ("activity_name", "activityName", "task_id")
    start_keys = ("runStart", "activityRunStart", "start_time")
    end_keys = ("runEnd", "activityRunEnd", "end_time")


class TalendMapper(OrchestrationMapper):
    tool_id = "talend"
    pipeline_keys = ("job_name", "jobName", "executable", "pipeline_id", "name")
    run_keys = ("execution_id", "run_id", "pid", "id")
    status_keys = ("status", "state", "exit_status", "executionStatus")


class SsisMapper(OrchestrationMapper):
    tool_id = "ssis"
    pipeline_keys = ("package_name", "packageName", "folderName", "pipeline_id", "name")
    run_keys = ("execution_id", "ExecutionId", "run_id")
    status_keys = ("status", "Status", "state", "statusDescription")
    task_keys = ("task_name", "executable_name", "task_id")


class NifiMapper(OrchestrationMapper):
    tool_id = "nifi"
    pipeline_keys = ("process_group", "processGroupId", "processGroupName", "pipeline_id", "name", "flow_name")
    run_keys = ("bulletin_id", "flowfile_uuid", "run_id", "event_id", "id")
    status_keys = ("status", "state", "level")
    task_keys = ("component_name", "processor_name", "sourceName", "task_id")


class PrefectMapper(OrchestrationMapper):
    tool_id = "prefect"
    pipeline_keys = ("flow_name", "flow_id", "name", "pipeline_id")
    run_keys = ("flow_run_id", "run_id", "id")
    status_keys = ("state_name", "state", "status")
    task_keys = ("task_name", "task_run_name", "task_id")


class DagsterMapper(OrchestrationMapper):
    tool_id = "dagster"
    pipeline_keys = ("job_name", "pipeline_name", "pipeline_id", "name")
    run_keys = ("run_id", "dagster_run_id", "execution_id", "runId")
    status_keys = ("status", "state")
    task_keys = ("op_name", "solid_name", "step_key", "task_id")


# --- ELT ---


class DbtMapper(OrchestrationMapper):
    """
    Production dbt support:
    - flat task/pipeline payloads
    - run_results.json ({ metadata, results: [...] })
    - each result → task.execution.*.v1
    - failed tests/models raise task failed
    """

    tool_id = "dbt"
    family = "elt_transform"
    pipeline_keys = ("project_name", "project", "pipeline_id", "name")
    run_keys = ("invocation_id", "run_id", "execution_id")
    status_keys = ("status", "state")
    task_keys = ("node_name", "model_name", "task_id", "unique_id")
    time_keys = ("compiled_at", "execute_completed_at", "occurred_at", "timestamp", "generated_at")

    def map_record(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # run_results node
        if "unique_id" in raw or first(raw, "unique_id"):
            unique_id = str(first(raw, "unique_id"))
            project = str(
                first(
                    raw,
                    "project_name",
                    "project_name",
                    default=unique_id.split(".")[1] if "." in unique_id else "dbt",
                )
            )
            # Prefer metadata.project_name from parent merge
            meta = raw.get("_parent_metadata") if isinstance(raw.get("_parent_metadata"), dict) else {}
            project = str(meta.get("project_name") or first(raw, "project_name", default=project))
            invocation = str(first(raw, "invocation_id", default=meta.get("invocation_id") or "unknown"))
            status = normalize_status(first(raw, "status", default="success"))
            # dbt uses error/fail/warn/skipped/pass/success
            if status in {"error", "fail", "failed"}:
                status = "failed"
            elif status in {"pass", "success", "succeeded"}:
                status = "succeeded"
            elif status == "warn":
                status = "succeeded"
            event_type = task_event_type(status)
            node_name = unique_id.split(".")[-1]
            timing = first(raw, "execution_time", "execution_time")
            duration_ms = None
            if timing is not None:
                try:
                    duration_ms = int(float(timing) * 1000)
                except (TypeError, ValueError):
                    duration_ms = None
            payload = {
                "pipeline_id": project,
                "task_id": unique_id,
                "execution_id": invocation,
                "status": status,
                "attempt": 1,
                "started_at": None,
                "finished_at": first(raw, "compiled_at", "execute_completed_at"),
                "error_message": first(raw, "message", "error_message"),
                "duration_ms": duration_ms,
                "resource_type": first(raw, "resource_type", default=unique_id.split(".")[0] if "." in unique_id else "model"),
            }
            return [
                self.event(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    payload=payload,
                    occurred_at=first(raw, "generated_at", "compiled_at", "occurred_at"),
                    connector_instance_id=connector_instance_id,
                    id_parts=[tenant_id, self.tool_id, event_type, project, unique_id, invocation, status],
                )
            ]
        return super().map_record(raw, tenant_id=tenant_id, connector_instance_id=connector_instance_id)


# --- Warehouses / DBs ---


class SnowflakeMapper(WarehouseMapper):
    tool_id = "snowflake"
    database_keys = ("database", "database_name", "DATABASE_NAME", "TABLE_CATALOG")
    schema_keys = ("schema", "schema_name", "SCHEMA_NAME", "TABLE_SCHEMA")
    dataset_keys = ("table", "table_name", "TABLE_NAME", "name", "dataset_id")


class BigQueryMapper(WarehouseMapper):
    tool_id = "bigquery"
    database_keys = ("project", "project_id", "database", "tableReference.projectId")
    schema_keys = ("dataset", "dataset_id", "schema", "tableReference.datasetId")
    dataset_keys = ("table", "table_id", "table_name", "name", "dataset_id", "tableReference.tableId")

    def map_record(self, raw, *, tenant_id, connector_instance_id=None):
        # Google API nested tableReference
        ref = raw.get("tableReference")
        if isinstance(ref, dict):
            raw = {
                **raw,
                "project": ref.get("projectId"),
                "dataset": ref.get("datasetId"),
                "table": ref.get("tableId"),
            }
        return super().map_record(raw, tenant_id=tenant_id, connector_instance_id=connector_instance_id)


class DatabricksMapper(WarehouseMapper):
    tool_id = "databricks"
    database_keys = ("catalog", "database", "catalog_name")
    schema_keys = ("schema", "schema_name")
    dataset_keys = ("table", "table_name", "name", "dataset_id", "full_name")


class RedshiftMapper(WarehouseMapper):
    tool_id = "redshift"


class OracleMapper(WarehouseMapper):
    tool_id = "oracle"
    schema_keys = ("owner", "OWNER", "schema", "schema_name")
    dataset_keys = ("table_name", "TABLE_NAME", "table", "object_name", "name", "dataset_id")


class PostgresMapper(WarehouseMapper):
    tool_id = "postgres"


class MysqlMapper(WarehouseMapper):
    tool_id = "mysql"
    schema_keys = ("database", "schema", "table_schema", "TABLE_SCHEMA")
    database_keys = ("database", "schema", "TABLE_SCHEMA")


class SqlServerMapper(WarehouseMapper):
    tool_id = "sqlserver"


# --- Streaming / storage ---


class KafkaMapper(WarehouseMapper):
    tool_id = "kafka"
    family = "streaming_storage"
    dataset_keys = ("topic", "topic_name", "dataset_id", "name", "table")
    schema_keys = ("cluster", "schema")
    database_keys = ("cluster", "database", "env")


class S3Mapper(WarehouseMapper):
    tool_id = "s3"
    family = "streaming_storage"
    dataset_keys = ("key", "Key", "path", "bucket_key", "object_key", "dataset_id", "name", "table")
    schema_keys = ("prefix", "schema")
    database_keys = ("bucket", "Bucket", "database")


class GcsMapper(WarehouseMapper):
    tool_id = "gcs"
    family = "streaming_storage"
    dataset_keys = ("object", "name", "path", "dataset_id", "table")
    schema_keys = ("prefix", "schema")
    database_keys = ("bucket", "database")


class AdlsMapper(WarehouseMapper):
    tool_id = "adls"
    family = "streaming_storage"
    dataset_keys = ("path", "name", "dataset_id", "table")
    schema_keys = ("filesystem", "container", "schema")
    database_keys = ("account", "database")


# --- SaaS / API sources ---


class SalesforceMapper(WarehouseMapper):
    tool_id = "salesforce"
    family = "saas_source"
    dataset_keys = ("object", "sobject", "name", "table", "dataset_id", "attributes.type")
    schema_keys = ("org", "schema")
    database_keys = ("org_id", "database", "org")

    def map_record(self, raw, *, tenant_id, connector_instance_id=None):
        attrs = raw.get("attributes")
        if isinstance(attrs, dict) and attrs.get("type") and "object" not in raw:
            raw = {**raw, "object": attrs["type"]}
        return super().map_record(raw, tenant_id=tenant_id, connector_instance_id=connector_instance_id)


class SapMapper(WarehouseMapper):
    tool_id = "sap"
    family = "saas_source"
    dataset_keys = ("table", "odata_entity", "name", "dataset_id")
    schema_keys = ("system", "schema")
    database_keys = ("system_id", "database", "system")


class GenericApiMapper(WarehouseMapper):
    tool_id = "generic_api"
    family = "saas_source"
    dataset_keys = ("resource", "endpoint", "name", "dataset_id", "table")
    schema_keys = ("api", "schema")
    database_keys = ("service", "database", "api")


# --- BI ---


class TableauMapper(BiMapper):
    tool_id = "tableau"


class LookerMapper(BiMapper):
    tool_id = "looker"


class PowerBiMapper(BiMapper):
    tool_id = "powerbi"
