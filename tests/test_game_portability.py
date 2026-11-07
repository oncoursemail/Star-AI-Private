"""WebAssembly portability analysis on small hand-built modules."""
from __future__ import annotations

import pytest

from star.game_portability import analyse_wasm

HEADER = b"\0asm\x01\0\0\0"


def leb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def name(text: str) -> bytes:
    raw = text.encode()
    return leb(len(raw)) + raw


def section(section_id: int, body: bytes) -> bytes:
    return bytes([section_id]) + leb(len(body)) + body


def memory_section(*limits: bytes) -> bytes:
    return section(5, leb(len(limits)) + b"".join(limits))


def func_imports(*pairs: tuple[str, str]) -> bytes:
    body = leb(len(pairs)) + b"".join(name(m) + name(f) + b"\x00" + leb(0) for m, f in pairs)
    return section(2, body)


def codes(report: dict) -> set[str]:
    return {item["code"] for item in report["findings"]}


def test_plain_wasm32_memory_reports_pages_and_mib():
    report = analyse_wasm(HEADER + memory_section(b"\x01" + leb(256) + leb(512)))
    assert report["memories"] == [{"min_pages": 256, "max_pages": 512, "shared": False, "memory64": False,
                                   "imported": False, "min_mib": 16.0, "max_mib": 32.0}]
    assert codes(report) == set()


def test_shared_memory_requires_cross_origin_isolation():
    report = analyse_wasm(HEADER + memory_section(b"\x03" + leb(1) + leb(16384)))
    assert report["memories"][0]["shared"] is True
    assert "shared_memory_threads" in codes(report)


def test_memory64_flag_reads_64_bit_limits():
    big = 6 * 1024 * 16  # 6 GiB in 64 KiB pages: impossible for wasm32
    report = analyse_wasm(HEADER + memory_section(b"\x04" + leb(big)))
    assert report["memories"][0]["memory64"] is True
    assert report["memories"][0]["min_mib"] == 6144.0
    assert "memory64_required" in codes(report)


def test_unbounded_and_over_limit_wasm32_memories_are_flagged():
    assert "memory_unbounded" in codes(analyse_wasm(HEADER + memory_section(b"\x00" + leb(1))))
    assert "wasm32_memory_invalid" in codes(analyse_wasm(HEADER + memory_section(b"\x00" + leb(70000))))


def test_imported_memory_and_host_apis_come_from_the_import_section():
    imports = func_imports(("env", "wgpuDeviceCreateBuffer"), ("env", "glClear"),
                           ("wasi_snapshot_preview1", "fd_write"), ("env", "emscripten_sleep"))
    mem_import = section(2, leb(1) + name("env") + name("memory") + b"\x02\x01" + leb(2) + leb(4))
    report = analyse_wasm(HEADER + imports + mem_import)
    assert report["host_apis"] == ["emscripten_runtime", "wasi", "webgl", "webgpu"]
    assert report["function_imports"] == 4
    assert report["import_modules"] == {"env": 4, "wasi_snapshot_preview1": 1}
    assert report["memories"][0]["imported"] is True
    assert {"webgpu_imports", "wasi_imports"} <= codes(report)
    assert "webgl_imports" not in codes(report)  # WebGPU dominates the renderer finding


def test_target_features_section_lists_required_features():
    body = name("target_features") + leb(2) + b"+" + name("simd128") + b"-" + name("tail-call")
    report = analyse_wasm(HEADER + section(0, body) + memory_section(b"\x01" + leb(1) + leb(1)))
    assert report["target_features"] == ["+simd128", "-tail-call"]
    assert "simd128_required" in codes(report)
    assert "tail_call_required" not in codes(report)


def test_large_code_section_is_skipped_not_parsed():
    report = analyse_wasm(HEADER + section(10, b"\xff" * 5000))
    assert report["sections"] == [{"id": 10, "name": "code", "size": 5000}]
    assert "no_memory" in codes(report)


@pytest.mark.parametrize("data", [b"MZ\x90\x00", b"\0asm\x02\0\0\0", HEADER + b"\x05\x10\x01",
                                  HEADER + memory_section(b"\x08" + leb(1))])
def test_non_wasm_truncated_or_unknown_flags_raise(data):
    with pytest.raises(ValueError):
        analyse_wasm(data)
