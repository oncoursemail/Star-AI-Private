"""Advisory, bounded change-to-test planner for STAR development.

This is deliberately NOT a test runner, code dependency graph, or promotion gate.
Its suggestions accelerate the *first* check after a code edit; the independently
owned full verification and holdout suites remain mandatory before promotion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Iterable

MAX_CHANGED = 256
MAX_TESTS = 12_000
MAX_FAILURES = 200
MAX_FOCUSED = 32
MAX_MANIFEST_BYTES = 512_000
_ALLOWED = re.compile(r"[A-Za-z0-9_.@/-]{1,240}\Z")
_CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".lua", ".luau", ".gd", ".cs", ".java"}
_SENSITIVE_PREFIXES = (".github/", "installer/", "evals/", "star/security/", "star/policy")
_SENSITIVE_EXACT = {
    "star/agent.py", "star/eval_gate.py", "star/eval_stats.py", "star/github_app.py",
    "star/selfbuild.py", "star/updates.py", "star/protected_paths.py",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    "frontend/package.json", "frontend/package-lock.json",
}
_DOC_TEST_NAMES = {"tests/test_docs_links.py", "tests/test_docs_guide_links.py"}


def _repo_path(value: object) -> str:
    if type(value) is not str or not _ALLOWED.fullmatch(value):
        raise ValueError("Paths must be bounded, printable, relative repository paths")
    parts = value.split("/")
    if (value.startswith("/") or any(part in ("", ".", "..") for part in parts)
            or ":" in value or "\\" in value):
        raise ValueError("Absolute, traversal and ambiguous paths are not supported")
    return value


def _path_list(raw: object, name: str, maximum: int, *, nonempty: bool = False) -> list[str]:
    if type(raw) is not list or len(raw) > maximum or (nonempty and not raw):
        raise ValueError(f"{name} must be a bounded {'nonempty ' if nonempty else ''}list")
    paths = [_repo_path(value) for value in raw]
    if len(paths) != len(set(paths)):
        raise ValueError(f"{name} contains duplicate paths")
    return paths


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if path.startswith("tests/") and name.startswith("test_") and name.endswith(".py"):
        return True
    if path.startswith("frontend/src/") and re.search(r"\.(?:test|spec)\.[jt]sx?$", name):
        return True
    return "/src/test/" in "/" + path and path.endswith(".java")


def _matches_source(source: str, test: str) -> bool:
    # Name-based matches are a navigation hint, not a verified dependency.
    path = Path(source)
    stem = path.stem
    if source.startswith("star/") and path.suffix == ".py" and stem != "__init__":
        return (test == f"tests/test_{stem}.py"
                or (test.startswith(f"tests/test_{stem}_") and test.endswith(".py")))
    if source.startswith("frontend/src/") and path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
        without_extension = source.rsplit(".", 1)[0]
        return test in {f"{without_extension}.{kind}.{ext}"
                        for kind in ("test", "spec") for ext in ("ts", "tsx", "js", "jsx")}
    if source.startswith("server/") and path.suffix == ".py":
        return test == f"tests/test_{stem}.py"
    return False


def plan_checks(manifest: dict) -> dict:
    """Return reproducible test *suggestions*, never passing/failing claims.

    Manifest keys: changed_paths (required), available_tests (required),
    recent_failed_tests (optional), base_sha (optional).
    """
    if type(manifest) is not dict or set(manifest) - {
            "changed_paths", "available_tests", "recent_failed_tests", "base_sha"}:
        raise ValueError("Unexpected change-impact manifest keys")
    changed = _path_list(manifest.get("changed_paths"), "changed_paths", MAX_CHANGED, nonempty=True)
    tests = _path_list(manifest.get("available_tests"), "available_tests", MAX_TESTS)
    failures = _path_list(manifest.get("recent_failed_tests", []), "recent_failed_tests", MAX_FAILURES)
    if any(not _is_test(t) for t in tests):
        raise ValueError("available_tests must contain only named test files, never holdouts")
    if any(not _is_test(t) for t in failures):
        raise ValueError("recent_failed_tests must contain only named test files")
    base_sha = manifest.get("base_sha")
    if base_sha is not None and (type(base_sha) is not str or not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha)):
        raise ValueError("base_sha must be a frozen 40-digit commit SHA")

    available = set(tests)
    chosen: set[str] = set(failures) & available
    mapped: dict[str, list[str]] = {}
    uncovered: list[str] = []
    review_paths: list[str] = []
    for source in changed:
        if source.startswith(_SENSITIVE_PREFIXES) or source in _SENSITIVE_EXACT:
            review_paths.append(source)
        if _is_test(source):
            if source in available:
                chosen.add(source)
                mapped[source] = [source]
            else:
                uncovered.append(source)
        elif source.startswith("docs/") and source.endswith(".md"):
            hits = sorted(available & _DOC_TEST_NAMES)
            chosen.update(hits)
            if hits:
                mapped[source] = hits
            else:
                uncovered.append(source)
        elif Path(source).suffix in _CODE_EXTENSIONS:
            hits = sorted(t for t in available if _matches_source(source, t))
            chosen.update(hits)
            if hits:
                mapped[source] = hits
            else:
                uncovered.append(source)
        else:
            uncovered.append(source)
    # A stable, bounded quick stage; never silently claim exhaustive coverage.
    ordered = sorted(chosen, key=lambda t: (t not in failures, t))
    truncated = len(ordered) > MAX_FOCUSED
    return {
        "base_sha": base_sha,
        "changed_paths": changed,
        "focused_tests": ordered[:MAX_FOCUSED],
        "selected_test_count": len(ordered),
        "selection_truncated": truncated,
        "uncovered_paths": uncovered,
        "mapped_paths": {k: mapped[k] for k in sorted(mapped)},
        "review_required_paths": review_paths,
        "missing_recent_failures": sorted(set(failures) - available),
        "advisory_only": True,
        "full_suite_required_before_merge_or_learning": True,
        "can_claim_pass": False,
        "note": "Name-based first-check hints only; execute real checks and independently verify the full suite.",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Suggest first checks for a STAR source change (read-only)")
    parser.add_argument("manifest", type=Path, help="JSON with changed_paths and available_tests")
    args = parser.parse_args(argv)
    if args.manifest.stat().st_size > MAX_MANIFEST_BYTES:
        parser.error("manifest exceeds the 512 KB input limit")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        print(json.dumps(plan_checks(manifest), indent=2, sort_keys=True))
    except (ValueError, UnicodeError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
