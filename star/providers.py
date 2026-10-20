"""Strict provider routing and OS-backed credentials for STAR Intelligence.

Never accept a model-supplied base URL or store API tokens in settings/SQLite.
The desktop may use a named hosted model only after the owner configures a key.

Every provider has a typed kind, and callers branch on the kind, never on the id:

  local  the managed llama.cpp brain on this PC's loopback interface (no key)
  lan    STAR Server: an owner-entered private address on the local network,
         OpenAI-compatible, always with an API key
  cloud  a fixed HTTPS vendor with the owner's own key

The LAN address is typed by the owner in Settings. It is validated here, at the
one place every model call passes through, so the server key can only ever be
sent only to a validated private address with no DNS lookup.
"""
from __future__ import annotations
from dataclasses import dataclass
import ipaddress
import os
from typing import Literal
from urllib.parse import urlsplit

SERVICE = "STAR Intelligence"
ProviderKind = Literal["local", "lan", "cloud"]

@dataclass(frozen=True)
class Provider:
    label: str
    base_url: str
    env_var: str
    suggested_model: str
    kind: ProviderKind = "cloud"
    base_url_from_settings: bool = False  # the owner's Settings hold the address
    requires_key: bool = True
    default_timeout: float = 55.0         # seconds of silence before one request is dropped
    allow_parallel: bool = True           # may STAR issue two model calls at once?

PROVIDERS: dict[str, Provider] = {
    "groq": Provider("GroqCloud", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-20b"),
    "openrouter": Provider("OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openrouter/free"),
    "gemini": Provider("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.5-flash-lite"),
    "cerebras": Provider("Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gpt-oss-120b"),
}
LOCAL = "local"
STAR_SERVER = "star_server"
# Private providers use owner-entered endpoints. The LAN endpoint is checked
# before STAR reads the server credential.
PRIVATE_PROVIDERS: dict[str, Provider] = {
    LOCAL: Provider("On-device (private)", "", "", "", kind="local",
                    base_url_from_settings=True, requires_key=False,
                    default_timeout=95.0, allow_parallel=False),
    STAR_SERVER: Provider("STAR Server (LAN)", "", "STAR_SERVER_API_KEY", "", kind="lan",
                          base_url_from_settings=True, requires_key=True,
                          default_timeout=600.0, allow_parallel=True),
}
ALL_PROVIDERS: dict[str, Provider] = {**PRIVATE_PROVIDERS, **PROVIDERS}
SEARCH_KEYS = {"brave": "BRAVE_SEARCH_API_KEY", "tavily": "TAVILY_API_KEY"}
KEY_ENV = {**{name: provider.env_var for name, provider in ALL_PROVIDERS.items()
              if provider.requires_key}, **SEARCH_KEYS}

# Use explicit ranges: ipaddress.is_private also includes non-LAN addresses.
# Left out on purpose: link-local (169.254.0.0/16, fe80::/10), where cloud metadata services
# answer, and carrier-grade NAT (100.64.0.0/10), which is opt-in and
# holds a cloud metadata service (100.100.100.200).
_LAN_NETWORKS = tuple(ipaddress.ip_network(block) for block in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",  # RFC 1918
    "127.0.0.0/8",                                    # loopback
    "::1/128", "fc00::/7",                            # IPv6 loopback, ULA
))
# A metadata service that sits inside an allowed range (the IPv6 unique local block).
_METADATA_ADDRESSES = frozenset({ipaddress.ip_address("fd00:ec2::254"),
                                 ipaddress.ip_address("100.100.100.200")})
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_LAN_HINT = "Use your server's private IP address, for example http://192.168.1.20:8080/v1"


def validate_lan_endpoint(value, *, path: str = "/v1", label: str = "STAR Server",
                          allow_cgnat: bool = False) -> str:
    """Return a canonical local-network URL or raise ValueError.

    Allow only explicitly listed private IP ranges; hostnames are refused until
    connection-level DNS pinning prevents credential exfiltration via rebinding.
    """
    hint = _LAN_HINT if path == "/v1" else _LAN_HINT.replace(":8080/v1", ":8091")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Enter your {label} address. " + hint)
    if len(value) > 200 or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{label} address contains spaces or control characters")
    if any(ch in value for ch in "@?#%\\"):
        raise ValueError(f"{label} address must not contain credentials, a query, a fragment or % escapes")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise ValueError(f"{label} address is not a valid URL. " + hint) from exc
    if url.scheme not in ("http", "https"):
        raise ValueError(f"{label} address must start with http:// or https://")
    if url.username is not None or url.password is not None or url.query or url.fragment:
        raise ValueError(f"{label} address must not contain credentials, a query or a fragment")
    try:
        address = ipaddress.ip_address(url.hostname or "")
    except ValueError as exc:
        raise ValueError(f"{label} must use a private IP literal, not a hostname. " + hint) from exc
    # One spelling per destination: an IPv4-mapped IPv6 literal (::ffff:a.b.c.d) is in none of
    # the ranges above and is refused, never unwrapped to its IPv4 address.
    if address in _METADATA_ADDRESSES or not (any(address in network for network in _LAN_NETWORKS)
                                              or (allow_cgnat is True and address in _CGNAT_NETWORK)):
        raise ValueError(f"{label} must be on your private network (10.x, 172.16-31.x, 192.168.x, "
                         "127.x or an IPv6 unique local address). Public, link-local, shared "
                         "(100.64.x unless explicitly enabled) and cloud metadata addresses are refused.")
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    if port is None or not 1024 <= port <= 65535:
        raise ValueError(f"{label} address needs a port from 1024 to 65535, for example :"
                         + ("8080" if path == "/v1" else "8091"))
    canonical = f"{url.scheme}://{host}:{port}{path}"
    # Check what will actually be used, not a silently normalised URL.
    if value not in (canonical, canonical + "/"):
        raise ValueError(f"{label} address must look exactly like {canonical}")
    return canonical

def provider_spec(name) -> Provider:
    """Typed metadata for a provider id. Unknown ids fail closed."""
    spec = ALL_PROVIDERS.get(name) if isinstance(name, str) else None
    if spec is None:
        raise ValueError("Unrecognized model provider")
    return spec

def provider_kind(settings) -> ProviderKind:
    """`local`, `lan` or `cloud` for the selected provider. Compare this, not the id."""
    return provider_spec(getattr(settings, "provider", LOCAL)).kind

def uses_star_server(settings) -> bool:
    """True when STAR Server (LAN) is the selected provider. Never raises, even
    for a hand-edited settings file with an unknown provider id."""
    try:
        return provider_kind(settings) == "lan"
    except ValueError:
        return False

@dataclass(frozen=True)
class CallLimits:
    request_timeout: float   # seconds without a byte before one model request is dropped
    connect_timeout: float
    parallel: int            # simultaneous model calls STAR may issue (1 or 2)
    trust_env: bool          # False: private traffic never goes through a system proxy

def call_limits(settings) -> CallLimits:
    """Per-provider HTTP budget. The LAN server is a slow CPU box: be generous."""
    spec = provider_spec(getattr(settings, "provider", LOCAL))
    if spec.kind == "lan":
        slots = getattr(settings, "server_parallel", 1)
        return CallLimits(float(getattr(settings, "server_timeout", spec.default_timeout)), 5.0,
                          max(1, min(2, slots if type(slots) is int else 1)), False)
    return CallLimits(spec.default_timeout, 8.0, 2 if spec.allow_parallel else 1, True)

def _check_name(name: str) -> None:
    if name not in KEY_ENV:
        raise ValueError("Unknown credential provider")

def get_api_key(name: str) -> str | None:
    """Environment variables take precedence; keyring is optional for CLI tests."""
    _check_name(name)
    value = os.environ.get(KEY_ENV[name], "").strip()
    if value:
        return value
    try:
        import keyring
        return (keyring.get_password(SERVICE, name) or "").strip() or None
    except Exception:
        return None

def save_api_key(name: str, token: str) -> None:
    _check_name(name)
    if not isinstance(token, str) or not 8 <= len(token) <= 2048 or any(c.isspace() for c in token):
        raise ValueError("Paste a valid API key (8–2048 characters, no spaces)")
    try:
        import keyring
        keyring.set_password(SERVICE, name, token)
    except Exception as exc:
        raise RuntimeError("Secure Windows credential storage unavailable; configure the environment variable instead") from exc

def clear_api_key(name: str) -> None:
    _check_name(name)
    try:
        import keyring
        keyring.delete_password(SERVICE, name)
    except Exception:
        pass

def credential_status() -> dict[str, bool]:
    """Never return key bytes to the browser or model."""
    return {name: bool(get_api_key(name)) for name in KEY_ENV}

def connection_for(settings) -> tuple[str, str]:
    """The single place that decides which address and bearer a model call uses."""
    spec = provider_spec(getattr(settings, "provider", None))
    if spec.kind == "local":
        return settings.endpoint, "local-only"
    if spec.kind == "lan":
        endpoint = validate_lan_endpoint(getattr(settings, "server_endpoint", ""),
                                         allow_cgnat=getattr(settings, "allow_cgnat", False))
        key = get_api_key(STAR_SERVER)
        if not key:
            raise ValueError("STAR Server needs its API key. Add it in Settings → STAR Server.")
        return endpoint, key
    key = get_api_key(settings.provider)
    if not key:
        raise ValueError(f"{spec.label} needs an API key. Add it in Settings → AI providers.")
    return spec.base_url, key

def open_client(settings, *, request_timeout: float | None = None):
    """Build the AsyncOpenAI client for the selected provider with its own limits.

    A private LAN server gets an explicit httpx client with `trust_env=False`,
    so a Windows system proxy can never see the prompt or the server key.
    """
    from openai import AsyncOpenAI
    import httpx
    endpoint, key = connection_for(settings)
    limits = call_limits(settings)
    timeout = httpx.Timeout(request_timeout or limits.request_timeout, connect=limits.connect_timeout)
    extra = {} if limits.trust_env else {
        "http_client": httpx.AsyncClient(trust_env=False, timeout=timeout)}
    return AsyncOpenAI(base_url=endpoint, api_key=key, timeout=timeout, max_retries=0, **extra)

# Context size and slot count last reported by a server's own /props endpoint.
# Process memory only: nothing here is a secret and nothing is written to disk.
_SERVER_LIMITS: dict[tuple[str, str], tuple[int, int]] = {}
# Other names the server answers to for the same loaded model (`star-vision` is
# `star-fast`): they share one set of slots, so they share one entry here.
_MODEL_NAMES: dict[tuple[str, str], str] = {}

def remember_model_names(endpoint: str, model: str, aliases=()) -> None:
    """`aliases` are further names of `model` on this server (from its /v1/models list)."""
    for alias in aliases:
        if isinstance(alias, str) and alias and alias != model:
            _MODEL_NAMES[(endpoint.rstrip("/"), alias)] = model

def _instance(settings, model: str | None = None) -> tuple[str, str]:
    """(server address, the server's own id for `model`): the key of everything per-model."""
    endpoint = str(getattr(settings, "server_endpoint", "")).rstrip("/")
    name = str(model or getattr(settings, "model", ""))
    return endpoint, _MODEL_NAMES.get((endpoint, name), name)

def remember_server_limits(endpoint: str, model: str, context_tokens: int, slots: int) -> None:
    if type(context_tokens) is int and context_tokens > 0:
        endpoint = endpoint.rstrip("/")
        _SERVER_LIMITS[(endpoint, _MODEL_NAMES.get((endpoint, model), model))] = (
            context_tokens, slots if type(slots) is int and slots > 0 else 1)

def server_context_tokens(settings, model: str | None = None) -> int:
    """Per-request context of a LAN model: the owner's value, else what /props last said, else 0.

    `model` is the model a request is routed to; the primary model when omitted.
    """
    chosen = getattr(settings, "server_context_tokens", 0)
    known = _SERVER_LIMITS.get(_instance(settings, model))
    if type(chosen) is int and chosen > 0:
        # The owner's value is a ceiling they chose; a smaller model still has its own limit.
        return min(chosen, known[0]) if known and model else chosen
    return known[0] if known else 0

def server_slots(settings, model: str | None = None) -> int:
    """Parallel slots a LAN model last reported through /props; 0 while unknown."""
    known = _SERVER_LIMITS.get(_instance(settings, model))
    return known[1] if known else 0

# Which slot each conversation uses, per (server, model). Process memory only. The
# start is a hash of the conversation, so a chat finds its slot (and the prompt the
# server still holds there) again after STAR restarts.
_SLOT_TABLE: dict[tuple[str, str], dict] = {}
_SLOT_TABLE_CHATS = 64

def _conversation_slot(key: tuple[str, str], conversation: str, slots: int, *, prime: bool) -> int:
    """The slot of a conversation's own requests (a turn, or the warm-up of that turn)."""
    import zlib
    table = _SLOT_TABLE.setdefault(key, {"active": None, "slot": {}})
    held: dict = table["slot"]
    active = table["active"]
    slot = held.get(conversation)
    if slot is None or slot >= slots:
        slot = zlib.crc32(str(conversation).encode("utf-8", "replace")) % slots
        if active is not None and active != conversation and held.get(active) == slot:
            slot = (slot + 1) % slots   # another chat is open there: leave its prompt alone
        if len(held) >= _SLOT_TABLE_CHATS:
            for name in [name for name in held if name != active][:len(held) - _SLOT_TABLE_CHATS + 1]:
                del held[name]
        held[conversation] = slot
    if not prime:
        busy = _busy_slots_now(key)
        if slot in busy:
            # Issue 118: another client (or a helper the server placed there) is generating in this
            # chat's slot right now, so a request naming it would wait for that whole reply. Move the
            # chat to the next idle slot and keep it there: its next turns find this prompt cached.
            idle = [(slot + step) % slots for step in range(1, slots) if (slot + step) % slots not in busy]
            if idle:
                slot = held[conversation] = idle[0]
        table["active"] = conversation   # a real turn: this is the chat the owner is in
    return slot

# Slots a model's server reported as generating, per (server, model), from `GET /slots` just before
# a chat turn (see `look_for_busy_slots`). Read once by that turn's slot choice, then forgotten.
_BUSY_SLOTS: dict[tuple[str, str], tuple[float, frozenset]] = {}
_BUSY_SLOTS_FRESH_S = 5.0
# Servers that answered `GET /slots` with "not here" (llama.cpp started with --no-slots, or not
# llama.cpp at all): not asked again by this process.
_NO_SLOTS_PAGE: set[str] = set()
# Tests replace this with an httpx mock transport; None means the real network.
_SLOT_PROBE_TRANSPORT = None
SLOT_PROBE_TIMEOUT_S = 0.4

def _busy_slots_now(key: tuple[str, str]) -> frozenset:
    import time
    seen = _BUSY_SLOTS.pop(key, None)
    if not seen or time.monotonic() - seen[0] > _BUSY_SLOTS_FRESH_S:
        return frozenset()
    return seen[1]

def _slot_probe_wanted() -> bool:
    """`STAR_SERVER_SLOT_PROBE=off` skips the look at the server's slots before a turn. On unless set."""
    return os.environ.get("STAR_SERVER_SLOT_PROBE", "").strip().lower() not in ("off", "0", "false", "no")

def _busy_from_report(report) -> frozenset | None:
    """Slot ids that are generating, from llama.cpp's `/slots` list; None when it is not such a list."""
    if not isinstance(report, list):
        return None
    busy = set()
    for row in report:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            continue
        processing = row.get("is_processing")
        if processing is None:                      # older llama.cpp builds: state 0 = idle
            processing = row.get("state") not in (None, 0)
        if processing is True:
            busy.add(row["id"])
    return frozenset(busy)

async def look_for_busy_slots(settings, model: str = "", *, conversation: str = "") -> frozenset:
    """Before a chat turn on STAR Server, ask the server which slots of `model` are generating.

    Issue 118: two STAR clients share nothing but the server, so their chats can hash to the same
    slot, and a turn that names a busy slot waits although another slot is free. The answer is kept
    for a few seconds and read once by this turn's `llama_request_fields`, which then moves the chat
    to an idle slot (and keeps it there). Only when the request would be pinned at all (STAR Server,
    two or more slots, a conversation, pinning not switched off).

    Never raises and never delays a turn by more than `SLOT_PROBE_TIMEOUT_S`: any failure (no
    answer, an error status, an unreadable page) leaves the slot choice exactly as it was. Sends the
    server key only to the validated server address (`connection_for`), without any system proxy.
    Two turns sent at the very same moment can both see the slot idle; this narrows the collision to
    the few milliseconds between the look and the request, it does not lock anything on the server.
    `GET /slots?model=X` on a llama.cpp router asks the instance of X, the model this turn is about to use.
    """
    if (provider_kind(settings) != "lan" or not conversation or _server_places_every_request()
            or not _slot_probe_wanted() or server_slots(settings, model or None) < 2):
        return frozenset()
    import time
    import httpx
    key = _instance(settings, model or None)
    try:
        endpoint, api_key = connection_for(settings)
        endpoint = endpoint.rstrip("/")
        if endpoint in _NO_SLOTS_PAGE:
            return frozenset()
        root = endpoint[:-len("/v1")] if endpoint.endswith("/v1") else endpoint
        async with httpx.AsyncClient(trust_env=False, timeout=SLOT_PROBE_TIMEOUT_S,
                                     transport=_SLOT_PROBE_TRANSPORT) as http:
            answer = await http.get(root + "/slots", params={"model": key[1]},
                                    headers={"Authorization": f"Bearer {api_key}"})
        if answer.status_code in (404, 405, 501):
            _NO_SLOTS_PAGE.add(endpoint)
            return frozenset()
        busy = _busy_from_report(answer.json()) if answer.status_code == 200 else None
    except Exception:
        return frozenset()
    if busy is None:
        return frozenset()
    busy = frozenset(slot for slot in busy if not _own_warm(key, slot))
    _BUSY_SLOTS[key] = (time.monotonic(), busy)
    return busy

# Slots busy with this app's own cache warm-up (star/warmup.py `_prime`: the post-answer warm-up or a draft
# warm-up), per ((server, model), slot) -> until when (inf while the request runs). Such a slot is not
# "another client": the turn stays there, waits for the warm-up and reuses what it read. A cancelled
# warm-up keeps the mark for OWN_WARM_GRACE_S, because the server finishes the batch it is reading first.
_OWN_WARMS: dict[tuple[tuple[str, str], int], float] = {}
OWN_WARM_GRACE_S = 15.0

def _own_warm(key: tuple[str, str], slot: int) -> bool:
    import time
    until = _OWN_WARMS.get((key, slot))
    return until is not None and time.monotonic() < until

def own_warm_started(settings, model: str, slot) -> tuple | None:
    """Mark a slot as holding one of this app's warm-ups; returns the mark for `own_warm_ended`."""
    if type(slot) is not int:
        return None
    mark = (_instance(settings, model or None), slot)
    _OWN_WARMS[mark] = float("inf")
    return mark

def own_warm_ended(mark, *, cancelled: bool) -> None:
    import time
    if mark is None:
        return
    if cancelled:
        _OWN_WARMS[mark] = time.monotonic() + OWN_WARM_GRACE_S
    else:
        _OWN_WARMS.pop(mark, None)

async def model_slots_full(settings, model: str, *, probe=None) -> bool:
    """True when every slot of `model` on STAR Server is generating right now (so a new request would queue).

    One `look_for_busy_slots` question (<= `SLOT_PROBE_TIMEOUT_S`). False whenever it cannot tell: not STAR
    Server, slot count unknown, probe switched off or failed. Used to keep interactive chat off a main model
    whose slots are all held by background answers (docs/agents/chat-speed-20261013.md).
    """
    try:
        busy = await (probe or look_for_busy_slots)(settings, model, conversation="interactive-busy-check")
        slots = server_slots(settings, model or None)
    except Exception:
        return False
    return bool(slots) and len(busy) >= slots

def _server_places_every_request() -> bool:
    """`STAR_SERVER_SLOT_PINNING=off`: name no slot at all (see `llama_request_fields`). Off unless set."""
    return os.environ.get("STAR_SERVER_SLOT_PINNING", "").strip().lower() in ("off", "0", "false", "no")

def llama_request_fields(settings, *, conversation: str = "", tools: bool = False, model: str = "",
                         background: bool = False, prime: bool = False) -> dict:
    """Extra request-body fields that make a llama.cpp server reuse its prompt cache.

    Only for the kinds `local` and `lan`, which are llama.cpp servers the owner
    runs. Cloud providers get {}: these are not OpenAI fields and are never
    sent to a vendor.

      cache_prompt        keep the tokens of this prompt in the slot and reuse the
                          common start on the next request
      chat_template_kwargs.preserve_thinking
                          render earlier answers exactly as they were generated
                          (Qwen templates otherwise re-render them differently, which
                          makes the server read every previous answer again)
      id_slot             one conversation stays on one slot of each model. Sent only
                          for the conversation's own requests (a turn and its
                          warm-up), and only when that model has reported two or
                          more slots.

    Slot rules:

      * `model` is the model this request goes to; slots belong to a model, so
        the same chat has one slot on the quick model and one on the main model.
      * A chat keeps its slot. A chat that is opened while another one is in use
        takes a different slot, so switching back finds the first one cached.
      * `prime=True` is the cache warm-up: it takes the chat's slot (the turn it
        prepares is sent there) without declaring that chat the one in use.
      * `background=True` (summaries, sub-agents, code repairs, the lesson digest,
        a voice call: prompts of their own) carries no `id_slot`. A request with
        `id_slot` waits for that one slot even while another is free, so helpers
        pinned to one slot queued behind each other and behind another client
        (issue 118). The server now places them itself. The price: nothing keeps
        the server from putting such a request into the slot that holds the
        chat's prompt, and the chat's next turn then reads its prompt again or
        gets it back from the server's RAM prompt cache.
      * A request without a conversation name is not pinned either.
      * `tools` does not move a request to another slot. The tool prompt and the
        plain prompt of one chat share its slot; the server's RAM prompt cache
        brings back whichever was replaced (1.3-1.6 s, measured).

    Two STAR clients share nothing but the server, so the chats of two clients
    can have the same slot number (a hash, with two slots: one pair in two).
    Before a chat turn the app asks the server which slots are generating
    (`look_for_busy_slots`, issue 118); when the chat's slot is busy and another
    is idle, the turn goes to the idle one and the chat stays there. Two turns
    sent at the very same moment can still both see the slot idle, and then the
    second waits for the first one's request. Setting the
    environment variable `STAR_SERVER_SLOT_PINNING=off` (read for every request,
    off unless set) removes `id_slot` from every request: the server then places
    the chat's turns too, and no client waits while a slot is free. The price:
    a conversation finds its cached prompt only through the server's own choice,
    and two chats with the same system prompt take turns in one slot.

    Pinned requests were verified against llama.cpp build 11541 (router mode) on
    the owner's server. Where the server puts a request without `id_slot` was
    measured there once with a probe script (research notes, server inference
    2.4): the idle slot whose cached prompt shares the longest start with the
    request (above 10 %), otherwise the least recently used one; the next turn
    of a conversation reused its cached prompt that way. It has not been
    measured with STAR's own helpers running or with two clients. That a
    request with `id_slot` waits while its slot is busy is how the llama.cpp
    server queues work (it defers the task); the tests reproduce it with a fake
    server, and it was not timed on the owner's server for this change.
    """
    kind = provider_kind(settings)
    if kind == "cloud":
        return {}
    fields: dict = {"cache_prompt": True, "chat_template_kwargs": {"preserve_thinking": True}}
    slots = server_slots(settings, model or None) if kind == "lan" else 0
    from . import background_cap
    if kind == "lan" and background_cap.process_is_background() and background_cap.is_capped(
            _instance(settings, model or None)[1]):
        # A background process (evals): every star-fast request names the highest background slot, so the
        # server runs at most background_cap.limit() background requests and slot 0 stays free for chat.
        allowed = background_cap.background_slots(slots)
        if allowed or not slots:            # slot count unknown: slot 1; a single-slot model: no pin
            fields["id_slot"] = (allowed or [background_cap.FALLBACK_SLOT])[-1]
        return fields
    if slots >= 2 and conversation and not background and not _server_places_every_request():
        fields["id_slot"] = _conversation_slot(_instance(settings, model or None), str(conversation), slots,
                                               prime=prime)
    return fields

def model_unavailable(exc: BaseException) -> bool:
    """Did a request fail because the server could not serve that model at all?

    True for "model not found" (llama.cpp router: HTTP 400), 404, and the 5xx a
    router returns when a model fails to load. Nothing was generated in any of
    these cases, so the same message can be sent to another model.
    """
    status = getattr(exc, "status_code", None)
    if status in (404, 500, 502, 503):
        return True
    return status == 400 and "not found" in str(getattr(exc, "message", "") or exc).lower()

class _PinnedClient:
    """`client.chat.completions.create(...)` with extra llama.cpp body fields chosen per model.

    Lets the helpers that make their own model calls (summaries, sub-agents,
    specialists, code repair) stay unaware of slots: they are handed this
    instead of the plain client.
    """

    def __init__(self, client, fields_for):
        self._client, self._fields_for = client, fields_for
        self.chat = self.completions = self

    async def create(self, **kwargs):
        send = self._client.chat.completions.create
        extras = None if "extra_body" in kwargs else self._fields_for(str(kwargs.get("model", "")))
        if not extras:
            return await send(**kwargs)
        try:
            return await send(**kwargs, extra_body=extras)
        except Exception as exc:
            # A server that is not llama.cpp may refuse the fields; nothing was generated.
            if getattr(exc, "status_code", None) not in (400, 422):
                raise
            return await send(**kwargs)

def background_client(client, settings, *, conversation: str = ""):
    """The client for model calls that are not the conversation itself.

    On STAR Server every such call carries `llama_request_fields(...,
    background=True)`: the prompt-cache fields without `id_slot`, so the server
    chooses the slot and two helpers never wait for the same one. That also
    means a helper is no longer kept out of the chat's slot (see
    `llama_request_fields`). `conversation` is accepted for the callers and
    does not select anything. For a cloud provider and the on-PC brain this is
    the plain client.
    """
    if provider_kind(settings) != "lan":
        return client
    return _PinnedClient(client, lambda model: llama_request_fields(
        settings, conversation=conversation, model=model, background=True))

def provider_catalog() -> list[dict]:
    statuses = credential_status()
    return [{"id": LOCAL, "label": PRIVATE_PROVIDERS[LOCAL].label, "model": "", "connected": True, "kind": "local"},
            {"id": STAR_SERVER, "label": PRIVATE_PROVIDERS[STAR_SERVER].label, "model": "",
             "connected": statuses[STAR_SERVER], "kind": "lan"}] + [
        {"id": name, "label": p.label, "model": p.suggested_model, "connected": statuses[name], "kind": p.kind}
        for name, p in PROVIDERS.items()
    ]
