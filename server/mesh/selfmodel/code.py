"""Code awareness, run on the owner PC (gh is signed in there; nothing is copied to the servers):

    python -m mesh.selfmodel code-push [--repo-dir DIR] [--branch star/next] [--router URL] [--dry-run]

Reports to the self-model (kind "code"): the branch head, open PRs into it with the services they touch, the CI state
of the head, and for every deployed service the commit its main file comes from (the service reports the git blob id
of the deployed file; here `git log --find-object` finds the commit) and how many newer commits touched that file.
Router URL: --router, STAR_MESH_URL or the first line of ~/.star/mesh_url. Key: ~/.star/server_api_key (never printed).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SERVICE_PATHS = [   # path prefix -> service name (first match wins)
    ("server/mesh/node/", "gpu-node"), ("server/mesh/verify/", "verify"), ("server/mesh/docs/", "docs"),
    ("server/mesh/selfmodel/", "selfmodel"), ("server/mesh/autotune/", "autotune"), ("server/mesh/upgrade/", "upgrade"),
    ("server/mesh/", "router"), ("server/training/", "training"), ("server/night_school/", "night-school"),
    ("server/", "brain-server"), ("star/inner/", "star-inner-life"), ("star/", "star-app"), ("frontend/", "star-ui"),
    ("launcher/", "metallic-launcher"), ("tests/", "tests"), ("docs/", "docs-text"),
]


def services_of(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        name = next((s for prefix, s in SERVICE_PATHS if p.startswith(prefix)), "other")
        if name not in out:
            out.append(name)
    return out


def run(cmd: list[str], cwd: str | None = None, timeout: float = 60) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=True,
                          encoding="utf-8", errors="replace").stdout


def repo_slug(repo_dir: str) -> str:
    url = run(["git", "remote", "get-url", "origin"], repo_dir).strip()
    slug = url.split("github.com", 1)[-1].lstrip(":/")
    return slug[:-4] if slug.endswith(".git") else slug


def ci_state(check_runs: list[dict]) -> dict:
    failing = sorted({c.get("name", "?") for c in check_runs if c.get("conclusion") in ("failure", "timed_out", "cancelled")})
    pending = [c for c in check_runs if c.get("status") != "completed"]
    state = "failing" if failing else "running" if pending else "passing" if check_runs else "none"
    return {"state": state, "failing": failing, "checks": len(check_runs)}


def commit_of_blob(repo_dir: str, blob: str, path: str, branch: str) -> dict:
    """The oldest commit on `branch` whose `path` is exactly this blob, plus how many later commits changed the file."""
    try:
        commits = run(["git", "log", f"origin/{branch}", "--format=%H", "--find-object=" + blob], repo_dir).split()
    except subprocess.CalledProcessError:
        commits = []
    having = []
    for c in commits:
        try:
            if run(["git", "rev-parse", f"{c}:{path}"], repo_dir).strip() == blob:
                having.append(c)
        except subprocess.CalledProcessError:
            continue
    if not having:
        try:   # an unmerged branch? name it
            other = run(["git", "log", "--remotes", "--format=%H", "-1", "--find-object=" + blob], repo_dir).strip()
            refs = run(["git", "branch", "-r", "--contains", other], repo_dir).split() if other else []
        except subprocess.CalledProcessError:
            other, refs = "", []
        if other:
            return {"commit": other, "branch": refs[0] if refs else None,
                    "note": f"deployed from {refs[0] if refs else 'a branch'}, not merged into {branch} yet"}
        return {"commit": None, "note": "deployed file is not on any pushed branch (local edit)"}
    first = having[-1]   # git log is newest first
    newer = int(run(["git", "rev-list", "--count", f"{first}..origin/{branch}", "--", path], repo_dir).strip() or 0)
    return {"commit": first, "newer_commits_on_branch": newer}


def _router_url(arg: str | None) -> str:
    if arg:
        return arg
    if os.environ.get("STAR_MESH_URL"):
        return os.environ["STAR_MESH_URL"]
    f = Path.home() / ".star" / "mesh_url"
    return f.read_text(encoding="utf-8").split()[0] if f.is_file() else ""


def _key() -> str:
    return (Path.home() / ".star" / "server_api_key").read_text(encoding="utf-8").split()[0]


def _http(url: str, key: str, body: dict | None = None, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read())


def build_report(repo_dir: str, branch: str, deployed: dict, gh=run) -> dict:
    slug = repo_slug(repo_dir)
    run(["git", "fetch", "-q", "origin", branch], repo_dir, timeout=120)
    head = run(["git", "rev-parse", f"origin/{branch}"], repo_dir).strip()
    prs_raw = json.loads(gh(["gh", "pr", "list", "-R", slug, "--base", branch, "--state", "open", "--limit", "50",
                             "--json", "number,title,isDraft,headRefName,files,updatedAt"]))
    prs = [{"number": p["number"], "title": p["title"][:120], "draft": p.get("isDraft", False),
            "branch": p.get("headRefName"), "updated": p.get("updatedAt"),
            "services": services_of([f.get("path", "") for f in p.get("files") or []])} for p in prs_raw]
    runs = json.loads(gh(["gh", "api", f"repos/{slug}/commits/{head}/check-runs?per_page=100"])).get("check_runs", [])
    dep = {}
    for name, d in (deployed or {}).items():
        if d.get("blob") and d.get("file"):
            dep[name] = {"file": d["file"], **commit_of_blob(repo_dir, d["blob"], "server/" + d["file"], branch)}
    return {"kind": "code", "branch": branch, "head": head, "prs": prs, "ci": ci_state(runs), "deployed": dep}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="mesh.selfmodel code-push")
    ap.add_argument("--repo-dir", default=str(Path(__file__).resolve().parents[3]))
    ap.add_argument("--branch", default="star/next")
    ap.add_argument("--router")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    url, key = _router_url(a.router).rstrip("/"), _key()
    deployed = {}
    if url:
        deployed = (_http(url + "/mesh/self", key).get("code") or {}).get("deployed") or {}
    report = build_report(a.repo_dir, a.branch, deployed)
    print(json.dumps({k: report[k] for k in ("head", "ci", "deployed")} | {"prs": len(report["prs"])}, indent=1))
    if not a.dry_run and url:
        print(_http(url + "/mesh/self/report", key, report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
