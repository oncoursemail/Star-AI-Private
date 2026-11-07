"""Minecraft setup checks with fake transport; never starts Node or signs in."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.games import minecraft_setup as setup
from star.home import control


PROFILE = {"name": "Own world", "host": "localhost", "port": 25565, "username": "fixture-account@invalid.test",
           "auth": "microsoft", "version": "", "allows_bots": True}
AUTH = {"type": "auth_code", "uri": "https://www.microsoft.com/link", "code": "ABCD1234"}


class Child:
    def __init__(self, batches):
        self.batches, self.closed, self.polled = list(batches), 0, 0
    def poll(self):
        self.polled += 1
        return self.batches.pop(0) if self.batches else []
    def send(self, command):
        raise AssertionError("Setup must never send a Minecraft command")
    def close(self):
        self.closed += 1


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="star-minecraft-setup-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = {"social": {"minecraft": {"enabled": True, "servers": [dict(PROFILE)]}}}
        self._save()
        self.now, self.stop = 0.0, False
        self.created, self.auth = [], []
        self.child = Child([[{"type": "spawn"}]])

    def _save(self):
        (self.home / "config.json").write_text(json.dumps(self.config), encoding="utf-8")

    def _factory(self, server, *, auth_cache):
        self.created.append((server, auth_cache))
        return self.child

    def _sleep(self, seconds):
        self.now += seconds

    def _run(self, **kwargs):
        return setup.run_setup(self.home, PROFILE, transport_factory=self._factory,
                               clock=lambda: self.now, sleep=self._sleep, stopped=lambda: self.stop,
                               **kwargs)

    def test_preview_opens_no_process_or_cache_and_reports_no_live_proof(self):
        out = self._run()
        self.assertEqual(self.created, [])
        self.assertFalse((self.home / "auth").exists())
        self.assertEqual(out["state"], "preview")
        self.assertFalse(out["connected"] or out["autonomy_verified"])
        self.assertNotIn(PROFILE["username"], json.dumps(out))

    def test_spawn_only_rehearsal_closes_child_and_sends_no_commands(self):
        out = self._run(connect=True)
        self.assertTrue(out["connected"] and out["ok"] and out["child_closed"])
        self.assertFalse(out["autonomy_verified"])
        self.assertEqual(out["commands_sent"], 0)
        self.assertEqual(self.child.closed, 1)
        self.assertEqual(self.created[0][1], self.home / "auth" / "minecraft")

    def test_valid_auth_is_only_sent_to_owner_callback_never_returned(self):
        self.child = Child([[AUTH], [{"type": "spawn"}]])
        out = self._run(connect=True, emit_auth=lambda uri, code: self.auth.append((uri, code)))
        self.assertTrue(out["connected"])
        self.assertEqual(self.auth, [(AUTH["uri"], AUTH["code"])])
        self.assertNotIn(AUTH["code"], json.dumps(out))
        self.assertNotIn(AUTH["uri"], json.dumps(out))

    def test_auth_without_owner_console_closes_without_exposing_code(self):
        self.child = Child([[AUTH]])
        out = self._run(connect=True)
        self.assertEqual(out["state"], "owner_console_required")
        self.assertEqual(self.child.closed, 1)
        self.assertNotIn(AUTH["code"], json.dumps(out))

    def test_exact_official_https_login_endpoint_allowlist(self):
        for host in ("microsoft.com", "www.microsoft.com"):
            for path in ("link", "devicelogin"):
                uri = f"https://{host}/{path}"
                self.assertEqual(setup.validate_login(uri, "ABCD-EFGH"), (uri, "ABCD-EFGH"))
        bad = ("http://microsoft.com/link", "https://microsoft.com.evil.test/link",
               "https://evil.test/microsoft.com/link", "https://microsoft.com@evil.test/link",
               "https://owner@microsoft.com/link", "https://microsoft.com:443/link",
               "https://microsoft.com/link?code=ABCD1234", "https://microsoft.com/link#fragment",
               "https://microsoft.com/link/", "https://microsoft.com/%6cink",
               "https://microsoft.com/other", "https://MICROSOFT.COM/link",
               "https://microsoft.com\\@evil.test/link", " https://microsoft.com/link",
               "https://microsoft.com/link\n", "javascript:alert(1)", None)
        for uri in bad:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                setup.validate_login(uri, AUTH["code"])

    def test_invalid_code_shapes_are_rejected(self):
        for code in ("", "ABC", "aBCD1234", "ABCD\n1234", "ABCD 1234", "ABCD1234\x1b[31m", "A" * 25, None, 12345678):
            with self.subTest(code=code), self.assertRaises(ValueError):
                setup.validate_login(AUTH["uri"], code)

    def test_invalid_auth_event_never_reaches_callback(self):
        self.child = Child([[{**AUTH, "uri": "https://evil.test/link"}]])
        out = self._run(connect=True, emit_auth=lambda *args: self.auth.append(args))
        self.assertEqual(out["state"], "invalid_auth")
        self.assertEqual(self.auth, [])
        self.assertEqual(self.child.closed, 1)

    def test_timeout_always_closes_and_never_claims_connected(self):
        self.child = Child([])
        out = self._run(connect=True, timeout=1)
        self.assertEqual(out["state"], "timeout")
        self.assertFalse(out["connected"])
        self.assertEqual(self.child.closed, 1)

    def test_stop_before_start_never_opens_transport(self):
        self.stop = True
        out = self._run(connect=True)
        self.assertEqual(out["state"], "stopped")
        self.assertEqual(self.created, [])

    def test_injected_stop_callback_cannot_override_global_stop_file(self):
        control.stop(self.home)
        out = self._run(connect=True)
        self.assertEqual(out["state"], "stopped")
        self.assertEqual(self.created, [])

    def test_stop_during_factory_closes_before_poll(self):
        original = self._factory
        def factory(*args, **kwargs):
            self.stop = True
            return original(*args, **kwargs)
        with patch.object(self, "_factory", factory):
            out = self._run(connect=True)
        self.assertEqual(out["state"], "stopped")
        self.assertEqual(self.child.polled, 0)
        self.assertEqual(self.child.closed, 1)

    def test_stop_during_auth_callback_never_claims_spawn(self):
        self.child = Child([[AUTH, {"type": "spawn"}]])
        def show(uri, code): self.stop = True
        out = self._run(connect=True, emit_auth=show)
        self.assertEqual(out["state"], "stopped")
        self.assertFalse(out["connected"])
        self.assertEqual(self.child.closed, 1)

    def test_terminal_events_do_not_leak_raw_error_or_server_text(self):
        for kind in ("kicked", "error", "end"):
            with self.subTest(kind=kind):
                self.child = Child([[{"type": "spawn"}, {"type": kind, "reason": AUTH["code"]}]])
                out = self._run(connect=True)
                self.assertEqual(out["state"], kind)
                self.assertFalse(out["connected"])
                self.assertNotIn(AUTH["code"], json.dumps(out))
                self.assertEqual(self.child.closed, 1)

    def test_poll_failure_and_keyboard_interrupt_still_close(self):
        for error in (OSError(AUTH["code"]), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.child = Child([])
                def poll(): raise error
                self.child.poll = poll
                out = self._run(connect=True)
                self.assertFalse(out["ok"])
                self.assertNotIn(AUTH["code"], json.dumps(out))
                self.assertEqual(self.child.closed, 1)

    def test_owner_callback_failure_never_leaks_code(self):
        self.child = Child([[AUTH]])
        def fail(uri, code): raise OSError(code)
        out = self._run(connect=True, emit_auth=fail)
        self.assertEqual(out["state"], "unavailable")
        self.assertNotIn(AUTH["code"], json.dumps(out))
        self.assertEqual(self.child.closed, 1)

    def test_cleanup_failure_is_reported_without_raw_error(self):
        def fail(): raise OSError(AUTH["code"])
        self.child.close = fail
        out = self._run(connect=True)
        self.assertEqual(out["state"], "cleanup_failed")
        self.assertFalse(out["ok"])
        self.assertNotIn(AUTH["code"], json.dumps(out))

    def test_repeated_auth_challenges_are_bounded(self):
        self.child = Child([[AUTH] * 4])
        out = self._run(connect=True, emit_auth=lambda *args: self.auth.append(args))
        self.assertEqual(out["state"], "auth_limit")
        self.assertEqual(len(self.auth), 3)
        self.assertEqual(self.child.closed, 1)

    def test_unrelated_chat_and_state_events_are_ignored_without_commands(self):
        self.child = Child([[{"type": "chat", "message": AUTH["code"]},
                             {"type": "whisper", "message": "follow me"},
                             {"type": "state", "inventory": {"wood": 3}}, {"type": "spawn"}]])
        out = self._run(connect=True)
        self.assertTrue(out["connected"])
        self.assertEqual(out["commands_sent"], 0)
        self.assertNotIn(AUTH["code"], json.dumps(out))

    def test_reparse_cache_is_refused_before_transport_creation(self):
        original = Path.is_symlink
        def symlink(path):
            return path == self.home / "auth" or original(path)
        with patch.object(Path, "is_symlink", symlink):
            out = self._run(connect=True)
        self.assertEqual(out["state"], "unavailable")
        self.assertEqual(self.created, [])

    def test_auth_callback_cannot_extend_deadline_into_spawn(self):
        self.child = Child([[AUTH, {"type": "spawn"}]])
        def show(*args): self.now += 2
        out = self._run(connect=True, timeout=1, emit_auth=show)
        self.assertEqual(out["state"], "timeout")
        self.assertFalse(out["connected"])
        self.assertEqual(self.child.closed, 1)

    def test_foreign_or_credential_bearing_profile_never_connects(self):
        bad = ({**PROFILE, "host": "other.test"}, {**PROFILE, "password": "fixture"},
               {**PROFILE, "token": "fixture"}, {**PROFILE, "allows_bots": 1},
               {**PROFILE, "port": True}, {**PROFILE, "host": "https://localhost/path"})
        for profile in bad:
            with self.subTest(fields=list(profile)), self.assertRaises(ValueError):
                setup.run_setup(self.home, profile, connect=True, transport_factory=self._factory)
        self.assertEqual(self.created, [])

    def test_disabled_or_duplicated_profile_is_refused(self):
        self.config["social"]["minecraft"]["enabled"] = False
        self._save()
        with self.assertRaises(ValueError): self._run(connect=True)
        self.config["social"]["minecraft"]["enabled"] = True
        self.config["social"]["minecraft"]["servers"].append(dict(PROFILE))
        self._save()
        with self.assertRaises(ValueError): self._run(connect=True)
        self.assertEqual(self.created, [])

    def test_invalid_timeout_and_truthy_connect_are_refused(self):
        for timeout in (0, 901, float("inf"), float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError): self._run(connect=True, timeout=timeout)
        with self.assertRaises(ValueError): self._run(connect=1)
        self.assertEqual(self.created, [])

    def test_cli_preview_is_inert_and_never_prints_account_label(self):
        output = io.StringIO()
        with patch.object(setup, "NodeTransport", side_effect=AssertionError("started Node")), redirect_stdout(output):
            code = setup.cli(["--home", str(self.home), "--server", PROFILE["name"]])
        self.assertEqual(code, 0)
        self.assertNotIn(PROFILE["username"], output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["state"], "preview")

    def test_noninteractive_cli_hides_code_without_explicit_owner_override(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                self.child = Child([[AUTH], [{"type": "spawn"}]])
                output = io.StringIO()
                args = ["--home", str(self.home), "--server", PROFILE["name"], "--connect"]
                if explicit: args.append("--show-login-code")
                with patch.object(setup, "NodeTransport", self._factory), redirect_stdout(output):
                    setup.cli(args)
                self.assertEqual(AUTH["code"] in output.getvalue(), explicit)
                self.assertEqual(self.child.closed, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
