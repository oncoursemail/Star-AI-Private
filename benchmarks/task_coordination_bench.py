"""Microbenchmark for STAR's durable task/communication ledger.

Run from the repository root:
    python benchmarks/task_coordination_bench.py --tasks 1000
Use --database PATH for file-backed WAL and --synchronous FULL|NORMAL to compare
the durability/performance trade-off. This is not a production SLA.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time

from star.task_coordination import TaskLedger, TaskLedgerConfig, TaskStatus


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--database", default=":memory:")
    parser.add_argument("--synchronous", choices=("FULL", "NORMAL"), default="FULL")
    args = parser.parse_args()
    if not 1 <= args.tasks <= 100_000:
        parser.error("--tasks must be from 1 to 100000")

    durations: list[float] = []
    started = time.perf_counter()
    config = TaskLedgerConfig(synchronous=args.synchronous)
    with TaskLedger(args.database, config) as ledger:
        for index in range(args.tasks):
            task_id = f"bench-{index}"
            logical_now = 1_800_000_000.0 + index * 100.0
            task_started = time.perf_counter()
            ledger.create_task(
                task_id, "Benchmark task", now=logical_now,
                event_id=f"create-{index}", priority=index % 101,
            )
            ledger.transition(
                task_id, 1, TaskStatus.ACCEPTED,
                now=logical_now + 1, event_id=f"accept-{index}",
            )
            ledger.claim_task(
                task_id, 1, "benchmark-worker", f"lease-{index}",
                now=logical_now + 2, event_id=f"claim-{index}",
            )
            ledger.checkpoint_task(
                task_id, 1, f"checkpoint://{index}",
                now=logical_now + 3, event_id=f"checkpoint-{index}",
                lease_id=f"lease-{index}",
            )
            evidence_ref = f"evidence://{index}"
            ledger.transition(
                task_id, 1, TaskStatus.COMPLETED,
                now=logical_now + 4, event_id=f"complete-{index}",
                lease_id=f"lease-{index}",
                result_ref=f"artifact://{index}", evidence_ref=evidence_ref,
            )
            ledger.queue_report(
                f"report-{index}", task_id, 1,
                f"content://{index}", evidence_ref,
                now=logical_now + 5, event_id=f"queue-report-{index}",
            )
            ledger.mark_report_played(
                f"report-{index}", 1, f"playback-{index}",
                now=logical_now + 6, event_id=f"played-{index}",
            )
            durations.append(time.perf_counter() - task_started)
        elapsed = time.perf_counter() - started
        stats = ledger.stats

    operations = args.tasks * 7
    result = {
        "database": args.database,
        "synchronous": args.synchronous,
        "tasks": args.tasks,
        "operations": operations,
        "elapsed_seconds": round(elapsed, 6),
        "tasks_per_second": round(args.tasks / elapsed, 2),
        "ledger_operations_per_second": round(operations / elapsed, 2),
        "per_task_latency_ms": {
            "p50": round(statistics.median(durations) * 1000, 3),
            "p95": round(percentile(durations, 0.95) * 1000, 3),
            "max": round(max(durations) * 1000, 3),
        },
        "final_stats": {
            "tasks": stats.tasks,
            "events": stats.events,
            "reports": stats.reports,
            "queued_reports": stats.queued_reports,
            "completed_tasks": stats.completed_tasks,
            "stale_report_count": stats.stale_reports,
        },
        "note": "Local microbenchmark only; compare on the same host and database mode.",
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
