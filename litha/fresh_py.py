"""The environment for every Python run on code Litha just changed (a planted mutant, a candidate fix, a proof).

Python keeps a module's .pyc while the source has the same size and the same mtime second. A mutant (`+` -> `-`,
`<` -> `>`) or a one-token fix is the same size, and on a fast machine it is written within that second: the run then
executes the OLD code. Measured 2026-11-02 on Linux: rewrite `1 + 1` to `1 - 1` and import -> 2. On CI this hid
every planted bug of the standard-suite test (0/4 killed) and let a no-op edit pass for a fix.
Her runs write no bytecode, and the checkout's own caches are dropped before each run, so its code is compiled from
the source she sees. Installed packages keep theirs (a cache prefix for everything cost 1-1.5 s per pytest start)."""
from __future__ import annotations

import os
from pathlib import Path

SKIP = {".git", "node_modules", "target", "dist", "build", "site-packages", "__pypackages__"}


def forget(tree: Path) -> int:
    """Delete the .pyc files under the checkout (not in its venvs or node_modules); how many."""
    n = 0
    for root, dirs, files in os.walk(tree):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".venv")]
        if os.path.basename(root) == "__pycache__":
            for f in files:
                if f.endswith(".pyc"):
                    try:
                        os.unlink(os.path.join(root, f))
                        n += 1
                    except OSError:
                        pass
    return n


def env(tree: Path | None = None, **extra: str) -> dict[str, str]:
    """os.environ + no bytecode written, + extra; with a tree, its stale caches are dropped first."""
    if tree is not None:
        forget(tree)
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **extra)
