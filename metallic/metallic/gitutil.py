"""Thin git helpers. Every call is a subprocess with an explicit cwd; nothing here changes the user's index or HEAD."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: str | os.PathLike, *, env: dict | None = None, check: bool = True,
        identity: tuple[str, str] | None = None) -> str:
    cmd = ["git"]
    if identity:
        cmd += ["-c", "user.name=" + identity[0], "-c", "user.email=" + identity[1]]
    full_env = dict(os.environ, **(env or {}))
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    proc = subprocess.run(cmd + args, cwd=str(cwd), env=full_env, capture_output=True)
    out = proc.stdout.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} failed ({proc.returncode}): "
                       + proc.stderr.decode("utf-8", "replace").strip()[:400])
    return out


def ok(args: list[str], cwd) -> bool:
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True).returncode == 0


def repo_root(path: str | os.PathLike = ".") -> Path:
    return Path(git(["rev-parse", "--show-toplevel"], path).strip())


def common_dir(root: Path) -> Path:
    p = Path(git(["rev-parse", "--git-common-dir"], root).strip())
    return p if p.is_absolute() else (root / p).resolve()


def state_dir(root: Path) -> Path:
    """Per-clone state shared by all worktrees (queue, runs, lock); never inside the work tree, never committed."""
    d = common_dir(root) / "metallic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def rev(ref: str, cwd) -> str:
    return git(["rev-parse", "--verify", ref + "^{commit}"], cwd).strip()


def current_branch(cwd) -> str:
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


def worktree_tree(root: Path) -> str:
    """Tree hash of the work tree as it is now (tracked + untracked, minus ignored), via a throw-away index.

    The real index is copied first so `git add -A` can reuse its stat cache; the user's index is never written.
    copy2 keeps the index file's mtime: git's racy-entry rule compares entry mtimes with it, and a fresh mtime would
    make a same-size edit made in the same second as the last `git add` invisible."""
    real_index = Path(git(["rev-parse", "--git-path", "index"], root).strip())
    if not real_index.is_absolute():
        real_index = root / real_index
    fd, tmp = tempfile.mkstemp(prefix="metallic-index-")
    os.close(fd)
    try:
        if real_index.exists():
            shutil.copy2(real_index, tmp)
        else:
            os.unlink(tmp)
        env = {"GIT_INDEX_FILE": tmp}
        git(["add", "-A", "."], root, env=env)
        return git(["write-tree"], root, env=env).strip()
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def tree_of(ref: str, cwd) -> str:
    return git(["rev-parse", "--verify", ref + "^{tree}"], cwd).strip()


def blobs(tree: str, cwd) -> dict[str, str]:
    """path -> blob hash for every file in a tree (submodules and symlinks included as their object ids)."""
    out = git(["ls-tree", "-r", "-z", "--full-tree", tree], cwd)
    result = {}
    for rec in out.split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        result[path] = meta.split()[2]
    return result


def changed(base_tree: str, tree: str, cwd) -> list[str]:
    out = git(["diff", "--name-only", "-z", "--no-renames", base_tree, tree], cwd)
    return [p for p in out.split("\0") if p]


def diff_text(base_tree: str, tree: str, cwd, paths: list[str] | None = None) -> str:
    return git(["diff", "--no-color", "--no-renames", "-U0", base_tree, tree] + (["--"] + paths if paths else []), cwd)


def read_blob(blob: str, cwd) -> bytes:
    return subprocess.run(["git", "cat-file", "blob", blob], cwd=str(cwd), capture_output=True, check=True).stdout
