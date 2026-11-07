# STAR — guarded host dispatch, general intelligence, and VTuber system design

Research and implementation note · 2026-11-06 · owner-approved offline rehearsal

## Implemented in this branch

The existing `HostMonotonicGameProbe` supported opt-in frame queues and
`pre_submit_check()`, but checking an action and issuing that input were two
**separate host operations**. A race or mistaken integration could keep a stale
decision on the path to game input. This change adds:

- `guarded_dispatch(sequence, submit)`, an opt-in **synchronous callback
  wrapper** around the age check and a trusted host's actual submission callback.
- The probe takes its own monotonic timestamp immediately before the callback.
  If the decision is already stale, it refuses to call `submit` at all.
- It holds one state lock across the callback and the post-submit time sample.
  Reentrant probe mutation aborts the entire window; failed/aborted callbacks
  also revoke all prior successful evidence.
- A second age check after the callback detects slow host submissions.
  `action_ack()` is still separate and MUST come from the host, not the model.
- This is disabled unless `owner_approved=True` and
  `max_action_age_ns` is explicitly configured. Older integrations are
  unchanged; the two submission styles cannot be combined for a frame.
- The callback is dependency-injected: Star does not import a game automation
  tool, send keyboard input, bypass anti-cheat, connect to OBS, or broadcast.
- Tests use deterministic local clocks and fake callbacks. A private synthetic
  maze still provides rehearsal scoring, not proof of real-game control.

Example integration pseudocode, only for an authorized **private game host**:

```python
probe = HostMonotonicGameProbe(
    owner_approved=True,
    require_frame_opportunities=True,
    max_queue_wait_ns=30_000_000,
    max_action_age_ns=80_000_000,
)
offered = probe.frame_available()               # one per host-offered frame
seq = probe.capture(opportunity=offered)
# Host authenticates state and obtains a permissible action independently.
probe.decision_ready(seq)
probe.guarded_dispatch(seq, approved_host_submit) # callback performs ONE input
probe.action_ack(seq)                             # actual host ACK, not success
timings = probe.finalize()
```

**Limitations:** The host callback remains trusted and can block. If it spends
too long inside itself and *then* sends a stale input, the post-return check
will revoke evidence but cannot reverse the side effect. Holding an RLock does
not make an OS input operation transactional or remotely attested. To establish
real safety, the trusted host must enforce deadlines at its actual input
boundary and produce independently verified game-state transitions. No
inference speed-up or real gaming improvement is claimed for this branch.

## System design: a real-time Star must be THREE different loops

1. **Reflex loop:** ≤1 frame of on-device perception/control under load;
   avoids long language-model calls for hard deadlines; explicitly declines
   unsafe actions if confidence or freshness fails.
2. **Tactical loop:** seconds-level planning; selects goals, predicts changes,
   retrieves prior verified skills, updates plans on new authenticated events.
3. **Learning loop:** off-stream curriculum: novel games, failed-run analysis,
   self-generated test scenarios, replay, regression comparison, and bounded
   promotion of skills. It cannot update production controllers merely by
   declaring itself improved.

The separation prevents a slow strategy prompt from pausing motor control.
Realtime-Bench (October 15, 2026) reports at most 44% success in its
wall-clock setting for evaluated leading models; pausing game time can
overstate competence: https://arxiv.org/abs/2610.22155

### Proposed per-task evidence contract (NOT implemented here)

Store one local immutable receipt per action, binding game-instance identity,
session ID, frame digest, time-domain identity, controller version, action
classification, deadline, host ACK, and independently observed game-state
change. A claim such as `defeated boss` needs observed game state, not a model
message or input ACK. An offline evaluator checks provenance, objective
completion, collisions, latency distribution and surprise mechanics. Never
record private streams/chat/audio indiscriminately.

Use *two* trusted windows: the input freshness window and the world-state
observation freshness window. A legitimate input submission is not proof that
the game simulated or accepted it. Set explicit expiration for both.

## Inference/QoS research: speed is end-to-end

The user's 8 GB GPU can be overcommitted by game rendering, AI, compositor,
speech, avatar runtime and OBS. The real target is *correct decisions per
second under a stable game stream*, not isolated tokens/sec.

**Benchmark matrix** (all same prompts/models, warmed and cold runs):

| Setting | Monitor |
| --- | --- |
| CPU-only/low-VRAM speech vs GPU TTS | first audible chunk, clarity, CPU time, GPU headroom |
| single fast model vs planner+fast controller | objective completion, collisions, p50/p95 action age |
| n-gram speculative vs no speculation | actual acceptance, TTFT, tokens/s, VRAM and correctness |
| lower context vs retrieval-augmented smaller context | answer quality, cache partitioning, swap pressure |
| OBS+avatar+game+inference simultaneous | game 1% low FPS, OBS dropped/rendered frames, audio underruns |

llama.cpp implements speculative decoding, including draft-model and other
modes; effectiveness must be benchmarked, not assumed:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

SPEED-Bench provides an inference-serving comparison path:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Kyutai's Pocket TTS October 21, 2026 maintenance update includes fixes to
compact English voice configurations. Try short offline A/B rehearsals before
making it the default voice; smaller does not automatically mean humanlike:
https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.1

**Guardrails:** retain reserve VRAM for game and OBS, cap simultaneous
generation jobs, and degrade gracefully. Under pressure, drop decorative
commentary before input freshness, audio capture, and safe gameplay. Separate
stream-chat KV caches from other users; never cross-share private contexts.

## VTuber: humanlike behavior without presenting Star as a human

A convincing, clearly identified AI character is best achieved by *timing*
and persistent personality, not exaggerated synthetic emotion.

- **Listen and respond together:** local voice activity/barge-in cues, speech
  interruption, turn-taking, and brief listening acknowledgments.
- **Proactive restraint:** comment when funny/important events occur; be quiet
  during critical input windows; avoid narrating every small motion.
- **Grounded reactions:** surprise, relief, excitement and disappointment from
  witnessed events (kills, losses, discovery), not fictional experiences.
- **Consistency:** long-lived preferences, in-jokes, boundaries, episodic
  memories with retention control and explicit source-confidence metadata.
- **Expressive animation:** time-align phonemes and mouth shapes, blink/gaze,
  body/hand gestures, hair physics; default to lower animation fidelity when
  frame rate degrades.
- **Moderation / broadcast gates:** offline rehearsal by default; chat speech
  sanitization; no uncontrolled TTS of untrusted viewer input; emergency
  mute/pause, owner-defined safe mode, privacy-aware overlays.
- **Audience metrics:** meaningful replies, interruption recovery, percentage
  of commentary tied to a real event, first-audio latency, silence balance,
  stream stability and user-reported naturalness.

Proact-VL (March 3, 2026) researches *when* a gaming companion should speak,
not only *what* it should say:
https://arxiv.org/abs/2603.03447

NVIDIA DyaPlex (June 2026) investigates simultaneous listening, speaking,
partner motion perception, and synchronized expressive responses:
https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

## General intelligence, knowledge, and game creation

- **Knowledge:** versioned local reference bank with dated citations, tests
  of source freshness, confidence and contradiction detection. For unfamiliar
  skills, Star should say unknown, research with opt-in web access, then verify
  with a task—not pretend to have experience.
- **Games:** curriculum from deterministic synthetic obstacles through
  authorized single-player games, randomized maps and unfamiliar mechanics.
  Promotion requires held-out tasks; compare paired seeds, success, collisions,
  recovery, and *actual elapsed decision time*.
- **Roblox creation:** model a task as inspect → design → edit in isolated
  Studio instance → run Luau analysis / playtest → check output/visuals →
  repair → reviewer gate. Ensure the correct `studio_id` for multi-Studio.
  Roblox's official MCP docs describe multi-instance support:
  https://create.roblox.com/docs/studio/mcp
- **Live cloud risk:** Studio MCP Open Cloud permissions are enforced per game;
  some datastore writes affect real players. Do NOT enable these capabilities
  by default or use production data to practice:
  https://create.roblox.com/docs/studio/mcp-open-cloud
- **Self-improvement:** tests and observable task outcomes supersede
  self-reported confidence. Maintain an offline rollback point, diff
  explanation, benchmark budget and host audit before experiments are promoted.

## Recommended milestones (sequenced by evidence, not feature count)

1. **This PR:** host callback guard; synthetic clocks and local callbacks;
   measure failure, not only success. Document unable-to-undo limitation.
2. **Next:** trusted *private* Windows host adapter with per-frame identity,
   actual input-edge deadline enforcement, explicit abort and observed action
   consequences. No public multiplayer automation or broadcast at first.
3. **Then:** OBS + avatar + speech + game rehearsal with GPU headroom budgeting,
   speech interruptions, lost-frame telemetry and timestamp-correlated traces.
   Keep OBS WebSocket authenticated, and never embed passwords in logs:
   https://github.com/obsproject/obs-websocket
4. **Then:** progressively harder verified game curricula and Roblox Studio
   build/playtest/repair benchmarks with independent scoring and rollback.

## Reproducibility

Execute locally with existing development dependencies (no model downloads):

```sh
python -m pytest -q tests/test_host_guarded_dispatch.py \
  tests/test_host_action_freshness_gate.py tests/test_host_monotonic_game_probe.py
python -m ruff check star/host_monotonic_game_probe.py \
  tests/test_host_guarded_dispatch.py
```

These offline tests cannot certify a Windows driver, game authenticity,
real streaming performance, full-duplex speech quality, or sent-input timing.
