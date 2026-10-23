"""Optional Strata/Qwen3.8 specialist routing for STAR.

Strata is not a replacement for STAR's normal local brain.  When the owner
turns it on, complex reasoning/Roblox/research/Agent turns may use a separate
loopback Strata server.  Simple chat keeps the small resident model.  The
wrapper below fails back to that normal local model only when the Strata
transport/model is unavailable *before* any streamed output is observed.

No model is downloaded or started here.  Installation is deliberately separate:
Qwen3.8-Flash-Next model files are tens of gigabytes and the owner chooses when
and where to install them.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Callable

from .providers import provider_kind

_LOOPBACK = re.compile(r"^http://(?:127\.0\.0\.1|localhost):(\d{2,5})/v1/?$")
_REASONING = frozenset({"auto", "none", "low", "medium", "high"})
_PROFILES = frozenset({"reasoning", "roblox", "research", "vision", "agent"})


@dataclass(frozen=True)
class StrataPlan:
    active: bool = False
    endpoint: str = ""
    model: str = ""
    reasoning_effort: str = "none"
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 1
    response_tokens: int = 0
    context_chars: int = 0
    task_timeout: int = 0
    reason: str = ""

    @property
    def sampling(self) -> dict[str, float]:
        if not self.active:
            return {}
        return {"temperature": self.temperature, "top_p": self.top_p}


def validate_endpoint(value: str) -> str:
    """Accept only a loopback OpenAI-compatible /v1 endpoint.

    A future remote-Strata feature can reuse STAR Server's authenticated private
    endpoint rules.  The first integration intentionally cannot expose a
    no-key Strata process to the LAN.
    """
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("Strata endpoint must be a local /v1 URL")
    match = _LOOPBACK.fullmatch(value)
    if not match:
        raise ValueError("Use a loopback Strata URL such as http://127.0.0.1:8082/v1")
    port = int(match.group(1))
    if not 1024 <= port <= 65535:
        raise ValueError("Strata port must be between 1024 and 65535")
    return value.rstrip("/")


def _effort(settings: Any, profile: str) -> str:
    chosen = str(getattr(settings, "strata_reasoning", "auto") or "auto").lower()
    if chosen not in _REASONING:
        chosen = "auto"
    if chosen != "auto":
        return chosen
    if profile in {"roblox", "agent"}:
        return "high"
    if profile in {"reasoning", "research", "vision"}:
        return "medium"
    return "none"


def choose(settings: Any, route: Any, prompt: str, *, mode: str, image_count: int = 0) -> StrataPlan:
    """Return a deterministic opt-in plan; performs no I/O and starts nothing."""
    if getattr(settings, "strata_enabled", False) is not True:
        return StrataPlan(reason="disabled")
    if provider_kind(settings) != "local":
        return StrataPlan(reason="selected provider is not the on-device brain")
    if mode == "fast":
        return StrataPlan(reason="Fast mode keeps the resident small model")
    profile = str(getattr(route, "profile", ""))
    if profile not in _PROFILES:
        return StrataPlan(reason="simple chat stays on the resident model")
    if image_count and getattr(settings, "strata_vision_enabled", True) is not True:
        return StrataPlan(reason="Strata vision is disabled")
    model = str(getattr(settings, "strata_model", "") or "").strip()
    if not model:
        return StrataPlan(reason="no Strata model is configured")
    endpoint = validate_endpoint(getattr(settings, "strata_endpoint", ""))
    effort = _effort(settings, profile)
    thinking = effort != "none"
    response = {"reasoning": 4096, "roblox": 6144, "research": 4096, "vision": 4096, "agent": 8192}[profile]
    # Qwen thinking is part of the output budget.  A small cap can expire inside
    # the think block without ever producing the useful answer/tool call.
    response = max(response, int(getattr(route, "response_tokens", 0) or 0))
    context_tokens = int(getattr(settings, "strata_context_tokens", 32768) or 32768)
    context_chars = min(240_000, max(int(getattr(settings, "context_chars", 26000) or 26000),
                                     2 * max(1500, context_tokens - 1024)))
    request_timeout = int(getattr(settings, "strata_timeout", 900) or 900)
    task_timeout = max(int(getattr(route, "task_timeout", 0) or 0),
                       min(3600, request_timeout * (2 if getattr(route, "use_tools", False) else 1)))
    return StrataPlan(
        active=True, endpoint=endpoint, model=model, reasoning_effort=effort,
        temperature=1.0 if thinking else 0.7,
        top_p=0.95 if thinking else 0.80,
        top_k=20, response_tokens=response, context_chars=context_chars,
        task_timeout=task_timeout, reason=f"Strata specialist for {profile}",
    )


def effective_settings(settings: Any, plan: StrataPlan):
    """A Settings clone pointed at Strata; the owner's saved provider is untouched."""
    if not plan.active:
        return settings
    return replace(settings, endpoint=plan.endpoint, model=plan.model)


def request_extras(plan: StrataPlan) -> dict:
    """Strata/Qwen sampling plus an explicit finite thinking budget (issue #728).

    The model can spend thousands of tokens repeating reasoning before
    reaching content. Give it at most 60% of the output cap for thinking so
    that useful answers and tool calls retain their own output allowance.
    This mitigates, but cannot repair, quantization/model-specific loops.
    """
    if not plan.active:
        return {}
    fields = {"reasoning_effort": plan.reasoning_effort, "top_k": plan.top_k}
    if plan.reasoning_effort == "none":
        # Card-recommended Qwen3.8 no-thinking penalty. This must be explicit
        # because legacy Strata configs and clients can override defaults.
        fields["presence_penalty"] = 1.5
    else:
        fields["reasoning_budget_tokens"] = max(
            256, min(8192, int(plan.response_tokens * 0.60)))
    return fields


async def probe(settings: Any, *, endpoint: str | None = None, model: str | None = None) -> dict:
    """Make one tiny real completion against Strata without changing saved settings."""
    from time import monotonic
    from .brain_router import validate_alias
    from .providers import open_client

    target = validate_endpoint(endpoint or getattr(settings, "strata_endpoint", ""))
    name = str(model or getattr(settings, "strata_model", "") or "").strip()
    validate_alias(name, field="strata_model")
    if not name:
        raise ValueError("Choose a Strata model before testing it")
    timeout = int(getattr(settings, "strata_timeout", 900) or 900)
    candidate = replace(settings, provider="local", endpoint=target, model=name)
    started = monotonic()
    async with open_client(candidate, request_timeout=timeout, trust_env=False) as client:
        completion = await client.chat.completions.create(
            model=name,
            messages=[
                {"role": "system", "content": "You are STAR. Reply briefly and plainly."},
                {"role": "user", "content": "Reply with the exact words: Strata is ready."},
            ],
            max_tokens=96, temperature=0.7, top_p=0.8,
            extra_body={"reasoning_effort": "none", "top_k": 20,
                        "presence_penalty": 1.5},
        )
    if not getattr(completion, "choices", None):
        raise RuntimeError("Strata returned no completion choices")
    response = str(completion.choices[0].message.content or "").strip()
    if not response:
        raise RuntimeError("Strata returned no visible text")
    return {
        "ok": True, "model": name, "sample": response[:180],
        "elapsed_ms": max(0, round((monotonic() - started) * 1000)),
    }


def _fallback_worthy(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (404, 500, 502, 503, 504):
        return True
    text = str(exc).lower()
    return any(term in text for term in (
        "connection refused", "connection error", "connecterror", "server disconnected",
        "service unavailable", "out of memory", "cuda error", "model not found",
        "timed out", "timeout",
    ))


class _FallbackStream:
    """Stream Strata with no-replay fallback and bounded repetition detection."""

    def __init__(self, primary, start_fallback: Callable[[], Any],
                 fail: Callable[[BaseException], None], *,
                 loop_guard: bool = True,
                 on_loop: Callable[[BaseException], None] | None = None):
        from .strata_loop_guard import StrataRepetitionGuard
        self._stream = primary.__aiter__() if hasattr(primary, "__aiter__") else primary
        self._start_fallback = start_fallback
        self._fail = fail
        self._seen = False
        self._using_fallback = False
        self._guard = StrataRepetitionGuard() if loop_guard else None
        self._on_loop = on_loop

    def _inspect(self, item) -> None:
        """Only user text and reasoning, never tool-call arguments, are inspected."""
        if self._guard is None or self._using_fallback:
            return
        choices = getattr(item, "choices", None)
        if not choices:
            return
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return
        for key, section in (("reasoning_content", "reasoning"),
                             ("content", "answer")):
            value = getattr(delta, key, None)
            if isinstance(value, str) and value:
                self._guard.feed(section, value)

    def __aiter__(self):
        return self

    async def __anext__(self):
        from .strata_loop_guard import StrataRepetitionError
        while True:
            try:
                item = await self._stream.__anext__()
                self._seen = True
                self._inspect(item)
                return item
            except StopAsyncIteration:
                raise
            except StrataRepetitionError as exc:
                if self._on_loop is not None:
                    try:
                        self._on_loop(exc)
                    except Exception:
                        pass
                close = getattr(self._stream, "aclose", None)
                if callable(close):
                    try:
                        await close()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if self._seen or self._using_fallback or not _fallback_worthy(exc):
                    raise
                self._using_fallback = True
                self._fail(exc)
                replacement = await self._start_fallback()
                self._stream = replacement.__aiter__() if hasattr(replacement, "__aiter__") else replacement


class BackgroundClient:
    """Inject a small Qwen thinking budget for summaries/subagents.

    These callers often request only hundreds of tokens.  Leaving Strata at its
    default high/xhigh thinking can consume the cap before visible output.
    Explicit caller values still win.
    """

    def __init__(self, client):
        self._client = client
        self.chat = self
        self.completions = self

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def create(self, **kwargs):
        options = dict(kwargs)
        # Internal helper calls can originate with a legacy greedy temperature
        # of 0, a known contributor to Qwen3.8 repetition in Strata #728.
        if options.get("temperature") in (None, 0, 0.0):
            options["temperature"] = 1.0
        options.setdefault("temperature", 1.0)
        options.setdefault("top_p", 0.95)
        extra = options.get("extra_body")
        if extra is None:
            extra = {}
        if isinstance(extra, dict):
            extra = dict(extra)
            extra.setdefault("reasoning_effort", "low")
            extra.setdefault("top_k", 20)
            effort = extra["reasoning_effort"]
            if effort == "none":
                extra.setdefault("presence_penalty", 1.5)
            else:
                cap = options.get("max_tokens", 850)
                tokens = cap if type(cap) is int and cap >= 128 else 850
                extra.setdefault("reasoning_budget_tokens",
                                 min(768, max(96, tokens // 2)))
            options["extra_body"] = extra
        return await self._client.chat.completions.create(**options)


class RoutingClient:
    """Minimal AsyncOpenAI-compatible chat wrapper with a safe resident fallback.

    Once Strata fails, every later model call in this task stays on the resident
    model so a tool loop never bounces engines back and forth.
    """

    def __init__(self, primary, fallback, *, strata_model: str, fallback_model: str,
                 on_fallback: Callable[[BaseException], None] | None = None,
                 loop_guard: bool = True,
                 on_loop: Callable[[BaseException], None] | None = None):
        self._primary = primary
        self._fallback = fallback
        self._strata_model = strata_model
        self._fallback_model = fallback_model
        self._on_fallback = on_fallback
        self._on_loop = on_loop
        self._loop_guard = loop_guard
        self._failed = False
        self.chat = self
        self.completions = self

    def __getattr__(self, name):
        return getattr(self._primary, name)

    def _fallback_kwargs(self, kwargs: dict) -> dict:
        cleaned = dict(kwargs)
        cleaned["model"] = self._fallback_model
        # Strata's reasoning/top-k body fields and sampling are not inherited by
        # STAR's resident model; preserve its existing deterministic behavior.
        cleaned.pop("extra_body", None)
        cleaned.pop("top_p", None)
        cleaned["temperature"] = 0.0
        return cleaned

    def _mark_failed(self, exc: BaseException) -> None:
        self._failed = True
        if self._on_fallback is not None:
            try:
                self._on_fallback(exc)
            except Exception:
                pass

    def _inspect_complete(self, result) -> None:
        if not self._loop_guard:
            return
        from .strata_loop_guard import StrataRepetitionGuard, StrataRepetitionError
        guard = StrataRepetitionGuard()
        choices = getattr(result, "choices", None)
        if not choices:
            return
        message = getattr(choices[0], "message", None)
        if message is None:
            return
        try:
            for key, section in (("reasoning_content", "reasoning"),
                                 ("content", "answer")):
                value = getattr(message, key, None)
                if isinstance(value, str) and value:
                    guard.feed(section, value)
        except StrataRepetitionError as exc:
            if self._on_loop is not None:
                try:
                    self._on_loop(exc)
                except Exception:
                    pass
            raise

    async def create(self, **kwargs):
        if self._failed or str(kwargs.get("model", "")) != self._strata_model:
            return await self._fallback.chat.completions.create(**self._fallback_kwargs(kwargs))

        async def fallback_call():
            return await self._fallback.chat.completions.create(**self._fallback_kwargs(kwargs))

        try:
            result = await self._primary.chat.completions.create(**kwargs)
        except Exception as exc:
            if not _fallback_worthy(exc):
                raise
            self._mark_failed(exc)
            return await fallback_call()

        if hasattr(result, "__aiter__"):
            return _FallbackStream(
                result, fallback_call, self._mark_failed,
                loop_guard=self._loop_guard, on_loop=self._on_loop)
        self._inspect_complete(result)
        return result
