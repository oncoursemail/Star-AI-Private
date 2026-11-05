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

def test_quality_pilot_reaches_live_qos_only_after_verified_host_admission():
    """Only exact host-catalog, approved quality evidence may choose a worker."""
    from star.stream_quality_route_selector import (
        QualityGatedRouteSelector,
        VerifiedRouteTrialSummary,
    )

    c = HostInferenceCatalog((
        route("baseline", ram=300),
        route("candidate", ram=210, model=SHA_C),
    ))
    suite = "1" * 64

    def evidence(alias, p95, *, correct=30):
        return VerifiedRouteTrialSummary(
            alias, c.profile_for(alias), "speech", "game_recording",
            suite, 30, correct, p95, 2600, 1_800_000_000, True,
        )

    select = QualityGatedRouteSelector(
        catalog=c, summaries=(evidence("baseline", 400),
                              evidence("candidate", 160))
    )
    g, s, qos = host_with_catalog(c)
    common = dict(selector=select, baseline_alias="baseline",
                  workload="game_recording", suite_sha256=suite,
                  now_unix_s=1_800_000_001, max_p95_ms=600,
                  max_total_gpu_mib=6656)
    denied = g.admit_quality_pilot(job("pilot", now=s.now), **common)
    assert not denied.admitted
    assert denied.reason == "quality_pilot_owner_approval_missing"
    assert qos.status()["inflight"] == 0
    wrong_catalog = QualityGatedRouteSelector(
        catalog=HostInferenceCatalog((
            route("baseline", ram=300),
            route("candidate", ram=210, model=SHA_C),
        )),
        summaries=(evidence("baseline", 400), evidence("candidate", 160)),
    )
    assert not g.admit_quality_pilot(
        job("wrong", now=s.now), **{**common, "selector": wrong_catalog},
        pilot_approved=True,
    ).admitted
    assert qos.status()["inflight"] == 0
    success = g.admit_quality_pilot(
        job("approved", now=s.now), **common, pilot_approved=True,
    )
    assert success.admitted and success.lease is not None
    assert success.lease.device == "cpu"
    assert qos.status()["inflight"] == 1
    s.tick(20)
    assert g.acknowledge_worker_stopped(
        success.lease, worker_stopped=True, succeeded=True
    )


def test_quality_pilot_never_admits_a_regressed_worker():
    from star.stream_quality_route_selector import (
        QualityGatedRouteSelector,
        VerifiedRouteTrialSummary,
    )

    c = HostInferenceCatalog((route("baseline"), route("weak", model=SHA_C)))
    summary = lambda alias, p95, correct: VerifiedRouteTrialSummary(
        alias, c.profile_for(alias), "speech", "game_recording",
        "2" * 64, 30, correct, p95, 2700, 1_800_000_000, True
    )
    s = QualityGatedRouteSelector(
        catalog=c, summaries=(summary("baseline", 900, 30),
                              summary("weak", 80, 20))
    )
    governor, host, qos = host_with_catalog(c)
    denied = governor.admit_quality_pilot(
        job("no-route", now=host.now), selector=s, pilot_approved=True,
        baseline_alias="baseline", workload="game_recording",
        suite_sha256="2" * 64, now_unix_s=1_800_000_001,
        max_p95_ms=300, max_total_gpu_mib=6656,
    )
    assert not denied.admitted
    assert denied.reason == "quality_pilot_no_quality_and_resource_qualified_route"
    assert qos.status()["inflight"] == 0
