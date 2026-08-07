"""
Register hr_etl in Metadata MySQL (does not replace stock_etl as active).

Run from repo root:
  python application/register_hr_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from application.src.pipelines import get_hr_etl_pipeline, new_pipeline_id
from application.src.store.meta_mysql import list_pipelines, upsert_pipeline


def main() -> None:
    pipeline = get_hr_etl_pipeline(pipeline_id=new_pipeline_id())
    # Keep stock_etl as the Sync default unless you pass make_active=True
    result = upsert_pipeline(pipeline, make_active=False)
    print("Registered:", result)
    print("All pipelines:")
    for row in list_pipelines():
        print(
            " -",
            row.get("pipeline_name"),
            "|",
            row.get("pipeline_id"),
            "| active=",
            row.get("is_active"),
            "|",
            f"{row.get('source_tool')}/{row.get('source_schema')} -> "
            f"{row.get('etl_tool')} -> "
            f"{row.get('target_tool')}/{row.get('target_schema')}",
        )


if __name__ == "__main__":
    main()
