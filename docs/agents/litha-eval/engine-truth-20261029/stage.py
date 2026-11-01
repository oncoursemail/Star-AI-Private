"""Stage the three deploy trees from FRESH copies of the live trees (router-deploy-lock.md rule: merge the live trees first).

    python stage.py live_router_now live_verify_now      -> dt_router/, dt_verify/, dt_pg/ (LF line endings)
Router tree  = live + engine package + polyglot/note.py + the 3 router.py hunks.
Verifier tree = live + verify/core.py + verify/service.py + polyglot/client.py.
Container tree = the worktree's server/mesh/polyglot (runner.py, engine.py, data/, workers/UnityStubs.cs, client.py, note.py).
"""
import os
import shutil
import sys

WT = os.environ.get("REPO_MESH", "server/mesh")
CR = bytes([13, 10])
LF = bytes([10])


def lf_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    data = open(src, "rb").read().replace(CR, LF)
    open(dst, "wb").write(data)


def copy_tree(src_dir, dst_dir, skip=("__pycache__", "build", "deploy.sh")):
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f in skip or f.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(root, f), src_dir)
            lf_copy(os.path.join(root, f), os.path.join(dst_dir, rel))


def fresh(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    return path


live_router, live_verify = sys.argv[1], sys.argv[2]
# --- router
dt = fresh("dt_router")
shutil.copytree(live_router, dt)
copy_tree(os.path.join(WT, "engine"), os.path.join(dt, "mesh", "engine"))
lf_copy(os.path.join(WT, "polyglot", "note.py"), os.path.join(dt, "mesh", "polyglot", "note.py"))
p = os.path.join(dt, "mesh", "router.py")
s = open(p, "rb").read().decode("utf-8").replace(CR.decode(), LF.decode())
hunks = [
    ("from .general import inject as general\n", "from .engine import facts as engine_facts\nfrom .general import inject as general\n"),
    ("    **polyglot_note.DEFAULTS,",
     "    **engine_facts.DEFAULTS,         # Unity 6 version facts note (server/mesh/engine; the other engines keep the polyglot note)\n    **polyglot_note.DEFAULTS,"),
    ("            cache_hdr.update(polyglot_note.apply(req, self.cfg))",
     "            cache_hdr.update(engine_facts.apply(req, self.cfg))      # engine questions: one facts note (polyglot then skips)\n            cache_hdr.update(polyglot_note.apply(req, self.cfg))"),
]
for old, new in hunks:
    assert s.count(old) == 1, old
    s = s.replace(old, new, 1)
open(p, "wb").write(s.encode("utf-8"))
# --- verifier
dv = fresh("dt_verify")
shutil.copytree(live_verify, dv)
for rel in ("verify/core.py", "verify/service.py", "polyglot/client.py"):
    lf_copy(os.path.join(WT, rel), os.path.join(dv, "mesh", rel))
# --- container
dp = fresh("dt_pg")
copy_tree(os.path.join(WT, "polyglot"), os.path.join(dp, "polyglot"))
print("staged dt_router, dt_verify, dt_pg")
