"""Build px.json: the data behind the PX page (launcher view and public site).

Sources, all read-only:
  roadmap.json  curated items with one of five honest states (planned, implemented, tested, accepted, released)
  the forge     milestones, release list and issue counts per repository (Forgejo/Gitea API, token read from a file)

Nothing here turns issue counts into a completion percentage. The forge numbers are shown as what they are (tracker
issues, milestone issues, releases). `--public` output carries no issue titles or release notes, no counts for private
repositories, and is scanned for addresses, user names and key shapes before it is written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATES = ("planned", "implemented", "tested", "accepted", "released")
ROADMAP = Path(__file__).with_name("roadmap.json")
SECRET_PATTERNS = [
    (re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\b"), "private address"),  # star:allow
    (re.compile(r"\balexbuz1?\b", re.I), "server user name"),  # star:allow
    (re.compile(r"\b(?:ghp|gho|github_pat|sk|rk)_[A-Za-z0-9_]{16,}"), "token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),  # star:allow
    (re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[^\\\"]+", re.I), "local path"),
]


class PxError(Exception):
    pass


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


# ---- forge ---------------------------------------------------------------------------------------------------------

class Forge:
    """Minimal read-only Forgejo/Gitea client. `get` is injectable so tests need no network."""

    def __init__(self, base_url: str, token: str = "", org: str = "metallic", timeout: float = 15.0, get=None):
        self.base, self.token, self.org, self.timeout = base_url.rstrip("/"), token, org, timeout
        self._get = get or self._http_get

    def _http_get(self, path: str):
        req = urllib.request.Request(self.base + "/api/v1" + path,
                                     headers={"Authorization": f"token {self.token}"} if self.token else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise PxError(f"forge request failed for {path.split('?')[0]}: {getattr(exc, 'reason', exc)}") from exc

    def pages(self, path: str, limit: int = 50, max_pages: int = 40) -> list:
        out, sep = [], "&" if "?" in path else "?"
        for page in range(1, max_pages + 1):
            chunk = self._get(f"{path}{sep}limit={limit}&page={page}")
            if not isinstance(chunk, list):
                raise PxError("unexpected forge reply")
            out.extend(chunk)
            if len(chunk) < limit:
                break
        return out

    def repo(self, name: str) -> dict:
        base = f"/repos/{self.org}/{urllib.parse.quote(name)}"
        return {"milestones": self.pages(f"{base}/milestones?state=all"),
                "releases": self.pages(f"{base}/releases"),
                "issues": self.pages(f"{base}/issues?type=issues&state=all")}


def week_start(t: datetime) -> datetime:
    d = t.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


def activity(issues: list, now: datetime, weeks: int = 12) -> list[dict]:
    """Opened and closed issues per week for the last `weeks` weeks, from real timestamps."""
    first = week_start(now) - timedelta(weeks=weeks - 1)
    rows = [{"start": (first + timedelta(weeks=i)).strftime("%Y-%m-%d"), "opened": 0, "closed": 0} for i in range(weeks)]
    index = {r["start"]: r for r in rows}
    for issue in issues:
        for field, key in (("created_at", "opened"), ("closed_at", "closed")):
            t = parse_iso(issue.get(field))
            if t:
                row = index.get(week_start(t).strftime("%Y-%m-%d"))
                if row:
                    row[key] += 1
    return rows


def tracker_block(raw: dict, now: datetime, public: bool, private_repo: bool) -> dict | None:
    issues = [i for i in raw["issues"] if not i.get("pull_request")]
    closed = sum(1 for i in issues if i.get("state") == "closed")
    block = {"open": len(issues) - closed, "closed": closed, "weeks": activity(issues, now),
             "milestones": [{"title": m["title"], "open": m.get("open_issues", 0), "closed": m.get("closed_issues", 0),
                             "due": (m.get("due_on") or "")[:10] or None, "state": m.get("state", "open")}
                            for m in raw["milestones"]]}
    if public and private_repo:
        return None
    return block


def release_rows(raw: dict, public: bool) -> list[dict]:
    rows = []
    for r in sorted(raw["releases"], key=lambda r: r.get("published_at") or r.get("created_at") or "", reverse=True):
        if r.get("draft"):
            continue
        row = {"tag": r.get("tag_name", ""), "name": r.get("name") or r.get("tag_name", ""),
               "date": (r.get("published_at") or r.get("created_at") or "")[:10], "prerelease": bool(r.get("prerelease"))}
        if not public:
            row["notes"] = (r.get("body") or "").strip()[:600]
        rows.append(row)
    return rows


# ---- model ---------------------------------------------------------------------------------------------------------

def load_roadmap(path: Path | None = None) -> dict:
    data = json.loads(Path(path or ROADMAP).read_text(encoding="utf-8"))
    ids = set()
    for proj in data["projects"]:
        for item in proj["items"]:
            if item["state"] not in STATES:
                raise PxError(f"{item['id']}: unknown state {item['state']!r}")
            if item["id"] in ids:
                raise PxError(f"duplicate roadmap id {item['id']}")
            ids.add(item["id"])
    for proj in data["projects"]:
        for item in proj["items"]:
            for dep in item.get("depends", []):
                if dep not in ids:
                    raise PxError(f"{item['id']} depends on unknown {dep}")
    return data


def build(roadmap: dict, forge: Forge | None, *, public: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    projects, changelog, forge_state = [], [], {"state": "off", "detail": "no forge configured"}
    failures = 0
    for proj in roadmap["projects"]:
        counts = Counter(i["state"] for i in proj["items"])
        item_state = {i["id"]: i["state"] for i in proj["items"]}
        items = []
        for i in proj["items"]:
            row = {k: i[k] for k in ("id", "title", "state", "evidence") if k in i}
            for k in ("note", "blockers", "depends"):
                if i.get(k):
                    row[k] = i[k]
            if i.get("depends"):
                row["waiting_on"] = [d for d in i["depends"] if item_state.get(d) in ("planned", "implemented")]
            items.append(row)
        entry = {"id": proj["id"], "name": proj["name"], "role": proj["role"], "items": items,
                 "states": {s: counts.get(s, 0) for s in STATES}, "total": len(items),
                 "updated": max((i["evidence"] for i in items), default=""), "tracker": None, "releases": []}
        if forge is not None:
            try:
                raw = forge.repo(proj["repo"])
                entry["tracker"] = tracker_block(raw, now, public, proj.get("private", False))
                entry["releases"] = release_rows(raw, public)
            except PxError as exc:
                failures += 1
                forge_state = {"state": "offline", "detail": str(exc)}
        projects.append(entry)
        for r in entry["releases"]:
            changelog.append({"date": r["date"], "project": proj["id"], "kind": "release",
                              "title": r["name"], **({"text": r["notes"]} if r.get("notes") else {})})
        for i in proj["items"]:
            if i["state"] in ("accepted", "released", "tested"):
                changelog.append({"date": i["evidence"], "project": proj["id"], "kind": i["state"], "title": i["title"],
                                  **({"text": i["note"]} if i.get("note") else {})})
    if forge is not None and not failures:
        forge_state = {"state": "online", "detail": ""}
    elif forge is not None and failures < len(projects):
        forge_state["state"] = "partial"
    changelog.sort(key=lambda c: (c["date"], c["title"]), reverse=True)
    return {"schema": 1, "generated": iso(now), "mode": "public" if public else "internal", "forge": forge_state,
            "states": list(STATES), "projects": projects, "changelog": changelog[:80]}


def scrub(data: dict) -> list[str]:
    """Names of private-looking things found in the serialized data (empty = clean)."""
    text = json.dumps(data, ensure_ascii=False)
    return sorted({label for rx, label in SECRET_PATTERNS if rx.search(text)})


def write(data: dict, out: Path) -> Path:
    problems = scrub(data) if data["mode"] == "public" else []
    if problems:
        raise PxError("public output refused, it contains: " + ", ".join(problems))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m launcher.px", description=__doc__)
    p.add_argument("--out", required=True, help="where to write px.json")
    p.add_argument("--public", action="store_true", help="strip titles, notes and private-repo counts")
    p.add_argument("--forge", help="forge base URL (omit to build from roadmap.json alone)")
    p.add_argument("--token-file", help="file holding a read-only forge token")
    p.add_argument("--org", default="metallic")
    p.add_argument("--roadmap")
    a = p.parse_args(argv)
    token = Path(a.token_file).read_text(encoding="utf-8").strip() if a.token_file else ""
    try:
        data = build(load_roadmap(Path(a.roadmap) if a.roadmap else None),
                     Forge(a.forge, token, a.org) if a.forge else None, public=a.public)
        path = write(data, Path(a.out))
    except (PxError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {path} ({data['mode']}, forge {data['forge']['state']})")
    return 0
