"""
Near-realtime poller (Phase 3).

Every SYNC_INTERVAL_SECONDS (default 300):
  - For each enabled pipeline, run Sync (dbt + warehouse snapshots)
  - Record collector heartbeats
  - Optionally roll up yesterday's metrics and purge raw rows past retention
  - Evaluate monitors → alerts / incidents

Run from repo root:
  python application/poller.py

Env:
  SYNC_INTERVAL_SECONDS=300
  POLLER_PIPELINE_NAME=   (optional: only one pipeline name)
  RAW_RETENTION_DAYS=30
  POLLER_RUN_EVALUATE=1
  POLLER_RUN_ROLLUP=1
  POLLER_RUN_PURGE=1
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> None:
    from application.src.store import meta_mysql as store
    from application.src.sync_once import run_sync_once
    from application.src.services.observability.lifecycle import evaluate_monitors

    interval = int(os.getenv("SYNC_INTERVAL_SECONDS") or "300")
    only_name = (os.getenv("POLLER_PIPELINE_NAME") or "").strip() or None
    print(f"Poller starting interval={interval}s only_name={only_name or '*'}")

    while True:
        tick_start = time.time()
        conn = None
        try:
            conn = store.get_connection()
            store.ensure_tables(conn)
            try:
                store.migrate_pipeline_bindings(conn)
            except Exception as exc:
                print("bindings migrate warn:", exc)
            pipes = store.list_pipelines()
            if only_name:
                pipes = [p for p in pipes if str(p.get("pipeline_name")) == only_name]
            # Skip junk placeholder ids
            pipes = [p for p in pipes if str(p.get("pipeline_id") or "") not in {"string", "null", "undefined"}]

            for p in pipes:
                pid = str(p.get("pipeline_id") or "")
                pname = str(p.get("pipeline_name") or "")
                try:
                    result = run_sync_once(pipeline_id=pid, pipeline_name=pname)
                    store.record_heartbeat(
                        conn,
                        pid,
                        "poller",
                        ok=True,
                        meta={"pipeline_name": pname, "run_id": (result or {}).get("run_id")},
                    )
                    print(f"OK {pname} ({pid}) run={(result or {}).get('run_id')}")
                except Exception as exc:
                    store.record_heartbeat(conn, pid, "poller", ok=False, error=str(exc)[:500])
                    print(f"FAIL {pname} ({pid}): {exc}")

            store.bump_usage(conn, poll_ticks=1)
            conn.commit()

            if (os.getenv("POLLER_RUN_EVALUATE") or "1") == "1":
                try:
                    ev = evaluate_monitors(conn)
                    print("evaluate:", ev)
                except Exception as exc:
                    print("evaluate warn:", exc)
                try:
                    from application.src.services.observability.dq_rules import evaluate_dq_rules

                    dr = evaluate_dq_rules(conn)
                    print("evaluate_dq_rules:", dr)
                except Exception as exc:
                    print("evaluate_dq_rules warn:", exc)

            if (os.getenv("POLLER_RUN_ROLLUP") or "1") == "1":
                try:
                    n = store.rollup_daily_metrics(conn)
                    print(f"rollup rows≈{n}")
                except Exception as exc:
                    print("rollup warn:", exc)

            if (os.getenv("POLLER_RUN_PURGE") or "1") == "1":
                try:
                    purged = store.purge_raw_observations(conn)
                    print("purge:", purged)
                except Exception as exc:
                    print("purge warn:", exc)

        except Exception:
            traceback.print_exc()
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        elapsed = time.time() - tick_start
        sleep_for = max(5, interval - int(elapsed))
        print(f"sleep {sleep_for}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
