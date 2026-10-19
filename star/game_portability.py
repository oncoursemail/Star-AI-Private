"""Offline, documentation-backed game-portability planning.

These functions return candidate guidance from supplied facts. They do not
inspect the caller's machine, probe a browser, run code, import lessons, or train
a model. The opt-in reverse-engineering gateway owns tool availability.
"""
from __future__ import annotations

from dataclasses import dataclass


WASM32_MAX_LINEAR_MEMORY_MIB = 4096
# A bound on this planner's input, not a claim that a target can allocate 1 TiB.
MAX_LINEAR_MEMORY_MIB = 1_048_576
MAX_GUIDANCE_CHARS = 6000
TARGETS = ("browser", "roblox", "native")
TOPICS = ("overview", "browser", "streaming", "multiplayer", "asset_integrity", "roblox")
REFERENCE_REVISION = "6cef9e1fcca97dde758be845930a7bb9738339b9"
_GRAND_V = f"https://gitlab.com/SebasKitten/Grand-V/-/blob/{REFERENCE_REVISION}/"

_SOURCES: dict[str, tuple[str, str]] = {
    "memory64": (
        "WebAssembly Memory64 proposal",
        "https://github.com/WebAssembly/memory64/blob/main/proposals/memory64/Overview.md",
    ),
    "compiler_settings": (
        "Emscripten compiler settings",
        "https://emscripten.org/docs/tools_reference/settings_reference.html",
    ),
    "pthreads": ("Emscripten pthreads", "https://emscripten.org/docs/porting/pthreads.html"),
    "isolation": ("Chrome COOP/COEP guidance", "https://web.dev/articles/coop-coep"),
    "webgpu": ("Official GPUWeb explainer", "https://gpuweb.github.io/gpuweb/explainer/"),
    "gpu_timing": (
        "Chrome WebGPU timestamp queries",
        "https://developer.chrome.com/blog/new-in-webgpu-121",
    ),
    "storage": ("WHATWG Storage Standard", "https://storage.spec.whatwg.org/"),
    "opfs": ("Chrome OPFS guidance", "https://web.dev/articles/origin-private-file-system"),
    "wasm_compilation": ("V8 Wasm compilation", "https://v8.dev/docs/wasm-compilation-pipeline"),
    "frame_timing": (
        "Chrome performance reference",
        "https://developer.chrome.com/docs/devtools/performance/reference",
    ),
    "roblox_profiler": (
        "Roblox MicroProfiler",
        "https://create.roblox.com/docs/performance-optimization/microprofiler",
    ),
    "roblox_streaming": ("Roblox instance streaming", "https://create.roblox.com/docs/workspace/streaming"),
    "grand_v_readme": ("Grand-V author description", _GRAND_V + "README.md"),
    "grand_v_config": ("Grand-V inspected asset validator", _GRAND_V + "LauncherApp/rust/src/config.rs"),
    "grand_v_server": ("Grand-V inspected asset server", _GRAND_V + "LauncherApp/rust/src/server.rs"),
    "grand_v_relay": ("Grand-V inspected pose relay", _GRAND_V + "LauncherApp/rust/src/relay.rs"),
    "grand_v_build": ("Grand-V native host manifest", _GRAND_V + "LauncherApp/rust/Cargo.toml"),
}


@dataclass(frozen=True)
class _Lesson:
    principle: str
    preconditions: tuple[str, ...]
    acceptance_checks: tuple[str, ...]
    source_ids: tuple[str, ...]


_LESSONS = {
    "memory_capacity": _Lesson(
        "Memory64 extends addressability; smaller wasm32 pointers can save memory. Neither proves a speedup.",
        ("Measure live linear memory including static data, stack and heap; pin the compiler version.",),
        (
            "Probe required Wasm features and allocation on each target; account for GPU and decoded assets separately.",
            "Compare matched workloads before changing pointer width; current Emscripten docs recommend -m64.",
        ),
        ("memory64", "compiler_settings"),
    ),
    "browser_workers": _Lesson(
        "Shared-memory workers need deployment and synchronization contracts; more workers do not prove higher speed.",
        ("Verify shared Wasm memory, worker startup and cross-origin isolation in the deployed page.",),
        (
            "Keep the browser main thread responsive; avoid blocking waits that deadlock synchronous worker proxies.",
            "Test a separate nonthreaded build when semantics allow fallback; one pthread binary cannot do both.",
        ),
        ("pthreads", "isolation"),
    ),
    "gpu_contract": _Lesson(
        "WebGPU devices have specific features and limits, and may be lost. GPU timing is separate from frame timing.",
        ("Acquire an adapter and request only supported features and limits; do not infer support from a GPU name.",),
        (
            "Check shader and allocation errors, balance error scopes, and test rebuilding resources after device loss.",
            "Use supported timestamp queries; record quantization and invalid deltas instead of inventing GPU timings.",
        ),
        ("webgpu", "gpu_timing"),
    ),
    "bounded_streaming": _Lesson(
        "Stream a bounded working set. OPFS has quotas and eviction conditions; Roblox streaming has engine contracts.",
        ("Separate download, compressed cache, decoded memory and GPU budgets; choose the target's storage APIs.",),
        (
            "Test quota failure, interrupted writes, cache removal, cancellation and missing or corrupt chunks.",
            "In Roblox, test stream-out and return, respawn and moving assemblies without assuming all objects exist.",
        ),
        ("storage", "opfs", "roblox_streaming"),
    ),
    "performance_evidence": _Lesson(
        "Frame consistency and controlled workloads matter. Wasm tiering and cache state change the measurement context.",
        ("Record build, device, browser or engine, scene, quality, resolution, workload and cold/warm state.",),
        (
            "Compare frame-time distributions, stalls, memory and correctness; keep GPU pass and full-frame time distinct.",
            "Use browser traces or Roblox MicroProfiler as appropriate; fixture results do not verify full gameplay.",
        ),
        ("wasm_compilation", "frame_timing", "roblox_profiler"),
    ),
    "asset_integrity": _Lesson(
        "The inspected launcher validator checks paths and sizes. Equal-size corruption requires content-digest checks.",
        ("Use an identified manifest revision with relative paths, sizes and digests; establish manifest provenance.",),
        (
            "Reject equal-length corruption, truncation, missing entries, path escapes, duplicates and unstable files.",
            "Matching a manifest proves byte consistency for that read, not trusted authorship or later file integrity.",
        ),
        ("grand_v_config",),
    ),
    "host_budget": _Lesson(
        "The inspected host buffers batches capped at 1000 ranges and 64 MiB. Per-request caps need aggregate budgeting.",
        ("Count concurrent reads, compression copies and queued output; keep limits independent of player capacity.",),
        (
            "Exercise slow consumers, concurrent requests, malformed ranges and cancellation under a global budget.",
            "Measure time to first byte and peak resident memory before claiming streaming or language changes help.",
        ),
        ("grand_v_server",),
    ),
    "multiplayer_contract": _Lesson(
        "The inspected two-player relay forwards sequenced poses; it does not establish authoritative world simulation.",
        ("Define what state is relayed, what the server decides, and which build and map identities must match.",),
        (
            "Test duplicate and stale sequences, joins, reconnects, slow peers and bounded queues on an owned fixture.",
            "Coalesce obsolete poses separately from control events; test world consistency before expanding claims.",
        ),
        ("grand_v_relay",),
    ),
    "roblox_loop": _Lesson(
        "Apply engine-native profiling and streaming to Roblox. Browser runtime choices do not replace Roblox's engine.",
        ("Use an owned test place and discover available Studio MCP profiling methods before claiming integration.",),
        (
            "Capture the same gameplay path before and after a change; inspect script, physics and rendering spikes.",
            "Test lower-memory clients, respawn and streamed-out objects; keep unrelated correctness checks intact.",
        ),
        ("roblox_profiler", "roblox_streaming"),
    ),
}

_TOPIC_LESSONS = {
    "overview": ("memory_capacity", "browser_workers", "gpu_contract", "bounded_streaming", "performance_evidence"),
    "browser": ("memory_capacity", "browser_workers", "gpu_contract", "performance_evidence"),
    "streaming": ("bounded_streaming", "host_budget", "asset_integrity"),
    "multiplayer": ("multiplayer_contract", "host_budget", "performance_evidence"),
    "asset_integrity": ("asset_integrity", "bounded_streaming"),
    "roblox": ("roblox_loop", "asset_integrity", "performance_evidence"),
}


def _choice(name: str, value: str, choices: tuple[str, ...]) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")


def _sources(source_ids: list[str] | tuple[str, ...]) -> list[dict]:
    return [
        {"id": key, "title": _SOURCES[key][0], "url": _SOURCES[key][1]}
        for key in dict.fromkeys(source_ids)
    ]


def _candidate_metadata() -> dict:
    return {
        "schema_version": 1,
        "status": "candidate",
        "read_only": True,
        "executed": False,
        "runtime_verified": False,
        "learning_effect": "Reference guidance only; no lesson import, training or model-weight update.",
    }


def reference_guidance(topic: str = "overview") -> dict:
    """Return bounded original guidance with source and validation context."""
    _choice("topic", topic, TOPICS)
    result = _candidate_metadata()
    result.update({
        "topic": topic,
        "research_date": "2026-10-19",
        "reference_context": {
            "project": "Grand-V",
            "revision": REFERENCE_REVISION,
            "scope": (
                "Inspected native launcher source. The README's Wasm memory64, shared-memory worker and WebGPU "
                "game architecture remains author-reported; the complete browser runtime was not reproduced."
            ),
            "url": _SOURCES["grand_v_readme"][1],
        },
        "lessons": [],
    })
    source_ids: list[str] = []
    for key in _TOPIC_LESSONS[topic]:
        lesson = _LESSONS[key]
        result["lessons"].append({
            "id": key,
            "principle": lesson.principle,
            "preconditions": list(lesson.preconditions),
            "acceptance_checks": list(lesson.acceptance_checks),
            "source_ids": list(lesson.source_ids),
        })
        source_ids.extend(lesson.source_ids)
    result["sources"] = _sources(source_ids)
    result["notice"] = "Documentation and source inspection are not runtime tests; revalidate pinned target versions."
    return result


def plan_portability(
    target: str,
    *,
    required_linear_memory_mib: int,
    webgpu: bool | None = None,
    memory64: bool | None = None,
    cross_origin_isolated: bool | None = None,
    threads: bool | None = None,
    requires_threads: bool = False,
) -> dict:
    """Plan from supplied capability reports, preserving unknown versus absent.

Memory is an integer MiB requirement for live linear memory, including its
static/stack/heap overhead. It is not a measurement or a total process-memory
budget. None means unreported, not unsupported. No probe or allocation occurs.
    """
    _choice("target", target, TARGETS)
    if type(required_linear_memory_mib) is not int:
        raise TypeError("required_linear_memory_mib must be an integer, not a boolean")
    if not 1 <= required_linear_memory_mib <= MAX_LINEAR_MEMORY_MIB:
        raise ValueError(f"required_linear_memory_mib must be between 1 and {MAX_LINEAR_MEMORY_MIB}")
    capabilities = {
        "webgpu": webgpu,
        "memory64": memory64,
        "cross_origin_isolated": cross_origin_isolated,
        "threads": threads,
    }
    for name, value in capabilities.items():
        if value is not None and type(value) is not bool:
            raise TypeError(f"{name} must be a boolean or null; null means unreported")
    if type(requires_threads) is not bool:
        raise TypeError("requires_threads must be a boolean")

    result = _candidate_metadata()
    result.update({
        "target": target,
        "required_linear_memory_mib": required_linear_memory_mib,
        "requires_threads": requires_threads,
        "capability_reports": capabilities,
        "capability_evidence": "caller_supplied_not_probed_or_measured",
        "browser_capabilities_applicable": target == "browser",
        "findings": [],
        "acceptance_checks": [],
    })
    findings: list[dict] = result["findings"]
    checks: list[str] = result["acceptance_checks"]
    source_ids: list[str] = []

    def finding(code: str, level: str, message: str) -> None:
        findings.append({"code": code, "level": level, "message": message})

    if target != "browser":
        result["memory_plan"] = {
            "addressing": "engine_managed" if target == "roblox" else "native_abi_selection",
            "note": "The supplied Wasm linear-memory requirement does not establish engine, process or GPU memory use.",
        }
        result["renderer_plan"] = "engine_supported_renderer" if target == "roblox" else "native_backend_selection"
        result["threading_plan"] = {
            "path": "target_concurrency_review" if requires_threads else "target_execution_model",
            "note": "Browser reports do not verify target-native concurrency support.",
        }
        finding("browser_reports_not_applied", "context", "Browser capability reports were not used to validate this target.")
        if target == "roblox":
            checks.extend((
                "Profile an owned test place with MicroProfiler; discover Studio MCP capture methods before using them.",
                "Measure script, physics, rendering and asset memory on target clients; use supported engine APIs.",
                "Test stream-out/return, respawn and missing instances; browser Wasm/WebGPU plans do not replace Roblox.",
            ))
            source_ids.extend(("roblox_profiler", "roblox_streaming"))
        else:
            checks.extend((
                "Choose and build the target OS/ABI and rendering backend; verify dependencies and memory allocations.",
                "Measure a representative workload before choosing a language or claiming a host/runtime speedup.",
                "Test asset integrity, service shutdown, bounded concurrent work and recovery on each supported OS.",
            ))
            source_ids.extend(("grand_v_build", "grand_v_server", "grand_v_config"))
        if requires_threads:
            checks.append("Validate the target's concurrency model, synchronization and correctness under contention.")
    else:
        source_ids.extend(("memory64", "compiler_settings", "webgpu", "frame_timing"))
        if required_linear_memory_mib <= WASM32_MAX_LINEAR_MEMORY_MIB:
            result["memory_plan"] = {
                "addressing": "wasm32",
                "note": "Fits the theoretical address-space limit; allocation and total memory remain unverified.",
            }
            if required_linear_memory_mib == WASM32_MAX_LINEAR_MEMORY_MIB:
                finding(
                    "wasm32_at_limit", "verify",
                    "4096 MiB uses the full wasm32 address space. Confirm all overhead is included and allocation "
                    "succeeds; otherwise reduce the working set or verify memory64.",
                )
            if memory64 is True:
                finding(
                    "memory64_not_required", "context",
                    "Reported memory64 support does not justify wider pointers for this supplied requirement or prove speed.",
                )
        else:
            result["memory_plan"] = {
                "addressing": "wasm64_required",
                "note": "The supplied requirement exceeds wasm32's address space; wasm32 is not a viable unchanged path.",
            }
            if memory64 is False:
                finding(
                    "memory64_unavailable", "blocked",
                    "Memory64 is reported unavailable. Use a verified capable target, reduce live memory, or select native.",
                )
            elif memory64 is None:
                finding("memory64_unreported", "unknown", "Memory64 support must be probed before this requirement can run.")
            else:
                finding(
                    "memory64_report_needs_validation", "verify",
                    "Reported memory64 support is not an allocation test. Pin a supported toolchain and test actual limits.",
                )
        checks.append(
            "Verify the chosen Wasm module and allocation on each target; include static/stack/heap and separate GPU/asset use."
        )

        if webgpu is True:
            result["renderer_plan"] = "webgpu_candidate"
        elif webgpu is False:
            result["renderer_plan"] = "verified_alternative_required"
            finding(
                "webgpu_unavailable", "verify",
                "WebGPU is reported unavailable; test an alternative renderer such as WebGL2 without assuming it is supported.",
            )
        else:
            result["renderer_plan"] = "capability_probe_required"
            finding("webgpu_unreported", "unknown", "WebGPU support and adapter availability have not been reported.")
        checks.append(
            "For WebGPU, validate adapter/features/limits, shader and allocation errors, and recovery after device loss; "
            "otherwise validate the chosen fallback renderer."
        )

        if requires_threads:
            source_ids.extend(("pthreads", "isolation"))
            for name, value in (("threads", threads), ("cross_origin_isolated", cross_origin_isolated)):
                if value is False:
                    finding(f"{name}_unavailable", "blocked", f"Required browser prerequisite {name} is reported false.")
                elif value is None:
                    finding(f"{name}_unreported", "unknown", f"Required browser prerequisite {name} needs runtime verification.")
            if threads is False or cross_origin_isolated is False:
                thread_path = "unsupported_as_reported"
            elif threads is None or cross_origin_isolated is None:
                thread_path = "pthread_requires_verification"
            else:
                thread_path = "pthread_candidate"
            result["threading_plan"] = {
                "path": thread_path,
                "single_binary_fallback": False,
                "fallback": "Build a separate nonthreaded binary only if workload semantics permit; otherwise report unsupported.",
            }
            checks.extend((
                "Verify COOP/COEP, deployed crossOriginIsolated, shared Wasm memory and actual worker startup/resource loading.",
                "Keep the browser main thread responsive; avoid blocking waits while workers synchronously proxy work to it.",
                "Profile bounded worker-pool sizes and startup; test the distinct nonthreaded build if offering that fallback.",
            ))
        else:
            result["threading_plan"] = {
                "path": "single_threaded_candidate",
                "note": "No pthread requirement supplied; optional threading needs separate capability and workload validation.",
            }
            checks.append("Keep long work off the browser UI critical path and test input responsiveness during loading.")
        checks.extend((
            "Compare fixed scenes at matched quality/resolution using cold/warm runs, frame-time distributions and correctness.",
            "Budget streamed assets and cache copies; handle quota failures, interrupted writes and cache eviction.",
        ))
        source_ids.extend(("storage", "opfs"))

    levels = {item["level"] for item in findings}
    if "blocked" in levels:
        result["assessment"] = "blocked_by_reported_capabilities"
    elif "unknown" in levels:
        result["assessment"] = "needs_capability_verification"
    else:
        result["assessment"] = "candidate_requires_runtime_validation"
    result["sources"] = _sources(source_ids)
    result["notice"] = "This is a plan from supplied reports, not a successful build, compatibility test or measured speedup."
    return result
