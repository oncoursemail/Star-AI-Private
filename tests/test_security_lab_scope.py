"""Security lab scope: explicit owner-chosen target, read-only by default."""

from pathlib import Path

import pytest

from star.security_lab import ScopeError, SecurityLabScope, resolve_scope


def test_no_target_is_refused(tmp_path):
    with pytest.raises(ScopeError):
        resolve_scope("", allowed_roots=[tmp_path])


def test_default_is_read_only_audit(tmp_path):
    scope = resolve_scope(str(tmp_path), allowed_roots=[tmp_path])
    assert isinstance(scope, SecurityLabScope)
    assert scope.mode == "read_only_audit"
    assert scope.allows_write is False
    assert scope.root == Path(tmp_path).resolve()


def test_target_outside_owner_roots_is_refused(tmp_path):
    allowed = tmp_path / "owner"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ScopeError):
        resolve_scope(str(other), allowed_roots=[allowed])


def test_missing_target_is_refused(tmp_path):
    with pytest.raises(ScopeError):
        resolve_scope(str(tmp_path / "nope"), allowed_roots=[tmp_path])


def test_url_target_is_refused(tmp_path):
    with pytest.raises(ScopeError):
        resolve_scope("https://example.com/app", allowed_roots=[tmp_path])


def test_write_mode_requires_owner_approval(tmp_path):
    with pytest.raises(ScopeError):
        resolve_scope(str(tmp_path), allowed_roots=[tmp_path], mode="write")
    scope = resolve_scope(
        str(tmp_path), allowed_roots=[tmp_path], mode="write", owner_approved=True
    )
    assert scope.allows_write is True


def test_path_breakout_is_refused(tmp_path):
    inner = tmp_path / "proj"
    inner.mkdir()
    scope = resolve_scope(str(inner), allowed_roots=[tmp_path])
    assert scope.contains(inner / "a.py")
    assert not scope.contains(inner / ".." / "secret.txt")
    assert not scope.contains(tmp_path / "elsewhere")


def test_symlink_breakout_is_refused(tmp_path):
    inner = tmp_path / "proj"
    inner.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = inner / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    scope = resolve_scope(str(inner), allowed_roots=[tmp_path])
    assert not scope.contains(link / "x.txt")


def test_unknown_mode_is_refused(tmp_path):
    with pytest.raises(ScopeError):
        resolve_scope(str(tmp_path), allowed_roots=[tmp_path], mode="scan")
