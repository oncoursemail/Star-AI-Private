"""Explicit, backed-up local Strata issue #728 recovery configuration.

Only a Strata config file deliberately chosen by the owner may be changed.
STAR never edits Strata files during a chat or enables external network access.
The engine must be restarted to read the new configuration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile

_MAX_BYTES = 2 * 1024 * 1024
_CONFIG_NAME = re.compile(r"^strata-[A-Za-z0-9_.-]{1,120}\.json$")


def enable_repeat_recovery(path: Path) -> dict:
    """Safely set an existing Strata run config to reasoning_loop_recovery='recover'.

    The backup is created exclusively, never overwritten. Paths and config
    contents (which may contain an API key) are not returned to the UI.
    """
    config_path = Path(path)
    if (not _CONFIG_NAME.fullmatch(config_path.name)
            or config_path.is_symlink() or str(config_path).startswith(("\\\\", "//"))):
        raise ValueError("Choose an existing local strata-<model>.json configuration file")
    try:
        details = config_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= _MAX_BYTES:
            raise ValueError("Strata config must be a regular JSON file smaller than 2 MiB")
        original = config_path.read_bytes()
        document = json.loads(original.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read a valid Strata JSON configuration") from exc
    if not isinstance(document, dict):
        raise ValueError("Strata configuration must be a JSON object")
    if document.get("reasoning_loop_recovery") == "recover":
        return {"configured": True, "changed": False, "restart_required": False}

    # Strata 0.1.40+ understands this key. Do not attempt to change its model,
    # cache, sampling, API key, server host, or other launch settings.
    document["reasoning_loop_recovery"] = "recover"
    updated = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(updated) > _MAX_BYTES:
        raise ValueError("Updated Strata configuration would exceed the size limit")
    backup = config_path.with_name(config_path.name + ".star-before-recovery.bak")
    if backup.exists() or backup.is_symlink():
        raise FileExistsError(
            "STAR found an existing Strata recovery backup; it will not overwrite it. "
            "Review the earlier change before modifying this configuration again."
        )

    # Backup is exact original bytes, never sent outside this machine.
    mode = stat.S_IMODE(details.st_mode)
    fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode or 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        backup.unlink(missing_ok=True)
        raise

    temporary: str | None = None
    try:
        handle, temporary = tempfile.mkstemp(prefix=".strata-recovery-", dir=config_path.parent)
        with os.fdopen(handle, "wb") as output:
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode or 0o600)
        os.replace(temporary, config_path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return {"configured": True, "changed": True, "restart_required": True,
            "backup_name": backup.name}
