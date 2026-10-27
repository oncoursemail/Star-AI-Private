"""The OpenAPI document is the source of truth: routes, path/query parameters, request bodies, required scopes, rate
overrides and upstream (accounts) forwards are all read from `openapi.json`. The server has a handler per operationId;
`check()` fails when the two disagree.

The validator covers the JSON Schema subset the document uses (type, const, enum, required, properties,
additionalProperties false, min/maxLength, pattern, minimum/maximum, items, min/maxItems, allOf, $ref).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re

SPEC_PATH = Path(__file__).with_name("openapi.json")
METHODS = ("get", "post", "put", "patch", "delete")


class Invalid(ValueError):
    pass


@dataclass
class Operation:
    op_id: str
    method: str
    path: str
    regex: re.Pattern
    params: list[dict]
    body_schema: dict | None
    body_required: bool
    security: list[dict]            # [] = public; else alternatives [{"metallicUser": [...]}, {"serverKey": [...]}]
    rate: dict | None
    upstream: dict | None
    success: int = 200
    raw: dict = field(default_factory=dict)

    @property
    def public(self) -> bool:
        return not self.security


def load(path: Path = SPEC_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Spec:
    def __init__(self, doc: dict | None = None):
        self.doc = doc or load()
        self.ops: list[Operation] = []
        for path, item in self.doc["paths"].items():
            shared = item.get("parameters", [])
            for method in METHODS:
                op = item.get(method)
                if op is None:
                    continue
                params = [self.resolve(p) for p in shared + op.get("parameters", [])]
                body = op.get("requestBody")
                schema = body["content"]["application/json"]["schema"] if body else None
                ok = sorted(int(c) for c in op["responses"] if c.isdigit() and c.startswith("2"))
                rx = re.compile("^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(path)) + "$")
                self.ops.append(Operation(op["operationId"], method.upper(), path, rx, params, schema,
                                          bool(body and body.get("required")), op.get("security", []),
                                          op.get("x-metallic-rate"), op.get("x-metallic-upstream"),
                                          ok[0] if ok else 200, op))
        self.by_id = {o.op_id: o for o in self.ops}
        self.scopes: dict = self.doc.get("x-metallic-scopes", {})

    def resolve(self, node: dict) -> dict:
        while isinstance(node, dict) and "$ref" in node:
            cur = self.doc
            for part in node["$ref"].lstrip("#/").split("/"):
                cur = cur[part]
            node = cur
        return node

    def match(self, method: str, path: str) -> tuple[Operation | None, dict, list[str]]:
        """(operation, path params, allowed methods for this path)."""
        allowed, found = [], None
        for op in self.ops:
            m = op.regex.match(path)
            if m:
                allowed.append(op.method)
                if op.method == method:
                    found = (op, m.groupdict())
        if found:
            return found[0], found[1], allowed
        return None, {}, allowed

    # ---------- validation ----------
    def validate(self, value, schema: dict, where: str = "body") -> None:
        s = self.resolve(schema)
        for sub in s.get("allOf", []):
            self.validate(value, sub, where)
        if "const" in s and value != s["const"]:
            raise Invalid(f"{where} must be {s['const']!r}")
        if "enum" in s and value not in s["enum"]:
            raise Invalid(f"{where} must be one of {', '.join(str(e) for e in s['enum'] if e not in ('', None))}")
        t = s.get("type")
        if t is not None:
            types = t if isinstance(t, list) else [t]
            if not any(_is(value, x) for x in types):
                raise Invalid(f"{where} must be {' or '.join(types)}")
        if isinstance(value, str):
            if len(value) < s.get("minLength", 0):
                raise Invalid(f"{where} is too short")
            if "maxLength" in s and len(value) > s["maxLength"]:
                raise Invalid(f"{where} is too long (at most {s['maxLength']})")
            if "pattern" in s and not re.search(s["pattern"], value):
                raise Invalid(f"{where} has the wrong format")
            if s.get("format") == "uri" and not re.match(r"^https?://[^\s/]+", value):
                raise Invalid(f"{where} must be an http(s) URL")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in s and value < s["minimum"]:
                raise Invalid(f"{where} must be at least {s['minimum']}")
            if "maximum" in s and value > s["maximum"]:
                raise Invalid(f"{where} must be at most {s['maximum']}")
        if isinstance(value, list):
            if len(value) < s.get("minItems", 0) or len(value) > s.get("maxItems", 10**9):
                raise Invalid(f"{where} has the wrong number of items")
            for i, v in enumerate(value):
                if "items" in s:
                    self.validate(v, s["items"], f"{where}[{i}]")
        if isinstance(value, dict):
            for k in s.get("required", []):
                if k not in value:
                    raise Invalid(f"{where}.{k} is required")
            props = s.get("properties", {})
            if s.get("additionalProperties") is False:
                extra = sorted(set(value) - set(props))
                if extra:
                    raise Invalid(f"{where}.{extra[0]} is not allowed")
            for k, v in value.items():
                if k in props:
                    self.validate(v, props[k], f"{where}.{k}")

    def coerce_param(self, param: dict, raw: str):
        """Path/query strings -> typed values, then validate."""
        s = self.resolve(param["schema"])
        value: object = raw
        if s.get("type") == "integer":
            if not re.fullmatch(r"-?\d{1,9}", raw):
                raise Invalid(f"{param['name']} must be a whole number")
            value = int(raw)
        self.validate(value, s, param["name"])
        return value

    def check(self, handlers: set[str]) -> list[str]:
        """Problems between the document and the code (empty = consistent)."""
        problems = []
        ids = [o.op_id for o in self.ops]
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            problems.append(f"duplicate operationId {dup}")
        for o in self.ops:
            if o.op_id not in handlers and o.upstream is None:
                problems.append(f"{o.op_id}: no handler and no x-metallic-upstream")
            names = set(re.findall(r"\{(\w+)\}", o.path))
            declared = {p["name"] for p in o.params if p["in"] == "path"}
            if names != declared:
                problems.append(f"{o.op_id}: path parameters {sorted(names)} vs declared {sorted(declared)}")
            for alt in o.security:
                for scheme, scopes in alt.items():
                    if scheme not in self.doc["components"]["securitySchemes"]:
                        problems.append(f"{o.op_id}: unknown security scheme {scheme}")
                    for sc in scopes:
                        if sc not in self.scopes:
                            problems.append(f"{o.op_id}: scope {sc} is not in x-metallic-scopes")
        for h in sorted(handlers - set(ids)):
            problems.append(f"handler {h} has no operation in the document")
        return problems


def _is(value, t: str) -> bool:
    return {"string": lambda v: isinstance(v, str), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool), "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list), "null": lambda v: v is None}[t](value)
