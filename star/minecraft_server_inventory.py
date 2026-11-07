"""Read-only Minecraft server/project inventory for STAR's confined workspace.

Does not execute JARs, read arbitrary configuration values, contact a server, or reveal
secrets such as RCON passwords, proxy forwarding tokens, database credentials or IPs.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import zipfile

MAX_JARS = 160
MAX_JAR_BYTES = 300 * 1024 * 1024
MAX_METADATA_BYTES = 100 * 1024
MAX_PROPERTIES_BYTES = 256 * 1024
META_PATHS = ("paper-plugin.yml", "plugin.yml", "fabric.mod.json", "META-INF/neoforge.mods.toml", "META-INF/mods.toml")
PROP_INTS = frozenset({"view-distance", "simulation-distance", "max-players", "entity-broadcast-range-percentage",
                       "network-compression-threshold", "rate-limit"})
PROP_BOOLEANS = frozenset({"online-mode", "enforce-secure-profile", "enable-rcon", "enable-query",
                           "require-resource-pack", "white-list", "spawn-monsters"})
PACK_MANAGERS = frozenset({"nexo", "oraxen", "itemsadder", "polymer", "packman"})


def _non_sensitive_properties(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_PROPERTIES_BYTES or path.is_symlink():
        return {}
    safe = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = (v.strip() for v in line.split("=", 1))
        if key in PROP_INTS and re.fullmatch(r"-?\d{1,8}", value):
            safe[key] = int(value)
        elif key in PROP_BOOLEANS and value.lower() in ("true", "false"):
            safe[key] = value.lower() == "true"
        elif key == "resource-pack":
            safe["resource-pack-configured"] = bool(value)
        elif key == "resource-pack-sha1":
            safe["resource-pack-hash-configured"] = bool(value)
        # Everything else is excluded, especially RCON password and URLs.
    return safe


def _scalar(text: str, key: str) -> str:
    match = re.search(r"(?m)^" + re.escape(key) + r"\s*:\s*(.*)$", text)
    if not match:
        return ""
    value = match.group(1).split("#", 1)[0].strip().strip("\"'")
    return re.sub(r"[\x00-\x1f\x7f]", "", value)[:120]


def _mod_toml_scalar(text: str, key: str) -> str:
    match = re.search(r"(?m)^\s*" + re.escape(key) + r"\s*=\s*[\"']([^\"'\n]+)[\"']", text)
    return match.group(1)[:120] if match else ""


def _metadata(jar: Path, workspace, root: Path) -> dict:
    result = {"file": jar.name, "name": "", "id": "", "version": "", "kind": "unknown",
              "source": "jar-metadata", "load_tested": False}
    if jar.is_symlink() or not jar.resolve().is_relative_to(root.resolve()):
        result["error"] = "JAR symlink or escaped server folder; not inspected"
        return result
    if jar.stat().st_size > MAX_JAR_BYTES:
        result["error"] = "JAR exceeds static inspection limit"
        return result
    try:
        # ZIP central directory is inspected; no classes or plugin code are executed.
        with zipfile.ZipFile(jar) as archive:
            names = set(archive.namelist())
            if len(names) > 20000:
                result["error"] = "JAR has an excessive entry count"
                return result
            for path in META_PATHS:
                if path not in names:
                    continue
                info = archive.getinfo(path)
                if (info.file_size > MAX_METADATA_BYTES or
                        (info.file_size > 10000 and info.file_size > max(info.compress_size, 1) * 200)):
                    result["error"] = "Plugin metadata exceeds size/decompression limit"
                    return result
                data = archive.read(info).decode("utf-8", errors="replace")
                if path == "fabric.mod.json":
                    manifest = json.loads(data)
                    if not isinstance(manifest, dict):
                        result["error"] = "fabric.mod.json is not an object"
                        return result
                    result.update(kind="fabric", name=str(manifest.get("name", ""))[:120],
                                  id=str(manifest.get("id", ""))[:120],
                                  version=str(manifest.get("version", ""))[:120])
                elif path.endswith("mods.toml"):
                    result.update(kind="neoforge" if "neoforge" in path else "forge",
                                  name=_mod_toml_scalar(data, "displayName"),
                                  id=_mod_toml_scalar(data, "modId"),
                                  version=_mod_toml_scalar(data, "version"))
                else:
                    result.update(kind="paper" if path == "paper-plugin.yml" else "bukkit",
                                  name=_scalar(data, "name"), version=_scalar(data, "version"),
                                  api_version=_scalar(data, "api-version"))
                    result["id"] = result["name"].lower().replace(" ", "")
                    if path == "plugin.yml":
                        result["declares_folia_support"] = _scalar(data, "folia-supported").lower() == "true"
                result["metadata_file"] = path
                break
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, json.JSONDecodeError):
        result["error"] = "Unable to inspect JAR metadata (invalid or inaccessible archive)"
    return result


def inspect(workspace, relative: str = ".") -> dict:
    root = workspace.resolve(relative)
    if not root.is_dir():
        raise ValueError("Choose an existing Minecraft server/project directory")
    # Safe, fixed file probes rather than recursively reading server credentials or worlds.
    names = {p.name for p in root.iterdir() if not p.is_symlink()}
    indicators = {n: n in names for n in
                  ("server.properties", "velocity.toml", "paper.yml", "bukkit.yml",
                   "spigot.yml", "fabric.mod.json", "pack.mcmeta",
                   "plugins", "mods", "config", "world")}
    family = ("velocity-proxy" if indicators["velocity.toml"] else
              "bukkit-paper-family" if indicators["plugins"] else
              "fabric-neoforge-family" if indicators["mods"] else
              "resource-pack" if indicators["pack.mcmeta"] else "unknown")
    jars = []
    issues = []
    for folder in ("plugins", "mods"):
        directory = root / folder
        if not directory.is_dir() or directory.is_symlink():
            continue
        candidates = sorted(p for p in directory.glob("*.jar") if p.is_file())
        if len(candidates) > MAX_JARS:
            issues.append({"severity": "warning", "code": "jar-list-truncated",
                           "message": f"{folder} has more than {MAX_JARS} JARs"})
        for jar in candidates[:MAX_JARS]:
            jars.append(_metadata(jar, workspace, root))
    ids = {}
    for jar in jars:
        identifier = jar["id"].casefold()
        if identifier and identifier in ids:
            issues.append({"severity": "warning", "code": "duplicate-mod-id",
                           "message": f"Multiple JARs declare ID {identifier}"})
        if identifier:
            ids[identifier] = jar["file"]
    managers = sorted({j["name"].casefold() for j in jars if j["name"].casefold() in PACK_MANAGERS}
                      | {j["id"].casefold() for j in jars if j["id"].casefold() in PACK_MANAGERS})
    if len(set(managers) & {"nexo", "oraxen", "itemsadder"}) > 1:
        issues.append({"severity": "warning", "code": "multiple-pack-managers",
                       "message": "More than one pack manager detected; verify which owns generated resources"})
    props = _non_sensitive_properties(root / "server.properties") if indicators["server.properties"] else {}
    if props.get("enable-rcon") is True:
        issues.append({"severity": "info", "code": "rcon-review",
                       "message": "RCON is enabled; restrict access and never expose its password"})
    if props.get("online-mode") is False and family != "velocity-proxy":
        issues.append({"severity": "info", "code": "authentication-review",
                       "message": "Online mode is disabled; verify proxy forwarding and firewall isolation"})
    return {"root": relative, "recognised": any(indicators.values()), "family_hint": family,
            "file_indicators": indicators, "safe_server_properties": props, "jars": jars,
            "pack_managers": managers, "issues": issues,
            "observed_running_state": False, "jar_executed": False,
            "minecraft_version": None, "java_runtime": None,
            "notice": "Offline static workspace inventory. Live software versions, Java runtime and performance are not verified; credential values are never returned."}
