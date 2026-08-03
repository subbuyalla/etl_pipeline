"""
Template for a new production connector.

1. Rename this module and tool_id.
2. Fill SPEC + create_<tool>_connector.
3. Register in connectors.registry._register_builtins.
4. Add a Normalization mapper for source_system=<tool_id> if missing.
"""

from __future__ import annotations

from typing import Any, Iterator

from connector_sdk import ConnectionResult, Connector, ConnectorContext, ConnectorSpec, RawEnvelope

# EXAMPLE_SPEC = ConnectorSpec(
#     tool_id="my_tool",
#     display_name="My Tool",
#     description="Describe what this connector syncs.",
#     auth_kinds=["token"],
#     capabilities=["catalog"],
#     secret_fields=["api_token"],
#     input_modes=["live"],
#     config_schema={
#         "type": "object",
#         "required": ["host"],
#         "properties": {
#             "host": {"type": "string", "title": "Host"},
#             "api_token_env": {"type": "string", "title": "Token env var", "default": "MY_TOOL_TOKEN"},
#         },
#     },
# )


class MyToolConnector(Connector):
    tool_id = "my_tool"

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx

    def test_connection(self) -> ConnectionResult:
        return ConnectionResult(ok=True, message="Replace with a real ping")

    def discover(self) -> list[dict[str, Any]]:
        return []

    def pull_state(self) -> list[RawEnvelope]:
        # Emit vendor-shaped raw dicts only — never canonical events.
        return [
            RawEnvelope(
                source_system=self.tool_id,
                tenant_id=self.ctx.tenant_id,
                raw={"example": True},
                connector_instance_id=self.ctx.connector_instance_id,
            )
        ]

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        yield from self.pull_state()


def create_my_tool_connector(ctx: ConnectorContext) -> Connector:
    return MyToolConnector(ctx)
