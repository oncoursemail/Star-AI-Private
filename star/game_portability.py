"""Browser/native portability facts read from a user-supplied WebAssembly module.

Parses only the module's section headers, imports, memories and the
`target_features` custom section. Nothing is compiled, instantiated or run, and
the findings describe what the module requires, not whether a target can run it.
"""
from __future__ import annotations

import re

WASM_PAGE_BYTES = 64 * 1024
WASM32_MAX_PAGES = 65536          # 4 GiB address space
MAX_IMPORTS = 100_000
MAX_DETAILS = 40

_SECTION_NAMES = {0: "custom", 1: "type", 2: "import", 3: "function", 4: "table", 5: "memory",
                  6: "global", 7: "export", 8: "start", 9: "element", 10: "code", 11: "data",
                  12: "datacount", 13: "tag"}
_GL = re.compile(r"gl[A-Z]")
_WASI_MODULES = {"wasi_snapshot_preview1", "wasi_unstable"}


class _Reader:
    def __init__(self, data: bytes, pos: int = 0, end: int | None = None):
        self.data, self.pos = data, pos
        self.end = len(data) if end is None else end

    def byte(self) -> int:
        if self.pos >= self.end:
            raise ValueError("Unexpected end of WebAssembly data")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def uleb(self, max_bits: int = 32) -> int:
        result = shift = 0
        while True:
            byte = self.byte()
            result |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
            if shift >= max_bits + 7:
                raise ValueError("Malformed LEB128 integer")
        if result >= 1 << max_bits:
            raise ValueError("LEB128 integer out of range")
        return result

    def name(self) -> str:
        length = self.uleb()
        if self.pos + length > self.end:
            raise ValueError("Name runs past its section")
        raw = self.data[self.pos:self.pos + length]
        self.pos += length
        return raw.decode("utf-8", "replace")[:200]

    def limits(self) -> dict:
        flags = self.byte()
        if flags & ~0x07:
            raise ValueError(f"Unknown limits flags 0x{flags:02x}")
        wide = bool(flags & 0x04)
        minimum = self.uleb(64 if wide else 32)
        maximum = self.uleb(64 if wide else 32) if flags & 0x01 else None
        return {"min_pages": minimum, "max_pages": maximum,
                "shared": bool(flags & 0x02), "memory64": wide}


def _memory_row(limits: dict, imported: bool) -> dict:
    row: dict = {**limits, "imported": imported}
    row["min_mib"] = round(limits["min_pages"] * WASM_PAGE_BYTES / 2**20, 2)
    row["max_mib"] = (None if limits["max_pages"] is None
                      else round(limits["max_pages"] * WASM_PAGE_BYTES / 2**20, 2))
    return row


def analyse_wasm(data: bytes) -> dict:
    """Return module facts plus portability findings derived only from them."""
    if data[:4] != b"\0asm":
        raise ValueError("Not a WebAssembly binary module (missing \\0asm magic)")
    if len(data) < 8 or int.from_bytes(data[4:8], "little") != 1:
        raise ValueError("Unsupported WebAssembly binary version (only version 1 is parsed)")
    reader = _Reader(data, 8)
    sections: list[dict] = []
    memories: list[dict] = []
    imports: dict[str, int] = {}
    import_names: list[str] = []
    features: list[str] = []
    counts = {"function_imports": 0, "exports": 0}
    while reader.pos < len(data):
        section_id = reader.byte()
        size = reader.uleb()
        start, end = reader.pos, reader.pos + size
        if end > len(data):
            raise ValueError("Section runs past the end of the file")
        body = _Reader(data, start, end)
        label = _SECTION_NAMES.get(section_id, f"unknown_{section_id}")
        if section_id == 0:
            label = "custom:" + body.name()
            if label == "custom:target_features":
                for _ in range(min(body.uleb(), 256)):
                    prefix = chr(body.byte())
                    features.append(prefix + body.name())
        elif section_id == 2:
            total = body.uleb()
            if total > MAX_IMPORTS:
                raise ValueError("Import count exceeds the parser bound")
            for _ in range(total):
                module, field = body.name(), body.name()
                imports[module] = imports.get(module, 0) + 1
                kind = body.byte()
                if kind == 0:
                    body.uleb()
                    counts["function_imports"] += 1
                    import_names.append(field)
                elif kind == 1:
                    body.byte()
                    body.limits()
                elif kind == 2:
                    memories.append(_memory_row(body.limits(), True))
                elif kind == 3:
                    body.byte()
                    body.byte()
                elif kind == 4:
                    body.byte()
                    body.uleb()
                else:
                    raise ValueError(f"Unknown import kind {kind}")
        elif section_id == 5:
            for _ in range(body.uleb()):
                memories.append(_memory_row(body.limits(), False))
        elif section_id == 7:
            counts["exports"] = body.uleb()
        sections.append({"id": section_id, "name": label, "size": size})
        reader.pos = end

    host_apis = sorted({api for api, hit in (
        ("webgpu", any(n.startswith(("wgpu", "emscripten_webgpu")) for n in import_names)),
        ("webgl", any(_GL.match(n) or n.startswith("emscripten_webgl") for n in import_names)),
        ("wasi", bool(_WASI_MODULES & set(imports))),
        ("emscripten_runtime", any(n.startswith(("emscripten_", "__syscall", "_emscripten")) for n in import_names)),
    ) if hit})
    return {
        "format": "wasm", "version": 1, "size_bytes": len(data),
        "sections": sections[:MAX_DETAILS], "sections_omitted": max(0, len(sections) - MAX_DETAILS),
        "memories": memories, "import_modules": imports, **counts,
        "target_features": features, "host_apis": host_apis,
        "findings": _findings(memories, features, host_apis, any(s["id"] == 13 for s in sections)),
        "executed": False, "untrusted": True,
        "notice": ("Facts come from the module bytes only. Target support (browser version, GPU adapter, "
                   "server headers) is not probed; test the module on each target before claiming it runs."),
    }


def _findings(memories: list[dict], features: list[str], host_apis: list[str], has_tags: bool) -> list[dict]:
    out: list[dict] = []

    def add(code: str, level: str, message: str) -> None:
        out.append({"code": code, "level": level, "message": message})

    enabled = {f[1:] for f in features if f.startswith(("+", "="))}
    for index, memory in enumerate(memories):
        if memory["memory64"]:
            add("memory64_required", "requires",
                f"Memory {index} uses 64-bit indices: the target runtime must support the Memory64 proposal.")
        elif memory["min_pages"] > WASM32_MAX_PAGES:
            add("wasm32_memory_invalid", "blocked",
                f"Memory {index} declares {memory['min_pages']} initial pages, beyond the 4 GiB wasm32 limit.")
        elif memory["max_pages"] is None and not memory["shared"]:
            add("memory_unbounded", "context",
                f"Memory {index} has no maximum: it may grow toward the 4 GiB wasm32 limit; budget the device.")
        if memory["shared"]:
            add("shared_memory_threads", "requires",
                f"Memory {index} is shared (threads): browsers need a cross-origin-isolated page "
                "(COOP/COEP headers) for SharedArrayBuffer; one threaded binary cannot fall back to no threads.")
    for feature, message in (("simd128", "128-bit SIMD instructions are enabled: the target must support Wasm SIMD."),
                             ("exception-handling", "Wasm exception handling is enabled: check target support."),
                             ("tail-call", "Tail calls are enabled: check target support.")):
        if feature in enabled:
            add(feature.replace("-", "_") + "_required", "requires", message)
    if has_tags and "exception-handling" not in enabled:
        add("exception_handling_required", "requires", "The module has a tag section (Wasm exceptions).")
    if "webgpu" in host_apis:
        add("webgpu_imports", "requires",
            "Imports WebGPU bindings: the page needs an available GPU adapter; there is no automatic WebGL fallback.")
    if "webgl" in host_apis and "webgpu" not in host_apis:
        add("webgl_imports", "context", "Imports WebGL/GL bindings (WebGL2 context expected in browsers).")
    if "wasi" in host_apis:
        add("wasi_imports", "context",
            "Imports WASI: runs directly in WASI runtimes (wasmtime, wasmer); browsers need a WASI shim.")
    if not memories:
        add("no_memory", "context", "The module declares no linear memory.")
    return out
