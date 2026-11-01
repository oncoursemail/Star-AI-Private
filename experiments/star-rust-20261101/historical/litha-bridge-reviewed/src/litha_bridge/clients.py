"""Small, separately feature-flagged Lemonade and AnythingLLM API clients.

Calls are side-effect-free except Lemonade inference may load a model already
installed, and AnythingLLM chat may store a conversation in its workspace.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import BoundedSemaphore
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .config import BridgeConfig, ConfigError
from .transport import JSONTransport, ProviderError


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class SearchHit:
    text: str
    title: str
    reference: str
    score: float | None = None


def _must_have(flag: bool, name: str) -> None:
    if not flag:
        raise ConfigError(f"{name} integration is disabled; explicitly enable it to run")


class LemonadeClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.transport = JSONTransport(config.lemonade_url, config.lemonade_api_key, "Lemonade", config)
        self._chat_slots = BoundedSemaphore(config.max_parallel_chat)

    def health(self) -> dict[str, Any]:
        _must_have(self.config.lemonade_enabled, "Lemonade")
        result = self.transport.request("GET", "/health")
        return {k: result.get(k) for k in ("status", "version", "model_loaded")}

    def stats(self) -> dict[str, Any]:
        _must_have(self.config.lemonade_enabled, "Lemonade")
        result = self.transport.request("GET", "/stats")
        return {k: result.get(k) for k in ("time_to_first_token", "tokens_per_second", "input_tokens", "output_tokens", "cache_tokens")}

    def models(self) -> list[dict[str, Any]]:
        """Only installed models; deliberately do not request catalog `show_all`."""
        _must_have(self.config.lemonade_enabled, "Lemonade")
        result = self.transport.request("GET", "/models")
        items = result.get("data")
        if not isinstance(items, list):
            raise ProviderError("Lemonade models response is malformed")
        # Fail closed on malformed capability metadata; never use substring
        # membership on a provider-supplied string in place of a labels array.
        models: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            labels = item.get("labels", [])
            if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
                raise ProviderError("Lemonade model metadata is malformed")
            recipe = item.get("recipe", "")
            if not isinstance(recipe, str):
                raise ProviderError("Lemonade model metadata is malformed")
            if recipe == "cloud" or recipe.startswith("collection.") or item.get("cloud_provider"):
                continue
            models.append({"id": item["id"], "labels": list(labels)})
        return models

    def chat(
        self,
        model: str,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int = 512,
    ) -> ChatResult:
        """Local, already-installed, text-only, non-streaming chat."""
        _must_have(self.config.lemonade_enabled, "Lemonade")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ConfigError("An explicit model ID is required")
        if type(max_tokens) is not int or not (1 <= max_tokens <= 8192):
            raise ConfigError("max_tokens must be between 1 and 8192")
        if not messages or len(messages) > 64:
            raise ConfigError("Provide between 1 and 64 messages")
        sanitized: list[dict[str, str]] = []
        total_characters = 0
        for message in messages:
            if not isinstance(message, Mapping) or message.get("role") not in {"system", "user", "assistant"}:
                raise ConfigError("Only text system/user/assistant messages are supported")
            content = message.get("content")
            if not isinstance(content, str) or len(content) > 50_000:
                raise ConfigError("Message content must be text up to 50,000 characters")
            total_characters += len(content)
            if total_characters > self.config.max_prompt_characters:
                raise ConfigError("Combined messages exceed max_prompt_characters")
            sanitized.append({"role": message["role"], "content": content})
        # Bound admission separately from socket inactivity timeouts. The caller
        # should share one client instance per endpoint; this is not a cross-
        # process/global resource scheduler and not an end-to-end deadline.
        if not self._chat_slots.acquire(timeout=self.config.queue_timeout_seconds):
            raise ProviderError("Lemonade chat queue wait expired; no request was sent")
        try:
            chat_ids = {item["id"] for item in self.models() if "chat" in item["labels"]}
            if model not in chat_ids:
                raise ProviderError("Requested Lemonade chat model is not installed locally; no model was pulled")
            result = self.transport.request("POST", "/chat/completions", payload={
                "model": model, "messages": sanitized, "stream": False, "max_tokens": max_tokens,
            })
        finally:
            self._chat_slots.release()
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("Lemonade chat response is malformed")
        choice = choices[0]
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderError("Lemonade returned no text completion")
        usage = result.get("usage")
        if isinstance(usage, dict):
            usage = {k: v for k, v in usage.items() if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, int)}
        else:
            usage = None
        return ChatResult(text=content, model=result.get("model") if isinstance(result.get("model"), str) else model, usage=usage)


class AnythingLLMClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.transport = JSONTransport(config.anythingllm_url, config.anythingllm_api_key, "AnythingLLM", config)

    def _check(self) -> None:
        _must_have(self.config.anythingllm_enabled, "AnythingLLM")
        if not self.config.anythingllm_api_key:
            raise ConfigError("AnythingLLM requires an API key; configure it outside version control")

    @staticmethod
    def _workspace_path(slug: str, suffix: str) -> str:
        if not isinstance(slug, str) or not slug.strip() or len(slug) > 128 or any(c in slug for c in "/\\?#"):
            raise ConfigError("Invalid workspace slug")
        return f"/workspace/{quote(slug, safe='')}/{suffix}"

    def vector_search(self, workspace_slug: str, query: str, *, top_n: int | None = None,
                      score_threshold: float | None = None) -> list[SearchHit]:
        """Return search evidence; not an LLM completion or proof of factuality."""
        self._check()
        if not isinstance(query, str) or not query.strip() or len(query) > 12000:
            raise ConfigError("Query must be nonempty and at most 12000 characters")
        limit = top_n if top_n is not None else self.config.max_search_results
        if type(limit) is not int or not (1 <= limit <= 20):
            raise ConfigError("top_n must be between 1 and 20")
        payload: dict[str, Any] = {"query": query, "topN": limit}
        if score_threshold is not None:
            if type(score_threshold) not in (int, float) or not 0 <= score_threshold <= 1:
                raise ConfigError("score_threshold must be between 0 and 1")
            payload["scoreThreshold"] = score_threshold
        result = self.transport.request("POST", self._workspace_path(workspace_slug, "vector-search"), payload=payload)
        items = result.get("results")
        if not isinstance(items, list):
            raise ProviderError("AnythingLLM vector-search response is malformed")
        hits: list[SearchHit] = []
        for item in items[:limit]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
                continue
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            title = str(meta.get("title") or meta.get("chunkSource") or "Untitled source")[:200]
            reference = str(meta.get("url") or meta.get("docSource") or meta.get("chunkSource") or title)[:500]
            raw_score = item.get("score")
            score = float(raw_score) if isinstance(raw_score, (int, float)) and 0 <= raw_score <= 1 else None
            hits.append(SearchHit(text=item["text"][:5000], title=title, reference=reference, score=score))
        return hits

    def chat(self, workspace_slug: str, message: str, *, mode: str = "query", session_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        """A separate AnythingLLM-owned chat (can persist workspace history)."""
        self._check()
        if mode not in {"query", "chat"}:
            raise ConfigError("Only non-agent query or chat mode is supported")
        if not isinstance(message, str) or not message.strip() or len(message) > 12000:
            raise ConfigError("Chat message must be nonempty and at most 12000 characters")
        if session_id is not None and (not isinstance(session_id, str) or len(session_id) > 128):
            raise ConfigError("Invalid session_id")
        payload: dict[str, Any] = {"message": message, "mode": mode}
        if session_id:
            payload["sessionId"] = session_id
        result = self.transport.request("POST", self._workspace_path(workspace_slug, "chat"), payload=payload)
        if result.get("type") == "abort" or result.get("error"):
            # The provider's error text may echo document or query content; do not surface it.
            raise ProviderError("AnythingLLM chat aborted or reported an error")
        content = result.get("textResponse")
        if not isinstance(content, str):
            raise ProviderError("AnythingLLM returned no text response")
        sources = result.get("sources")
        return content, sources if isinstance(sources, list) else []
