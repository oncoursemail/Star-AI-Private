"""Client for STAR Knowledge: official Roblox and Luau documentation on the owner's STAR Server.

The knowledge service runs beside the model server on the private network. It answers three
read-only questions:

  search      cited passages from the indexed official documentation
  api_lookup  does this exact engine class or member exist, and is it deprecated
  luau_check  does this Luau snippet compile and pass static type analysis (it is never run)

Rules this module enforces:
  * the address is the owner's setting, validated as a private IP address exactly like
    the STAR Server address; the model can never supply a host or a URL;
  * the key is the STAR Server key from the OS keyring or environment, and it is only ever
    sent to that validated private address, never through a system proxy, never on a redirect;
  * every reply is size-capped and re-shaped field by field, so nothing the service returns
    is trusted as an instruction or allowed to grow the prompt without bound;
  * any failure is a `KnowledgeUnavailable` (an OSError). Callers treat it as "no documentation
    this turn"; a chat turn never fails because of it.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from time import monotonic
from urllib.parse import urlsplit

from .providers import STAR_SERVER, get_api_key, validate_lan_endpoint

KNOWLEDGE_PORT = 8091
OFF = "off"
MAX_REPLY_BYTES = 512 * 1024
MAX_PASSAGE_CHARS = 2400
MAX_QUERY_CHARS = 600
MAX_CODE_CHARS = 20_000
SEARCH_TIMEOUT = 8.0
LOOKUP_TIMEOUT = 5.0
CHECK_TIMEOUT = 25.0
CONNECT_TIMEOUT = 2.0
# Hosts a documentation link may point at. Anything else is dropped, not shown.
_SOURCE_HOSTS = frozenset({"create.roblox.com", "luau.org", "github.com"})
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
# A documentation link is written by STAR into the prompt and into the Markdown sources list, so
# it may only contain characters that cannot end a line, a Markdown link or the data region.
_SOURCE_URL = re.compile(r"https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~%/#?=&+:@,;-]*)?")
_LABEL = "STAR Knowledge"


class KnowledgeUnavailable(OSError):
    """The knowledge service could not answer. Never fatal for a chat turn."""


def validate_knowledge_endpoint(value) -> str:
    """Canonical private-IP URL for STAR Knowledge; only the path differs."""
    return validate_lan_endpoint(value, path="", label=_LABEL)


def knowledge_endpoint_for(settings) -> str:
    """The address to use, or '' when documentation search is off or not configured.

    An explicit `knowledge_endpoint` wins. Otherwise it is the STAR Server's own host on the
    knowledge port. Never raises: a bad saved value simply means "not configured".
    """
    chosen = getattr(settings, "knowledge_endpoint", "")
    if not isinstance(chosen, str) or chosen.strip().lower() == OFF:
        return ""
    try:
        if chosen:
            return validate_knowledge_endpoint(chosen)
        server = validate_lan_endpoint(getattr(settings, "server_endpoint", ""),
                                    allow_cgnat=getattr(settings, "allow_cgnat", False))
    except ValueError:
        return ""
    url = urlsplit(server)
    host = url.netloc.rsplit(":", 1)[0]  # already validated; works for IPv4 and bracketed IPv6
    return f"{url.scheme}://{host}:{KNOWLEDGE_PORT}"


def clean_text(value, limit: int) -> str:
    """Bounded text with control and bidirectional-override characters removed."""
    if not isinstance(value, str):
        return ""
    return _CONTROL.sub("", value)[:limit]


def safe_source_url(value) -> str:
    """An https link to one of the known documentation hosts, else ''.

    Whitespace of any kind, brackets, parentheses, quotes and angle brackets are refused: a link
    such as `https://github.com/x)[Sign in](https://elsewhere` would otherwise add a second link
    (or, with a line break, whole lines) to the list STAR shows under the answer.
    """
    if not isinstance(value, str) or len(value) > 400 or not _SOURCE_URL.fullmatch(value):
        return ""
    try:
        url = urlsplit(value)
    except ValueError:
        return ""
    if url.scheme != "https" or url.username or url.password or (url.hostname or "") not in _SOURCE_HOSTS:
        return ""
    return value


def _passage(raw, rank: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = clean_text(raw.get("text"), MAX_PASSAGE_CHARS).strip()
    if not text:
        return None
    return {
        "rank": rank,
        "title": clean_text(raw.get("title"), 160).strip(),
        "heading": clean_text(raw.get("heading"), 200).strip(),
        "kind": clean_text(raw.get("kind"), 24),
        "url": safe_source_url(raw.get("url")),
        "source": clean_text(raw.get("source"), 40),
        "path": clean_text(raw.get("path"), 240),
        "commit": clean_text(raw.get("commit"), 64),
        "licence": clean_text(raw.get("licence"), 80),
        "retrieved_at": clean_text(raw.get("retrieved_at"), 32),
        "text": text,
    }


def _diagnostics(raw, limit: int = 12) -> list[dict]:
    found = []
    for item in (raw if isinstance(raw, list) else [])[:limit]:
        if not isinstance(item, dict):
            continue
        line, column = item.get("line"), item.get("column")
        found.append({"line": line if type(line) is int and 0 <= line < 1_000_000 else 0,
                      "column": column if type(column) is int and 0 <= column < 100_000 else 0,
                      "kind": clean_text(item.get("kind"), 40),
                      "message": clean_text(item.get("message"), 300)})
    return found


@dataclass
class KnowledgeClient:
    """One short-lived HTTP client per task. `transport` exists for tests."""
    base_url: str
    key: str
    transport: object | None = None

    def _request(self, method: str, path: str, body: dict | None, timeout: float) -> dict:
        import httpx
        # httpx applies its read timeout to each read, not to the reply as a whole. This is the
        # limit for the whole reply, so a service that trickles bytes cannot hold a chat turn.
        deadline = monotonic() + CONNECT_TIMEOUT + timeout
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, transport=self.transport,
                              timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)) as client:
                with client.stream(method, self.base_url + path, json=body,
                                   headers={"Authorization": "Bearer " + self.key}) as response:
                    if response.status_code != 200:
                        raise KnowledgeUnavailable(f"{_LABEL} answered HTTP {response.status_code}")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_REPLY_BYTES:
                            raise KnowledgeUnavailable(f"{_LABEL} reply is too large")
                        if monotonic() > deadline:
                            raise KnowledgeUnavailable(f"{_LABEL} answered too slowly")
                        chunks.append(chunk)
            data = json.loads(b"".join(chunks))
        except KnowledgeUnavailable:
            raise
        except (httpx.HTTPError, ValueError, UnicodeDecodeError) as exc:
            # The exception text may contain the address; the type name is enough.
            raise KnowledgeUnavailable(f"{_LABEL} is unreachable ({type(exc).__name__})") from None
        if not isinstance(data, dict):
            raise KnowledgeUnavailable(f"{_LABEL} sent an unexpected reply")
        return data

    def health(self) -> dict:
        data = self._request("GET", "/health", None, LOOKUP_TIMEOUT)
        return {"ok": data.get("ok") is True,
                "chunks": data.get("chunks") if type(data.get("chunks")) is int else 0,
                "embedded": data.get("embedded") if type(data.get("embedded")) is int else 0,
                "luau_check": data.get("luau_check") is True}

    def search(self, query: str, *, top: int = 4, mode: str = "vector", scope: str | None = None) -> list[dict]:
        """Passages most relevant to `query`, best first. Each is plain, bounded data.

        `scope`: "roblox" searches only the Roblox and Luau documentation, "all" or a group name other indexed
        sources; None leaves the field out (an older service ignores it; a newer one decides from the query)."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query is empty")
        if type(top) is not int or not 1 <= top <= 10 or mode not in ("vector", "bm25", "hybrid"):
            raise ValueError("Invalid documentation search options")
        if scope is not None and (not isinstance(scope, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", scope)):
            raise ValueError("Invalid documentation search scope")
        body = {"query": clean_text(query, MAX_QUERY_CHARS).strip(), "mode": mode, "top": top}
        if scope is not None:
            body["scope"] = scope
        data = self._request("POST", "/search", body, SEARCH_TIMEOUT)
        passages = []
        for raw in (data.get("passages") if isinstance(data.get("passages"), list) else [])[:top]:
            item = _passage(raw, len(passages) + 1)
            if item:
                passages.append(item)
        return passages

    def api_lookup(self, symbols: list[str]) -> list[dict]:
        """Exact engine API names: found or not, signature, deprecation, documentation link."""
        if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 8
                or not all(isinstance(s, str) and 1 <= len(s) <= 120 for s in symbols)):
            raise ValueError("Give 1 to 8 API names such as TweenService:Create")
        data = self._request("POST", "/api-lookup", {"symbols": symbols}, LOOKUP_TIMEOUT)
        results = []
        for raw in (data.get("results") if isinstance(data.get("results"), list) else [])[:8]:
            if not isinstance(raw, dict):
                continue
            item = {"symbol": clean_text(raw.get("symbol"), 120), "found": raw.get("found") is True}
            if item["found"]:
                item.update({
                    "signature": clean_text(raw.get("signature"), 300),
                    "deprecated": raw.get("deprecated") is True,
                    "inherited_from": clean_text(raw.get("inherited_from"), 64),
                    "title": clean_text(raw.get("title"), 160),
                    "heading": clean_text(raw.get("heading"), 200),
                    "kind": clean_text(raw.get("kind"), 24),
                    "url": safe_source_url(raw.get("url")),
                    "source": clean_text(raw.get("source"), 40),
                    "commit": clean_text(raw.get("commit"), 64),
                    "licence": clean_text(raw.get("licence"), 80),
                    "retrieved_at": clean_text(raw.get("retrieved_at"), 32),
                    "text": clean_text(raw.get("text"), 1200).strip(),
                })
            results.append(item)
        return results

    def luau_run(self, code: str, *, tests: str = "", time_limit_s: float = 3.0,
                 memory_limit_mb: int = 256) -> dict:
        """Explicit remote execution on the independently enabled sandbox; no local fallback."""
        from .luau_run_client import run
        return run(self, code, tests=tests, time_limit_s=time_limit_s,
                   memory_limit_mb=memory_limit_mb)

    def luau_check(self, code: str, *, strict: bool = False) -> dict:
        """Static check only. `ran` is True only when the service really ran its tools."""
        if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
            raise ValueError(f"Luau code must be 1 to {MAX_CODE_CHARS} characters")
        body = {"code": code, **({"mode": "strict"} if strict else {})}
        data = self._request("POST", "/luau/check", body, CHECK_TIMEOUT)
        if data.get("executed") is not False or type(data.get("ok")) is not bool:
            raise KnowledgeUnavailable(f"{_LABEL} sent an unexpected Luau check reply")
        errors = _diagnostics(data.get("errors"))
        if not data["ok"] and not errors:
            # A tool hit its time or memory limit: there is no verdict, so this is not a failed
            # check. The caller then says nothing about the code instead of "did not pass".
            raise KnowledgeUnavailable(f"{_LABEL} could not finish the Luau check")
        count = data.get("error_count")
        return {
            "ran": True,
            "ok": data["ok"] and not errors,
            "compiled": data.get("compiled") is True,
            "analyzed": data.get("analyzed") is True,
            "errors": errors,
            "error_count": count if type(count) is int and count >= len(errors) else len(errors),
            "warnings": _diagnostics(data.get("warnings"), 6),
            "notes": [clean_text(n, 240) for n in (data.get("notes") if isinstance(data.get("notes"), list) else [])[:4]
                      if isinstance(n, str)],
            "roblox_api_types": data.get("roblox_api_types") is True,
            "executed": False,
        }


def client_for(settings, *, transport=None) -> KnowledgeClient | None:
    """A client when an address and the STAR Server key both exist, else None. Never raises."""
    try:
        endpoint = knowledge_endpoint_for(settings)
        key = get_api_key(STAR_SERVER) if endpoint else None
    except Exception:
        return None
    return KnowledgeClient(endpoint, key, transport) if endpoint and key else None
