"""Brief -> plan -> build -> check -> render -> vision critique -> revise, through STAR's model router.

CLI (writes everything under --out/<name>/):
  python -m star.blockbench.pipeline "a copper lantern with a glowing flame" --category block --rounds 2
  python -m star.blockbench.pipeline --spec my_model.spec.json          # build + check + render only

The router is OpenAI-compatible (STAR mesh :8100 or a brain :8080). Base URL and key come from
--base-url / --key-file or STAR_MESH_URL / STAR_API_KEY_FILE (default ~/.star/mesh_url, ~/.star/server_api_key).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import time
from pathlib import Path

from . import build as B
from . import checks as C
from . import prompts as P
from . import render as R
from . import spec as S


class LLM:
    def __init__(self, base_url: str, key: str, model: str, *, timeout: float = 900.0, retries: int = 0):
        self.retries = retries
        self.base = base_url.rstrip("/")
        if not self.base.endswith("/v1"):
            self.base += "/v1"
        self.key, self.model, self.timeout = key, model, timeout

    def chat(self, messages, *, max_tokens=4096, temperature=0.4, json_mode=True, seed=7):
        import httpx
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "seed": seed,
                "chat_template_kwargs": {"enable_thinking": False}}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t = time.time()
        for attempt in range(self.retries + 1):
            try:
                r = httpx.post(self.base + "/chat/completions", json=body, timeout=self.timeout,
                               headers={"Authorization": f"Bearer {self.key}"})
                r.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError):
                # a busy router can hand a request to a slow CPU fallback; a retry is ranked again
                if attempt == self.retries:
                    raise
                time.sleep(5)
        data = r.json()
        text = data["choices"][0]["message"].get("content") or ""
        return text, time.time() - t, data.get("usage", {})


def default_llm(model: str, base_url: str | None = None, key_file: str | None = None, *,
                timeout: float = 900.0, retries: int = 0) -> LLM:
    home = Path.home() / ".star"
    if not base_url:
        base_url = os.environ.get("STAR_MESH_URL") or (home / "mesh_url").read_text(encoding="utf-8").strip()
    kf = Path(key_file or os.environ.get("STAR_API_KEY_FILE") or home / "server_api_key")
    key = kf.read_text(encoding="utf-8").strip().splitlines()[0]
    return LLM(base_url, key, model, timeout=timeout, retries=retries)


def extract_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, end, in_str, esc = 0, -1, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    chunk = t[start:end + 1] if end > 0 else t[start:]
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", chunk))


def evaluate(spec_raw: dict, *, out_dir: Path | None = None, size: int = 384) -> dict:
    """normalize + build + checks + previews. Returns a record (no network)."""
    spec, fixes = S.normalize(spec_raw)
    built = B.build(spec)
    report = C.check(built["bbmodel"])
    views = R.previews(built["bbmodel"], size=size)
    sheet = R.sheet(list(views.values()), list(views), title=spec["name"])
    rec = {"spec": spec, "fixes": fixes, "built": built, "checks": report, "sheet": sheet}
    if out_dir is not None:
        paths = B.write_outputs(spec, built, out_dir)
        sheet.save(Path(out_dir) / f"{spec['name']}_views.png")
        for anim in spec["animations"]:
            strip = R.animation_strip(built["bbmodel"], anim["name"])
            if strip:
                strip.save(Path(out_dir) / f"{spec['name']}_{anim['name']}.png")
        rec["paths"] = paths
    return rec


def _png_b64(img) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def critique(llm: LLM, brief: str, rec: dict) -> dict:
    spec = rec["spec"]
    parts = "; ".join(f"{p['name']}: {p['from']}->{p['to']}" for p in spec["parts"])[:3000]
    msg = [{"role": "system", "content": P.CRITIC_SYSTEM},
           {"role": "user", "content": [
               {"type": "text", "text": P.CRITIC_TEMPLATE.format(brief=brief, category=spec["category"], parts=parts)},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _png_b64(rec["sheet"])}}]}]
    text, secs, usage = llm.chat(msg, max_tokens=600, temperature=0.2)
    try:
        out = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        out = {"scores": {}, "issues": [], "unparsed": text[:500]}
    sc = out.get("scores") or {}
    try:
        overall = float(sc.get("overall") or sum(float(v) for v in sc.values()) / max(1, len(sc)))
    except (TypeError, ValueError):
        overall = 0.0
    out["overall"] = max(0.0, min(10.0, overall))
    out["seconds"] = round(secs, 1)
    return out


def _findings_text(rec) -> str:
    lines = [f"- [{f['severity']}] {f['message']}" for f in rec["checks"]["findings"] if f["severity"] != "info"]
    lines += [f"- [auto-fixed] {x}" for x in rec["fixes"]]
    return "\n".join(lines) or "- none"


def _critique_text(cr) -> str:
    if not cr:
        return "- (no critique)"
    sc = cr.get("scores") or {}
    head = "scores: " + ", ".join(f"{k} {v}" for k, v in sc.items())
    issues = [f"- {i.get('part', '?')}: {i.get('problem', '')} -> fix: {i.get('fix', '')}"
              for i in (cr.get("issues") or []) if isinstance(i, dict)]
    return "\n".join([head] + issues[:6])


def plan(llm: LLM, brief: str, category: str | None = None, *, seed: int = 7) -> tuple[dict, list]:
    user = f"Brief: {brief}" + (f"\nCategory: {category}" if category else "")
    msgs = [{"role": "system", "content": P.PLAN_SYSTEM}, {"role": "user", "content": user}]
    log = []
    for attempt in range(2):
        text, secs, usage = llm.chat(msgs, max_tokens=6000, temperature=0.5, seed=seed + attempt)
        log.append({"step": "plan", "seconds": round(secs, 1), "tokens": usage.get("completion_tokens")})
        try:
            raw = extract_json(text)
            S.normalize(raw)
            if category:
                raw.setdefault("category", category)
            return raw, log
        except (ValueError, json.JSONDecodeError, S.SpecError) as exc:
            msgs += [{"role": "assistant", "content": text[:12000]},
                     {"role": "user", "content": f"That JSON is not valid: {exc}. Reply with the corrected JSON only."}]
    raise S.SpecError("planner did not produce a valid model JSON")


def combined(rec) -> float:
    vis = (rec.get("critique") or {}).get("overall", 0.0)
    return round(0.4 * rec["checks"]["score"] / 10.0 + 0.6 * vis, 2)


def run(brief: str, *, category: str | None = None, rounds: int = 2, planner: LLM, critic: LLM | None,
        out_dir: str | Path, seed: int = 7, keep_rounds: bool = True) -> dict:
    """Full loop. Round 0 is the single-shot baseline; rounds 1..N revise from checks + critique."""
    out = Path(out_dir)
    t0 = time.time()
    raw, log = plan(planner, brief, category, seed=seed)
    history = []
    for r in range(rounds + 1):
        rdir = out / f"round{r}" if keep_rounds else None
        try:
            rec = evaluate(raw, out_dir=rdir)
        except (S.SpecError, ValueError) as exc:
            log.append({"step": f"build{r}", "error": str(exc)[:300]})
            if not history:
                raise
            break
        if critic is not None and (rounds > 0 or r == 0):
            rec["critique"] = critique(critic, brief, rec)
            log.append({"step": f"critique{r}", "seconds": rec["critique"]["seconds"],
                        "overall": rec["critique"]["overall"]})
        rec["combined"] = combined(rec)
        history.append(rec)
        log.append({"step": f"round{r}", "checks": rec["checks"]["score"], "combined": rec["combined"]})
        if r == rounds or (rec["checks"]["score"] >= 95 and (rec.get("critique") or {}).get("overall", 0) >= 9):
            break
        prompt = P.REVISE_TEMPLATE.format(brief=brief, spec=json.dumps(rec["spec"], separators=(",", ":")),
                                          findings=_findings_text(rec), critique=_critique_text(rec.get("critique")))
        msgs = [{"role": "system", "content": P.PLAN_SYSTEM}, {"role": "user", "content": prompt}]
        try:
            text, secs, usage = planner.chat(msgs, max_tokens=6000, temperature=0.4, seed=seed + 10 + r)
            log.append({"step": f"revise{r}", "seconds": round(secs, 1)})
            new = extract_json(text)
            S.normalize(new)
            raw = new
        except (ValueError, json.JSONDecodeError, S.SpecError) as exc:
            log.append({"step": f"revise{r}", "error": str(exc)[:300]})
            break
    best = max(history, key=lambda h: (h["combined"], -history.index(h)))
    best_i = history.index(best)
    final = out / "final"
    evaluate(best["spec"], out_dir=final)
    summary = {"brief": brief, "category": best["spec"]["category"], "name": best["spec"]["name"],
               "best_round": best_i, "rounds": [{"round": i, "checks": h["checks"]["score"],
                                                  "critic": (h.get("critique") or {}).get("overall"),
                                                  "combined": h["combined"],
                                                  "findings": [f["code"] for f in h["checks"]["findings"]],
                                                  "issues": (h.get("critique") or {}).get("issues")}
                                                 for i, h in enumerate(history)],
               "log": log, "seconds": round(time.time() - t0, 1), "final_dir": str(final)}
    (out / "report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief", nargs="?")
    ap.add_argument("--spec", help="build an existing spec JSON (no model calls)")
    ap.add_argument("--category", choices=S.CATEGORIES)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--planner", default="litha")
    ap.add_argument("--critic", default="star-fast")
    ap.add_argument("--no-critic", action="store_true")
    ap.add_argument("--base-url")
    ap.add_argument("--key-file")
    ap.add_argument("--out", default="blockbench-out")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    if a.spec:
        raw = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        rec = evaluate(raw, out_dir=Path(a.out) / S.normalize(raw)[0]["name"])
        print(json.dumps({"checks": rec["checks"], "fixes": rec["fixes"], "paths": rec.get("paths")}, indent=1))
        return 0
    if not a.brief:
        ap.error("give a brief or --spec")
    planner = default_llm(a.planner, a.base_url, a.key_file, timeout=300, retries=3)
    critic = None if a.no_critic else default_llm(a.critic, a.base_url, a.key_file)
    name = S._ident(a.brief, "model")[:40]
    res = run(a.brief, category=a.category, rounds=a.rounds, planner=planner, critic=critic,
              out_dir=Path(a.out) / name, seed=a.seed)
    print(json.dumps({k: res[k] for k in ("name", "best_round", "rounds", "seconds", "final_dir")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
