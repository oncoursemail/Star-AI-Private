"""Minecraft Java plugins and mods: Paper/Spigot (plugin.yml, paper-plugin.yml), Velocity, Fabric, NeoForge.

All Java blocks of one answer are compiled together by the warm javac service (jvm/CompileServer.java, in its own
container; `JvmClient`), against the real API jars of the detected target. Its diagnostics come back with the real
member names of the class (reflection on those jars) and the javadoc deprecation note, so the fix loop gets
"sendActionbar does not exist on Player; real: sendActionBar". Descriptor files are checked here (stdlib only):
plugin.yml keys, main class, api-version, commands used by getCommand("x"); fabric.mod.json; neoforge.mods.toml.

    problems_by_block = check_answer(blocks, text, jvm)   # {block index: [problem, ...]}

A block that is only a fragment (no class) is wrapped in a class; for it only API facts count (a method or constant
that does not exist on a real API class, removed API), never "variable x not found" from the missing context.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

try:
    import tomllib
except ImportError:                     # Python < 3.11
    tomllib = None

TYPE_DECL = re.compile(r"^[ \t]*(?:(?:public|protected|private|abstract|final|sealed|non-sealed|static|strictfp)\s+)*"
                       r"(?:class|interface|enum|record|@interface)\s+([A-Z_$][\w$]*)", re.M)
PUBLIC_TYPE = re.compile(r"^(?:(?:abstract|final|sealed|non-sealed|strictfp)\s+)*public\s+(?:(?:abstract|final|sealed|"
                         r"non-sealed|static|strictfp)\s+)*(?:class|interface|enum|record|@interface)\s+([A-Z_$][\w$]*)",
                         re.M)
PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
IMPORT = re.compile(r"^\s*import\s+(static\s+)?([\w.]+)(\.\*)?\s*;", re.M)
METHOD_DECL = re.compile(r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|protected|private|static|final|synchronized|"
                         r"abstract|default)\s+)*(?:<[^>]+>\s+)?[\w.$<>\[\], ?]+\s+\w+\s*\([^;{]*\)\s*(?:throws\s+[\w., ]+)?"
                         r"\s*\{", re.M)
SAVE_RESOURCE = re.compile(r"saveDefaultConfig\(\s*\)|saveResource\(\s*\"([^\"]+)\"")
GET_COMMAND = re.compile(r"getCommand\(\s*\"([^\"]+)\"\s*\)")
MOD_ANN = re.compile(r"@Mod\(\s*(?:value\s*=\s*)?(\"[^\"]*\"|[\w.]+)\s*\)")
VELOCITY_ID = re.compile(r"@Plugin\s*\((?:[^)]|\n)*?\bid\s*=\s*\"([^\"]*)\"")
NAME_NEAR = re.compile(r"(paper-plugin\.yml|plugin\.yml|bungee\.yml|fabric\.mod\.json|neoforge\.mods\.toml|mods\.toml|"
                       r"velocity-plugin\.json|build\.gradle(?:\.kts)?|pom\.xml|[\w-]+\.mixins\.json)", re.I)
API_VERSION = re.compile(r"^(1\.(1[3-9]|2[01])(\.\d{1,2})?|2[6-9]\.\d{1,2}(\.\d{1,2})?)$")
MOD_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
FABRIC_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
VELOCITY_ID_OK = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

TARGET_HINTS = [("velocity", re.compile(r"\bcom\.velocitypowered\.")),
                ("neoforge", re.compile(r"\bnet\.neoforged\.")),
                ("forge", re.compile(r"\bnet\.minecraftforge\.")),
                ("fabric", re.compile(r"\bnet\.fabricmc\.")),
                ("paper", re.compile(r"\b(org\.bukkit|io\.papermc\.paper|com\.destroystokyo\.paper|org\.spigotmc|"
                                     r"net\.md_5\.bungee\.api\.chat)\.")),
                ("bungee", re.compile(r"\bnet\.md_5\.bungee\.api\.plugin\."))]
# Fabric: Yarn names (Loom default for years) vs official Mojang names (Fabric example mod since 1.21)
MOJMAP = re.compile(r"\bnet\.minecraft\.(world\.|network\.chat\.|resources\.|core\.|server\.level\.|commands\.Commands\b)")
YARN = re.compile(r"\bnet\.minecraft\.(entity\.|text\.|util\.Identifier\b|server\.network\.ServerPlayerEntity\b|"
                  r"registry\.|item\.Item\b|server\.command\.CommandManager\b|util\.math\.)")
SNIPPET_IMPORTS = {
    "paper": "org.bukkit org.bukkit.entity org.bukkit.event org.bukkit.event.player org.bukkit.event.block "
             "org.bukkit.event.entity org.bukkit.event.inventory org.bukkit.inventory org.bukkit.inventory.meta "
             "org.bukkit.command org.bukkit.plugin org.bukkit.plugin.java org.bukkit.scheduler org.bukkit.block "
             "net.kyori.adventure.text net.kyori.adventure.text.format java.util",
    "velocity": "com.velocitypowered.api.proxy com.velocitypowered.api.event com.velocitypowered.api.plugin "
                "com.velocitypowered.api.command net.kyori.adventure.text java.util",
}
SNIPPET_BASE = {"paper": "extends org.bukkit.plugin.java.JavaPlugin implements org.bukkit.event.Listener, "
                         "org.bukkit.command.CommandExecutor"}
# a fragment uses variables from code it does not show; javac skips the method check of a call whose argument is
# unknown, so the usual names get their usual type (only for this check)
_B = {"Player": "org.bukkit.entity.Player", "CommandSender": "org.bukkit.command.CommandSender",
      "Location": "org.bukkit.Location", "ItemStack": "org.bukkit.inventory.ItemStack"}
SNIPPET_VARS = {
    "paper": {"player": _B["Player"], "p": _B["Player"], "target": _B["Player"], "sender": _B["CommandSender"],
              "plugin": "org.bukkit.plugin.java.JavaPlugin", "world": "org.bukkit.World", "item": _B["ItemStack"],
              "stack": _B["ItemStack"], "itemStack": _B["ItemStack"], "loc": _B["Location"],
              "location": _B["Location"], "block": "org.bukkit.block.Block", "entity": "org.bukkit.entity.Entity",
              "inventory": "org.bukkit.inventory.Inventory", "inv": "org.bukkit.inventory.Inventory",
              "args": "String[]", "label": "String", "config": "org.bukkit.configuration.file.FileConfiguration",
              "meta": "org.bukkit.inventory.meta.ItemMeta", "server": "org.bukkit.Server",
              "command": "org.bukkit.command.Command", "cmd": "org.bukkit.command.Command"},
    "velocity": {"player": "com.velocitypowered.api.proxy.Player", "server": "com.velocitypowered.api.proxy.ProxyServer",
                 "proxy": "com.velocitypowered.api.proxy.ProxyServer", "logger": "org.slf4j.Logger"},
}


def _p(kind, message, severity="error", name=None, suggestion=None, line=None, **extra) -> dict:
    p = {"kind": kind, "severity": severity, "name": name, "message": message, "suggestion": suggestion, "line": line}
    p.update({k: v for k, v in extra.items() if v})
    return p


class JvmClient:
    """POST /compile to the warm javac service. `None` from compile() = service down or late (static checks only)."""

    def __init__(self, url: str, token: str, timeout_s: float = 4.0):
        self.url, self.token, self.timeout_s = url.rstrip("/"), token, timeout_s

    @classmethod
    def from_config(cls, cfg: dict):
        url, tf = cfg.get("jvm_url"), cfg.get("jvm_token_file")
        if not url or not tf:
            return None
        try:
            with open(tf, encoding="utf-8") as f:
                token = f.read().strip()
        except OSError:
            return None
        return cls(url, token, float(cfg.get("jvm_timeout_s", 4.0))) if token else None

    def compile(self, target: str, files: dict) -> dict | None:
        req = urllib.request.Request(self.url + "/compile", json.dumps({"target": target, "files": files}).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return json.loads(r.read())
        except (OSError, ValueError):
            return None


# ---- what each block is ----------------------------------------------------------------------------------------
def block_role(b: dict, text: str) -> str:
    """java | kotlin | plugin.yml | paper-plugin.yml | bungee.yml | fabric.mod.json | neoforge.mods.toml | mods.toml |
    velocity-plugin.json | build | other"""
    info = (b.get("info") or "").lower().split(" ")[0]
    code = b["code"]
    if info in ("kotlin", "kt", "kts"):
        return "kotlin" if "build.gradle" not in code[:200] else "build"
    first = code.lstrip().splitlines()[0] if code.strip() else ""
    near = NAME_NEAR.findall(first) or NAME_NEAR.findall(text[max(0, b["start"] - 260):b["start"]])
    name = near[-1].lower() if near else ""
    if b.get("language") == "java" or info == "java":
        return "java"
    if name.startswith("build.gradle") or name == "pom.xml" or info in ("groovy", "gradle", "xml"):
        return "build"
    if info in ("yaml", "yml") or (not info and re.search(r"^main:\s*\S", code, re.M)):
        if name in ("paper-plugin.yml", "bungee.yml"):
            return name
        return "plugin.yml" if re.search(r"^main:\s*\S", code, re.M) or name == "plugin.yml" else "other"
    if info in ("toml",) or "modLoader" in code or "[[mods]]" in code:
        return "neoforge.mods.toml" if name != "mods.toml" else "mods.toml"
    if info in ("json", "json5", "") and '"schemaVersion"' in code:
        return "fabric.mod.json"
    if info in ("json", "") and name == "velocity-plugin.json":
        return "velocity-plugin.json"
    if not info and (TYPE_DECL.search(code) and IMPORT.search(code)):
        return "java"
    return "other"


def detect_target(java_text: str, prose: str = "") -> str | None:
    for name, rx in TARGET_HINTS:
        if rx.search(java_text):
            if name != "fabric":
                return name
            break
    else:                                   # only vanilla classes: the question says which loader
        if not re.search(r"\bnet\.minecraft\.", java_text):
            return None
        if re.search(r"neoforge", prose, re.I):
            return "neoforge"
    return "fabric-mojmap" if len(MOJMAP.findall(java_text)) > len(YARN.findall(java_text)) else "fabric"


def java_path(code: str, k: int) -> tuple[str, str, str]:
    """(file path, package, main type name) of one Java block."""
    pkg = PACKAGE.search(code)
    pkg = pkg.group(1) if pkg else ""
    pub = PUBLIC_TYPE.search(code)
    name = pub.group(1) if pub else (TYPE_DECL.search(code).group(1) if TYPE_DECL.search(code) else f"Snippet{k}")
    return ("/".join(pkg.split(".")) + "/" if pkg else "") + name + ".java", pkg, name


def wrap_snippet(code: str, k: int, target: str, extra_imports: list[str], fields: str = "") -> tuple[str, int]:
    """A fragment as a compilable class. Returns (source, number of lines added before the fragment)."""
    imports = [m.group(0).strip() for m in IMPORT.finditer(code)]
    body = IMPORT.sub("", code)
    head = sorted(set(imports + extra_imports + [f"import {p}.*;" for p in SNIPPET_IMPORTS.get(target, "java.util")
                                                    .split()]))
    base = SNIPPET_BASE.get(target, "")
    members = bool(METHOD_DECL.search(body)) or re.search(r"^\s*(private|public|protected|static)\s", body, re.M)
    lines = head + [f"abstract class Snippet{k} {base} {{ {fields}"]
    if not members:
        lines.append("void __run() throws Exception {")
    # IMPORT.sub keeps the line breaks of removed imports, so fragment line n is still line n of `body`
    src = "\n".join(lines) + "\n" + body + ("\n}" if not members else "") + "\n}\n"
    return src, len(lines)


# ---- descriptors -----------------------------------------------------------------------------------------------
def parse_plugin_yml(code: str) -> tuple[dict, dict, list[dict]]:
    """(top-level scalars, commands {name: {aliases: [...]}}, problems) for the plugin.yml subset Bukkit reads."""
    top, commands, problems = {}, {}, []
    section, cmd, cmd_indent, alias_list = None, None, None, False
    for n, raw in enumerate(code.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            problems.append(_p("yaml", "plugin.yml is indented with a tab: YAML allows only spaces, the server "
                                       "refuses to load the plugin (InvalidDescriptionException)", line=n))
            continue
        line = re.sub(r"\s+#.*$", "", raw).rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        ind = len(line) - len(line.lstrip())
        s = line.strip()
        if ind == 0:
            m = re.match(r"^([\w-]+):\s*(.*)$", s)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip("'\"")
            if key in top:
                problems.append(_p("yaml", f"plugin.yml has the key '{key}' twice", line=n, name=key))
            top[key] = val
            section, cmd = key, None
            continue
        if section != "commands":
            continue
        m = re.match(r"^([\w:.-]+):\s*(.*)$", s)
        if cmd_indent is None or ind <= cmd_indent:
            if m:
                cmd_indent, cmd, alias_list = ind, m.group(1), False
                commands[cmd] = {"aliases": [], "line": n}
            continue
        if cmd and m and m.group(1) == "aliases":
            v = m.group(2).strip()
            if v.startswith("["):
                commands[cmd]["aliases"] += [a.strip().strip("'\"") for a in v.strip("[]").split(",") if a.strip()]
            elif v:
                commands[cmd]["aliases"].append(v.strip("'\""))
            alias_list = not v
        elif cmd and alias_list and s.startswith("- "):
            commands[cmd]["aliases"].append(s[2:].strip().strip("'\""))
        else:
            alias_list = False
    return top, commands, problems


def check_plugin_yml(code: str, kind: str, classes: dict, used_cmds: dict) -> list[dict]:
    top, commands, probs = parse_plugin_yml(code)
    need = ("name", "version", "main") + (("api-version",) if kind == "paper-plugin.yml" else ())
    for key in need:
        if not top.get(key):
            probs.append(_p("descriptor", f"{kind} has no '{key}:' (required); the server will not load the plugin",
                            name=key))
    name = top.get("name", "")
    if name and not re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
        probs.append(_p("descriptor", f"plugin name '{name}' may only use letters, digits, space, '_', '.', '-'",
                        name=name))
    main = top.get("main", "")
    plugin_classes = [c for c, info in classes.items() if info.get("plugin_main")]
    if main and classes and main not in classes:
        sug = plugin_classes[0] if plugin_classes else None
        probs.append(_p("descriptor", f"{kind} main: {main} is not a class in the answer"
                        + (f"; the JavaPlugin class is {sug}" if sug else ""), name=main, suggestion=sug))
    av = top.get("api-version", "")
    if av and not API_VERSION.match(av):
        probs.append(_p("descriptor", f"api-version '{av}' is not a Minecraft version Paper accepts (use '1.21' or "
                                      "a full version like '1.21.11')", name=av, suggestion="1.21"))
    elif not av and kind == "plugin.yml":
        probs.append(_p("descriptor", "plugin.yml has no api-version: Paper loads it as a legacy (pre-1.13) plugin "
                                      "with the slow legacy Material layer; add api-version: '1.21'", "info"))
    known = set(commands) | {a for c in commands.values() for a in c["aliases"]}
    for cmd_name, line in used_cmds.items():
        if kind == "paper-plugin.yml":
            probs.append(_p("descriptor", f'getCommand("{cmd_name}") always returns null with paper-plugin.yml (it '
                                          "has no commands: section): register the command with Brigadier in "
                                          "LifecycleEvents.COMMANDS, or use plugin.yml", name=cmd_name))
        elif cmd_name.lower() not in {k.lower() for k in known}:
            probs.append(_p("descriptor", f'the code calls getCommand("{cmd_name}") but plugin.yml has no command '
                                          f"'{cmd_name}' under commands: -> null -> NullPointerException in onEnable",
                            name=cmd_name, suggestion=f"commands:\n  {cmd_name}:\n    description: ..."))
    return probs


def check_fabric_mod_json(code: str, classes: dict) -> list[dict]:
    try:
        d = json.loads(code)
    except ValueError as e:
        return [_p("json", f"fabric.mod.json is not valid JSON ({e}); the loader refuses the mod")]
    probs = []
    if d.get("schemaVersion") != 1:
        probs.append(_p("descriptor", "fabric.mod.json needs \"schemaVersion\": 1", name="schemaVersion"))
    mid = d.get("id", "")
    if not FABRIC_ID.match(str(mid)):
        probs.append(_p("descriptor", f"mod id '{mid}' must be 2-64 chars of a-z, 0-9, '-' or '_', starting with a "
                                      "letter", name=str(mid)))
    if not d.get("version"):
        probs.append(_p("descriptor", "fabric.mod.json has no \"version\"", name="version"))
    for ep, wants in (("main", "ModInitializer"), ("server", "DedicatedServerModInitializer"),
                      ("client", "ClientModInitializer")):
        for e in (d.get("entrypoints") or {}).get(ep, []) or []:
            cls = e.get("value") if isinstance(e, dict) else e
            if not isinstance(cls, str):
                continue
            cls = cls.split("::")[0]
            if classes and cls not in classes:
                probs.append(_p("descriptor", f"entrypoint {ep}: {cls} is not a class in the answer", name=cls))
            elif cls in classes and wants not in classes[cls].get("source", ""):
                probs.append(_p("descriptor", f"entrypoint {ep}: {cls} must implement {wants}", name=cls))
    return probs


def check_mods_toml(code: str, role: str, classes: dict) -> list[dict]:
    probs = []
    if role == "mods.toml":
        probs.append(_p("descriptor", "NeoForge 1.20.5+ reads META-INF/neoforge.mods.toml; META-INF/mods.toml is the "
                                      "old Forge name and is ignored", "warning", name="mods.toml",
                        suggestion="neoforge.mods.toml"))
    if tomllib is None:
        return probs
    try:
        d = tomllib.loads(code)
    except Exception as e:                  # tomllib.TOMLDecodeError
        return probs + [_p("toml", f"neoforge.mods.toml does not parse ({e})")]
    if not d.get("modLoader"):
        probs.append(_p("descriptor", "neoforge.mods.toml needs modLoader=\"javafml\"", name="modLoader"))
    if not d.get("loaderVersion"):
        probs.append(_p("descriptor", "neoforge.mods.toml needs loaderVersion (e.g. \"[1,)\")", name="loaderVersion"))
    ann = {m for c in classes.values() for m in c.get("mod_ids", [])}
    for mod in d.get("mods") or []:
        mid = str(mod.get("modId", ""))
        if not MOD_ID.match(mid):
            probs.append(_p("descriptor", f"modId '{mid}' must be 2-64 chars of a-z, 0-9 or '_'", name=mid))
        elif ann and mid not in ann:
            probs.append(_p("descriptor", f"modId '{mid}' does not match @Mod(\"{sorted(ann)[0]}\") in the code: the "
                                          "mod class is never loaded", name=mid, suggestion=sorted(ann)[0]))
    return probs


# ---- compile diagnostics -> problems ---------------------------------------------------------------------------
def _diag_problem(d: dict, line: int | None) -> dict:
    msg = d["message"].split("\n")[0]
    sym, loc, cands = d.get("symbol"), d.get("location"), d.get("candidates") or []
    severity = {"ERROR": "error"}.get(d["kind"], "info")
    if d["kind"] in ("WARNING", "MANDATORY_WARNING"):
        severity = "warning" if "marked for removal" in d["message"] else "info"
    if sym and loc:
        msg = f"{msg}: {sym} on {loc}"
    elif sym:
        msg = f"{msg}: {sym}"
    elif d.get("code") == "compiler.err.doesnt.exist" and cands:
        msg += f" (real packages: {', '.join(cands[:4])})"
    if d.get("note"):
        msg += f" - {d['note']}"
    sug = None
    if cands and sym and cands[0].lower() == sym.lower():
        sug = cands[0]
    return _p("compile", msg, severity, name=sym, suggestion=sug, line=line,
              candidates=cands if not sug else None, code=d.get("code"))


def check_answer(blocks: list[dict], text: str, jvm: JvmClient | None) -> dict:
    """{block index: [problems]} for the Java, descriptor and Kotlin blocks of the answer; {} when there are none.
    Also returns key "_meta" with target and compile timing."""
    roles = {k: block_role(b, text) for k, b in enumerate(blocks)}
    java = [k for k, r in roles.items() if r == "java"]
    out: dict = {k: [] for k, r in roles.items() if r not in ("other", "build")}
    if not out:
        return {}
    java_text = "\n".join(blocks[k]["code"] for k in java)
    target = detect_target(java_text, text) if java else None
    if target is None:                      # plain Java (no Minecraft API): not this checker's business
        for k in java:
            out.pop(k, None)
        java = []
        if not out:
            return {}
    meta ={"target": target, "compile_ms": None, "compiled": False}
    files, origin, classes = {}, {}, {}
    full_imports = sorted({m.group(0).strip() for k in java for m in IMPORT.finditer(blocks[k]["code"])
                           if TYPE_DECL.search(blocks[k]["code"])})
    for k in java:
        code = blocks[k]["code"]
        if TYPE_DECL.search(code):
            path, pkg, name = java_path(code, k)
            src, offset = code, 0
            fqn = f"{pkg}.{name}" if pkg else name
            for t in TYPE_DECL.findall(code):            # every top-level-looking type (good enough for lookups)
                classes.setdefault(f"{pkg}.{t}" if pkg else t, {"source": code, "block": k})
            classes[fqn] = {"source": code, "block": k,
                            "plugin_main": bool(re.search(r"\bextends\s+(?:org\.bukkit\.plugin\.java\.)?JavaPlugin\b",
                                                          code)),
                            "mod_ids": _mod_ids(code)}
        else:
            src, offset = wrap_snippet(code, k, target or "", full_imports)
            path = f"Snippet{k}.java"
        if path in files:                       # the same class shown twice: the later version is the answer
            origin.pop(path)
        files[path] = src
        origin[path] = (k, offset, not TYPE_DECL.search(code))
    for k, r in roles.items():
        if r == "kotlin":
            out[k].append(_p("lang", "Kotlin is not compiled by this verifier (only Java)", "info"))
    if target == "forge":
        for k in java:
            out[k].append(_p("target", "this is (Lex)Forge API (net.minecraftforge); for NeoForge 1.21 the packages "
                                       "are net.neoforged.*: not compiled", "info"))
    elif target == "bungee":
        for k in java:
            out[k].append(_p("target", "BungeeCord API is not compiled by this verifier", "info"))
    elif java and target and jvm is not None:
        t0 = time.perf_counter()
        res = jvm.compile(target, files)
        if res is not None and target.startswith("fabric") and not res.get("ok"):
            other = "fabric-mojmap" if target == "fabric" else "fabric"
            res2 = jvm.compile(other, files)      # the other mapping set may be what the answer was written in
            if res2 is not None and _errors(res2) < _errors(res):
                res, target = res2, other
                meta["target"] = target
        guessed = _guess_fields(res, origin, target) if res is not None else {}
        if guessed:                            # once more with the fragments' context variables declared
            for path, fields in guessed.items():
                k = origin[path][0]
                files[path] = wrap_snippet(blocks[k]["code"], k, target, full_imports, fields)[0]
            res = jvm.compile(target, files) or res
        meta["compile_ms"] = round((time.perf_counter() - t0) * 1000)
        if res is not None and "diagnostics" in res:
            meta["compiled"] = True
            _map_diagnostics(res["diagnostics"], files, origin, out)
    used = {}
    for k in java:
        for m in GET_COMMAND.finditer(blocks[k]["code"]):
            used.setdefault(m.group(1), m.start())
    for k, r in roles.items():
        code = blocks[k]["code"]
        if r in ("plugin.yml", "paper-plugin.yml"):
            out[k] += check_plugin_yml(code, r, classes, used)
        elif r == "fabric.mod.json":
            out[k] += check_fabric_mod_json(code, classes)
        elif r in ("neoforge.mods.toml", "mods.toml"):
            out[k] += check_mods_toml(code, r, classes)
    shown = {m.group(1) for k, b in enumerate(blocks) if roles[k] == "other"
             for m in re.finditer(r"([\w-]+\.ya?ml)", b["code"].lstrip()[:80] + " " + text[max(0, b["start"] - 200):b["start"]])}
    for k in java:
        for m in SAVE_RESOURCE.finditer(blocks[k]["code"]):
            res = m.group(1) or "config.yml"
            if target in ("paper", "spigot") and res not in shown:
                line = blocks[k]["code"].count("\n", 0, m.start()) + 1
                out[k].append(_p("resource", f"{m.group(0)} copies {res} from the plugin jar, but the answer has no "
                                             f"{res}: the plugin fails to enable (IllegalArgumentException: embedded "
                                             f"resource '{res}' cannot be found). Show {res} (src/main/resources) or "
                                             "set defaults in code: getConfig().addDefault(...); "
                                             "getConfig().options().copyDefaults(true); saveConfig();",
                                 "warning", name=m.group(0), line=line))
        for m in VELOCITY_ID.finditer(blocks[k]["code"]):
            if not VELOCITY_ID_OK.match(m.group(1)):
                out[k].append(_p("descriptor", f"Velocity plugin id '{m.group(1)}' must be lowercase a-z, 0-9, '-' or "
                                               "'_' and start with a letter: Velocity refuses to load it",
                                 name=m.group(1), suggestion=re.sub(r"[^a-z0-9_-]", "", m.group(1).lower()) or None))
    out["_meta"] = meta
    out["_roles"] = {k: r for k, r in roles.items() if k in out}
    return out


def _guess_fields(res: dict, origin: dict, target: str) -> dict:
    """{snippet path: "Type name; ..."} for unknown variables of fragments that have a usual type."""
    known, out = SNIPPET_VARS.get(target, {}), {}
    for d in res.get("diagnostics", []):
        path = d.get("file", "")
        if path in origin and origin[path][2] and "symbol:   variable" in d.get("message", "") and                 (d.get("location") or "").startswith("Snippet") and d.get("symbol") in known:
            decl = f"{known[d['symbol']]} {d['symbol']};"
            if decl not in out.get(path, ""):
                out[path] = (out.get(path, "") + " " + decl).strip()
    return out


def _mod_ids(code: str) -> list[str]:
    ids = []
    for m in MOD_ANN.finditer(code):
        v = m.group(1)
        if v.startswith('"'):
            ids.append(v.strip('"'))
        else:
            c = re.search(rf"\b{re.escape(v.split('.')[-1])}\s*=\s*\"([^\"]+)\"", code)
            if c:
                ids.append(c.group(1))
    return ids


def _errors(res: dict) -> int:
    return sum(d["kind"] == "ERROR" for d in res.get("diagnostics", []))


def _map_diagnostics(diags: list[dict], files: dict, origin: dict, out: dict):
    external = set()                       # simple names imported from packages the target does not have
    for d in diags:
        if d.get("code") == "compiler.err.doesnt.exist":
            pkg = re.search(r"package ([\w.]+) does not exist", d["message"])
            if pkg and not d.get("candidates") and not pkg.group(1).startswith(("java.", "javax.")):
                d["external"] = True
                src = files.get(d.get("file", ""), "")
                for m in IMPORT.finditer(src):
                    if m.group(2).startswith(pkg.group(1)):
                        external.add(m.group(2).rsplit(".", 1)[-1])
                external.add(pkg.group(1))
    seen = set()
    for d in diags:
        path = d.get("file", "")
        if path not in origin:
            continue
        k, offset, snippet = origin[path]
        if d.get("external"):
            pkg = re.search(r"package ([\w.]+)", d["message"]).group(1)
            if pkg not in seen:
                seen.add(pkg)
                out[k].append(_p("dependency", f"{pkg} is from another plugin/library (not on the compile classpath): "
                                               "not checked; declare it as a dependency", "info", name=pkg))
            continue
        if d.get("symbol") in external or (d.get("location") or "").split(".")[-1] in external:
            continue
        line = d.get("line") - offset if d.get("line", -1) > 0 else None
        if snippet:
            if line is not None and line < 1:
                continue                        # an error in the wrapper itself
            loc = d.get("location") or ""
            api_fact = (d.get("code", "").startswith("compiler.err.cant.resolve") and d.get("api")) or \
                d["kind"] in ("WARNING", "MANDATORY_WARNING")
            if not api_fact or loc.startswith("Snippet"):
                continue
        if d["kind"] == "NOTE":
            continue
        out[k].append(_diag_problem(d, line))
