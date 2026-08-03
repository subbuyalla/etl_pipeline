from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from connectors.runner import TOOLS, build_connector, ingest_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="connectors", description="CSV-backed Snowflake / dbt connectors")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="List assets from CSV")
    p_disc.add_argument("--tool", required=True, choices=sorted(TOOLS))
    p_disc.add_argument("--csv", required=True, help="Path to CSV file")
    p_disc.add_argument("--tenant-id", default="demo")

    p_ing = sub.add_parser("ingest", help="Normalize CSV and write to Metadata")
    p_ing.add_argument("--tool", required=True, choices=sorted(TOOLS))
    p_ing.add_argument("--csv", required=True)
    p_ing.add_argument("--tenant-id", default="demo")

    p_list = sub.add_parser("list-tools", help="List connector tools")

    args = parser.parse_args(argv)

    if args.cmd == "list-tools":
        print(json.dumps(sorted(TOOLS), indent=2))
        return 0

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 2

    if args.cmd == "discover":
        conn = build_connector(args.tool, csv_path, tenant_id=args.tenant_id)
        print(json.dumps({"tool": args.tool, "assets": conn.discover()}, indent=2, default=str))
        return 0

    if args.cmd == "ingest":
        stats = ingest_csv(args.tool, csv_path, tenant_id=args.tenant_id)
        print(json.dumps(stats, indent=2, default=str))
        return 0 if not stats.get("errors") else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
