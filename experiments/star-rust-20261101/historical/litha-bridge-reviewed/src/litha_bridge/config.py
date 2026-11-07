"""No third-party dependency configuration with secure local-only defaults."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import math
from urllib.parse import urlsplit, urlunsplit


class ConfigError(ValueError):
    """An unsafe or inconsistent integration configuration."""


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    raise ConfigError(f"{name} must be an explicit boolean")


def validated_api_base(url: str, *, remote_enabled: bool, name: str) -> str:
    """Reject credential-bearing URLs, arbitrary paths, and remote HTTP endpoints.

    Loopback hosts require explicit URL port on defaults, but an omitted port is
    allowed for local proxy deployments. DNS hostnames other than localhost
    are not considered loopback, even if they currently resolve to 127.0.0.1.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port  # validates port syntax and range
    except ValueError as exc:
        raise ConfigError(f"Invalid {name} URL") from exc
    _ = port
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError(f"Invalid {name} URL scheme or host")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError(f"Credentials must not be embedded in {name} URL")
    if parsed.query or parsed.fragment:
        raise ConfigError(f"Query strings and fragments are not allowed in {name} URL")
    if parsed.path.rstrip("/") not in ("", "/v1", "/api/v1"):
        raise ConfigError(f"Unsupported {name} API path")
    loopback = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if not loopback and not remote_enabled:
        raise ConfigError(f"Remote {name} endpoint disabled by default")
    if not loopback and parsed.scheme != "https":
        raise ConfigError(f"Remote {name} endpoint requires HTTPS")
    # Normalize canonical API prefix so API calls have exactly one prefix.
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/v1", "", ""))


@dataclass(frozen=True)
class BridgeConfig:
    lemonade_enabled: bool = False
    anythingllm_enabled: bool = False
    remote_enabled: bool = False
    lemonade_url: str = "http://127.0.0.1:13305/api/v1"
    anythingllm_url: str = "http://127.0.0.1:3001/api/v1"
    lemonade_api_key: str = field(default="", repr=False)
    anythingllm_api_key: str = field(default="", repr=False)
    timeout_seconds: float = 30.0
    queue_timeout_seconds: float = 5.0
    max_prompt_characters: int = 50_000
    max_parallel_chat: int = 1
    max_context_characters: int = 6000
    max_search_results: int = 4

    def __post_init__(self) -> None:
        for name in ("lemonade_enabled", "anythingllm_enabled", "remote_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ConfigError(f"{name} must be a boolean")
        for name, lower, upper in (("timeout_seconds", 0.2, 300),
                                    ("queue_timeout_seconds", 0.01, 60)):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not lower <= value <= upper):
                raise ConfigError(f"{name} must be finite and in [{lower}, {upper}]")
        for name, lower, upper in (("max_parallel_chat", 1, 16),
                                   ("max_context_characters", 200, 50000),
                                   ("max_prompt_characters", 200, 200000),
                                   ("max_search_results", 1, 20)):
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ConfigError(f"{name} must be an integer in [{lower}, {upper}]")
        validated_api_base(self.lemonade_url, remote_enabled=self.remote_enabled, name="Lemonade")
        validated_api_base(self.anythingllm_url, remote_enabled=self.remote_enabled, name="AnythingLLM")

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        def number(name: str, convert, default):
            value = os.getenv(name)
            if value is None:
                return default
            try:
                return convert(value)
            except ValueError as exc:
                raise ConfigError(f"Invalid {name}") from exc

        return cls(
            lemonade_enabled=_enabled("LITHA_LEMONADE_ENABLED"),
            anythingllm_enabled=_enabled("LITHA_ANYTHINGLLM_ENABLED"),
            remote_enabled=_enabled("LITHA_ALLOW_REMOTE_AI"),
            lemonade_url=os.getenv("LITHA_LEMONADE_URL", cls.lemonade_url),
            anythingllm_url=os.getenv("LITHA_ANYTHINGLLM_URL", cls.anythingllm_url),
            lemonade_api_key=os.getenv("LITHA_LEMONADE_API_KEY", ""),
            anythingllm_api_key=os.getenv("LITHA_ANYTHINGLLM_API_KEY", ""),
            timeout_seconds=number("LITHA_AI_TIMEOUT", float, 30.0),
            queue_timeout_seconds=number("LITHA_QUEUE_TIMEOUT", float, 5.0),
            max_prompt_characters=number("LITHA_MAX_PROMPT_CHARS", int, 50000),
            max_parallel_chat=number("LITHA_MAX_PARALLEL_CHAT", int, 1),
            max_context_characters=number("LITHA_MAX_CONTEXT_CHARS", int, 6000),
            max_search_results=number("LITHA_MAX_RETRIEVED_CHUNKS", int, 4),
        )
