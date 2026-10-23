#!/usr/bin/env python3
"""Pull-only encrypted backups. Never restores over production or deletes a baseline."""
from __future__ import annotations

import argparse
from contextlib import closing
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".status-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def directory_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def cleanup_restore_staging(parent):
    """Called under the operation lock: remove only this program's abandoned exports."""
    for path in Path(parent).iterdir():
        if not re.fullmatch(r"restore-check-[a-z0-9_]{8}", path.name):
            continue
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Unexpected object in restore staging namespace")
        shutil.rmtree(path)


def run_command(command, *, timeout, env, output=None):
    """A deadline kills the entire child group, including the SSH/export child."""
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(command, stdout=output or subprocess.PIPE,
                                stderr=errors, env=env, start_new_session=True)
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except BaseException as error:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                # Also stop descendants if the direct child exited first.
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                proc.wait()
                if proc.stdout is not None:
                    proc.stdout.close()
            if isinstance(error, subprocess.TimeoutExpired):
                raise RuntimeError("Backup command exceeded its deadline") from None
            raise
        if proc.returncode != 0:
            # Keep credentials and application output out of status files.
            errors.seek(0)
            hint = errors.read(2048).decode("utf-8", "replace").strip()
            print("recovery: command failed: " + hint, file=sys.stderr)
            raise RuntimeError("Backup command failed with exit code " + str(proc.returncode))
        return (stdout or b"").decode("utf-8")


def validate_archive(archive, target, max_bytes, expected_sources=None):
    """Extract to a fresh private directory; verify every member against its manifest."""
    target = Path(target)
    target.mkdir(mode=0o700)
    observed, manifest, used, seen = {}, None, 0, set()
    with tarfile.open(archive, "r:") as stream:
        for entry in stream:
            name = entry.name.rstrip("/") if entry.isdir() else entry.name
            parts = name.split("/")
            if (PurePosixPath(name).is_absolute() or "\\" in name
                    or any(part in ("", ".", "..") for part in parts)
                    or not (entry.isfile() or entry.isdir()) or entry.issparse()
                    or name in seen or len(seen) >= 200000):
                raise ValueError("Unsafe or duplicate archive member")
            seen.add(name)
            if entry.isdir():
                if entry.size != 0 or name == "RECOVERY_MANIFEST.json":
                    raise ValueError("Unsafe archive directory")
                target.joinpath(*parts).mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            used += entry.size
            if entry.size < 0 or used > max_bytes or (name == "RECOVERY_MANIFEST.json" and entry.size > 16 * 1024**2):
                raise ValueError("Archive exceeds verification size limit")
            incoming = stream.extractfile(entry)
            if incoming is None:
                raise ValueError("Missing member data")
            if name == "RECOVERY_MANIFEST.json":
                manifest = json.load(incoming)
                continue
            dest = target.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest, count = hashlib.sha256(), 0
            with dest.open("xb") as outgoing:
                while chunk := incoming.read(1024**2):
                    digest.update(chunk)
                    outgoing.write(chunk)
                    count += len(chunk)
            dest.chmod(0o600)
            observed[name] = {"size": count, "sha256": digest.hexdigest()}
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Missing or unsupported recovery manifest")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Empty recovery manifest")
    indexed = {item["path"]: item for item in entries}
    if len(indexed) != len(entries) or set(indexed) != set(observed):
        raise ValueError("Manifest does not describe exactly the restored files")
    if expected_sources is not None and set(manifest.get("source_names", [])) != set(expected_sources):
        raise ValueError("Required source list changed")
    sqlite_count = 0
    for name, metadata in observed.items():
        item = indexed[name]
        if metadata["size"] != item["size"] or metadata["sha256"] != item["sha256"]:
            raise ValueError("Restored file checksum mismatch")
        if item.get("sqlite"):
            uri = target.joinpath(*name.split("/")).as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                deadline = time.monotonic() + 300
                db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Restored SQLite integrity check failed")
            sqlite_count += 1
    if manifest.get("total_bytes") != sum(item["size"] for item in observed.values()):
        raise ValueError("Manifest total size mismatch")
    return {"files": len(observed), "sqlite_databases": sqlite_count,
            "source_bytes": manifest["total_bytes"], "source_names": manifest.get("source_names", [])}


class Backup:
    def __init__(self, config):
        self.cfg = config
        rolling = Path(config["repository"]).resolve()
        baseline = Path(config["baseline_repository"]).resolve()
        if rolling.is_relative_to(baseline) or baseline.is_relative_to(rolling):
            raise ValueError("Rolling and baseline repositories must be distinct and disjoint")
        if Path(config["password_file"]).resolve() == Path(config["baseline_password_file"]).resolve():
            raise ValueError("Rolling and baseline password files must be separate")
        self.state_path = Path(config["state_file"])
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.env = os.environ.copy()
        # Do not inherit a caller's unrelated restic backend or password variables.
        for key in list(self.env):
            if key.startswith("RESTIC_"):
                del self.env[key]
        self.env["GOMAXPROCS"] = "2"
        self.env["RESTIC_CACHE_DIR"] = config["cache_dir"]
        self.timeout = config.get("timeout_seconds", 1200)

    def save(self):
        atomic_json(self.state_path, self.state)

    def call(self, *args, baseline=False, output=None):
        prefix = "baseline_" if baseline else ""
        cmd = [self.cfg["restic"], "--repo", self.cfg[prefix + "repository"],
               "--password-file", self.cfg[prefix + "password_file"], *args]
        return run_command(cmd, timeout=self.timeout, env=self.env, output=output)

    def initialize(self, baseline=False):
        prefix = "baseline_" if baseline else ""
        repo = Path(self.cfg[prefix + "repository"])
        password = Path(self.cfg[prefix + "password_file"])
        if (repo / "config").exists():
            if not password.is_file():
                raise RuntimeError("Existing repository password is missing; refusing to replace it")
            self.call("cat", "config", baseline=baseline)
            return
        if repo.exists() and any(repo.iterdir()):
            raise RuntimeError("Refusing to initialize a nonempty repository directory")
        repo.mkdir(parents=True, exist_ok=True, mode=0o700)
        password.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not password.exists():
            fd = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(48) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(password.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        args = ["init", "--repository-version", "2"]
        if baseline:
            args += ["--from-repo", self.cfg["repository"], "--from-password-file",
                     self.cfg["password_file"], "--copy-chunker-params"]
        self.call(*args, baseline=baseline)

    def space_check(self, multiplier=1):
        parent = Path(self.cfg["repository"]).parent
        reserve = self.cfg.get("min_free_bytes", 20 * 1024**3)
        needed = multiplier * self.cfg.get("max_export_bytes", 3 * 1024**3)
        if shutil.disk_usage(parent).free < reserve + needed:
            raise RuntimeError("Insufficient free space; existing recovery points preserved")
        total = directory_bytes(self.cfg["repository"]) + directory_bytes(self.cfg["baseline_repository"])
        if total > self.cfg.get("max_repository_bytes", 20 * 1024**3):
            raise RuntimeError("Backup size budget reached; baseline preserved")

    def backup(self):
        self.state.update(last_attempt_utc=utc_now(), latest_complete=False, in_progress=True)
        self.save()
        self.space_check()
        # Default unlock only removes locks restic itself judges stale. Never --remove-all.
        self.call("unlock")
        result = self.call("backup", "--json", "--compression", "max", "--host", self.cfg["workload"],
                           "--tag", "recovery:" + self.cfg["workload"], "--stdin-filename", "recovery.tar",
                           "--stdin-from-command", "--", *self.cfg["export_command"])
        messages = [json.loads(line) for line in result.splitlines() if line.startswith("{")]
        summary = next((item for item in reversed(messages) if item.get("message_type") == "summary"), None)
        if not summary or not summary.get("snapshot_id"):
            raise RuntimeError("Successful command did not report a snapshot")
        self.call("check")
        self.state.update(last_success_utc=utc_now(), last_snapshot_id=summary["snapshot_id"],
                          last_error=None, latest_complete=True, in_progress=False,
                          data_added=summary.get("data_added"), data_added_packed=summary.get("data_added_packed"),
                          repository_bytes=directory_bytes(self.cfg["repository"]))
        self.save()
        return summary["snapshot_id"]

    def verify(self, snapshot, baseline=False):
        self.space_check(2)
        self.call("unlock", baseline=baseline)
        self.call("check", "--read-data", baseline=baseline)
        scratch = Path(self.cfg["state_file"]).parent
        with tempfile.TemporaryDirectory(prefix="restore-check-", dir=scratch) as name:
            root = Path(name)
            archive = root / "recovery.tar"
            with archive.open("xb") as stream:
                self.call("dump", snapshot, "recovery.tar", baseline=baseline, output=stream)
            result = validate_archive(archive, root / "restored", self.cfg.get("max_export_bytes", 3 * 1024**3),
                                      self.cfg.get("expected_sources"))
        result.update(verified_utc=utc_now(), snapshot=snapshot,
                      application_boot_tested=False, clean_world_validated=False)
        self.state["baseline_verification" if baseline else "last_restore_verification"] = result
        self.save()
        return result

    def baseline(self):
        recorded = self.state.get("baseline_snapshot_id") or self.state.get("baseline_verification", {}).get("snapshot")
        if recorded and not (Path(self.cfg["baseline_repository"]) / "config").is_file():
            raise RuntimeError("Recorded baseline repository is missing; refusing to replace it")
        self.initialize(baseline=True)
        snapshots = json.loads(self.call("snapshots", "--json", baseline=True))
        if recorded and (len(snapshots) != 1 or snapshots[0]["id"] != recorded):
            raise RuntimeError("Recorded baseline identity changed; refusing to replace it")
        if snapshots:
            if len(snapshots) != 1:
                raise RuntimeError("Unexpected baseline snapshots; refusing automatic modification")
            snapshot = snapshots[0]["id"]
        else:
            source = self.state.get("last_snapshot_id")
            if not source or not self.state.get("latest_complete"):
                raise RuntimeError("A successful backup is required before baseline creation")
            self.verify(source)
            self.call("copy", "--from-repo", self.cfg["repository"], "--from-password-file",
                      self.cfg["password_file"], source, baseline=True)
            snapshots = json.loads(self.call("snapshots", "--json", baseline=True))
            if len(snapshots) != 1:
                raise RuntimeError("Baseline copy did not yield one snapshot")
            snapshot = snapshots[0]["id"]
        result = self.verify(snapshot, baseline=True)
        self.state["baseline_snapshot_id"] = snapshot
        self.save()
        return result

    def retention(self):
        if not self.state.get("baseline_verification") or not self.state.get("latest_complete"):
            raise RuntimeError("Retention requires a verified baseline and successful latest backup")
        success = dt.datetime.fromisoformat(self.state["last_success_utc"])
        if (dt.datetime.now(dt.timezone.utc) - success).total_seconds() > 3 * 3600:
            raise RuntimeError("Latest backup is stale; retention suspended")
        baseline = json.loads(self.call("snapshots", "--json", baseline=True))
        if len(baseline) != 1 or baseline[0]["id"] != self.state["baseline_snapshot_id"]:
            raise RuntimeError("Protected baseline identity changed; retention suspended")
        snapshots = json.loads(self.call("snapshots", "--json"))
        now = dt.datetime.now(dt.timezone.utc)
        for item in snapshots:
            timestamp = dt.datetime.fromisoformat(item["time"].replace("Z", "+00:00"))
            if timestamp > now + dt.timedelta(minutes=5) or item.get("hostname") != self.cfg["workload"]:
                raise RuntimeError("Unexpected snapshot identity/time; retention suspended")
        if len(snapshots) > 500:
            raise RuntimeError("Unexpected snapshot count; retention suspended")
        self.call("check")
        # The baseline is in another repository. This command cannot rotate it.
        self.call("forget", "--host", self.cfg["workload"], "--tag", "recovery:" + self.cfg["workload"],
                  "--keep-within", "2d", "--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "2")
        self.call("prune", "--max-repack-size", "128M", "--max-unused", "10%")
        self.call("check")
        self.state["last_retention_utc"] = utc_now()
        self.save()


def main():
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("action", choices=["init", "backup", "verify", "baseline", "retention", "status"])
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    os.umask(0o077)
    worker = Backup(config)
    lock_path = worker.state_path.with_suffix(".lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another recovery operation is running", file=sys.stderr)
            return 1
        # Construction may have raced an operation that finished just before this lock.
        # Only state loaded while holding the lock may be used or written back.
        worker.state = json.loads(worker.state_path.read_text()) if worker.state_path.exists() else {}
        try:
            cleanup_restore_staging(worker.state_path.parent)
            if args.action == "init":
                worker.initialize()
                result = {"repository_initialized": True}
            elif args.action == "backup":
                result = {"snapshot": worker.backup()}
            elif args.action == "verify":
                result = worker.verify(worker.state["last_snapshot_id"])
            elif args.action == "baseline":
                result = worker.baseline()
            elif args.action == "retention":
                worker.retention()
                result = {"retention_completed": True}
            else:
                result = worker.state
            print(json.dumps(result))
            return 0
        except Exception as error:
            worker.state["last_error"] = {"at": utc_now(), "action": args.action, "type": type(error).__name__,
                                          "message": str(error)[:500]}
            if args.action == "backup":
                worker.state["latest_complete"] = False
                worker.state["in_progress"] = False
            worker.save()
            print("Recovery operation failed: " + str(error), file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
