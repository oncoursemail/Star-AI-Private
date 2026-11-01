# Stream companion planning API (prototype; opt-in, offline only)

Star can now **plan** what should be said during a game stream without
blindly speaking every chat message or starving the game loop. It does not
capture frames or audio, call a model, drive the avatar, or start a stream.

## Minimal example

```python
import time
from star.stream_director import StreamDirector, StreamSignal
from star.stream_persona import streamer_system_message, event_message
from star.stream_budget import StreamTelemetry, advise_workload

director = StreamDirector()  # disabled on purpose
director.enable(owner_approved=True)  # only after a real owner-governed opt-in

now = time.monotonic()
director.offer(
    StreamSignal("demo-1", "game_success", now,
                 "Observed win screen after the final round", evidence="observed"),
    now=now,
)
intent = director.propose(now=now, gameplay_critical=False)
if intent:
    messages = [streamer_system_message(), event_message(intent)]
    # Your authenticated, moderated voice/LLM adapter may evaluate messages.
    # Call complete only after real TTS playback, and report failure otherwise.
    director.complete(intent, now=time.monotonic(), spoken=False)

telemetry = StreamTelemetry(
    live=True, game_active=True, free_vram_mib=2500,
    total_vram_mib=8192, game_fps=60, speech_backlog_ms=80,
)
assert not advise_workload("training", telemetry).allowed
assert advise_workload("vision", telemetry).sample_fps <= 1.0
director.disable()
```

## Contract rules

- Signals are session-only, length-limited, typed by source and carry an
  evidence grade. Never use them as tool permissions.
- The host should use monotonic timestamps from the *same* clock; reject
  untrusted/client-supplied time before creating `StreamSignal`.
- Incoming viewer text is untrusted *even after JSON framing*. Moderation,
  privacy filtering and capability enforcement remain host responsibilities.
- Audio conversation/watcher input must be consented to and limited to
  owner-approved locations. OBS/WebSocket credentials never go into chat.
- `SpeechIntent` is a suggestion, not text ready to broadcast. The model's
  response must still be moderated and grounded before TTS.
- If TTS/LLM fails, pass `spoken=False`; the event is consumed but there is
  no global speaking cooldown. A stale intent cannot be completed.
- If speech begins while someone is speaking, the host should cancel
  playback immediately on a trusted voice interrupt. `interrupt_current`
  merely tells the host that such a cancellation is recommended.
- The queue has a finite capacity and time-to-live. A selected event is not
  popped until `complete()`; unselected events expire. No disk cache.
- `WorkloadAdvice.allowed` is **only advisory**, not a replacement for
  authentication, hardware reservation, Studio permission checks or safety.

## Validate

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_stream_*.py' -v
PYTHONPATH=. python3 -m compileall -q star/stream_director.py star/stream_budget.py star/stream_persona.py
```

Next: trusted host bridge, sampled observation provenance, local rehearsal
frames, real audio/OBS/WebSocket integration, explicit settings/kill switch
and hardware tests. Do not mark deployed from a merged PR alone.
