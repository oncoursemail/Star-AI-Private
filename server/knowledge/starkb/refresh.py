"""Nightly refresh: pull the documentation repositories, rebuild the index, embed what changed,
check retrieval on the 30 development questions and append one dated line to a report file.

Safety rules:
  * it waits while the server's quiet lock exists (before it starts and before each stage) and
    gives up, without touching anything, if the lock is still there after `max_wait` seconds;
  * every repository is FETCHED first; only if all fetches succeed are the checkouts moved. A
    failed fetch ends the run with the index and the checkouts exactly as they were;
  * the rebuild is one transaction and is refused if it would shrink the index by more than
    20 % (store.build); the checkouts are then put back to the commits the index was built from;
  * when no repository changed, nothing is rebuilt; only the retrieval check runs.
The report line always gets written, whatever happened.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

from .quiet import Stopper, lock_held, wait_while_locked
from .store import RebuildRefused, build, connect

REPORT_NAME = "refresh-report.log"
# Most texts the nightly refresh embeds on this machine (0 = all). A bulk change (a new corpus) is left for a GPU
# machine (offload.py) instead of slowing chat for days; the daily Roblox docs changes (tens of texts) fit easily, and
# pending texts are taken in index order, so the Roblox sources come first.
EMBED_LIMIT = int(os.environ.get("STAR_KB_REFRESH_EMBED_LIMIT", "0"))


def _git(repo: Path, *args: str, timeout: float = 600) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed in {repo.name}: {(done.stderr or done.stdout).strip()[-200:]}")
    return done.stdout.strip()


class QuietTimeout(RuntimeError):
    """The lock prevented a refresh stage or source fetch from starting."""


def wait_for_quiet(max_wait: float, stop, log) -> bool:
    waited = wait_while_locked(log=log, stop=stop, poll=15, max_wait=max_wait, held=lock_held)
    return waited is not None and not stop()


def fetch_all(sources_dir: Path, config: dict, git=_git, *, wait=None) -> list[dict]:
    """Fetch every source without moving any checkout. Raises RuntimeError if one fetch fails."""
    found = []
    seen: set[str] = set()
    for source in config["sources"]:
        if source.get("kind", "git") != "git":
            continue        # fetched pages (fetch_pages.py) are refreshed by their own job, not by git
        checkout = source.get("checkout", source["name"])
        if checkout in seen:
            continue        # two sources (licences) in one checkout: fetched once
        seen.add(checkout)
        if wait is not None and not wait():
            raise QuietTimeout("server lock held during repository fetch")
        repo = sources_dir / checkout
        if not (repo / ".git").is_dir():
            raise RuntimeError(f"no checkout for {source['name']} (run fetch.sh once)")
        old = git(repo, "rev-parse", "HEAD")
        git(repo, "fetch", "--quiet", "--depth", "1", "origin", source["branch"])
        new = git(repo, "rev-parse", "FETCH_HEAD")
        found.append({"name": checkout, "repo": repo, "old": old, "new": new})
    return found


def report_line(result: dict) -> str:
    parts = [result["at"], "status=" + result["status"]]
    for source in result.get("sources", []):
        old, new = source["old"][:7], source["new"][:7]
        parts.append(f"{source['name']}=" + (old if old == new else f"{old}>{new}"))
    if "chunks" in result:
        parts.append(f"chunks={result['chunks']}")
    for key in ("texts_added", "texts_removed", "embedded_now", "embed_left", "embedded", "unstudied"):
        if key in result:
            parts.append(f"{key}={result[key]}")
    if result.get("eval"):
        parts.append("eval30: " + result["eval"])
    if result.get("error"):
        parts.append("error=" + json.dumps(result["error"][:200]))
    parts.append(f"took={result['seconds']}s")
    return " ".join(parts)


def run(db_path: Path, home: Path, app: Path, *, max_wait: float = 3 * 3600, modes: str = "bm25,vector",
        report: Path | None = None, log=print, stop=None, fetch=fetch_all, check=True,
        embed_limit: int = EMBED_LIMIT) -> dict:
    stop = stop or Stopper()
    report = report or (db_path.parent / REPORT_NAME)
    sources_dir = home / "sources"
    config = json.loads((app / "corpora.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    result: dict = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "ok"}
    moved: list[dict] = []
    try:
        if not wait_for_quiet(max_wait, stop, log):
            result["status"] = "skipped-lock"
            return result
        try:
            result["sources"] = (fetch(sources_dir, config,
                                       wait=lambda: wait_for_quiet(max_wait, stop, log))
                                 if fetch is fetch_all else fetch(sources_dir, config))
        except QuietTimeout:
            result["status"] = "skipped-lock"
            return result
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            result["status"] = "fetch-failed"       # nothing was moved, nothing was rebuilt
            result["error"] = str(exc)
            return result
        changed = [s for s in result["sources"] if s["old"] != s["new"]]
        if changed:
            if not wait_for_quiet(max_wait, stop, log):
                result["status"] = "skipped-lock"
                return result
            try:
                for source in changed:
                    if not wait_for_quiet(max_wait, stop, log):
                        raise QuietTimeout("server lock held during checkout update")
                    _git(source["repo"], "reset", "--quiet", "--hard", source["new"])
                    moved.append(source)
                stats = build(db_path, sources_dir, app / "corpora.json", log=log)
                result["texts_added"] = stats["_all"]["texts_added"]
                result["texts_removed"] = stats["_all"]["texts_removed"]
            except (RebuildRefused, RuntimeError, subprocess.SubprocessError, OSError, ValueError) as exc:
                result["status"] = ("skipped-lock" if isinstance(exc, QuietTimeout) else
                                    "rebuild-refused" if isinstance(exc, RebuildRefused) else "rebuild-failed")
                if not isinstance(exc, QuietTimeout):
                    result["error"] = str(exc)
                for source in moved:        # the working index was built from the old commits: go back to them
                    try:
                        _git(source["repo"], "reset", "--quiet", "--hard", source["old"])
                    except RuntimeError as undo:
                        result["error"] = result.get("error", "") + f"; could not restore {source['name']}: {undo}"
                return result
            from .embed import run as embed_run
            embedded = embed_run(db_path, batch=8, log=log, stop=stop, limit=embed_limit or None)
            result["embedded_now"] = embedded["embedded_now"]
            if embed_limit and embedded["pending_before"] >= embed_limit:
                result["embed_left"] = "offload"     # more texts were pending than the limit: see offload.py
        else:
            result["status"] = "unchanged"
        db = connect(db_path)
        result["chunks"] = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        result["embedded"] = db.execute(
            "SELECT COUNT(*) FROM chunks c WHERE EXISTS (SELECT 1 FROM embeddings e WHERE e.text_sha=c.text_sha)").fetchone()[0]
        if db.execute("SELECT 1 FROM chunk_questions LIMIT 1").fetchone():
            result["unstudied"] = db.execute(
                """SELECT COUNT(DISTINCT text_sha) FROM chunks c WHERE NOT EXISTS
                   (SELECT 1 FROM study_log s WHERE s.text_sha=c.text_sha)""").fetchone()[0]
        db.close()
        if check:
            if not wait_for_quiet(max_wait, stop, log):
                result["eval"] = "skipped (server lock)"
                return result
            from .evaluate import one_line, run_eval
            try:
                result["eval"] = one_line(run_eval(db_path, app / "eval" / "questions.jsonl",
                                                   [m for m in modes.split(",") if m], details=False))
            except Exception as exc:   # the check must never turn a good refresh into a failed unit
                result["eval"] = f"failed ({type(exc).__name__})"
        return result
    finally:
        result["seconds"] = round(time.monotonic() - started)
        for source in result.get("sources", []):
            source.pop("repo", None)
        line = report_line(result)
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        log(line)
