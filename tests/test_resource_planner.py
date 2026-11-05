"""The live resource planner: admission decisions with fake probes, the lease service, the client's fail-safe and
the wiring of night school, the eval runner, the knowledge re-index, Studio tests and GPU training.

No real server, model, GPU or Studio is used: every snapshot is built by hand, every clock is fake."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from star import agent_resource_planner as arp
from star import planner_client as pc
from star import resource_planner_service as svc
from star import resource_probes as probes

ROOT = Path(__file__).resolve().parents[1]
NOW = float(int(time.time()))


def brain1(*, busy=(), slots=2, deferred=None, lock="", mem=70_000, cpu=0.5, taken=NOW, voice_busy=(),
           helpers_busy=False, tasks=None):
    tasks = tasks or {}
    models = {
        "star-fast": tuple(arp.SlotState(i, i in busy, tasks.get(i, 10 + i)) for i in range(slots)),
        "star-voice": tuple(arp.SlotState(i, i in voice_busy, 20 + i) for i in range(2)),
        "star-embed": (arp.SlotState(0, helpers_busy, 5),),
    }
    return arp.MachineSnapshot("brain1", taken, 48, cpu, 128_000, mem, models=models, deferred=deferred or {},
                               lock_owner=lock)


def pc_snap(*, mem=20_000, owner_busy="", vram_used=500, taken=NOW):
    return arp.MachineSnapshot("pc", taken, 12, 0.2, 32_000, mem, owner_busy=owner_busy, gpu_util=0.05,
                               vram_total_mib=8192, vram_used_mib=vram_used)


def brain2(*, studios=1, mem=5000, taken=NOW):
    return arp.MachineSnapshot("brain2", taken, 6, 0.3, 11_000, mem,
                               studios=tuple({"studio_id": f"studio-{100 + i}", "place_id": arp.STUDIO_TEST_PLACE[1],
                                              "universe_id": arp.STUDIO_TEST_PLACE[0]} for i in range(studios)))


def lease(job_class, holder="h", *, slot=None, machine=None, capability=None, studio_id="", expires=NOW + 100):
    cls = arp.DEFAULT_CLASSES[job_class]
    return arp.Lease(f"L-{job_class}-{holder}", job_class, machine or cls.machine, holder, "job",
                     capability or cls.capability, NOW - 10, expires, cls.memory_mib, cls.cpu_threads, slot=slot,
                     studio_id=studio_id)


def admit(job_class, snap, leases=(), *, chat_ago=None, pending=(), holder="h", **extra):
    last_chat = {} if chat_ago is None else {snap.machine if snap else "brain1": NOW - chat_ago}
    return arp.decide_admit(arp.JobRequest(job_class, holder, "job", **extra), snap, list(leases), now=NOW,
                            last_chat=last_chat, pending=list(pending))


def renew(the_lease, snap, leases=(), *, chat_ago=None, pending=()):
    last_chat = {} if chat_ago is None else {the_lease.machine: NOW - chat_ago}
    return arp.decide_renew(the_lease, snap, [the_lease, *leases], now=NOW, last_chat=last_chat, pending=list(pending))


# --- admission decisions (pure) -------------------------------------------------------------------------------------

def test_night_school_runs_on_an_idle_brain_and_waits_while_chat_is_active():
    assert admit("nightschool", brain1(), slot=1).action == "run"
    waiting = admit("nightschool", brain1(), chat_ago=30, slot=1)
    assert waiting.action == "wait" and "chat" in waiting.reason and waiting.retry_after_s <= 90
    assert admit("nightschool", brain1(), chat_ago=500, slot=1).action == "run"     # quiet again after 120 s


def test_running_night_school_yields_to_chat_but_the_reindex_only_slows_down():
    ns = lease("nightschool", slot=1)
    assert renew(ns, brain1(busy=(1,))).action == "run"
    assert renew(ns, brain1(busy=(1,)), chat_ago=3).action == "yield"
    rx = lease("reindex", capability="cpu")
    slow = renew(rx, brain1(), chat_ago=3)
    assert slow.action == "run" and slow.duty == pytest.approx(0.25)
    assert renew(rx, brain1()).duty == 1.0


def test_one_star_fast_slot_stays_free_for_chat():
    ns = lease("nightschool", slot=1)
    second = admit("eval", brain1(busy=(1,)), [ns])
    assert second.action == "wait" and "star-fast" in second.reason
    with_three = arp.MachineSnapshot("brain1", NOW, 48, 0.5, 128_000, 70_000,
                                     models={"star-fast": tuple(arp.SlotState(i, False) for i in range(3))})
    assert admit("eval", with_three, [ns]).action == "run"          # parallel = 3 would give batch two slots


def test_a_waiting_eval_preempts_night_school():
    ns = lease("nightschool", slot=1)
    pending = [arp.Pending("eval", "brain1", "star-fast", 60, "eval-1", NOW - 5)]
    decision = renew(ns, brain1(busy=(1,)), pending=pending)
    assert decision.action == "yield" and "eval" in decision.reason
    old = [arp.Pending("eval", "brain1", "star-fast", 60, "eval-1", NOW - 120)]
    assert renew(ns, brain1(busy=(1,)), pending=old).action == "run"
    again = admit("nightschool", brain1(), pending=pending, slot=1)     # it cannot grab the slot back first
    assert again.action == "wait" and "eval" in again.reason
    assert admit("eval", brain1(), pending=pending, holder="eval-1").action == "run"


def test_the_quiet_lock_stops_batch_work_but_not_its_own_timing_window():
    locked = brain1(lock="claude-release")
    assert admit("nightschool", locked, slot=1).action == "wait"
    assert renew(lease("nightschool", slot=1), locked).action == "yield"
    assert admit("eval-timing", locked, holder="bench").action == "wait"
    mine = brain1(lock=arp.planner_lock_owner("bench"))
    assert admit("eval-timing", mine, holder="bench").action == "run"


def test_a_timing_window_waits_for_others_to_step_aside_and_blocks_new_batch_work():
    ns = lease("nightschool", slot=1)
    first = admit("eval-timing", brain1(busy=(1,)), [ns], holder="bench")
    assert first.action == "wait" and "step aside" in first.reason
    pending = [arp.Pending("eval-timing", "brain1", "star-fast", 90, "bench", NOW - 2)]
    assert renew(ns, brain1(busy=(1,)), pending=pending).action == "yield"
    assert admit("reindex", brain1(), pending=pending).action == "wait"
    assert admit("eval-timing", brain1(busy=(0,)), holder="bench").action == "wait"   # a request still running
    assert admit("eval-timing", brain1(), holder="bench", chat_ago=10).action == "wait"
    assert admit("eval-timing", brain1(), holder="bench").action == "run"
    window = lease("eval-timing", "bench")
    assert admit("nightschool", brain1(), [window], slot=1).action == "wait"


def test_no_fresh_data_means_fallback_never_a_guess():
    assert admit("nightschool", None, slot=1).action == "fallback"
    stale = brain1(taken=NOW - 60)
    assert admit("nightschool", stale, slot=1).action == "fallback"
    assert renew(lease("nightschool", slot=1), stale).action == "fallback"
    assert admit("no-such-class", brain1()).action == "refuse"


def test_low_ram_on_brain1_stops_new_and_running_batch_work():
    assert admit("reindex", brain1(mem=20_000)).action == "wait"           # below the 24 GiB star-deep headroom
    assert renew(lease("reindex", capability="cpu"), brain1(mem=3000)).action == "yield"


def test_gpu_training_needs_an_idle_owner_free_vram_and_the_ram_floor():
    assert admit("gpu-train", pc_snap()).action == "run"
    gaming = admit("gpu-train", pc_snap(owner_busy="game running: robloxplayerbeta.exe"))
    assert gaming.action == "wait" and "owner" in gaming.reason
    assert admit("gpu-train", pc_snap(vram_used=7000)).action == "wait"
    assert admit("gpu-train", pc_snap(mem=9000)).action == "wait"         # 6 GiB floor + 4 GiB job > 9000 MiB
    assert admit("gpu-train", pc_snap(mem=11_000)).action == "run"
    running = lease("gpu-train")
    assert renew(running, pc_snap(owner_busy="fullscreen: game.exe")).action == "yield"
    assert renew(running, pc_snap(mem=5000)).action == "yield"
    assert renew(running, pc_snap()).action == "run"


def test_studio_tests_run_one_per_studio_and_only_on_the_test_place():
    universe, place = arp.STUDIO_TEST_PLACE
    ok = dict(universe_id=universe, place_id=place, identity_verified=True)
    assert admit("studio-test", brain2(), **ok).action == "run"
    busy = lease("studio-test", studio_id="studio-100")
    second = admit("studio-test", brain2(), [busy], **ok)
    assert second.action == "wait" and "already running" in second.reason
    assert admit("studio-test", brain2(studios=2), [busy], **ok).action == "run"     # the other Studio is free
    observed = admit("studio-test", brain2(), universe_id=universe, place_id=place, identity_verified=False)
    assert observed.action == "run"                 # brain 2's reporter saw the test place in Studio's launch line
    unknown = arp.MachineSnapshot("brain2", NOW, 6, 0.3, 11_000, 5000, studios=({"studio_id": "studio-1"},))
    unverified = admit("studio-test", unknown, universe_id=universe, place_id=place, identity_verified=False)
    assert unverified.action == "wait" and "verified" in unverified.reason
    elsewhere = arp.MachineSnapshot("brain2", NOW, 6, 0.3, 11_000, 5000,
                                    studios=({"studio_id": "studio-1", "universe_id": 5, "place_id": 6},))
    assert admit("studio-test", elsewhere, universe_id=universe, place_id=place, identity_verified=True).action == "wait"
    foreign = arp.MachineSnapshot("brain2", NOW, 6, 0.3, 11_000, 5000,
                                  studios=({"studio_id": "studio-1", "universe_id": 555, "place_id": 666},))
    other = admit("studio-test", foreign, universe_id=555, place_id=666, identity_verified=True)
    assert other.action == "wait" and "STAR Test Place" in other.reason
    blank = arp.MachineSnapshot("brain2", NOW, 6, 0.3, 11_000, 5000,
                                studios=({"studio_id": "studio-1", "universe_id": 0, "place_id": 0},))
    assert admit("studio-test", blank, universe_id=0, place_id=0, identity_verified=True).action == "run"
    assert admit("studio-test", brain2(studios=0), **ok).action == "wait"
    assert admit("studio-test", brain2(mem=1500), **ok).action == "wait"          # brain 2 RAM


def test_chat_signs_tell_leased_batch_work_from_chat():
    ns = lease("nightschool", slot=1)
    ev = lease("eval", "e1")
    assert arp.chat_signs(None, brain1(busy=(1,)), [ns]) == []                 # night school's own pinned slot
    assert arp.chat_signs(None, brain1(busy=(0, 1)), [ns, ev]) == []           # plus one unpinned eval
    assert arp.chat_signs(None, brain1(busy=(0, 1)), [ns])                     # slot 0 busy, nobody leased it
    assert arp.chat_signs(None, brain1(voice_busy=(0,)), [ns])                 # star-voice = plain chat
    assert arp.chat_signs(None, brain1(helpers_busy=True), []) == []           # embeddings are never chat
    assert arp.chat_signs(None, brain1(busy=(0, 1), deferred={"star-fast": 1}), [ns, ev])   # a queued request
    before = brain1(tasks={0: 10})
    after = brain1(tasks={0: 11})
    assert arp.chat_signs(before, after, [])                                   # a short request between looks
    assert arp.chat_signs(before, after, [ev]) == []                           # ambiguous with an unpinned lease


def test_snapshots_from_json_are_validated_and_clamped():
    snap = arp.MachineSnapshot.from_dict({
        "machine": "brain2", "taken_at": NOW, "cpu_threads": 6, "cpu_busy": 7, "mem_available_mib": -5,
        "models": {"star-fast": [{"id": 0, "processing": True, "task": 3}, {"id": "x"}], "bad name!": []},
        "deferred": {"star-fast": 2, "x": -1}, "lock_owner": "evil;rm -rf", "studios": [{"studio_id": "s1", "x": 1}]})
    assert snap.cpu_busy == 1 and snap.mem_available_mib == 0
    assert list(snap.models) == ["star-fast"] and len(snap.models["star-fast"]) == 1
    assert snap.deferred == {"star-fast": 2} and snap.lock_owner == "evilrm-rf" and snap.studios == ({"studio_id": "s1"},)
    assert arp.MachineSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    with pytest.raises(ValueError):
        arp.MachineSnapshot.from_dict({"machine": "", "taken_at": NOW})


# --- the lease service ---------------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


def planner(tmp_path, clock=None):
    clock = clock or Clock()
    return svc.Planner(lock_dir=str(tmp_path / "lock"), clock=clock, log=lambda m: None), clock


def snap_dict(snap, clock):
    data = snap.to_dict()
    data["taken_at"] = clock()
    return data


def test_service_admits_renews_and_releases(tmp_path):
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(), clock))
    first = p.admit({"job_class": "nightschool", "holder": "ns", "job_id": "practice", "slot": 1})
    assert first["action"] == "run" and first["lease_id"]
    again = p.admit({"job_class": "nightschool", "holder": "ns", "job_id": "practice", "slot": 1})
    assert again["lease_id"] == first["lease_id"]                               # asking twice keeps one lease
    p.observe(snap_dict(brain1(busy=(1,)), clock))                               # its own slot: no chat
    assert p.renew({"lease_id": first["lease_id"]})["action"] == "run"
    clock.t += 2
    p.observe(snap_dict(brain1(busy=(0, 1)), clock))                             # slot 0 busy without a lease
    assert p.status()["machines"]["brain1"]["chat_active"]
    assert p.renew({"lease_id": first["lease_id"]})["action"] == "yield"
    assert p.renew({"lease_id": first["lease_id"]})["action"] == "refuse"       # a yield ends the lease
    assert p.status()["leases"] == []


def test_service_expires_leases_and_old_reports_never_replace_new_ones(tmp_path):
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(), clock))
    grant = p.admit({"job_class": "reindex", "holder": "kb", "job_id": "embed"})
    assert grant["action"] == "run"
    clock.t += 400
    p.observe(snap_dict(brain1(), clock))
    assert p.status()["leases"] == []
    late = brain1(taken=NOW).to_dict()
    p.observe(late)
    assert p.snapshots["brain1"].taken_at == clock.t


def test_timing_window_sets_and_removes_only_its_own_quiet_lock(tmp_path):
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(), clock))
    grant = p.admit({"job_class": "eval-timing", "holder": "bench", "job_id": "window", "ttl_s": 300})
    assert grant["action"] == "run"
    owner = (tmp_path / "lock" / "owner").read_text().split()[0]
    assert owner == "planner-bench" and probes.lock_owner(str(tmp_path / "lock"), clock=clock) == "planner-bench"
    p.observe(snap_dict(brain1(lock="planner-bench"), clock))
    assert p.renew({"lease_id": grant["lease_id"]})["action"] == "run"
    assert p.admit({"job_class": "nightschool", "holder": "ns", "job_id": "practice", "slot": 1})["action"] == "wait"
    p.release({"lease_id": grant["lease_id"]})
    assert not (tmp_path / "lock").exists()


def test_timing_window_never_takes_over_someone_elses_lock(tmp_path):
    p, clock = planner(tmp_path)
    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "owner").write_text("claude-release 2026-10-13T19:00:00Z\n")
    p.observe(snap_dict(brain1(lock="claude-release"), clock))
    grant = p.admit({"job_class": "eval-timing", "holder": "bench", "job_id": "window"})
    assert grant["action"] == "wait" and "claude-release" in grant["reason"]
    assert (lock / "owner").read_text().startswith("claude-release")
    p.observe(snap_dict(brain1(lock="claude-release"), clock))      # the expiry sweep leaves a foreign lock alone
    assert lock.exists()


def test_planner_lock_without_a_window_is_removed_after_a_minute(tmp_path):
    p, clock = planner(tmp_path)
    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "owner").write_text("planner-gone 2026-10-13T19:00:00Z\n")
    import os
    os.utime(lock / "owner", (clock.t - 120, clock.t - 120))
    p.observe(snap_dict(brain1(), clock))
    assert not lock.exists()


def test_status_reports_queue_counters_and_averages(tmp_path):
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(cpu=0.4), clock))
    p.observe(snap_dict(pc_snap(owner_busy="game running: cs2.exe"), clock))
    p.admit({"job_class": "nightschool", "holder": "ns", "job_id": "practice", "slot": 1})
    p.admit({"job_class": "eval", "holder": "eval-1", "job_id": "A-1"})
    p.admit({"job_class": "gpu-train", "holder": "pc-training", "job_id": "embed"})
    status = p.status()
    assert [l["job_class"] for l in status["leases"]] == ["nightschool"]
    assert {w["job_class"] for w in status["waiting"]} == {"eval", "gpu-train"}
    assert status["counters"]["admitted"] == 1 and status["counters"]["waited"] == 2
    text = pc.format_status(status)
    assert "brain1" in text and "OWNER BUSY" in text and "queue: 2" in text and "nightschool" in text


# --- HTTP + client --------------------------------------------------------------------------------------------------

@pytest.fixture
def live_service(tmp_path):
    from http.server import ThreadingHTTPServer
    p, clock = planner(tmp_path, clock=time.time)
    server = ThreadingHTTPServer(("127.0.0.1", 0), svc.make_handler(p, "test-key", "report-token"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield p, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_http_round_trip_with_key_and_status_from_loopback(live_service):
    p, url = live_service
    p.observe(brain1(taken=time.time()).to_dict())
    client = pc.PlannerClient(url, key="test-key")
    grant = client.admit("nightschool", "ns", "practice", slot=1)
    assert grant.action == "run" and grant.planned
    assert client.renew(grant).action == "run"
    status = client.status()
    assert status["leases"][0]["holder"] == "ns"
    client.release(grant)
    assert p.status()["leases"] == []
    wrong = pc.PlannerClient(url, key="nope")
    assert wrong.admit("nightschool", "ns", "practice").action == "fallback"   # 401 -> the old rules apply
    client.interactive("brain1", "desktop")
    assert p.status()["machines"]["brain1"]["chat_active"]


def test_report_token_only_reports_and_nobody_overwrites_the_planners_own_machine(live_service):
    import urllib.error
    import urllib.request
    p, url = live_service

    def post(path, body, token):
        request = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": "Bearer " + token,
                                                  "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as reply:
                return reply.status
        except urllib.error.HTTPError as exc:
            return exc.code
    report = brain2(taken=time.time()).to_dict()
    assert post("/v1/report", {"snapshot": report}, "report-token") == 200
    assert "brain2" in p.snapshots
    assert post("/v1/admit", {"job_class": "studio-test", "holder": "x", "job_id": "y"}, "report-token") == 401
    fake_brain1 = brain1(taken=time.time() + 5).to_dict()
    assert post("/v1/report", {"snapshot": fake_brain1}, "test-key") == 400
    assert post("/v1/admit", {"job_class": "eval", "holder": "x", "job_id": "y", "snapshot": fake_brain1},
                "test-key") == 400


def test_client_without_a_planner_always_falls_back_quickly():
    off = pc.PlannerClient("")
    assert not off.enabled and off.admit("eval", "e", "t").action == "fallback"
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        raise ConnectionRefusedError("refused at a private address")
    dead = pc.PlannerClient("http://planner.invalid:8098", key="k", opener=opener, down_for=30)
    first = dead.admit("nightschool", "ns", "practice")
    second = dead.admit("nightschool", "ns", "practice")
    assert first.action == second.action == "fallback" and first.go
    assert len(calls) == 1                                 # stays quiet for down_for seconds
    assert dead.last_error == "ConnectionRefusedError" and "private address" not in first.reason


def test_client_reads_the_url_from_env_and_off_disables(monkeypatch, tmp_path):
    monkeypatch.setenv("STAR_PLANNER_URL", "http://p:8098")
    assert pc.configured_url() == "http://p:8098"
    monkeypatch.setenv("STAR_PLANNER_URL", "off")
    assert pc.configured_url() == ""


class FakeClient:
    """A scripted planner client: `answers` is a list of actions handed out in order (last one repeats)."""

    def __init__(self, admits=("run",), renews=("run",), duty=1.0):
        self.admits, self.renews, self.duty = list(admits), list(renews), duty
        self.calls = []
        self.enabled = True

    def _next(self, queue):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def admit(self, job_class, holder, job_id, **extra):
        self.calls.append(("admit", job_class, holder, job_id, extra))
        action = self._next(self.admits)
        return pc.Grant(action, f"scripted {action}", "lease-1" if action == "run" else "", self.duty, 1.0, job_class)

    def renew(self, grant):
        self.calls.append(("renew", grant.lease_id))
        action = self._next(self.renews)
        return pc.Grant(action, f"scripted {action}", grant.lease_id if action in ("run", "fallback") else "",
                        self.duty, 1.0, grant.job_class)

    def release(self, grant):
        self.calls.append(("release", grant.lease_id if grant else ""))
        if grant:
            grant.lease_id = ""

    def wait_for(self, job_class, holder, job_id, *, stop=lambda: False, max_wait=None, sleep=time.sleep, log=None,
                 **extra):
        return pc.PlannerClient.wait_for(self, job_class, holder, job_id, stop=stop, max_wait=max_wait, sleep=sleep,
                                         log=log, **extra)


def test_wait_for_and_pacer_follow_the_planner():
    client = FakeClient(admits=("wait", "wait", "run"), renews=("run", "yield"), duty=0.25)
    slept = []
    grant = client.wait_for("reindex", "kb", "embed", sleep=slept.append)
    assert grant.action == "run" and len(slept) == 2
    pacer = pc.Pacer(client, "reindex", "kb", "embed", sleep=slept.append)
    pacer.grant = grant
    slept.clear()
    assert pacer.step(2.0) is True and slept == [pytest.approx(6.0)]      # duty 0.25: 2 s work, 6 s rest
    assert pacer.step(2.0) is False                                       # yield
    pacer.close()


# --- probes -------------------------------------------------------------------------------------------------------------

def test_probe_parsers(tmp_path):
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3 4\n")
    busy, total = probes.proc_cpu_times(str(stat))
    assert (busy, total) == (200, 1000)
    assert probes.cpu_busy_share((200, 1000), (700, 2000)) == pytest.approx(0.5)
    mem = tmp_path / "meminfo"
    mem.write_text("MemTotal:       131072000 kB\nMemFree: 1 kB\nMemAvailable:   75000000 kB\n")
    assert probes.proc_meminfo(str(mem)) == (128000, 73242)
    assert probes.parse_nvidia_smi("37, 8192, 1500\n") == {"gpu_util": 0.37, "vram_total_mib": 8192,
                                                           "vram_used_mib": 1500}
    metrics = "# HELP x\nllamacpp:requests_processing 2\nllamacpp:requests_deferred 3\n"
    assert probes.parse_metric(metrics, "llamacpp:requests_deferred") == 3


def test_lock_owner_follows_the_15_minute_rule(tmp_path):
    lock = tmp_path / "lock"
    assert probes.lock_owner(str(lock)) == ""
    lock.mkdir()
    (lock / "owner").write_text("claude-release 2026-10-13T19:00:00Z\n")
    assert probes.lock_owner(str(lock)) == "claude-release"
    assert probes.lock_owner(str(lock), clock=lambda: time.time() + 901) == ""


def test_brain_probe_never_asks_an_unloaded_model_for_its_slots():
    asked = []

    def fetch(path):
        asked.append(path)
        if path == "/v1/models":
            return json.dumps({"data": [
                {"id": "star-fast", "status": {"value": "loaded"}},
                {"id": "star-deep", "status": {"value": "unloaded"}},
                {"id": "star-embed", "status": {"value": "loaded"}}]}).encode()
        if path.startswith("/slots?model=star-fast"):
            return json.dumps([{"id": 0, "is_processing": True, "id_task": 7}, {"id": 1, "is_processing": False}]).encode()
        if path.startswith("/slots?model=star-embed"):
            raise OSError("no slots")
        if path.startswith("/metrics?model=star-fast"):
            return b"llamacpp:requests_deferred 1\n"
        raise OSError("off")
    models, queued = probes.BrainProbe(fetch=fetch).snapshot(skip=frozenset())
    assert not any("star-deep" in p for p in asked)
    asked.clear()
    probes.BrainProbe(fetch=fetch).snapshot()
    assert not any("star-embed" in p for p in asked)              # helpers are not asked by default
    assert models == {"star-fast": [{"id": 0, "processing": True, "task": 7}, {"id": 1, "processing": False, "task": -1}]}
    assert queued == {"star-fast": 1}


def test_owner_busy_signals():
    assert probes.owner_busy_reason(processes={"robloxplayerbeta.exe"}, fullscreen="", gpu=None,
                                    compute_pids=None).startswith("game running")
    assert probes.owner_busy_reason(processes=set(), fullscreen="Game.exe", gpu=None, compute_pids=None) == \
        "fullscreen: Game.exe"
    assert probes.owner_busy_reason(processes=set(), fullscreen="", gpu={"gpu_util": 0.9},
                                    compute_pids=set()).startswith("graphics load")
    assert probes.owner_busy_reason(processes=set(), fullscreen="", gpu={"gpu_util": 0.9},
                                    compute_pids={1234}) == ""                 # STAR's own training explains it
    assert probes.owner_busy_reason(processes=set(), fullscreen="", gpu={"gpu_util": 0.05},
                                    compute_pids=set()) == ""


# --- wiring: night school ----------------------------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "server" / "night_school"))
sys.path.insert(0, str(ROOT / "tests"))
from nightschool.config import Settings as NsSettings          # noqa: E402
from nightschool.idle import IdleGate, PlannedGate, make_planner   # noqa: E402


class FakeWatch:
    def __init__(self):
        self.table = {("star-fast", 0): (False, 1), ("star-fast", 1): (False, 1)}

    def snapshot(self):
        return dict(self.table)


def ns_settings(tmp_path, **extra):
    s = NsSettings(home=tmp_path, idle_s=600, poll_s=1, lock_dir=str(tmp_path / "lock"), **extra)
    s.ensure_dirs()
    return s


def test_planned_gate_starts_without_the_ten_minute_wait_and_yields_on_request(tmp_path):
    client = FakeClient(admits=("run",), renews=("run", "yield"))
    gate = PlannedGate(ns_settings(tmp_path), FakeWatch(), planner=client, log=lambda m: None, sleep=lambda s: None)
    assert gate.look() == "" and gate.mode == "planner"
    assert client.calls[0][:4] == ("admit", "nightschool", "nightschool", "practice")
    assert client.calls[0][4] == {"slot": 1}
    assert gate.intruder(1) == ""
    reason = gate.intruder(1)
    assert reason.startswith("planner:") and gate.grant is None


def test_planned_gate_falls_back_to_the_idle_gate_when_the_planner_is_out(tmp_path):
    client = FakeClient(admits=("fallback",))
    watch = FakeWatch()
    gate = PlannedGate(ns_settings(tmp_path), watch, planner=client, log=lambda m: None, sleep=lambda s: None)
    assert "quiet" in gate.look()                       # old rule: 600 s of quiet first
    watch.table[("star-fast", 0)] = (True, 2)
    assert gate.look() == "brain busy, waiting" and gate.mode == "idle-gate"


def test_planned_gate_checks_hold_and_lock_before_asking(tmp_path):
    settings = ns_settings(tmp_path)
    client = FakeClient()
    gate = PlannedGate(settings, FakeWatch(), planner=client, log=lambda m: None, sleep=lambda s: None)
    settings.hold_file.write_text("")
    assert gate.look() == "HOLD file present, paused" and client.calls == []
    settings.hold_file.unlink()
    (tmp_path / "lock").mkdir()
    assert gate.look() == "quiet lock held, waiting" and client.calls == []


def test_planned_gate_waits_while_the_planner_says_wait(tmp_path):
    client = FakeClient(admits=("wait", "run"))
    slept = []
    gate = PlannedGate(ns_settings(tmp_path), FakeWatch(), planner=client, log=lambda m: None, sleep=slept.append)
    assert gate.wait() is True and slept == [1]


def test_night_school_planner_switch(tmp_path, monkeypatch):
    assert make_planner(SimpleNamespace(planner_url="off"), "k") is None
    client = make_planner(SimpleNamespace(planner_url="http://127.0.0.1:8098"), "k")
    assert client is not None and client.url == "http://127.0.0.1:8098"
    no_planner = PlannedGate(ns_settings(tmp_path), FakeWatch(), planner=None, log=lambda m: None)
    assert "quiet" in no_planner.look()                 # exactly IdleGate
    assert isinstance(no_planner, IdleGate)


# --- wiring: eval runner --------------------------------------------------------------------------------------------

def test_eval_runner_takes_a_lease_per_task_and_repeats_a_yielded_task(tmp_path):
    from star import eval_checks as ec
    from star import eval_runner as er
    tasks = [{"id": t, "category": "c", "goal": "g", "required_evidence": ["e"], "pass_conditions": ["p"],
              "run_mode": "automated", "prompt": "Write " + t, "auto": {"code": False, "compile": False}}
             for t in ("A-1", "A-2")]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    suite = er.load_suite(path)
    client = FakeClient(admits=("run",), renews=("yield", "run"))
    asked = []

    def ask(task, cancel=None):
        asked.append(task["id"])
        if len(asked) == 1:                      # the first request runs until the planner wants the slot back
            for _ in range(200):
                if cancel.is_set():
                    raise RuntimeError("cancelled")
                time.sleep(0.01)
        return er.Asked("answer", [], 0.1)

    def scorer(task, answer):
        score = ec.TaskScore()
        score.checks.append(ec.Check("x", True, ""))
        return score
    result = er.run_suite(suite, out=tmp_path / "out.json", ask=ask, scorer=scorer, run_info={"fingerprint": "f"},
                          log=lambda m: None, planner=client, planner_holder="eval-test", watch_interval=0.02,
                          sleep=lambda s: None)
    assert result["complete"] and asked == ["A-1", "A-1", "A-2"]
    admits = [c for c in client.calls if c[0] == "admit"]
    assert [c[3] for c in admits] == ["A-1", "A-1", "A-2"] and admits[0][1:3] == ("eval", "eval-test")
    assert sum(1 for c in client.calls if c[0] == "release") >= 3


def test_eval_runner_without_a_planner_is_unchanged(tmp_path):
    from star import eval_runner as er
    import inspect
    assert inspect.signature(er.run_suite).parameters["planner"].default is None


# --- wiring: Studio tests on brain 2 ---------------------------------------------------------------------------------

class FakeConnector:
    def __init__(self, place=(arp.STUDIO_TEST_PLACE[1], arp.STUDIO_TEST_PLACE[0])):
        self.place = place
        self.calls = []

    async def call_tool(self, name, arguments=None):
        from star import studio_remote as sr
        self.calls.append(name)
        if name == "execute_luau":
            # Return only an answer to this exact nonce-bearing identity query.
            # A static pin receipt must NOT pass the production verifier.
            import re
            code = (arguments or {}).get("code", "")
            suffix = code.removeprefix(sr.PIN_QUESTION) if code.startswith(sr.PIN_QUESTION) else ""
            challenge = re.fullmatch(r' .. " ([0-9a-f]{32})"', suffix)
            text = (f"{sr.PIN_OK} {self.place[0]} {self.place[1]} {challenge.group(1)}"
                    if challenge else "invalid challenge request")
        else:
            text = "ok"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], isError=False,
                               model_dump=lambda **_: {"content": [{"type": "text", "text": text}]})


def test_a_playtest_holds_a_studio_lease_on_brain2_and_waits_when_the_studio_is_busy():
    from star import studio_remote as sr
    from star import studio_loop as sl
    client = FakeClient(admits=("run",))
    pinned = sr.PinnedSession(FakeConnector(), planner=client)
    start = asyncio.run(pinned.call_tool("start_stop_play", {"studio_id": "S", "is_start": True}))
    assert not sl.result_failed(start)
    admit_call = [c for c in client.calls if c[0] == "admit"][0]
    assert admit_call[1] == "studio-test" and admit_call[4] == {
        "universe_id": arp.STUDIO_TEST_PLACE[0], "place_id": arp.STUDIO_TEST_PLACE[1], "identity_verified": True}
    asyncio.run(pinned.call_tool("start_stop_play", {"studio_id": "S", "is_start": False}))
    assert ("release", "lease-1") in client.calls
    busy = sr.PinnedSession(FakeConnector(), planner=FakeClient(admits=("wait",)))
    refused = asyncio.run(busy.call_tool("start_stop_play", {"studio_id": "S", "is_start": True}))
    assert sl.result_failed(refused) and "busy" in sl.result_text(refused)
    assert "start_stop_play" not in busy._session.calls
    held = pc.Grant("run", "", "lab-lease", job_class="studio-test")
    pc._HELD.setdefault("studio-test", set()).add(held.lease_id)       # a Studio Lab run holds the Studio already
    try:
        inner = FakeClient(admits=("wait",))
        nested = sr.PinnedSession(FakeConnector(), planner=inner)
        assert not sl.result_failed(asyncio.run(nested.call_tool("start_stop_play", {"studio_id": "S", "is_start": True})))
        assert not [c for c in inner.calls if c[0] == "admit"]
    finally:
        pc._HELD["studio-test"].discard(held.lease_id)
    unplanned = sr.PinnedSession(FakeConnector())
    assert not sl.result_failed(asyncio.run(unplanned.call_tool("start_stop_play", {"studio_id": "S", "is_start": True})))


# --- wiring: GPU training on the PC ---------------------------------------------------------------------------------

def test_training_gate_respects_the_floor_and_the_planner():
    sys.path.insert(0, str(ROOT / "server" / "training" / "gpu"))
    pytest.importorskip("numpy")
    import common
    free = {"gb": 20.0}
    client = FakeClient(admits=("wait", "run"), renews=("run", "yield"))
    gate = common.TrainingGate("embed", client=client, log=lambda m: None, renew_every=0, free_gb=lambda: free["gb"])
    client.wait_for = lambda *a, **k: pc.PlannerClient.wait_for(client, *a, sleep=lambda s: None, **{
        x: y for x, y in k.items() if x != "sleep"})
    assert gate.start() is True
    assert gate.stop_reason() == ""
    assert gate.stop_reason().startswith("planner:")
    free["gb"] = 5.0
    assert gate.stop_reason().startswith("free RAM")
    assert gate.start() is False
    nobody = common.TrainingGate("embed", client=None, log=lambda m: None, free_gb=lambda: 20.0)
    nobody.client = None
    assert nobody.start() is True and nobody.stop_reason() == ""


# --- wiring: knowledge re-index ---------------------------------------------------------------------------------------

def _starkb():
    """starkb with the desktop's small dependencies (numpy is only needed at import time by modules not used here)."""
    from types import ModuleType
    sys.path.insert(0, str(ROOT / "server" / "knowledge"))
    sys.path.insert(0, str(ROOT / "server" / "knowledge" / "tests"))
    try:
        import numpy  # noqa: F401
        shim = False
    except ModuleNotFoundError:
        sys.modules["numpy"] = ModuleType("numpy")
        shim = True
    try:
        from starkb import embed, quiet
        from test_jobs_lock import minimal_index
    finally:
        if shim:
            del sys.modules["numpy"]
    return embed, quiet, minimal_index


def test_knowledge_pacer_is_off_unless_configured(monkeypatch):
    _embed, quiet, _ = _starkb()
    monkeypatch.setenv("STAR_PLANNER_URL", "off")
    assert quiet.planner_pacer("embed") is None
    monkeypatch.delenv("STAR_PLANNER_URL")
    assert quiet.planner_pacer("embed") is None
    monkeypatch.setenv("STAR_PLANNER_URL", "http://127.0.0.1:9")
    pacer = quiet.planner_pacer("embed")
    assert pacer is not None and pacer.job_class == "reindex"


def test_knowledge_embedding_is_paced_and_paused_by_the_planner(tmp_path, monkeypatch):
    embed, _quiet, minimal_index = _starkb()
    index = tmp_path / "index.sqlite3"
    minimal_index(index)

    class Brain:
        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts], len(texts)

    class FakePacer:
        def __init__(self):
            self.events = []

        def wait(self, max_wait=None):
            self.events.append("wait")

        def step(self, seconds, base_duty=1.0):
            self.events.append(("step", base_duty))
            return len([e for e in self.events if isinstance(e, tuple)]) != 1     # the first step: chat, pause

        def close(self):
            self.events.append("close")
    pacer = FakePacer()
    monkeypatch.setattr(embed, "Brain", Brain)
    monkeypatch.setattr(embed, "planner_pacer", lambda job, **k: pacer)
    result = embed.run(index, batch=1, duty=0.5, log=lambda m: None, stop=lambda: False)
    assert result["embedded_now"] == 2
    assert pacer.events == ["wait", ("step", 0.5), "wait", ("step", 0.5), "close"]


# --- night school parallel lanes ------------------------------------------------------------------------------------

def test_parallel_lanes_overlap_model_calls_and_keep_state_consistent(tmp_path):
    from test_night_school import Script, engine_for
    script = Script()
    active, peak, lock = [0], [0], threading.Lock()
    original = script.solve

    def slow_solve(task, lessons):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        try:
            return original(task, lessons)
        finally:
            with lock:
                active[0] -= 1
    ids = ["E-1", "E-2", "E-3", "H-1", "X-1", "E-4", "V-1", "V-2"]
    settings, store, engine = engine_for(tmp_path, ids, script, batch=6)
    engine._solve = slow_solve
    lane_log = []

    def lane(k):
        def run(work):
            lane_log.append(k)
            work()
            return True
        return run
    outcomes = engine.run_batch(lanes=[lane(0), lane(1)])
    assert sum(outcomes.values()) == 6 and peak[0] == 2                 # two answers in flight at once
    tried = [t for t, seen in store.state["tasks"].items() if seen["tries"]]
    assert sorted(tried) == ["E-1", "E-2", "E-3", "E-4", "H-1", "X-1"]  # six distinct tasks, none twice
    assert set(lane_log) == {0, 1}
    c = store.state["counters"]
    assert c["tasks_tried"] == 6 and c["passed_first"] == 4 and engine._in_flight == set() and not engine._parallel


def test_a_lane_that_yields_ends_the_batch_without_losing_counts(tmp_path):
    from nightschool.engine import Yielded as NsYielded
    from test_night_school import Script, engine_for
    script = Script()
    script.interrupt_on = "E-2"
    settings, store, engine = engine_for(tmp_path, ["E-1", "E-2", "E-3", "V-1"], script, batch=3)
    with pytest.raises(NsYielded):
        engine.run_batch(lanes=[lambda w: (w(), True)[1], lambda w: (w(), True)[1]])
    assert "E-2" not in [t for t, s in store.state["tasks"].items() if s.get("tries")]
    assert engine._in_flight == set() and not engine._parallel


def test_extra_lanes_need_the_planner(tmp_path):
    settings = ns_settings(tmp_path)
    off = PlannedGate(settings, FakeWatch(), planner=None, extra_lane=True, slot=2, log=lambda m: None)
    assert "planner" in off.look()
    out = PlannedGate(settings, FakeWatch(), planner=FakeClient(admits=("fallback",)), extra_lane=True, slot=2,
                      log=lambda m: None)
    assert "planner" in out.look()
    client = FakeClient(admits=("run",), renews=("fallback",))
    lane = PlannedGate(settings, FakeWatch(), planner=client, holder="nightschool-1", extra_lane=True, slot=2,
                       log=lambda m: None)
    assert lane.look() == "" and client.calls[0][2:] == ("nightschool-1", "practice", {"slot": 2})
    assert lane.intruder(2).startswith("planner gone")


def test_planner_gives_night_school_two_lanes_only_with_three_slots():
    three = arp.MachineSnapshot("brain1", NOW, 48, 0.5, 128_000, 70_000,
                                models={"star-fast": tuple(arp.SlotState(i, False) for i in range(3))})
    lane1 = lease("nightschool", "nightschool", slot=1)
    assert admit("nightschool", three, [lane1], holder="nightschool-1", slot=2).action == "run"
    lane2 = lease("nightschool", "nightschool-1", slot=2)
    assert admit("nightschool", three, [lane1, lane2], holder="nightschool-2", slot=3).action == "wait"
    assert admit("nightschool", brain1(), [lane1], holder="nightschool-1", slot=2).action == "wait"   # 2 slots


def test_lane_answers_run_in_a_child_process_that_a_yield_kills(tmp_path, monkeypatch):
    import threading as th
    from nightschool import real
    from nightschool.engine import Yielded as NsYielded

    class Child:
        killed = False

        def __init__(self, argv, **kw):
            self.argv, self.env, self.returncode = argv, kw.get("env"), 0
            self._done = th.Event()

        def communicate(self, data):
            request = json.loads(data)
            if request["task"]["id"] == "slow":
                self._done.wait(5)
                return b"", b""
            return (json.dumps({"passed": True, "reasons": [], "answer": "x", "seconds": 1.0,
                                "slot_seen": request["slot"]}) + "\n").encode(), b""

        def kill(self):
            Child.killed = True
            self._done.set()
    monkeypatch.setattr(real.subprocess, "Popen", Child)

    class Gate:
        def __init__(self, reasons):
            self.reasons = list(reasons)

        def wait(self, stop):
            return True

        def intruder(self, slot):
            return self.reasons.pop(0) if self.reasons else ""

        def own_work_done(self):
            pass
    model = object.__new__(real.RealModel)
    model.settings = SimpleNamespace(watch_s=0.01, slot=1)
    model.stop, model._wait, model.prelude = (lambda: False), True, ""
    model._lane = th.local()
    model.gates, model.lane_slots, model.child_env = [Gate([])], [1], {"X": "1"}
    model.add_lane(Gate([]), 2)
    model._lane.index = 1
    result = model.solve({"id": "t1", "prompt": "p"}, [])
    assert result.passed and result.answer == "x"
    model.gates[1] = Gate(["planner: chat is active"])
    with pytest.raises(NsYielded):
        model.solve({"id": "slow", "prompt": "p"}, [])
    assert Child.killed


# --- brain 2 as two pools ---------------------------------------------------------------------------------------------

def test_cpu_work_goes_to_brain2_first_and_never_eats_studio_headroom():
    snaps = {"brain1": brain1(), "brain2": brain2(mem=4600)}
    req = arp.JobRequest("cpu-work", "eval-check", "luau-check")
    decision, machine = arp.decide_admit_any(req, snaps, [], now=NOW, last_chat={})
    assert decision.action == "run" and machine == "brain2"
    tight = {"brain1": brain1(), "brain2": brain2(mem=3500)}     # 3500 - 1024 base - 2560 Studio play reserve < 512
    decision, machine = arp.decide_admit_any(req, tight, [], now=NOW, last_chat={})
    assert decision.action == "run" and machine == "brain1"
    busy1 = {"brain1": brain1(cpu=0.99), "brain2": brain2(mem=3500)}
    decision, machine = arp.decide_admit_any(req, busy1, [], now=NOW, last_chat={})
    assert decision.action == "wait"
    assert arp.decide_admit_any(req, {}, [], now=NOW, last_chat={})[0].action == "fallback"


def test_service_places_cpu_work_and_renews_on_that_machine(tmp_path):
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(), clock))
    p.observe(snap_dict(brain2(mem=4600), clock))
    grant = p.admit({"job_class": "cpu-work", "holder": "eval-check", "job_id": "luau-check"})
    assert grant["action"] == "run" and grant["machine"] == "brain2"
    assert p.renew({"lease_id": grant["lease_id"]})["action"] == "run"
    assert p.status()["leases"][0]["machine"] == "brain2"


def test_planned_sandbox_uses_the_machine_the_planner_picked():
    from star import eval_runner as er

    class Box:
        def __init__(self, name):
            self.name, self.limits = name, {"wall_s": 15}

        def run(self, source):
            return self.name

        def lock_present(self):
            return False

    class Picker(FakeClient):
        def admit(self, job_class, holder, job_id, **extra):
            grant = super().admit(job_class, holder, job_id, **extra)
            grant.machine = "brain2" if grant.planned else ""
            return grant
    box = er.PlannedSandbox({"brain2": Box("b2"), "brain1": Box("b1")}, Picker(), Box("default"))
    assert box.run("print(1)") == "b2" and box.placed == {"brain2": 1}
    out = er.PlannedSandbox({"brain2": Box("b2")}, FakeClient(admits=("fallback",)), Box("default"))
    assert out.run("print(1)") == "default" and out.lock_present() is False


def test_embedding_job_uses_the_brain2_worker_and_falls_back_to_the_brain(monkeypatch):
    embed, _quiet, _ = _starkb()
    made = []

    class Brain:
        def __init__(self, url="brain", key_file="", retries=3, timeout=300.0):
            self.url = url
            made.append(url)

        def embed(self, texts):
            if self.url == "http://worker:8099" and fail["on"]:
                raise RuntimeError("down")
            return [[1.0]], 1
    fail = {"on": False}
    monkeypatch.setattr(embed, "Brain", Brain)
    monkeypatch.setenv("STAR_KB_EMBED_URL", "http://worker:8099")
    brain, where = embed.embedding_brain(log=lambda m: None)
    assert where == "worker" and brain.url == "http://worker:8099"
    fail["on"] = True
    brain, where = embed.embedding_brain(log=lambda m: None)
    assert where == "brain" and brain.url == "brain"


def test_run_held_stops_on_yield_and_resumes(tmp_path):
    client = FakeClient(admits=("run",), renews=("run", "yield", "run"))
    started = []

    class Proc:
        def __init__(self, cmd):
            started.append(cmd)
            self.code, self.polls = None, 0

        def poll(self):
            self.polls += 1
            if len(started) == 2 and self.polls > 2:      # the resumed run finishes by itself
                self.code = 0
            return self.code

        def terminate(self):
            self.code = -15

        def wait(self):
            return self.code if self.code is not None else 0
    t = [0.0]

    def sleep(s):
        t[0] += s
    stop = tmp_path / "STOP"
    code = pc.run_held(client, "gpu-train", "pc-practice", "practice", ["train"], stop_file=str(stop), restart=True,
                       renew_every=2.0, log=lambda m: None, popen=Proc, sleep=sleep, clock=lambda: t[0])
    assert code == 0 and len(started) == 2
    assert not stop.exists()                                   # removed again before the resumed run
    assert sum(1 for c in client.calls if c[0] == "release") == 2


def test_confined_adds_ram_cap_and_numa_pinning_when_the_tools_exist(monkeypatch):
    monkeypatch.setattr(pc.os, "name", "posix")
    cmd = pc.confined(["job"], memory_max="2G", numa_node=3, which=lambda name: "/usr/bin/" + name)
    assert cmd[:6] == ["systemd-run", "--scope", "--quiet", "-p", "MemoryMax=2G", "-p"]
    assert cmd[-4:] == ["numactl", "--cpunodebind=3", "--membind=3", "job"]
    assert pc.confined(["job"], memory_max="2G", numa_node=3, which=lambda name: None) == ["job"]


def test_studio_processes_counts_studio_itself_not_its_webview_helpers(tmp_path):
    def proc(pid, *argv):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    proc(10, "/home/star/v/RobloxStudioBeta.exe", "roblox-studio:1+placeId:128074805767678+universeId:10770312935")
    proc(11, r"C:\EdgeWebView\msedgewebview2.exe", "--webview-exe-name=RobloxStudioBeta.exe")
    proc(12, r"Z:\home\v\RobloxCrashHandler.exe", "--no-rate-limit")
    proc(13, "vinegar", "roblox-studio:1+placeId:1")
    found = probes.studio_processes(str(tmp_path))
    assert found == [{"studio_id": "studio-10", "place_id": 128074805767678, "universe_id": 10770312935}]


def test_lesson_drafts_on_star_quick_are_not_mistaken_for_chat(tmp_path):
    ns = arp.Lease("L", "nightschool", "brain1", "nightschool", "practice", "star-fast", NOW, NOW + 100, 3072, 12,
                   slot=1, extra_models=("star-voice",))
    assert arp.chat_signs(None, brain1(busy=(1,), voice_busy=(1,)), [ns]) == []
    assert arp.chat_signs(None, brain1(busy=(1,), voice_busy=(0,)), [ns])          # star-voice slot 0 = chat
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(), clock))
    grant = p.admit({"job_class": "nightschool", "holder": "ns", "job_id": "practice", "slot": 1,
                     "extra_models": ["star-voice"]})
    assert grant["action"] == "run" and p.leases[grant["lease_id"]].extra_models == ("star-voice",)
    settings = ns_settings(tmp_path, diagnose_model="star-voice")
    client = FakeClient()
    PlannedGate(settings, FakeWatch(), planner=client, log=lambda m: None).look()
    assert client.calls[0][4] == {"slot": 1, "extra_models": ["star-voice"]}


def test_a_connector_studio_id_maps_to_a_free_attached_studio():
    universe, place = arp.STUDIO_TEST_PLACE
    two = brain2(studios=2)
    req = arp.JobRequest("studio-test", "studio-lab-a", "run", studio_id="mcp-abc", universe_id=universe,
                         place_id=place, identity_verified=True)
    assert arp.resolve_studio(req, two, []).studio_id == "studio-100"
    taken = lease("studio-test", "studio-lab-b", studio_id="studio-100")
    assert arp.resolve_studio(req, two, [taken]).studio_id == "studio-101"
    assert admit("studio-test", two, [taken], holder="studio-lab-a", studio_id="mcp-abc", universe_id=universe,
                 place_id=place, identity_verified=True).action == "run"
    both = [taken, lease("studio-test", "studio-lab-c", studio_id="studio-101")]
    assert admit("studio-test", two, both, holder="studio-lab-a", studio_id="mcp-abc", universe_id=universe,
                 place_id=place, identity_verified=True).action == "wait"


# --- Brain page panel ---------------------------------------------------------------------------------------------------

def test_brain_page_planner_snapshot_is_compact_and_fails_closed(tmp_path):
    from star.brain_overview import planner_snapshot
    from star.desktop_core import Settings
    settings_file = tmp_path / "settings.json"
    Settings().save(settings_file)
    assert planner_snapshot(settings_file)["available"] is False          # local provider: nothing is asked
    p, clock = planner(tmp_path)
    p.observe(snap_dict(brain1(), clock))
    p.admit({"job_class": "nightschool", "holder": "nightschool", "job_id": "practice", "slot": 1})
    p.admit({"job_class": "eval", "holder": "eval-1", "job_id": "A-1"})
    clock.t += 1
    p.observe(snap_dict(brain1(busy=(1,)), clock))

    class Direct:
        def status(self):
            return p.status()
    data = planner_snapshot(settings_file, client=Direct())
    assert data["available"] is True and data["machines"][0]["name"] == "brain1"
    assert data["machines"][0]["slots"]["star-fast"] == {"busy": 1, "total": 2}
    assert data["jobs"][0]["jobClass"] == "nightschool" and data["queue"][0]["jobClass"] == "eval"

    class Silent:
        def status(self):
            return None
    assert planner_snapshot(settings_file, client=Silent())["available"] is False
