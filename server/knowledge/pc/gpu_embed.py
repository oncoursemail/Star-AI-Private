"""Embed brain 1's pending knowledge chunks on this PC's graphics card, only while the owner is away.

    python gpu_embed.py [--home DIR] model      copy the brain's embedding GGUF here (checked by SHA-256)
    python gpu_embed.py [--home DIR] pull       the texts still to embed -> DIR/pending.jsonl (takes the brain's claim "pc"
                                                for 12 h; refused while the laptop's offload-run holds it)
    python gpu_embed.py [--home DIR] verify     embed 200 texts the brain already embedded; cosine to the brain's
    python gpu_embed.py [--home DIR] run        embed DIR/pending.jsonl -> DIR/vectors.bin while the PC is idle
    python gpu_embed.py [--home DIR] push       load DIR/vectors.bin into the brain's index (never replaces vectors),
                                                then gives the claim back

Same model file as the brain (star-embed-ft1), the server's own pooling and L2 normalisation, and the same 512-token
physical batch, so an over-long input is shortened exactly as on the brain (starkb.embed.embed_batch). `run` uses the
GPU night turbo's idle rules (server/night_school/pc/turbo.py: owner idle 20 min, 5 min at night; stops within
seconds of any input; no full-screen program, no other llama-server, no other program busy on the card) and also
never runs next to Roblox Studio or the Roblox player. Resumable at any point: rerun `run`, then `push`.
OFF switch: create DIR/OFF. The SSH target comes from the turbo's config.json (never in the repository).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                        # server/knowledge -> starkb
sys.path.insert(0, str(HERE.parents[2] / "night_school" / "pc"))  # turbo.py (idle rules)

from starkb import offload   # noqa: E402
import turbo                 # noqa: E402

MODEL_ALIAS = "star-embed-ft1"
REMOTE_MODEL = "/opt/star/models/embeddinggemma-300m-star-ft1/embeddinggemma-300m-star-ft1-Q8_0.gguf"
REMOTE_APP = "/opt/star/knowledge/app"
REMOTE_PY = "/opt/star/knowledge/venv/bin/python"
ALWAYS_BLOCK = {"robloxstudiobeta.exe", "robloxplayerbeta.exe"}
PORT = 8097
LOOK_S = 60.0                    # programs + GPU counters take ~3 s; input is checked before every batch


def default_home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "STAR-embed-offload"


class Server:
    """Minimal client with the starkb.client.Brain embed() contract (no `requests` on this PC)."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        body = json.dumps({"model": MODEL_ALIAS, "input": texts}).encode()
        request = urllib.request.Request(self.url + "/v1/embeddings", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"/v1/embeddings returned HTTP {exc.code}: {exc.read()[:200]!r}") from None
        rows = sorted(data["data"], key=lambda r: r["index"])
        return [r["embedding"] for r in rows], int((data.get("usage") or {}).get("prompt_tokens") or 0)


def remote(config: dict, command: str) -> list[str]:
    """ssh argv running `command` as user star inside the brain's container, in the knowledge app folder."""
    inner = f"cd {REMOTE_APP} && STAR_EMBED_MODEL={MODEL_ALIAS} {command}"
    return ["ssh", "-o", "BatchMode=yes", config["server_ssh"],
            f"lxc exec {config.get('container') or 'starai'} -- runuser -u star -- sh -c '{inner}'"]


def server_argv(config: dict, model: Path, port: int) -> list[str]:
    # -ub 512 = the brain's physical batch (inputs over 512 tokens are refused there too); -c 8192 / -np 4 = 2048 per slot
    return [config["llama_server"], "-m", str(model), "--embeddings", "--alias", MODEL_ALIAS, "-ngl", "99",
            "-fa", "on", "-c", "8192", "-np", "4", "-b", "2048", "-ub", "512", "--host", "127.0.0.1",
            "--port", str(port)]


class Gate:
    """The turbo's start/stop rules for this job (probe = turbo.Probe)."""

    def __init__(self, home: Path, config: dict, probe=None, clock=time.monotonic,
                 hour=lambda: time.localtime().tm_hour):
        self.home, self.config, self.probe, self.clock, self.hour = home, config, probe or turbo.Probe(), clock, hour
        self.own: set[int] = set()
        self.looked, self.hot = -1e18, 0

    def _programs(self) -> str:
        if self.probe.fullscreen():
            return "a full-screen program or game is in front"
        names = self.probe.processes()
        blocked = ALWAYS_BLOCK | {n.lower() for n in self.config.get("block_processes", [])}
        for pid, name in names.items():
            if pid in self.own:
                continue
            if name.lower() == "llama-server.exe":
                return "another llama-server is running (GPU switch or night turbo)"
            if name.lower() in blocked:
                return f"{name} is running"
        busy = [(p, pct) for p, pct in self.probe.gpu_users().items() if p not in self.own
                and names.get(p, "").lower() not in turbo.SYSTEM_GPU and pct >= float(self.config["other_gpu_percent"])]
        self.hot = self.hot + 1 if busy else 0
        if self.hot >= 2:
            return "another program is using the graphics card"
        return ""

    def start_blocker(self) -> str:
        if (self.home / "OFF").exists():
            return "off (the OFF file exists)"
        night = turbo.night_now(self.config, self.hour())
        need = 60 * float(self.config["night_idle_minutes" if night else "day_idle_minutes"])
        if self.probe.idle_seconds() < need:
            return "the owner is active"
        self.looked = self.clock()
        found = self._programs()
        if not found and self.hot:                 # one busy look: look again before starting
            found = self._programs()
        return found

    def stop_reason(self) -> str:
        if (self.home / "OFF").exists():
            return "off switch"
        if self.probe.idle_seconds() < float(self.config["back_seconds"]):
            return "the owner is back"
        if self.clock() - self.looked >= LOOK_S:
            self.looked = self.clock()
            return self._programs()
        return ""


def log(home: Path, text: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + text
    print(line, flush=True)
    with open(home / "gpu-embed.log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def start_server(config: dict, model: Path, home: Path, port: int = PORT):
    out = open(home / "server.log", "ab")
    process = subprocess.Popen(server_argv(config, model, port), stdout=out, stderr=subprocess.STDOUT,
                               creationflags=turbo.NO_WINDOW)
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited with code {process.returncode} (see {home / 'server.log'})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    return process
        except OSError:
            pass
        time.sleep(1)
    turbo.kill_tree(process)
    raise RuntimeError("llama-server did not become ready in 120 s")


def run(home: Path, config: dict, model: Path, *, gate: Gate | None = None, batch: int = 32,
        poll: float = 30.0) -> dict:
    gate = gate or Gate(home, config)
    pending, vectors = home / "pending.jsonl", home / "vectors.bin"
    while True:
        why = gate.start_blocker()
        if why:
            time.sleep(poll)
            continue
        log(home, "start: the PC is idle")
        process = start_server(config, model, home)
        gate.own = {process.pid}
        reason = {"text": ""}
        started = time.monotonic()

        def keep_going() -> bool:
            reason["text"] = gate.stop_reason()
            return not reason["text"]
        try:
            result = offload.embed_file(Server(f"http://127.0.0.1:{PORT}"), pending, vectors, batch=batch,
                                        gate=keep_going, log=lambda m: log(home, m))
        finally:
            turbo.kill_tree(process)
            gate.own = set()
        seconds = time.monotonic() - started
        log(home, f"stop: {reason['text'] or 'done'}; {result['embedded_now']} texts in {seconds:.0f}s "
                  f"({result['embedded_now'] / seconds:.1f}/s incl. model load), {result['left']} left")
        if not result["left"]:
            return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gpu_embed")
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--turbo-home", type=Path, default=Path.home() / ".star" / "night-turbo",
                        help="the GPU night turbo's home (config.json: server_ssh, container, llama_server)")
    parser.add_argument("cmd", choices=["model", "pull", "verify", "run", "push"])
    args = parser.parse_args(argv)
    home = args.home
    home.mkdir(parents=True, exist_ok=True)
    config = turbo.load_config(args.turbo_home)
    model = home / Path(REMOTE_MODEL).name
    if args.cmd == "model":
        with open(model, "wb") as out:
            subprocess.run(["ssh", "-o", "BatchMode=yes", config["server_ssh"],
                            f"lxc exec {config.get('container') or 'starai'} -- cat {REMOTE_MODEL}"],
                           stdout=out, check=True)
        want = subprocess.run(remote(config, f"sha256sum {REMOTE_MODEL}"), capture_output=True, text=True,
                              check=True).stdout.split()[0]
        got = sha256(model)
        print(json.dumps({"model": str(model), "sha256": got, "same_as_brain": got == want}))
        return 0 if got == want else 1
    if args.cmd == "pull":
        taken = subprocess.run(remote(config, f"{REMOTE_PY} -m starkb offload-claim --owner pc"),
                               capture_output=True, text=True)
        if taken.returncode:
            print("not pulling, another machine is embedding the pending texts:", taken.stdout.strip())
            return 75
        with open(home / "pending.jsonl", "wb") as out:
            subprocess.run(remote(config, f"{REMOTE_PY} -m starkb offload-export"), stdout=out, check=True)
        count = sum(1 for _ in open(home / "pending.jsonl", encoding="utf-8"))
        print(count, "texts in", home / "pending.jsonl")
        if not count:
            subprocess.run(remote(config, f"{REMOTE_PY} -m starkb offload-release --owner pc"), capture_output=True)
        return 0
    if args.cmd == "verify":
        sample = home / "sample.jsonl"
        with open(sample, "wb") as out:
            subprocess.run(remote(config, f"{REMOTE_PY} -m starkb offload-sample --n 200"), stdout=out, check=True)
        process = start_server(config, model, home)
        try:
            result = offload.compare_sample(Server(f"http://127.0.0.1:{PORT}"), sample)
        finally:
            turbo.kill_tree(process)
        log(home, f"verify: {json.dumps(result)}")
        return 0 if result["n"] and result["below_0.999"] == 0 else 1
    if args.cmd == "run":
        run(home, config, model)
        return 0
    with open(home / "vectors.bin", "rb") as source:
        code = subprocess.run(remote(config, f"{REMOTE_PY} -m starkb offload-import"), stdin=source).returncode
    if not code:
        subprocess.run(remote(config, f"{REMOTE_PY} -m starkb offload-release --owner pc"), capture_output=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
