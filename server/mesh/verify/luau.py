"""Roblox Luau checks: API names against the Roblox API index, plus syntax/type errors from luau-analyze.

The API check is a light static pass (no full type inference): it follows expression chains from what it can type
for sure (game, workspace, game:GetService("X"), Instance.new("X"), Enum, event callback parameters, locals bound to
those) and reports names that cannot exist. A `.Name` that is not a member is treated as a child lookup (always
legal), so it is only reported when it cannot be a child: used as an event (`.X:Connect`), a case slip of a real
member (`humanoid.health`), or on a service that holds no children. Methods (`:X()`) must be members. Every suggestion
is a name from the API index; the only names not from the dump are the deprecated Luau globals below.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

from .apidump import ApiIndex, closest

# Roblox globals luau-analyze does not know (it knows the Luau built-ins: print, math, table, pcall, ...).
ROBLOX_GLOBALS = set("""game workspace script plugin shared Enum Instance task wait delay spawn tick time elapsedTime
settings UserSettings warn require typeof version printidentity stats Stats Game Workspace DebuggerManager
PluginManager ypcall LoadLibrary _G Axes BrickColor CatalogSearchParams CFrame Color3 ColorSequence
ColorSequenceKeypoint Content DateTime DockWidgetPluginGuiInfo Faces FloatCurveKey Font NumberRange NumberSequence
NumberSequenceKeypoint OverlapParams Path2DControlPoint PathWaypoint PhysicalProperties Random Ray RaycastParams Rect
Region3 Region3int16 RotationCurveKey SharedTable TweenInfo UDim UDim2 ValueCurveKey Vector2 Vector2int16 Vector3
Vector3int16 SecurityCapabilities buffer vector utf8 bit32""".split())

# Deprecated Luau globals in Roblox (not part of the class dump): name -> replacement.
DEPRECATED_GLOBALS = {"wait": "task.wait", "spawn": "task.spawn", "delay": "task.delay", "Game": "game",
                      "Workspace": "workspace", "ypcall": "pcall"}
REMOVED_GLOBALS = {"LoadLibrary"}

SIGNAL_METHODS = ["Connect", "Once", "Wait", "ConnectParallel"]
DEPRECATED_SIGNAL = {"connect": "Connect", "wait": "Wait", "connectParallel": "ConnectParallel"}
CLASS_ARG_METHODS = {"FindFirstChildOfClass", "FindFirstChildWhichIsA", "FindFirstAncestorOfClass",
                     "FindFirstAncestorWhichIsA", "FindFirstDescendantOfClass"}
CHILD_METHODS = {"WaitForChild", "FindFirstChild", "FindFirstAncestor", "FindFirstDescendant"}
# Services that hold user objects (children may have any name).
CONTAINERS = {"Workspace", "ReplicatedStorage", "ReplicatedFirst", "ServerStorage", "ServerScriptService",
              "StarterGui", "StarterPack", "StarterPlayer", "Lighting", "SoundService", "Teams", "Players", "Chat",
              "TextChatService", "MaterialService", "CoreGui", "LocalizationService", "InsertService", "TestService",
              "Selection", "VoiceChatService", "StarterPlayerScripts", "StarterCharacterScripts", "Debris"}
KEYWORDS = set("and break do else elseif end false for function if in local nil not or repeat return then true "
               "until while continue export type typeof".split()) - {"typeof"}
BINOPS = {"and", "..", "+", "-", "*", "/", "//", "%", "^", "==", "~=", "<", ">", "<=", ">="}

TOKEN = re.compile(r"""
    (?P<nl>\n) | (?P<ws>[ \t\r]+)
  | (?P<lcom>--\[(?P<lceq>=*)\[) | (?P<com>--[^\n]*)
  | (?P<lstr>\[(?P<lseq>=*)\[)
  | (?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)
  | (?P<num>0[xX][0-9a-fA-F_]+|0[bB][01_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.\.|\.\.=?|//=?|::|->|[=~<>]=|[-+*/%^]=|[-+*/%^#<>=(){}\[\];:,.?&|])
  | (?P<bad>.)""", re.X | re.S)


def tokenize(code: str) -> list[tuple[str, str, int]]:
    toks, line, pos = [], 1, 0
    while pos < len(code):
        m = TOKEN.match(code, pos)
        kind = m.lastgroup
        if kind in ("lcom", "lstr"):
            eq = m.group("lceq" if kind == "lcom" else "lseq")
            close = code.find("]" + eq + "]", m.end())
            end = len(code) if close < 0 else close + len(eq) + 2
            text = code[m.end():close if close >= 0 else len(code)]
            if kind == "lstr":
                toks.append(("str", text, line))
            line += code.count("\n", pos, end)
            pos = end
            continue
        text = m.group(kind)
        if kind == "str":
            toks.append(("str", text[1:-1], line))
            line += text.count("\n")
        elif kind in ("num", "name", "op", "bad"):
            toks.append(("name" if kind == "name" and text not in KEYWORDS else
                         "kw" if kind == "name" else kind, text, line))
        elif kind == "nl":
            line += 1
        pos = m.end()
    return toks


class _T:
    """A static type: kind 'class' (name), 'loose' (some Instance), 'event' (args), 'list' (element class)."""
    __slots__ = ("kind", "name", "args")

    def __init__(self, kind, name=None, args=None):
        self.kind, self.name, self.args = kind, name, args


def _cls(api: ApiIndex, name):
    if not name:
        return None
    if name == "Instance":
        return _T("loose")
    return _T("class", name) if name in api.classes else None


class LuauChecker:
    def __init__(self, api: ApiIndex, analyzer: str | None = None):
        self.api = api
        self.analyzer = analyzer if analyzer and os.path.isfile(analyzer) else None

    # ---- public --------------------------------------------------------------------------------------------------
    def check(self, code: str) -> list[dict]:
        problems = self.check_api(code)
        if self.analyzer:
            problems += self.check_syntax(code)
        problems.sort(key=lambda p: (p.get("line") or 0))
        return problems

    def check_syntax(self, code: str) -> list[dict]:
        fd, path = tempfile.mkstemp(suffix=".luau")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
            try:
                out = subprocess.run([self.analyzer, "--formatter=plain", path], capture_output=True, text=True,
                                     timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            except (OSError, subprocess.TimeoutExpired):
                return []
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        problems = []
        for ln in out.splitlines():
            m = re.match(r".*?:(\d+):[\d-]+: \(\w+\) (\w+): (.*)", ln)
            if not m:
                continue
            line, kind, msg = int(m.group(1)), m.group(2), m.group(3)
            if kind == "SyntaxError":
                problems.append(_p("syntax", "error", None, msg, None, line))
            elif kind == "TypeError":
                g = re.match(r"Unknown global '(\w+)'", msg)
                if g:
                    if g.group(1) not in ROBLOX_GLOBALS:
                        problems.append(_p("undefined_global", "info", g.group(1), msg, None, line))
                elif "Unknown require" not in msg:
                    problems.append(_p("type", "error", None, msg, None, line))
        return problems

    # ---- API pass ------------------------------------------------------------------------------------------------
    def check_api(self, code: str) -> list[dict]:
        self.toks = tokenize(code)
        self.problems = []
        for k, (kind, val, line) in enumerate(self.toks):
            # the player list only shows a folder named exactly "leaderstats"
            if kind == "str" and val != "leaderstats" and val.lower() == "leaderstats" and k >= 2 \
                    and self.toks[k - 1][1] == "=" and self.toks[k - 2][1] == "Name":
                self._add("roblox_rule", "error", val, f'the leaderboard only shows a folder named exactly '
                          f'"leaderstats", not "{val}"', '"leaderstats"', line)
        self.env: dict[str, _T | None] = {}
        self.pending_params: dict[int, list] = {}     # index of a `function` token -> param types
        self.chain_type: dict[int, tuple] = {}        # head index -> (type, end index)
        toks, i, n = self.toks, 0, len(self.toks)
        while i < n:
            kind, val, _ = toks[i]
            prev = toks[i - 1][1] if i else ""
            if kind == "kw" and val == "local" and i + 1 < n and toks[i + 1][1] != "function":
                self._local(i)
            elif kind == "kw" and val == "function":
                self._function(i)
            elif kind == "kw" and val == "for":
                self._for(i)
            elif kind == "name" and prev not in (".", ":", "function"):
                self._chain(i)
                if i + 1 < n and toks[i + 1][1] == "=" and prev not in ("local", ","):
                    self._bind([val], [None], i + 2)
            i += 1
        return self.problems

    def _bind(self, names, annots, expr_i):
        """Bind `names` from the expression starting at token expr_i (types known only for a single chain)."""
        t = None
        if len(names) == 1 and expr_i < len(self.toks) and self.toks[expr_i][0] == "name":
            self._chain(expr_i)
            ct, end = self.chain_type.get(expr_i, (None, expr_i))
            nxt = self.toks[end][1] if end < len(self.toks) else ""
            if nxt not in BINOPS:
                t = ct
        for k, name in enumerate(names):
            ann = annots[k] if k < len(annots) else None
            self.env[name] = _cls(self.api, ann) if ann else (t if k == 0 else None)

    def _local(self, i):
        toks, j, names, annots = self.toks, i + 1, [], []
        while j < len(toks) and toks[j][0] == "name":
            names.append(toks[j][1])
            ann = None
            if j + 2 < len(toks) and toks[j + 1][1] == ":" and toks[j + 2][0] == "name":
                ann = toks[j + 2][1]
                j += 2
            annots.append(ann)
            j += 1
            if j < len(toks) and toks[j][1] == "<":    # attributes like <const>
                j += 3
            if j < len(toks) and toks[j][1] == ",":
                j += 1
            else:
                break
        if j < len(toks) and toks[j][1] == "=":
            self._bind(names, annots, j + 1)
        else:
            for k, name in enumerate(names):
                self.env[name] = _cls(self.api, annots[k])

    def _function(self, i):
        toks, j = self.toks, i + 1
        while j < len(toks) and toks[j][1] != "(":
            j += 1
        types = self.pending_params.pop(i, [])
        k, j = 0, j + 1
        while j < len(toks) and toks[j][1] != ")":
            if toks[j][0] == "name":
                ann = toks[j + 2][1] if j + 2 < len(toks) and toks[j + 1][1] == ":" else None
                self.env[toks[j][1]] = _cls(self.api, ann) if ann else (types[k] if k < len(types) else None)
                k += 1
                j += 2 if ann else 0
            j += 1

    def _for(self, i):
        toks, j, names = self.toks, i + 1, []
        while j < len(toks) and toks[j][1] != "in" and toks[j][1] != "=":
            if toks[j][0] == "name":
                names.append(toks[j][1])
            j += 1
        for name in names:
            self.env[name] = None
        if j >= len(toks) or toks[j][1] != "in":
            return
        j += 1
        if j + 1 < len(toks) and toks[j][1] in ("ipairs", "pairs") and toks[j + 1][1] == "(":
            j += 2
        if j < len(toks) and toks[j][0] == "name":
            self._chain(j)
            t = self.chain_type.get(j, (None, j))[0]
            if t is not None and t.kind == "list" and len(names) >= 2:
                self.env[names[1]] = _cls(self.api, t.name) if t.name else _T("loose")

    def _args(self, j):
        """Tokens j.. form call args: `(...)`, a string or a table. Returns (first string arg, index after, open)."""
        toks = self.toks
        if j >= len(toks):
            return None, j, None
        if toks[j][0] == "str":
            return toks[j][1], j + 1, None
        if toks[j][1] not in ("(", "{"):
            return None, j, None
        close = self._match(j)
        first = toks[j + 1][1] if toks[j][1] == "(" and j + 2 <= close and toks[j + 1][0] == "str" \
            and toks[j + 2][1] in (",", ")") else None
        return first, close + 1, j

    def _match(self, j):
        pairs = {"(": ")", "{": "}", "[": "]"}
        depth, toks = 0, self.toks
        opener = toks[j][1]
        for k in range(j, len(toks)):
            if toks[k][1] == opener:
                depth += 1
            elif toks[k][1] == pairs[opener]:
                depth -= 1
                if depth == 0:
                    return k
        return len(toks) - 1

    def _chain(self, i):
        if i in self.chain_type:
            return
        toks = self.toks
        name, line = toks[i][1], toks[i][2]
        j = i + 1
        t = None
        if name in self.env:
            t = self.env[name]
        elif name in ("game", "Game"):
            t = _T("class", "DataModel")
        elif name in ("workspace", "Workspace"):
            t = _T("class", "Workspace")
        elif name == "script":
            t = _T("loose")
        elif name == "Enum":
            j = self._enum(i)
        elif name == "Instance" and j + 1 < len(toks) and toks[j][1] == "." and toks[j + 1][1] == "new":
            arg, j, _ = self._args(j + 2)
            t = self._instance_new(arg, line)
        if name not in self.env:
            if name in DEPRECATED_GLOBALS and (name[0].isupper() or (j < len(toks) and toks[j][1] == "(")):
                self._add("deprecated", "warning", name, f"'{name}' is deprecated",
                          DEPRECATED_GLOBALS[name], line)
            elif name in REMOVED_GLOBALS:
                self._add("unknown_api", "error", name, f"'{name}' was removed from Roblox", None, line)
        while j < len(toks):
            op = toks[j][1]
            if op in (".", ":") and j + 1 < len(toks) and toks[j + 1][0] in ("name", "kw"):
                mname, mline = toks[j + 1][1], toks[j + 1][2]
                nxt = j + 2
                calls = nxt < len(toks) and (toks[nxt][1] in ("(", "{") or toks[nxt][0] == "str")
                arg, after, open_i = self._args(nxt) if calls else (None, nxt, None)
                if op == ".":
                    t = self._dot(t, mname, mline, calls, nxt)
                    if calls:          # `obj.f(...)`: the call result is not typed
                        t, nxt = None, after
                else:
                    t = self._colon(t, mname, mline, arg, open_i)
                    nxt = after
                j = nxt
            elif op in ("(", "[", "{") or toks[j][0] == "str":
                t = None
                j = self._match(j) + 1 if toks[j][0] != "str" else j + 1
            else:
                break
        self.chain_type[i] = (t, j)

    def _enum(self, i):
        toks, api = self.toks, self.api
        j = i + 1
        if j + 1 >= len(toks) or toks[j][1] != "." or toks[j + 1][0] != "name":
            return j
        ename, line = toks[j + 1][1], toks[j + 1][2]
        j += 2
        enum = api.enums.get(ename)
        if enum is None:
            self._add("unknown_enum", "error", f"Enum.{ename}", f"Enum.{ename} does not exist",
                      _join(closest(ename, api.enums)), line)
            return j
        if enum.get("deprecated"):
            self._add("deprecated", "warning", f"Enum.{ename}", f"Enum.{ename} is deprecated", None, line)
        if j + 1 < len(toks) and toks[j][1] == "." and toks[j + 1][0] in ("name", "kw"):
            item = toks[j + 1][1]
            full = f"Enum.{ename}.{item}"
            if item in enum["items"]:
                if item in enum["dep"]:
                    rep = enum["dep"][item]
                    self._add("deprecated", "warning", full, f"{full} is deprecated",
                              f"Enum.{ename}.{rep}" if rep in enum["items"] else None, line)
            elif item in enum["legacy"]:
                self._add("deprecated", "warning", full, f"{full} is a legacy name",
                          f"Enum.{ename}.{enum['legacy'][item]}", line)
            elif item not in ("GetEnumItems", "FromName", "FromValue"):
                self._add("unknown_enum", "error", full, f"{full} does not exist",
                          _join(f"Enum.{ename}.{c}" for c in closest(item, enum["items"])), line)
            j += 2
        return j

    def _instance_new(self, cls_name, line):
        api = self.api
        if cls_name is None:
            return _T("loose")
        info = api.classes.get(cls_name)
        if info is None:
            creatable = [c for c, i in api.classes.items() if not set(i.get("tags", [])) & {"NotCreatable", "Service"}]
            self._add("unknown_class", "error", cls_name, f'Instance.new("{cls_name}"): no such class',
                      _join(closest(cls_name, creatable)), line)
            return _T("loose")
        tags = set(info.get("tags", []))
        if tags & {"NotCreatable", "Service"}:
            what = "a service (use game:GetService)" if "Service" in tags else "not creatable with Instance.new"
            self._add("not_creatable", "error", cls_name, f'"{cls_name}" is {what}', None, line)
        elif "Deprecated" in tags:
            pref = info.get("pref")
            self._add("deprecated", "warning", cls_name, f'class "{cls_name}" is deprecated',
                      pref if pref in api.classes else None, line)
        return _T("class", cls_name)

    def _dot(self, t, name, line, calls, nxt):
        api = self.api
        if t is None:
            return None
        if t.kind == "loose":
            ev = self._event_anywhere(name)
            return ev
        if t.kind != "class":
            return None
        found = api.member(t.name, name)
        if found is None:
            if t.name == "DataModel" and name in api.services:
                return _T("class", name)
            is_event_use = nxt + 1 < len(self.toks) and self.toks[nxt][1] == ":" and \
                self.toks[nxt + 1][1] in SIGNAL_METHODS + list(DEPRECATED_SIGNAL)
            twin = closest(name, api.members(t.name))
            case_twin = [c for c in twin if c.lower() == name.lower()]
            svc_strict = "Service" in api.classes[t.name].get("tags", []) and t.name not in CONTAINERS
            if t.name == "DataModel" and name.lower() in {s.lower() for s in api.services}:
                self._add("unknown_api", "error", f"game.{name}", f"game.{name}: names are case-sensitive",
                          _join(s for s in api.services if s.lower() == name.lower()), line)
            elif is_event_use:
                self._add("unknown_api", "error", f"{t.name}.{name}", f"{t.name} has no event '{name}'",
                          _join(closest(name, api.members(t.name, "e"), cutoff=0.6)), line)
            elif case_twin or svc_strict or calls:
                self._add("unknown_api", "error", f"{t.name}.{name}", f"{t.name} has no member '{name}'",
                          _join(case_twin or twin), line)
            else:
                return _T("loose")     # a child object
            return None
        owner, m = found
        self._member_flags(t.name, owner, name, m, line, ".")
        if m["k"] == "f" and calls:
            self._add("wrong_call", "error", f"{owner}.{name}", f"{name} is a method: call it with ':' not '.'",
                      f"{owner}:{name}", line)
            return None
        if m["k"] == "e":
            return _T("event", name, [self._arg_type(a) for a in m.get("args", [])])
        if m["k"] == "p":
            return _cls(api, m.get("t"))
        return None

    def _colon(self, t, name, line, arg, open_i):
        api = self.api
        if t is None:
            return None
        if t.kind == "event":
            if name in DEPRECATED_SIGNAL:
                self._add("deprecated", "warning", f"{t.name}:{name}", f"RBXScriptSignal:{name} is deprecated",
                          DEPRECATED_SIGNAL[name], line)
                name = DEPRECATED_SIGNAL[name]
            elif name not in SIGNAL_METHODS:
                self._add("unknown_api", "error", f"{t.name}:{name}", f"events have no method '{name}'",
                          _join(closest(name, SIGNAL_METHODS) or SIGNAL_METHODS[:1]), line)
                return None
            if name in ("Connect", "Once", "ConnectParallel") and open_i is not None:
                k = open_i + 1
                if k < len(self.toks) and self.toks[k][1] == "function":
                    self.pending_params[k] = t.args or []
            if name == "Wait":
                return (t.args or [None])[0]
            return None
        if t.kind == "loose":
            if name in SIGNAL_METHODS or name in DEPRECATED_SIGNAL:
                return None
            if name not in api.all_member_names():
                self._add("unknown_api", "error", name, f"no Roblox class has a method '{name}'",
                          _join(closest(name, api.members("Instance", "f") + api.members("BasePart", "f")
                                        + api.members("Humanoid", "f") + api.members("Model", "f"))), line)
                return None
            return self._call_result(None, name, arg, line)
        if t.kind != "class":
            return None
        found = api.member(t.name, name)
        if found is None:
            self._add("unknown_api", "error", f"{t.name}:{name}", f"{t.name} has no method '{name}'",
                      _join(closest(name, api.members(t.name, "f"))), line)
            return None
        owner, m = found
        self._member_flags(t.name, owner, name, m, line, ":")
        if m["k"] != "f":
            self._add("wrong_call", "error", f"{owner}.{name}", f"{name} is not a method", f"{owner}.{name}", line)
            return None
        return self._call_result(t.name, name, arg, line, m)

    def _call_result(self, cls_name, name, arg, line, m=None):
        api = self.api
        if name in ("GetService", "FindService") and arg is not None:
            if arg not in api.services:
                self._add("unknown_service", "error", arg, f'"{arg}" is not a Roblox service',
                          _join(closest(arg, api.services)), line)
                return _T("loose")
            if "Deprecated" in api.classes[arg].get("tags", []):
                self._add("deprecated", "warning", arg, f'service "{arg}" is deprecated', None, line)
            return _T("class", arg)
        if (name in CLASS_ARG_METHODS or name == "IsA") and arg is not None:
            if arg not in api.classes:
                self._add("unknown_class", "error", arg, f'{name}("{arg}"): no such class',
                          _join(closest(arg, api.classes)), line)
                return _T("loose")
            return None if name == "IsA" else _T("class", arg)
        if name in CHILD_METHODS:
            return _T("loose")
        if name == "GetPlayers":
            return _T("list", "Player")
        if name in ("GetChildren", "GetDescendants"):
            return _T("list", None)
        if name == "Clone" and cls_name:
            return _T("class", cls_name)
        return _cls(api, (m or {}).get("t"))

    def _member_flags(self, cls_name, owner, name, m, line, sep):
        api = self.api
        full = f"{owner}{sep}{name}"
        if m.get("ns") or m.get("sec") == "locked":
            self._add("not_accessible", "error", full, f"{full} cannot be used from game scripts (Roblox-internal)",
                      None, line)
        elif m.get("sec") == "plugin":
            self._add("plugin_only", "info", full, f"{full} works only in Studio plugins", None, line)
        if m.get("dep"):
            rep = api.replacement(cls_name, name, m)
            sugg = None
            if rep:
                here = api.member(cls_name, rep)
                if here and not here[1].get("dep") and rep != name:
                    sugg = f"{here[0]}{':' if here[1]['k'] == 'f' else '.'}{rep}"
                else:
                    others = [c for c, i in api.classes.items()
                              if rep in i["members"] and not i["members"][rep].get("dep")]
                    if others:
                        sugg = f"{others[0]}{':' if api.classes[others[0]]['members'][rep]['k'] == 'f' else '.'}{rep}"
            self._add("deprecated", "warning", full, f"{full} is deprecated", sugg, line)

    def _event_anywhere(self, name):
        for info in self.api.classes.values():
            m = info["members"].get(name)
            if m is not None and m["k"] == "e":
                return _T("event", name, None)
        return None

    def _arg_type(self, cls_name):
        return _cls(self.api, cls_name) if cls_name else None

    def _add(self, kind, severity, name, message, suggestion, line):
        p = _p(kind, severity, name, message, suggestion, line)
        if p not in self.problems:
            self.problems.append(p)


def _join(names) -> str | None:
    names = list(names)
    return " or ".join(names) if names else None


def _p(kind, severity, name, message, suggestion, line) -> dict:
    return {"kind": kind, "severity": severity, "name": name, "message": message, "suggestion": suggestion,
            "line": line}
