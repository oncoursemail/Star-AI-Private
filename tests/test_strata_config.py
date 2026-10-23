"""No-network tests for opt-in repair of Strata's issue #728 config."""
import json
from pathlib import Path
import pytest
from star.strata_config import enable_repeat_recovery


def test_updates_only_loop_recovery_and_retains_exact_backup(tmp_path):
    path = tmp_path / "strata-qwen38-iq3_xxs.json"
    original = '{"args": ["--port", "8082"], "sampling": {"temperature": 0.7}, "api_key": "secret-private"}\n'
    path.write_text(original, encoding="utf-8")
    result = enable_repeat_recovery(path)
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["reasoning_loop_recovery"] == "recover"
    assert updated["sampling"] == {"temperature": 0.7}
    assert updated["api_key"] == "secret-private"
    backup = path.with_name(result["backup_name"])
    assert backup.read_text(encoding="utf-8") == original
    assert result["changed"] and result["restart_required"]
    assert "secret" not in repr(result)
    assert enable_repeat_recovery(path)["changed"] is False


@pytest.mark.parametrize("name", ["settings.json", "strata-other.txt", "strata-bad name.json"])
def test_rejects_unrelated_or_malformed_names(tmp_path, name):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        enable_repeat_recovery(target)


def test_invalid_json_or_oversize_does_not_touch_file(tmp_path):
    path = tmp_path / "strata-qwen.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError):
        enable_repeat_recovery(path)
    assert path.read_text(encoding="utf-8") == "not-json"
    path.write_bytes(b"a" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        enable_repeat_recovery(path)


def test_existing_backup_is_not_overwritten(tmp_path):
    path = tmp_path / "strata-qwen.json"
    path.write_text('{"api_key":"present"}', encoding="utf-8")
    backup = path.with_name(path.name + ".star-before-recovery.bak")
    backup.write_text("old backup", encoding="utf-8")
    with pytest.raises(FileExistsError):
        enable_repeat_recovery(path)
    assert backup.read_text() == "old backup"
    assert json.loads(path.read_text()) == {"api_key": "present"}


def test_rejects_symlink_when_supported(tmp_path):
    source = tmp_path / "strata-real.json"
    source.write_text("{}", encoding="utf-8")
    link = tmp_path / "strata-linked.json"
    try:
        link.symlink_to(source)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks require privilege on this OS")
    with pytest.raises(ValueError):
        enable_repeat_recovery(link)
