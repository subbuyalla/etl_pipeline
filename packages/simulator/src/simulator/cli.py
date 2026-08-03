from __future__ import annotations

import argparse
import json
import re
import sys

from metadata.db import get_database_url
from simulator.estate import default_estate, estate_summary
from simulator.runner import bootstrap_and_stream, run_named_scenarios
from simulator.twin import SCENARIOS, DigitalTwinConnector


def _mask_db_url(url: str) -> str:
    return re.sub(r":([^:@/]+)@", r":****@", url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ETL Digital Twin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sum = sub.add_parser("summary", help="Show mock estate summary")
    p_sum.add_argument("--tenant-id", default="demo")

    p_db = sub.add_parser("db-url", help="Show resolved database URL (password masked)")

    p_boot = sub.add_parser("run", help="Bootstrap + stream mock events into Metadata")
    p_boot.add_argument("--tenant-id", default="demo")
    p_boot.add_argument("--ticks", type=int, default=40, help="Number of streamed envelopes after bootstrap")
    p_boot.add_argument("--seed", type=int, default=42)
    p_boot.add_argument("--db", default=None, help="SQLAlchemy URL override (else .env)")
    p_boot.add_argument("--no-bootstrap", action="store_true")

    p_sc = sub.add_parser("scenario", help="Run one or more named MC scenarios")
    p_sc.add_argument("names", nargs="+", choices=list(SCENARIOS))
    p_sc.add_argument("--tenant-id", default="demo")
    p_sc.add_argument("--db", default=None)

    p_dry = sub.add_parser("dry-run", help="Print sample raw envelopes (no DB write)")
    p_dry.add_argument("--ticks", type=int, default=5)
    p_dry.add_argument("--tenant-id", default="demo")

    args = parser.parse_args(argv)

    if args.cmd == "summary":
        print(json.dumps(estate_summary(default_estate(args.tenant_id)), indent=2))
        return 0

    if args.cmd == "db-url":
        print(_mask_db_url(get_database_url()))
        return 0

    if args.cmd == "dry-run":
        twin = DigitalTwinConnector(tenant_id=args.tenant_id)
        for i, env in enumerate(twin.stream_events(ticks=args.ticks)):
            print(json.dumps({"i": i, **env.to_dict()}, indent=2, default=str))
        return 0

    db = getattr(args, "db", None)

    if args.cmd == "run":
        stats = bootstrap_and_stream(
            tenant_id=args.tenant_id,
            ticks=args.ticks,
            seed=args.seed,
            database_url=db,
            bootstrap=not args.no_bootstrap,
        )
        discover_count = len(stats.pop("discover", []))
        stats["discover_assets"] = discover_count
        stats["database"] = _mask_db_url(db or get_database_url())
        print(json.dumps(stats, indent=2, default=str))
        return 0 if stats.get("dead_letters", 0) == 0 else 1

    if args.cmd == "scenario":
        stats = run_named_scenarios(args.names, tenant_id=args.tenant_id, database_url=db)
        stats["database"] = _mask_db_url(db or get_database_url())
        print(json.dumps(stats, indent=2, default=str))
        return 0 if stats.get("dead_letters", 0) == 0 else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
