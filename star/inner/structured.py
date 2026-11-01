"""Structured brain calls: JSON-schema constrained decoding first, then strict parse, tolerant parse, one retry.

Every model output the mind uses (insights, extracted facts) goes through `ask_json`. `complete(system, user,
schema=None) -> str`; `schema_complete(config)` sends `response_format: {"type": "json_schema", ...}` (llama.cpp's
server turns it into a grammar), so a small model cannot produce broken JSON in the first place. A plain
`complete(system, user)` still works: the schema is then only used to validate. Invalid output -> None (callers keep
their rule-based result).
"""
from __future__ import annotations

import inspect
import json
import re
import urllib.request
from pathlib import Path

_TYPES = {"string": str, "number": (int, float), "integer": int, "array": list, "object": dict, "boolean": bool}
_BAD_ESCAPE = re.compile(r"\\(?![\"\\/bfnrtu])")


def tolerant_loads(raw: str):
    """json.loads, else the outermost {...} with code fences dropped and invalid escapes (\\' etc.) repaired."""
    text = str(raw or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = _BAD_ESCAPE.sub("", text[start:end + 1])
    try:
        return json.loads(chunk)
    except ValueError:
        return None


def valid(value, schema: dict) -> bool:
    """A small JSON-schema subset: type, properties, required, items, minItems/maxItems, maxLength."""
    kind = schema.get("type")
    if kind and not isinstance(value, _TYPES[kind]) or (kind in ("number", "integer") and isinstance(value, bool)):
        return False
    if kind == "object":
        props = schema.get("properties", {})
        if any(name not in value for name in schema.get("required", [])):
            return False
        return all(valid(value[name], sub) for name, sub in props.items() if name in value)
    if kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10 ** 6):
            return False
        return all(valid(item, schema.get("items", {})) for item in value)
    if kind == "string":
        return len(value) <= schema.get("maxLength", 10 ** 6)
    return True


def call(complete, system: str, user: str, schema: dict, name: str) -> str:
    """complete() with the schema when it accepts one (constrained decoding on the server), else plain."""
    try:
        takes_schema = "schema" in inspect.signature(complete).parameters
    except (TypeError, ValueError):
        takes_schema = False
    if takes_schema:
        return complete(system, user, schema={"name": name, "schema": schema})
    return complete(system, user)


def parse(raw: str) -> dict:
    """The first JSON object in a model answer (social.activity.parse_json), else the tolerant repair; {} if none."""
    from ..social.activity import parse_json
    value = parse_json(raw)
    if not value:
        fixed = tolerant_loads(raw)
        value = fixed if isinstance(fixed, dict) else {}
    return value


def _obj(required: list[str], **props) -> dict:
    return {"type": "object", "properties": props, "required": required}


_STR, _INT, _NUM = {"type": "string"}, {"type": "integer"}, {"type": "number"}
# Schemas for the older inner calls (sent to the server only; their callers keep validating field by field).
CARD_SCHEMA = _obj(["card", "seed", "in_days", "important"], card=_STR, seed={"type": ["string", "null"]},
                   in_days=_INT, important={"type": "array", "items": _INT})
DIARY_SCHEMA = _obj(["diary", "opinions"], diary=_STR, opinions={"type": "array", "items": _obj(
    ["topic", "evidence", "reason"], topic=_STR, evidence=_NUM, reason=_STR)})
AUDIT_SCHEMA = _obj(["problems"], problems={"type": "array", "items": _obj(["line", "why"], line=_INT, why=_STR)})
DREAM_SCHEMA = _obj(["dream", "gist", "valence", "tell"], dream=_STR, gist=_STR, valence=_NUM, tell=_STR)
REVISE_SCHEMA = _obj(["changes"], changes={"type": "array", "maxItems": 3, "items": _obj(
    ["field", "op", "value", "why"], field=_STR, op=_STR, value={}, why=_STR)})


def ask_json(complete, system: str, user: str, schema: dict, *, name: str = "reply", retries: int = 1):
    """The parsed, schema-valid object, or None."""
    prompt = user
    for _ in range(retries + 1):
        try:
            raw = call(complete, system, prompt, schema, name)
        except Exception:
            return None
        value = tolerant_loads(raw)
        if value is not None and valid(value, schema):
            return value
        prompt = user + "\n\nReply with one JSON object only, exactly in the requested shape."
    return None


def schema_complete(config: dict, *, max_tokens: int = 500, opener=urllib.request.urlopen):
    """complete(system, user, schema=None) on the brain at config['brain_url'] with JSON-schema constrained output."""
    from ..server_key_file import read_key_file
    url = str(config.get("brain_url") or "").rstrip("/")
    if not url:
        raise RuntimeError("brain_url is not set in config.json")
    key = read_key_file(path=Path(config["key_file"])) if config.get("key_file") else read_key_file()
    endpoint = url + ("/chat/completions" if url.endswith("/v1") else "/v1/chat/completions")

    def complete(system: str, user: str, schema: dict | None = None) -> str:
        payload = {"model": config.get("model", "star-fast"), "max_tokens": max_tokens, "temperature": 0.4,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.get("name", "reply"), "strict": True, "schema": schema["schema"]}}
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with opener(request, timeout=float(config.get("request_timeout_s", 180))) as response:
            reply = json.loads(response.read().decode("utf-8"))
        return str(reply["choices"][0]["message"].get("content") or "")
    return complete
