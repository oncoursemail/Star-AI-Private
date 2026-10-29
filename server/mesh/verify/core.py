"""Verify the code blocks of an answer, and the fix loop (failing blocks repaired by the fast tier, re-verified).

    report = Verifier(api, analyzer).verify(text, language=None)
    result = Verifier(...).fix(text, call_model, language=None, rounds=2)

A problem is {kind, severity (error | warning | info), name, message, suggestion, line}. A block is `ok` when it has
no error; it `needs_fix` when it has an error or a warning (deprecated API). Info never triggers a fix.
"""
from __future__ import annotations

import re
import time

from . import csharp, minecraft
from .apidump import ApiIndex
from .luau import LuauChecker

try:                                    # the game's own data (server/mesh/mcdata); without an index: hand-written checks
    from ..mcdata import commands as mc_commands, extract as mc_extract, index as mc_index, packs as mc_packs
except ImportError:                     # pragma: no cover
    mc_commands = mc_extract = mc_index = mc_packs = None

FENCE = re.compile(r"^(?P<ind>[ \t]{0,3})(?P<f>`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n(?P<code>.*?)^(?P=ind)(?P=f)[ \t]*$",
                   re.M | re.S)
OPEN_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n", re.M)
LANGS = {"lua": "luau", "luau": "luau", "rbxlua": "luau", "roblox": "luau",
         "cs": "csharp", "csharp": "csharp", "c#": "csharp", "unity": "csharp",
         "mcfunction": "mcfunction", "minecraft": "minecraft", "mcf": "mcfunction", "mc": "minecraft",
         "json": "json", "java": "java", "kotlin": "kotlin",
         # checked by the star-polyglot compilers (server/mesh/polyglot) when it is configured
         "python": "python", "py": "python", "python3": "python",
         "javascript": "javascript", "js": "javascript", "jsx": "javascript", "node": "javascript", "mjs": "javascript",
         "typescript": "typescript", "ts": "typescript", "tsx": "typescript",
         "cpp": "cpp", "c++": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "c": "c",
         "rust": "rust", "rs": "rust", "go": "go", "golang": "go",
         "gdscript": "gdscript", "gd": "gdscript", "godot": "gdscript",
         "sql": "sql", "sqlite": "sql", "bash": "shell", "sh": "shell", "shell": "shell"}
LOVE_HINT = re.compile(r"\blove\.\w+|\bio\.write\(|\bio\.read\(|\bio\.lines\(|\bos\.exit\(")
ROBLOX_HINT = re.compile(r"game:GetService|Instance\.new|\bworkspace\b|:Connect\(|script\.Parent|\btask\.wait|\bEnum\.")
# what a reader fills in: <spawn_x>, [X], X_POS, ~ ~ ~ (the fix loop never rewrites these)
PLACEHOLDER = re.compile(r"(?<![\w>])<[A-Za-z_][\w -]{0,30}>|(?<![\w\])}])\[[A-Za-z_][\w ]{0,30}\]"
                         r"|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|(?<!\S)[~^][-\d.]*[ \t]+[~^][-\d.]*[ \t]+[~^][-\d.]*(?!\S)")
LUAU_HINT = re.compile(r"game:GetService|Instance\.new|\bworkspace\b|\blocal\s+\w+\s*=|:Connect\(|\bend\b")
CS_HINT = re.compile(r"using\s+UnityEngine|:\s*MonoBehaviour|\bvoid\s+Update\s*\(")


def _detect(code: str, info: str) -> str:
    lang = LANGS.get(info.strip().split(" ")[0].lower(), "") if info.strip() else ""
    if lang == "luau" and info.strip().split(" ")[0].lower() == "lua" and LOVE_HINT.search(code) \
            and not ROBLOX_HINT.search(code):
        return "lua"                       # plain Lua (LÖVE / scripts), not Roblox
    if lang:
        return lang
    if CS_HINT.search(code):
        return "csharp"
    lines = [ln.strip() for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if lines and all(ln.startswith("/") and ln[1:].split(" ")[0] in minecraft.COMMANDS for ln in lines):
        return "minecraft"
    if LUAU_HINT.search(code):
        return "luau"
    return ""


def placeholders(code: str) -> set[str]:
    return {m.group(0) for m in PLACEHOLDER.finditer(code)}


def is_placeholder(name: str | None) -> bool:
    return bool(name) and bool(PLACEHOLDER.fullmatch(name.strip()))


def _bad(problems: list[dict]) -> tuple[int, int]:
    return (sum(p["severity"] == "error" for p in problems), sum(p["severity"] == "warning" for p in problems))


def extract_blocks(text: str, language: str | None = None) -> list[dict]:
    """Fenced code blocks with their spans. Text without fences is one block only when `language` is given
    ("auto" = detect it)."""
    blocks = []
    for m in FENCE.finditer(text):
        blocks.append({"start": m.start("code"), "end": m.end("code"), "code": m.group("code"),
                       "info": m.group("info").strip(), "line": text.count("\n", 0, m.start("code")) + 1})
    tail = OPEN_FENCE.search(text, blocks[-1]["end"] + 1 if blocks else 0)
    if tail:                                   # a last fence that is never closed runs to the end of the text
        blocks.append({"start": tail.end(), "end": len(text), "code": text[tail.end():],
                       "info": tail.group("info").strip(), "line": text.count("\n", 0, tail.end()) + 1})
    if not blocks and text.strip() and language:     # unfenced text is code only when the caller says so
        lang = LANGS.get(language.lower(), language) if language != "auto" else _detect(text, "")
        blocks.append({"start": 0, "end": len(text), "code": text, "info": lang, "line": 1})
    for b in blocks:
        b["language"] = _detect(b["code"], b["info"]) or (LANGS.get((language or "").lower(), "") if
                                                           len(blocks) == 1 else "")
    return blocks


class Verifier:
    def __init__(self, api: ApiIndex, analyzer: str | None = None, mc=None, *, polyglot=None):
        self.api = api
        self.luau = LuauChecker(api, analyzer)
        self.mc = mc if mc else None             # McIndex (server/mesh/mcdata) or None
        self.polyglot = polyglot           # server/mesh/polyglot client (None = those languages stay unchecked)
        self._pg: dict = {}

    def _poly(self, code: str, lang: str, prose: str) -> dict | None:
        if not self.polyglot or lang not in COMPILED or (lang == "java" and JAVA_PLUGIN.search(code)):
            return None                    # Paper/Fabric/NeoForge/Velocity Java belongs to the mc-plugins checker
        key = (lang, code)
        if key not in self._pg:
            self._pg[key] = self.polyglot.check(lang, code, prose)
        return self._pg[key]

    def prefetch(self, blocks: list[dict], prose: str):
        """Compile the blocks of one answer in parallel (the per-block results are then read from the cache)."""
        self._pg = {}
        if self.polyglot:
            todo = [(b["language"], b["code"]) for b in blocks if b["language"] in COMPILED
                    and not (b["language"] == "java" and JAVA_PLUGIN.search(b["code"]))]
            if len(todo) > 1:
                self._pg.update(self.polyglot.check_many(todo, prose))

    def check_block(self, code: str, lang: str, prose: str = "", path: str | None = None) -> tuple[list[dict], bool]:
        problems, checked = self._check_block(code, lang, prose, path)
        for p in problems:                      # a placeholder is for the reader, not a mistake to fix
            if p["severity"] != "info" and is_placeholder(p.get("name")):
                p["severity"] = "info"
        return problems, checked

    def _check_block(self, code: str, lang: str, prose: str = "", path: str | None = None) -> tuple[list[dict], bool]:
        if lang == "luau":
            return self.luau.check(code), True
        if lang == "csharp":
            light = csharp.check_csharp(code)
            pg = self._poly(code, lang, prose)
            if pg is None:
                return light, True
            # Roslyn is the authority on syntax; the light pass still knows Unity message names and `using`
            return [p for p in light if p["kind"] != "syntax" or "using UnityEngine" in (p.get("suggestion") or "")] \
                + pg["problems"], True
        if lang in POLYGLOT:
            pg = self._poly(code, lang, prose)
            return (pg["problems"], True) if pg is not None else ([], False)
        if self.mc is not None:
            if path and (path.startswith(("data/", "assets/")) or path.endswith("pack.mcmeta")):
                return mc_packs.check_file(path, code, self.mc, prose, lang), True
            if lang in ("minecraft", "mcfunction"):
                # a block only tagged mcfunction (no .mcfunction path) is often chat commands: a slash is a warning
                return mc_commands.check_commands(code, self.mc, prose, in_function=lang == "mcfunction",
                                                  slash="warning"), True
            if lang == "json" and ("pack_format" in code or re.search(r'^\s*\{\s*"pack"\s*:', code)):
                return mc_packs.check_file("pack.mcmeta", code, self.mc, prose, lang), True
            return [], False
        if lang in ("minecraft", "mcfunction"):
            return minecraft.check_commands(code, in_function=lang == "mcfunction"), True
        # only a block that looks like pack.mcmeta: an answer that names pack.mcmeta also shows other JSON files
        # (data/minecraft/tags/function/tick.json = {"values": [...]}), which are not pack.mcmeta
        if lang == "json" and ("pack_format" in code or re.search(r'^\s*\{\s*"pack"\s*:', code)):
            return minecraft.check_pack_mcmeta(code), True
        return [], False

    def verify(self, text: str, language: str | None = None, question: str | None = None) -> dict:
        """`question` (optional): the user's question; a Minecraft version it names decides the target version."""
        t0 = time.perf_counter()
        scope = question if question and self.mc is not None and mc_index.VERSION_RE.search(question) else text
        blocks = extract_blocks(text, language)
        self.prefetch(blocks, text)
        out = []
        prev = 0
        for k, b in enumerate(blocks):
            path = None
            if self.mc is not None:
                path, _ = mc_extract.block_path(text[prev:b["start"]], b["code"])
                prev = b["end"]
                if path and path.endswith(".mcfunction"):
                    b["language"] = "mcfunction"
                b["path"] = path
            problems, checked = self.check_block(b["code"], b["language"], scope, path)
            for p in problems:
                if p.get("line"):
                    p["answer_line"] = b["line"] + p["line"] - 1
            out.append({"index": k, "language": b["language"] or None, "checked": checked, "line": b["line"],
                        **({"path": path} if path else {}),
                        "ok": not any(p["severity"] == "error" for p in problems),
                        "needs_fix": any(p["severity"] in ("error", "warning") for p in problems),
                        "problems": problems})
        prose_problems = minecraft.check_datapack_paths(text) if "data/" in text else []
        if self.mc is not None:
            prose_problems += self._mc_prose(text, scope)
        return {"ok": all(b["ok"] for b in out) and not prose_problems,
                "needs_fix": any(b["needs_fix"] for b in out),
                "blocks": out, "problems": prose_problems,
                "ms": round((time.perf_counter() - t0) * 1000, 1),
                "dump": {k: self.api.meta.get(k) for k in ("version", "fetched")}}

    def _mc_prose(self, text: str, scope: str | None = None) -> list[dict]:
        """Minecraft problems outside checked code blocks: inline `/commands` in the prose and folder-tree blocks."""
        out = []
        cmds, _, tree = mc_extract.extract(text)
        for b, n, cmd in cmds:
            if b != -1:
                continue
            for p in mc_commands.check_commands(cmd, self.mc, scope or text):
                if p["severity"] == "error":
                    out.append({**p, "kind": "mc_inline", "name": p.get("name") or cmd[:40],
                                "message": f"inline command '/{cmd[:60]}': {p['message']}", "line": n})
        seen = {p["name"] for p in minecraft.check_datapack_paths(text)}
        for p in mc_packs.check_tree(tree, self.mc, scope or text):
            if p.get("name") not in seen:
                out.append({**p, "kind": p["kind"] + "_tree"})
        return out

    def fix(self, text: str, call_model, language: str | None = None, rounds: int = 2, docs=None,
            question: str | None = None) -> dict:
        """Repair the blocks that need it with `call_model(messages) -> str`, re-verify, at most `rounds` times.
        `docs(names) -> str` (optional): the official docs entries for the flagged names, given to the model."""
        t0 = time.perf_counter()
        first = report = self.verify(text, language, question)
        changes, done, model_ms = [], 0, 0.0
        renames = [p for p in report["problems"] if p["kind"] == "mc_datapack" and p.get("suggestion")]
        if renames:                            # prose: renamed datapack folders have one exact replacement
            for p in renames:
                text = text.replace(p["name"], p["suggestion"])
            changes.append({"round": 0, "block": None, "fixed": [p["message"] for p in renames]})
            report = self.verify(text, language, question)
        for rnd in range(1, rounds + 1):
            todo = [b for b in report["blocks"] if b["needs_fix"]]
            if not todo:
                break
            done = rnd
            spans = extract_blocks(text, language)
            edits = []
            for b in todo:
                span = spans[b["index"]]
                t1 = time.perf_counter()
                try:
                    ref = docs(problem_names(b["problems"])) if docs else ""
                    reply = call_model(fix_messages(span["code"], b["language"], b["problems"], ref))
                except Exception as e:     # model unreachable: keep the answer, report it
                    changes.append({"round": rnd, "block": b["index"], "error": f"fix call failed: {e}"})
                    continue
                finally:
                    model_ms += (time.perf_counter() - t1) * 1000
                new = code_from_reply(reply, span["code"])
                if not new or new.strip() == span["code"].strip():
                    continue
                flagged = {p.get("name") for p in b["problems"] if p.get("name")}
                lost = sorted(ph for ph in placeholders(span["code"]) if ph not in flagged and ph not in new)
                if lost:
                    changes.append({"round": rnd, "block": b["index"],
                                    "rejected": f"the fix rewrote the placeholder {lost[0]}; kept as written"})
                    continue
                if _bad(self.check_block(new, b["language"], question if question and mc_index and mc_index.VERSION_RE.search(question) else text, b.get("path"))[0]) >= _bad(b["problems"]):
                    changes.append({"round": rnd, "block": b["index"],
                                    "rejected": "the fix did not remove problems; kept as written"})
                    continue
                edits.append((span, new, b))
            for span, new, b in sorted(edits, key=lambda e: -e[0]["start"]):
                text = text[:span["start"]] + new + text[span["end"]:]
            report = self.verify(text, language, question)
            for span, new, b in edits:
                after = report["blocks"][b["index"]] if b["index"] < len(report["blocks"]) else None
                changes.append({"round": rnd, "block": b["index"], "fixed": [p["message"] for p in b["problems"]
                                                                             if p["severity"] != "info"],
                                "remaining": [p["message"] for p in (after or {}).get("problems", [])
                                              if p["severity"] != "info"]})
            if not edits and not any(c.get("rejected") and c["round"] == rnd for c in changes):
                break
        return {"answer": text, "ok": report["ok"], "rounds": done, "changes": changes,
                "before": _summary(first), "after": _summary(report), "verify": report,
                "model_ms": round(model_ms), "ms": round((time.perf_counter() - t0) * 1000)}


def _summary(report: dict) -> dict:
    probs = [p for b in report["blocks"] for p in b["problems"]] + report["problems"]
    return {"errors": sum(p["severity"] == "error" for p in probs),
            "warnings": sum(p["severity"] == "warning" for p in probs),
            "blocks_failing": sum(not b["ok"] for b in report["blocks"])}


FIX_SYSTEM = ("You repair code. You get one code block and a list of problems found by a verifier that checks every "
              "API name against the official API list. Fix exactly those problems and keep everything else "
              "unchanged (same structure, names, comments). Placeholders the reader fills in ([X], <x>, X_POS, "
              "~ ~ ~) stay exactly as written. When a problem gives a suggestion, use it. When it lists the real "
              "members instead, the name usually belongs to another object (for example a service): write what the "
              "code means, which may need that other object; never just take the closest-sounding name. Never invent "
              "an API: if a call does not exist and there is no suggestion, rewrite that part with APIs you are sure "
              "exist. Reply with only the corrected code in one fenced code block, nothing else.")
FENCE_TAG = {"luau": "lua", "csharp": "csharp", "minecraft": "mcfunction", "mcfunction": "mcfunction", "shell": "bash"}
POLYGLOT = {"python", "javascript", "typescript", "java", "cpp", "c", "rust", "go", "gdscript", "lua", "sql", "shell"}
COMPILED = POLYGLOT | {"csharp"}                   # sent to the star-polyglot compilers
# any non-JDK import, or a Bukkit/Paper/Fabric fragment without imports: the mc-plugins checker's job
JAVA_PLUGIN = re.compile(r"^\s*import\s+(?:static\s+)?(?!java\.|javax\.)[\w.]+|\b(?:JavaPlugin|CommandSender|"
                         r"CommandExecutor|Bukkit\.|@EventHandler|PlayerJoinEvent|ModInitializer|ServerPlayerEntity|"
                         r"MinecraftServer|getServer\(\))", re.M)
COMPILE_FIX_SYSTEM = ("You repair code. You get one code block and the errors the real compiler / type checker / engine "
                      "reported for it. Fix exactly those errors and keep everything else unchanged (same structure, "
                      "names, comments, behaviour). Placeholders the reader fills in ([X], <x>, X_POS) stay exactly as "
                      "written. When an error gives a suggestion, use it. When it lists real members of a class instead, use "
                      "the one that does what the code means (or rewrite that part with other real APIs); never just take "
                      "the closest-sounding name. Never invent an API: use only functions and "
                      "members you are sure exist in that language/engine version. Reply with only the corrected code in "
                      "one fenced code block, nothing else.")


HINT_OWNER = re.compile(r"'(\w+)' is an? (?:event|method|property) of ([\w, ]+?), not of")


def problem_names(problems: list[dict]) -> list[str]:
    """API names worth looking up in the docs for these problems: the flagged name, its suggestions and the class the
    hint says the member really belongs to (PlayerRemoving -> Players.PlayerRemoving)."""
    out = []
    for p in problems:
        if p["severity"] == "info":
            continue
        names = [p.get("name")] + (p.get("suggestion") or "").split(" or ")
        m = HINT_OWNER.search(p.get("hint") or p.get("message") or "")
        if m:
            names += [f"{c.strip()}.{m.group(1)}" for c in m.group(2).split(",")]
        for n in names:
            n = (n or "").strip()
            if n and n not in out and not is_placeholder(n):
                out.append(n)
    return out[:12]


def fix_messages(code: str, language: str, problems: list[dict], docs: str = "") -> list[dict]:
    lines = []
    for p in problems:
        if p["severity"] == "info":
            continue
        s = f"- line {p['line']}: {p['message']}" if p.get("line") else f"- {p['message']}"
        if p.get("suggestion"):
            s += f" (use: {p['suggestion']})"
        if p.get("candidates"):
            s += f"\n  real members of that class you may use: {', '.join(p['candidates'])}"
        lines.append(s)
    tag = FENCE_TAG.get(language, language or "")
    ref = ("\n\nOfficial docs for these names (exact signatures; follow them):\n" + docs) if docs else ""
    return [{"role": "system", "content": COMPILE_FIX_SYSTEM if language in POLYGLOT else FIX_SYSTEM},
            {"role": "user", "content": f"Language: {language}\n\nCode:\n```{tag}\n{code.rstrip()}\n```\n\n"
                                        "Problems:\n" + "\n".join(lines) + ref}]


def code_from_reply(reply: str, old: str) -> str:
    reply = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).strip()
    m = FENCE.search(reply + ("\n" if not reply.endswith("\n") else ""))
    code = m.group("code") if m else reply
    if old.endswith("\n") and not code.endswith("\n"):
        code += "\n"
    return code
