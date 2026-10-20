#!/usr/bin/env node
'use strict';

// Developer-invoked only. Playwright tests/config are trusted executable code;
// this runner is neither a sandbox nor an authentication/independent test gate.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { _io } = require('./debug_playwright_reporter.cjs');

class RunnerError extends Error {}

const MAX_BYTES = 2000000;
const STATUSES = new Set(['passed', 'failed', 'incomplete', 'error']);
const OUTCOMES = new Set(['passed', 'failed', 'skipped', 'xfailed', 'xpassed', 'error']);
const DIGEST = /^[a-f0-9]{64}$/;
const USAGE = 'Usage: node scripts/debug_playwright_run.cjs --output <repo-relative.json> ' +
  '[--timeout-ms 120000] -- <trusted Playwright test/config arguments>\n';

function parseArgs(argv) {
  const separator = argv.indexOf('--');
  if (separator < 0 || separator === argv.length - 1) throw new RunnerError('Explicit Playwright arguments after -- are required.');
  let output;
  let timeout = 120000;
  for (let index = 0; index < separator; index++) {
    const name = argv[index];
    const value = argv[++index];
    if (index >= separator) throw new RunnerError('A runner option is missing its value.');
    if (name === '--output' && !output) output = value;
    else if (name === '--timeout-ms' && /^\d+$/.test(value)) timeout = Number(value);
    else throw new RunnerError('Unknown or duplicate runner option.');
  }
  if (!output || output.includes('\0') || path.extname(output).toLowerCase() !== '.json') {
    throw new RunnerError('An explicit .json evidence output is required.');
  }
  if (!Number.isSafeInteger(timeout) || timeout < 100 || timeout > 1800000) {
    throw new RunnerError('The runner timeout must be between 100 and 1800000 ms.');
  }
  const args = argv.slice(separator + 1);
  const blocked = /^(?:--(?:reporter|ui(?:-.*)?|debug|help|version|list(?:-.*)?|update-snapshots)(?:=|$)|-[huV]$)/;
  if (args.length > 256 || args.some((arg) => arg.length > 8192 || arg.includes('\0') || arg === '--' || blocked.test(arg))) {
    throw new RunnerError('Reporter overrides, listing, interactive modes, and snapshot updates are not evidence runs.');
  }
  return { output, timeout, args };
}

function readJSON(filename, maxBytes = MAX_BYTES) {
  _io.noSymlinkParents(path.dirname(filename), false);
  _io.checkDestination(filename);
  const descriptor = fs.openSync(filename, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const stat = fs.fstatSync(descriptor);
    if (!stat.isFile() || stat.size > maxBytes) throw new RunnerError('Evidence is not a bounded regular file.');
    const buffer = Buffer.alloc(maxBytes + 1);
    let size = 0;
    while (size < buffer.length) {
      const count = fs.readSync(descriptor, buffer, size, buffer.length - size, size);
      if (!count) break;
      size += count;
    }
    if (size > maxBytes) throw new RunnerError('Evidence exceeds its byte limit.');
    return { value: JSON.parse(buffer.subarray(0, size).toString('utf8')), stat };
  } finally { fs.closeSync(descriptor); }
}

function localCLI(root) {
  // No PATH/npx/global/ancestor resolution, installation, or remote fallback.
  const candidates = ['node_modules/@playwright/test', 'node_modules/playwright',
    'frontend/node_modules/@playwright/test', 'frontend/node_modules/playwright'];
  for (const relative of candidates) {
    const directory = path.join(root, relative);
    const manifest = path.join(directory, 'package.json');
    if (!fs.existsSync(manifest)) continue;
    const realDirectory = fs.realpathSync(directory);
    if (!_io.inside(root, realDirectory)) throw new RunnerError('The local Playwright installation resolves outside this repository.');
    const packageInfo = readJSON(path.join(realDirectory, 'package.json'), 65536).value;
    if (!['@playwright/test', 'playwright'].includes(packageInfo.name)) throw new RunnerError('Unexpected local Playwright package.');
    const entry = typeof packageInfo.bin === 'string' ? packageInfo.bin : packageInfo.bin && packageInfo.bin.playwright;
    if (typeof entry !== 'string') throw new RunnerError('The local Playwright package has no CLI.');
    const cli = fs.realpathSync(path.resolve(realDirectory, entry));
    if (!_io.inside(root, cli) || !fs.statSync(cli).isFile()) throw new RunnerError('Unsafe local Playwright CLI path.');
    return cli;
  }
  throw new RunnerError('Install Playwright in this repository or its frontend directory before invoking this runner.');
}

function emptyReport(runId, reason, elapsed = 0) {
  return { schema: 'star-debug-evidence-v1', producer: 'playwright', run_id: runId,
    status: 'incomplete', duration_ms: Math.max(0, Math.min(elapsed, 31536000000)), truncated: true,
    summary: { total: 0, passed: 0, failed: 0, skipped: 0, xfailed: 0, xpassed: 0, error: 0 },
    tests: [], failures: [], test_hashes: {}, harness_hashes: {},
    environment: { node: process.version, platform: process.platform, arch: process.arch }, diagnostics: [],
    runner: { producer: 'star-playwright-runner-v1', reason } };
}

function validateReport(value, runId) {
  const object = (item) => !!item && typeof item === 'object' && !Array.isArray(item);
  const count = (item) => Number.isInteger(item) && item >= 0 && item <= 1e12;
  const text = (item, max) => typeof item === 'string' && item.length <= max;
  if (!object(value) || value.schema !== 'star-debug-evidence-v1' || value.producer !== 'playwright' ||
      value.run_id !== runId || value.runner || !STATUSES.has(value.status) || typeof value.truncated !== 'boolean' ||
      !Number.isFinite(value.duration_ms) || value.duration_ms < 0 || value.duration_ms > 31536000000 ||
      !object(value.summary) || !Object.values(value.summary).every(count) || !object(value.environment) ||
      !object(value.test_hashes) || (value.harness_hashes !== undefined && !object(value.harness_hashes)) ||
      !Array.isArray(value.tests) || value.tests.length > 5000 ||
      !Array.isArray(value.failures) || value.failures.length > 1000 ||
      !Array.isArray(value.diagnostics) || value.diagnostics.length > 2000) return false;
  for (const row of value.tests) {
    if (!object(row) || !text(row.nodeid, 2000) || !row.nodeid || !DIGEST.test(row.identity_sha256 || '') ||
        !OUTCOMES.has(row.outcome) || !text(row.file, 1024) || !count(row.line) || !count(row.attempt) ||
        !Number.isFinite(row.duration_ms) || row.duration_ms < 0 || row.duration_ms > 31536000000) return false;
  }
  for (const hashes of [value.test_hashes, value.harness_hashes || {}]) {
    for (const [file, digest] of Object.entries(hashes)) {
      if (!file || file.length > 1024 || path.isAbsolute(file) || file.split(/[\\/]/).includes('..') || !DIGEST.test(digest)) return false;
    }
  }
  // Keep this a format/freshness check. Repository code can write this file;
  // run identity ties observations together but is not a security signature.
  return true;
}

function writeReport(output, report) {
  const encoded = JSON.stringify(report) + '\n';
  if (Buffer.byteLength(encoded) > MAX_BYTES) throw new RunnerError('Finalized evidence exceeds its byte limit.');
  _io.atomicWrite(output, encoded);
}

function execute(cli, args, options) {
  return new Promise((resolve) => {
    let child;
    let reason = null;
    let stopped = false;
    let termination;
    let forced;
    let cutoff;
    let treeCleanup;
    let groupCleanup = 'not_requested';
    const windowsTreeKill = () => {
      if (treeCleanup) return;
      treeCleanup = new Promise((done) => {
        const systemRoot = process.env.SystemRoot;
        if (!systemRoot || !path.isAbsolute(systemRoot)) { done(false); return; }
        const executable = path.join(systemRoot, 'System32', 'taskkill.exe');
        let killer;
        let deadline;
        let completed = false;
        const complete = (success) => {
          if (completed) return;
          completed = true;
          clearTimeout(deadline);
          if (killer) killer.unref();
          done(success);
        };
        try {
          // Fixed executable and argv, only our still-tracked child PID. /T
          // includes browser/worker descendants; no shell or process matching.
          killer = spawn(executable, ['/PID', String(child.pid), '/T', '/F'], {
            shell: false, windowsHide: true, stdio: 'ignore',
          });
          killer.once('error', () => complete(false));
          killer.once('close', (code) => complete(code === 0));
          deadline = setTimeout(() => {
            try { killer.kill(); } catch { /* completion remains unverified */ }
            complete(false);
          }, 2000);
        } catch { complete(false); }
      });
    };
    const signalChild = (signal) => {
      if (!child || !child.pid) return;
      try {
        if (process.platform === 'win32') {
          if (child.exitCode !== null || child.signalCode !== null) return;
          windowsTreeKill();
          // A direct forced kill is only a fallback if taskkill fails. The
          // report will explicitly retain an unverified tree-cleanup outcome.
          if (signal === 'SIGKILL') child.kill(signal);
        }
        else {
          // The private process group can outlive its launcher. Keep targeting
          // that group through shutdown even after the leader has exited.
          process.kill(-child.pid, signal);
          groupCleanup = signal === 'SIGKILL' ? 'process_group_sigkill_sent' : 'process_group_signaled';
        }
      } catch (error) {
        if (process.platform !== 'win32') {
          groupCleanup = error.code === 'ESRCH' ? 'process_group_absent' : 'unverified';
        }
        if (error.code !== 'ESRCH') reason = reason || 'termination_error';
      }
    };
    const stop = (why, signal = 'SIGTERM') => {
      if (reason) return;
      reason = why;
      signalChild(signal);
      // The process group belongs to this invocation. Bound shutdown as well
      // as execution; a child cannot keep capture open indefinitely.
      forced = setTimeout(() => signalChild('SIGKILL'), 1500);
      cutoff = setTimeout(() => finish(null, signal), 3000);
    };
    const onInterrupt = () => stop('interrupted', 'SIGINT');
    const onTerminate = () => stop('terminated', 'SIGTERM');
    const finish = async (code, signal) => {
      if (stopped) return;
      stopped = true;
      // A launcher may honor SIGTERM while a descendant ignores it. Finish
      // group shutdown before canceling the grace timer on the leader's close.
      if (reason && process.platform !== 'win32') signalChild('SIGKILL');
      clearTimeout(termination);
      clearTimeout(forced);
      clearTimeout(cutoff);
      process.removeListener('SIGINT', onInterrupt);
      process.removeListener('SIGTERM', onTerminate);
      if (child) child.unref();
      const cleanup = treeCleanup ? await treeCleanup ? 'taskkill_confirmed' : 'unverified' :
        groupCleanup;
      resolve({ code: Number.isInteger(code) ? code : null, signal: signal || null, reason, cleanup });
    };
    process.on('SIGINT', onInterrupt);
    process.on('SIGTERM', onTerminate);
    try {
      child = spawn(process.execPath, [cli, 'test', '--reporter', 'line,' + path.join(__dirname, 'debug_playwright_reporter.cjs'), ...args], {
        cwd: options.root, env: { ...process.env, STAR_DEBUG_REPORT: options.output,
          STAR_DEBUG_RUN_ID: options.runId, STAR_DEBUG_ROOT: options.root },
        shell: false, stdio: 'inherit', detached: process.platform !== 'win32',
      });
      child.once('error', () => { reason = reason || 'spawn_error'; finish(null, null); });
      child.once('close', finish);
      termination = setTimeout(() => stop('timeout'), options.timeout);
    } catch {
      reason = 'spawn_error';
      finish(null, null);
    }
  });
}

async function run(options) {
  const root = fs.realpathSync(process.cwd());
  const output = path.resolve(root, options.output);
  if (!_io.inside(root, output) || path.extname(output).toLowerCase() !== '.json') {
    throw new RunnerError('Evidence output must be a .json file inside the current repository.');
  }
  if (__dirname.includes(',')) throw new RunnerError('The runner path cannot contain a comma.');
  _io.noSymlinkParents(path.dirname(output), true);
  _io.checkDestination(output);
  if (fs.existsSync(output)) {
    const old = readJSON(output).value;
    if (!old || old.schema !== 'star-debug-evidence-v1' || old.producer !== 'playwright') {
      throw new RunnerError('Refusing to overwrite an unrelated JSON file.');
    }
  }
  const runId = crypto.randomUUID();
  const started = Date.now();
  writeReport(output, emptyReport(runId, 'awaiting_reporter'));
  let observed;
  try {
    observed = await execute(localCLI(root), options.args, { ...options, root, output, runId });
  } catch {
    observed = { code: null, signal: null, reason: 'local_cli_unavailable' };
  }
  const elapsed = Date.now() - started;
  let report;
  let capture = 'fresh';
  try {
    const loaded = readJSON(output);
    if (loaded.stat.mtimeMs + 2000 < started || !validateReport(loaded.value, runId)) throw new RunnerError('Capture mismatch.');
    report = loaded.value;
  } catch {
    capture = 'missing_or_invalid';
    report = emptyReport(runId, observed.reason || 'missing_or_invalid_capture', elapsed);
  }
  if (observed.reason || observed.signal || observed.code === null) report.status = 'incomplete';
  else if (report.status === 'passed') {
    if (report.tests.some((row) => ['failed', 'xpassed', 'error'].includes(row.outcome)) || observed.code !== 0) report.status = 'failed';
    else if (report.truncated || report.tests.length === 0) report.status = 'incomplete';
  }
  if (observed.code !== null) report.exit_code = observed.code;
  else delete report.exit_code;
  report.runner = { producer: 'star-playwright-runner-v1', capture,
    reason: observed.reason || (observed.signal ? 'signal' : capture === 'fresh' ? 'process_exited' : 'missing_or_invalid_capture'),
    duration_ms: Math.min(elapsed, 31536000000), cleanup: observed.cleanup || 'not_requested' };
  if (observed.signal) report.runner.signal = observed.signal;
  if (Buffer.byteLength(JSON.stringify(report) + '\n') > MAX_BYTES) {
    const metadata = report.runner;
    report = emptyReport(runId, 'finalization_limit', elapsed);
    report.runner = { ...metadata, reason: 'finalization_limit' };
    if (observed.code !== null) report.exit_code = observed.code;
  }
  writeReport(output, report);
  if (observed.reason === 'timeout') return 124;
  if (observed.reason === 'interrupted' || observed.signal === 'SIGINT') return 130;
  if (observed.reason === 'terminated' || observed.signal === 'SIGTERM') return 143;
  if (observed.code !== null && observed.code !== 0) return observed.code;
  if (report.status === 'passed') return 0;
  return report.status === 'failed' || report.status === 'error' ? 1 : 2;
}

if (require.main === module) {
  (async () => {
    try {
      const code = await run(parseArgs(process.argv.slice(2)));
      process.exitCode = code;
      if (code !== 0) process.stderr.write('STAR Playwright evidence is not a clean completed pass; inspect the configured report.\n');
    } catch (error) {
      const message = error instanceof RunnerError ? error.message : 'The evidence path or local installation could not be used safely.';
      process.stderr.write('STAR Playwright runner: ' + message + '\n' + USAGE);
      process.exitCode = 2;
    }
  })();
}

module.exports = { parseArgs, run };
