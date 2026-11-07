"""Synthetic contract tests: these do not claim a real browser was exercised."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE") or shutil.which("node")
REPORTER = Path(__file__).resolve().parents[1] / "scripts" / "debug_playwright_reporter.cjs"
pytestmark = pytest.mark.skipif(not NODE, reason="Node is needed for the standalone Playwright reporter")

PRELUDE = r"""
const Reporter = require(process.argv[1]);
const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const root = process.argv[2];
const output = path.join(root, 'evidence.json');
const file = path.join(root, 'smoke.spec.ts');
const source = 'test("smoke", async () => {});\n';
fs.writeFileSync(file, source);
function specimen({project = 'chromium', repeat = 0, expected = 'passed', title = 'smoke', filename = file} = {}) {
  return { title, titlePath: () => ['', project, 'smoke.spec.ts', 'group', title],
    parent: { project: () => ({name: project}) },
    location: {file: filename, line: 1, column: 1}, repeatEachIndex: repeat, expectedStatus: expected };
}
function result(status = 'passed', retry = 0, extra = {}) {
  return {status, retry, duration: 12, errors: [], attachments: [], ...extra};
}
function begin(reporter, tests) {
  reporter.onBegin({rootDir: root, version: 'synthetic-1'}, {allTests: () => tests});
}
function finish(reporter, status = 'passed', extra = {}) {
  reporter.onEnd({status, duration: 42, ...extra});
  return JSON.parse(fs.readFileSync(output, 'utf8'));
}
"""


def run_node(tmp_path: Path, script: str) -> dict | list:
    env = os.environ.copy()
    env.pop("STAR_DEBUG_REPORT", None)
    env.pop("STAR_DEBUG_RUN_ID", None)
    env.pop("STAR_DEBUG_ROOT", None)
    completed = subprocess.run(
        [str(NODE), "-e", PRELUDE + "\n" + script, str(REPORTER), str(tmp_path)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_disabled_reporter_performs_no_report_io(tmp_path: Path) -> None:
    data = run_node(tmp_path, r"""
const reporter = new Reporter();
const hostile = new Proxy({}, {get() { throw new Error('Disabled reporter inspected input'); }});
reporter.onBegin(hostile, hostile);
reporter.onTestEnd(hostile, hostile);
reporter.onError(hostile);
reporter.onEnd(hostile);
reporter.onExit();
console.log(JSON.stringify({exists: fs.existsSync(output), exported: Reporter === Reporter.Reporter}));
""")
    assert data == {"exists": False, "exported": True}


def test_environment_opt_in_initial_incomplete_and_source_hash(tmp_path: Path) -> None:
    data = run_node(tmp_path, r"""
process.env.STAR_DEBUG_REPORT = output;
process.env.STAR_DEBUG_RUN_ID = 'synthetic-run-1';
process.env.SHOULD_NEVER_APPEAR = 'environment-secret';
const reporter = new Reporter();
const test = specimen();
begin(reporter, [test]);
const initial = JSON.parse(fs.readFileSync(output, 'utf8'));
reporter.onTestEnd(test, result());
console.log(JSON.stringify({initial, final: finish(reporter)}));
""")
    assert data["initial"]["status"] == "incomplete"
    report = data["final"]
    assert report["schema"] == "star-debug-evidence-v1"
    assert report["producer"] == "playwright"
    assert report["run_id"] == "synthetic-run-1"
    assert report["status"] == "passed"
    assert report["truncated"] is False
    assert report["duration_ms"] == 42
    assert "exit_code" not in report
    assert report["tests"][0]["file"] == "smoke.spec.ts"
    assert report["tests"][0]["line"] == 1
    assert report["tests"][0]["duration_ms"] == 12
    assert report["test_hashes"]["smoke.spec.ts"] == hashlib.sha256((tmp_path / "smoke.spec.ts").read_bytes()).hexdigest()
    assert "environment-secret" not in json.dumps(report)


def test_nodeids_stable_across_runs_and_distinguish_projects_and_repeats(tmp_path: Path) -> None:
    data = run_node(tmp_path, r"""
const cases = [specimen(), specimen({project: 'firefox'}), specimen({repeat: 1})];
const reports = [];
for (const order of [cases, [...cases].reverse()]) {
  const reporter = new Reporter({outputFile: output});
  begin(reporter, order);
  for (const test of order) reporter.onTestEnd(test, result());
  reports.push(finish(reporter));
}
console.log(JSON.stringify(reports));
""")
    first = [test["nodeid"] for test in data[0]["tests"]]
    second = [test["nodeid"] for test in data[1]["tests"]]
    assert first == second
    assert len(set(first)) == 3
    assert len({test["identity_sha256"] for test in data[0]["tests"]}) == 3
    assert [test["identity_sha256"] for test in data[0]["tests"]] == [test["identity_sha256"] for test in data[1]["tests"]]
    assert data[0]["run_id"] != data[1]["run_id"]


@pytest.mark.parametrize("mutation", ["unchanged", "changed", "removed", "missing"])
def test_explicit_config_is_fingerprinted_and_must_remain_unchanged(tmp_path: Path, mutation: str) -> None:
    report = run_node(tmp_path, r"""
const mode = %s;
const configFile = path.join(root, 'playwright.config.ts');
const original = 'export default { retries: 0 };\n';
if (mode !== 'missing') fs.writeFileSync(configFile, original);
const reporter = new Reporter({outputFile: output});
const test = specimen();
reporter.onBegin({rootDir: root, configFile}, {allTests: () => [test]});
if (mode === 'changed') fs.writeFileSync(configFile, 'export default { retries: 10 };\n');
if (mode === 'removed') fs.unlinkSync(configFile);
reporter.onTestEnd(test, result());
console.log(JSON.stringify(finish(reporter)));
""" % json.dumps(mutation))
    if mutation == "missing":
        assert report["harness_hashes"] == {}
    else:
        original_hash = hashlib.sha256(b"export default { retries: 0 };\n").hexdigest()
        assert report["harness_hashes"] == {"playwright.config.ts": original_hash}
    if mutation == "unchanged":
        assert report["status"] == "passed"
        assert report["truncated"] is False
    else:
        assert report["status"] == "incomplete"
        assert report["truncated"] is True
        kind = "harness_changed" if mutation == "changed" else "harness_hash_unavailable"
        assert any(event["kind"] == kind for event in report["diagnostics"])


def test_secret_parameter_titles_remain_distinct_after_display_redaction(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const tests = [specimen({title: 'login password=alpha'}), specimen({title: 'login password=beta'})];
const reporter = new Reporter({outputFile: output});
begin(reporter, tests);
for (const test of tests) reporter.onTestEnd(test, result());
console.log(JSON.stringify(finish(reporter)));
""")
    rows = report["tests"]
    assert rows[0]["nodeid"] == rows[1]["nodeid"]
    assert rows[0]["identity_sha256"] != rows[1]["identity_sha256"]
    assert all(len(row["identity_sha256"]) == 64 for row in rows)
    assert "alpha" not in json.dumps(report)
    assert "beta" not in json.dumps(report)
    assert report["status"] == "passed"
    assert report["summary"]["unique_tests"] == 2


def test_failed_retry_is_preserved_and_never_becomes_clean_pass(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output});
const test = specimen();
begin(reporter, [test]);
reporter.onTestEnd(test, result('failed', 0, {errors: [{message: 'Expected ready; token=q',
  stack: 'Error: Expected ready\n    at render (' + file + ':7:2)'}]}));
reporter.onTestEnd(test, result('passed', 1));
console.log(JSON.stringify(finish(reporter)));
""")
    assert report["status"] == "failed"
    assert report["summary"]["failed"] == 1
    assert report["summary"]["flaky"] == 1
    assert report["summary"]["retried"] == 1
    assert [test["outcome"] for test in report["tests"]] == ["failed", "passed"]
    assert [test["attempt"] for test in report["tests"]] == [0, 1]
    assert len({test["nodeid"] for test in report["tests"]}) == 1
    failure = report["failures"][0]
    assert "token=q" not in failure["message"]
    assert failure["frames"][0]["file"] == "smoke.spec.ts"
    assert failure["frames"][0]["line"] == 7


@pytest.mark.parametrize(
    ("raw_status", "expected", "outcome", "status"),
    [("failed", "failed", "xfailed", "passed"), ("passed", "failed", "xpassed", "failed"),
     ("skipped", "skipped", "skipped", "passed"), ("timedOut", "failed", "error", "failed")],
)
def test_expected_outcomes_and_timeouts(
    tmp_path: Path, raw_status: str, expected: str, outcome: str, status: str
) -> None:
    report = run_node(tmp_path, """
const reporter = new Reporter({outputFile: output});
const test = specimen({expected: %s});
begin(reporter, [test]);
reporter.onTestEnd(test, result(%s));
console.log(JSON.stringify(finish(reporter)));
""" % (json.dumps(expected), json.dumps(raw_status)))
    assert report["tests"][0]["outcome"] == outcome
    assert report["status"] == status


def test_browser_http_transport_console_pageerror_and_crash_capture(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const page = new EventEmitter();
const recorder = Reporter.attachPageDiagnostics(page);
page.emit('console', {type: () => 'info', text: () => 'ignored'});
page.emit('console', {type: () => 'error',
  text: () => 'password=x api_key="a b" token: q key=k aws_access_key_id=a access_key=b aws_secret_access_key=c user=alice@example.com https://u:p@example.test/api?private=secret#hidden',
  args() { throw new Error('Object arguments must never be read'); },
  location: () => ({url: 'https://u:p@example.test/app.js?token=a#b', lineNumber: 2, columnNumber: 3})});
page.emit('pageerror', new Error('client_secret=z'));
page.emit('requestfailed', {url: () => 'https://u:p@example.test/request?token=a#b', method: () => 'GET',
  failure: () => ({errorText: 'net::ERR_CONNECTION_REFUSED'}),
  headers() { throw new Error('Headers must never be read'); }});
page.emit('response', {status: () => 200, url: () => 'https://example.test/ok'});
page.emit('response', {status: () => 503, url: () => 'https://u:p@example.test/api?password=a#b',
  body() { throw new Error('Bodies must never be read'); }});
page.emit('crash');
const evidence = recorder.stop();
if (page.eventNames().length) throw new Error('Listeners leaked');
page.emit('crash');
if (recorder.stop().events.length !== evidence.events.length) throw new Error('Stop was not idempotent');
const reporter = new Reporter({outputFile: output});
const test = specimen();
begin(reporter, [test]);
reporter.onTestEnd(test, result('passed', 0, {attachments: [{name: Reporter.ATTACHMENT_NAME,
  body: Buffer.from(JSON.stringify(evidence)), contentType: 'application/json'}]}));
console.log(JSON.stringify(finish(reporter)));
""")
    events = report["diagnostics"]
    assert [event["kind"] for event in events] == ["console", "pageerror", "requestfailed", "http_error", "crash"]
    assert events[3]["status"] == 503
    assert events[3]["url"] == "https://example.test/api"
    assert events[0]["line"] == 3
    assert events[0]["column"] == 4
    text = json.dumps(events)
    for secret in ("password=x", '"a b"', "token: q", "key=k", "client_secret=z", "alice@example.com",
                   "aws_access_key_id=a", "access_key=b", "aws_secret_access_key=c",
                   "u:p@", "private=secret", "hidden", "?token", "#b"):
        assert secret not in text
    assert "password=[REDACTED]" in events[0]["message"]
    assert all(event["attempt"] == 0 and event["nodeid"] for event in events)


def test_hard_byte_cap_matches_shared_reader(tmp_path: Path) -> None:
    data = run_node(tmp_path, r"""
const page = new EventEmitter();
const recorder = Reporter.attachPageDiagnostics(page, {
  maxDiagnostics: 500, maxMessageChars: 8192, maxBytes: 3000000,
});
for (let i = 0; i < 334; i++) page.emit('pageerror', new Error('x'.repeat(6000)));
const snapshot = recorder.stop();
console.log(JSON.stringify({bytes: Buffer.byteLength(JSON.stringify(snapshot)), truncated: snapshot.truncated}));
""")
    assert data["bytes"] <= 2_000_000
    assert data["truncated"] is True


def test_helper_and_reporter_bounds_and_untrusted_attachment_properties(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const page = new EventEmitter();
const recorder = Reporter.attachPageDiagnostics(page, {maxDiagnostics: 2, maxMessageChars: 32});
for (let i = 0; i < 8; i++) page.emit('pageerror', new Error('password=x ' + 'x'.repeat(100)));
const evidence = recorder.stop();
evidence.events[0].headers = {Authorization: 'do-not-copy'};
evidence.events[0].body = 'do-not-copy-body';
const reporter = new Reporter({outputFile: output, maxDiagnostics: 1});
const test = specimen();
begin(reporter, [test]);
reporter.onTestEnd(test, result('passed', 0, {attachments: [{name: Reporter.ATTACHMENT_NAME,
  body: Buffer.from(JSON.stringify(evidence))}]}));
console.log(JSON.stringify(finish(reporter)));
""")
    assert report["truncated"] is True
    assert report["status"] == "incomplete"
    assert len(report["diagnostics"]) == 1
    assert len(report["diagnostics"][0]["message"]) <= 32
    assert report["summary"]["dropped_diagnostics"] >= 6
    assert "do-not-copy" not in json.dumps(report)


def test_count_caps_keep_observed_failure_and_total_counts(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output, maxTests: 2, maxFailures: 1});
const tests = [0, 1, 2, 3].map(i => specimen({title: 'case ' + i}));
begin(reporter, tests);
for (const test of tests) reporter.onTestEnd(test, result('failed', 0, {errors: [{message: 'assertion'}]}));
console.log(JSON.stringify(finish(reporter)));
""")
    assert report["status"] == "failed"
    assert report["truncated"] is True
    assert report["summary"]["total"] == 4
    assert report["summary"]["failed"] == 4
    assert report["summary"]["dropped_tests"] == 2
    assert report["summary"]["dropped_failures"] == 3
    assert len(report["tests"]) == 2
    assert len(report["failures"]) == 1


def test_total_byte_cap_accounts_for_utf8_and_remains_parseable(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output, maxBytes: 1024});
const test = specimen({title: '🟨'.repeat(100)});
begin(reporter, [test]);
reporter.onTestEnd(test, result('failed', 0, {errors: [{message: '🟨'.repeat(500)}]}));
console.log(JSON.stringify(finish(reporter)));
""")
    assert (tmp_path / "evidence.json").stat().st_size <= 1024
    assert report["truncated"] is True
    assert report["status"] == "failed"
    assert report["summary"]["failed"] == 1
    assert not list(tmp_path.glob(".star-debug-*.tmp"))


def test_never_overwrites_symlink_destination(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep-me", encoding="utf-8")
    try:
        (tmp_path / "evidence.json").symlink_to(victim)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    data = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output});
let blocked = false;
try { begin(reporter, [specimen()]); } catch (error) { blocked = /safely/.test(error.message); }
console.log(JSON.stringify({blocked}));
""")
    assert data["blocked"] is True
    assert victim.read_text(encoding="utf-8") == "keep-me"
    assert (tmp_path / "evidence.json").is_symlink()


def test_symlinked_test_source_is_not_read(tmp_path: Path) -> None:
    try:
        (tmp_path / "linked.spec.ts").symlink_to(tmp_path / "smoke.spec.ts")
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    report = run_node(tmp_path, r"""
const link = path.join(root, 'linked.spec.ts');
const reporter = new Reporter({outputFile: output});
const test = specimen({filename: link});
begin(reporter, [test]);
reporter.onTestEnd(test, result());
console.log(JSON.stringify(finish(reporter)));
""")
    assert report["status"] == "incomplete"
    assert report["summary"]["missing_test_hashes"] == 1
    assert report["test_hashes"] == {}


def test_source_hash_is_captured_before_test_execution(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output});
const test = specimen();
begin(reporter, [test]);
fs.writeFileSync(file, 'changed during execution');
reporter.onTestEnd(test, result());
console.log(JSON.stringify(finish(reporter)));
""")
    original = b'test("smoke", async () => {});\n'
    assert report["test_hashes"]["smoke.spec.ts"] == hashlib.sha256(original).hexdigest()


def test_incomplete_missing_test_and_global_runner_error(tmp_path: Path) -> None:
    data = run_node(tmp_path, r"""
const tests = [specimen(), specimen({title: 'never ran'})];
const reporter = new Reporter({outputFile: output});
begin(reporter, tests);
reporter.onTestEnd(tests[0], result());
const incomplete = finish(reporter);
const failedReporter = new Reporter({outputFile: output});
begin(failedReporter, []);
failedReporter.onError({message: 'worker died with password=q'});
const error = finish(failedReporter, 'failed', {exitCode: 3});
console.log(JSON.stringify({incomplete, error}));
""")
    assert data["incomplete"]["status"] == "incomplete"
    assert data["error"]["status"] == "error"
    assert data["error"]["exit_code"] == 3
    assert data["error"]["failures"][0]["phase"] == "runner"
    assert "password=q" not in json.dumps(data)


def test_exit_without_on_end_writes_incomplete_report(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output});
const test = specimen();
begin(reporter, [test]);
reporter.onTestEnd(test, result());
reporter.onExit();
console.log(fs.readFileSync(output, 'utf8'));
""")
    assert report["status"] == "incomplete"


def test_bad_browser_attachment_is_incomplete_without_raw_contents(tmp_path: Path) -> None:
    report = run_node(tmp_path, r"""
const reporter = new Reporter({outputFile: output});
const test = specimen();
begin(reporter, [test]);
reporter.onTestEnd(test, result('passed', 0, {attachments: [{name: Reporter.ATTACHMENT_NAME,
  body: Buffer.from('password=untrusted-malformed-json')}]}));
console.log(JSON.stringify(finish(reporter)));
""")
    assert report["status"] == "incomplete"
    assert report["diagnostics"][0]["kind"] == "attachment_error"
    assert "untrusted-malformed-json" not in json.dumps(report)
