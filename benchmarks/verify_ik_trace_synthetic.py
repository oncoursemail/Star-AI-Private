"""Standalone synthetic developer checks for the new diagnostic module, not STAR's eval gate."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from star.ik_trace_quality import report_ik_trace

checks = 0


def close(actual, expected):
    assert math.isclose(actual, expected, abs_tol=1e-10, rel_tol=1e-10), (actual, expected)


def fixture(samples, scale=1):
    return {"schema_version": 1, "rig_scale": scale, "chains": [{"name": "limb", "samples": samples}]}


def frame(t=0, x=0, **extra):
    return {"t": t, "effector": [x, 0, 0], "target": [0, 0, 0], **extra}


def result(payload):
    return report_ik_trace(payload)["chains"][0]


def rejected(payload):
    global checks
    try:
        report_ik_trace(payload)
    except ValueError:
        checks += 1
    else:
        raise AssertionError("invalid trace accepted")


single = result(fixture([frame(x=2)], scale=4))["metrics"]
close(single["position_error_rig"]["max"], 0.5)
for key in ("orientation_error_deg", "speed_rig_per_second", "contact_error_rig", "contact_drift_rig"):
    assert single[key] == {"samples": 0, "mean": None, "rms": None, "p95": None, "max": None}
checks += 1

payload = fixture([frame(0, 0), frame(1, 1), frame(3, 9)])
snapshot = copy.deepcopy(payload)
metrics = result(payload)["metrics"]
close(metrics["speed_rig_per_second"]["max"], 4)
close(metrics["acceleration_rig_per_second2"]["max"], 2)
assert payload == snapshot
checks += 1

q = [0.1, 0.2, 0.3, math.sqrt(0.86)]
metrics = result(fixture([frame(0, effector_q=q, target_q=[-v for v in q])]))["metrics"]
assert metrics["orientation_error_deg"]["max"] == 0
checks += 1

half = math.sqrt(0.5)
metrics = result(fixture([frame(0, effector_q=[0, 0, 0, 1], target_q=[0, 0, 0, 1]),
                          frame(2.5, effector_q=[0, 0, half, half], target_q=[0, 0, 0, 1])]))["metrics"]
close(metrics["orientation_error_deg"]["max"], 90)
close(metrics["angular_speed_deg_per_second"]["max"], 36)
checks += 1

moving = [frame(t, 10*t, contact=True, contact_frame="platform-A", contact_position=[2, 0, 0],
                contact_anchor=[2, 0, 0]) for t in (0, 1, 2)]
metrics = result(fixture(moving))["metrics"]
close(metrics["speed_rig_per_second"]["max"], 10)
for key in ("contact_error_rig", "contact_drift_rig", "contact_slip_speed_rig_per_second"):
    assert metrics[key]["max"] == 0
checks += 1

reacquire = [frame(0, contact=True, contact_frame="A", contact_position=[0, 0, 0], contact_anchor=[0, 0, 0]),
             frame(1, contact=True, contact_frame="A", contact_position=[0.1, 0, 0], contact_anchor=[0, 0, 0]),
             frame(2, contact=False),
             frame(3, contact=True, contact_frame="A", contact_position=[100, 0, 0], contact_anchor=[100, 0, 0]),
             frame(4, contact=True, contact_frame="A", contact_position=[100.2, 0, 0], contact_anchor=[100, 0, 0])]
chain = result(fixture(reacquire))
assert chain["measured_contact_spans"] == 2
close(chain["metrics"]["contact_drift_rig"]["max"], 0.2)
assert chain["metrics"]["contact_drift_rig"]["samples"] == 2
checks += 1

gap = copy.deepcopy(reacquire)
gap[2] = frame(2, contact=True)
assert result(fixture(gap))["measured_contact_spans"] == 2
checks += 1

for bad in (True, float("nan"), float("inf"), -float("inf"), 10**10000, "1"):
    rejected(fixture([frame(x=bad)]))
for bad in (0, False, -1, float("nan")):
    rejected(fixture([frame()], bad))
for bad in (True, 1.0, 0, 2):
    data = fixture([frame()])
    data["schema_version"] = bad
    rejected(data)
for bad_time in (0, -1, 0.00000001, True):
    rejected(fixture([frame(), frame(bad_time)]))
rejected(fixture([frame(contact=1)]))
rejected(fixture([frame(effector_q=[0, 0, 0, 1])]))
rejected(fixture([frame(effector_q=[0, 0, 0, 0], target_q=[0, 0, 0, 1])]))
rejected(fixture([frame(effector_q=[0, 0, 0, 2], target_q=[0, 0, 0, 1])]))
rejected(fixture([frame(contact=True, contact_position=[0, 0, 0])]))
bad = copy.deepcopy(moving)
bad[1]["contact_anchor"] = [3, 0, 0]
rejected(fixture(bad))
bad = copy.deepcopy(moving)
bad[0]["contact"] = False
rejected(fixture(bad))
data = fixture([frame()])
data["chains"].append(copy.deepcopy(data["chains"][0]))
rejected(data)
rejected(fixture([]))
rejected(fixture([frame()]*10001))
rejected(fixture([frame(extra_field=1)]))

with tempfile.TemporaryDirectory(prefix="ik-trace-verify-") as directory:
    path = Path(directory) / "input.json"
    for text, expected_code in ((json.dumps(fixture([frame()])), 0),
                                ('{"schema_version":1,"schema_version":1}', 2),
                                ('{"schema_version":NaN}', 2),
                                ('{"bad":', 2),
                                (' '*(8*1024*1024+1), 2)):
        path.write_text(text)
        proc = subprocess.run([sys.executable, "-m", "star.ik_trace_quality", str(path)],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)
        assert proc.returncode == expected_code, proc.stderr
        if expected_code == 0:
            report = json.loads(proc.stdout)
            assert report["engine_capture_verified"] is False
            assert report["quality_proven"] is False
        else:
            assert proc.stdout == ""
        checks += 1

print(json.dumps({"synthetic_check_groups_passed": checks,
                  "engine_or_windows_tested": False,
                  "sealed_evaluation_run": False}))
