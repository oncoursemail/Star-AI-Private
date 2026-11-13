"""STAR voice calls: listen, think, speak, and stop talking when interrupted.

Core (pure Python, always importable): chunker, turn, call, metrics, persona, brain, pcm.
Engines and audio devices (optional dependencies from requirements-voice.txt): engines, devices.
File-driven test mode and the command line: filecall, `python -m star.voice`.
See docs/STAR_VOICE_CALLS.md.
"""
from .call import CallConfig, CallSession
from .chunker import SentenceChunker, speakable
from .metrics import TurnMetrics, latency_table
from .room_payloads import (
    RoomPayload,
    RoomPayloadKind,
    RoomPayloadStore,
    RoomPayloadStoreConfig,
    RoomPayloadStoreResult,
    RoomPayloadStoreStats,
)
from .room_queue import RoomCueQueue, RoomQueueConfig, RoomQueueResult, RoomQueueStats
from .turn import EchoGate, TurnConfig, TurnDetector, TurnEvent

__all__ = [
    "CallConfig",
    "CallSession",
    "EchoGate",
    "SentenceChunker",
    "TurnConfig",
    "TurnDetector",
    "TurnEvent",
    "TurnMetrics",
    "latency_table",
    "speakable",
    "RoomCueQueue",
    "RoomQueueConfig",
    "RoomQueueResult",
    "RoomQueueStats",
    "RoomPayload",
    "RoomPayloadKind",
    "RoomPayloadStore",
    "RoomPayloadStoreConfig",
    "RoomPayloadStoreResult",
    "RoomPayloadStoreStats",
]
