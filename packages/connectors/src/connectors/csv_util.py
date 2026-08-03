from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any


def read_csv_rows(source: str | Path | io.StringIO) -> list[dict[str, Any]]:
    """Load CSV into list of dicts; empty cells → omitted keys."""
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8-sig")
    elif isinstance(source, io.StringIO):
        text = source.getvalue()
    else:
        # path string or raw CSV text
        path = Path(source)
        text = path.read_text(encoding="utf-8-sig") if path.is_file() else str(source)

    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    rows: list[dict[str, Any]] = []
    for raw in reader:
        cleaned: dict[str, Any] = {}
        for k, v in raw.items():
            if k is None:
                continue
            key = k.strip()
            if not key:
                continue
            if v is None:
                continue
            val = v.strip()
            if val == "":
                continue
            cleaned[key] = _coerce(val)
        if cleaned:
            rows.append(cleaned)
    return rows


def _coerce(value: str) -> Any:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
