"""Model calls for the builder: STAR's router (OpenAI-compatible). Text: `litha`; vision critic: `star-fast`.

The key is read from ~/.star/server_api_key (or STAR_ROUTER_KEY); it is never printed or returned.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

def _router() -> str:
    """Router URL: STAR_ROUTER_URL, else the first line of ~/.star/mesh_url (kept out of the repository)."""
    env = os.environ.get("STAR_ROUTER_URL", "").strip()
    if env:
        return env
    try:
        return (Path.home() / ".star" / "mesh_url").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return "http://127.0.0.1:8100"


ROUTER = _router()
TEXT_MODEL = os.environ.get("STAR_BUILD_MODEL", "litha")
VISION_MODEL = os.environ.get("STAR_BUILD_VISION", "star-fast")


def _key() -> str:
    env = os.environ.get("STAR_ROUTER_KEY", "").strip()
    if env:
        return env
    path = Path.home() / ".star" / "server_api_key"
    return path.read_text(encoding="utf-8").splitlines()[0].strip()


# Router helpers that would change a structured answer (answer cache, grounding, docs, general helper): off.
PLAIN = {"X-Mesh-Cache": "off", "X-Mesh-Ground": "off", "X-Mesh-General": "off", "X-Mesh-Docs": "off"}


def brain_load() -> int | None:
    """Requests in flight on brain1 (the vision model's host), from the router status; None if unknown."""
    try:
        req = urllib.request.Request(ROUTER.rstrip("/") + "/mesh/status", headers={"Authorization": "Bearer " + _key()})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(json.load(resp).get("brain", {}).get("inflight"))
    except Exception:
        return None


def idle_nodes() -> list[str] | None:
    try:
        req = urllib.request.Request(ROUTER.rstrip("/") + "/mesh/status", headers={"Authorization": "Bearer " + _key()})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return [n.get("name") for n in json.load(resp).get("nodes", []) if n.get("state") == "idle"]
    except Exception:
        return None


def wait_for_node(max_wait_s: float = 4 * 3600, poll_s: float = 20) -> float:
    """Block until a GPU node is idle (so `litha` is not sent to the overloaded brain queue). Returns seconds waited."""
    started = time.monotonic()
    while time.monotonic() - started < max_wait_s:
        nodes = idle_nodes()
        if nodes is None or nodes:
            break
        time.sleep(poll_s)
    return round(time.monotonic() - started, 1)


def node_endpoint() -> tuple[str, str] | None:
    """(chat URL, mesh token) of an idle GPU node, to queue on its own slot instead of letting the router fall back to
    the overloaded brain. Same model the router would use (litha-fast). STAR_BUILD_DIRECT=0 turns this off."""
    if os.environ.get("STAR_BUILD_DIRECT", "1") == "0":
        return None
    try:
        token = (Path.home() / ".star" / "mesh_token").read_text(encoding="utf-8").splitlines()[0].strip()
        req = urllib.request.Request(ROUTER.rstrip("/") + "/mesh/status", headers={"Authorization": "Bearer " + _key()})
        with urllib.request.urlopen(req, timeout=10) as resp:
            nodes = json.load(resp).get("nodes", [])
    except Exception:
        return None
    for n in sorted(nodes, key=lambda n: -(n.get("tok_s") or 0)):
        if n.get("state") == "idle" and n.get("status_url"):
            base = n["status_url"].rsplit(":", 1)[0]
            return base + ":8098/v1/chat/completions", token
    return None


def _stream_once(body: dict, first_token_s: float, timeout: float, endpoint: tuple[str, str] | None = None) -> tuple[str, dict]:
    url, auth, extra = ROUTER.rstrip("/") + "/v1/chat/completions", _key(), PLAIN
    if endpoint:
        url, auth, extra = endpoint[0], endpoint[1], {}
        body = {**body, "model": "litha-fast"}
    req = urllib.request.Request(url, data=json.dumps({**body, "stream": True}).encode(),
                                 headers={"Authorization": "Bearer " + auth, "Content-Type": "application/json", **extra})
    started = time.monotonic()
    chunks, first = [], None
    with urllib.request.urlopen(req, timeout=first_token_s) as resp:
        resp.fp.raw._sock.settimeout(first_token_s) if hasattr(resp.fp, "raw") else None
        for raw in resp:
            now = time.monotonic()
            if now - started > timeout:
                raise TimeoutError("total timeout")
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if "error" in obj:
                raise RuntimeError("stream error")
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                if first is None:
                    first = now - started
                    try:
                        resp.fp.raw._sock.settimeout(120)
                    except Exception:
                        pass
                chunks.append(piece)
    return "".join(chunks), {"seconds": round(time.monotonic() - started, 1), "ttft": round(first or 0, 1)}


def chat(messages: list[dict], *, model: str = TEXT_MODEL, max_tokens: int = 3000, temperature: float = 0.4,
         json_mode: bool = True, timeout: float = 1500.0, first_token_s: float = 420.0) -> tuple[str, dict]:
    """Streamed call; when no token comes within first_token_s (e.g. the router picked the overloaded brain),
    give up on that attempt and ask again (the router re-plans)."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    last = None
    waited = 0.0
    for attempt in range(8):
        endpoint = None
        if model == TEXT_MODEL:
            waited += wait_for_node()
            endpoint = node_endpoint()
        try:
            text, meta = _stream_once(body, first_token_s if not endpoint else 1200, timeout, endpoint)
            meta["direct"] = bool(endpoint)
            meta.update({"model": model, "attempts": attempt + 1, "waited_for_node_s": waited})
            return text, meta
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
            last = error
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"router call failed: {type(last).__name__}")


def _scan(raw: str):
    """Yield (index, char, in_string) over raw, tracking JSON strings."""
    in_str = esc = False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            yield i, ch, True
            continue
        if ch == '"':
            in_str = True
            yield i, ch, True
            continue
        yield i, ch, False


def _repair(raw: str) -> str:
    """Close a truncated JSON text: cut back to the last complete value, then close open brackets."""
    stack, last_ok = [], 0
    for i, ch, quoted in _scan(raw):
        if quoted:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            last_ok = i + 1
            if not stack:
                return raw[:i + 1]
        elif ch == ",":
            last_ok = i
    cut = raw[:last_ok].rstrip().rstrip(",")
    stack = []
    for _i, ch, quoted in _scan(cut):
        if quoted:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    return cut + "".join("}" if b == "{" else "]" for b in reversed(stack))


_COMMENT = re.compile(r"(?m)//[^\n\"]*$")
_TRAILING = re.compile(r",\s*([}\]])")


def parse_json(text: str) -> dict | None:
    """The first JSON object in a reply (tolerates fences, thinking text, comments, trailing commas, truncation)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = text.replace("```json", "").replace("```", "")
    start = text.find("{")
    if start < 0:
        return None
    body = _COMMENT.sub("", text[start:])
    for raw in (body, _repair(body)):
        for attempt in (raw, _TRAILING.sub(r"\1", raw)):
            try:
                value = json.loads(attempt)
                if isinstance(value, dict):
                    return value
            except ValueError:
                continue
    return None


def image_part(path: Path, max_side: int = 1024) -> dict:
    data = Path(path).read_bytes()
    try:
        from io import BytesIO

        from PIL import Image
        im = Image.open(BytesIO(data)).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=82)
        data = buf.getvalue()
    except Exception:
        pass
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}}
