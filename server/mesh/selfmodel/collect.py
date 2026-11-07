"""One snapshot of everything STAR runs on, pulled from endpoints that already exist (nothing new on the GPU PCs).

Sources (all optional; a missing or failing one becomes `ok: false` with the reason, never an exception):
  router  GET <router_url>/mesh/status   nodes (state, busy reason, GPU, VRAM free, tok/s), brain health, decisions
  brain   GET <brain_url>/models         every brain model: loaded or not, context, threads, slots, drafter
          GET <brain_url>/metrics?model= requests processing now (only for loaded models)
  services GET <url> per entry           knowledge, laptop workers, image service, verifier, docs, Forgejo, ...
  files   deployed_files                 git blob id of each service's main file (code.py maps it to a commit)

The brain key is sent only to the router and the brain (and to a service marked "auth": "key"); never to Forgejo or
the laptop/image services. Values of keys are never stored in the snapshot.
"""
from __future__ import annotations

import hashlib
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

Fetch = Callable[[str, dict, float], tuple[int, bytes]]


def http_fetch(url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # LAN only: never a system proxy
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(1_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(20_000)


def blob_id(data: bytes) -> str:
    """The git blob id of a file's bytes (what `git hash-object` prints)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _json(raw: bytes):
    import json
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None


def _get(fetch: Fetch, url: str, key: str | None, timeout: float) -> tuple[bool, object, float, str]:
    """(ok, parsed JSON or text, ms, error)."""
    t0 = time.monotonic()
    try:
        status, raw = fetch(url, {"Authorization": f"Bearer {key}"} if key else {}, timeout)
    except Exception as e:   # connect refused, timeout, DNS: the source is down, not the self-model
        return False, None, round((time.monotonic() - t0) * 1000), f"{type(e).__name__}: {str(e)[:120]}"
    ms = round((time.monotonic() - t0) * 1000)
    data = _json(raw)
    if data is None:
        data = raw.decode("utf-8", "replace")
    if status != 200:
        return False, data, ms, f"HTTP {status}"
    return True, data, ms, ""


def _arg(args: list, flag: str):
    try:
        return args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def brain_models(data) -> list[dict]:
    out = []
    for m in (data or {}).get("data", []) if isinstance(data, dict) else []:
        st = m.get("status") or {}
        args = [str(a) for a in st.get("args") or []]
        model_file = _arg(args, "--model") or ""
        out.append({
            "id": m.get("id"),
            "loaded": st.get("value") == "loaded",
            "status": st.get("value"),
            "ctx": int(_arg(args, "--ctx-size") or 0) or None,
            "threads": int(_arg(args, "--threads") or 0) or None,
            "parallel": int(_arg(args, "--parallel") or 0) or None,
            "drafter": "--model-draft" in args or "--spec-type" in args,
            "file": model_file.rsplit("/", 1)[-1],
            "size_gb": round(((m.get("meta") or {}).get("size") or 0) / 1e9, 1) or None,
        })
    return out


def metric(text: str, name: str) -> float | None:
    m = re.search(rf"^llamacpp:{re.escape(name)}\s+([0-9.eE+-]+)\s*$", text or "", re.M)
    return float(m.group(1)) if m else None


def summarize_decisions(decisions: list) -> dict:
    """Last router decisions -> who answered, how fast, what went wrong (the 'why slow' evidence)."""
    rows = [d for d in decisions or [] if isinstance(d, dict)]
    by: dict[str, int] = {}
    ttft, tps, errors = [], [], []
    for d in rows:
        chosen = d.get("chosen") or d.get("cache") or "none"
        by[str(chosen)] = by.get(str(chosen), 0) + 1
        if isinstance(d.get("ttft_ms"), (int, float)):
            ttft.append(d["ttft_ms"])
        if isinstance(d.get("tok_s"), (int, float)) and d["tok_s"] > 0:
            tps.append(d["tok_s"])
        for e in d.get("errors") or []:
            errors.append(str(e)[:160])
    last = rows[0] if rows else {}
    return {
        "requests": len(rows),
        "by_backend": by,
        "median_first_word_ms": round(statistics.median(ttft)) if ttft else None,
        "median_tok_s": round(statistics.median(tps), 1) if tps else None,
        "errors": errors[:5],
        "last": {k: last.get(k) for k in ("model", "chosen", "reason", "ttft_ms", "tok_s", "outcome", "ts")} if last else {},
    }


def node_view(n: dict) -> dict:
    models = n.get("models") or []
    model = next((m for m in models if m.get("id") == "litha-fast"), models[0] if models else {})
    gpu = n.get("gpu") or {}
    return {
        "name": n.get("name"), "state": n.get("state"), "reason": n.get("reason") or "", "usable": bool(n.get("usable")),
        "why_not": n.get("why_not") or "", "tok_s": n.get("tok_s"), "model": model.get("id"),
        "model_loaded": bool(model.get("loaded")), "inflight": n.get("inflight", 0), "served": n.get("served", 0),
        "last_error": n.get("last_error") or "", "gpu": gpu.get("name"), "vram_total_mb": gpu.get("vram_total_mb"),
        "vram_free_mb": gpu.get("vram_free_mb"), "gpu_util": gpu.get("util"),
    }


def local_hour(tz: str = "America/Chicago", now: float | None = None) -> int:
    """Hour in the owner's zone (the night rule is Chicago time; the container clock is UTC)."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromtimestamp(now or time.time(), ZoneInfo(tz)).hour
    except Exception:   # no tz database: the host's own local time
        return time.localtime(now).tm_hour


def scheduling(nodes: list[dict], brain: dict, min_vram_mb: int = 6000, tz: str = "America/Chicago") -> dict:
    """Where heavy work of her own (training, distillation, re-indexing) can run right now, from real states.
    A GPU counts as free when its node is idle (nobody gaming/streaming, the node's own checks) or switched off by us
    with the card actually free; the brain counts as free when no request is in flight and none is processing."""
    free = []
    for n in nodes:
        vram = n.get("vram_free_mb") or 0
        if n.get("state") == "idle" and n.get("inflight", 0) == 0:
            free.append({"name": n["name"], "gpu": n.get("gpu"), "vram_free_mb": vram, "serving_litha": True})
        elif n.get("state") == "off" and "OFF file" in (n.get("reason") or "") and vram >= min_vram_mb:
            free.append({"name": n["name"], "gpu": n.get("gpu"), "vram_free_mb": vram, "serving_litha": False})
    processing = sum(int(m.get("processing") or 0) for m in brain.get("models") or [])
    brain_idle = bool(brain.get("healthy")) and processing == 0 and int(brain.get("inflight") or 0) == 0
    best = max(free, key=lambda f: f["vram_free_mb"], default=None)
    hour = local_hour(tz)
    return {
        "free_gpus": free,
        "best_gpu": best["name"] if best else None,
        "brain_idle": brain_idle,
        "night": hour < 8,   # the owner's rule: heavy work 00:00-08:00 Chicago
        "local_hour": hour,
        "why": ("free: " + ", ".join(f"{f['name']} ({f['vram_free_mb']} MB)" for f in free)) if free
               else "no GPU is free: " + "; ".join(f"{n['name']} {n.get('state')} ({n.get('reason') or '-'})" for n in nodes),
    }


def collect(cfg: dict, key: str | None, fetch: Fetch = http_fetch, read_file=None) -> dict:
    timeout = float(cfg.get("timeout_s", 3.0))
    read_file = read_file or (lambda p: Path(p).read_bytes())
    snap: dict = {"ts": time.time(), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "errors": []}

    # router: nodes + brain health + decisions
    ok, data, ms, err = _get(fetch, cfg["router_url"].rstrip("/") + "/mesh/status", key, timeout)
    nodes: list[dict] = []
    router: dict = {"ok": ok, "ms": ms}
    brain: dict = {}
    if ok and isinstance(data, dict):
        nodes = [node_view(n) for n in data.get("nodes") or []]
        router.update({k: (data.get("router") or {}).get(k) for k in ("version", "uptime_s")})
        router["recent"] = summarize_decisions(data.get("decisions") or [])
        b = data.get("brain") or {}
        brain = {"name": b.get("name", "brain1"), "healthy": b.get("healthy"), "tok_s": b.get("tok_s"),
                 "inflight": b.get("inflight", 0)}
        cache = (data.get("instant") or {}).get("cache") or {}
        router["answer_cache"] = {"entries": cache.get("entries"), "hits": cache.get("hits")}
        for n in nodes:
            if n["last_error"]:
                snap["errors"].append({"where": f"node {n['name']}", "error": n["last_error"]})
        for e in router["recent"]["errors"]:
            snap["errors"].append({"where": "router", "error": e})
    else:
        router["error"] = err
        snap["errors"].append({"where": "router", "error": err})

    # brain: models + what is processing
    if cfg.get("brain_url"):
        base = cfg["brain_url"].rstrip("/")
        ok, data, ms, err = _get(fetch, base + "/models", key, timeout)
        brain.update({"ok": ok, "ms": ms})
        if ok:
            brain["models"] = brain_models(data)
            for m in brain["models"]:
                if m["loaded"]:
                    mok, text, _, _ = _get(fetch, f"{base}/metrics?model={m['id']}", key, timeout)
                    if mok and isinstance(text, str):
                        m["processing"] = int(metric(text, "requests_processing") or 0)
                        m["deferred"] = int(metric(text, "requests_deferred") or 0)
                        tps = metric(text, "predicted_tokens_seconds")
                        m["tok_s_avg"] = round(tps, 1) if tps else None
        else:
            brain["error"] = err
            snap["errors"].append({"where": "brain", "error": err})
    if cfg.get("load_file"):
        try:
            brain["host_load"] = [float(x) for x in read_file(cfg["load_file"]).split()[:3]]
        except (OSError, ValueError):
            pass

    # services
    services = []
    for s in cfg.get("services") or []:
        ok, data, ms, err = _get(fetch, s["url"], key if s.get("auth") == "key" else None, timeout)
        detail = ""
        if isinstance(data, dict):
            for k in ("model", "service", "status", "busy", "waiting", "loaded", "device"):
                if k in data and not isinstance(data[k], (dict, list)):
                    detail += f"{k}={data[k]} "
            if s.get("version_regex") is None and isinstance(data.get("sources"), list):
                detail += f"sources={len(data['sources'])} "
        elif isinstance(data, str) and s.get("version_regex"):
            m = re.search(s["version_regex"], data)
            if m:
                detail = f"version={m.group(1)}"
        services.append({"name": s["name"], "host": s.get("host", ""), "role": s.get("role", ""), "ok": ok, "ms": ms,
                         "detail": detail.strip() or (err if not ok else "")})
        if not ok:
            snap["errors"].append({"where": f"service {s['name']}", "error": err or "down"})

    # deployed code: blob ids of each service's main file in this container
    deployed = {}
    for name, path in (cfg.get("deployed_files") or {}).items():
        try:
            data = read_file(path)
            # deploys from a Windows checkout (core.autocrlf) carry CRLF; git stores LF: report the LF id too
            deployed[name] = {"file": path.split("/app/", 1)[-1], "blob": blob_id(data),
                              "blob_lf": blob_id(data.replace(b"\r\n", b"\n"))}
        except OSError:
            deployed[name] = {"file": path.split("/app/", 1)[-1], "blob": None}

    machines = []
    for name, facts in (cfg.get("machines") or {}).items():
        row = {"name": name, **facts}
        node = next((n for n in nodes if n["name"] == name), None)
        if node:
            row.update({"gpu": node["gpu"] or facts.get("gpu"), "vram_free_mb": node["vram_free_mb"],
                        "vram_total_mb": node["vram_total_mb"], "gpu_util": node["gpu_util"], "state": node["state"]})
        machines.append(row)

    snap.update({"router": router, "nodes": nodes, "brain": brain, "services": services, "machines": machines,
                 "code": {"deployed": deployed}, "scheduling": scheduling(nodes, brain, int(cfg.get("heavy_min_vram_mb", 6000)),
                                                                   cfg.get("timezone", "America/Chicago"))})
    return snap
