"""Owner setup and independent STOP channels on synthetic state; no PC or account actions."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home import control
from star.home.onboarding import configure, server_config, social_config
from star.home.runtime import Runtime
from star.social.activity import DEFAULT_SETTINGS
from star.social.friends import FriendMemory


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="star-integration-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.memory = FriendMemory(self.home / "friends.sqlite3")
        self.addCleanup(self.memory.close)
        self.voice = SimpleNamespace(set_stop_check=lambda check: setattr(self, "check_stop", check), stop=lambda: None)
        self.rt = Runtime(self.home, {}, SimpleNamespace(dry_run=False), SimpleNamespace(), memory=self.memory,
                          voice=self.voice, emotion=None)
        self.profile = server_config("Practice", "server.example.invalid", 25565, "Star", "microsoft", True)

    def configure(self, **kwargs):
        return configure(self.home, legacy_loader=lambda: DEFAULT_SETTINGS, **kwargs)

    def test_preview_is_inert_and_hides_account_metadata(self):
        result = self.configure(discord=True, server=self.profile)
        self.assertFalse((self.home / "config.json").exists())
        self.assertFalse(result["sign_in_performed"] or result["live_use_verified"])
        self.assertNotIn(self.profile["host"], json.dumps(result))

    def test_apply_persists_inline_settings_preserving_other_fields(self):
        path = self.home / "config.json"
        path.write_text(json.dumps({"dry_run": True, "owner_extra": "keep"}))
        self.configure(discord=True, server=self.profile, apply=True)
        self.configure(server=self.profile, apply=True)
        raw = json.loads(path.read_text())
        self.assertTrue(raw["dry_run"])
        self.assertEqual(raw["owner_extra"], "keep")
        self.assertEqual(len(raw["social"]["minecraft"]["servers"]), 1)
        self.assertTrue(control.load_config(self.home)["social"]["discord"]["enabled"])
        rt = Runtime(self.home, control.load_config(self.home), SimpleNamespace(dry_run=True), None, voice=self.voice, emotion=None)
        self.assertTrue(rt.social_settings()["minecraft"]["enabled"])

    def test_preserves_legacy_configuration_during_first_inline_change(self):
        legacy = social_config(DEFAULT_SETTINGS)
        legacy["minecraft"].update(enabled=True, servers=[self.profile])
        configure(self.home, discord=True, apply=True, legacy_loader=lambda: legacy)
        self.assertEqual(json.loads((self.home / "config.json").read_text())["social"]["minecraft"], legacy["minecraft"])

    def test_explicit_empty_inline_config_never_reenables_legacy(self):
        legacy = social_config(DEFAULT_SETTINGS)
        legacy["discord"]["enabled"] = True
        (self.home / "config.json").write_text('{"social":{}}')
        result = configure(self.home, server=self.profile, legacy_loader=lambda: legacy)
        self.assertFalse(result["discord_enabled"])
        rt = Runtime(self.home, control.load_config(self.home), SimpleNamespace(dry_run=True), None, voice=self.voice, emotion=None)
        self.assertFalse(rt.social_settings()["discord"]["enabled"])

    def test_selected_profile_moves_first_without_deleting_others(self):
        self.configure(server=self.profile, apply=True)
        other = {**self.profile, "name": "Other"}
        self.configure(server=other, apply=True)
        rows = json.loads((self.home / "config.json").read_text())["social"]["minecraft"]["servers"]
        self.assertEqual([row["name"] for row in rows], ["Other", "Practice"])

    def test_limit_and_invalid_existing_permissions_fail_before_write(self):
        social = social_config(DEFAULT_SETTINGS)
        social["minecraft"]["servers"] = [{**self.profile, "name": str(i)} for i in range(16)]
        path = self.home / "config.json"
        original = json.dumps({"social": social})
        path.write_text(original)
        with self.assertRaises(ValueError):
            self.configure(server=self.profile, apply=True)
        self.assertEqual(path.read_text(), original)
        social["minecraft"]["servers"] = [{**self.profile, "allows_bots": "false"}]
        with self.assertRaises(ValueError):
            social_config(social)
        social["minecraft"]["servers"][0]["allows_bots"] = False
        self.assertIs(social_config(social)["minecraft"]["servers"][0]["allows_bots"], False)

    def test_host_port_auth_and_permission_checks(self):
        for host in ("https://server.example.invalid", "user@server.example.invalid", "host/path", "host\nvalue"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                server_config("Practice", host, 25565, "Star", "microsoft", True)
        for port in (True, 0, 65536):
            with self.assertRaises(ValueError):
                server_config("Practice", "host", port, "Star", "microsoft", True)
        with self.assertRaises(ValueError):
            server_config("Practice", "host", 25565, "Star", "microsoft", False)

    def test_standing_lookups_never_create_reciprocity(self):
        self.rt.standing("discord", "Someone")
        self.assertIsNone(self.memory.known("discord", "Someone"))
        self.assertIsNone(self.rt.person_id("discord", "Someone"))
        self.rt.feel("friend_ignored", "discord", "Someone")
        self.assertFalse(self.memory.known("discord", "Someone").they_started)

    def test_forgotten_contact_cannot_be_restored_by_close_list(self):
        self.memory.person("discord", "Someone")
        self.memory.forget("discord", "Someone")
        self.rt.config["close_friends"] = {"discord": ["Someone"]}
        self.assertEqual(self.rt.standing("discord", "Someone").tier(0.5), "never")
        self.rt.feel("friend_ignored", "discord", "Someone")
        self.assertIsNone(self.memory.known("discord", "Someone"))

    def test_stop_predicate_is_live_and_resume_preserves_other_interrupt(self):
        self.assertFalse(self.check_stop())
        control.stop(self.home)
        self.assertTrue(self.check_stop())
        self.rt.watch_tick()
        self.assertTrue(self.rt.interrupt.is_set())
        self.rt.interrupt.set("an actual incoming call")
        control.resume(self.home)
        self.rt.watch_tick()
        self.assertEqual(self.rt.interrupt.reason, "an actual incoming call")

    def test_preview_blocks_native_voice_without_blocking_planning(self):
        self.rt.executor.dry_run = True
        self.assertTrue(self.check_stop())
        self.assertFalse(self.rt.admission_blocked())
        self.rt.executor.dry_run = False
        self.assertFalse(self.check_stop())

    def test_blocked_voice_cleanup_cannot_delay_game_cleanup(self):
        release, entered, game = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def blocked():
            entered.set()
            release.wait(2)
        self.voice.stop = blocked
        self.rt.track_activity("game", game.set)
        control.stop(self.home)
        self.rt.stop()
        self.assertTrue(entered.wait(1) and game.wait(1))
        self.assertIn("voice", self.rt.stop_status()["pending"])
        for _ in range(5):
            self.rt.stop()
        self.assertEqual(self.rt.stop_status()["pending"].count("voice"), 1)
        release.set()

    def test_resume_waits_for_pending_old_cleanup(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def blocked():
            entered.set()
            release.wait(2)
            completed.set()
        self.voice.stop = blocked
        control.stop(self.home)
        self.rt.watch_tick()
        self.assertTrue(entered.wait(1))
        control.resume(self.home)
        self.rt.watch_tick()
        self.assertTrue(self.rt.admission_blocked())
        self.assertTrue(self.check_stop())
        self.assertEqual(self.rt.interrupt.reason, "owner STOP")
        release.set()
        self.assertTrue(completed.wait(1))

    def test_cleanup_failure_and_full_disk_do_not_skip_other_channels(self):
        game = threading.Event()
        def fail():
            raise RuntimeError("fixture")
        self.voice.stop = fail
        self.rt.track_activity("game", game.set)
        with patch.object(control, "log_action", side_effect=OSError("full disk")):
            self.rt.stop()
            self.assertTrue(game.wait(1))

    def test_stale_unregister_cannot_remove_replacement(self):
        old, replacement = lambda: None, lambda: None
        self.rt.track_activity("game", old)
        self.rt.track_activity("game", replacement)
        self.rt.untrack_activity("game", old)
        self.assertIs(self.rt._activity_stops["game"], replacement)


if __name__ == "__main__":
    unittest.main(verbosity=2)
