"""Optional SHA-256 launch-file pins for Star's trusted Windows worker host.

Only the owner-controlled host may configure these pins. Check immutable
local executables/scripts/config before spawning optional disposable work.
Digest checks run on the supervisor thread, never audio/gameplay callbacks.
A successful check does NOT solve path replacement after verification, dynamic
library substitution, inherited credentials, or arbitrary-code sandboxing.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import os
from pathlib import Path
import re
import stat

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK = 1024 * 1024
MAX_LAUNCH_HASH_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class HostArtifactPin:
    """Owner-reviewed file + expected digest; cannot be inferred from a model."""

    path: Path
    sha256_hex: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("pinned artifact requires an absolute path")
        if type(self.sha256_hex) is not str or not _DIGEST.fullmatch(self.sha256_hex):
            raise ValueError("pinned artifact requires lowercase SHA-256")
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("pinned artifact must be an existing regular file")

    def verify(self, *, max_bytes: int = MAX_LAUNCH_HASH_BYTES) -> bool:
        """Hash an opened file and check its identity before and after reading.

        This reduces simple disk-tampering risks but the filesystem path can
        still be changed between checking and CreateProcess; trusted host
        directory ACLs and deployment immutability are still required.
        """
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_LAUNCH_HASH_BYTES:
            raise ValueError("bounded launch-time hashing budget required")
        try:
            before = self.path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                return False
            with self.path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                    opened.st_mtime_ns,
                ):
                    return False
                digest = sha256()
                consumed = 0
                while block := stream.read(_CHUNK):
                    consumed += len(block)
                    if consumed > max_bytes:
                        return False
                    digest.update(block)
                after_fd = os.fstat(stream.fileno())
            after = self.path.lstat()
            same = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            final = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            open_final = (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns)
            return same == final == open_final and hmac.compare_digest(digest.hexdigest(), self.sha256_hex)
        except (OSError, ValueError):
            return False


__all__ = ["HostArtifactPin", "MAX_LAUNCH_HASH_BYTES"]
