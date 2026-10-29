"""Run build_bpy.py in headless Blender: locally or on a remote Windows host over ssh (STAR's PC by default).

Remote layout: <root>\\build_bpy.py, <root>\\jobs\\<job_id>\\job.json -> out\\ (copied back with scp).
The host alias and paths come from the environment, never from a model.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build_bpy.py"
LOCAL_BLENDER = os.environ.get("STAR_BLENDER_EXE", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
REMOTE_HOST = os.environ.get("STAR_ASSET3D_HOST", "star-pc")
REMOTE_ROOT = os.environ.get("STAR_ASSET3D_ROOT", r"D:\StarBlender")
REMOTE_BLENDER = REMOTE_ROOT + r"\Blender 5.2\blender.exe"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
_pushed = False


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def push_builder():
    global _pushed
    r = _run(["scp", "-q", "-o", "BatchMode=yes", str(BUILD), f"{REMOTE_HOST}:{REMOTE_ROOT}/build_bpy.py".replace("\\", "/")],
             120)
    if r.returncode:
        raise RuntimeError("scp builder failed: " + r.stderr[-300:])
    _pushed = True


def build(job: dict, outdir: Path, where: str = "remote", timeout: int = 1800) -> dict:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    if where == "local":
        cmd = [LOCAL_BLENDER, "-b", "--factory-startup", "-noaudio", "--python", str(BUILD), "--",
               str(outdir / "job.json"), str(outdir)]
        r = _run(cmd, timeout)
        (outdir / "blender.log").write_text(r.stdout[-20000:] + r.stderr[-5000:], encoding="utf-8")
    else:
        if not _pushed:
            push_builder()
        jid = uuid.uuid4().hex[:12]
        rdir = f"{REMOTE_ROOT}\\jobs\\{jid}"
        r = _run(SSH + [REMOTE_HOST, f'mkdir "{rdir}"'], 60)
        if r.returncode:
            raise RuntimeError("remote mkdir failed: " + r.stderr[-300:])
        r = _run(["scp", "-q", "-o", "BatchMode=yes", str(outdir / "job.json"),
                  f"{REMOTE_HOST}:{rdir}/job.json".replace("\\", "/")], 120)
        if r.returncode:
            raise RuntimeError("scp job failed: " + r.stderr[-300:])
        run = (f'cd /d "{rdir}" && start "" /low /wait /b "{REMOTE_BLENDER}" -b --factory-startup -noaudio '
               f'--python "{REMOTE_ROOT}\\build_bpy.py" -- job.json out > blender.log 2>&1')
        r = _run(SSH + [REMOTE_HOST, run], timeout)
        tmp = outdir / "_pull"
        if tmp.exists():
            shutil.rmtree(tmp)
        r2 = _run(["scp", "-q", "-r", "-o", "BatchMode=yes", f"{REMOTE_HOST}:{rdir}/out".replace("\\", "/"),
                   str(tmp)], 600)
        _run(["scp", "-q", "-o", "BatchMode=yes", f"{REMOTE_HOST}:{rdir}/blender.log".replace("\\", "/"),
              str(outdir / "blender.log")], 120)
        if r2.returncode:
            raise RuntimeError("scp results failed: " + r2.stderr[-300:])
        for item in tmp.iterdir():
            dest = outdir / item.name
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            shutil.move(str(item), str(dest))
        tmp.rmdir()
        _run(SSH + [REMOTE_HOST, f'rmdir /s /q "{rdir}"'], 60)
    mpath = outdir / "metrics.json"
    if not mpath.exists():
        return {"ok": False, "error": "no metrics.json (Blender crashed?)"}
    m = json.loads(mpath.read_text(encoding="utf-8"))
    # paths inside metrics point at the remote host: rewrite to local files
    if m.get("views"):
        m["views"] = {k: str(outdir / "views" / f"{k}.png") for k in m["views"]}
    return m


def contact_sheet(views: dict, path: Path, order=("front34", "side", "back34", "top34"), tile: int = 384,
                  quality: int = 88) -> Path:
    from PIL import Image
    ims = [Image.open(views[v]).convert("RGB").resize((tile, tile)) for v in order if v in views]
    cols = 2
    rows = (len(ims) + 1) // 2
    sheet = Image.new("RGB", (tile * cols, tile * rows), (20, 20, 22))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * tile, (i // cols) * tile))
    path = Path(path)
    sheet.save(path, quality=quality)
    return path
