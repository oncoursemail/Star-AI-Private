"""API lock (G1): restrict the identifier after a typed Roblox receiver to members that exist.

While the model writes Luau, a llama.cpp sampler (server/api_lock/0004-api-lock-sampler.patch) watches the text. When
it ends in a receiver whose class is known with confidence (`game:GetService("Players")`, `Instance.new("Part")`, a
local bound to one of those, `game`, `workspace`, `script`, `Enum`, `Enum.Material`) followed by `:` or `.`, the
next identifier may only be a member of that class (with inheritance) from the local API dump, plus names the
request's own prompt already uses after a dot. When one name is left, the rest of it is put in as a draft that the
sampler accepts without a choice (free tokens). Unknown receivers get no mask.

This module is the reference implementation of that state machine (the C++ patch mirrors it; both run the shared
cases in server/api_lock/cases.json), the builder of the table the server loads, an audit that runs the lock over
existing code (a "block" on verified code is a false block), and the request field. Opt-in: setting
`api_lock_enabled`, off by default; a server without the patch ignores the field.

    python -m star.api_lock table OUT.json          write the class/member table for LLAMA_API_LOCK_TABLE
    python -m star.api_lock audit FILE...           blocks the lock would make on the code in .md/.lua/.jsonl files
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys

TABLE_VERSION = 1
MODE_OFF, MODE_FENCES, MODE_ALL = 0, 1, 2
DATA = Path(__file__).resolve().parents[1] / "data" / "roblox_api" / "roblox_api.json"

# Services whose `.` is followed by a member, not by a child's name: `.` is masked on these. Container services
# (Workspace, ReplicatedStorage, Lighting, StarterGui, Teams, SoundService, ...) are left out on purpose: their
# `.Name` is usually a child.
DOT_CLOSED_SERVICES = (
    "AssetService", "AvatarEditorService", "BadgeService", "CollectionService", "ContentProvider",
    "ContextActionService", "DataStoreService", "Debris", "GroupService", "GuiService", "HapticService",
    "HttpService", "InsertService", "KeyframeSequenceProvider", "LocalizationService", "LogService",
    "MarketplaceService", "MemoryStoreService", "MessagingService", "PathfindingService", "PhysicsService",
    "Players", "PolicyService", "ProximityPromptService", "RunService", "SocialService", "TeleportService",
    "TextService", "TweenService", "UserInputService", "VRService",
)
# Globals the lock knows; a local, parameter or assignment of the same name switches that global off.
GLOBALS = ("game", "workspace", "script", "Enum", "Instance")

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
# Receivers, matched at the end of the text before the separator. The match must not follow [A-Za-z0-9_.:].
# The same patterns are in the C++ patch (std::regex, ECMAScript); keep both in step.
RE_GETSERVICE = re.compile(r"game\s*:\s*GetService\s*\(\s*[\"']([A-Za-z0-9_]+)[\"']\s*\)$")
RE_NEW = re.compile(r"Instance\s*\.\s*new\s*\(\s*[\"']([A-Za-z0-9_]+)[\"']\s*(?:,[^()]*)?\)$")
RE_GAME_DOT = re.compile(r"game\s*\.\s*(" + IDENT + r")$")
RE_ENUM_DOT = re.compile(r"Enum\s*\.\s*(" + IDENT + r")$")
RE_NAME = re.compile(r"(" + IDENT + r")$")
RE_MEMBER_TAIL = re.compile(r"([.:])(" + IDENT + r")?$")
# Completed-line rules (bindings). Applied to the code part of a line (comment cut off).
RE_LOCAL_ONE = re.compile(r"^\s*local\s+(" + IDENT + r")\s*(?::\s*(" + IDENT + r")\s*)?=(?!=)\s*(.*)$")
RE_LOCAL_MANY = re.compile(r"^\s*local\s+(?!function\b)([A-Za-z_][A-Za-z0-9_\s,:]*?)\s*(?:=|$)")
RE_ASSIGN = re.compile(r"^\s*(" + IDENT + r")\s*=(?!=)\s*(.*)$")
RE_FOR = re.compile(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_\s,:]*?)\s*(?:=|\bin\b)")
RE_FUNCTION = re.compile(r"\bfunction\b\s*([A-Za-z0-9_.:]*)\s*\(([^)]*)\)")
RE_RHS_GETSERVICE = re.compile(r"^game\s*:\s*GetService\s*\(\s*[\"']([A-Za-z0-9_]+)[\"']\s*\)\s*;?\s*$")
RE_RHS_NEW = re.compile(r"^Instance\s*\.\s*new\s*\(\s*[\"']([A-Za-z0-9_]+)[\"']\s*(,\s*(" + IDENT + r"))?\s*\)\s*;?\s*$")
RE_PARENT_SET = re.compile(r"\.\s*Parent\s*=(?!=)\s*(" + IDENT + r")")
RE_NEW_WITH_PARENT = re.compile(r"Instance\s*\.\s*new\s*\(\s*[\"'][A-Za-z0-9_]+[\"']\s*,\s*(" + IDENT + r")\s*\)")
RE_DOT_NAME = re.compile(r"\.(" + IDENT + r")")
RE_LONG_OPEN = re.compile(r"\[(=*)\[")
RE_TYPE_LINE = re.compile(r"^\s*(?:export\s+)?type\s")
MAX_EXTRA = 2000


# --- the table ------------------------------------------------------------------------------------------------

def build_table(path: str | Path = DATA) -> dict:
    """The JSON table the server loads: every class (own members, own methods, superclass), services, enums."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    classes = {}
    for entry in raw["Classes"]:
        members = entry.get("Members") or []
        classes[entry["Name"]] = {
            "super": entry.get("Superclass", ""),
            "members": sorted({m["Name"] for m in members}),
            "methods": sorted({m["Name"] for m in members if m.get("MemberType") == "Function"}),
        }
    services = sorted(e["Name"] for e in raw["Classes"] if "Service" in (e.get("Tags") or []))
    return {
        "version": TABLE_VERSION,
        "studio_version": (raw.get("StarSource") or {}).get("studioVersion", ""),
        "classes": classes,
        "services": services,
        "dot_closed": [name for name in DOT_CLOSED_SERVICES if name in classes],
        "enums": {e["Name"]: sorted(i["Name"] for i in e.get("Items") or []) for e in raw["Enums"]},
    }


@dataclass
class Table:
    members: dict[str, tuple[str, ...]]     # inherited, sorted
    methods: dict[str, tuple[str, ...]]     # inherited Function members, sorted
    services: frozenset[str]
    dot_closed: frozenset[str]
    enums: dict[str, tuple[str, ...]]
    enum_names: tuple[str, ...]
    game_dot: tuple[str, ...]               # DataModel members + service names

    @classmethod
    def from_json(cls, data: dict) -> "Table":
        raw = data["classes"]

        def chain(name: str, key: str) -> tuple[str, ...]:
            names: set[str] = set()
            seen: set[str] = set()
            current = name
            while current in raw and current not in seen:
                seen.add(current)
                names.update(raw[current][key])
                current = raw[current]["super"]
            return tuple(sorted(names))

        members = {name: chain(name, "members") for name in raw}
        services = frozenset(data["services"])
        return cls(members=members, methods={name: chain(name, "methods") for name in raw}, services=services,
                   dot_closed=frozenset(data["dot_closed"]),
                   enums={k: tuple(v) for k, v in data["enums"].items()}, enum_names=tuple(sorted(data["enums"])),
                   game_dot=tuple(sorted(set(members.get("DataModel", ())) | services)))


_BUNDLED: Table | None = None


def bundled_table() -> Table:
    global _BUNDLED
    if _BUNDLED is None:
        _BUNDLED = Table.from_json(build_table())
    return _BUNDLED


# --- the state machine ----------------------------------------------------------------------------------------

def _is_word(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


def _scan(line: str) -> tuple[bool, int, str]:
    """(the end of the line is code, where its code part ends, the closing bracket of a long string/comment the
    line leaves open or '')."""
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "-" and line.startswith("--", i):
            m = RE_LONG_OPEN.match(line, i + 2)
            if not m:
                return False, i, ""
            close = "]" + m.group(1) + "]"
            j = line.find(close, m.end())
            if j < 0:
                return False, i, close
            i = j + len(close)
            continue
        if c in "\"'`":
            start = i
            i += 1
            while i < n and line[i] != c:
                i += 2 if line[i] == "\\" else 1
            if i >= n:
                return False, start, ""
            i += 1
            continue
        if c == "[":
            m = RE_LONG_OPEN.match(line, i)
            if m:
                close = "]" + m.group(1) + "]"
                j = line.find(close, m.end())
                if j < 0:
                    return False, i, close
                i = j + len(close)
                continue
        i += 1
    return True, n, ""


def _type_position(text: str, start: int) -> bool:
    """A name right after `:` or `->` (or on a `type` line) is a type: `player: Players.Player` names no member."""
    return text[:start].rstrip().endswith((":", ">")) or RE_TYPE_LINE.match(text) is not None


def _starts_clean(text: str, start: int) -> bool:
    return start == 0 or not (_is_word(text[start - 1]) or text[start - 1] in ".:")


@dataclass
class Binding:
    cls: str
    closed: bool        # `.` is masked: a fresh Instance.new nothing was parented to


@dataclass
class Lock:
    table: Table
    mode: int = MODE_FENCES
    extra: tuple[str, ...] = ()
    line: str = ""
    in_fence: bool = False
    fence_luau: bool = False
    in_long: str = ""                   # the closing bracket of an open long string/comment, '' when none
    bindings: dict[str, Binding] = field(default_factory=dict)
    killed: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.extra = tuple(sorted(set(self.extra)))[:MAX_EXTRA]

    # feeding text -----------------------------------------------------------------------------------------
    def feed(self, text: str) -> None:
        for ch in text:
            if ch == "\r":
                continue
            if ch == "\n":
                self._end_line(self.line)
                self.line = ""
            else:
                self.line += ch

    def _luau(self) -> bool:
        return self.mode == MODE_ALL or (self.in_fence and self.fence_luau)

    def _end_line(self, line: str) -> None:
        stripped = line.lstrip()
        if stripped.startswith("```"):
            if self.mode == MODE_FENCES:
                if self.in_fence:
                    self.in_fence = self.fence_luau = False
                else:
                    info = stripped[3:].strip().lower().split()
                    self.in_fence, self.fence_luau = True, bool(info) and info[0] in ("lua", "luau")
                    self.bindings, self.killed, self.in_long = {}, set(), ""
            return
        if not self._luau():
            return
        if self.in_long:
            if self.in_long in line:
                self.in_long = ""
            return
        _, cut, self.in_long = _scan(line)
        self._bind(line[:cut])

    def _kill(self, name: str) -> None:
        self.bindings.pop(name, None)
        if name in GLOBALS:
            self.killed.add(name)

    def _bind_rhs(self, name: str, rhs: str) -> bool:
        m = RE_RHS_GETSERVICE.match(rhs)
        if m and "game" not in self.killed and m.group(1) in self.table.services:
            self.bindings[name] = Binding(m.group(1), m.group(1) in self.table.dot_closed)
            return True
        m = RE_RHS_NEW.match(rhs)
        if m and "Instance" not in self.killed and m.group(1) in self.table.members:
            self.bindings[name] = Binding(m.group(1), True)
            if m.group(3) and m.group(3) in self.bindings:
                self.bindings[m.group(3)].closed = False
            return True
        return False

    def _kill_items(self, items: str) -> None:
        """Kill each `name` or `name: Type` of a declaration list. Type annotations bind nothing: the model writes
        them and they can be wrong (`store: DataStore` used as an OrderedDataStore) or narrowed later by `:IsA`."""
        for item in items.split(","):
            name = item.partition(":")[0].strip()
            if re.fullmatch(IDENT, name):
                self._kill(name)

    def _bind(self, code: str) -> None:
        m = RE_LOCAL_ONE.match(code)
        if m:
            self._kill(m.group(1))
            self._bind_rhs(m.group(1), m.group(3))
        else:
            m = RE_LOCAL_MANY.match(code)
            if m:
                self._kill_items(m.group(1))
            else:
                m = RE_ASSIGN.match(code)
                if m:
                    self._kill(m.group(1))
                    self._bind_rhs(m.group(1), m.group(2))
        m = RE_FOR.match(code)
        if m:
            self._kill_items(m.group(1))
        for m in RE_FUNCTION.finditer(code):
            if re.fullmatch(IDENT, m.group(1)):
                self._kill(m.group(1))
            self._kill_items(m.group(2))
        for regex in (RE_PARENT_SET, RE_NEW_WITH_PARENT):
            for m in regex.finditer(code):
                if m.group(1) in self.bindings:
                    self.bindings[m.group(1)].closed = False

    # contexts ---------------------------------------------------------------------------------------------
    def _receiver(self, text: str):
        """('class', name, closed) | ('game',) | ('enum_ns',) | ('enum', name) | None for text ending in a receiver."""
        tail = text[-300:]
        offset = len(text) - len(tail)
        m = RE_GETSERVICE.search(tail)
        if m and _starts_clean(text, offset + m.start()):
            name = m.group(1)
            if "game" in self.killed or name not in self.table.services:
                return None
            return ("class", name, name in self.table.dot_closed)
        m = RE_NEW.search(tail)
        if m and _starts_clean(text, offset + m.start()):
            if "Instance" in self.killed or m.group(1) not in self.table.members:
                return None
            return ("class", m.group(1), True)
        m = RE_GAME_DOT.search(tail)
        if m and _starts_clean(text, offset + m.start()):
            name = m.group(1)
            if "game" in self.killed or name not in self.table.services:
                return None
            return ("class", name, name in self.table.dot_closed)
        m = RE_ENUM_DOT.search(tail)
        if m and _starts_clean(text, offset + m.start()):
            if "Enum" in self.killed or m.group(1) not in self.table.enums:
                return None
            return ("enum", m.group(1))
        m = RE_NAME.search(tail)
        if m and _starts_clean(text, offset + m.start()) and not _type_position(text, offset + m.start()):
            name = m.group(1)
            if name in self.bindings:
                b = self.bindings[name]
                return ("class", b.cls, b.closed)
            if name in self.killed:
                return None
            if name == "game":
                return ("game",)
            if name == "workspace":
                return ("class", "Workspace", False)
            if name == "script":
                return ("class", "Script", False)
            if name == "Enum":
                return ("enum_ns",)
        return None

    def _allowed(self, receiver, sep: str) -> tuple[str, ...] | None:
        kind = receiver[0]
        if kind == "class":
            if sep == ":":
                return self.table.methods.get(receiver[1])
            if receiver[2]:
                return _merge(self.table.members.get(receiver[1], ()), self.extra)
            return None
        if kind == "game":
            return self.table.methods.get("DataModel") if sep == ":" else _merge(self.table.game_dot, self.extra)
        if kind == "enum_ns":
            return self.table.enum_names if sep == "." else None
        if kind == "enum":
            return self.table.enums[receiver[1]] if sep == "." else None
        return None

    def _code_now(self) -> bool:
        return (self._luau() and not self.in_long and not self.line.lstrip().startswith("```")
                and _scan(self.line)[0])

    def member_context(self) -> tuple[tuple[str, ...], str] | None:
        """(allowed names, partial identifier) when the text ends in receiver + separator + partial."""
        if not self._code_now():
            return None
        m = RE_MEMBER_TAIL.search(self.line[-300:])
        if not m:
            return None
        start = len(self.line) - len(self.line[-300:]) + m.start()
        receiver = self._receiver(self.line[:start])
        if receiver is None:
            return None
        allowed = self._allowed(receiver, m.group(1))
        partial = m.group(2) or ""
        if allowed is None or not _has_prefix(allowed, partial):
            return None
        return allowed, partial

    def receiver_context(self) -> dict[str, tuple[str, ...]]:
        """{separator: allowed names} when the text ends exactly in a known receiver."""
        if not self._code_now():
            return {}
        receiver = self._receiver(self.line)
        if receiver is None:
            return {}
        out = {}
        for sep in ".:":
            allowed = self._allowed(receiver, sep)
            if allowed is not None:
                out[sep] = allowed
        return out

    # questions the sampler asks ----------------------------------------------------------------------------
    def allows(self, piece: str) -> bool:
        """May the model write `piece` next?"""
        if not piece:
            return True
        ctx = self.member_context()
        if ctx is not None:
            return _piece_ok(ctx[0], ctx[1], piece)
        if piece[0] in ".:":
            allowed = self.receiver_context().get(piece[0])
            if allowed is not None:
                return _piece_ok(allowed, "", piece[1:])
        return True

    def forced(self) -> str:
        """The rest of the identifier when exactly one allowed name starts with the partial one, else ''."""
        ctx = self.member_context()
        if ctx is None or not ctx[1]:
            return ""
        allowed, partial = ctx
        i = bisect_left(allowed, partial)
        if i < len(allowed) and allowed[i].startswith(partial) and allowed[i] != partial and (
                i + 1 >= len(allowed) or not allowed[i + 1].startswith(partial)):
            return allowed[i][len(partial):]
        return ""


def _merge(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    return a if not b else tuple(sorted(set(a) | set(b)))


def _has_prefix(allowed: tuple[str, ...], prefix: str) -> bool:
    i = bisect_left(allowed, prefix)
    return i < len(allowed) and allowed[i].startswith(prefix)


def _ident_len(piece: str) -> int:
    k = 0
    while k < len(piece) and _is_word(piece[k]):
        k += 1
    return k


def _piece_ok(allowed: tuple[str, ...], partial: str, piece: str) -> bool:
    k = _ident_len(piece)
    if k == 0:
        return not partial or _contains(allowed, partial)
    if not partial and piece[0].isdigit():
        return True
    word = partial + piece[:k]
    if k == len(piece):
        return _has_prefix(allowed, word)
    return _contains(allowed, word)


def _contains(allowed: tuple[str, ...], name: str) -> bool:
    i = bisect_left(allowed, name)
    return i < len(allowed) and allowed[i] == name


def prompt_symbols(prompt: str) -> tuple[str, ...]:
    """Names the request already uses after a dot: the project's own symbols (child names, module fields)."""
    return tuple(sorted(set(RE_DOT_NAME.findall(prompt or ""))))[:MAX_EXTRA]


# --- audit: what the lock would have blocked in existing text -------------------------------------------------

@dataclass(frozen=True)
class Block:
    line: int
    name: str
    receiver_line: str


def audit_text(text: str, table: Table | None = None, *, mode: int = MODE_FENCES) -> list[Block]:
    """Every identifier in `text` the lock would not have allowed (character by character, like the sampler)."""
    lock = Lock(table or bundled_table(), mode)
    blocks: list[Block] = []
    line_no = 1
    i = 0
    while i < len(text):
        ch = text[i]
        if not lock.allows(ch):
            ctx = lock.member_context()
            j = i + 1 if ch in ".:" else i
            while j < len(text) and _is_word(text[j]):
                j += 1
            word = (ctx[1] if ctx else "") + text[i:j].lstrip(".:")
            blocks.append(Block(line_no, word, lock.line[-80:]))
            lock.feed(text[i:j] or ch)
            i = max(j, i + 1)
            continue
        lock.feed(ch)
        if ch == "\n":
            line_no += 1
        i += 1
    return blocks


def _texts(path: Path):
    if path.suffix == ".jsonl":
        for row in path.read_text(encoding="utf-8").splitlines():
            if row.strip():
                obj = json.loads(row)
                yield f"{path.name}:{obj.get('id', '?')}", obj.get("answer") or obj.get("completion") or obj.get("text") or ""
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        for tid, rec in (data.get("tasks") or {}).items():
            if rec.get("answer"):
                yield f"{path.name}:{tid}", rec["answer"]
    else:
        yield str(path), path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "table":
        Path(argv[1]).write_text(json.dumps(build_table(), separators=(",", ":")), encoding="utf-8")
        print(f"wrote {argv[1]}")
        return 0
    if len(argv) >= 2 and argv[0] == "audit":
        total = blocked = 0
        for name in argv[1:]:
            path = Path(name)
            for label, text in _texts(path):
                mode = MODE_ALL if path.suffix in (".lua", ".luau") else MODE_FENCES
                found = audit_text(text, mode=mode)
                total += 1
                blocked += bool(found)
                for b in found:
                    print(f"{label}:{b.line}: {b.name!r} after {b.receiver_line!r}")
        print(f"{blocked} of {total} texts have a block")
        return 0
    print("usage: python -m star.api_lock table OUT.json | audit FILE...")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
