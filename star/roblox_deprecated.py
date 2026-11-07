"""Deprecated and beta-only Roblox API gate (a rung of the check-fix ladder, star/verify_ladder.py).

Data, both in data/roblox_api/:
  deprecated.json      Roblox's own inventory of deprecated engine members with replacements
                       (https://create.roblox.com/docs/reference/engine/deprecated.md, "Do NOT suggest any API listed
                       below"), regenerated with `python -m star.roblox_deprecated refresh`.
  feature_status.json  APIs the official docs mark as beta (Studio > File > Beta Features) or that have no docs page; such
                       code does not run in a published experience. Hand-kept, one source path per entry.

`findings(code, prompt)` reports (line, message) pairs, precision first:
  * `Enum.Type.Item` items, `Instance.new("Class")` of a deprecated class, and deprecated globals (`wait(`, `spawn(`,
    `table.getn(` ...) are exact;
  * `x:Member(`, `x.Member` and `x.Event:Connect(` count when the receiver's class is plain (a GetService alias,
    `Instance.new`, `:WaitForChild("Humanoid")`-style lookups, or a variable named like a class) and the member is
    deprecated on that class in the bundled API dump; or, for a method call or a signal with an unknown receiver, when
    no class has a live member of that name and the name is not a plain lower-case word (`entry.userId` on the user's
    own table is never reported: plain property reads need a known receiver);
  * methods the code defines itself and names the request mentions are never reported; a beta API the request names
    is allowed (the user asked for it).
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import date

from .luau_lint import _tokens
from .luau_roblox_rules import (DEPRECATED_CLASSES, _close, _is_ident, _literal_after, _locally_bound,
                                _service_aliases)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "roblox_api"
DEPRECATED_FILE = DATA_DIR / "deprecated.json"
FEATURE_FILE = DATA_DIR / "feature_status.json"
SOURCE_URL = "https://create.roblox.com/docs/reference/engine/deprecated.md"
MAX_FINDINGS = 8
_KINDS = {"Properties": "Property", "Methods": "Method", "Events": "Event", "Callbacks": "Callback",
          "Functions": "Function", "Enum": "EnumItem"}
_ROW = re.compile(r"^\| (.+?) \| `(.+?)` \| (.+?) \| (.*?) \|\s*$")
_LOOKUPS = ("WaitForChild", "FindFirstChild", "FindFirstChildOfClass", "FindFirstChildWhichIsA",
            "FindFirstAncestorOfClass", "FindFirstAncestorWhichIsA")
_PLAIN_WORD = re.compile(r"[a-z][a-z0-9]*\Z")


def parse_inventory(markdown: str) -> list[dict]:
    """The rows of deprecated.md: kind, owner (class, enum, 'Roblox globals'...), member, replacement, note."""
    rows: list[dict] = []
    kind = None
    for line in markdown.splitlines():
        heading = re.match(r"## Deprecated (\w+)", line)
        if heading:
            kind = _KINDS.get(heading.group(1))
            continue
        match = _ROW.match(line)
        if not match or kind is None or match.group(1).startswith("Class/Type"):
            continue
        owner, member, replacement, note = (part.strip() for part in match.groups())
        replacement = "" if replacement.startswith("*(") else replacement.strip("`")
        rows.append({"kind": kind, "owner": owner, "member": member, "replacement": replacement, "note": note[:160]})
    return rows


def refresh(markdown: str, *, path: Path = DEPRECATED_FILE, today: str | None = None) -> dict:
    rows = parse_inventory(markdown)
    if len(rows) < 100:
        raise ValueError(f"only {len(rows)} rows parsed: the page format changed, not writing")
    try:
        before = json.loads(path.read_text(encoding="utf-8"))["members"] if path.is_file() else []
    except (OSError, ValueError, KeyError):
        before = []
    data = {"source": SOURCE_URL, "fetched": today or date.today().isoformat(),
            "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(), "count": len(rows), "members": rows}
    head = json.dumps({k: v for k, v in data.items() if k != "members"}, ensure_ascii=False)[:-1]
    body = ",\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(head + ', "members": [\n' + body + "\n]}\n", encoding="utf-8", newline="\n")
    if before:   # members the docs list as deprecated now and did not before: queued for night school (#555)
        from . import api_dump_diff
        listed = api_dump_diff.diff_deprecated(before, rows)
        if listed:
            api_dump_diff.queue_changes({"newly_deprecated": listed, "new": {}})
            data["newly_listed"] = listed
    return data


@lru_cache(maxsize=1)
def _data() -> tuple[dict, dict, dict, dict]:
    """(member replacements by (owner, member), enum items, globals, feature status by api)."""
    members, enums, globals_ = {}, {}, {}
    try:
        rows = json.loads(DEPRECATED_FILE.read_text(encoding="utf-8"))["members"]
    except (OSError, ValueError, KeyError):
        rows = []
    for row in rows:
        note = row.get("note") or ""
        text = ("use " + row["replacement"]) if row["replacement"] else ("" if note.startswith("Deprecated") else note)
        if row["kind"] == "EnumItem":
            enums[(row["owner"], row["member"])] = text
        elif row["kind"] == "Function":
            globals_[(row["owner"], row["member"])] = text
        else:
            members[(row["owner"], row["member"])] = text
    try:
        features = {f["api"]: f for f in json.loads(FEATURE_FILE.read_text(encoding="utf-8"))["apis"]}
    except (OSError, ValueError, KeyError):
        features = {}
    return members, enums, globals_, features


@lru_cache(maxsize=1)
def _api():
    from .roblox_api_dataset import load
    dataset = load()
    live: set[str] = set()
    for cls in dataset.classes.values():
        if cls.deprecated:
            continue
        live.update(name for name, m in cls.members.items() if not m.deprecated)
    return dataset, frozenset(live)


def _replacement(owner_chain: list[str], member: str, dump_preferred: str | None) -> str:
    members = _data()[0]
    for owner in owner_chain:
        if (owner, member) in members:
            return members[(owner, member)]
    return ("use " + dump_preferred) if dump_preferred else ""


def _defined_here(words: list[str]) -> set[str]:
    """Names the code defines as methods or fields of its own tables (function T:name / T.name = ...)."""
    names = set()
    for i in range(len(words) - 3):
        if words[i] == "function" and words[i + 2] in (".", ":") and _is_ident(words[i + 3]):
            names.add(words[i + 3])
        if words[i] in (".", ":") and _is_ident(words[i + 1]) and words[i + 2] == "=" and words[i + 3] == "function":
            names.add(words[i + 1])
    return names


def _classes_of(code: str, tokens: list, words: list[str]) -> dict[str, str]:
    """Variable -> class where it is plain: services, Instance.new, child lookups by class name, class-named locals."""
    dataset, _ = _api()
    known = {name: cls for name, cls in _service_aliases(code, tokens, words).items() if cls in dataset.classes}
    lower = {name.lower(): name for name in dataset.classes}
    for i in range(1, len(words) - 4):
        if words[i] != "=" or not _is_ident(words[i - 1]) or (i >= 2 and words[i - 2] in (".", ":")):
            continue
        target, j = words[i - 1], i + 1
        if words[j:j + 4] == ["Instance", ".", "new", "("]:
            cls = _literal_after(code, tokens, j + 3)
        else:
            cls = None
            # ...:WaitForChild("Humanoid") / :FindFirstChildOfClass("Animator") ending the assigned expression
            for k in range(j, min(len(words) - 2, j + 24)):
                if words[k] in ("local", "end", "then", "do", "=", "function"):
                    break
                if words[k] == ":" and words[k + 1] in _LOOKUPS and words[k + 2] == "(":
                    if words[_close(words, k + 2) + 1:][:1] not in (["."], [":"], ["("]):
                        cls = _literal_after(code, tokens, k + 2)
                    break
        if cls in dataset.classes:
            known[target] = cls
        elif cls is None and target not in known and target.lower() in lower and \
                not dataset.classes[lower[target.lower()]].service:
            known[target] = lower[target.lower()]            # `local humanoid = ...`: named like the class
    for name in set(words):
        if _is_ident(name) and name not in known and name.lower() in lower and name[:1].islower() and \
                not dataset.classes[lower[name.lower()]].service:
            known[name] = lower[name.lower()]                # parameters such as `function(humanoid)`
    return known


def findings(code: str, prompt: str = "") -> list[tuple[int, str]]:
    if not isinstance(code, str) or not code.strip():
        return []
    dataset, live = _api()
    members, enums, globals_, features = _data()
    tokens = _tokens(code)
    words = [t.value for t in tokens]
    asked = prompt.lower()
    own = _defined_here(words)
    known = _classes_of(code, tokens, words)
    out: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()

    def add(index: int, message: str) -> None:
        key = (tokens[index].line, message)
        if key not in seen:
            seen.add(key)
            out.append(key)

    def beta(index: int, api: str) -> None:
        entry = features.get(api)
        if entry and api.split(".")[-1].lower() not in asked:
            add(index, f"{api} is {entry['status']} ({entry['note']}): it does not work in a published game; "
                       "use a released API")

    size = len(words)
    for i, word in enumerate(words):
        prev = words[i - 1] if i else ""
        nxt = words[i + 1] if i + 1 < size else ""
        if word == "Enum" and nxt == "." and i + 4 < size and words[i + 3] == "." and prev not in (".", ":"):
            enum, item = words[i + 2], words[i + 4]
            if (enum, item) in enums:
                text = enums[(enum, item)]
                add(i, f"Enum.{enum}.{item} is deprecated" + (f"; {text}" if text else ""))
            beta(i, f"Enum.{enum}.{item}")
            continue
        if word == "new" and words[i - 2:i] == ["Instance", "."] and nxt == "(":
            cls = _literal_after(code, tokens, i + 1)
            if cls and cls in dataset.classes and dataset.classes[cls].deprecated:
                text = DEPRECATED_CLASSES.get(cls) or dataset.classes[cls].preferred or ""
                text = ("use " + text) if text else ""
                add(i, f"the {cls} class is deprecated" + (f"; {text}" if text else ""))
            if cls:
                beta(i, cls)
            continue
        if prev not in (".", ":", "function", "local") and nxt == "(" and not _locally_bound(words, word):
            for owner in ("Roblox globals", "Luau globals"):
                if (owner, word) in globals_:
                    text = globals_[(owner, word)]
                    add(i, f"the global {word}() is deprecated" + (f"; {text}" if text else ""))
        if word == "table" and nxt == "." and i + 3 < size and words[i + 3] == "(" and prev not in (".", ":") \
                and ("table", words[i + 2]) in globals_:
            add(i, f"table.{words[i + 2]} is deprecated; use a for loop or #t")
        if words[i - 2:i] == ["Enum", "."]:
            continue
        if prev not in (".", ":") or not _is_ident(word) or word in own or word.lower() in asked.split():
            continue
        is_call = prev == ":" and nxt == "("
        is_signal = prev == "." and nxt == ":" and words[i + 2:i + 3] in (["Connect"], ["connect"], ["Once"], ["Wait"])
        receiver = words[i - 2] if i >= 2 and _is_ident(words[i - 2]) and (i < 3 or words[i - 3] not in (".", ":")) \
            else None
        cls = known.get(receiver) if receiver else None
        if receiver in ("game", "workspace"):
            cls = "DataModel" if receiver == "game" else "Workspace"
        if cls:
            member = dataset.member(cls, word)
            if member is not None and member.deprecated:
                text = _replacement(dataset.ancestry(cls), word, member.preferred)
                add(i, f"{cls}.{word} is deprecated" + (f"; {text}" if text else ""))
            elif member is not None:
                beta(i, f"{member.class_name}.{word}")
            continue
        if word in live or _PLAIN_WORD.match(word):
            continue
        owners = [owner for (owner, name) in members if name == word]
        # an unknown receiver's `.field` can be the user's own table: only calls, signals and PascalCase assignments
        is_set = prev == "." and nxt == "=" and words[i + 2:i + 3] != ["="] and word[:1].isupper()
        if owners and (is_call or is_signal or is_set):
            text = members[(owners[0], word)]
            add(i, f"{owners[0]}.{word} is deprecated" + (f"; {text}" if text else ""))
    return sorted(out)[:MAX_FINDINGS]


def rung(code: str, prompt: str = ""):
    """The ladder rung: pass, or fail with every finding (the fix call gets the replacement text)."""
    from .verify_ladder import Rung, _bounded
    try:
        found = findings(code, prompt)
    except Exception:
        return Rung("deprecated", "skip", "the deprecated-API check could not read this code")
    if not found:
        return Rung("deprecated", "pass")
    listing = "; ".join(f"line {line}: {message}" for line, message in found)
    first = re.sub(r";.*", "", found[0][1])
    return Rung("deprecated", "fail", _bounded(listing), found[0][0], len(found), "deprecated:" + first[:120])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["refresh"]:
        if len(args) > 1:
            text = Path(args[1]).read_text(encoding="utf-8")
        else:
            import httpx
            text = httpx.get(SOURCE_URL, timeout=30, follow_redirects=True).raise_for_status().text
        data = refresh(text)
        print(f"{data['count']} deprecated members written to {DEPRECATED_FILE}")
        return 0
    if args[:1] == ["check"] and len(args) > 1:
        for line, message in findings(Path(args[1]).read_text(encoding="utf-8")):
            print(f"{args[1]}:{line}: {message}")
        return 0
    print("usage: python -m star.roblox_deprecated refresh [deprecated.md] | check FILE.luau", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
