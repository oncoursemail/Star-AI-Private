"""Wire a PROMOTED nightly adapter into the owner-PC mesh node (only called after the promotion gate passed).

The node's llama-server gets `--lora-scaled <adapter.gguf> 1.0`: every answer uses the adapter by default and any
request can still send `"lora": [{"id": 0, "scale": 0}]` to get the base model (per-request A/B). Every ladder step's
memory need grows by the adapter's size so the guard keeps its measured headroom. The node is restarted and must
report the model loaded within --wait minutes; otherwise the backup node.json is put back and the node restarted
again (a node is never left unloaded by this step). Rollback by hand: `python -m training.nightly.deploy rollback`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

NODE_DIR = Path(os.path.expanduser("~/models/litha-node"))
STATUS = "http://127.0.0.1:8099/status"
TASK = "Litha mesh node"
LORA_FLAGS = ("--lora", "--lora-scaled")


def strip_lora(args: list) -> list:
    out, skip = [], 0
    for a in args:
        if skip:
            skip -= 1
            continue
        if str(a) == "--lora":
            skip = 1
            continue
        if str(a) == "--lora-scaled":
            skip = 2
            continue
        if str(a) == "--lora-init-without-apply":
            continue
        out.append(a)
    return out


def with_adapter(cfg: dict, adapter: str, scale: float = 1.0, mb: int | None = None) -> dict:
    """node.json with the adapter (replacing an earlier one) and the ladder's memory needs raised by its size."""
    new = json.loads(json.dumps(cfg))
    added_before = int(new.pop("nightly_lora_mb", 0) or 0)
    if mb is None:
        mb = math.ceil(Path(adapter).stat().st_size / 2**20) + 16
    new["llama_args"] = strip_lora(new.get("llama_args", [])) + ["--lora-scaled", str(adapter), str(scale)]
    for step in new.get("ngl_ladder") or []:
        step[1] = int(step[1]) - added_before + mb
    new["nightly_lora_mb"] = mb
    new["nightly_lora"] = str(adapter)
    return new


def without_adapter(cfg: dict) -> dict:
    new = json.loads(json.dumps(cfg))
    added = int(new.pop("nightly_lora_mb", 0) or 0)
    new.pop("nightly_lora", None)
    new["llama_args"] = strip_lora(new.get("llama_args", []))
    for step in new.get("ngl_ladder") or []:
        step[1] = int(step[1]) - added
    return new


def node_state(url: str = STATUS) -> tuple[str, bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            st = json.load(r)
    except Exception as e:  # noqa: BLE001
        return "unreachable", False, repr(e)[:120]
    m = (st.get("models") or [{}])[0]
    return st.get("state", ""), bool(m.get("loaded")), st.get("reason", "")


def restart(node_dir: Path = NODE_DIR) -> None:
    pid = (node_dir / "logs" / "node.pid")
    if pid.exists():
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid.read_text().strip()], capture_output=True)
    time.sleep(3)
    subprocess.run(["schtasks", "/run", "/tn", TASK], capture_output=True)


def wait_loaded(minutes: float, url: str = STATUS) -> tuple[bool, str]:
    end = time.time() + minutes * 60
    why = ""
    while time.time() < end:
        state, loaded, why = node_state(url)
        if loaded and state == "idle":
            return True, why
        if state == "away" and why.startswith("failed"):
            return False, why
        time.sleep(10)
    return False, f"not loaded after {minutes} min ({why})"


def deploy(adapter: str, node_dir: Path = NODE_DIR, wait: float = 8, scale: float = 1.0, say=print) -> dict:
    cfg_p = node_dir / "node.json"
    backup = node_dir / f"node.json.bak-nightly-{time.strftime('%Y%m%d-%H%M')}"
    shutil.copy2(cfg_p, backup)
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    cfg_p.write_text(json.dumps(with_adapter(cfg, adapter, scale), indent=1), encoding="utf-8")
    say(f"deploy: node.json -> --lora-scaled {adapter} {scale} (backup {backup.name}); restarting the node")
    restart(node_dir)
    ok, why = wait_loaded(wait)
    if ok:
        return {"deployed": True, "adapter": adapter, "backup": str(backup), "node": why}
    say(f"deploy: node did not load with the adapter ({why}); rolling back")
    shutil.copy2(backup, cfg_p)
    restart(node_dir)
    ok2, why2 = wait_loaded(wait)
    return {"deployed": False, "reason": why, "rolled_back": True, "node_after_rollback": why2, "loaded": ok2}


def rollback(node_dir: Path = NODE_DIR, wait: float = 8, say=print) -> dict:
    cfg_p = node_dir / "node.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    if "nightly_lora" not in cfg:
        return {"rolled_back": False, "reason": "no nightly adapter in node.json"}
    shutil.copy2(cfg_p, node_dir / f"node.json.bak-nightly-rollback-{time.strftime('%Y%m%d-%H%M')}")
    cfg_p.write_text(json.dumps(without_adapter(cfg), indent=1), encoding="utf-8")
    restart(node_dir)
    ok, why = wait_loaded(wait)
    say(f"rollback: node loaded={ok} ({why})")
    return {"rolled_back": True, "loaded": ok, "node": why}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["deploy", "rollback"])
    ap.add_argument("--adapter", default="")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--node-dir", default=str(NODE_DIR))
    a = ap.parse_args(argv)
    if a.action == "deploy":
        print(json.dumps(deploy(a.adapter, Path(a.node_dir), scale=a.scale)))
    else:
        print(json.dumps(rollback(Path(a.node_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
