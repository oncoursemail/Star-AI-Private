"""Defensive security lab: explicit owner-chosen scope, read-only by default.

Only a local directory the owner listed in ``allowed_roots`` can be a target.
URLs, missing paths, and anything that resolves outside the target are refused.
Writing needs the owner's approval. Nothing here scans or contacts anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MODE_READ_ONLY = "read_only_audit"
MODE_WRITE = "write"
_MODES = (MODE_READ_ONLY, MODE_WRITE)


class ScopeError(ValueError):
    """The requested target or mode is outside what the owner allowed."""


@dataclass(frozen=True)
class SecurityLabScope:
    root: Path
    mode: str = MODE_READ_ONLY

    @property
    def allows_write(self) -> bool:
        return self.mode == MODE_WRITE

    def contains(self, path: str | Path) -> bool:
        """True only if the fully resolved path stays inside the target."""
        try:
            Path(path).resolve().relative_to(self.root)
        except (ValueError, OSError):
            return False
        return True


def resolve_scope(
    target: str,
    *,
    allowed_roots: list[Path] | tuple[Path, ...],
    mode: str = MODE_READ_ONLY,
    owner_approved: bool = False,
) -> SecurityLabScope:
    if mode not in _MODES:
        raise ScopeError(f"unknown mode: {mode!r}")
    text = (target or "").strip()
    if not text:
        raise ScopeError("no target chosen: the owner must pick one project")
    if "://" in text:
        raise ScopeError("network targets are not allowed; choose a local project")
    root = Path(text).resolve()
    if not root.is_dir():
        raise ScopeError("target is not an existing directory")
    if not any(root == r.resolve() or r.resolve() in root.parents for r in allowed_roots):
        raise ScopeError("target is outside the owner's allowed projects")
    if mode == MODE_WRITE and not owner_approved:
        raise ScopeError("writing needs the owner's approval")
    return SecurityLabScope(root=root, mode=mode)
