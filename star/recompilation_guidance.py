"""Original engineering guidance from a pinned ps3recomp source audit.

Reference context is not a trained model, an accepted lesson, or execution
evidence. Source inspection, fixture coverage and gameplay remain distinct.
"""
from __future__ import annotations

from copy import deepcopy

PS3RECOMP_COMMIT = "749182eebb936f086a007f63e1c7d853f3cf708a"
_BASE = f"https://github.com/sp00nznet/ps3recomp/blob/{PS3RECOMP_COMMIT}/"
TOPICS = ("overview", "elf", "ppu", "spu", "verification", "runtime", "porting")
_SOURCES = {
    "ps3_overview": ("ps3recomp architecture and platform scope", _BASE + "README.md"),
    "ps3_parser": ("Inspected ELF parser", _BASE + "tools/elf_parser.py"),
    "ppu_lifter": ("Inspected PPU translation and fallback", _BASE + "tools/ppu_lifter.py"),
    "ppu_tests": ("PPU conformance case generation", _BASE + "tools/test_ppu_lift.py"),
    "spu_interpreter": ("SPU runtime interpreter", _BASE + "runtime/spu/spu_interp.c"),
    "float_referee": ("SPU mismatch classifier", _BASE + "runtime/spu/tests/spu_float_referee.py"),
    "diff_driver": ("Differential test exit handling", _BASE + "runtime/spu/tests/build_diff_test.sh"),
    "regression_gate": ("Regression scope and mutable first-run state", _BASE + "docs/REGRESSION_GATE.md"),
    "runtime": ("PS3 runtime model", _BASE + "docs/RUNTIME.md"),
    "elf_header": ("ELF header format", "https://gabi.xinuos.com/elf/02-eheader.html"),
    "elf_load": ("ELF program loading", "https://gabi.xinuos.com/elf/07-pheader.html"),
    "alive2": ("Alive2 LLVM translation validation", "https://github.com/AliveToolkit/alive2"),
    "csmith": ("Csmith differential compiler testing", "https://github.com/csmith-project/csmith"),
}

_PRINCIPLES = (
    {
        "id": "validate_container_before_translation",
        "topics": ("elf", "porting"),
        "principle": "Validate the declared file structure before deriving a load map or lifting code.",
        "preconditions": ["A selected local unencrypted ELF within the analysis budget."],
        "acceptance_checks": [
            "Reject unknown class/encoding values and truncated declared header tables.",
            "Check every supported file and address range; distinguish initialized bytes from zero-fill.",
            "Retain unsupported extensions as unresolved; parsing does not establish playability.",
        ],
        "sources": ("ps3_parser", "elf_header", "elf_load"),
    },
    {
        "id": "preserve_guest_abi",
        "topics": ("elf", "ppu", "porting"),
        "principle": "Separate container width, guest effective addresses, function descriptors and host pointers.",
        "preconditions": ["A verified ABI/profile for the exact guest image and target runtime."],
        "acceptance_checks": [
            "Record the raw entry value and mapped region; do not assume it is directly callable code.",
            "Verify TOC, entry descriptors, stack layout, endian conversions and indirect calls with fixtures.",
            "Do not apply a generic Linux PPC64 descriptor layout to a PS3 image without evidence.",
        ],
        "sources": ("runtime", "elf_header", "ppu_lifter"),
    },
    {
        "id": "test_instruction_semantics",
        "topics": ("ppu", "spu", "verification"),
        "principle": "A compilable lowering must preserve the selected instruction's defined behavior.",
        "preconditions": ["Explicit input bit patterns, expected observables and a stated ISA interpretation."],
        "acceptance_checks": [
            "Exercise signedness, carry, saturation, shifts, endian lanes and exceptional operands.",
            "Compare fixed-width raw bits; do not hide guest float differences with a global tolerance.",
            "Track unhandled opcodes and unverified no-op replacements instead of counting them as covered.",
        ],
        "sources": ("ppu_lifter", "ppu_tests", "csmith"),
    },
    {
        "id": "keep_spu_state_explicit",
        "topics": ("spu", "runtime"),
        "principle": "SPU behavior includes local store, image identity, DMA and ordered communication.",
        "preconditions": ["An identified SPU image and a defined communication scenario."],
        "acceptance_checks": [
            "Check the 256 KiB local-store boundary and overlapping image addresses.",
            "Observe DMA completion, channel/mailbox event order and synchronization under contention.",
            "Record interpreted versus lifted paths; a valid fallback need not imply full static coverage.",
        ],
        "sources": ("runtime", "spu_interpreter", "ps3_overview"),
    },
    {
        "id": "require_complete_test_inventory",
        "topics": ("verification", "ppu", "spu"),
        "principle": "No mismatch lines is insufficient evidence that a test suite completed.",
        "preconditions": ["A nonempty expected case inventory established independently of the observed log."],
        "acceptance_checks": [
            "Require the exact expected case IDs, inputs, observations and completed run status.",
            "Treat missing, duplicate, extra, skipped, unknown and unsupported cases explicitly.",
            "Preserve process failures and completion counts before applying a mismatch classifier.",
        ],
        "sources": ("float_referee", "diff_driver", "ppu_tests"),
    },
    {
        "id": "bound_oracle_claims",
        "topics": ("verification", "porting"),
        "principle": "Bind comparisons to a suite and artifacts, and state what the oracle actually establishes.",
        "preconditions": ["Separate recorded reference/candidate runs and reproducible suite identity."],
        "acceptance_checks": [
            "Pin reference inputs where available and preserve the first reproducible counterexample.",
            "Record producer and run identities; different labels alone do not authenticate independence.",
            "Use formal validation only within supported IR semantics; fixture agreement is not a whole-game proof.",
        ],
        "sources": ("alive2", "csmith"),
    },
    {
        "id": "measure_runtime_service_coverage",
        "topics": ("runtime", "porting", "verification"),
        "principle": "Runtime services must be validated by behavior exercised by the target scenario.",
        "preconditions": ["An import/service inventory and representative guest workloads."],
        "acceptance_checks": [
            "Count unresolved services and unverified stubs even when a function returns success.",
            "Check callbacks, buffer ownership, errors, threading and state changes, not only return values.",
            "Separate runtime-library build results from title boot, rendering, audio and gameplay.",
        ],
        "sources": ("runtime", "ps3_overview"),
    },
    {
        "id": "reproduce_initial_state",
        "topics": ("verification", "runtime", "porting"),
        "principle": "A repeatable regression scenario includes its initial state and measurement scope.",
        "preconditions": ["An isolated fixture state and recorded platform, compiler, runtime and workload."],
        "acceptance_checks": [
            "Reset first-run save/install state and record whether a scenario was actually executed.",
            "Report unavailable scenarios as missing coverage, not successful gameplay.",
            "Compare distributions and resource budgets for the same workload before claiming a speedup.",
        ],
        "sources": ("regression_gate", "ps3_overview"),
    },
    {
        "id": "separate_visual_and_cpu_evidence",
        "topics": ("porting", "runtime", "verification"),
        "principle": "Correct CPU outputs and a headless milestone do not establish visual or gameplay fidelity.",
        "preconditions": ["A target-specific rendering and interaction acceptance scenario."],
        "acceptance_checks": [
            "Capture representative rendered frames, audio and interaction behavior on the intended backend.",
            "Keep downstream patches and their platform evidence separate from upstream library CI.",
            "For STAR projects, use their native test environment before proposing a reviewed reusable lesson.",
        ],
        "sources": ("ps3_overview", "regression_gate"),
    },
)


def recompilation_guidance(topic: str = "overview") -> dict:
    if not isinstance(topic, str) or topic not in TOPICS:
        raise ValueError("Unknown recompilation guidance topic")
    selected = [item for item in _PRINCIPLES if topic == "overview" or topic in item["topics"]]
    source_ids = dict.fromkeys(source for item in selected for source in item["sources"])
    return {
        "status": "candidate",
        "topic": topic,
        "read_only": True,
        "executed": False,
        "runtime_verified": False,
        "evidence_scope": "reference_guidance",
        "research_date": "2026-10-19",
        "reference": {"project": "sp00nznet/ps3recomp", "commit": PS3RECOMP_COMMIT, "release": "v0.16.0"},
        "principles": deepcopy(selected),
        "sources": [{"id": key, "title": _SOURCES[key][0], "url": _SOURCES[key][1]} for key in source_ids],
        "learning_effect": (
            "On-demand reference context only. No model training or automatic lesson acceptance. "
            "Project-specific execution evidence and STAR's existing review/evaluation gates remain required."
        ),
        "toolchain_note": "Recheck mutable external documentation for the selected compiler/runtime version.",
    }
