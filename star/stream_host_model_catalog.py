"""Trusted, immutable model-to-worker routing for STAR's realtime VTuber.

A scheduler profile supplied by a chat message is not evidence of the model
that will actually run. The embedding host must load *its own* deployment
manifest, verify the worker/runtime and weight digests, and bind a fixed route
before submitting a request. This module cannot inspect loaded weights or
launch workers; treat it as a configuration consistency guard, not attestation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Mapping

from .stream_qos import InferenceJob

_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_KINDS = frozenset({"speech", "vision", "commentary", "research", "training", "render"})


@dataclass(frozen=True)
class HostModelRoute:
    """Host-configured identity and *reserved* resources for one worker model.

    model_sha256 must represent verified weights (or a trusted immutable
    manifest of all weight shards), runtime_sha256 the deployed binary/build,
    and voice_sha256 the voice/configuration digest, if speech. They are NOT
    supplied by a model, prompt, viewer, or network request.
    """

    alias: str
    kind: str
    device: str
    engine: str
    model_sha256: str
    runtime_sha256: str
    ram_mib: float
    vram_mib: float
    voice_sha256: str = ""

    def __post_init__(self) -> None:
        if type(self.alias) is not str or not _ALIAS.fullmatch(self.alias):
            raise ValueError("route alias must be a bounded opaque host ID")
        if self.kind not in _KINDS or self.device not in {"cpu", "gpu"}:
            raise ValueError("route requires an eligible kind and fixed device")
        if type(self.engine) is not str or not _ALIAS.fullmatch(self.engine):
            raise ValueError("runtime engine must be a bounded opaque label")
        for field in ("model_sha256", "runtime_sha256"):
            value = getattr(self, field)
            if type(value) is not str or not _DIGEST.fullmatch(value):
                raise ValueError(f"{field} requires a verified lowercase SHA256")
        if (type(self.voice_sha256) is not str or
                (self.voice_sha256 and not _DIGEST.fullmatch(self.voice_sha256))):
            raise ValueError("voice_sha256 must be empty or lowercase SHA256")
        for field in ("ram_mib", "vram_mib"):
            value = getattr(self, field)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{field} must be a finite host reservation")
            if not 0 <= value <= 200_000:
                raise ValueError(f"{field} exceeds the host reservation range")
        if self.kind in {"vision", "render"} and self.device != "gpu":
            raise ValueError("vision/render must reserve GPU under current QoS")
        if self.device == "cpu" and self.vram_mib:
            raise ValueError("CPU model cannot reserve GPU memory")

    @property
    def route_profile(self) -> str:
        """Stable within a deployed build, different for each material change.

        Includes engine, exact worker identity, voice configuration, resource
        reservation and device. Does not reveal filesystem paths or raw hashes.
        """
        values = {
            "kind": self.kind, "device": self.device, "engine": self.engine,
            "weights": self.model_sha256, "runtime": self.runtime_sha256,
            "voice": self.voice_sha256, "ram": self.ram_mib,
            "vram": self.vram_mib,
        }
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        return "route-" + hashlib.sha256(payload).hexdigest()[:32]


class HostInferenceCatalog:
    """Immutable, host-owned route registry. A nickname is not an authorization.

    The caller is responsible for executing the same verified model/build as
    the chosen manifest entry. Catalog labels are not secrets or credentials.
    """

    def __init__(self, routes: tuple[HostModelRoute, ...]) -> None:
        if type(routes) is not tuple or not routes:
            raise ValueError("a nonempty immutable tuple of routes is required")
        entries: dict[str, HostModelRoute] = {}
        for route in routes:
            if not isinstance(route, HostModelRoute):
                raise TypeError("catalog routes must be HostModelRoute")
            if route.alias in entries:
                raise ValueError("duplicate host route alias")
            entries[route.alias] = route
        self._routes: Mapping[str, HostModelRoute] = MappingProxyType(entries)

    def bind(self, job: InferenceJob, *, route_alias: str) -> InferenceJob:
        if not isinstance(job, InferenceJob):
            raise TypeError("expected validated inference request")
        if type(route_alias) is not str:
            raise ValueError("host must select a route from its own catalog")
        route = self._routes.get(route_alias)
        if route is None:
            raise ValueError("unknown host-selected model route")
        if route.kind != job.kind:
            raise ValueError("requested kind does not match deployed worker")
        if job.device not in ("auto", route.device):
            raise ValueError("requested device conflicts with the deployed worker")
        if job.route_profile:
            raise ValueError("untrusted request cannot pre-bind its own profile")
        return replace(job, device=route.device, ram_mib=route.ram_mib,
                       vram_mib=route.vram_mib,
                       route_profile=route.route_profile)

    def profile_for(self, route_alias: str) -> str:
        """For offline calibration reports, not as an execution credential."""
        return self._routes[route_alias].route_profile

    @property
    def route_count(self) -> int:
        return len(self._routes)


__all__ = ["HostModelRoute", "HostInferenceCatalog"]
