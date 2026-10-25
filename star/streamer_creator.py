"""Offline, non-networking safety and attention contracts for STAR Creator Studio.

This is NOT a broadcaster, chat client, channel creator, or account connector.
The future trusted host owns authentication, platform scopes, moderation and
stream state verification. Model/game/chat text never authorizes tool actions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

PLATFORMS = frozenset({"twitch", "youtube", "tiktok"})
MODES = frozenset({"focus", "chat", "story", "cozy", "cat", "puppy"})
MAX_CHAT_QUEUE = 80
CHAT_TTL_MS = 90_000
CHAT_RESPONSE_COOLDOWN_MS = 12_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")


@dataclass(frozen=True)
class ChatCandidate:
    """The verified host supplies a public, already-moderated message.

    Neither the fields nor the Python dataclass are proof of API authentication.
    The candidate is UNTRUSTED TEXT, never an instruction or permission.
    """
    platform: str
    message_id: str
    received_ms: int
    text: str
    moderated: bool


@dataclass(frozen=True)
class ChatChoice:
    platform: str
    message_id: str
    question: str
    # Still untrusted data. Only a separate speech-only LLM context may read it.


class ChatAttention:
    """Bounded, ephemeral chat queue; quiet when gameplay is demanding.

    Never stores names, platform credentials or personal history. Its in-memory
    queue and seen IDs vanish when the process exits. Chat selection isn't a
    command, and this class never sends messages to a platform.
    """
    def __init__(self) -> None:
        self._queue: list[ChatCandidate] = []
        self._seen: set[tuple[str, str]] = set()
        self._seen_order: list[tuple[str, str]] = []
        self._last_ms: int | None = None
        self._last_platform: str | None = None

    def reset(self) -> None:
        self._queue.clear()
        self._seen.clear()
        self._seen_order.clear()
        self._last_ms = None
        self._last_platform = None

    def ingest(self, candidate: ChatCandidate, *, now_ms: int) -> bool:
        if not isinstance(candidate, ChatCandidate) or type(now_ms) is not int or now_ms < 0:
            raise ValueError("Malformed chat observation")
        c = candidate
        valid = (
            isinstance(c.platform, str) and c.platform in PLATFORMS and isinstance(c.message_id, str)
            and bool(_ID.fullmatch(c.message_id)) and type(c.received_ms) is int
            and 0 <= now_ms - c.received_ms <= CHAT_TTL_MS and c.moderated is True
            and isinstance(c.text, str) and 1 <= len(c.text.strip()) <= 300
            and not any(ord(char) < 32 and char not in "\t\n" for char in c.text)
            and (c.platform, c.message_id) not in self._seen
        )
        if not valid:
            return False
        key = (c.platform, c.message_id)
        self._seen.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > 1024:
            self._seen.remove(self._seen_order.pop(0))
        if len(self._queue) >= MAX_CHAT_QUEUE:
            self._queue.pop(0)
        self._queue.append(c)
        return True

    def select(self, *, now_ms: int, mode: str, game_urgency: float = 0) -> ChatChoice | None:
        if type(now_ms) is not int or now_ms < 0 or not isinstance(mode, str) or mode not in MODES:
            raise ValueError("Invalid chat scheduler state")
        if not isinstance(game_urgency, (float, int)) or not 0 <= game_urgency <= 1:
            raise ValueError("Urgency must be 0..1")
        self._queue = [m for m in self._queue if 0 <= now_ms - m.received_ms <= CHAT_TTL_MS]
        if mode == "focus" or game_urgency >= 0.5 or (self._last_ms is not None
                                                       and now_ms - self._last_ms < CHAT_RESPONSE_COOLDOWN_MS):
            return None
        if not self._queue:
            return None
        # Prefer conversational questions, then another platform to avoid one
        # platform monopolizing replies; ties resolved by oldest received message.
        def score(c: ChatCandidate) -> tuple[int, int, int]:
            return (1 if "?" in c.text else 0,
                    1 if c.platform != self._last_platform else 0, -c.received_ms)
        index = max(range(len(self._queue)), key=lambda i: score(self._queue[i]))
        candidate = self._queue.pop(index)
        self._last_ms = now_ms
        self._last_platform = candidate.platform
        return ChatChoice(candidate.platform, candidate.message_id, candidate.text.strip())

    def queued(self) -> int:
        return len(self._queue)


@dataclass(frozen=True)
class PlatformScene:
    """One stream output's PUBLIC overlay configuration, not credentials."""
    platform: str
    visible_chat_platforms: tuple[str, ...] = ()
    shows_external_redirect: bool = False


def validate_scenes(scenes: tuple[PlatformScene, ...]) -> None:
    """Hard-block unsafe cross-platform overlays in a Twitch-visible output.

    Platform ToS is broader and may change: this check is necessary but not
    sufficient for policy compliance or broadcasting authorization.
    """
    if not scenes:
        raise ValueError("Select at least one platform output")
    seen: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, PlatformScene) or not isinstance(scene.platform, str) or scene.platform not in PLATFORMS:
            raise ValueError("Unknown streaming output")
        if scene.platform in seen:
            raise ValueError("Duplicate output")
        seen.add(scene.platform)
        if any(p not in PLATFORMS for p in scene.visible_chat_platforms):
            raise ValueError("Unknown visible chat source")
        if scene.platform == "twitch":
            if any(p != "twitch" for p in scene.visible_chat_platforms):
                raise ValueError("Twitch output cannot show other platforms' chat")
            if scene.shows_external_redirect:
                raise ValueError("Twitch output cannot redirect to concurrent streams")


class BroadcastPlan:
    """Owner-reviewed intent only, deliberately no OBS or network implementation.

    Security boundary: owner_confirmed must be supplied by a trusted local UI
    after actual authentication, not by a model, chat message or game event.
    The host must ALSO verify OBS output, credentials, policies and preflight.
    """
    def __init__(self) -> None:
        self.state = "offline"
        self.scenes: tuple[PlatformScene, ...] = ()
        self._preflight = False

    def preview(self, scenes: tuple[PlatformScene, ...], *, owner_confirmed: bool) -> None:
        if owner_confirmed is not True:
            raise PermissionError("Preview needs owner confirmation")
        if self.state != "offline":
            raise ValueError("Broadcast must be offline before preview")
        validate_scenes(scenes)
        self.scenes = scenes
        self.state = "preview"
        self._preflight = False

    def mark_preflight(self, *, host_verified: bool, owner_confirmed: bool) -> None:
        if self.state != "preview" or host_verified is not True or owner_confirmed is not True:
            raise PermissionError("Real host preflight and owner confirmation required")
        self._preflight = True

    def authorize_live_intent(self, *, owner_confirmed: bool) -> None:
        if owner_confirmed is not True or self.state != "preview" or not self._preflight:
            raise PermissionError("Explicit owner go-live approval after preflight required")
        self.state = "live_intent"
        # This records ONLY an authorization intent. It cannot start OBS.

    def stop(self) -> None:
        self.state = "offline"
        self.scenes = ()
        self._preflight = False


@dataclass(frozen=True)
class StoryFact:
    """Fiction stays labeled as fiction; lived events need verified evidence."""
    text: str
    kind: str
    approved_by_owner: bool
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in {"fiction", "observed"} \
                or not isinstance(self.text, str) or not 1 <= len(self.text.strip()) <= 700 \
                or self.approved_by_owner is not True:
            raise ValueError("Story requires approved bounded content and an explicit kind")
        if self.kind == "observed":
            if not isinstance(self.evidence_id, str) or not _ID.fullmatch(self.evidence_id):
                raise ValueError("An observed story requires independent verified evidence")
        elif self.evidence_id:
            raise ValueError("Fiction must not masquerade as observed-event evidence")

    def labeled(self) -> str:
        return ("Fictional Observatory lore: " if self.kind == "fiction"
                else "Previously verified stream event: ") + self.text.strip()
