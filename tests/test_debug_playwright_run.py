"""Real Node subprocess checks with a tiny local CLI double, without a browser."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import pytest


NODE = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE") or shutil.which("node")
RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "debug_playwright_run.cjs"
pytestmark = pytest.mark.skipif(not NODE, reason="Node is required for Playwright runner subprocess tests")

CLI_DOUBLE = r"""
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const args = process.argv.slice(2);
fs.writeFileSync('observed-argv.json', JSON.stringify(args));
const reporterArg = args[args.indexOf('--reporter') + 1];
const Reporter = require(reporterArg.slice('line,'.length));
const mode = process.env.RUNNER_TEST_MODE || 'pass';
const output = process.env.STAR_DEBUG_REPORT;
if (mode === 'missing') { fs.unlinkSync(output); process.exit(0); }
if (mode === 'pending') process.exit(0);
if (mode === 'invalid') { fs.writeFileSync(output, '{}'); process.exit(0); }
const source = path.join(process.cwd(), 'example.spec.js');
fs.writeFileSync(source, 'test("example", async () => {});\n');
const specimen = {title: 'example', titlePath: () => ['', 'chromium', 'example.spec.js', 'example'],
  location: {file: source, line: 1, column: 1}, repeatEachIndex: 0, expectedStatus: 'passed',
  parent: {project: () => ({name: 'chromium'})}};
const reporter = new Reporter();
reporter.onBegin({rootDir: process.cwd()}, {allTests: () => [specimen]});
if (mode === 'timeout' || mode === 'timeout-leader-exits' || mode === 'interrupted') {
  const descendant = require('node:child_process').spawn(process.execPath, ['-e',
    "process.on('SIGTERM', () => {}); process.send('ready'); setInterval(() => {}, 1000)"],
    {stdio: ['ignore', 'ignore', 'ignore', 'ipc']});
  fs.writeFileSync('descendant-pid', String(descendant.pid));
  descendant.once('message', () => fs.writeFileSync('child-ready', String(process.pid)));
  process.on('SIGTERM', () => { if (mode === 'timeout-leader-exits') process.exit(0); });
  process.on('SIGINT', () => {});
  setInterval(() => {}, 1000);
} else {
  const failed = mode === 'fail' || mode === 'flaky';
  const row = {status: failed ? 'failed' : 'passed', retry: 0, duration: 1,
    errors: failed ? [{message: 'Expected ready; password=a'}] : [], attachments: []};
  reporter.onTestEnd(specimen, row);
  if (mode === 'flaky') reporter.onTestEnd(specimen, {...row, status: 'passed', retry: 1, errors: []});
  reporter.onEnd({status: mode === 'fail' ? 'failed' : 'passed', duration: 2});
  if (mode === 'stale-id') {
    const report = JSON.parse(fs.readFileSync(output));
    report.run_id = 'old-run';
    fs.writeFileSync(output, JSON.stringify(report));
  }
  if (mode === 'stale-time') fs.utimesSync(output, new Date(1000), new Date(1000));
  if (mode === 'no-identity') {
    const report = JSON.parse(fs.readFileSync(output));
    delete report.tests[0].identity_sha256;
    fs.writeFileSync(output, JSON.stringify(report));
  }
  if (mode === 'oversized') {
    const report = JSON.parse(fs.readFileSync(output));
    report.padding = 'x'.repeat(2000001);
    fs.writeFileSync(output, JSON.stringify(report));
  }
  if (mode === 'invalid-harness') {
    const report = JSON.parse(fs.readFileSync(output));
    report.harness_hashes = {'playwright.config.ts': 'invalid'};
    fs.writeFileSync(output, JSON.stringify(report));
  }
  process.exit(mode === 'fail' ? 1 : mode === 'exit-mismatch' ? 7 : 0);
}
"""


def make_local_cli(tmp_path: Path) -> None:
    package = tmp_path / "node_modules" / "@playwright" / "test"
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": "@playwright/test", "version": "synthetic", "bin": {"playwright": "cli.cjs"}}),
        encoding="utf-8",
    )
    (package / "cli.cjs").write_text(CLI_DOUBLE, encoding="utf-8")


def environment(mode: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("STAR_DEBUG_REPORT", "STAR_DEBUG_RUN_ID", "STAR_DEBUG_ROOT"):
        env.pop(name, None)
    env["RUNNER_TEST_MODE"] = mode
    return env


def command(*args: str, timeout: int = 5000) -> list[str]:
    return [str(NODE), str(RUNNER), "--output", "artifacts/evidence.json", "--timeout-ms", str(timeout),
            "--", *(args or ("example.spec.js",))]


def invoke(tmp_path: Path, mode: str = "pass", *args: str, timeout: int = 5000) -> tuple[subprocess.CompletedProcess, dict]:
    completed = subprocess.run(command(*args, timeout=timeout), cwd=tmp_path, env=environment(mode),
                               text=True, capture_output=True, timeout=12, check=False)
    report = json.loads((tmp_path / "artifacts" / "evidence.json").read_text(encoding="utf-8"))
    return completed, report


@pytest.mark.parametrize(("mode", "exit_code", "status", "wrapper_code"), [
    ("pass", 0, "passed", 0), ("fail", 1, "failed", 1),
    ("exit-mismatch", 7, "failed", 7), ("flaky", 0, "failed", 1),
])
def test_observed_process_exit_and_failed_retry_are_truthful(
    tmp_path: Path, mode: str, exit_code: int, status: str, wrapper_code: int
) -> None:
    make_local_cli(tmp_path)
    completed, report = invoke(tmp_path, mode)
    assert completed.returncode == wrapper_code, completed.stderr
    assert report["status"] == status
    assert report["exit_code"] == exit_code
    assert report["runner"]["capture"] == "fresh"
    assert report["runner"]["reason"] == "process_exited"
    assert len(report["tests"][0]["identity_sha256"]) == 64
    assert report["tests"][0]["file"] == "example.spec.js"
    assert "password=a" not in json.dumps(report)


@pytest.mark.parametrize("mode", ["missing", "pending", "invalid", "stale-id", "stale-time", "no-identity", "oversized", "invalid-harness"])
def test_missing_stale_or_invalid_capture_never_passes(tmp_path: Path, mode: str) -> None:
    make_local_cli(tmp_path)
    completed, report = invoke(tmp_path, mode)
    assert completed.returncode == 2
    assert report["status"] == "incomplete"
    assert report["exit_code"] == 0
    assert report["tests"] == []
    assert report["runner"]["capture"] == "missing_or_invalid"
    assert report["run_id"] != "old-run"


def test_arguments_reach_child_literally_without_shell(tmp_path: Path) -> None:
    make_local_cli(tmp_path)
    literal = 'literal; touch shell-injection-marker; $(touch shell-substitution-marker)'
    completed, report = invoke(tmp_path, "pass", "--grep", literal, "example.spec.js")
    assert completed.returncode == 0
    args = json.loads((tmp_path / "observed-argv.json").read_text())
    assert args[0] == "test"
    assert args[-3:] == ["--grep", literal, "example.spec.js"]
    assert not (tmp_path / "shell-injection-marker").exists()
    assert not (tmp_path / "shell-substitution-marker").exists()
    assert literal not in json.dumps(report)


@pytest.mark.parametrize("argument", ["--reporter=json", "--reporter", "--list", "--ui", "--debug", "--update-snapshots", "-u"])
def test_disallowed_modes_do_not_launch_child(tmp_path: Path, argument: str) -> None:
    make_local_cli(tmp_path)
    completed = subprocess.run(command(argument), cwd=tmp_path, env=environment("pass"),
                               text=True, capture_output=True, timeout=10, check=False)
    assert completed.returncode == 2
    assert not (tmp_path / "observed-argv.json").exists()
    assert not (tmp_path / "artifacts" / "evidence.json").exists()


def test_no_local_cli_never_falls_back_to_global_install(tmp_path: Path) -> None:
    completed, report = invoke(tmp_path)
    assert completed.returncode == 2
    assert report["status"] == "incomplete"
    assert report["runner"]["reason"] == "local_cli_unavailable"
    assert "exit_code" not in report


def test_existing_report_is_replaced_with_a_new_run_identity(tmp_path: Path) -> None:
    make_local_cli(tmp_path)
    first, baseline = invoke(tmp_path, "fail")
    second, candidate = invoke(tmp_path, "pass")
    assert first.returncode == 1 and second.returncode == 0
    assert baseline["run_id"] != candidate["run_id"]
    assert baseline["tests"][0]["identity_sha256"] == candidate["tests"][0]["identity_sha256"]


@pytest.mark.parametrize("mode", [
    "timeout",
    pytest.param("timeout-leader-exits", marks=pytest.mark.skipif(os.name == "nt", reason="POSIX leader exits on SIGTERM")),
])
def test_timeout_terminates_unresponsive_child_and_descendant(tmp_path: Path, mode: str) -> None:
    make_local_cli(tmp_path)
    completed, report = invoke(tmp_path, mode, timeout=1000)
    assert completed.returncode == 124
    assert report["status"] == "incomplete"
    assert report["runner"]["reason"] == "timeout"
    if os.name == "nt":
        assert report["runner"]["cleanup"] == "taskkill_confirmed"
    else:
        assert report["runner"]["cleanup"] in {"process_group_sigkill_sent", "process_group_absent"}
        if mode == "timeout-leader-exits":
            assert report["exit_code"] == 0
        else:
            assert report["runner"]["signal"] == "SIGKILL"
            assert "exit_code" not in report
    assert report["runner"]["duration_ms"] < 5000
    assert (tmp_path / "child-ready").exists(), "Descendant did not register its signal handler before timeout"
    descendant = (tmp_path / "descendant-pid").read_text()
    check = subprocess.run([str(NODE), "-e", r"""
const fs = require('node:fs');
const pid = Number(process.argv[1]);
let alive = false;
try { process.kill(pid, 0); alive = true; } catch (error) { if (error.code !== 'ESRCH') throw error; }
if (alive && process.platform === 'linux') {
  // A terminated orphan may remain briefly as a zombie before PID 1 reaps it.
  try { if (/\) Z /.test(fs.readFileSync('/proc/' + pid + '/stat', 'utf8'))) alive = false; } catch {}
}
// Cleanup the specifically tracked fixture descendant if a regression left it
// alive, while preserving a failing test result.
if (alive) process.kill(pid, 'SIGKILL');
process.exitCode = alive ? 1 : 0;
""", descendant], text=True, capture_output=True, timeout=5, check=False)
    assert check.returncode == 0, "Runner left its child process tree alive: " + check.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal forwarding test")
def test_interruption_remains_incomplete(tmp_path: Path) -> None:
    make_local_cli(tmp_path)
    child = subprocess.Popen(command(), cwd=tmp_path, env=environment("interrupted"),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "child-ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "child-ready").exists(), "Child failed to become ready"
        child.send_signal(signal.SIGTERM)
        _, stderr = child.communicate(timeout=8)
        assert child.returncode == 143, stderr
        report = json.loads((tmp_path / "artifacts" / "evidence.json").read_text())
        assert report["status"] == "incomplete"
        assert report["runner"]["reason"] == "terminated"
        assert "exit_code" not in report
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


@pytest.mark.parametrize("symlink", [False, True])
def test_unrelated_files_and_symlinks_are_not_overwritten(tmp_path: Path, symlink: bool) -> None:
    make_local_cli(tmp_path)
    directory = tmp_path / "artifacts"
    directory.mkdir()
    target = tmp_path / "important.json"
    target.write_text('{"keep": true}', encoding="utf-8")
    output = directory / "evidence.json"
    if symlink:
        try:
            output.symlink_to(target)
        except OSError as error:
            pytest.skip(f"Symlinks unavailable: {error}")
    else:
        output.write_text(target.read_text(), encoding="utf-8")
    completed = subprocess.run(command(), cwd=tmp_path, env=environment("pass"),
                               text=True, capture_output=True, timeout=10, check=False)
    assert completed.returncode == 2
    assert target.read_text() == '{"keep": true}'
    assert output.read_text() == '{"keep": true}'
    assert not (tmp_path / "observed-argv.json").exists()
