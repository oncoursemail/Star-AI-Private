"""Deterministic API-catalog intelligence for STAR.

This module is intentionally network-free.  Callers may fetch catalog snapshots with STAR's
existing guarded web reader, then hand the text/spec here for parsing, ranking and planning.
Keeping discovery analysis pure makes it testable and prevents a catalog row from becoming
an executable instruction or an automatic credentialed request.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse


PUBLIC_APIS_REPO = "https://github.com/public-apis/public-apis"
APIS_GURU_DIRECTORY = "https://api.apis.guru/v2/list.json"
MCP_REGISTRY = "https://registry.modelcontextprotocol.io"
API_DIRECTORY = "https://apidirectory.dev/apis.json"

SAFE_HTTP_METHODS = frozenset({"get", "head", "options"})
WRITE_HTTP_METHODS = frozenset({"post", "put", "patch", "delete"})
_WORD = re.compile(r"[a-z0-9][a-z0-9+._-]*", re.IGNORECASE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


@dataclass(frozen=True)
class ApiCandidate:
    name: str
    url: str
    description: str
    category: str = ""
    auth: str = "unknown"
    https: bool | None = None
    cors: str = "unknown"
    source: str = ""
    score: float = 0.0
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenApiSummary:
    title: str
    version: str
    servers: tuple[str, ...]
    operations: tuple[str, ...]
    auth_schemes: tuple[str, ...]
    write_operations: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ArazzoSummary:
    title: str
    version: str
    source_descriptions: tuple[str, ...]
    workflows: tuple[str, ...]
    operation_references: tuple[str, ...]
    workflow_references: tuple[str, ...]
    step_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IntegrationPlan:
    candidate: ApiCandidate
    requested_capability: str
    auth_strategy: str
    verification_steps: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    risk_flags: tuple[str, ...]
    executable_by_star: bool = False


def catalog_fingerprint(text: str) -> str:
    """Stable content identity for provenance without storing the whole catalog in analytics."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cell(value: str) -> str:
    value = value.strip()
    return re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE).strip()


def _extract_link(value: str) -> tuple[str, str]:
    match = _MD_LINK.search(value)
    if match:
        return _cell(match.group(1)), match.group(2).strip()
    url = re.search(r"https?://[^\s|)]+", value)
    return _cell(_MD_LINK.sub(r"\1", value)), url.group(0) if url else ""


def _boolish(value: str) -> bool | None:
    value = value.strip().lower()
    if value in {"yes", "true", "https"}:
        return True
    if value in {"no", "false", "http"}:
        return False
    return None


def parse_public_apis_markdown(markdown: str, *, source: str = PUBLIC_APIS_REPO) -> list[ApiCandidate]:
    """Parse the common public-apis Markdown table shape.

    The parser accepts reordered columns and ignores malformed rows.  It never follows links.
    """
    candidates: list[ApiCandidate] = []
    category = ""
    headers: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            category = line[3:].strip()
            headers = []
            continue
        if not line.startswith("|") or line.count("|") < 3:
            continue
        cells = [_cell(part) for part in line.strip("|").split("|")]
        lowered = [c.lower() for c in cells]
        if not headers and ("api" in lowered or "name" in lowered) and "description" in lowered:
            headers = lowered
            continue
        if all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c):
            continue
        if not headers or len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        api_cell = row.get("api") or row.get("name") or ""
        name, url = _extract_link(api_cell)
        if not name or not url:
            continue
        description = row.get("description", "")
        auth = row.get("auth", "unknown") or "unknown"
        https = _boolish(row.get("https", ""))
        cors = (row.get("cors", "unknown") or "unknown").lower()
        candidates.append(ApiCandidate(
            name=name,
            url=url,
            description=description,
            category=category,
            auth=auth,
            https=https,
            cors=cors,
            source=source,
        ))
    return candidates


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _WORD.finditer(text) if len(match.group(0)) > 1}


def _security_warnings(candidate: ApiCandidate) -> list[str]:
    warnings: list[str] = []
    parsed = urlparse(candidate.url)
    if parsed.scheme != "https":
        warnings.append("documentation link is not HTTPS")
    if candidate.https is False:
        warnings.append("catalog marks API as not HTTPS")
    auth = candidate.auth.strip().lower()
    if auth in {"", "unknown", "null"}:
        warnings.append("authentication requirements need verification")
    if "oauth" in auth:
        warnings.append("OAuth requires an explicit owner-authorized connection")
    if candidate.cors not in {"yes", "no", "unknown"}:
        warnings.append("CORS status is nonstandard and needs verification")
    return warnings


def rank_api_candidates(
    candidates: Iterable[ApiCandidate],
    query: str,
    *,
    prefer_no_auth: bool = True,
    require_https: bool = True,
    limit: int = 12,
) -> list[ApiCandidate]:
    """Rank by lexical fit plus operational friction; no LLM is needed for first-pass retrieval."""
    query_tokens = _tokens(query)
    ranked: list[ApiCandidate] = []
    for candidate in candidates:
        haystack = _tokens(f"{candidate.name} {candidate.category} {candidate.description}")
        overlap = len(query_tokens & haystack)
        if query_tokens and not overlap:
            continue
        score = overlap * 5.0
        reasons: list[str] = []
        if overlap:
            reasons.append(f"{overlap} query terms matched")
        if candidate.https is True:
            score += 2
            reasons.append("catalog marks HTTPS=yes")
        elif require_https:
            score -= 8
        auth = candidate.auth.strip().lower()
        if prefer_no_auth and auth in {"", "no", "none", "null"}:
            score += 3
            reasons.append("no API key listed")
        elif "oauth" in auth:
            score -= 1
        if candidate.cors == "yes":
            score += 0.5
        warnings = _security_warnings(candidate)
        ranked.append(ApiCandidate(
            **{**candidate.__dict__, "score": score, "reasons": tuple(reasons), "warnings": tuple(warnings)}
        ))
    ranked.sort(key=lambda item: (-item.score, item.name.lower(), item.url))
    return ranked[: max(1, min(limit, 50))]


def summarize_openapi(spec: dict[str, Any]) -> OpenApiSummary:
    """Extract the small amount of an OpenAPI document needed for integration planning."""
    if not isinstance(spec, dict):
        raise TypeError("OpenAPI document must be an object")
    version = str(spec.get("openapi") or spec.get("swagger") or "")
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    title = str(info.get("title") or "Untitled API")
    servers: list[str] = []
    if isinstance(spec.get("servers"), list):
        for server in spec["servers"]:
            if isinstance(server, dict) and isinstance(server.get("url"), str):
                servers.append(server["url"])
    elif isinstance(spec.get("host"), str):
        scheme = "https"
        schemes = spec.get("schemes")
        if isinstance(schemes, list) and schemes and isinstance(schemes[0], str):
            scheme = schemes[0]
        base_path = spec.get("basePath") if isinstance(spec.get("basePath"), str) else ""
        servers.append(f"{scheme}://{spec['host']}{base_path}")

    operations: list[str] = []
    writes: list[str] = []
    paths = spec.get("paths")
    if isinstance(paths, dict):
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                method_l = str(method).lower()
                if method_l not in SAFE_HTTP_METHODS | WRITE_HTTP_METHODS:
                    continue
                operation_id = ""
                if isinstance(operation, dict) and isinstance(operation.get("operationId"), str):
                    operation_id = operation["operationId"]
                label = f"{method_l.upper()} {path}"
                if operation_id:
                    label += f" ({operation_id})"
                operations.append(label)
                if method_l in WRITE_HTTP_METHODS:
                    writes.append(label)

    schemes: dict[str, Any] = {}
    components = spec.get("components")
    if isinstance(components, dict) and isinstance(components.get("securitySchemes"), dict):
        schemes = components["securitySchemes"]
    elif isinstance(spec.get("securityDefinitions"), dict):
        schemes = spec["securityDefinitions"]
    auth_schemes = tuple(sorted(str(name) for name in schemes))

    warnings: list[str] = []
    if not version:
        warnings.append("missing OpenAPI/Swagger version")
    if not servers:
        warnings.append("no server URL declared")
    if any(urlparse(url).scheme == "http" for url in servers):
        warnings.append("an API server uses plaintext HTTP")
    if writes:
        warnings.append("spec exposes mutating operations; keep them disabled until separately authorized")
    if not auth_schemes:
        warnings.append("no declared security scheme; verify whether the API is truly unauthenticated")
    return OpenApiSummary(
        title=title,
        version=version,
        servers=tuple(servers),
        operations=tuple(sorted(operations)),
        auth_schemes=auth_schemes,
        write_operations=tuple(sorted(writes)),
        warnings=tuple(warnings),
    )


def integration_plan(candidate: ApiCandidate, requested_capability: str, *, openapi: OpenApiSummary | None = None) -> IntegrationPlan:
    """Create a reviewable plan.  It never executes the external API."""
    auth = candidate.auth.strip() or "unknown"
    risk_flags = list(candidate.warnings or _security_warnings(candidate))
    if openapi is not None:
        risk_flags.extend(openapi.warnings)
    verification = [
        "Open the vendor's first-party documentation and verify the API still exists.",
        "Verify pricing/free-tier limits, attribution, commercial-use terms, retention and privacy rules.",
        "Verify authentication and secret placement; never place service keys in prompts, URLs or client-side code.",
        "Verify HTTPS, redirects, request/response size bounds, timeout behavior and rate limits.",
        "Prefer a machine-readable OpenAPI document or an official MCP server when the provider offers one.",
    ]
    implementation = [
        "Generate a typed adapter from verified documentation/spec metadata, not from catalog prose alone.",
        "Default to read-only GET/HEAD operations and an explicit host allowlist.",
        "Validate all model-generated parameters against a schema before a network request.",
        "Redact credentials and sensitive response fields from logs and model context.",
        "Use bounded retries only for idempotent operations; surface quota/auth failures instead of guessing.",
        "Add recorded-response unit tests plus one owner-approved live smoke test before enabling the adapter.",
    ]
    if openapi and openapi.write_operations:
        implementation.append("Keep POST/PUT/PATCH/DELETE operations behind a separate per-integration permission.")
    return IntegrationPlan(
        candidate=candidate,
        requested_capability=requested_capability,
        auth_strategy=auth,
        verification_steps=tuple(verification),
        implementation_steps=tuple(implementation),
        risk_flags=tuple(dict.fromkeys(risk_flags)),
        executable_by_star=False,
    )


def snapshot_manifest(*, source_url: str, body: str, retrieved_at: str) -> str:
    """Small deterministic manifest suitable for an evidence record."""
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("catalog source must be an absolute HTTPS URL")
    payload = {
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "sha256": catalog_fingerprint(body),
        "bytes": len(body.encode("utf-8")),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))



def summarize_arazzo(document: dict[str, Any]) -> ArazzoSummary:
    """Summarize an Arazzo workflow description without executing any step.

    Arazzo documents are untrusted orchestration descriptions.  STAR records source
    descriptions and operation/workflow references so a later verifier can map them
    onto already-verified OpenAPI/AsyncAPI capabilities before any execution.
    """
    if not isinstance(document, dict):
        raise TypeError("Arazzo document must be an object")
    version = str(document.get("arazzo") or "")
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    title = str(info.get("title") or "Untitled workflow")
    sources: list[str] = []
    warnings: list[str] = []
    raw_sources = document.get("sourceDescriptions")
    if isinstance(raw_sources, list):
        for source in raw_sources:
            if not isinstance(source, dict):
                continue
            name = str(source.get("name") or "").strip()
            url = str(source.get("url") or "").strip()
            source_type = str(source.get("type") or "").strip()
            label = " ".join(part for part in (name, source_type, url) if part)
            if label:
                sources.append(label)
            if url:
                parsed = urlparse(url)
                if parsed.scheme not in {"https", ""}:
                    warnings.append("a workflow source description is not HTTPS")
                if parsed.username is not None or parsed.password is not None:
                    warnings.append("a workflow source URL contains credentials and must be refused")
    elif raw_sources is not None:
        warnings.append("sourceDescriptions is malformed")

    workflow_ids: list[str] = []
    operation_refs: list[str] = []
    workflow_refs: list[str] = []
    step_count = 0
    seen_workflows: set[str] = set()
    raw_workflows = document.get("workflows")
    if isinstance(raw_workflows, list):
        for workflow in raw_workflows:
            if not isinstance(workflow, dict):
                continue
            workflow_id = str(workflow.get("workflowId") or "").strip()
            if workflow_id:
                if workflow_id in seen_workflows:
                    warnings.append("duplicate workflowId")
                seen_workflows.add(workflow_id)
                workflow_ids.append(workflow_id)
            steps = workflow.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_count += 1
                for field in ("operationId", "operationPath"):
                    value = step.get(field)
                    if isinstance(value, str) and value.strip():
                        operation_refs.append(value.strip())
                value = step.get("workflowId")
                if isinstance(value, str) and value.strip():
                    workflow_refs.append(value.strip())
                timeout = step.get("timeout")
                if timeout is not None and (type(timeout) is not int or timeout < 0):
                    warnings.append("a workflow step has an invalid timeout")
    elif raw_workflows is not None:
        warnings.append("workflows is malformed")

    if not version:
        warnings.append("missing Arazzo version")
    if not workflow_ids:
        warnings.append("no workflow IDs found")
    if not sources:
        warnings.append("no source descriptions found")
    if step_count > 500:
        warnings.append("workflow is unusually large and should be reviewed before use")
    # Arazzo itself explicitly leaves security enforcement to the consumer.  Preserve that
    # boundary in the summary so downstream planning never treats a workflow as permission.
    warnings.append("workflow description is orchestration data, not execution permission")
    return ArazzoSummary(
        title=title,
        version=version,
        source_descriptions=tuple(dict.fromkeys(sources)),
        workflows=tuple(dict.fromkeys(workflow_ids)),
        operation_references=tuple(dict.fromkeys(operation_refs)),
        workflow_references=tuple(dict.fromkeys(workflow_refs)),
        step_count=step_count,
        warnings=tuple(dict.fromkeys(warnings)),
    )
