"""Verify and build the gold exemplar bank (developer tool; needs STAR Server for the Luau tools and embeddings).

    python -m star.gold_bank_verify check data/gold_bank/src/ui/gb-ui-x.md ...   one line per item, no files written
    python -m star.gold_bank_verify build                                     bank.jsonl + manifest.json + LICENSES.md
    python -m star.gold_bank_verify export --out FILE                         training rows (fine-tune hand-off)

Every item must pass all of these, or it is dropped with the reason recorded:
  luau     each ```lua block compiles and passes luau-analyze in strict mode with no lint warning
           (STAR Knowledge /luau/check, mode strict; Roblox globals are typed any there)
  lint     star.luau_lint with the safety, server-trust and Roblox rules: no finding
  api      star.roblox_api_checker against the bundled API dump: no finding; no deprecated member, class or
           enum item, and every Enum.X.Y exists in the dump
  slop     star.slop.score_answer: no finding
  runtime  the item's # Test runs in the standalone Luau VM (eval sandbox) after data/gold_bank/stubs.luau and every
           check passes (items without a test are marked runtime "none")
  leakage  no overlap with the evaluation suites (server/training/startrain/decontam.py: exact, 5/8-gram text,
           reference-answer and unit-test overlap, embedding cosine) and no near-duplicate inside the bank

Configuration comes from the environment, never from this file: STAR_GOLD_KNOWLEDGE (STAR Knowledge URL),
STAR_EVAL_SERVER (STAR Server /v1 URL, embeddings), STAR_EVAL_SANDBOX_SSH or STAR_EVAL_SSH (user@host of the
Luau VM container), STAR_SERVER_API_KEY or ~/.star/server_api_key.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from .gold_bank import CATEGORIES, validate_row

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "gold_bank"
SRC = GOLD / "src"
STUBS = GOLD / "stubs.luau"
SOURCES = GOLD / "sources.json"
EVALS = ROOT / "evals" / "roblox"
VERSION = 6                      # bump when a check changes, so cached results are not reused
ORIGINAL_SPDX = "LicenseRef-STAR-Original"
_FRONT_KEYS = {"id", "category", "topics", "source", "source_id", "source_path", "source_commit", "test_block"}
_FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
_DEFINED = re.compile(r"function\s+[A-Za-z_][\w.]*[.:]([A-Za-z_]\w*)\s*\(|\b([A-Za-z_]\w*)\s*=\s*function\b"
                      r"|^\s*([A-Za-z_]\w*)\s*=", re.M)
# Method-call syntax only: deprecated engine members are methods (obj:Remove()); module functions use a dot.
_CALLED = re.compile(r"(?:\b([A-Za-z_]\w*)\s*)?:([A-Za-z_]\w*)\s*\(")
_LIBRARIES = frozenset({"table", "string", "math", "buffer", "coroutine", "bit32", "utf8", "os", "debug", "task",
                        "vector"})
# Engine data types the standalone analyzer does not know. Each one the code names is declared `type X = any` on one
# extra first line (STAR Knowledge already types Roblox globals as any), so an annotation such as `a: Vector3` stays
# usable in arithmetic instead of becoming an unknown type. Classes from the API dump are added the same way.
_DATATYPES = frozenset({
    "Vector3", "Vector2", "CFrame", "Color3", "UDim", "UDim2", "TweenInfo", "NumberRange", "NumberSequence",
    "ColorSequence", "NumberSequenceKeypoint", "ColorSequenceKeypoint", "Rect", "Ray", "RaycastParams",
    "RaycastResult", "OverlapParams", "PhysicalProperties", "BrickColor", "Random", "DateTime", "Font", "EnumItem",
    "RBXScriptSignal", "RBXScriptConnection", "Region3", "Vector3int16", "Vector2int16", "Axes", "Faces",
    "PathWaypoint", "SharedTable", "Content", "Secret", "CatalogSearchParams", "DockWidgetPluginGuiInfo"})
_CAPITALISED = re.compile(r"\b[A-Z][A-Za-z0-9]*\b")
_LOCAL_TYPE = re.compile(r"\btype\s+([A-Za-z_]\w*)")
_ENUM = re.compile(r"\bEnum\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
_NEW = re.compile(r"\bInstance\.new\(\s*\"([A-Za-z_]\w*)\"")


@dataclass
class Item:
    id: str
    path: str
    category: str
    topics: list[str]
    source: str
    source_id: str
    source_path: str
    source_commit: str
    test_block: int
    request: str
    answer: str
    setup: str = ""
    test: str = ""
    sha: str = ""

    @property
    def blocks(self) -> list[str]:
        return lua_blocks(self.answer)


@dataclass
class Result:
    id: str
    ok: bool = True
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def fail(self, check: str, reason: str) -> None:
        self.ok = False
        self.checks[check] = "fail"
        self.reasons.append(f"{check}: {reason}"[:300])


def lua_blocks(markdown: str) -> list[str]:
    return [m.group(2) for m in _FENCE.finditer(markdown) if m.group(1).lower() in ("lua", "luau")]


def parse_item(text: str, path: str = "") -> Item:
    """Parse one authoring file; raises ValueError with the reason when its shape is wrong."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing front matter")
    head, body = text[4:].split("\n---\n", 1)
    front: dict[str, str] = {}
    for line in head.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in _FRONT_KEYS or key in front:
            raise ValueError(f"bad front matter line: {line[:60]}")
        front[key] = value.strip()
    sections: dict[str, str] = {}
    for match in re.finditer(r"^# (Request|Answer|Test)[ \t]*\n(.*?)(?=^# (?:Request|Answer|Test)[ \t]*$|\Z)", body,
                             re.M | re.S):
        if match.group(1) in sections:
            raise ValueError(f"duplicate section {match.group(1)}")
        sections[match.group(1)] = match.group(2).strip()
    for needed in ("id", "category", "topics", "source"):
        if not front.get(needed):
            raise ValueError(f"front matter needs {needed}")
    if "Request" not in sections or "Answer" not in sections:
        raise ValueError("needs # Request and # Answer")
    if not re.fullmatch(r"gb-[a-z0-9]+(?:-[a-z0-9]+)*", front["id"]) or len(front["id"]) > 64:
        raise ValueError("bad id")
    if path and Path(path).stem != front["id"]:
        raise ValueError("file name must be the id")
    if front["category"] not in CATEGORIES:
        raise ValueError(f"unknown category {front['category']}")
    if front["source"] not in ("original", "adapted", "verbatim"):
        raise ValueError("source must be original, adapted or verbatim")
    if front["source"] != "original":
        if not front.get("source_id") or not front.get("source_path") \
                or not re.fullmatch(r"[0-9a-f]{40}", front.get("source_commit", "")):
            raise ValueError("third-party item needs source_id, source_path and a 40-hex source_commit")
    tests = lua_blocks(sections.get("Test", ""))
    if len(tests) > 2:
        raise ValueError("# Test holds at most two lua blocks (setup, test)")
    answer = sections["Answer"]
    if not lua_blocks(answer):
        raise ValueError("the answer has no ```lua block")
    test_block = int(front.get("test_block") or 1)
    if not 1 <= test_block <= len(lua_blocks(answer)):
        raise ValueError("test_block points past the answer's lua blocks")
    topics = [t.strip() for t in front["topics"].split(",") if t.strip()]
    return Item(
        id=front["id"], path=path, category=front["category"], topics=topics[:12], source=front["source"],
        source_id=front.get("source_id", ""), source_path=front.get("source_path", ""),
        source_commit=front.get("source_commit", ""), test_block=test_block, request=sections["Request"],
        answer=answer, setup=tests[0] if len(tests) == 2 else "", test=tests[-1] if tests else "",
        sha=hashlib.sha256(text.encode("utf-8")).hexdigest())


def harness(item: Item, stubs: str) -> str:
    """The script the Luau VM runs: stubs, setup, the tested block as a function, the test, the summary."""
    code = re.sub(r"(?m)^export type\b", "type", item.blocks[item.test_block - 1])
    return "\n".join([
        stubs, "do", item.setup, "end",
        "local item", "task.spawn(function()", "\titem = (function()", code, "\tend)()", "end)",
        "do", item.test, "end", "__done()", ""])


def runtime_verdict(stdout: str, rc: int) -> str:
    """'' when the run passed, else a short reason."""
    summary = re.findall(r"^@@SUMMARY\t(\d+)\t(\d+)$", stdout, re.M)
    failed = re.findall(r"^@@T\tfail\t(.*)$", stdout, re.M)
    if rc != 0 or not summary:
        tail = [line for line in stdout.strip().splitlines() if not line.startswith("@@")][-2:]
        return f"run did not finish (rc {rc}): {' | '.join(tail)[:200]}"
    passes, fails = (int(x) for x in summary[-1])
    if fails or failed:
        return "failed checks: " + ", ".join(failed[:5])
    if passes == 0:
        return "the test made no check"
    return ""


# --- API dump checks ---------------------------------------------------------------------------------------------

def api_findings(code: str, dump, dataset) -> list[str]:
    from .roblox_api_checker import check_luau_api
    out = [f"line {f.line}: {f.rule_id} {f.class_name or ''}.{f.name}" for f in check_luau_api(code, dump)]
    defined = {name for groups in _DEFINED.findall(code) for name in groups if name}
    for match in _CALLED.finditer(code):
        receiver, name = match.group(1), match.group(2)
        if name in defined or receiver in _LIBRARIES:
            continue
        found = dataset.find_member(name)
        if found and all(member.deprecated for member in found):
            line = code.count("\n", 0, match.start()) + 1
            out.append(f"line {line}: deprecated member {name}")
    for match in _NEW.finditer(code):
        cls = dataset.classes.get(match.group(1))
        if cls is not None and cls.deprecated:
            out.append(f"deprecated class {match.group(1)}")
    for match in _ENUM.finditer(code):
        enum, value = match.groups()
        if value in ("GetEnumItems", "FromName", "FromValue"):
            continue
        if enum not in dataset.enums:
            out.append(f"unknown enum {enum}")
        elif value not in dataset.enums[enum]:
            out.append(f"unknown enum item {enum}.{value}")
    return out


# --- server-backed tools ------------------------------------------------------------------------------------------

def _key() -> str:
    key = os.environ.get("STAR_SERVER_API_KEY", "").strip()
    path = Path.home() / ".star" / "server_api_key"
    if not key and path.is_file():
        key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("No STAR Server key (STAR_SERVER_API_KEY or ~/.star/server_api_key)")
    return key


class Tools:
    """Luau check (STAR Knowledge), Luau VM (eval sandbox), embeddings (STAR Server)."""

    def __init__(self, *, need_runtime: bool = True):
        from .doc_knowledge import KnowledgeClient
        from .eval_sandbox import ContainerSandbox
        from .roblox_api_dataset import api_dump, load
        knowledge = os.environ.get("STAR_GOLD_KNOWLEDGE", "").strip()
        server = os.environ.get("STAR_EVAL_SERVER", "").strip().rstrip("/")
        sandbox = (os.environ.get("STAR_EVAL_SANDBOX_SSH") or os.environ.get("STAR_EVAL_SSH") or "").strip()
        if not knowledge or not server or (need_runtime and not sandbox):
            raise SystemExit("Set STAR_GOLD_KNOWLEDGE, STAR_EVAL_SERVER and STAR_EVAL_SANDBOX_SSH (see module docstring)")
        self.key = _key()
        self.knowledge = KnowledgeClient(knowledge, self.key)
        self.server = server
        self.sandbox = ContainerSandbox(sandbox, wall_s=30, cpu_s=20) if sandbox else None
        self.dump, self.dataset = api_dump(), load()
        self.stubs = STUBS.read_text(encoding="utf-8")

    def embed(self, texts: list[str], model: str = "star-embed") -> list[list[float]]:
        import httpx
        out: list[list[float]] = []
        for start in range(0, len(texts), 32):
            reply = httpx.post(self.server + "/embeddings", json={"model": model, "input": texts[start:start + 32]},
                               headers={"Authorization": "Bearer " + self.key}, timeout=120, trust_env=False)
            reply.raise_for_status()
            rows = sorted(reply.json()["data"], key=lambda row: row["index"])
            out.extend(row["embedding"] for row in rows)
        return out

    def luau_check(self, code: str) -> dict:
        last: Exception = OSError("no attempt")
        for attempt in range(3):
            try:
                return self.knowledge.luau_check(code, strict=True)
            except OSError as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
        raise last


# --- leakage -------------------------------------------------------------------------------------------------------

def _startrain():
    path = str(ROOT / "server" / "training")
    if path not in sys.path:
        sys.path.insert(0, path)
    from startrain import config, decontam, similarity
    return config, decontam, similarity


def leakage_index(tools: Tools, cache: Path) -> dict:
    """The decontamination index over the evaluation suites (golden tasks, holdout, references, unit tests)."""
    _, decontam, _ = _startrain()
    digest = decontam.digest_of(decontam.tree_hashes(EVALS))
    path = cache.parent / "gold-decontam-index.json"
    if path.is_file():
        index = json.loads(path.read_text(encoding="utf-8"))
        if index.get("suite_digest") == digest:
            return index
    index = decontam.build_index(EVALS, embed=tools.embed)
    index["items"] = [i for i in index["items"] if not i["source"].startswith("practice-")]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index), encoding="utf-8")
    return index


# --- verification --------------------------------------------------------------------------------------------------

def engine_type_prelude(code: str, dataset) -> str:
    """One line declaring the engine types this code names (API dump classes and data types) as `any`."""
    own = set(_LOCAL_TYPE.findall(code))
    names = sorted({word for word in _CAPITALISED.findall(code)
                    if word not in own and (word in _DATATYPES or word in dataset.classes)})
    parts = [f"type {name} = any" for name in names]
    if re.search(r"\bdebug\.profile(?:begin|end)\b", code):
        parts.append("local debug: any = debug")       # the Roblox-only profiler labels
    return "; ".join(parts)


def static_checks(item: Item, tools: Tools, result: Result) -> None:
    from .luau_lint import lint
    from .slop import score_answer
    for n, code in enumerate(item.blocks, 1):
        # The prelude takes the place of a first-line `--!strict` (strict mode is passed to the analyzer anyway),
        # otherwise it is one extra line; diagnostics are shifted back to the block's own line numbers.
        lines = code.split("\n")
        directive = lines[0].startswith("--!")
        shift = 0 if directive else 1
        sent = engine_type_prelude(code, tools.dataset) + "\n" + "\n".join(lines[1:] if directive else lines)
        try:
            report = tools.luau_check(sent)
        except Exception as exc:          # no verdict is not a pass
            result.fail("luau", f"block {n}: check unavailable ({type(exc).__name__})")
            continue
        # `typeof(x) == "Vector3"` makes the standalone analyzer look up the engine type by name and warn
        # UnknownType: that is its missing Roblox definitions, not a problem of the code.
        warnings = [d for d in report["warnings"] if not (
            d["kind"] == "UnknownType" and (m := re.search(r"Unknown type '([A-Za-z0-9_]+)'", d["message"]))
            and (m.group(1) in _DATATYPES or m.group(1) in tools.dataset.classes))]
        problems = [f"{d['line'] - shift}: {d['message']}" for d in report["errors"]] + \
                   [f"{d['line'] - shift}: {d['kind']} {d['message']}" for d in warnings]
        if not report["compiled"] or not report["analyzed"] or problems:
            result.fail("luau", f"block {n}: " + "; ".join(problems[:3] or ["not compiled/analysed"]))
        findings = lint(code, safety_checks=True, server_security=True, roblox_rules=True)
        if findings:
            result.fail("lint", f"block {n}: " + "; ".join(f"{f.line} {f.rule_id}" for f in findings[:4]))
        api = api_findings(code, tools.dump, tools.dataset)
        if api:
            result.fail("api", f"block {n}: " + "; ".join(api[:4]))
    slop = score_answer(item.answer, prompt=item.request, api_dump=tools.dump)
    if slop.findings:
        result.fail("slop", "; ".join(f"{f.rule} line {f.line}" for f in slop.findings[:4]))
    for check in ("luau", "lint", "api", "slop"):
        result.checks.setdefault(check, "pass")


def runtime_check(item: Item, tools: Tools, result: Result) -> None:
    if not item.test:
        result.checks["runtime"] = "none"
        return
    if tools.sandbox is None:
        result.fail("runtime", "sandbox unavailable: no sandbox configured")
        return
    run = tools.sandbox.run(harness(item, tools.stubs))
    if run.error:
        result.fail("runtime", "sandbox unavailable: " + run.error)
        return
    reason = runtime_verdict(run.stdout, run.rc)
    if reason:
        result.fail("runtime", reason)
    else:
        result.checks["runtime"] = "pass"


def leakage_checks(items: list[Item], results: dict[str, Result], tools: Tools, index: dict) -> None:
    config, decontam, sim = _startrain()
    guard = decontam.Decontaminator(index, config.Settings())
    vectors = tools.embed([decontam.EMBED_PREFIX + item.request[:2000] for item in items])
    kept: list[tuple[str, dict, list[float]]] = []
    for item, vector in zip(items, vectors):
        result = results[item.id]
        code = "\n".join(item.blocks)
        fp = sim.fingerprint(item.request, code, item.test)
        reason = guard.check_text(fp) or guard.check_vector(vector)
        result.checks["eval_max_cosine"] = round(guard.max_cosine(vector), 3)
        if reason:
            result.fail("leakage", reason)
            continue
        for other, ofp, ovec in kept:
            if (sim.jaccard(fp["prompt_sh5"], ofp["prompt_sh5"]) >= 0.5
                    or (len(fp["code_sh5"]) > 20 and sim.jaccard(fp["code_sh5"], ofp["code_sh5"]) >= 0.7)
                    or sim.cosine(vector, ovec) >= 0.97):
                result.fail("leakage", f"near-duplicate of {other}")
                break
        else:
            result.checks["leakage"] = "pass"
            if result.ok:
                kept.append((item.id, fp, vector))


def load_items(paths: list[Path]) -> tuple[list[Item], dict[str, Result]]:
    items, broken = [], {}
    seen = set()
    for path in paths:
        try:
            item = parse_item(path.read_text(encoding="utf-8"), str(path))
        except (ValueError, UnicodeError) as exc:
            result = Result(path.stem)
            result.fail("format", str(exc))
            broken[path.stem] = result
            continue
        if item.id in seen:
            result = Result(item.id)
            result.fail("format", "duplicate id")
            broken[item.id + "#dup"] = result
            continue
        seen.add(item.id)
        items.append(item)
    return items, broken


def verify(paths: list[Path], tools: Tools, cache_path: Path, *, workers: int = 4) -> tuple[list[Item], dict[str, Result]]:
    items, results = load_items(paths)
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    stubs_sha = hashlib.sha256(tools.stubs.encode()).hexdigest()

    def one(item: Item) -> Result:
        key = f"{VERSION}:{item.sha}:{stubs_sha}"
        hit = cache.get(item.id)
        if hit and hit.get("key") == key:
            return Result(item.id, hit["ok"], hit["reasons"], hit["checks"])
        result = Result(item.id)
        static_checks(item, tools, result)
        runtime_check(item, tools, result)
        if not any("unavailable" in r for r in result.reasons):
            cache[item.id] = {"key": key, "ok": result.ok, "reasons": result.reasons, "checks": result.checks}
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item, result in zip(items, pool.map(one, items)):
            results[item.id] = result
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    leakage_checks(items, results, tools, leakage_index(tools, cache_path))
    return items, results


# --- outputs -------------------------------------------------------------------------------------------------------

def load_sources() -> dict:
    data = json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.is_file() else {"sources": {}}
    return data.get("sources", {})


def source_record(item: Item, sources: dict) -> dict:
    if item.source == "original":
        return {"kind": "original", "spdx": ORIGINAL_SPDX, "url": "", "note": "written for STAR and verified"}
    src = sources.get(item.source_id)
    if not src or src.get("accepted") is not True:
        raise ValueError(f"source {item.source_id!r} is not an accepted entry of sources.json")
    url = src["url"].rstrip("/")
    return {"kind": item.source, "source_id": item.source_id, "spdx": src["spdx"], "url": url,
            "path": item.source_path, "commit": item.source_commit,
            "file_url": f"{url}/blob/{item.source_commit}/{item.source_path}"}


def bank_rows(items: list[Item], results: dict[str, Result], sources: dict) -> list[dict]:
    rows = []
    for item in sorted(items, key=lambda i: i.id):
        result = results[item.id]
        if not result.ok:
            continue
        try:
            source = source_record(item, sources)
        except ValueError as exc:
            result.fail("licence", str(exc))
            continue
        row = {"id": item.id, "category": item.category, "topics": item.topics, "request": item.request,
               "answer": item.answer, "source": source, "checks": result.checks, "verified": True}
        try:
            validate_row(row)
        except ValueError as exc:
            result.fail("licence", str(exc))
            continue
        rows.append(row)
    return rows


def licences_markdown(rows: list[dict], sources: dict) -> str:
    used: dict[str, int] = {}
    for row in rows:
        key = row["source"].get("source_id", "original")
        used[key] = used.get(key, 0) + 1
    lines = ["# Gold bank licences (generated by `python -m star.gold_bank_verify build`; do not edit)", "",
             "Every row of bank.jsonl records its source kind, SPDX licence id and, for third-party code, the",
             "repository, file and commit it came from. Original items were written for STAR.", "",
             "| source | items | SPDX | repository | commit |", "|---|---|---|---|---|"]
    lines.append(f"| original | {used.get('original', 0)} | {ORIGINAL_SPDX} | (this repository) | |")
    for key in sorted(k for k in used if k != "original"):
        src = sources[key]
        lines.append(f"| {key} | {used[key]} | {src['spdx']} | {src['url']} | {src['commit']} |")
    lines += ["", "## Attribution notices", ""]
    for key in sorted(k for k in used if k != "original"):
        src = sources[key]
        lines.append(f"### {src.get('name', key)} ({src['spdx']})")
        lines.append(f"Source: {src['url']} at commit {src['commit']} (licence file `{src.get('licence_path', '')}`).")
        for copyright_line in src.get("copyright", []):
            lines.append(f"- {copyright_line}")
        if src.get("attribution"):
            lines.append(f"- Attribution: {src['attribution']}")
        lines.append("")
    spdx_used = {sources[k]["spdx"] for k in used if k != "original"}
    lines += ["## Licence texts", "",
              "Third-party items marked `adapted` were modified (rewritten into a request + answer, made strict-typed",
              "and self-contained); `verbatim` items are unmodified excerpts.", ""]
    if "MIT" in spdx_used:
        lines += ["### MIT (applies with each MIT source's copyright line above)", "", MIT_TEXT, ""]
    if "Apache-2.0" in spdx_used:
        lines += ["### Apache-2.0", "",
                  "Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0). The",
                  "Apache-2.0 sources above ship no NOTICE file; the adapted items are modified works.", ""]
    return "\n".join(lines).rstrip() + "\n"


MIT_TEXT = """Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""


def manifest(items: list[Item], results: dict[str, Result], rows: list[dict]) -> dict:
    by_reason: dict[str, int] = {}
    for result in results.values():
        if not result.ok:
            for check in sorted({r.split(":", 1)[0] for r in result.reasons}):
                by_reason[check] = by_reason.get(check, 0) + 1
    kept = {row["id"] for row in rows}
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    runtime: dict[str, int] = {}
    for row in rows:
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        key = row["source"].get("source_id", "original")
        by_source[key] = by_source.get(key, 0) + 1
        state = row["checks"].get("runtime", "none")
        runtime[state] = runtime.get(state, 0) + 1
    return {
        "schema": 1, "verifier_version": VERSION,
        "stubs_sha256": hashlib.sha256(STUBS.read_bytes()).hexdigest(),
        "counts": {"written": len(results), "kept": len(rows), "dropped": len(results) - len(rows),
                   "dropped_by_check": dict(sorted(by_reason.items())), "kept_by_category": dict(sorted(by_category.items())),
                   "kept_by_source": dict(sorted(by_source.items())), "kept_runtime": dict(sorted(runtime.items()))},
        "dropped": {rid: r.reasons for rid, r in sorted(results.items()) if rid.split("#")[0] not in kept},
    }


def training_rows(rows: list[dict]) -> list[dict]:
    """The fine-tune agent's row shape (as work/ft20 bank.jsonl) plus chat messages and the licence record."""
    out = []
    for row in rows:
        out.append({
            "id": "gold-" + row["id"], "group_id": row["id"], "task_category": row["category"],
            "instruction": row["request"], "response": row["answer"],
            "messages": [{"role": "user", "content": row["request"]}, {"role": "assistant", "content": row["answer"]}],
            "evidence": ["gold bank automated checks: " + ", ".join(f"{k} {v}" for k, v in sorted(row["checks"].items())
                                                                    if k != "eval_max_cosine")],
            "source": "gold-bank-verified", "licence": row["source"], "reviewed": False,
            "rights_confirmed": row["source"]["kind"] == "original" or bool(row["source"].get("commit")),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify, build and export the gold exemplar bank")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("paths", nargs="+", type=Path)
    sub.add_parser("build")
    export = sub.add_parser("export")
    export.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "star-gold-bank" / "cache.json")
    args = parser.parse_args(argv)
    if args.command == "export":
        rows = [json.loads(line) for line in (GOLD / "bank.jsonl").read_text(encoding="utf-8").splitlines() if line]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in training_rows(rows)),
                            encoding="utf-8")
        print(f"wrote {len(rows)} training rows to {args.out}")
        return 0
    tools = Tools()
    paths = sorted(SRC.rglob("*.md")) if args.command == "build" else \
        [p for arg in args.paths for p in (sorted(arg.rglob("*.md")) if arg.is_dir() else [arg])]
    items, results = verify(paths, tools, args.cache)
    if args.command == "check":
        for rid, result in sorted(results.items()):
            print(("PASS " if result.ok else "FAIL ") + rid + ("" if result.ok else "  " + " | ".join(result.reasons)))
        return 0 if all(r.ok for r in results.values()) else 1
    sources = load_sources()
    rows = bank_rows(items, results, sources)
    (GOLD / "bank.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                                     encoding="utf-8", newline="\n")
    (GOLD / "manifest.json").write_text(json.dumps(manifest(items, results, rows), indent=1, sort_keys=True) + "\n",
                                        encoding="utf-8", newline="\n")
    (GOLD / "LICENSES.md").write_text(licences_markdown(rows, sources), encoding="utf-8", newline="\n")
    print(f"kept {len(rows)} of {len(results)}; see data/gold_bank/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
