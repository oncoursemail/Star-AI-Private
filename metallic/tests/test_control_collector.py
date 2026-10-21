"""Metallic Control collector: rates from counters, the brain router's formats, alerts, request mapping, PC pushes."""
from __future__ import annotations

import json

from metallic.control import collector as col
from metallic.control.store import Store

METRICS = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
llamacpp:prompt_tokens_total 243015
llamacpp:prompt_tokens_cached_total 432758
llamacpp:prompt_seconds_total 5589.06
llamacpp:tokens_predicted_total 220496
llamacpp:tokens_predicted_seconds_total 25741.5
llamacpp:spec_decode_num_draft_tokens_total 243320
llamacpp:spec_decode_num_accepted_tokens_total 142495
llamacpp:predicted_tokens_seconds 8.55483
llamacpp:requests_processing 1
llamacpp:requests_deferred 0
llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="0"} 57131
"""
MODELS = {"data": [
    {"id": "star-fast", "status": {"value": "loaded", "args": ["/x/llama-server", "--port", "46613", "--parallel", "2",
                                                               "--ctx-size", "65536", "--cache-ram", "24576",
                                                               "--spec-type", "draft-dspark,ngram-mod"]}},
    {"id": "star-deep", "status": {"value": "unloaded", "args": ["--port", "0", "--parallel", "1"]}},
    {"id": "star-embed", "status": {"value": "loaded", "args": ["--embeddings", "--port", "59175"]}},
]}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_cpu_and_counter_rates():
    assert col.cpu_percent([100, 0, 100, 700, 100, 0, 0, 0], [150, 0, 150, 750, 150, 0, 0, 0]) == 50.0
    assert col.cpu_percent(None, [1, 2, 3, 4, 5]) is None
    assert col.rate(1000, 3000, 2.0) == 1000.0
    assert col.rate(4_000_000_000, 10, 10.0) is None          # 32-bit wrap / reboot: no negative rate
    assert col.cpu_temperature({"k10temp/Tctl": 73.4, "k10temp/Tccd1": 70.0, "nvme/Composite": 80.0}) == 73.4
    assert col.cpu_temperature({"acpitz/temp1": 30.0}) is None


def test_router_models_and_metrics():
    models = col.router_models(MODELS)
    fast = models[0]
    assert (fast["port"], fast["parallel"], fast["ctx"], fast["cache_ram_mib"], fast["helper"]) == (
        "46613", 2, 65536, 24576, False)
    assert models[1]["status"] == "unloaded" and models[2]["helper"] is True
    m = col.parse_prometheus(METRICS)
    assert m["tokens_predicted_total"] == 220496 and "spec_decode_num_accepted_tokens_per_pos_total" not in m
    after = dict(m, tokens_predicted_total=m["tokens_predicted_total"] + 100,
                 tokens_predicted_seconds_total=m["tokens_predicted_seconds_total"] + 10,
                 spec_decode_num_draft_tokens_total=m["spec_decode_num_draft_tokens_total"] + 50,
                 spec_decode_num_accepted_tokens_total=m["spec_decode_num_accepted_tokens_total"] + 30)
    live = col.model_rates(m, after, 20.0)
    assert live["decode_tps"] == 10.0 and live["output_tps"] == 5.0 and live["draft_accept"] == 0.6
    assert live["cache_share_total"] == round(432758 / (432758 + 243015), 3)
    assert col.slot_summary([{"id": 0, "is_processing": False, "n_ctx": 32768},
                             {"id": 1, "is_processing": True, "n_ctx": 32768}]) == {"total": 2, "busy": 1, "ctx": 32768}


def test_poll_brain_never_asks_unloaded_or_helper_models():
    asked = []

    def fetch(path):
        asked.append(path)
        if path == "/v1/models":
            return json.dumps(MODELS).encode()
        if path.startswith("/slots"):
            return json.dumps([{"id": 0, "is_processing": True, "n_ctx": 32768}]).encode()
        return METRICS.encode()
    c = col.Collector({"brain": {"machine": "brain1"}}, Store(":memory:", clock=Clock(100.0)), clock=Clock(100.0))
    c.poll_brain(fetch)
    assert asked == ["/v1/models", "/slots?model=star-fast", "/metrics?model=star-fast"]
    fast = c.star["models"][0]
    assert fast["slots"]["busy"] == 1 and fast["live"]["deferred"] == 0
    assert c.sources["brain"]["error"] == ""


def _sample(t, cpu, net, ct_usec, fs_used=90):
    return json.dumps({"kind": "sample", "t": t, "cpu": cpu, "ncpu": 48, "load": [1.0, 1.0, 1.0],
                       "mem": {"total": 100, "available": 40, "swap_total": 10, "swap_free": 5},
                       "net": {"eno2": net}, "disk": {"sda": [0, 0]}, "fs": {"/": [100, fs_used, 100 - fs_used]},
                       "temps": {"k10temp/Tctl": 70.0},
                       "ct": {"starai": {"cpu_usec": ct_usec, "mem": 50, "mem_max": 52}}})


def test_host_samples_become_rates_series_and_alerts():
    clock = Clock(1005.0)
    store = Store(":memory:", clock=clock)
    c = col.Collector({"machine": [{"id": "brain1", "name": "Brain 1", "ssh": "x"}]}, store, clock=clock)
    c.on_host_line("brain1", _sample(1000.0, [0, 0, 0, 100, 0, 0, 0, 0], [1000, 2000], 0))
    c.on_host_line("brain1", _sample(1005.0, [50, 0, 0, 150, 0, 0, 0, 0], [6000, 4500], 2_500_000))
    st = c.state()
    m = st["machines"][0]
    assert m["online"] and m["cpu"] == 50.0 and m["net"] == {"rx": 1000, "tx": 500}
    assert m["mem"]["pct"] == 60.0 and m["fs"][0]["pct"] == 90.0
    assert m["containers"][0]["cores"] == 0.5
    texts = [a["text"] for a in st["alerts"]]
    assert "Brain 1 disk / 90 % full" in texts
    assert any("starai on Brain 1 at 96 % of its memory limit" in t for t in texts)
    assert store.series(["brain1.cpu"], "hour")["series"]["brain1.cpu"][0][1] == 50.0
    clock.t += 31                                                # no data for 31 s: not reporting
    assert any(a["text"].startswith("Brain 1 is not reporting") for a in c.state()["alerts"])


def test_request_timings_get_the_model_name_from_the_router_port():
    clock = Clock(1000.0)
    store = Store(":memory:", clock=clock)
    c = col.Collector({"machine": [{"id": "brain1", "ssh": "x"}]}, store, clock=clock)
    c.star["models"] = col.router_models(MODELS)
    row = json.loads(_sample(1000.0, [0] * 8, [0, 0], 0))
    row["reqs"] = [{"port": "46613", "slot": 1, "task": 9, "prompt_ms": 1500.0, "prompt_tokens": 400,
                    "eval_ms": 10000.0, "eval_tokens": 90, "total_ms": 11500.0, "t": 999.0}]
    c.on_host_line("brain1", json.dumps(row))
    assert store.requests(0)[0]["model"] == "star-fast"
    assert store.series(["llm.brain1.star-fast.tps"], "hour")["series"]["llm.brain1.star-fast.tps"][0][1] == 9.0


def test_backup_alerts():
    now = 1_800_000_000.0
    from datetime import datetime, timezone

    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).isoformat()
    fresh = {"set": "starai", "schedule": "hourly", "last_success_utc": iso(now - 600), "repository_bytes": 5,
             "max_repository_bytes": 100, "last_restore_verification": {"verified_utc": iso(now - 3600)}}
    assert col.backup_alerts(fresh, now) == []
    stale = dict(fresh, last_success_utc=iso(now - 4 * 3600))
    assert col.backup_alerts(stale, now) == [("warn", "backup starai: last success 4 h ago")]
    failed = dict(fresh, last_error={"at": iso(now - 60), "action": "retention", "message": "needs a baseline"})
    assert col.backup_alerts(failed, now) == [("warn", "backup starai: retention failed: needs a baseline")]
    retried = dict(failed, last_retention_utc=iso(now - 30))          # a later retention run succeeded
    assert col.backup_alerts(retried, now) == []
    full = dict(fresh, repository_bytes=90)
    assert col.backup_alerts(full, now) == [("warn", "backup starai: repository at 90 % of its budget")]
    old_check = dict(fresh, last_restore_verification={"verified_utc": iso(now - 3 * 86400)})
    assert col.backup_alerts(old_check, now) == [("warn", "backup starai: restore check older than 2 days")]


def test_pc_push_rates_and_gpu():
    clock = Clock(100.0)
    store = Store(":memory:", clock=clock)
    c = col.Collector({"machine": [{"id": "pc", "name": "PC", "kind": "pc"}]}, store, clock=clock)
    base = {"cpu": [100, 1000], "ncpu": 16, "mem": [32_000, 16_000], "net": [0, 0],
            "fs": [{"mount": "C:", "total": 1000, "used": 400}], "services": {"sunshine": "running"},
            "gpu": {"name": "RTX", "util": 4.0, "mem_used": 1.0, "mem_total": 8.0, "temp": 54.0, "power": 20.0}}
    assert c.on_pc_push({"sample": base}) == []
    clock.t = 110.0
    c.on_pc_push({"sample": dict(base, cpu=[350, 2000], net=[10_000, 5_000])})
    pc = c.state()["machines"][0]
    assert pc["cpu"] == 25.0 and pc["net"] == {"rx": 1000, "tx": 500} and pc["gpu"]["temp"] == 54.0
    assert pc["services"]["sunshine"] == "running" and pc["fs"][0]["pct"] == 40.0
