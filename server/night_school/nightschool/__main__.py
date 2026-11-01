"""python -m nightschool <command>

  run            the service loop: wait for an idle brain, practise, write the report, repeat
  dry-run        the whole loop against the built-in fake brain (no request reaches the real brain)
  validate-pool  load the practice pool with the repository's loader and count what was dropped
  guard          write the hash list that keeps copies of evaluation tasks out of the pool
  look           one look at the brain: idle or busy (two status reads, no model request)
  report         print the report rebuilt from the stored state
  conduct        one night-conductor cycle (conductor.py): new practice tasks from the newest failures and notes
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

from . import report
from .config import Settings
from .engine import Engine, Result, Store, Yielded
from .idle import BrainWatch, IdleGate, PlannedGate, PriorityGate, make_planner


def log(text: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + " " + text, flush=True)


class Stopper:
    def __init__(self):
        self.requested = False
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._set)
            except (ValueError, OSError):
                pass

    def _set(self, *_args) -> None:
        self.requested = True

    def __call__(self) -> bool:
        return self.requested


def make_gate(settings: Settings, watch: BrainWatch, *, planner, log=print, holder: str = "nightschool",
              slot: int | None = None, extra_lane: bool = False):
    """STAR_NS_GATE=priority: the priority-proxy gate (works beside other clients); otherwise the planner/idle gate."""
    if settings.gate.lower() == "priority":
        return PriorityGate(settings, watch, log=log)
    return PlannedGate(settings, watch, planner=planner, holder=holder, slot=slot, extra_lane=extra_lane, log=log)


def run(settings: Settings) -> int:
    from .pool import load_pool
    from .real import RealModel, bootstrap, export_outbox
    settings.ensure_dirs()
    key = bootstrap(settings)
    stop = Stopper()
    store = Store(settings.data)

    def gate_log(text: str) -> None:
        """The gate speaks when its state changes (and every 15 minutes): keep the report's status line current,
        so a reader can tell a waiting service from a dead one."""
        log(text)
        try:
            report.write(settings.report_file, store.state, status=text)
        except OSError:
            pass
    # The resource planner admits night school while chat is quiet and asks it to yield otherwise; when the planner
    # is off or unreachable this is exactly the old idle gate.
    planner = make_planner(settings, key)
    gate = make_gate(settings, BrainWatch(settings.brain_url, key), planner=planner, log=gate_log)
    pool = load_pool(settings.pool)
    log("night school started; " + pool.summary() + f"; lanes {settings.lanes}")
    model = RealModel(settings, gate, knowledge=settings.knowledge_url, stop=stop)
    for k in range(1, settings.lanes):
        model.add_lane(make_gate(settings, BrainWatch(settings.brain_url, key), planner=planner,
                                 holder=f"nightschool-{k}", slot=settings.slot + k, extra_lane=True,
                                 log=lambda text, k=k: log(f"lane {k + 1}: {text}")), settings.slot + k)
    lanes = [lambda work, k=k: model.in_lane(k, work) for k in range(settings.lanes)] if settings.lanes > 1 else None
    engine = Engine(settings, pool, store, solve=model.solve, diagnose=model.diagnose,
                    check_lesson=model.check_lesson, log=log)
    store.save()
    report.write(settings.report_file, store.state, status="service started; waiting until the brain has been idle "
                 f"for {int(settings.idle_s)} s")
    while not stop():
        pool = load_pool(settings.pool)                       # new practice tasks are picked up between batches
        engine.set_pool(pool)
        model.prelude = pool.prelude
        if not engine.training:
            log("no practice tasks in the pool, waiting")
            for _ in range(30):
                if stop():
                    break
                time.sleep(10)
            continue
        if not gate.wait(stop):
            break
        status = "working"
        try:
            outcomes = engine.run_batch(before_item=lambda: not stop(), lanes=lanes)
            log("batch done: " + (", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())) or "nothing"))
        except Yielded as yielded:
            store.count("backed_off")
            store.save()
            status = f"backed off ({yielded}); waiting for an idle brain"
            log(status)
        except Exception as exc:                              # one bad batch must not end the service
            store.count("batch_errors")
            store.save()
            status = "batch stopped by an internal error (" + type(exc).__name__ + "); will try again"
            log(status)
            time.sleep(60)
        try:
            report.write(settings.report_file, store.state, status=status)
            export_outbox(settings, store.state)
        except Exception as exc:
            log("report or outbox could not be written (" + type(exc).__name__ + ")")
        if settings.conductor.lower() not in ("off", "0", "no", "false"):
            from . import conductor
            conductor.after_batch(settings, model, log=log)       # never raises; at most once per interval
    for lane_gate in model.gates:
        lane_gate.close()
    log("night school stopped")
    return 0


def conduct(settings: Settings) -> int:
    """One conductor cycle outside the night-school loop (the star-night-conductor timer). It waits up to
    STAR_NS_CONDUCTOR_WAIT_S for a quiet brain; a busy brain means the night-school loop is working and runs the
    conductor itself after its batch."""
    from . import conductor
    from .real import RealModel, bootstrap
    settings.ensure_dirs()
    key = bootstrap(settings)
    state = conductor.load_state(settings)
    reason = conductor.due(settings, state)
    if reason:
        log("night conductor: not now (" + reason + ")")
        return 0
    practising = conductor.loop_practising(settings)
    if practising:
        log(f"night conductor: not now (the night-school loop is practising, last batch {practising}; it runs the "
            "conductor after its batches)")
        return 0
    stop = Stopper()
    gate = IdleGate(settings, BrainWatch(settings.brain_url, key), log=log)
    deadline = time.monotonic() + float(os.environ.get("STAR_NS_CONDUCTOR_WAIT_S", "1500"))
    while (why := gate.look()):
        if stop() or time.monotonic() > deadline:
            log("night conductor: the brain was not quiet (" + (", ".join(gate.signs) or why) + "); nothing done")
            return 0
        time.sleep(settings.poll_s)
    model = RealModel(settings, gate, knowledge=settings.knowledge_url, stop=stop)
    try:
        with conductor.CycleLock(settings) as got:
            if not got:
                log("night conductor: another cycle is running")
                return 0
            models = conductor.pick_models(settings, gate.watch)
            if not models:
                log("night conductor: no model with a free slot; nothing done")
            conductor.run_cycle(settings, model.complete, conductor.validators_for(settings, model), log=log, models=models)
    except Yielded as yielded:
        log(f"night conductor: stopped ({yielded})")
    finally:
        model.close()
    return 0


def dry_run(settings: Settings, items: int, real_checks: bool) -> int:
    """The same code path as `run` (run_task, the lesson store, the slot pin, the scorer, the report, the outbox)
    with the fake brain. With --real-checks the static Luau check is the server's knowledge service (no model)."""
    from . import fake
    from .pool import load_pool
    from .real import RealModel, bootstrap, export_outbox
    with tempfile.TemporaryDirectory(prefix="ns-dry-") as folder, fake.FakeBrain() as brain:
        dry = Settings(home=Path(folder), brain_url=brain.url, key_file=settings.key_file, luau_vm=settings.luau_vm,
                       idle_s=0, poll_s=0.2, watch_s=0.5, validation_percent=100,
                       validation_max=len(fake.DRY_VALIDATION_IDS), samples=2, recheck_samples=2, batch=items,
                       share="", validation_share=0, knowledge_url=settings.knowledge_url,
                       lock_dir=str(Path(folder) / "no-lock"))
        dry.ensure_dirs()
        import os
        os.environ["STAR_NS_APP"] = str(settings.app)
        key = bootstrap(dry) or "dry-run-key"
        os.environ.setdefault("STAR_SERVER_API_KEY", key)
        gate = IdleGate(dry, BrainWatch(brain.url), log=log)
        model = RealModel(dry, gate, knowledge="off", luau_check=None if real_checks else fake.luau_ok)
        if real_checks:
            from star.desktop_core import Settings as AppSettings
            from star.doc_knowledge import client_for
            model._knowledge = client_for(AppSettings(provider="star_server", server_endpoint=settings.brain_url.rstrip("/") + "/v1",
                                                      model=settings.model, knowledge_endpoint=settings.knowledge_url))
        tasks = fake.dry_tasks()
        pool = load_pool(dry.pool, extra=tasks)
        log("dry run: " + pool.summary())
        store = Store(dry.data)
        store.state["validation_ids"] = list(fake.DRY_VALIDATION_IDS)     # the five validation tasks, fixed
        engine = Engine(dry, pool, store, solve=model.solve, diagnose=model.diagnose, check_lesson=model.check_lesson, log=log)
        log(f"dry run: {len(engine.training)} training tasks, {len(engine.validation)} validation tasks")
        try:
            engine.run_batch(items)
        finally:
            model.close()
        text = report.write(dry.report_file, store.state, status="dry run with the fake brain")
        out = export_outbox(dry, store.state)
        slots = sorted({body.get("id_slot") for body in brain.completions})
        counters = store.state["counters"]
        print(text)
        log(f"dry run: {len(brain.completions)} fake model requests, slots used {slots}; outbox {out}")
        vm_ok = True
        if real_checks:
            from .real import LocalSandbox
            ran = LocalSandbox(settings.luau_vm).run("print('@@DONE')")
            vm_ok = ran.rc == 0 and "@@DONE" in ran.stdout and not ran.error
            log("dry run: Luau VM sandbox " + ("works" if vm_ok else "FAILED (" + (ran.error or f"status {ran.rc}") + ")"))
            log("dry run: static Luau checks were done by the knowledge service")
        ok = (vm_ok and counters.get("passed_first", 0) >= 1 and counters.get("fixed_by_lesson", 0) >= 2
              and counters.get("lessons_promoted", 0) >= 1 and slots == [1] and out["lessons"] >= 1 and len(text) <= report.LIMIT)
        log("dry run " + ("PASSED" if ok else "FAILED"))
        return 0 if ok else 1


def lane_solve(settings: Settings) -> int:
    """Child process of a parallel lane: one answer + its checks. Request on stdin, Result as one JSON line."""
    from dataclasses import asdict
    from .real import RealModel, bootstrap
    request = json.loads(sys.stdin.read())
    settings.slot = int(request["slot"])
    bootstrap(settings)

    class Gate:                       # the parent lane watches and kills this process; here nothing waits
        class watch:
            @staticmethod
            def slot_for(_wanted):
                return {}

        def wait(self, _stop):
            return True

        def intruder(self, _slot):
            return ""

        def own_work_done(self):
            pass
    model = RealModel(settings, Gate(), wait=False)
    model.prelude = request.get("prelude", "")
    try:
        result = model.solve(request["task"], request.get("lessons", []))
    except Yielded as exc:
        result = Result(error=f"yielded ({exc})")
    print(json.dumps(asdict(result)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="nightschool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    dry = sub.add_parser("dry-run")
    dry.add_argument("--items", type=int, default=8)
    dry.add_argument("--real-checks", action="store_true", help="use the knowledge service's static Luau check")
    sub.add_parser("validate-pool")
    guard = sub.add_parser("guard")
    guard.add_argument("--suite", action="append", required=True, type=Path)
    guard.add_argument("--out", required=True, type=Path)
    sub.add_parser("look")
    sub.add_parser("report")
    sub.add_parser("conduct")
    sub.add_parser("lane-solve", help="(internal) one answer for a parallel lane; request on stdin")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "guard":
        from .pool import build_guard
        data = build_guard(args.suite)
        args.out.write_text(json.dumps(data), encoding="utf-8")
        print(f"guard written: {len(data['prompt_sha256'])} prompt hashes")
        return 0
    if args.command == "report":
        print(report.build(Store(settings.data).state))
        return 0
    if args.command == "look":
        from .idle import read_key
        gate = IdleGate(settings, BrainWatch(settings.brain_url, read_key(settings.key_file)), log=log)
        print(gate.look() or "brain idle")
        return 0
    app = str(settings.app)
    if app not in sys.path:
        sys.path.insert(0, app)
    if args.command == "validate-pool":
        from .pool import load_pool
        pool = load_pool(settings.pool)
        print(pool.summary())
        return 0 if pool.tasks else 1
    if args.command == "dry-run":
        return dry_run(settings, args.items, args.real_checks)
    if args.command == "lane-solve":
        return lane_solve(settings)
    if args.command == "conduct":
        return conduct(settings)
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
