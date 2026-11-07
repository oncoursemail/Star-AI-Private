"""Litha bridge: optional Lemonade inference and AnythingLLM workspace retrieval.

This is an integration candidate, not a modification of a Litha repository.
"""
from .config import BridgeConfig, ConfigError
from .clients import (
    AnythingLLMClient,
    ChatResult,
    LemonadeClient,
    ProviderError,
    SearchHit,
)
from .grounded import GroundedAnswer, GroundedBridge

__all__ = [
    "AnythingLLMClient", "BridgeConfig", "ChatResult", "ConfigError",
    "GroundedAnswer", "GroundedBridge", "LemonadeClient", "ProviderError", "SearchHit",
]
