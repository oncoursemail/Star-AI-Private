"""Small, explicit public view of research events and source references.

This is a display boundary, not network authorization: web_fetch still validates
and pins every requested destination. No query, page body, model analysis or
provider exception is forwarded to the desktop's activity stream.
"""
from __future__ import annotations

from datetime import datetime
from html import unescape
import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_PHRASES = {
    "research_started": "Planning source research",
    "query_started": "Searching for sources",
    "query_completed": "Search results received",
    "query_failed": "A search returned no usable evidence",
    "source_started": "Reading a source page",
    "source_read": "Source page read",
    "source_failed": "A source page could not be read",
    "research_followup_started": "Following up on an evidence gap",
    "research_finished": "Research sources ready",
    "research_citations_checked": "Citation references checked",
}
_STATUS = frozenset({"new", "running", "completed", "partial", "failed", "cancelled", "timed_out"})
_STOP = frozenset({"no_sources", "collection_complete", "deadline_reached", "cancelled", "collector_error"})
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
_SENSITIVE_QUERY = re.compile(
    r"(?:api[-_]?key|token|access[-_]?token|refresh[-_]?token|secret|password|"
    r"credential|authorization|sig|signature|x-amz-.+|x-goog-.+)\Z", re.I)


def public_source_url(value) -> str:
    """Return a credential-free public-looking URL for a display link.

    No DNS lookup occurs here. This conservatively hides private address literals,
    local hostnames, signed query strings and malformed URLs. It does not assert
    that a hostname resolves publicly or that its content is trustworthy.
    """
    if (not isinstance(value, str) or not 8 <= len(value) <= 2000 or
            any(ch.isspace() or ord(ch) < 33 or ch in '<>"`\\' for ch in value) or
            _CONTROLS.search(value)):
        return ""
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").rstrip(".").lower()
        if (parts.scheme not in {"http", "https"} or not host or
                parts.username is not None or parts.password is not None):
            return ""
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            return ""
        if any(_SENSITIVE_QUERY.fullmatch(key) for key, _ in parse_qsl(parts.query)):
            return ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or re.fullmatch(r"[0-9.]+", host) or
                    host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".invalid"))):
                return ""
            ascii_host = host.encode("idna").decode("ascii")
            if not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                       for label in ascii_host.split(".")):
                return ""
        else:
            if (not address.is_global or address.is_multicast or address.is_reserved or
                    address.is_unspecified):
                return ""
        # A fragment is unnecessary for source identity and can hold private data.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    except (ValueError, UnicodeError):
        return ""


def _count(value, maximum: int) -> int | None:
    return value if type(value) is int and 0 <= value <= maximum else None


def _title(value) -> str:
    return " ".join(_CONTROLS.sub("", value).split())[:160] if isinstance(value, str) else ""


def sanitize_research_event(event: dict) -> dict | None:
    """Recognize only complete host-authored research event envelopes."""
    kind = event.get("event")
    if not isinstance(kind, str) or kind not in _PHRASES:
        return None
    run_id, seq = event.get("run_id"), _count(event.get("seq"), 1_000_000)
    if (not isinstance(run_id, str) or not _ID.fullmatch(run_id) or seq is None or
            event.get("event_id") != f"{run_id}:{seq}"):
        return {"phase": "Research activity update"}
    payload = {"type": "research", "event": kind, "run_id": run_id,
               "event_id": f"{run_id}:{seq}", "seq": seq}
    for key, values in (("phase", {"search", "read", "followup", "finished", "citations"}),
                        ("status", _STATUS), ("stop_reason", _STOP),
                        ("source_status", {"discovered", "read", "failed"})):
        if isinstance(event.get(key), str) and event[key] in values:
            payload[key] = event[key]
    for key, maximum in (("queries", 12), ("failed_queries", 12), ("planned_queries", 8),
                         ("ordinal", 12), ("pages", 24), ("sources_found", 40),
                         ("sources_read", 40), ("sources_failed", 40),
                         ("peak_concurrency", 4), ("elapsed_ms", 4_000_000), ("found", 4)):
        value = _count(event.get(key), maximum)
        if value is not None:
            payload[key] = value
    if kind.startswith("query_"):
        query_id = event.get("query_id")
        if not isinstance(query_id, str) or not re.fullmatch(r"Q[1-9][0-9]?", query_id):
            return {"phase": "Research activity update"}
        payload["query_id"] = query_id
    if kind.startswith("source_"):
        source_id = event.get("source_id")
        if not isinstance(source_id, str) or not re.fullmatch(r"S[1-9][0-9]?", source_id):
            return {"phase": "Research activity update"}
        payload.update(source_id=source_id, title=_title(event.get("title")),
                       url=public_source_url(event.get("url")))
    if kind == "research_citations_checked":
        checked, invalid = (_count(event.get(key), 10000) for key in ("checked", "invalid"))
        if checked is None or invalid is None or invalid > checked or event.get("semantic_support") != "unchecked":
            return {"phase": "Research activity update"}
        payload.update(checked=checked, invalid=invalid, semantic_support="unchecked")
    at = event.get("at")
    if isinstance(at, str) and len(at) <= 40:
        try:
            stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                payload["at"] = stamp.isoformat(timespec="milliseconds")
        except ValueError:
            pass
    phrase = _PHRASES[kind]
    if kind == "research_finished":
        phrase = {"failed": "Research could not retrieve sources", "cancelled": "Research stopped",
                  "timed_out": "Research time limit reached", "partial": "Research has limited sources"}.get(
                      payload.get("status"), phrase)
    return {"phase": phrase, "activity": payload}


def research_source_report(session, answer: str) -> str:
    """Host-authored source manifest plus honest, non-semantic reference checks."""
    check = session.report_citations(answer)
    summary = session.summary()
    lines = ["### Research sources", "",
             f"{summary['queries']} searches; {summary['sources_read']} pages read; "
             f"{summary['sources_found']} distinct source URLs found."]
    if summary["failed_queries"] or summary["sources_failed"]:
        lines.append(f"{summary['failed_queries']} searches returned no usable evidence; "
                     f"{summary['sources_failed']} source pages could not be read.")
    if summary["status"] in {"cancelled", "timed_out", "failed"}:
        lines.append("Source collection was incomplete; the available evidence is limited.")
    if check["checked"]:
        lines.append(f"Reference check: {check['checked']} references inspected; "
                     f"{check['invalid']} do not match this research session.")
    else:
        lines.append("The response contains no source references. The list below records the retrieved sources.")
    if check["unread_source_ids"]:
        lines.append("Some cited sources were available only as search snippets: " +
                     ", ".join(check["unread_source_ids"]) + ".")
    lines.append("These checks confirm reference membership only. Claim support has not been automatically verified.")
    lines.append("")
    for row in session.source_manifest():
        url = public_source_url(row["final_url"] or row["requested_url"])
        title = _title(unescape(row["title"])) or "Source"
        title = re.sub(r"([\\`*_{}\[\]()#+.!|<>-])", r"\\\1", title)
        status = "page read" if row["status"] == "read" else "search snippet only; page not read"
        destination = f"<{url}>" if url else "link omitted"
        lines.append(f"- [{row['id']}] {title} — {status}. {destination}")
    return "\n".join(lines)
