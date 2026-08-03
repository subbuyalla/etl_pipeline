from __future__ import annotations


class NormalizationError(Exception):
    """Base error for the normalization layer."""


class UnknownToolError(NormalizationError):
    def __init__(self, tool: str) -> None:
        self.tool = tool
        super().__init__(f"No mapper registered for source_system/tool '{tool}'")


class InvalidRawPayloadError(NormalizationError):
    def __init__(self, tool: str, detail: str) -> None:
        self.tool = tool
        self.detail = detail
        super().__init__(f"Invalid raw payload for '{tool}': {detail}")


class CanonicalValidationError(NormalizationError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Canonical event validation failed: {detail}")
