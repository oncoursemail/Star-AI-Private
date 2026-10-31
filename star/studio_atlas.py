"""Studio Atlas: verified, production-quality Roblox systems that STAR retrieves as reference code (setting `studio_atlas`).

`data/studio_atlas/index.json` lists the systems; each one is strict-typed Luau under `systems/<id>/` with a README
(API, wiring, pitfalls) and a Lune test (`test.luau`). Retrieval is by capability: every system has tags (single
words) and phrases, and a request matches a system when its score reaches MIN_SCORE (a phrase is worth 3, a tag 1).
No model, no network, no embeddings: a request about something else gets nothing, so the prompt is never padded.
The block is reference material; the user's request comes first.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent / "data" / "studio_atlas"
HEADING = ("STUDIO ATLAS (verified reference systems: strict Luau, tested; adapt them to the request, "
           "the user's request comes first)")
MIN_SCORE = 3
PHRASE_WEIGHT = 3
MAX_SYSTEMS = 2
SECOND_SCORE_SHARE = 0.6
MAX_BLOCK_CHARS = 8000
MIN_CODE_CHARS = 1500
MAX_PROMPT_CHARS = 4000
_ID = re.compile(r"[a-z][a-z0-9-]{1,30}\Z")


@dataclass(frozen=True)
class System:
    id: str
    title: str
    summary: str
    tags: tuple[str, ...]
    phrases: tuple[str, ...]
    module: str
    readme: str
    test: str


def _strings(value: object, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(type(v) is str and 0 < len(v) <= 40 for v in value):
        raise ValueError(f"atlas index: invalid {what}")
    return tuple(v.lower() for v in value)


def parse_index(raw: str, root: Path = ROOT) -> list[System]:
    """The index file; anything malformed (or a path leaving the atlas folder, or a missing file) refuses it."""
    data = json.loads(raw)
    if type(data) is not dict or data.get("version") != 1 or not isinstance(data.get("systems"), list):
        raise ValueError("atlas index: unsupported format")
    systems, seen = [], set()
    for row in data["systems"]:
        if type(row) is not dict or type(row.get("id")) is not str or not _ID.fullmatch(row["id"]):
            raise ValueError("atlas index: invalid id")
        if row["id"] in seen:
            raise ValueError(f"atlas index: duplicate id {row['id']}")
        seen.add(row["id"])
        files = []
        for key in ("module", "readme", "test"):
            path = (root / str(row.get(key))).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                raise ValueError(f"atlas index: {row['id']}: bad {key} path")
            files.append(str(row[key]))
        if type(row.get("title")) is not str or type(row.get("summary")) is not str:
            raise ValueError(f"atlas index: {row['id']}: title and summary required")
        systems.append(System(row["id"], row["title"], row["summary"], _strings(row.get("tags"), "tags"),
                              _strings(row.get("phrases"), "phrases"), *files))
    return systems


_LOADED: dict[tuple[str, int, int], list[System]] = {}


def load(root: Path | None = None) -> list[System]:
    """The systems, cached per index version; [] when the index is missing."""
    root = Path(ROOT if root is None else root)
    index = root / "index.json"
    try:
        stat = index.stat()
    except OSError:
        return []
    key = (str(index), stat.st_mtime_ns, stat.st_size)
    if key not in _LOADED:
        _LOADED.clear()
        _LOADED[key] = parse_index(index.read_text(encoding="utf-8"), root)
    return _LOADED[key]


def _pattern(term: str) -> re.Pattern[str]:
    # Word start; short terms (ui, ban, mod) must be whole words, longer ones may continue (shop -> shopping).
    tail = r"\b" if len(term) <= 3 else r"\w*"
    return re.compile(r"\b" + re.escape(term) + tail)


def score(prompt: str, system: System) -> int:
    """Phrases are worth 3 each, tags 1 each; a tag that is also a phrase word is not counted twice."""
    text = prompt.lower()[:MAX_PROMPT_CHARS]
    total, covered = 0, set()
    for phrase in system.phrases:
        if _pattern(phrase).search(text):
            total += PHRASE_WEIGHT
            covered.update(phrase.split())
    for tag in system.tags:
        if tag not in covered and _pattern(tag).search(text):
            total += 1
    return total


def rank(prompt: str, systems: list[System]) -> list[tuple[int, System]]:
    """(score, system) best first, only those at or above MIN_SCORE."""
    scored = [(score(prompt, s), s) for s in systems]
    return sorted(((n, s) for n, s in scored if n >= MIN_SCORE), key=lambda pair: (-pair[0], pair[1].id))


def _code(path: Path) -> str:
    return "\n".join(line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) + "\n"


def render_system(system: System, root: Path, room: int) -> str:
    """README first (API, wiring, pitfalls), then as much of the module as fits; '' when even the README does not."""
    head = f"[studio atlas: {system.id}; {system.title}; passed luau-analyze strict and Lune tests]\n"
    readme = (root / system.readme).read_text(encoding="utf-8").strip() + "\n"
    tail = "[end studio atlas]\n"
    code = _code(root / system.module)
    fence_open, fence_close = f"Code ({Path(system.module).name}):\n```luau\n", "```\n"
    base = len(head) + len(readme) + len(fence_open) + len(fence_close) + len(tail)
    if len(head) + len(readme) + len(tail) > room:
        return ""
    if base + len(code) <= room:
        return head + readme + fence_open + code + fence_close + tail
    keep = room - base - len("-- (truncated)\n")
    if keep < MIN_CODE_CHARS:
        return head + readme + tail
    cut = code[:keep].rsplit("\n", 1)[0] + "\n-- (truncated)\n"
    return head + readme + fence_open + cut + fence_close + tail


def select(prompt: str, *, root: Path | None = None, max_chars: int = MAX_BLOCK_CHARS) -> tuple[str, list[System]]:
    """(block, systems) for this request; ('', []) when nothing matches or the atlas is missing."""
    if type(prompt) is not str or not prompt.strip() or max_chars < 600:
        return "", []
    root = Path(ROOT if root is None else root)
    try:
        ranked = rank(prompt, load(root))
    except (OSError, ValueError):
        return "", []
    parts, used = [], []
    for n, system in ranked[:MAX_SYSTEMS]:
        if used and n < ranked[0][0] * SECOND_SCORE_SHARE:
            break
        try:
            text = render_system(system, root, max_chars - sum(map(len, parts)))
        except OSError:
            continue
        if not text or (used and "(truncated)" in text):
            continue
        parts.append(text)
        used.append(system)
    return "".join(parts), used
