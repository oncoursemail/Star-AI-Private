"""Offline Home lifecycle regression checks; no model, desktop, accounts or network."""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home import control, loop, plugins  # noqa: E402
from star.home.activities import Context, Registry  # noqa: E402
from star.home.attention import Attention, Inbox, Situation  # noqa: E402
from star.home.life import Life  # noqa: E402


class Probe:
    free: int | None = 8000
    game = ""

    def free_mb(self):
        return self.free

    def game_running(self, names):
        return self.game


class RecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.life = Life(self.home)
        self.registry = Registry()
        self.now = 100.0
        class EmptyInbox:
            def due(self):
                return []
        self.attention = Attention(cast(Inbox, EmptyInbox()), Situation(), clock=lambda: self.now)
        self.probe = Probe()
        self.config = {"pause_minutes": 0, "sessions_per_day": 100, "game_reserve_mb": 5000}
        self.runs = []
        for name in ("_inner_tick", "_feel_outcome", "_emotion"):
            mock = patch.object(loop, name)
            mock.start()
            self.addCleanup(mock.stop)

    def add(self, name="draw", **kwargs):
        def run(ctx):
            self.runs.append((name, ctx.resumed, dict(ctx.resume_state)))
            return {"ok": True, "verified": True, "summary": "host checked", "evidence": ["fake receipt"]}
        self.registry.register(name, "drawing", run, **kwargs)
        return self.registry.items[name]

    def cycle(self, chat=None):
        return loop.cycle(self.home, self.config, self.registry, self.life, None, chat,
                          probe=self.probe, attention=self.attention)

    def park(self, activity):
        self.attention.park(activity, activity.interest, None, {"layer": 3})
        assert self.attention.parked is not None
        return self.attention.parked

    def test_requested_gpu_work_waits_without_discarding_previous_continuation(self):
        prior = self.park(self.add("prior"))
        self.add(gpu_mb=4000)
        self.probe.game = "fixture-game"
        self.attention.request("draw")
        self.assertEqual(self.cycle()["state"], "waiting")
        self.assertEqual(self.attention.requested, "draw")
        self.assertIs(self.attention.parked, prior)
        self.assertEqual(self.runs, [])
        self.assertEqual(self.life.history(), [])
        self.probe.free = 10000
        self.assertEqual(self.cycle()["activity"], "draw")
        self.assertEqual(self.runs, [("draw", False, {})])
        self.assertIsNone(self.attention.parked)

    def test_resumed_gpu_work_rechecks_resources_and_keeps_original_deadline(self):
        parked = self.park(self.add(gpu_mb=4000))
        self.probe.free = None
        self.now += 60
        self.assertEqual(self.cycle()["state"], "waiting")
        self.assertIs(self.attention.parked, parked)
        self.assertEqual(parked.at, 100)
        self.assertEqual(self.life.history(), [])
        self.probe.free = 8000
        self.assertEqual(self.cycle()["state"], "worked")
        self.assertEqual(self.runs, [("draw", True, {"layer": 3})])

    def test_blocked_resume_expires_instead_of_becoming_immortal(self):
        parked = self.park(self.add(gpu_mb=4000))
        self.probe.free = None
        self.assertEqual(self.cycle()["state"], "waiting")
        self.now = parked.at + float(self.attention.cfg["resume_within_minutes"]) * 60 + 1
        self.assertEqual(self.cycle()["state"], "idle")
        self.assertIsNone(self.attention.parked)
        self.assertEqual(self.runs, [])

    def test_explicit_request_preserves_adapters_with_their_own_brain_or_local_fallback(self):
        self.add(needs_brain=True)
        self.attention.request("draw")
        self.assertTrue(self.cycle()["verified"])
        self.assertEqual(self.runs, [("draw", False, {})])

    def test_resume_preserves_adapters_with_their_own_brain_or_local_fallback(self):
        self.park(self.add(needs_brain=True))
        self.assertTrue(self.cycle()["verified"])
        self.assertEqual(self.runs[0], ("draw", True, {"layer": 3}))

    def test_automatic_selection_still_filters_missing_brain(self):
        self.add(needs_brain=True)
        self.assertEqual(self.cycle()["state"], "idle")
        self.assertEqual(self.runs, [])
        self.assertEqual(self.life.history(), [])

    def test_stop_arriving_during_resource_probe_preserves_request(self):
        self.add(gpu_mb=4000)
        self.attention.request("draw")
        self.probe.free_mb = lambda: (control.stop(self.home), 8000)[1]
        self.assertEqual(self.cycle()["state"], "stopped")
        self.assertEqual(self.attention.requested, "draw")
        self.assertEqual(self.runs, [])
        self.probe.free_mb = lambda: 8000
        control.resume(self.home)
        self.assertEqual(self.cycle()["state"], "worked")

    def test_deferred_request_does_not_overwrite_newer_request_from_watcher(self):
        self.add("later")
        self.add(gpu_mb=4000)
        self.attention.request("draw")
        self.probe.free_mb = lambda: (self.attention.request("later"), 0)[1]
        self.assertEqual(self.cycle()["state"], "waiting")
        self.assertEqual(self.attention.requested, "later")
        self.assertEqual(self.cycle()["activity"], "later")

    def test_initial_stop_never_consumes_work(self):
        parked = self.park(self.add())
        self.attention.request("draw")
        control.stop(self.home)
        self.assertEqual(self.cycle()["state"], "stopped")
        self.assertEqual(self.attention.requested, "draw")
        self.assertIs(self.attention.parked, parked)
        self.assertEqual(self.runs, [])

    def test_runtime_pending_cleanup_blocks_admission_without_owner_stop_file(self):
        self.add()
        self.attention.request("draw")
        self.registry.runtime = SimpleNamespace(admission_blocked=lambda: True)
        self.assertFalse(control.stopped(self.home))
        self.assertEqual(self.cycle()["state"], "stopped")
        self.assertEqual(self.attention.requested, "draw")
        self.assertEqual(self.runs, [])
        self.assertEqual(self.life.history(), [])

    def test_bad_plugin_contracts_become_recorded_failures_and_next_cycle_recovers(self):
        malformed = [None, [], "success", {"ok": "false", "verified": True},
                     {"ok": True, "verified": "false"}, {"steps": "ten"}, {"steps": -1},
                     {"steps": True}, {"steps": 10 ** 5000}, {"minutes": float("nan")}, {"minutes": float("inf")},
                     {"minutes": -1}, {"minutes": 10 ** 400}, {"evidence": "file"},
                     {"evidence": [object()]}, {"failures": [None]}, {"summary": object()},
                     {"summary": "\ud800"}, {"evidence": ["\udfff"]}, {"failures": ["\ud800"]},
                     {"paused": "false"}, {"paused": True, "resume_state": []}, {"goal_done": "true"}]
        for index, bad in enumerate(malformed):
            with self.subTest(index=index):
                goal = self.life.add_goal("fixture", "checked completion")
                outputs = iter([bad, {"ok": True, "verified": True, "goal_done": True}])
                self.registry.register("fixture", "fixture", lambda ctx: next(outputs))
                self.attention.request("fixture")
                result = self.cycle()
                self.assertEqual(result["state"], "worked")
                self.assertFalse(result["verified"])
                row = self.life.history()[-1]
                self.assertFalse(row["claimed"])
                self.assertIn("invalid outcome", row["summary"])
                self.assertEqual(self.attention.situation.kind, "idle")
                self.assertIsNone(self.attention.parked)
                self.attention.request("fixture")
                self.assertTrue(self.cycle()["verified"])
                completed = next(g for g in self.life.goals(None) if g["id"] == goal["id"])
                self.assertEqual((completed["status"], completed["tries"]), ("done", 2))

    def test_direct_history_does_not_accept_truthy_success_or_contradictory_claims(self):
        for outcome in ({"ok": True, "verified": "false"}, {"ok": "false", "verified": True},
                        {"ok": False, "verified": True}, {"verified": True}):
            self.assertFalse(self.life.record("drawing", "fixture", outcome)["verified"])
        goal = self.life.add_goal("drawing", "do not finish from a string")
        self.life.record("drawing", "fixture", {"ok": True, "verified": True, "goal_done": "false"}, goal)
        self.assertEqual(next(g for g in self.life.goals() if g["id"] == goal["id"])["status"], "open")

    def test_crashed_activity_releases_attention_and_does_not_prevent_next_cycle(self):
        def crash(ctx):
            raise RuntimeError("fixture failure")
        self.registry.register("crash", "drawing", crash)
        self.attention.request("crash")
        self.assertFalse(self.cycle()["verified"])
        self.assertEqual(self.attention.situation.kind, "idle")
        self.add()
        self.attention.request("draw")
        self.assertTrue(self.cycle()["verified"])
        self.assertEqual(len(self.life.history()), 2)

    def test_well_formed_pause_still_resumes_exact_state_and_records_only_completion(self):
        def run(ctx):
            if not ctx.resumed:
                return {"ok": True, "verified": False, "paused": True, "resume_state": {"level": 7}}
            self.assertEqual(ctx.resume_state, {"level": 7})
            return {"ok": True, "verified": True, "minutes": 7.5, "steps": 3}
        self.registry.register("play", "play_games", run)
        self.attention.request("play")
        self.assertEqual(self.cycle()["state"], "paused")
        self.assertEqual(self.life.history(), [])
        self.assertTrue(self.cycle()["verified"])
        self.assertEqual(len(self.life.history()), 1)
        self.assertEqual(self.life.history()[0]["minutes"], 7.5)


class GameStopChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.now = 0.0
        self.interrupted = False
        self.sessions, self.transports, self.controllers, self.sleeps = [], [], [], []
        self.on_create = self.on_start = self.on_step = self.on_transport = None
        self.active = {}
        self.cfg = {"play": {"session_minutes": 0.01, "step_s": 0.25, "load_wait_s": 0, "obby_places": [123]}}
        self.rt = SimpleNamespace(
            home=self.home, config=self.cfg, social=None,
            host=SimpleNamespace(focus_window=lambda name: True),
            voice=SimpleNamespace(speak=lambda text: False, window_for=lambda game: None),
            hooks={"sleep": self.sleep, "clock": lambda: self.now,
                   "node_transport": self.make_transport, "minecraft_session": self.make_session,
                   "roblox_session": self.make_session},
            planner_brain=lambda: None, my_names=lambda: ["Star"],
            social_settings=lambda: {"roblox": {"enabled": True, "experiences": [{"place_id": 123, "name": "fixture"}]},
                                     "minecraft": {"enabled": True, "servers": [{"name": "fixture", "host": "localhost", "allows_bots": True}]}},
            track_activity=self.track, untrack_activity=self.untrack)
        self.ctx = SimpleNamespace(home=self.home, resume_state={}, situation=SimpleNamespace(in_moment=False),
                                   interrupt=SimpleNamespace(is_set=lambda: self.interrupted))
        owner = self

        class MinecraftController:
            def __init__(self, chat, server, *, transport_factory, **kwargs):
                self.factory, self.server, self.transport = transport_factory, server, None
                self.busy_until = 0
                owner.controllers.append(self)

            def start(self):
                self.transport = self.factory(self.server)
                return SimpleNamespace(ok=True)

            def step(self):
                if owner.on_step:
                    owner.on_step()
                return SimpleNamespace(ok=True, acted=True, note="fixture step")

        class RobloxController:
            def __init__(self, host, chat, experiences, **kwargs):
                self.current = None
                self.stops = 0
                owner.controllers.append(self)

            def start(self):
                self.current = SimpleNamespace(place_id=123)
                return SimpleNamespace(ok=True)

            def stop(self):
                self.stops += 1
                self.current = None

        for path, cls in (("star.games.minecraft.MinecraftPlay", MinecraftController),
                          ("star.games.roblox.RobloxPlay", RobloxController)):
            mock = patch(path, cls)
            mock.start()
            self.addCleanup(mock.stop)
        self.registry = Registry(runtime=self.rt)
        plugins.register_play(self.registry)

    def track(self, name, stopper):
        self.active[name] = stopper

    def untrack(self, name, stopper):
        if self.active.get(name) is stopper:
            del self.active[name]

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps.append(seconds)

    def make_transport(self, server):
        class Transport:
            closed = 0

            def close(self):
                self.closed += 1

            def send(self, command):
                pass

            def poll(self):
                return []
        transport = Transport()
        self.transports.append(transport)
        if self.on_transport:
            self.on_transport()
        return transport

    def make_session(self, *args, **kwargs):
        owner = self

        class Session:
            started = False
            stopped = 0
            fast = SimpleNamespace(on_moment=[])

            def start(self):
                self.started = True
                if owner.on_start:
                    owner.on_start()

            def stop(self):
                self.stopped += 1

            def report(self):
                return {"ticks": 2}
        session = Session()
        self.sessions.append(session)
        if self.on_create:
            self.on_create()
        return session

    def run_game(self, game="minecraft"):
        return self.registry.items[game].run(cast(Context, self.ctx))

    def assert_clean(self, *, sessions=True):
        if sessions:
            self.assertTrue(all(s.stopped == 1 for s in self.sessions))
        self.assertTrue(all(t.closed == 1 for t in self.transports))
        self.assertNotIn("minecraft.session", self.active)
        self.assertNotIn("roblox.session", self.active)

    def test_stop_before_start_creates_no_transport_or_session(self):
        control.stop(self.home)
        for game in ("minecraft", "roblox"):
            out = self.run_game(game)
            self.assertTrue(out["stopped"])
            self.assertFalse(out.get("paused"))
        self.assertEqual(self.transports, [])
        self.assertEqual(self.sessions, [])

    def assert_preview(self):
        def forbidden(*args, **kwargs):
            self.fail("preview called a controller/session/transport start factory")
        for controller in self.controllers:
            controller.start = forbidden
        for key in ("node_transport", "minecraft_session", "roblox_session"):
            self.rt.hooks[key] = forbidden
        for game in ("minecraft", "roblox"):
            result = self.run_game(game)
            self.assertTrue(result["ok"])
            self.assertFalse(result["verified"])
            self.assertIn("dry run", result["summary"])
            self.assertEqual(result["evidence"], [])
        self.assertEqual(self.sessions, [])
        self.assertEqual(self.transports, [])
        self.assertEqual(self.sleeps, [])
        self.assertEqual(set(self.active), {"minecraft.controller", "roblox.controller"})

    def test_context_preview_works_without_runtime_executor_and_never_starts_games(self):
        self.assertFalse(hasattr(self.rt, "executor"))
        self.ctx.executor = SimpleNamespace(dry_run=True)
        self.assert_preview()

    def test_runtime_preview_fallback_without_context_executor_never_starts_games(self):
        self.assertFalse(hasattr(self.ctx, "executor"))
        self.rt.executor = SimpleNamespace(dry_run=True)
        self.assert_preview()

    def test_stop_during_transport_creation_closes_unassigned_child(self):
        self.on_transport = lambda: control.stop(self.home)
        self.assertTrue(self.run_game()["stopped"])
        self.assertEqual(self.sessions, [])
        self.assert_clean()

    def test_stop_during_session_creation_never_starts_it(self):
        for game in ("minecraft", "roblox"):
            control.resume(self.home)
            self.on_create = lambda: control.stop(self.home)
            self.assertTrue(self.run_game(game)["stopped"])
            self.assertFalse(self.sessions[-1].started)
            self.assert_clean()

    def test_stop_during_session_start_cleans_both_games(self):
        for game in ("minecraft", "roblox"):
            control.resume(self.home)
            self.on_start = lambda: control.stop(self.home)
            self.assertTrue(self.run_game(game)["stopped"])
            self.assert_clean()

    def test_start_exception_cleans_session_and_transport(self):
        def fail():
            raise RuntimeError("fixture start failed")
        self.on_start = fail
        for game in ("minecraft", "roblox"):
            with self.assertRaises(RuntimeError):
                self.run_game(game)
            self.assert_clean()

    def test_factory_exception_still_closes_controller_transport(self):
        self.rt.hooks["minecraft_session"] = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("factory"))
        with self.assertRaises(RuntimeError):
            self.run_game()
        self.assert_clean()

    def test_step_exception_cleans_session_and_transport(self):
        self.on_step = lambda: (_ for _ in ()).throw(RuntimeError("fixture step"))
        with self.assertRaises(RuntimeError):
            self.run_game()
        self.assert_clean()

    def test_stop_inside_step_is_not_verified_or_parked(self):
        self.on_step = lambda: control.stop(self.home)
        out = self.run_game()
        self.assertTrue(out["stopped"])
        self.assertFalse(out["verified"])
        self.assertFalse(out.get("paused"))
        self.assertEqual(self.sleeps, [])
        self.assert_clean()

    def test_normal_completion_cleans_sessions_and_transports(self):
        self.assertTrue(self.run_game()["verified"])
        self.assert_clean()
        self.assertTrue(self.run_game("roblox")["verified"])
        self.assert_clean()
        self.assertIsNone(self.controllers[0].current)

    def test_attention_pause_retains_only_controller_and_resume_creates_fresh_session(self):
        self.interrupted = True
        paused = self.run_game()
        self.assertTrue(paused["paused"])
        self.assertEqual(self.sessions[0].stopped, 1)
        self.assertEqual(self.transports[0].closed, 0)
        self.assertNotIn("minecraft.session", self.active)
        self.ctx.resume_state = paused["resume_state"]
        self.interrupted = False
        self.assertTrue(self.run_game()["verified"])
        self.assertEqual(len(self.sessions), 2)
        self.assertEqual(len(self.transports), 1)
        self.assert_clean()

    def test_cleanup_failure_is_unverified_and_still_closes_transport(self):
        make = self.rt.hooks["minecraft_session"]

        def broken(*args, **kwargs):
            session = make(*args, **kwargs)
            session.stop = lambda: (_ for _ in ()).throw(RuntimeError("fixture cleanup"))
            return session
        self.rt.hooks["minecraft_session"] = broken
        out = self.run_game()
        self.assertFalse(out["ok"])
        self.assertFalse(out["verified"])
        self.assertFalse(out.get("paused"))
        self.assertEqual(self.transports[0].closed, 1)
        self.assertNotIn("minecraft.session", self.active)

    def test_cleanup_logging_failure_does_not_skip_other_resource_cleanup(self):
        original = self.make_session

        def broken(*args, **kwargs):
            session = original(*args, **kwargs)
            session.stop = lambda: (_ for _ in ()).throw(RuntimeError("fixture cleanup"))
            return session
        self.rt.hooks["minecraft_session"] = broken
        with patch.object(control, "log_action", side_effect=OSError("fixture disk unavailable")):
            out = self.run_game()
        self.assertFalse(out["verified"])
        self.assertEqual(self.transports[0].closed, 1)
        self.assertNotIn("minecraft.session", self.active)

    def test_registered_stoppers_work_while_main_game_step_is_stalled(self):
        entered, release = threading.Event(), threading.Event()
        self.on_step = lambda: (entered.set(), release.wait(3))
        results = []
        thread = threading.Thread(target=lambda: results.append(self.run_game()))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            control.stop(self.home)
            for stop in list(self.active.values()):
                stop()
            self.assertEqual(self.transports[0].closed, 1)
            self.assertEqual(self.sessions[0].stopped, 1)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]["stopped"])
        self.assert_clean()

    def test_concurrent_session_cleanup_does_not_claim_success_while_first_attempt_is_running(self):
        entered, release = threading.Event(), threading.Event()
        errors = []

        def fail_later():
            entered.set()
            release.wait(3)
            raise RuntimeError("fixture later failure")
        stopper = plugins._once(fail_later)

        def first():
            try:
                stopper()
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=first)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(RuntimeError, "still running"):
                stopper()
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["fixture later failure"])
        with self.assertRaisesRegex(RuntimeError, "previous session cleanup failed"):
            stopper()

    def test_shared_step_loop_honors_stop_even_when_interrupt_watching_is_disabled(self):
        steps = []
        def step():
            steps.append(1)
            control.stop(self.home)
            return SimpleNamespace(ok=True, acted=True, note="fixture")
        out = plugins.run_steps(step, self.ctx, minutes=1, step_s=10, sleep=self.sleep,
                                clock=lambda: self.now, watch_interrupt=False)
        self.assertEqual(steps, [1])
        self.assertTrue(out["stopped"])
        self.assertFalse(out["verified"])
        self.assertEqual(self.sleeps, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
