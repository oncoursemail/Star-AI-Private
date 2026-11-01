"""Opt-in llama.cpp q8 cache argument regression tests.

These tests never start the model executable or access the GPU/network.
"""
from pathlib import Path
import pytest
from star.local_runtime import Runtime


@pytest.fixture
def model_files(tmp_path: Path):
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"fake-executable")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"x" * 100_100)
    return exe, model


def test_existing_single_model_argv_unchanged(model_files):
    exe, model = model_files
    old = Runtime.arguments(exe, model)
    explicit_default = Runtime.arguments(exe, model, flash_attention="auto", kv_cache_type="f16")
    assert old == explicit_default
    assert "-fa" not in old and "-ctk" not in old and "-ctv" not in old
    assert old[old.index("--host") + 1] == "127.0.0.1"


def test_opt_in_q8_requires_explicit_attention_and_appends_only_expected_flags(model_files):
    exe, model = model_files
    cmd = Runtime.arguments(exe, model, flash_attention="on", kv_cache_type="q8_0")
    assert cmd[-6:] == ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]
    assert cmd[cmd.index("--ctx-size") + 1] == "4096"
    assert cmd[cmd.index("-ngl") + 1] == "25"


def test_router_preserves_one_slot_one_resident_model_and_loopback(model_files):
    exe, model = model_files
    default = Runtime.router_arguments(exe, model.parent)
    assert "-fa" not in default and "-ctk" not in default
    cmd = Runtime.router_arguments(exe, model.parent, flash_attention="on", kv_cache_type="q8_0")
    assert cmd[-6:] == ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"]
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--models-max") + 1] == "1"
    assert cmd[cmd.index("-np") + 1] == "1"


def test_flash_attention_without_quantization_is_separate_opt_in(model_files):
    exe, model = model_files
    cmd = Runtime.arguments(exe, model, flash_attention="on", kv_cache_type="f16")
    assert cmd[-2:] == ["-fa", "on"]
    assert "-ctk" not in cmd


@pytest.mark.parametrize("flash,cache", [
    ("auto", "q8_0"), ("off", "q8_0"), ("yes", "f16"),
    (True, "f16"), ("on", "q4_0"), ("on", 8),
])
def test_reject_incompatible_or_unapproved_flags(model_files, flash, cache):
    exe, model = model_files
    with pytest.raises(ValueError):
        Runtime.arguments(exe, model, flash_attention=flash, kv_cache_type=cache)
    with pytest.raises(ValueError):
        Runtime.router_arguments(exe, model.parent, flash_attention=flash, kv_cache_type=cache)
