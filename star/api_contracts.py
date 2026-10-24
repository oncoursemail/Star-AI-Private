"""Inert, typed request-shape compiler for inspected OpenAPI documents.

Generates only validation contracts for GET/HEAD path+query parameters.
It NEVER builds runnable HTTP requests, chooses credentials, resolves $refs,
executes scripts, writes project files, or grants permission to a provider.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from jsonschema import Draft202012Validator


_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~/%:{}+-]*$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_-]{0,79})\}")
_PARAM_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.\[\]-]{0,79}$")
_ALLOWED_TYPES = frozenset({"string", "integer", "number", "boolean"})
_READ_METHODS = ("get", "head")
MAX_WALKED_OPERATIONS = 1000
MAX_PARAMETERS_PER_OPERATION = 24
MAX_CONTRACTS = 8


def _credential_like(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return normalized in {
        "apikey", "api_key", "key", "password", "token", "access_token", "secret",
        "client_secret", "authorization", "auth", "bearer", "cookie", "session_key",
    } or normalized.endswith(("_api_key", "_password", "_token", "_secret"))


def _finite_number(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(float(value))


def _field_schema(source: Any) -> dict[str, Any] | None:
    """A strict, small JSON Schema subset. No untrusted regex or remote $ref."""
    if not isinstance(source, dict):
        return None
    if any(field in source for field in ("$ref", "oneOf", "anyOf", "allOf", "not", "items", "properties")):
        return None
    kind = source.get("type")
    if not isinstance(kind, str) or kind not in _ALLOWED_TYPES:
        return None
    output: dict[str, Any] = {"type": kind}
    if kind == "string":
        min_length = source.get("minLength", 0)
        max_length = source.get("maxLength", 512)
        if type(min_length) is not int or type(max_length) is not int:
            return None
        if min_length < 0 or max_length < 0 or min_length > 512:
            return None
        output["minLength"] = min_length
        output["maxLength"] = min(max_length, 512)
        if output["minLength"] > output["maxLength"]:
            return None
    elif kind in ("integer", "number"):
        for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            number = source.get(key)
            if number is not None:
                if not _finite_number(number):
                    return None
                output[key] = number
        if "minimum" in output and "maximum" in output and output["minimum"] > output["maximum"]:
            return None
    enum = source.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not 1 <= len(enum) <= 32:
            return None
        def acceptable(value: Any) -> bool:
            if kind == "string":
                return isinstance(value, str) and len(value) <= 512
            if kind == "integer":
                return type(value) is int
            if kind == "boolean":
                return type(value) is bool
            return _finite_number(value)
        if not all(acceptable(value) for value in enum):
            return None
        output["enum"] = enum
    return output


def _parameters(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 64:
        return []
    return [item for item in raw if isinstance(item, dict)]


def _operation_contract(
    path: str,
    method: str,
    operation: dict[str, Any],
    inherited_parameters: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    if not _SAFE_PATH.fullmatch(path) or len(path) > 400:
        return None, "unsupported route syntax"
    if "requestBody" in operation:
        return None, "read operation declares a request body"
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for param in [*inherited_parameters, *_parameters(operation.get("parameters"))]:
        name = param.get("name")
        where = param.get("in")
        if not isinstance(name, str) or not isinstance(where, str):
            continue
        if where in {"path", "query"}:
            combined[(where, name)] = param
    if len(combined) > MAX_PARAMETERS_PER_OPERATION:
        return None, "too many path/query parameters"

    fields: dict[str, dict[str, Any]] = {"path": {}, "query": {}}
    required: dict[str, list[str]] = {"path": [], "query": []}
    for (where, name), param in sorted(combined.items()):
        if not _PARAM_NAME.fullmatch(name):
            return None, "unsupported parameter name"
        if _credential_like(name):
            if param.get("required") is True or where == "path":
                return None, "required credential-like parameter must be configured outside model input"
            continue
        schema = _field_schema(param.get("schema"))
        if schema is None:
            return None, "unsupported or referenced parameter schema"
        fields[where][name] = schema
        if where == "path" or param.get("required") is True:
            required[where].append(name)

    placeholders = set(_PLACEHOLDER.findall(path))
    if set(fields["path"]) != placeholders:
        return None, "path template does not match required path parameters"

    nested: dict[str, Any] = {}
    outer_required: list[str] = []
    for where in ("path", "query"):
        nested[where] = {
            "type": "object",
            "properties": fields[where],
            "required": sorted(required[where]),
            "additionalProperties": False,
        }
        if required[where]:
            outer_required.append(where)
    operation_id = operation.get("operationId")
    if not isinstance(operation_id, str):
        operation_id = ""
    contract_id = hashlib.sha256(
        (method.upper() + "\x00" + path + "\x00" + operation_id).encode("utf-8")
    ).hexdigest()[:24]
    security = operation.get("security")
    return {
        "id": contract_id,
        "method": method.upper(),
        "path_template": path,
        "operation_id": operation_id[:120],
        "input_schema": {
            "type": "object",
            "properties": nested,
            "required": outer_required,
            "additionalProperties": False,
        },
        "security_declaration_present": security is not None,
        "status": "preview_only_no_execution",
    }, ""


def compile_read_contracts(spec: dict[str, Any], *, max_contracts: int = 6) -> dict[str, Any]:
    """Return a bounded list of typed GET/HEAD parameter shapes for owner review."""
    if not isinstance(spec, dict):
        raise TypeError("OpenAPI spec must be an object")
    if type(max_contracts) is not int or not 1 <= max_contracts <= MAX_CONTRACTS:
        raise ValueError("Request a bounded number of contracts")
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return {"contracts": [], "scanned_operations": 0, "skipped": {"missing paths": 1},
                "executable": False}

    built: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    count = 0
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        inherited = _parameters(item.get("parameters"))
        for method in _READ_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            count += 1
            if count > MAX_WALKED_OPERATIONS:
                skipped["operation scan limit"] = 1
                break
            result, reason = _operation_contract(path, method, operation, inherited)
            if result is None:
                skipped[reason] = skipped.get(reason, 0) + 1
            elif len(json.dumps(result["input_schema"], ensure_ascii=False)) > 4000:
                skipped["parameter schema exceeds response budget"] = (
                    skipped.get("parameter schema exceeds response budget", 0) + 1
                )
            elif len(built) < max_contracts:
                built.append(result)
        if count > MAX_WALKED_OPERATIONS:
            break

    return {
        "contracts": built,
        "scanned_operations": min(count, MAX_WALKED_OPERATIONS),
        "skipped": skipped,
        "executable": False,
        "notice": (
            "Input validation plans only. The caller must independently verify publisher, "
            "auth, vendor terms, resource limits, API semantics and response schema. "
            "No API call or external reference has been made."
        ),
    }


_SAFE_SCHEMA_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "minLength", "maxLength",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "enum",
})


def _safe_compiled_schema(schema: Any, *, depth: int = 0) -> bool:
    """Defense in depth: never let a forged contract smuggle in external references."""
    if depth > 4 or not isinstance(schema, dict):
        return False
    if any(key not in _SAFE_SCHEMA_KEYS for key in schema):
        return False
    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict) or len(props) > MAX_PARAMETERS_PER_OPERATION + 2:
            return False
        if schema.get("additionalProperties") is not False:
            return False
        return all(
            isinstance(name, str) and len(name) <= 80
            and _safe_compiled_schema(child, depth=depth + 1)
            for name, child in props.items()
        )
    return isinstance(schema.get("type"), str) and schema["type"] in _ALLOWED_TYPES


def validate_contract_arguments(contract: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """Check proposed inputs with our restricted schema; never construct an HTTP request."""
    if not isinstance(contract, dict) or contract.get("status") != "preview_only_no_execution":
        raise ValueError("Not a valid inert OpenAPI operation contract")
    schema = contract.get("input_schema")
    if not isinstance(schema, dict) or not isinstance(arguments, dict):
        raise ValueError("Contract arguments must be an object")
    if len(json.dumps(schema, ensure_ascii=False, allow_nan=False)) > 12_000 or not _safe_compiled_schema(schema):
        raise ValueError("Contract schema was not generated from the supported, no-reference subset")
    Draft202012Validator(schema).validate(arguments)
    # Normalizing through JSON refuses custom Python objects and NaN/Infinity.
    return json.loads(json.dumps(arguments, allow_nan=False))
