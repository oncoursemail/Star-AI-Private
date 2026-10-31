"""Turn a Minecraft answer into a real-server job.

    plugin_job(answer, id)    -> loadtest.py job (server/mesh/verify/jvm/loadtest.py) or None
    datapack_job(answer, id)  -> dprun job ({"id", "commands", "files"}) or None

Same file rules as the mc-plugins / mc-load eval job builders (docs/agents/mc-load-20261029.md): Java blocks with a
type declaration become sources, descriptor blocks become resources, the file label written before a YAML block decides
plugin.yml vs config.yml. Commands typed into the console come from the answer itself (plugin.yml `commands:` or the
first Brigadier literal), never from a task list.
"""
from __future__ import annotations

import re

from ..verify import core, javamc

LABEL = re.compile(r"([\w./-]*?(?:plugin\.yml|paper-plugin\.yml|config\.yml|bungee\.yml|[\w-]+\.ya?ml))", re.I)
LITERAL = re.compile(r"(?:Commands|CommandManager|LiteralArgumentBuilder\.<[^>]+>)?\.?literal\(\s*\"([a-z0-9_-]+)\"")
REGISTER = re.compile(r"\.register\(\s*(?:\w+\.)?(?:Commands|CommandManager)?\.?literal\(\s*\"([a-z0-9_-]+)\"")


def plugin_job(answer: str, job_id: str, fallback_target: str | None = None) -> dict | None:
    blocks = core.extract_blocks(answer)
    roles = {k: javamc.block_role(b, answer) for k, b in enumerate(blocks)}
    java = [k for k, r in roles.items() if r == "java"]
    jtext = "\n".join(blocks[k]["code"] for k in java)
    target = javamc.detect_target(jtext, answer) if java else None
    if fallback_target == "spigot" and target == "paper":
        target = "spigot"
    target = target or fallback_target
    if target not in ("paper", "spigot", "velocity", "fabric", "fabric-mojmap", "neoforge"):
        return None
    sources: dict[str, str] = {}
    resources: dict[str, str] = {}
    ids: list[str] = []
    for k in java:
        code = blocks[k]["code"]
        if javamc.TYPE_DECL.search(code):
            path, pkg, _ = javamc.java_path(code, k)
            sources[path] = code
            if pkg:
                ids.append(pkg)
    for k, r in roles.items():
        b = blocks[k]
        code = b["code"]
        first = code.lstrip().splitlines()[0] if code.strip() else ""
        label = LABEL.findall(first) or LABEL.findall(answer[max(0, b["start"] - 200):b["start"]])
        name = label[-1].rsplit("/", 1)[-1].lower() if label else ""
        if (b.get("info") or "").lower().split(" ")[0] in ("yaml", "yml", "") and name == "config.yml":
            resources["config.yml"] = code
            continue
        if r in ("plugin.yml", "paper-plugin.yml", "fabric.mod.json", "velocity-plugin.json"):
            resources[r] = code
        elif r in ("neoforge.mods.toml", "mods.toml"):
            resources["META-INF/" + r] = code
        else:
            near = javamc.NAME_NEAR.findall(first) or javamc.NAME_NEAR.findall(answer[max(0, b["start"] - 260):b["start"]])
            if near and near[-1].lower().endswith(".mixins.json"):
                resources[near[-1]] = code
    desc = resources.get("plugin.yml", "") + resources.get("paper-plugin.yml", "")
    m = re.search(r"^name:\s*['\"]?([^'\"\n]+)", desc, re.M)
    if m:
        ids.append(m.group(1).strip())
    for text in resources.values():
        for mm in re.finditer(r'"id"\s*:\s*"([^"]+)"|modId\s*=\s*"([^"]+)"', text):
            ids.append(mm.group(1) or mm.group(2))
    for mm in re.finditer(r'@Plugin\s*\((?:[^)]|\n)*?\bid\s*=\s*"([^"]+)"', jtext):
        ids.append(mm.group(1))
    return {"id": job_id, "target": target, "sources": sources, "resources": resources,
            "commands": commands(desc, jtext, target), "ids": list(dict.fromkeys(ids)),
            "vacuous": not sources}


def commands(descriptor: str, java_text: str, target: str) -> list[str]:
    """Root command names to type (no arguments): plugin.yml `commands:` keys, else registered Brigadier literals."""
    out: list[str] = []
    m = re.search(r"^commands:\s*\n((?:[ \t]+.*\n?|\s*\n)*)", descriptor, re.M)
    if m:
        body = m.group(1)
        ind = min((len(x) - len(x.lstrip()) for x in body.splitlines() if x.strip()), default=0)
        for ln in body.splitlines():
            if ln.strip() and len(ln) - len(ln.lstrip()) == ind and re.match(r"\s*['\"]?[\w-]+['\"]?\s*:", ln):
                out.append(ln.strip().split(":")[0].strip("'\""))
    if not out and target not in ("paper", "spigot"):
        out = list(dict.fromkeys(REGISTER.findall(java_text)))
        if not out and "register" in java_text:
            out = list(dict.fromkeys(LITERAL.findall(java_text)))[:1]
    if not out and target in ("paper", "spigot"):        # Paper's Brigadier lifecycle API (no plugin.yml commands)
        out = list(dict.fromkeys(REGISTER.findall(java_text)))
    return out[:6]


def datapack_job(answer: str, job_id: str) -> dict | None:
    try:
        from ..mcdata.extract import extract
    except ImportError:                       # pragma: no cover
        return None
    cmds, files, _ = extract(answer)
    fmap: dict[str, str] = {}
    for f in files:
        p, code = f["path"], f["code"]
        if f.get("comment_path"):
            code = code.split("\n", 1)[1] if "\n" in code else ""
        if p and ((p.startswith("data/") and p.endswith((".json", ".mcfunction"))) or p == "pack.mcmeta"):
            fmap[p] = code
    if not any(p.startswith("data/") for p in fmap):
        return None
    fn_blocks = {f["block"] for f in files if f["path"] and f["path"].endswith(".mcfunction")}
    return {"id": job_id, "commands": [c for b, _, c in cmds if b not in fn_blocks][:12], "files": fmap}
