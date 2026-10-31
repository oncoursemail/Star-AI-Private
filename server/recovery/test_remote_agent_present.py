import os
import unittest

if os.name == 'nt':  # fcntl, /proc and process groups: this code runs only on the Linux hosts
    raise unittest.SkipTest('Linux-only recovery module')

import errno
from pathlib import Path
import tempfile
from unittest import mock

import remote_agent_present as helper

SCRIPT = "/home/star/app/node_modules/@wonderwhy-er/desktop-commander/dist/index.js"


class MatcherTests(unittest.TestCase):
    def test_remote_host_and_bin_entry_match(self):
        self.assertTrue(helper.matches_remote(["/usr/bin/node", SCRIPT, "remote"]))
        self.assertTrue(helper.matches_remote(["node", "--trace-warnings", SCRIPT, "remote", "--port", "1234"]))
        self.assertTrue(helper.matches_remote(["node", "/home/star/app/node_modules/.bin/desktop-commander", "remote"]))

    def test_stdio_and_inexact_entries_do_not_match(self):
        for argv in (
            ["node", SCRIPT], ["node", SCRIPT, "stdio"], ["node", SCRIPT, "--mode", "remote"],
            ["node", SCRIPT + ".fake", "remote"], ["node", "/tmp/unrelated/index.js", "remote"],
            ["node", "node_modules/@wonderwhy-er/desktop-commander/dist/index.js", "remote"],
            ["sh", "-c", SCRIPT + " remote"], [], ["node"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(helper.matches_remote(argv))


class ProcInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def process(self, pid, args, executable="/usr/bin/node"):
        folder = self.root / str(pid)
        folder.mkdir()
        (folder / "exe").symlink_to(executable)
        (folder / "cmdline").write_bytes(b"\0".join(os.fsencode(a) for a in args) + b"\0")
        return folder

    def test_detects_only_actual_remote_host_pid(self):
        self.process(103, ["node", SCRIPT])
        self.process(101, ["node", SCRIPT, "remote"])
        self.process(102, ["python3", SCRIPT, "remote"], "/usr/bin/python3")
        (self.root / "self").mkdir()
        self.assertEqual(helper.inspect(self.root), ([101], False))

    def test_other_uid_is_not_counted(self):
        self.process(101, ["node", SCRIPT, "remote"])
        self.assertEqual(helper.inspect(self.root, uid=os.getuid() + 10000), ([], False))

    def test_gone_process_is_a_normal_race(self):
        folder = self.process(101, ["node", SCRIPT, "remote"])
        (folder / "cmdline").unlink()
        self.assertEqual(helper.inspect(self.root), ([], False))

    def test_permission_failure_is_inconclusive(self):
        self.process(101, ["node", SCRIPT, "remote"])
        with mock.patch.object(helper.os, "readlink", side_effect=PermissionError(errno.EACCES, "private")):
            self.assertEqual(helper.inspect(self.root), ([], True))

    def test_unreadable_executable_for_noncandidate_is_irrelevant(self):
        for pid, argv in enumerate((
            ["/usr/lib/systemd/systemd", "--user"], ["(sd-pam)"],
            ["/usr/bin/gpg-agent", "--daemon"], ["node", SCRIPT],
        ), 101):
            self.process(pid, argv)
        with mock.patch.object(helper.os, "readlink", side_effect=PermissionError(errno.EACCES, "private")) as readlink:
            self.assertEqual(helper.inspect(self.root), ([], False))
            readlink.assert_not_called()

    def test_known_host_still_wins_over_other_inconclusive_process(self):
        self.process(101, ["node", SCRIPT, "remote"])
        self.process(102, ["node", "x" * 70000])
        self.assertEqual(helper.inspect(self.root), ([101], True))

    def test_executable_replaced_on_disk_still_detected(self):
        self.process(101, ["node", SCRIPT, "remote"], "/usr/bin/node (deleted)")
        self.assertEqual(helper.inspect(self.root), ([101], False))

    def test_proc_enumeration_failure_is_inconclusive(self):
        self.assertEqual(helper.inspect(self.root / "missing"), ([], True))

    def test_same_uid_identity_is_rechecked(self):
        self.process(101, ["node", SCRIPT, "remote"])
        with mock.patch.object(helper.os, "fstat", side_effect=[mock.Mock(st_uid=os.getuid()), mock.Mock(st_uid=os.getuid() + 1)]):
            self.assertEqual(helper.inspect(self.root), ([], False))


if __name__ == "__main__":
    unittest.main()
