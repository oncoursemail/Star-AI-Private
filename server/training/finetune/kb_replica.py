"""Gate-only replica of STAR Knowledge on this PC, so a gate run never loads brain 1 (whose quiet lock other agents
hold for hours) while still answering with the same documents.

    python kb_replica.py --home work/ft20/kb --port 8094 --embed-url http://127.0.0.1:8095 \
        --luau-ssh U@HOST --luau-dir /opt/ft20-luau

- The index is a read-only snapshot of brain 1's kb.sqlite3 (+ private.sqlite3) in --home/data; the service code is
  the repository's server/knowledge/starkb (same search code as the brain).
- Query embeddings: a local llama-server with the same star-embed-ft1 GGUF (GPU vectors match the brain's, cosine
  >= 0.9996, docs/agents/embed-offload-20261020.md).
- Luau checks: starkb.luaucheck's two tool runs (luau-compile, luau-analyze, same binaries and version as brain 1)
  execute in an LXD container over ssh (`lxc exec starai`) under the same prlimit limits; Windows has no build of them.
- The key file holds the STAR Server key the eval client sends (read from ~/.star/server_api_key, never printed).
Windows only lacks SIGUSR1 (starkb registers a stack dump on it); that registration is skipped.
"""
from __future__ import annotations

import argparse
import faulthandler
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]


def requests_shim():
    """The part of `requests` that starkb.client uses (Session.post), on httpx (the app's venv has no requests)."""
    import types
    import httpx

    class Session:
        def __init__(self):
            self.headers: dict[str, str] = {}
            self.trust_env = False

        def post(self, url, json=None, timeout=None):
            return httpx.post(url, json=json, headers=self.headers, timeout=timeout, trust_env=False)

    return types.SimpleNamespace(Session=Session, RequestException=httpx.HTTPError)


def remote_runner(ssh: str, luau_dir: str):
    """A replacement for starkb.luaucheck._run that runs the tool in the container."""
    from starkb import luaucheck

    def run(argv: list[str], cwd: Path, *, timeout: float, memory_bytes: int):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in (luaucheck.FILE_NAME, ".luaurc"):
                if (cwd / name).is_file():
                    tar.add(cwd / name, arcname=name)
        tool = luau_dir.rstrip("/") + "/" + Path(argv[0]).name
        limits = (f"prlimit --cpu={int(timeout) + 1} --as={memory_bytes} --fsize={luaucheck.OUTPUT_BYTES} --core=0 "
                  f"--nofile=64 --")
        script = (f"d=$(mktemp -d) && cd $d && tar -x && LANG=C.UTF-8 timeout {int(timeout)} {limits} "
                  f"{shlex.join([tool, *argv[1:]])} 2>&1; rc=$?; cd / && rm -rf $d; exit $rc")
        try:
            proc = subprocess.run(["ssh", "-o", "BatchMode=yes", ssh, "lxc exec starai -- sh -c " + shlex.quote(script)],
                                  input=buf.getvalue(), capture_output=True, timeout=timeout + 20)
        except subprocess.TimeoutExpired:
            return None, "", True
        text = proc.stdout[:luaucheck.OUTPUT_BYTES].decode("utf-8", errors="replace")
        return (None, text, True) if proc.returncode == 124 else (proc.returncode, text, False)
    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--port", type=int, default=8094)
    ap.add_argument("--embed-url", required=True)
    ap.add_argument("--luau-ssh", required=True)
    ap.add_argument("--luau-dir", default="/opt/ft20-luau")
    args = ap.parse_args()
    key_file = args.home / "keys"
    key = (Path.home() / ".star" / "server_api_key").read_text(encoding="utf-8").strip()
    key_file.write_text(key + "\n", encoding="utf-8")
    os.environ.update(STAR_KB_HOME=str(args.home), STAR_BRAIN_URL=args.embed_url, STAR_BRAIN_KEY_FILE=str(key_file),
                      STAR_EMBED_MODEL="star-embed-ft1", STAR_KB_PRIVATE_DB=str(args.home / "data" / "private.sqlite3"),
                      STAR_LUAU_TOOLS=str(args.home / "tools"))
    sys.path.insert(0, str(ROOT / "server" / "knowledge"))
    try:
        import requests  # noqa: F401
    except ImportError:
        sys.modules["requests"] = requests_shim()
    if not hasattr(faulthandler, "register"):
        faulthandler.register = lambda *a, **k: None          # Windows: no SIGUSR1 stack dumps
    import signal
    if not hasattr(signal, "SIGUSR1"):
        signal.SIGUSR1 = signal.SIGTERM
    from starkb import luaucheck, serve
    luaucheck._run = remote_runner(args.luau_ssh, args.luau_dir)
    luaucheck.available = lambda *a, **k: True
    serve.serve(args.home / "data" / "kb.sqlite3", host="127.0.0.1", port=args.port, key_file=str(key_file))


if __name__ == "__main__":
    main()
