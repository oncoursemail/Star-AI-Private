"""Render + judge for design answers: what `star.design_check` cannot read from the code alone.

1. `render(html, out_dir)`: headless Chromium (tools/design_render.mjs on playwright-core) at 1280 and 390 px wide ->
   screenshots and measurements (horizontal overflow, computed text contrast, fonts/weights/sizes actually used, text
   under 12 px, tap targets under 32 px). `merge(report, measured)` turns them into rubric findings on the static report.
2. `judge(images, ...)`: a vision pass by STAR's own multimodal model (star-fast) against the rubric's tells -> a 0-10
   "AI look" grade with the tells it saw. Calibrate it with `python -m star.design_render --calibrate <dir>` where the
   folder holds good/*.html and bad/*.html (reports agreement with the labels).

Nothing here is needed by the static checker or the night-school hook; this module is for the PC (Node + Chromium) and
for measured before/after reports. Server address and key come from the environment, never from this file.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .design_check import Report, check_html, check_answer, extract, html_document

ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = ROOT / "tools" / "design_render.mjs"
JUDGE_MAX_TOKENS = 400
JUDGE_PROMPT = """You are a strict design reviewer. Look at this screenshot of a user interface or web page and decide whether it looks like a generic AI-generated template or like a page a careful human designer made for a specific subject.

Tells of generic AI output: violet/indigo or pink gradients; glassmorphism (blurred translucent panels); emoji used as icons; three identical icon-topped feature cards; everything centred; tiny tracked uppercase labels or pill badges above headings; placeholder copy (lorem ipsum, "Feature 1"); low-contrast grey text; many drop shadows and glows; a default sans-serif at one weight; four or more accent colours; cream background with a terracotta accent; content that overflows or looks cramped at phone width.
Signs of an intentional design: a clear type hierarchy (one or two typefaces, distinct sizes and weights); a limited palette with roles (ground, ink, one accent); left-aligned text blocks with consistent spacing; real, specific copy about the subject; structure from space and tone rather than boxes and lines; nothing decorative that carries no information.

Answer with JSON only, no prose, exactly in this shape:
{"ai_look": <integer 0-10, 0 = clearly human-made and intentional, 10 = textbook generic AI template>, "verdict": "generic" or "intentional", "tells": ["short phrase", ...]}"""


def _node() -> str:
    for candidate in (os.environ.get("STAR_NODE"), "node",
                      str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")):
        if candidate and (shutil.which(candidate) or Path(candidate).is_file()):
            return candidate
    raise RuntimeError("Node.js not found (set STAR_NODE)")


def _playwright_core() -> str:
    env = os.environ.get("STAR_PLAYWRIGHT_CORE")
    if env:
        return env
    for base in (os.environ.get("APPDATA", ""), str(Path.home() / "AppData/Roaming")):
        p = Path(base) / "npm/node_modules/@playwright/cli/node_modules/playwright-core"
        if p.is_dir():
            return str(p)
        p = Path(base) / "npm/node_modules/playwright-core"
        if p.is_dir():
            return str(p)
    return ""   # let Node resolve it from the working directory


def render(html: str, out_dir: Path, *, timeout: float = 90.0) -> dict:
    """Write `html` to out_dir/page.html, render it, return the measurement JSON (with 'error' when it failed)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "page.html"
    page.write_text(html, encoding="utf-8")
    cmd = [_node(), str(RENDER_SCRIPT), str(page), str(out_dir)]
    core = _playwright_core()
    if core:
        cmd.append(core)
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"render failed: {type(exc).__name__}"}
    if run.returncode != 0 or not run.stdout.strip():
        return {"error": "render failed: " + (run.stderr or "no output").strip()[-300:]}
    try:
        return json.loads(run.stdout)
    except ValueError:
        return {"error": "render output was not JSON"}


def merge(report: Report, measured: dict) -> Report:
    """Add the browser's measurements to a static report (ids from the rubric; nothing is removed)."""
    if not measured or measured.get("error"):
        report.add("X0.render", "info", measured.get("error", "not rendered") if measured else "not rendered")
        return report
    phone, desk = measured.get("phone") or {}, measured.get("desktop") or {}
    report.metrics["rendered"] = {"phone": phone, "desktop": desk}
    if phone.get("overflowX"):
        report.add("A12.phone_overflow", "fail", f"content {phone['scrollWidth']}px wide in a 390px viewport")
    low = desk.get("lowContrastCount", 0)
    if low >= 2:
        report.add("A8.contrast_measured", "fail", f"{low} text runs under WCAG AA, e.g. " +
                   "; ".join(f"{p['text'][:20]!r} {p['ratio']}:1" for p in desk.get("lowContrast", [])[:2]))
    elif low == 1:
        report.add("A8.contrast_measured", "warn", f"one text run under WCAG AA ({desk['lowContrast'][0]['ratio']}:1)")
    if desk.get("tinyText"):
        report.add("A6.tiny_text", "fail", f"{desk['tinyText']} text runs under 12px")
    if phone.get("smallTargets", 0) >= 3:
        report.add("A12.tap_targets", "warn", f"{phone['smallTargets']} tap targets under 32px on the phone")
    if phone.get("h1Lines", 0) > 4:
        report.add("A11.long_headline", "warn", f"h1 wraps to {phone['h1Lines']} lines on the phone")
    fonts = desk.get("fontsUsed") or []
    if len(fonts) > 2:
        report.add("A6.font_families_measured", "fail", f"{len(fonts)} typefaces rendered: {', '.join(fonts[:4])}")
    report.metrics["fonts_rendered"] = fonts
    return report


def full_report(answer: str, out_dir: Path) -> Report:
    """Static checks + render measurements for an HTML answer (fenced blocks or a raw document)."""
    parts = extract(answer)
    if not (parts["html"] or parts["css"]):
        return check_answer(answer, "auto")
    doc = html_document(parts)
    rep = check_html(doc)
    return merge(rep, render(doc, out_dir))


# --- vision judge ------------------------------------------------------------------------------------------------


def _client():
    from openai import OpenAI
    base = os.environ.get("STAR_DESIGN_BRAIN_URL") or os.environ.get("STAR_BRAIN_URL") or "http://127.0.0.1:8080/v1"
    if not base.rstrip("/").endswith("/v1"):
        base = base.rstrip("/") + "/v1"
    key = os.environ.get("STAR_SERVER_API_KEY", "")
    if not key:
        key_file = Path(os.environ.get("STAR_KEY_FILE", str(Path.home() / ".star" / "server_api_key")))
        key = key_file.read_text(encoding="utf-8").strip() if key_file.is_file() else "none"
    return OpenAI(base_url=base, api_key=key, timeout=float(os.environ.get("STAR_DESIGN_JUDGE_TIMEOUT", "300")))


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def judge(images: list[Path], *, model: str | None = None, client=None, prompt: str = JUDGE_PROMPT) -> dict:
    """One vision call: {"ai_look": int, "verdict": str, "tells": [...], "raw": str}. Never raises on a bad answer."""
    client = client or _client()
    model = model or os.environ.get("STAR_DESIGN_JUDGE_MODEL", "star-fast")
    content = [{"type": "text", "text": prompt}]
    for image in images[:2]:
        content.append({"type": "image_url", "image_url": {"url": _data_url(image)}})
    try:
        answer = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}],
                                                max_tokens=JUDGE_MAX_TOKENS, temperature=0)
        raw = (answer.choices[0].message.content or "").strip()
    except Exception as exc:   # noqa: BLE001 - the judge is advisory; the caller sees the error text
        return {"ai_look": None, "verdict": "error", "tells": [], "raw": f"{type(exc).__name__}: {exc}"[:300]}
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    grade = data.get("ai_look")
    try:
        grade = int(round(float(grade))) if grade is not None else None
    except (TypeError, ValueError):
        grade = None
    verdict = str(data.get("verdict", "")).lower()
    if verdict not in ("generic", "intentional") and grade is not None:
        verdict = "generic" if grade >= 5 else "intentional"
    return {"ai_look": grade, "verdict": verdict or "unknown", "tells": [str(t) for t in data.get("tells", [])][:8], "raw": raw[:600]}


def calibrate(folder: Path, out_dir: Path, *, log=print) -> dict:
    """good/*.html must grade intentional, bad/*.html generic. Returns agreement counts (judge and static checker)."""
    folder, out_dir = Path(folder), Path(out_dir)
    rows = []
    for label, expect in (("good", "intentional"), ("bad", "generic")):
        for page in sorted((folder / label).glob("*.html")):
            html = page.read_text(encoding="utf-8")
            target = out_dir / label / page.stem
            rep = merge(check_html(html), render(html, target))
            shots = [target / "desktop.png", target / "phone.png"]
            verdict = judge([s for s in shots if s.is_file()])
            rows.append({"page": f"{label}/{page.name}", "expect": expect, "static_score": rep.score,
                         "static_pass": rep.passed(), "judge": verdict})
            log(f"{label}/{page.name}: static {rep.score} ({'pass' if rep.passed() else 'fail'}), "
                f"judge {verdict['ai_look']} {verdict['verdict']} {verdict['tells'][:3]}")
    judged = [r for r in rows if r["judge"]["verdict"] in ("generic", "intentional")]
    agree_judge = sum(1 for r in judged if r["judge"]["verdict"] == r["expect"])
    agree_static = sum(1 for r in rows if r["static_pass"] == (r["expect"] == "intentional"))
    summary = {"pages": len(rows), "judge_answered": len(judged), "judge_agree": agree_judge,
               "static_agree": agree_static, "rows": rows}
    (out_dir / "calibration.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Render an HTML answer, measure it, optionally ask STAR's vision model.")
    ap.add_argument("file", nargs="?", help="an .html file or a .md answer with fenced html")
    ap.add_argument("--out", default="", help="output folder for page.html and screenshots")
    ap.add_argument("--judge", action="store_true", help="also run the vision judge (needs the brain)")
    ap.add_argument("--calibrate", default="", help="folder with good/ and bad/ html pages")
    args = ap.parse_args(argv)
    if args.calibrate:
        out = Path(args.out or tempfile.mkdtemp(prefix="design-cal-"))
        summary = calibrate(Path(args.calibrate), out)
        print(f"judge agreement {summary['judge_agree']}/{summary['judge_answered']} answered of {summary['pages']} pages; "
              f"static checker agreement {summary['static_agree']}/{summary['pages']}; details {out / 'calibration.json'}")
        return 0
    if not args.file:
        ap.error("give a file or --calibrate")
    text = Path(args.file).read_text(encoding="utf-8")
    if not args.file.endswith(".md"):
        text = f"```html\n{text}\n```"
    out = Path(args.out or tempfile.mkdtemp(prefix="design-render-"))
    rep = full_report(text, out)
    print(rep.summary())
    for f in rep.findings:
        print(f"  {f.level:4} {f.id}: {f.detail}")
    print(f"screenshots in {out}")
    if args.judge:
        shots = [out / "desktop.png", out / "phone.png"]
        verdict = judge([s for s in shots if s.is_file()])
        print(f"judge: ai_look {verdict['ai_look']} -> {verdict['verdict']}; tells: {', '.join(verdict['tells'])}")
    return 0 if rep.passed() else 1


if __name__ == "__main__":
    raise SystemExit(main())
