"""Open .bbmodel files in a real, headless Blockbench and check they load and export.

Runs where Blockbench (desktop build) is already started under Xvfb with remote debugging, e.g. in a
throwaway Linux container:
  xvfb-run -a ./squashfs-root/blockbench --no-sandbox --remote-debugging-port=9222 --use-angle=swiftshader &
  python3 tools/blockbench_validate.py --out results/ model1.bbmodel model2.bbmodel

For each file: load via Blockbench's own loader, count elements/groups/textures/animations, collect
console errors, compile with Blockbench's Java or Bedrock codec (written next to the summary for
comparison with STAR's own export) and save a viewport screenshot. Needs `websocket-client`.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import urllib.request

LOAD_JS = r"""
(async () => {
  const content = %s, name = %s;
  for (const p of ModelProject.all.slice()) { try { await p.close(true); } catch (e) {} }
  const errors = [];
  const origErr = console.error;
  console.error = (...a) => { errors.push(a.map(String).join(' ').slice(0, 300)); origErr(...a); };
  try { loadModelFile({content: content, path: '/tmp/' + name, name: name}); }
  catch (e) { console.error = origErr; return {ok: false, error: 'load: ' + e}; }
  for (let i = 0; i < 50; i++) {
    if (Texture.all.every(t => t.img && t.img.complete && t.img.naturalWidth > 0)) break;
    await new Promise(r => setTimeout(r, 100));
  }
  const res = {ok: true, format: Format.id, elements: Outliner.elements.length, groups: Group.all.length,
    textures: Texture.all.map(t => [t.name, t.img ? t.img.naturalWidth : 0, t.img ? t.img.naturalHeight : 0]),
    animations: (Animation.all || []).map(a => [a.name, a.length, Object.keys(a.animators).length])};
  try {
    if (Format.id === 'java_block') res.java = Codecs.java_block.compile();
    if (Format.id === 'bedrock') { res.bedrock = Codecs.bedrock.compile(); res.anim = JSON.stringify(Animator.buildFile()); }
    res.resave_bytes = Codecs.project.compile().length;
  } catch (e) { res.ok = false; res.error = 'export: ' + e; }
  try {
    const pv = Preview.selected;
    pv.camera.position.set(%s); pv.controls.target.set(%s); pv.camera.lookAt(pv.controls.target);
    pv.render();
    res.shot = pv.canvas.toDataURL('image/png');
  } catch (e) { res.shot_error = String(e); }
  res.console_errors = errors;
  console.error = origErr;
  if (res.textures.some(t => !t[1])) res.ok = false;
  return res;
})()
"""


def evaluate(expr: str, port: int = 9222, timeout: float = 180):
    import websocket
    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    page = next(p for p in pages if p["type"] == "page")
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1:
                r = m.get("result", {})
                if "exceptionDetails" in r:
                    return {"ok": False, "error": str(r["exceptionDetails"])[:1000]}
                return r.get("result", {}).get("value") or {"ok": False, "error": "no result"}
    finally:
        ws.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--camera", default="-30, 30, -40")
    ap.add_argument("--target", default="0, 8, 0")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for f in a.files:
        p = pathlib.Path(f)
        r = evaluate(LOAD_JS % (json.dumps(p.read_text(encoding="utf-8")), json.dumps(p.name), a.camera, a.target),
                     a.port)
        shot = r.pop("shot", None)
        if shot:
            (out / f"{p.stem}_blockbench.png").write_bytes(base64.b64decode(shot.split(",", 1)[1]))
        for k in ("java", "bedrock", "anim"):
            if r.get(k):
                (out / f"{p.stem}_blockbench_{k}.json").write_text(r.pop(k), encoding="utf-8")
        summary[str(p)] = r
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    bad = [k for k, v in summary.items() if not v.get("ok") or v.get("console_errors")]
    print(json.dumps({"files": len(summary), "failed": bad}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
