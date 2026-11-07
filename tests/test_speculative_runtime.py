"""Offline regression tests for opt-in llama.cpp n-gram speculation.

These tests validate CLI construction only. They do not benchmark actual hardware.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from star.local_runtime import Runtime


class SpeculativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.exe = self.folder / "llama-server.exe"
        self.exe.write_bytes(b"test executable")
        self.model = self.folder / "test.gguf"
        self.model.write_bytes(b"x" * 100_100)

    def flags(self, **kwargs):
        return Runtime.arguments(self.exe, self.model, **kwargs)

    def test_existing_default_cli_is_unchanged(self):
        args = self.flags()
        self.assertNotIn("--spec-type", args)
        self.assertNotIn("--spec-draft-n-max", args)
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertEqual(args.count("--jinja"), 1)

    def test_ngram_mode_is_explicitly_opt_in(self):
        args = self.flags(speculative="ngram-simple")
        self.assertEqual(args[-4:],
                         ["--spec-type", "ngram-simple", "--spec-draft-n-max", "16"])

    def test_draft_length_can_be_tuned_within_bounds(self):
        for tokens in (4, 8, 32, 64):
            with self.subTest(tokens=tokens):
                self.assertEqual(self.flags(speculative="ngram-simple",
                                            max_draft_tokens=tokens)[-1], str(tokens))

    def test_mode_is_strictly_allowlisted(self):
        for bad in ("draft", "ngram-mod", "", "--shell", True, None, 1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.flags(speculative=bad)

    def test_draft_length_is_strictly_bounded(self):
        for bad in (-1, 0, 3, 65, True, 16.0, "16", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.flags(speculative="ngram-simple", max_draft_tokens=bad)

    def test_validation_applies_even_when_mode_off(self):
        with self.assertRaises(ValueError):
            self.flags(speculative="off", max_draft_tokens=True)

    def test_no_executable_or_model_bypass(self):
        other = self.exe.with_name("other.exe")
        other.write_bytes(b"test executable")
        with self.assertRaises(ValueError):
            Runtime.arguments(other, self.model, speculative="ngram-simple")
        with self.assertRaises(ValueError):
            Runtime.arguments(self.exe, self.exe, speculative="ngram-simple")

    def test_router_default_off(self):
        with patch("star.local_runtime.inspect_models_dir",
                   return_value=SimpleNamespace(directory=self.folder)):
            args = Runtime.router_arguments(self.exe, self.folder)
        self.assertNotIn("--spec-type", args)
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertEqual(args[args.index("--models-max") + 1], "1")

    def test_router_opt_in(self):
        with patch("star.local_runtime.inspect_models_dir",
                   return_value=SimpleNamespace(directory=self.folder)):
            args = Runtime.router_arguments(self.exe, self.folder,
                                            speculative="ngram-simple",
                                            max_draft_tokens=24)
        self.assertEqual(args[-4:],
                         ["--spec-type", "ngram-simple", "--spec-draft-n-max", "24"])

    def test_single_runtime_forwards_mode_without_shell(self):
        runtime = Runtime()
        with patch("star.local_runtime.subprocess.Popen") as spawn:
            spawn.return_value.pid = 9001
            try:
                self.assertEqual(runtime.start(self.exe, self.model, self.folder / "local.log",
                                               speculative="ngram-simple"), 9001)
                args, kwargs = spawn.call_args
                self.assertEqual(args[0][-4:],
                                 ["--spec-type", "ngram-simple", "--spec-draft-n-max", "16"])
                self.assertNotIn("shell", kwargs)
            finally:
                runtime._close_log()

    def test_router_runtime_forwards_mode_without_shell(self):
        runtime = Runtime()
        with patch("star.local_runtime.inspect_models_dir",
                   return_value=SimpleNamespace(directory=self.folder)), patch(
                       "star.local_runtime.subprocess.Popen") as spawn:
            spawn.return_value.pid = 9002
            try:
                self.assertEqual(runtime.start_router(self.exe, self.folder,
                                                      self.folder / "router.log",
                                                      speculative="ngram-simple",
                                                      max_draft_tokens=8), 9002)
                args, kwargs = spawn.call_args
                self.assertEqual(args[0][-4:],
                                 ["--spec-type", "ngram-simple", "--spec-draft-n-max", "8"])
                self.assertNotIn("shell", kwargs)
            finally:
                runtime._close_log()

    def test_bad_mode_never_spawns_process(self):
        runtime = Runtime()
        with patch("star.local_runtime.subprocess.Popen") as spawn:
            with self.assertRaises(ValueError):
                runtime.start(self.exe, self.model, self.folder / "denied.log",
                              speculative="ngram-cache")
            spawn.assert_not_called()
            runtime._close_log()


if __name__ == "__main__":
    unittest.main()
