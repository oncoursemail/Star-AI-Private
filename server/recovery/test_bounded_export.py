import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import bounded_export


class BoundedExportTests(unittest.TestCase):
    def command(self, code, *, max_bytes=1024, timeout=3, args=()):
        return [sys.executable, str(Path(bounded_export.__file__)), "--max-bytes", str(max_bytes),
                "--timeout-seconds", str(timeout), "--", sys.executable, "-c", code, *args]

    def run_producer(self, code, **kwargs):
        return subprocess.run(self.command(code, **kwargs), capture_output=True, timeout=8)

    def test_successful_exact_binary_payload(self):
        payload = bytes(range(256)) * 3
        result = self.run_producer("import os; os.write(1, bytes(range(256))*3)", max_bytes=len(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, payload)
        self.assertEqual(result.stderr, b"")

    def test_larger_success_respects_backpressure(self):
        result = self.run_producer("import sys; sys.stdout.buffer.write(bytes(range(256))*4096)", max_bytes=1024**2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, bytes(range(256)) * 4096)

    def test_oversized_output_fails_before_forwarding_excess(self):
        result = self.run_producer("import os; os.write(1, b'x'*1025)", max_bytes=1024)
        self.assertEqual(result.returncode, 1)
        self.assertLessEqual(len(result.stdout), 1024)
        self.assertIn(b"byte limit", result.stderr)

    def test_infinite_producer_is_stopped_by_size_bound(self):
        started = time.monotonic()
        result = self.run_producer("import os\nwhile True: os.write(1, b'x'*65536)", max_bytes=100000)
        self.assertEqual(result.returncode, 1)
        self.assertLessEqual(len(result.stdout), 100000)
        self.assertLess(time.monotonic() - started, 5)

    def test_nonzero_after_data_is_not_success_and_stderr_stays_private(self):
        result = self.run_producer("import os; os.write(1, b'partial'); os.write(2, b'SECRET-PRODUCER-ERROR'); raise SystemExit(7)")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"partial")
        self.assertNotIn(b"SECRET-PRODUCER-ERROR", result.stderr)
        self.assertIn(b"unsuccessfully", result.stderr)

    def test_stalled_output_times_out(self):
        started = time.monotonic()
        result = self.run_producer("import time; time.sleep(30)", timeout=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"deadline", result.stderr)
        self.assertLess(time.monotonic() - started, 5)

    def test_closed_stdout_without_process_exit_still_times_out(self):
        result = self.run_producer("import os,time; os.close(1); time.sleep(30)", timeout=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"deadline", result.stderr)

    def test_blocked_receiver_output_does_not_disable_timeout(self):
        command = self.command("import os\nwhile True: os.write(1,b'x'*65536)", max_bytes=100000000, timeout=1)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # Intentionally do not drain stdout until after its deadline.
            process.wait(timeout=5)
            output, errors = process.communicate(timeout=1)
            self.assertEqual(process.returncode, 1)
            self.assertIn(b"deadline", errors)
            self.assertLess(len(output), 100000000)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_sigterm_stops_term_ignoring_producer_and_grandchild(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "processes.json"
            child_marker = Path(tmp) / "child-ready"
            child_code = "import os,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(30)"
            code = (
                "import json,os,signal,subprocess,sys,time\n"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                "child=subprocess.Popen([sys.executable,'-c',sys.argv[3],sys.argv[2]])\n"
                "while not os.path.exists(sys.argv[2]): time.sleep(0.01)\n"
                "open(sys.argv[1],'w').write(json.dumps([os.getpid(),child.pid]))\n"
                "time.sleep(30)\n"
            )
            command = self.command(code, timeout=10, args=(str(marker), str(child_marker), child_code))
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pids = []
            try:
                end = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), "producer tree did not start")
                pids = json.loads(marker.read_text())
                process.send_signal(signal.SIGTERM)
                output, errors = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 1)
                self.assertEqual(output, b"")
                self.assertIn(b"interrupted", errors)
                for pid in pids:
                    info = Path(f"/proc/{pid}/stat")
                    self.assertTrue(not info.exists() or info.read_text().split()[2] == "Z", f"producer {pid} survived cleanup")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.stdout.close()
                process.stderr.close()

    def test_missing_producer_fails_without_payload(self):
        command = [sys.executable, str(Path(bounded_export.__file__)), "--max-bytes", "1024",
                   "--timeout-seconds", "1", "--", "/does-not-exist-recovery-producer"]
        result = subprocess.run(command, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
