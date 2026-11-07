'use strict';

// Optional Playwright evidence reporter. Uses only Node built-ins, and performs
// no IO unless outputFile or STAR_DEBUG_REPORT is explicitly configured.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const ATTACHMENT_NAME = 'star-browser-diagnostics';
const BROWSER_SCHEMA = 'star-browser-diagnostics-v1';

function limit(value, fallback, min, max) {
  return Number.isFinite(value) ? Math.max(min, Math.min(max, Math.floor(value))) : fallback;
}

function limits(options = {}) {
  return {
    tests: limit(options.maxTests, 500, 1, 5000),
    failures: limit(options.maxFailures, 100, 1, 1000),
    diagnostics: limit(options.maxDiagnostics, 200, 1, 2000),
    message: limit(options.maxMessageChars, 2000, 32, 8192),
    frames: limit(options.maxFrames, 10, 0, 50),
    bytes: limit(options.maxBytes, 262144, 1024, 2000000),
    sourceBytes: limit(options.maxTestFileBytes, 1048576, 1024, 8388608),
  };
}

function plain(value) {
  return typeof value === 'string' ? value : '';
}

function sanitizeUrl(value) {
  const input = plain(value).slice(0, 65536);
  if (/^data:/i.test(input)) return '[data URL]';
  try {
    const url = new URL(input.startsWith('//') ? 'https:' + input : input);
    if (!['http:', 'https:', 'ws:', 'wss:', 'ftp:', 'file:'].includes(url.protocol)) return '[URL]';
    return url.protocol + '//' + url.host + url.pathname;
  } catch {
    return input.split(/[?#]/, 1)[0];
  }
}

function redact(value) {
  let text = plain(value).replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '');
  text = text.replace(/\b(?:https?|wss?|ftp|file):\/\/[^\s<>"'`]+/gi, sanitizeUrl);
  text = text.replace(/\bdata:[^\s<>]+/gi, '[data URL]');
  text = text.replace(/\b(?:Bearer|Basic)\s+[^\s,;"'}\]]+/gi, '[REDACTED authorization]');
  // Redact values of any length, including single-character test credentials.
  const keys = '(?:api[_-]?key|(?:aws[_-]?)?(?:secret[_-]?)?access[_-]?key(?:[_-]?id)?|key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|secret|password|passwd|pwd|authorization|proxy[_-]?authorization|cookie|set[_-]?cookie|client[_-]?secret|session(?:[_-]?(?:id|token))?|csrf(?:[_-]?token)?)';
  text = text.replace(new RegExp('(["\']?\\b' + keys + '["\']?\\s*[:=]\\s*)(?:\\[REDACTED[^\\]\\r\\n]*\\]|"[^"\\r\\n]*"|\'[^\'\\r\\n]*\'|[^\\s,;}\\]]+)', 'gi'), '$1[REDACTED]');
  text = text.replace(/\b(?:set[-_]?)?cookie\s*[:=]\s*[^\r\n]*/gi, 'cookie=[REDACTED]');
  text = text.replace(/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b/g, '[REDACTED token]');
  text = text.replace(/\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|sk-[A-Za-z0-9_-]{8,})\b/g, '[REDACTED token]');
  return text.replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, '[REDACTED email]');
}

class BoundedCollector {
  constructor(options) {
    this.limits = limits(options);
    this.truncated = false;
    this.dropped = 0;
    this.events = [];
    this.started = Date.now();
  }

  text(value, max = this.limits.message) {
    const raw = plain(value);
    if (raw.length > 65536) this.truncated = true;
    const safe = redact(raw.slice(0, 65536));
    if (safe.length > max) this.truncated = true;
    return safe.slice(0, max);
  }

  add(event) {
    if (this.events.length >= this.limits.diagnostics) {
      this.truncated = true;
      this.dropped += 1;
      return;
    }
    // Explicit field selection: never serialize console arguments, headers,
    // response bodies, browser objects, or arbitrary attachment properties.
    const safe = { kind: this.text(event.kind, 80), message: this.text(event.message) };
    if (typeof event.nodeid === 'string') safe.nodeid = this.text(event.nodeid, 1200);
    if (/^[a-f0-9]{64}$/.test(event.identity_sha256 || '')) safe.identity_sha256 = event.identity_sha256;
    if (typeof event.url === 'string') {
      if (event.url.length > 65536) this.truncated = true;
      safe.url = this.text(sanitizeUrl(event.url), 2048);
    }
    if (typeof event.level === 'string') safe.level = this.text(event.level, 32);
    if (typeof event.method === 'string') safe.method = this.text(event.method, 32);
    for (const name of ['status', 'line', 'column', 'attempt', 'timestamp_ms']) {
      if (Number.isFinite(event[name])) safe[name] = Math.max(0, Math.min(1e12, event[name]));
    }
    this.events.push(safe);
  }

  snapshot() {
    const snapshot = { schema: BROWSER_SCHEMA, events: this.events.slice(), truncated: this.truncated, dropped: this.dropped };
    while (Buffer.byteLength(JSON.stringify(snapshot)) > this.limits.bytes && snapshot.events.length) {
      const count = Math.max(1, Math.ceil(snapshot.events.length / 2));
      snapshot.events.splice(-count);
      snapshot.truncated = true;
      snapshot.dropped += count;
    }
    return snapshot;
  }
}

/**
 * Collect evidence in a Playwright fixture, then attach recorder.stop() as JSON
 * using ATTACHMENT_NAME. The helper performs no filesystem or network IO.
 * Diagnostic events are evidence; assertions still define expected behavior.
 */
function attachPageDiagnostics(page, options = {}) {
  const collector = new BoundedCollector(options);
  const handlers = [];
  let stopped = false;
  const listen = (name, read) => {
    const handler = (value) => {
      try {
        const event = read(value);
        if (event) collector.add({ ...event, timestamp_ms: Date.now() - collector.started });
      } catch {
        collector.truncated = true;
        collector.add({ kind: 'collector_error', message: 'A browser event could not be read.' });
      }
    };
    page.on(name, handler);
    handlers.push([name, handler]);
  };
  listen('console', (message) => {
    const level = message.type();
    if (level !== 'error' && level !== 'warning') return null;
    const location = typeof message.location === 'function' ? message.location() : {};
    return { kind: 'console', level, message: message.text(), url: location.url,
      line: Number.isFinite(location.lineNumber) ? location.lineNumber + 1 : undefined,
      column: Number.isFinite(location.columnNumber) ? location.columnNumber + 1 : undefined };
  });
  listen('pageerror', (error) => ({ kind: 'pageerror', message: plain(error && error.message) || plain(error) }));
  listen('requestfailed', (request) => ({ kind: 'requestfailed', url: request.url(), method: request.method(),
    message: plain((request.failure() || {}).errorText) || 'Transport request failed.' }));
  listen('response', (response) => {
    const status = response.status();
    if (status < 400) return null;
    return { kind: 'http_error', status, url: response.url(), message: 'HTTP ' + status };
  });
  listen('crash', () => ({ kind: 'crash', message: 'The browser page crashed.' }));
  return {
    snapshot: () => collector.snapshot(),
    stop() {
      if (!stopped) {
        for (const [name, handler] of handlers) page.removeListener(name, handler);
        stopped = true;
      }
      return collector.snapshot();
    },
  };
}

function safeDuration(value) {
  return Number.isFinite(value) ? Math.max(0, Math.min(value, 31536000000)) : 0;
}

function inside(root, filename) {
  const relative = path.relative(root, filename);
  return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}

function noSymlinkParents(directory, create) {
  const absolute = path.resolve(directory);
  const parsed = path.parse(absolute);
  let current = parsed.root;
  for (const part of absolute.slice(parsed.root.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    let stat;
    try { stat = fs.lstatSync(current); } catch (error) {
      if (!create || error.code !== 'ENOENT') throw error;
      try { fs.mkdirSync(current, { mode: 0o700 }); } catch (mkdirError) {
        if (mkdirError.code !== 'EEXIST') throw mkdirError;
      }
      stat = fs.lstatSync(current);
    }
    if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('Unsafe evidence directory.');
  }
}

function checkDestination(filename) {
  try {
    const stat = fs.lstatSync(filename);
    if (stat.isSymbolicLink() || !stat.isFile()) throw new Error('Unsafe evidence destination.');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

function atomicWrite(filename, data) {
  const directory = path.dirname(filename);
  noSymlinkParents(directory, true);
  checkDestination(filename);
  const temporary = path.join(directory, '.star-debug-' + crypto.randomUUID() + '.tmp');
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT |
      fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW || 0), 0o600);
    fs.writeFileSync(descriptor, data, 'utf8');
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = undefined;
    noSymlinkParents(directory, false);
    checkDestination(filename);
    fs.renameSync(temporary, filename);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    try { fs.unlinkSync(temporary); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
}

class Reporter {
  constructor(options = {}) {
    this.options = options;
    this.bounds = limits(options);
    const output = options.outputFile || process.env.STAR_DEBUG_REPORT;
    this.output = typeof output === 'string' && output.trim() ? path.resolve(output) : null;
    this.collector = new BoundedCollector(options);
    const requestedRun = options.runId || process.env.STAR_DEBUG_RUN_ID;
    this.runId = typeof requestedRun === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(requestedRun)
      ? requestedRun : crypto.randomUUID();
    this.root = path.resolve(options.rootDir || process.env.STAR_DEBUG_ROOT || process.cwd());
    this.started = Date.now();
    this.finished = false;
    this.tests = [];
    this.failures = [];
    this.hashes = Object.create(null);
    this.harnessHashes = Object.create(null);
    this.harnessLocation = null;
    this.seen = new Map();
    this.hashSeen = new Set();
    this.globalError = false;
    this.unexpected = false;
    this.planned = 0;
    this.summary = { total: 0, passed: 0, failed: 0, skipped: 0, xfailed: 0, xpassed: 0,
      error: 0, retried: 0, flaky: 0, dropped_tests: 0, dropped_failures: 0, missing_test_hashes: 0,
      runner_errors: 0, dropped_test_hashes: 0, missing_harness_hashes: 0,
      changed_harness_files: 0, dropped_harness_hashes: 0 };
    this.environment = { node: process.version, platform: process.platform, arch: process.arch };
  }

  printsToStdio() { return false; }

  onBegin(config, suite) {
    if (!this.output) return;
    this.root = path.resolve(this.options.rootDir || process.env.STAR_DEBUG_ROOT || config.rootDir || process.cwd());
    this.started = Date.now();
    if (typeof config.version === 'string') this.environment.playwright = this.collector.text(config.version, 80);
    if (typeof config.configFile === 'string') {
      this.harnessLocation = this.location({ location: { file: config.configFile } });
      this.checkHarness(false);
    }
    if (suite && typeof suite.allTests === 'function') {
      const planned = suite.allTests();
      this.planned = planned.length;
      // Hash source before execution, so a test cannot rewrite its own source
      // and silently change the verification baseline during a run.
      for (const test of planned.slice(0, this.bounds.tests)) this.fingerprint(this.location(test));
    }
    // Replace a previous run's result immediately with an incomplete report.
    this.write({ status: 'interrupted', duration: 0 });
  }

  location(test) {
    const location = test.location || {};
    const absolute = typeof location.file === 'string' ? path.resolve(this.root, location.file) : null;
    const relative = absolute ? path.relative(this.root, absolute).split(path.sep).join('/') : '<unknown>';
    return { absolute, identityFile: relative, file: this.collector.text(relative, 1024),
      line: limit(location.line, 0, 0, 1e9), column: limit(location.column, 0, 0, 1e9) };
  }

  identify(test, location) {
    let suite = test.parent;
    let project = '';
    for (let depth = 0; suite && depth < 100; depth++, suite = suite.parent) {
      const candidate = typeof suite.project === 'function' ? suite.project() : null;
      if (candidate) { project = plain(candidate.name); break; }
    }
    const titles = typeof test.titlePath === 'function' ? test.titlePath().filter((item) => typeof item === 'string') : [plain(test.title)];
    const repeat = limit(test.repeatEachIndex, 0, 0, 1e9);
    // Opaque identity is computed BEFORE redaction. Redacted parameter titles
    // can be identical, and must never merge separate tests during comparison.
    const identity = JSON.stringify([project, location.identityFile, location.line, location.column, titles, repeat]);
    return { identity_sha256: crypto.createHash('sha256').update(identity).digest('hex'),
      nodeid: this.collector.text(project || 'default', 120) + '::' + location.file + ':' + location.line +
        '::' + this.collector.text(titles[titles.length - 1] || 'test', 120) + '::repeat=' + repeat };
  }

  sourceHash(location) {
    if (location.file !== location.identityFile) throw new Error('Source path requires redaction.');
    if (!location.absolute || !inside(this.root, location.absolute)) throw new Error('Source is outside root.');
    noSymlinkParents(path.dirname(location.absolute), false);
    const stat = fs.lstatSync(location.absolute);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > this.bounds.sourceBytes) throw new Error('Source is unavailable.');
    const descriptor = fs.openSync(location.absolute, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
    try {
      const opened = fs.fstatSync(descriptor);
      if (!opened.isFile() || opened.size > this.bounds.sourceBytes) throw new Error('Source is unavailable.');
      const buffer = Buffer.alloc(this.bounds.sourceBytes + 1);
      let read = 0;
      while (read < buffer.length) {
        const count = fs.readSync(descriptor, buffer, read, buffer.length - read, read);
        if (!count) break;
        read += count;
      }
      if (read > this.bounds.sourceBytes) throw new Error('Source exceeds limit.');
      return crypto.createHash('sha256').update(buffer.subarray(0, read)).digest('hex');
    } finally { fs.closeSync(descriptor); }
  }

  checkHarness(verify) {
    if (!this.harnessLocation) return;
    const location = this.harnessLocation;
    try {
      const digest = this.sourceHash(location);
      if (!verify) this.harnessHashes[location.file] = digest;
      else if (digest !== this.harnessHashes[location.file]) {
        this.summary.changed_harness_files += 1;
        this.collector.truncated = true;
        this.collector.add({ kind: 'harness_changed', message: 'Playwright configuration changed during this run: ' + location.file });
      }
    } catch {
      this.summary.missing_harness_hashes += 1;
      this.collector.truncated = true;
      this.collector.add({ kind: 'harness_hash_unavailable', message: 'Playwright configuration could not be fingerprinted: ' + location.file });
    }
  }

  fingerprint(location) {
    if (!location.absolute || this.hashSeen.has(location.identityFile)) return;
    if (this.hashSeen.size >= this.bounds.tests) { this.collector.truncated = true; return; }
    this.hashSeen.add(location.identityFile);
    try {
      this.hashes[location.file] = this.sourceHash(location);
    } catch {
      this.summary.missing_test_hashes += 1;
      this.collector.truncated = true;
      this.collector.add({ kind: 'source_hash_unavailable', message: 'Test source could not be fingerprinted: ' + location.file });
    }
  }

  frames(error) {
    const stack = this.collector.text(error && error.stack, 16000);
    const frames = [];
    for (const row of stack.split('\n').slice(1)) {
      const trimmed = row.trim();
      let match = trimmed.match(/^at\s+(.*?)\s+\((.+):(\d+):(\d+)\)$/);
      if (!match) {
        const bare = trimmed.match(/^at\s+(.+):(\d+):(\d+)$/);
        if (bare) match = [bare[0], '', bare[1], bare[2], bare[3]];
      }
      if (!match) match = trimmed.match(/^(.*?)@(.+):(\d+):(\d+)$/);
      if (!match) continue;
      if (frames.length >= this.bounds.frames) { this.collector.truncated = true; break; }
      let file = match[2].trim();
      if (path.isAbsolute(file)) file = path.relative(this.root, file).split(path.sep).join('/');
      frames.push({ function: this.collector.text(match[1] || '', 160), file: this.collector.text(file, 1024),
        line: Number(match[3]), column: Number(match[4]) });
    }
    return frames;
  }

  failure(nodeid, error, location, category, phase = 'test', attempt, identity_sha256) {
    if (this.failures.length >= this.bounds.failures) {
      this.summary.dropped_failures += 1;
      this.collector.truncated = true;
      return;
    }
    const source = error && error.location && typeof error.location.file === 'string'
      ? this.location({location: error.location}) : location;
    const fallback = category === 'unexpected_pass' ? 'A test expected to fail passed unexpectedly.' : 'Test failed without an error message.';
    const failure = { nodeid, category, phase,
      message: this.collector.text(error && (error.message || error.value) || fallback),
      file: source.file, line: source.line, frames: this.frames(error) };
    if (Number.isInteger(attempt)) failure.attempt = attempt;
    if (identity_sha256) failure.identity_sha256 = identity_sha256;
    this.failures.push(failure);
  }

  consumeAttachments(result, nodeid, attempt, identity_sha256) {
    const attachments = Array.isArray(result.attachments) ? result.attachments : [];
    if (attachments.length > 100) this.collector.truncated = true;
    for (const attachment of attachments.slice(0, 100)) {
      if (!attachment || typeof attachment !== 'object') continue;
      if (attachment.name !== ATTACHMENT_NAME) continue;
      try {
        const body = attachment.body;
        if (!(Buffer.isBuffer(body) || typeof body === 'string') || Buffer.byteLength(body) > this.bounds.bytes) {
          throw new Error('Unavailable or oversized diagnostic attachment.');
        }
        const data = JSON.parse(Buffer.isBuffer(body) ? body.toString('utf8') : body);
        if (data.schema !== BROWSER_SCHEMA || !Array.isArray(data.events)) throw new Error('Invalid diagnostic attachment.');
        if (data.truncated || data.events.length > this.bounds.diagnostics) this.collector.truncated = true;
        if (data.events.length > this.bounds.diagnostics) this.collector.dropped += data.events.length - this.bounds.diagnostics;
        for (const event of data.events.slice(0, this.bounds.diagnostics)) {
          if (event && typeof event === 'object') this.collector.add({ ...event, nodeid, attempt, identity_sha256 });
        }
        if (Number.isSafeInteger(data.dropped) && data.dropped > 0) this.collector.dropped += Math.min(data.dropped, 1e9);
      } catch {
        this.collector.truncated = true;
        this.collector.add({ kind: 'attachment_error', nodeid, attempt, identity_sha256,
          message: 'Browser diagnostics were unavailable or invalid.' });
      }
    }
  }

  onTestEnd(test, result) {
    if (!this.output) return;
    const location = this.location(test);
    const { nodeid, identity_sha256 } = this.identify(test, location);
    const attempt = limit(result.retry, 0, 0, 1000000);
    let outcome;
    if (result.status === 'passed') outcome = test.expectedStatus === 'failed' ? 'xpassed' : 'passed';
    else if (result.status === 'failed') outcome = test.expectedStatus === 'failed' ? 'xfailed' : 'failed';
    else if (result.status === 'skipped') outcome = 'skipped';
    else outcome = 'error';
    this.summary.total += 1;
    this.summary[outcome] += 1;
    if (attempt > 0) this.summary.retried += 1;
    const unexpected = ['failed', 'xpassed', 'error'].includes(outcome);
    if (unexpected) this.unexpected = true;
    const prior = this.seen.get(identity_sha256);
    if (prior) {
      if (prior.failed && outcome === 'passed' && !prior.flaky) { this.summary.flaky += 1; prior.flaky = true; }
      prior.failed = prior.failed || unexpected;
    } else if (this.seen.size < this.bounds.tests) {
      this.seen.set(identity_sha256, { failed: unexpected, flaky: false });
    } else this.collector.truncated = true;
    if (this.tests.length < this.bounds.tests) {
      this.tests.push({ nodeid, identity_sha256, outcome, file: location.file, line: location.line,
        duration_ms: safeDuration(result.duration), attempt });
    } else { this.summary.dropped_tests += 1; this.collector.truncated = true; }
    this.fingerprint(location);
    if (unexpected) {
      const errors = Array.isArray(result.errors) && result.errors.length ? result.errors : [result.error || {}];
      const category = outcome === 'xpassed' ? 'unexpected_pass' : result.status === 'timedOut' ? 'timeout' :
        result.status === 'interrupted' ? 'interrupted' : 'test_failure';
      for (const error of errors.slice(0, this.bounds.failures)) {
        this.failure(nodeid, error, location, category, 'test', attempt, identity_sha256);
      }
      if (errors.length > this.bounds.failures) this.collector.truncated = true;
    }
    this.consumeAttachments(result, nodeid, attempt, identity_sha256);
  }

  onError(error) {
    if (!this.output) return;
    this.globalError = true;
    this.summary.runner_errors += 1;
    this.failure('playwright::runner', error, { file: '<runner>', line: 0 }, 'runner_error', 'runner');
  }

  report(result) {
    let status;
    if (this.globalError) status = 'error';
    else if (result.status !== 'passed' && result.status !== 'failed') status = 'incomplete';
    else if (this.unexpected || result.status === 'failed') status = 'failed';
    else if (result.status !== 'passed' || this.summary.total === 0 || this.collector.truncated ||
      this.planned > this.seen.size) status = 'incomplete';
    else status = 'passed';
    const report = { schema: 'star-debug-evidence-v1', producer: 'playwright', run_id: this.runId,
      status, duration_ms: safeDuration(result.duration ?? Date.now() - this.started),
      truncated: this.collector.truncated, summary: { ...this.summary, planned: this.planned,
        unique_tests: this.seen.size, dropped_diagnostics: this.collector.dropped },
      tests: this.tests.slice().sort((a, b) => a.identity_sha256.localeCompare(b.identity_sha256) || a.attempt - b.attempt),
      failures: this.failures.slice(), test_hashes: { ...this.hashes },
      harness_hashes: { ...this.harnessHashes }, environment: { ...this.environment },
      diagnostics: this.collector.events.slice() };
    // Playwright FullResult does not normally contain an exit code. Never infer
    // a successful process exit from an intermediate reporter callback.
    if (Number.isInteger(result.exitCode)) report.exit_code = result.exitCode;
    return report;
  }

  write(result) {
    const report = this.report(result);
    let encoded = JSON.stringify(report) + '\n';
    while (Buffer.byteLength(encoded) > this.bounds.bytes) {
      report.truncated = true;
      if (report.status === 'passed') report.status = 'incomplete';
      let shortened = false;
      for (const [name, counter] of [['diagnostics', 'dropped_diagnostics'], ['failures', 'dropped_failures'], ['tests', 'dropped_tests']]) {
        if (report[name].length) {
          const count = Math.max(1, Math.ceil(report[name].length / 2));
          report[name].splice(-count);
          report.summary[counter] += count;
          shortened = true;
          break;
        }
      }
      if (!shortened) {
        for (const [field, counter] of [['test_hashes', 'dropped_test_hashes'], ['harness_hashes', 'dropped_harness_hashes']]) {
          const names = Object.keys(report[field]);
          if (!names.length) continue;
          const count = Math.max(1, Math.ceil(names.length / 2));
          for (const name of names.slice(-count)) delete report[field][name];
          report.summary[counter] += count;
          shortened = true;
          break;
        }
        if (!shortened) throw new Error('STAR evidence byte limit is smaller than its required metadata.');
      }
      encoded = JSON.stringify(report) + '\n';
    }
    try { atomicWrite(this.output, encoded); } catch {
      throw new Error('STAR debugging evidence could not be written safely.');
    }
  }

  onEnd(result) {
    if (!this.output) return;
    this.checkHarness(true);
    this.write(result);
    this.finished = true;
  }

  onExit() {
    if (this.output && !this.finished) this.write({ status: 'interrupted', duration: Date.now() - this.started });
  }
}

module.exports = Reporter;
module.exports.Reporter = Reporter;
module.exports.attachPageDiagnostics = attachPageDiagnostics;
module.exports.ATTACHMENT_NAME = ATTACHMENT_NAME;
// Shared only with the developer-invoked runner; this is not a model tool API.
module.exports._io = Object.freeze({ atomicWrite, checkDestination, inside, noSymlinkParents });
