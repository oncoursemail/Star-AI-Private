"""STAR brain vault: the team's notes and a code map as an Obsidian-compatible folder of Markdown.

    python -m star.brain_vault build --out <vault> [--workspace <starai>] [--repo <checkout>] [--extract]
    python -m star.brain_vault status --out <vault>

The vault is PRIVATE. Every note passes `redact()` (private network addresses, server user names, keys
and tokens, e-mail addresses), but the folder still describes internal work: keep it outside every
Git repository that is, or may become, public. `build` refuses a target inside a Git checkout.

Layout (the generator owns only these entries; anything else in the folder, such as the owner's own
notes or `.obsidian`, is never touched):

    Home.md                   what this is, counts, how to refresh
    notes/<group>/<name>.md   team notes (docs/agents, docs/research, STATE.md, ...), one per source file
    daily/<date>.md           "what changed on that day": notes touched and commits
    code/<dir>/<file>_<ext>.md  one note per source file from Graphify's graph.json: docstring, symbols,
                              imports and who imports it (wiki-links)
    .brain-vault.json         marker + manifest (counts, hashes, redaction counts)

It is a read-only snapshot: edit the sources, not the vault; the next build replaces the owned folders.
Plain standard library; Graphify is only needed for `--extract` (it never runs without that flag).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import getpass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

MARKER = ".brain-vault.json"
OWNED = ("notes", "daily", "code", "Home.md")
MAX_NOTE_CHARS = 240_000          # below the Obsidian bridge's MAX_NOTE_BYTES
# Server user names are never written into this (Git-tracked) file: one per line in this file, or comma separated in
# the environment variable. The OS account running the build is always added.
PRIVATE_NAMES_FILE = Path.home() / ".star" / "vault-private-names.txt"
PRIVATE_NAMES_ENV = "STAR_VAULT_PRIVATE_NAMES"
CODE_SKIP_TOP = {"tests", "node_modules", "examples", "benchmarks", "evals", "site"}
MAX_SYMBOLS = 60
MAX_LINKS = 25

# ------------------------------------------------------------------------------------ redaction

_IP = re.compile(r"(?<![\w.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\w])(?!\.\d)")
_USER_AT = re.compile(r"\b([A-Za-z0-9_.-]{2,32})@(?=\[private-ip\])")
_TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}"),
)
_ASSIGN = re.compile(
    r"""(?ix)
    (?P<name>(?:api[_-]?key|secret|token|passw(?:or)?d|passwd|credential|auth[_-]?key|private[_-]?key)[A-Za-z0-9_.-]{0,40}
    ["']?\s*(?::=|=>|[:=])\s*["']?)
    (?P<val>[A-Za-z0-9+/=_\-.~!@\#$%^&*]{20,})""")
_PLACEHOLDER = re.compile(r"(?i)example|your|xxxx|changeme|placeholder|dummy|sample|<|\$\{|%\(|\bnone\b|redacted")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_WIN_USER = re.compile(r"(?i)(\b[A-Za-z]:[\\/]+Users[\\/]+|/(?:mnt/)?[a-z]/Users/|/home/)([^\\/\s\"'`<>|:*?]+)")


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(c / len(text) * math.log2(c / len(text)) for c in counts.values()) if text else 0.0


def _looks_secret(value: str) -> bool:
    if _PLACEHOLDER.search(value):
        return False
    classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    return classes >= 2 and bool(re.search(r"[0-9]", value)) and _entropy(value) >= 3.2


def _private_ip_or_same(match: re.Match) -> str:
    octets = [int(x) for x in match.groups()]
    if any(x > 255 for x in octets):
        return match.group(0)
    first, second = octets[0], octets[1]
    private = (first == 10 or (first == 192 and second == 168) or (first == 172 and 16 <= second <= 31)
               or (first == 100 and 64 <= second <= 127) or (first == 169 and second == 254))
    return "[private-ip]" if private else match.group(0)


def private_names() -> tuple[str, ...]:
    """Names replaced as whole words: the configured server user names plus the OS account (if 4+ characters)."""
    found = [n.strip() for n in os.environ.get(PRIVATE_NAMES_ENV, "").split(",")]
    try:
        found += [line.strip() for line in PRIVATE_NAMES_FILE.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
    except OSError:
        pass
    try:
        account = getpass.getuser()
        found.append(account if len(account) >= 4 else "")
    except (OSError, KeyError):
        pass
    return tuple(dict.fromkeys(n for n in found if n))


def redact(text: str, *, names: tuple[str, ...] | None = None) -> tuple[str, Counter]:
    """(text with private values replaced, counts per kind). Applying it twice changes nothing more.
    `names` (default: private_names()) are replaced as whole words."""
    found: Counter = Counter()
    names = private_names() if names is None else names

    def sub(kind: str, pattern: re.Pattern, repl, value: str) -> str:
        new, n = pattern.subn(repl, value)
        if n:
            found[kind] += n
        return new

    for pattern in _TOKEN_PATTERNS:
        text = sub("key-or-token", pattern, "[redacted-key]", text)

    def assigned(match: re.Match) -> str:
        if _looks_secret(match.group("val")):
            found["key-or-token"] += 1
            return match.group("name") + "[redacted-key]"
        return match.group(0)
    text = _ASSIGN.sub(assigned, text)
    before = text
    text = _IP.sub(_private_ip_or_same, text)
    replaced = text.count("[private-ip]") - before.count("[private-ip]")
    if replaced:
        found["private-ip"] += replaced
    text = sub("user-name", _USER_AT, "[user]@", text)
    text = sub("user-name", _WIN_USER, lambda m: m.group(1) + "[user]", text)
    for name in names:
        text = sub("user-name", re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.I),
                   "[user]", text)
    text = sub("email", _EMAIL, "[email]", text)
    return text, found


def redact_counted(text: str, total: Counter, **kw) -> str:
    out, found = redact(text, **kw)
    total.update(found)
    return out


# --------------------------------------------------------------------------------------- notes

def _title(raw: str, fallback: str) -> str:
    for line in raw.splitlines()[:40]:
        match = re.match(r"^#{1,2}\s+(.+?)\s*#*\s*$", line)
        if match:
            return match.group(1).strip()[:160]
    return fallback


def _summary(raw: str, limit: int = 160) -> str:
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "---", "```", "|", "<", ">", "- [", "* [")):
            return re.sub(r"\s+", " ", line.strip("-*> "))[:limit]
    return ""


def _frontmatter(**fields) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}: [" + ", ".join(json.dumps(v) for v in value) + "]")
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    return "\n".join(lines + ["---", ""])


def _strip_frontmatter(raw: str) -> str:
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            return raw[end + 4:].lstrip("\n")
    return raw


def _sources(workspace: Path | None, repo: Path | None):
    """(group, vault name, file) for every team note. The workspace wins over the repo for a clashing path."""
    seen: set[str] = set()
    plan = []
    if workspace is not None:
        plan += [(workspace, "docs/agents", "agents", False), (workspace, "docs/research", "research", False),
                 (workspace, "docs", "docs", False)]
    if repo is not None:
        plan += [(repo, "docs/agents", "agents", False), (repo, "docs/research", "research", False),
                 (repo, "docs", "docs", False), (repo, "docs/release", "release", True)]
    for root, sub, group, recursive in plan:
        folder = root / sub
        if not folder.is_dir():
            continue
        for file in sorted(folder.rglob("*.md") if recursive else folder.glob("*.md")):
            rel = file.relative_to(root).as_posix()
            if rel in seen or not file.is_file() or file.is_symlink():
                continue
            seen.add(rel)
            yield group, file.relative_to(folder).with_suffix("").as_posix().replace("/", "--"), file, rel
    for root in (workspace, repo):
        if root is None:
            continue
        for name in ("STATE.md", "OWNER-TODO.md", "AGENTS.md", "CLAUDE.md", "STAR-LEARNING.md", "README.md"):
            file = root / name
            if name not in seen and file.is_file():
                seen.add(name)
                yield "root", name[:-3], file, name


def _git_dates(repo: Path | None) -> dict[str, str]:
    """path -> date of the newest commit that touched it (any branch). A checkout's file times are the
    checkout time, so for committed notes the commit date is the honest "changed on" date."""
    if repo is None or not (repo / ".git").exists():
        return {}
    try:
        done = subprocess.run(["git", "-C", str(repo), "log", "--all", "--name-only", "--format=@%cs", "-n", "4000",
                               "--", "docs", "STATE.md", "OWNER-TODO.md"],
                              capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return {}
    dates: dict[str, str] = {}
    day = ""
    for line in done.stdout.splitlines():
        if line.startswith("@"):
            day = line[1:]
        elif line.strip() and day:
            dates.setdefault(line.strip(), day)
    return dates


def build_notes(out: Path, workspace: Path | None, repo: Path | None, totals: Counter) -> list[dict]:
    notes = []
    dates = _git_dates(repo)
    names: set[str] = set()
    for group, name, file, rel in _sources(workspace, repo):
        raw = file.read_text(encoding="utf-8", errors="replace")[:MAX_NOTE_CHARS]
        body = redact_counted(_strip_frontmatter(raw.replace("\r\n", "\n")), totals)
        title = redact_counted(_title(body, name), totals)
        vault_name = f"{group}/{name}"
        if vault_name in names:     # the same name from two folders cannot happen with the rel-path dedupe; keep safe
            continue
        names.add(vault_name)
        modified = (datetime.strptime(dates[rel], "%Y-%m-%d").replace(tzinfo=timezone.utc) if rel in dates
                    else datetime.fromtimestamp(file.stat().st_mtime, timezone.utc))
        head = _frontmatter(title=title, source=rel, group=group, modified=modified.strftime("%Y-%m-%d"),
                            tags=[f"star/{group}"])
        target = out / "notes" / group / f"{name}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(head + body.rstrip() + "\n", encoding="utf-8", newline="\n")
        notes.append({"path": f"notes/{group}/{name}.md", "title": title, "group": group, "source": rel,
                      "modified": modified, "summary": _summary(body)})
    return notes


def _commit_lines(repo: Path | None, since: datetime) -> dict[str, list[str]]:
    if repo is None or not (repo / ".git").exists():
        return {}
    try:
        done = subprocess.run(["git", "-C", str(repo), "log", "--all", "--no-merges", "--since", since.isoformat(),
                               "--format=%cs\t%h\t%s", "-n", "800"],
                              capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return {}
    days: dict[str, list[str]] = defaultdict(list)
    for line in done.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and len(days[parts[0]]) < 80:
            days[parts[0]].append(f"{parts[1]} {parts[2]}")
    return days


def build_daily(out: Path, notes: list[dict], repo: Path | None, totals: Counter, *, days: int,
                today: datetime | None = None) -> int:
    today = today or datetime.now(timezone.utc)
    since = (today - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    commits = _commit_lines(repo, since)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for note in notes:
        if note["modified"] >= since:
            by_day[note["modified"].strftime("%Y-%m-%d")].append(note)
    written = 0
    for day in sorted(set(by_day) | set(commits)):
        lines = [_frontmatter(title=f"Changes on {day}", kind="daily", tags=["star/daily"]),
                 f"# What changed on {day}", ""]
        touched = sorted(by_day.get(day, ()), key=lambda n: n["path"])
        if touched:
            lines += [f"## Notes written or updated ({len(touched)})", ""]
            for note in touched:
                summary = f" - {note['summary']}" if note["summary"] else ""
                lines.append(f"- [[{note['path'][:-3]}|{note['title']}]]{summary}")
            lines.append("")
        if commits.get(day):
            lines += [f"## Commits ({len(commits[day])})", ""]
            lines += [f"- {redact_counted(c, totals)}" for c in commits[day]]
            lines.append("")
        target = out / "daily" / f"{day}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        written += 1
    return written


# --------------------------------------------------------------------------------- code map

def _code_name(path: str) -> str:
    """star/slop.py -> code/star/slop_py (no dot in the name: Obsidian reads `x.py` as an attachment link)."""
    stem, dot, ext = path.rpartition(".")
    return "code/" + (f"{stem}_{ext}" if dot else path)


def build_code_map(out: Path, graph_file: Path, totals: Counter) -> dict:
    data = json.loads(graph_file.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n}
    edges = data.get("links", data.get("edges", []))
    where = {ident: str(n.get("source_file") or "") for ident, n in nodes.items()}
    files: dict[str, dict] = {}
    for ident, node in nodes.items():
        path = where[ident]
        if (node.get("file_type") == "code" and "/" in path and path.split("/")[0] not in CODE_SKIP_TOP):
            files.setdefault(path, {"symbols": set(), "doc": "", "imports": set(), "used_by": set(), "tests": set()})
    for edge in edges:
        relation = edge.get("relation")
        src, dst = nodes.get(edge.get("source")), nodes.get(edge.get("target"))
        if src is None or dst is None:
            continue
        a, b = where[src["id"]], where[dst["id"]]
        if relation == "contains" and a in files and a == b and dst.get("file_type") == "code":
            files[a]["symbols"].add((_line(dst), str(dst.get("label", ""))))
        elif relation == "rationale_for" and b in files and src.get("file_type") == "rationale":
            if _line(dst) <= 1 and not files[b]["doc"]:
                files[b]["doc"] = str(src.get("label", ""))
        elif relation in ("imports", "imports_from") and a != b:
            if a in files and b in files:
                files[a]["imports"].add(b)
                files[b]["used_by"].add(a)
            elif a.startswith("tests/") and b in files:
                files[b]["tests"].add(a)

    def link(path: str) -> str:
        return f"[[{_code_name(path)}|{path}]]"

    overview: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path, entry in sorted(files.items()):
        symbols = sorted(s for s in entry["symbols"] if s[1])
        doc = entry["doc"]
        body = [_frontmatter(title=path, source=path, kind="code", tags=["star/code"]), f"# {path}", ""]
        if doc:
            body += [doc, ""]
        if symbols:
            body += [f"## Defines ({len(symbols)})", ""]
            body += [f"- `{lb}` (line {ln})" if ln else f"- `{lb}`" for ln, lb in symbols[:MAX_SYMBOLS]]
            if len(symbols) > MAX_SYMBOLS:
                body.append(f"- ... and {len(symbols) - MAX_SYMBOLS} more")
            body.append("")
        for heading, group in (("Imports from the repo", entry["imports"]), ("Imported by", entry["used_by"]),
                               ("Tested by", entry["tests"])):
            group = sorted(group)
            if group:
                body += [f"## {heading} ({len(group)})", ""]
                body += [f"- {link(g)}" for g in group[:MAX_LINKS]]
                if len(group) > MAX_LINKS:
                    body.append(f"- ... and {len(group) - MAX_LINKS} more")
                body.append("")
        target = out / f"{_code_name(path)}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(redact_counted("\n".join(body), totals), encoding="utf-8", newline="\n")
        overview[path.rsplit("/", 1)[0]].append((path, doc))
    for folder, items in overview.items():
        lines = [_frontmatter(title=f"Code overview: {folder}", kind="code-overview", tags=["star/code"]),
                 f"# Code overview: {folder}", "", f"{len(items)} files, generated from Graphify's graph.json.", ""]
        for path, doc in items:
            lines.append(f"- {link(path)}" + (f" - {doc[:140]}" if doc else ""))
        target = out / "code" / folder / "_overview.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(redact_counted("\n".join(lines) + "\n", totals), encoding="utf-8", newline="\n")
    return {"files": len(files), "folders": len(overview), "graph_nodes": len(nodes), "graph_edges": len(edges)}


def _line(node: dict) -> int:
    match = re.match(r"L(\d+)", str(node.get("source_location") or ""))
    return int(match.group(1)) if match else 0


# ------------------------------------------------------------------------------ graphify call

def find_graphify() -> list[str] | None:
    """The command prefix that runs Graphify: the stable venv first, then PATH."""
    venv = Path.home() / ".star" / "graphify-venv" / ("Scripts" if os.name == "nt" else "bin")
    for name in ("python.exe", "python"):
        if (venv / name).is_file():
            return [str(venv / name), "-m", "graphify"]
    found = shutil.which("graphify")
    return [found] if found else None


def extract_graph(repo: Path, *, timeout: float = 1800) -> Path:
    command = find_graphify()
    if command is None:
        raise RuntimeError("Graphify is not installed (pip install graphifyy==0.9.69 into ~/.star/graphify-venv)")
    done = subprocess.run([*command, "extract", ".", "--code-only"], cwd=repo, capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="replace")
    graph = repo / "graphify-out" / "graph.json"
    if done.returncode != 0 or not graph.is_file():
        raise RuntimeError("graphify extract failed: " + (done.stderr or done.stdout)[-400:])
    return graph


def export_raw_graph(graph: Path, target: Path) -> tuple[int, Counter]:
    """Graphify's own `export obsidian` (one note per node: 20k+ notes, so it goes into its own folder),
    then every note through `redact()` (its labels are docstring sentences from the code)."""
    command = find_graphify()
    if command is None:
        raise RuntimeError("Graphify is not installed")
    target.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([*command, "export", "obsidian", "--graph", str(graph), "--dir", str(target)],
                          capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise RuntimeError("graphify export obsidian failed: " + (done.stderr or done.stdout)[-400:])
    totals: Counter = Counter()
    notes = 0
    for file in target.glob("*.md"):
        notes += 1
        raw = file.read_text(encoding="utf-8", errors="replace")
        clean = redact_counted(raw, totals)
        if clean != raw:
            file.write_text(clean, encoding="utf-8", newline="\n")
    return notes, totals


# --------------------------------------------------------------------------------------- build

def _inside_git(path: Path) -> bool:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return True
    return False


def _marker(out: Path) -> dict | None:
    try:
        return json.loads((out / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(out: Path, *, workspace: Path | None = None, repo: Path | None = None, graph: Path | None = None,
          days: int = 14, extract: bool = False, raw_graph_dir: Path | None = None,
          allow_in_git: bool = False, now: datetime | None = None) -> dict:
    out = out.expanduser().resolve()
    if _inside_git(out) and not allow_in_git:
        raise ValueError("the vault describes private work: choose a folder that is not inside a Git checkout")
    if out.exists() and any(out.iterdir()) and _marker(out) is None:
        raise ValueError("the target folder is not empty and is not a STAR brain vault; nothing was written")
    if extract:
        if repo is None:
            raise ValueError("--extract needs --repo")
        graph = extract_graph(repo)
    elif graph is None and repo is not None and (repo / "graphify-out" / "graph.json").is_file():
        graph = repo / "graphify-out" / "graph.json"
    stage = out.with_name(out.name + ".building")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    totals: Counter = Counter()
    try:
        notes = build_notes(stage, workspace, repo, totals)
        daily = build_daily(stage, notes, repo, totals, days=days, today=now)
        code = build_code_map(stage, graph, totals) if graph is not None and graph.is_file() else None
        keep_code = code is None and (out / "code").is_dir()      # no graph this time: the last code map stays
        if keep_code:
            code = (_marker(out) or {}).get("code")
        built = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        by_group = Counter(n["group"] for n in notes)
        _home(stage, notes, daily, code, built, by_group)
        manifest = {"built_at": built, "notes": len(notes), "notes_by_group": dict(by_group), "daily": daily,
                    "code": code, "redactions": dict(totals), "generator": "star.brain_vault", "private": True}
        (stage / MARKER).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        out.mkdir(parents=True, exist_ok=True)
        for name in OWNED:
            if name == "code" and keep_code:
                continue
            old, new = out / name, stage / name
            if old.is_dir():
                shutil.rmtree(old)
            elif old.exists():
                old.unlink()
            if new.exists():
                shutil.move(str(new), str(old))
        shutil.move(str(stage / MARKER), str(out / MARKER))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if raw_graph_dir is not None and graph is not None:
        manifest["raw_graph_notes"], raw_found = export_raw_graph(graph, raw_graph_dir)
        manifest["raw_graph_redactions"] = dict(raw_found)
        (out / MARKER).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _home(stage: Path, notes: list[dict], daily: int, code: dict | None, built: str, by_group: Counter) -> None:
    recent = sorted(notes, key=lambda n: n["modified"], reverse=True)[:12]
    lines = [_frontmatter(title="STAR brain: home", kind="home", tags=["star/home"]), "# STAR brain: home", "",
             f"Generated {built} by `python -m star.brain_vault build`. A read-only snapshot of the team's notes "
             "and the code map: edit the sources, not these notes. PRIVATE: keep it out of public repositories.", "",
             "## Start here", ""]
    for group, label in (("root", "Current state and to-do"), ("agents", "Agent progress notes"),
                         ("research", "Research"), ("release", "Release notes"), ("docs", "Project docs")):
        if by_group.get(group):
            lines.append(f"- {label}: {by_group[group]} notes under `notes/{group}/`")
    if daily:
        lines.append(f"- What changed, day by day: {daily} notes under `daily/`")
    if code:
        lines.append(f"- Code map: {code['files']} source files in {code['folders']} folders under `code/` "
                     "(open a `_overview` note, or search for a file or function name)")
    lines += ["", "## Most recently changed", ""]
    lines += [f"- [[{n['path'][:-3]}|{n['title']}]] ({n['modified']:%Y-%m-%d})" for n in recent]
    (stage / "Home.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def status(out: Path) -> dict:
    manifest = _marker(out.expanduser())
    if manifest is None:
        return {"vault": str(out), "exists": False}
    built = datetime.strptime(manifest["built_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return {"vault": str(out), "exists": True, "age_hours": round((datetime.now(timezone.utc) - built).total_seconds() / 3600, 1),
            **{k: manifest.get(k) for k in ("built_at", "notes", "daily", "code", "redactions")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.brain_vault", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="(re)generate the vault")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--workspace", type=Path, help="folder with docs/agents, docs/research, STATE.md, OWNER-TODO.md")
    b.add_argument("--repo", type=Path, help="Git checkout: repo docs, release notes, commits, graphify-out/graph.json")
    b.add_argument("--graph", type=Path, help="graph.json (default: <repo>/graphify-out/graph.json)")
    b.add_argument("--extract", action="store_true", help="run `graphify extract . --code-only` in --repo first")
    b.add_argument("--raw-graph-dir", type=Path, help="also run `graphify export obsidian` into this separate folder")
    b.add_argument("--days", type=int, default=14, help="days of daily notes (default 14)")
    s = sub.add_parser("status", help="show when the vault was built")
    s.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(status(args.out), indent=2))
            return 0
        manifest = build(args.out, workspace=args.workspace, repo=args.repo, graph=args.graph, days=args.days,
                         extract=args.extract, raw_graph_dir=args.raw_graph_dir)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"brain vault: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: manifest[k] for k in ("built_at", "notes", "notes_by_group", "daily", "code", "redactions")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
