"""Typed contract every external agent session adapter (ACP, JSON-RPC, SDK) implements for #424.

Only types and checks live here: nothing is installed, started or contacted by importing this module.

Auth, usage and errors are explicit states, never guesses. A model list, free tier or paid billing path
is known only when an owner-authorized host probe measured it through the provider's own API
(``UsageReport.source == "provider_api"``); a model name, a catalog entry or an agent's self-report
never fills these fields. Everything unmeasured stays ``"unknown"``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, AsyncIterator, Literal, Mapping, Protocol, runtime_checkable

TurnState = Literal["ok", "unavailable", "auth_required", "timeout", "cancelled", "error"]
SessionState = Literal["idle", "ready", "running", "stopped",
                       "unavailable", "auth_required", "timeout", "cancelled", "error"]
AuthState = Literal["unknown", "ok", "auth_required"]
UsageSource = Literal["unmeasured", "provider_api"]
Tier = Literal["unknown", "free", "paid"]
Billing = Literal["unknown", "zero_spend", "paid"]
EventKind = Literal["text", "tool_call", "permission", "end"]


@dataclass(frozen=True)
class UsageReport:
    """Model availability, tier and billing path as measured by an owner-authorized provider API call."""
    source: UsageSource = "unmeasured"
    models: tuple[str, ...] = ()        # as listed by the provider API, never inferred from names
    tier: Tier = "unknown"
    billing: Billing = "unknown"
    quota_remaining: int | None = None
    measured_at: float | None = None    # epoch seconds of the provider API response
    endpoint: str = ""                  # which provider API produced it (no keys, no hosts with secrets)

    def __post_init__(self) -> None:
        if self.source not in ("unmeasured", "provider_api") or self.tier not in ("unknown", "free", "paid") \
                or self.billing not in ("unknown", "zero_spend", "paid"):
            raise ValueError("Unknown usage state")
        if type(self.models) is not tuple or not all(type(m) is str and m for m in self.models):
            raise ValueError("Models must be a tuple of non-empty names")
        if self.quota_remaining is not None and (type(self.quota_remaining) is not int or self.quota_remaining < 0):
            raise ValueError("Quota must be a non-negative integer or None")
        if self.source == "unmeasured":
            if self.models or self.tier != "unknown" or self.billing != "unknown" \
                    or self.quota_remaining is not None or self.measured_at is not None or self.endpoint:
                raise ValueError("Unmeasured usage cannot claim models, tier, billing or quota")
        elif (not self.endpoint or self.measured_at is None or type(self.measured_at) not in (int, float)
              or not math.isfinite(self.measured_at) or self.measured_at <= 0):
            raise ValueError("A provider API measurement needs its endpoint and time")


UNMEASURED = UsageReport()


@dataclass(frozen=True)
class SessionProbe:
    """What the host knows about one agent without launching it."""
    agent: str
    installed: bool
    enabled: bool
    state: SessionState
    auth: AuthState = "unknown"
    usage: UsageReport = UNMEASURED
    error: str = ""


@dataclass(frozen=True)
class SessionEvent:
    """One streamed item of a turn. ``tool_call`` data is agent_reported, never host-verified."""
    kind: EventKind
    data: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentSessionAdapter(Protocol):
    name: str
    enabled: bool
    state: SessionState
    auth: AuthState

    def probe(self) -> SessionProbe:
        """Installed/auth/usage status; must not launch the agent or guess sign-in, quota or billing."""
        ...

    async def start(self) -> SessionState:
        """Launch and open one session; returns "ready" or the failure state. Refuses unless enabled."""
        ...

    def stream(self, prompt: str) -> AsyncIterator[SessionEvent]:
        """Send one prompt; yield text/tool_call/permission events, then exactly one ``end`` event."""
        ...

    async def request_tool_approval(self, request: Mapping[str, Any]) -> bool:
        ...
        """Ask the host whether one tool call may run; anything but an explicit yes is a no."""

    def cancel(self) -> None:
        """Ask the running turn to stop; the turn ends as "cancelled"."""

    async def stop(self) -> None:
        """End the session and its process."""
