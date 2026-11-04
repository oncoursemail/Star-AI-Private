"""Model-free integration tests for host-owned model/voice routing.

No live GPU, streamer, game, OBS, microphone or LLM used.
"""
from dataclasses import replace

import pytest

from star.stream_brain_governor import StreamBrainGovernor
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_qos import AdaptiveQoS, InferenceJob
from star.stream_stage import StarStage


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def route(alias="tiny", *, kind="speech", device="cpu", ram=200,
          vram=0, model=SHA_A, runtime=SHA_B, voice=SHA_C):
    return HostModelRoute(alias, kind, device, "pocket-tts", model,
                          runtime, ram, vram, voice)


def job(name="j1", *, kind="speech", device="auto", profile="",
        ram=1, vram=0, now=1000):
    return InferenceJob(name, kind, now, now + 1500,
                        ram, vram, device, route_profile=profile)


def test_profiles_are_stable_but_any_material_model_change_isolated():
    a = route()
    assert a.route_profile == route().route_profile
    assert a.route_profile.startswith("route-")
    variants = [
        replace(a, model_sha256=SHA_B),
        replace(a, runtime_sha256=SHA_C),
        replace(a, voice_sha256=SHA_A),
        replace(a, ram_mib=201),
        replace(a, device="gpu", vram_mib=100),
        replace(a, engine="other"),
    ]
    assert all(x.route_profile != a.route_profile for x in variants)
    assert all(len(x.route_profile) <= 80 for x in variants)


@pytest.mark.parametrize("kwargs", [
    {"alias": "../model"}, {"model": "fake"}, {"runtime": "b" * 63},
    {"voice": "X" * 64}, {"ram": True}, {"vram": float("nan")},
    {"device": "auto"}, {"kind": "unknown"}, {"ram": -1},
])
def test_invalid_host_manifest_fails_closed(kwargs):
    with pytest.raises(ValueError):
        route(**kwargs)


def test_gpu_only_and_cpu_reservations_enforced():
    with pytest.raises(ValueError):
        route(kind="vision")
    with pytest.raises(ValueError):
        route(vram=200)
    assert route(device="gpu", vram=256).device == "gpu"


def test_catalog_immutable_unique_and_no_profile_spoofing():
    catalog = HostInferenceCatalog((route(), route("other", model=SHA_C)))
    assert catalog.route_count == 2
    assert catalog.profile_for("tiny") != catalog.profile_for("other")
    bound = catalog.bind(job(ram=1, vram=1), route_alias="tiny")
    assert bound.ram_mib == 200 and bound.vram_mib == 0
    assert bound.device == "cpu"
    assert bound.route_profile == route().route_profile
    assert bound.job_id == "j1"
    with pytest.raises(ValueError):
        catalog.bind(job(profile="fake"), route_alias="tiny")
    with pytest.raises(ValueError):
        catalog.bind(job(device="gpu"), route_alias="tiny")
    with pytest.raises(ValueError):
        catalog.bind(job(kind="vision", device="gpu"), route_alias="tiny")
    with pytest.raises(ValueError):
        catalog.bind(job(), route_alias="not-deployed")
    with pytest.raises(ValueError):
        HostInferenceCatalog((route(), route()))
    with pytest.raises(ValueError):
        HostInferenceCatalog(())


class Sensors:
    def __init__(self):
        self.now = 100_000.0
        self.cpu = (300, 1000)
        self.gpu = {"vram_total_mib": 8192, "vram_used_mib": 2500}
        self.memory = (32768, 20000)

    def tick(self, ms=16):
        self.now += ms
        return self.now

    def cpu_probe(self):
        return self.cpu

    def gpu_probe(self):
        return self.gpu

    def memory_probe(self):
        return self.memory


def host_with_catalog(catalog, *, enforce=True):
    s = Sensors()
    hardware = RealtimeTelemetryHost(
        gpu_probe=s.gpu_probe, cpu_probe=s.cpu_probe,
        memory_probe=s.memory_probe, clock_ms=lambda: s.now,
    )
    q = AdaptiveQoS(require_route_profiles=True)
    governor = StreamBrainGovernor(
        telemetry=hardware, qos=q, stage=StarStage(clock=lambda: s.now / 1000),
        clock_ms=lambda: s.now, route_catalog=catalog,
        enforce_host_route_binding=enforce,
    )
    governor.enable(owner_approved=True, live=False, game_active=True,
                    private_stream_rehearsal=True)
    assert hardware.refresh_hardware()
    s.cpu = (310, 1100)
    s.tick(100)
    assert hardware.refresh_hardware()
    for _ in range(23):
        assert hardware.presented_frame(s.tick())
    assert hardware.report_audio_backlog(backlog_ms=20, at_ms=s.now)
    s.cpu = (320, 1200)
    assert hardware.refresh_hardware()
    return governor, s, q


def test_trusted_governor_denies_unbound_job_even_if_self_claims_profile():
    g, s, q = host_with_catalog(HostInferenceCatalog((route(),)))
    assert g.status()["host_route_binding_enforced"] is True
    assert g.status()["registered_model_routes"] == 1
    request = job("spoof", profile="route-" + "f"*32, now=s.now)
    denial = g.admit(request)
    assert not denial.admitted
    assert denial.reason == "trusted_host_model_binding_required"
    assert q.status()["inflight"] == 0
    admitted = g.admit_registered(job("real", now=s.now), route_alias="tiny")
    assert admitted.admitted
    assert admitted.lease.device == "cpu"
    assert admitted.predicted_p95_ms is None
    s.tick(90)
    assert g.acknowledge_worker_stopped(admitted.lease, worker_stopped=True, succeeded=True)
    assert q.status()["completed"] == 1


def test_host_reservation_overrides_untrusted_small_budget():
    catalog = HostInferenceCatalog((
        route("too-large", ram=19999),
        route("small", model=SHA_C, ram=200),
    ))
    g, s, q = host_with_catalog(catalog)
    denied = g.admit_registered(job("huge", ram=0, now=s.now),
                                route_alias="too-large")
    assert not denied.admitted
    assert q.status()["inflight"] == 0
    good = g.admit_registered(job("small", ram=19999, now=s.now),
                              route_alias="small")
    assert good.admitted
    assert good.lease.device == "cpu"


def test_catalog_binding_is_opt_in_and_wrong_types_rejected():
    from star.stream_brain_governor import StreamBrainGovernor
    from star.stream_hardware_telemetry import RealtimeTelemetryHost

    s = Sensors()
    telemetry = RealtimeTelemetryHost(
        gpu_probe=s.gpu_probe, cpu_probe=s.cpu_probe,
        memory_probe=s.memory_probe, clock_ms=lambda: s.now,
    )
    base = dict(telemetry=telemetry, qos=AdaptiveQoS(),
                stage=StarStage(clock=lambda: s.now / 1000),
                clock_ms=lambda: s.now)
    with pytest.raises(ValueError):
        StreamBrainGovernor(**base, enforce_host_route_binding=True)
    with pytest.raises(TypeError):
        StreamBrainGovernor(**base, enforce_host_route_binding=1)
    with pytest.raises(TypeError):
        StreamBrainGovernor(**base, route_catalog={"tiny": "fake"})
    legacy = StreamBrainGovernor(**base)
    assert legacy.admit_registered(job(), route_alias="missing").reason == (
        "host_model_catalog_not_configured"
    )
