"""Reproducible read-only local benchmark for STAR map-plan preflight."""
import statistics
import time
from star.map_plan import dry_run

parts = [
    {"name": f"Platform {i}", "position": [0, 3, i * 5 - 4500],
     "size": [2, 1, 2], "role": "platform"}
    for i in range(1600)
]
plan = {
    "mapName": "Long Course Benchmark",
    "bounds": {"size": [200, 80, 20000]},
    "parts": [{"name": "Floor", "position": [0, -.5, 0], "size": [80, 1, 80]}, *parts],
    "spawns": [{"name": "Spawn", "position": [20, .5, 0]}],
    "limits": {"maxObjects": 4000},
}

dry_run(plan, include_operations=False)  # lazy jsonschema import warmup
timings = []
for i in range(5):
    t = time.perf_counter()
    out = dry_run(plan, include_operations=False)
    timings.append(time.perf_counter() - t)
assert out["ok"], out["blockers"]
print("median_seconds", round(statistics.median(timings), 4))
print("runs_seconds", [round(t, 4) for t in timings])
print("parts", len(parts), "is_exhaustive", out.get("collision_audit", {}).get("exhaustive"))
