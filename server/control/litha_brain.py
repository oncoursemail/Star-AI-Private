#!/usr/bin/env python3
"""Litha on brain 1: on / off / status (run by the Metallic Control host gate as `act litha-brain:on|off`).

off: the mesh router stops sending litha / litha-deep to the brain's litha-26b (GPU nodes first, then star-fast /
star-deep), litha-26b unloads (~18 GB RAM back) and stays unloaded after a brain restart.
on:  the reverse; the cold load takes about a minute, the router uses it again after its restart.
Prints one JSON object {"ok", "text"}; the brain key is read inside the container and never printed.
"""
from __future__ import annotations

import json
import subprocess
import sys

LXC = "/usr/sbin/lxc"
BRAIN, MESH = "starai", "star-mesh"
MODEL = "litha-26b"
MESH_JSON = "/etc/star-mesh/mesh.json"
MODELS_INI = "/opt/star/config/models.ini"

# Runs inside the containers with python3 (argv: mode). Each prints one short line.
MESH_CODE = r"""
import json, sys
p = "%s"
cfg = json.load(open(p))
if sys.argv[1] != "status":
    cfg["brain_litha_model"] = "%s" if sys.argv[1] == "on" else ""
    open(p, "w").write(json.dumps(cfg, indent=1) + "\n")
print(cfg.get("brain_litha_model", "%s") or "off")
""" % (MESH_JSON, MODEL, MODEL)

BRAIN_CODE = r"""
import json, re, sys, time, urllib.request
mode, ini, model = sys.argv[1], "%s", "%s"
key = open("/opt/star/secrets/api_keys").read().split()[0]
def call(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:8080" + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))
if mode != "status":
    text = open(ini).read()
    want = "true" if mode == "on" else "false"
    new = re.sub(r"(\[" + re.escape(model) + r"\][^\[]*?load-on-startup = )(true|false)", r"\g<1>" + want, text)
    if new != text:
        open(ini, "w").write(new)
def state():
    found = [m.get("status", {}).get("value") for m in call("/models")["data"] if m["id"] == model]
    return found[0] if found else "missing"
if mode != "status" and (state() == "unloaded") == (mode == "on"):   # pressing it twice is harmless
    call("/models/load" if mode == "on" else "/models/unload", {"model": model})
now = state()
for _ in range(30 if mode == "off" else 0):   # the unload is asynchronous; report it once it has happened
    if now == "unloaded":
        break
    time.sleep(1)
    now = state()
print(now)
""" % (MODELS_INI, MODEL)


def _run(container: str, args: list[str], timeout: float = 130) -> subprocess.CompletedProcess:
    return subprocess.run([LXC, "exec", container, "--", *args], capture_output=True, text=True, timeout=timeout)


def main(mode: str) -> int:
    if mode not in ("on", "off", "status"):
        print(json.dumps({"ok": False, "text": "usage: litha_brain.py on|off|status"}))
        return 2
    steps = []
    if mode == "on":                          # load first, so the router never points at an unloaded model for long
        steps = [(BRAIN, ["python3", "-c", BRAIN_CODE, mode]), (MESH, ["python3", "-c", MESH_CODE, mode])]
    else:                                     # router off first, so no request reloads the model after the unload
        steps = [(MESH, ["python3", "-c", MESH_CODE, mode]), (BRAIN, ["python3", "-c", BRAIN_CODE, mode])]
    out = {}
    for container, args in steps:
        result = _run(container, args)
        if result.returncode != 0:
            err = (result.stderr.strip().splitlines() or ["no output"])[-1][:200]
            print(json.dumps({"ok": False, "text": f"{container}: {err}"}))
            return 1
        out[container] = result.stdout.strip()
        if container == MESH and mode != "status":
            restart = _run(MESH, ["systemctl", "restart", "star-mesh"], timeout=60)
            if restart.returncode != 0:
                print(json.dumps({"ok": False, "text": "star-mesh restart failed"}))
                return 1
    text = f"litha-26b on brain 1: {out.get(BRAIN, '?')}; router brain fallback: {out.get(MESH, '?')}"
    print(json.dumps({"ok": True, "text": text}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
