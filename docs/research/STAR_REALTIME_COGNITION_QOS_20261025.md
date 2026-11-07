# STAR realtime cognition, games and VTuber infrastructure — 2026-10-25

**Status:** engineering research and a tested, opt-in control primitive. **Not:** a trained model, real game agent, working OBS/TTS/Live2D integration, evidence of faster model inference, or permission to broadcast.

## Repository fit and overlap audit

At inspected `star/next` commit `79268ce0e6749856371e2506a3eb61434d9fa703`, STAR already contains `agent_resource_planner.py` and `resource_planner_service.py` (cross-machine job admission), `playtest_learning.py` and `selfplay_curriculum.py` (guarded Roblox Studio testing), `cascade_router.py` (offline model routing analysis), `general_knowledge_benchmark.py`, and voice/video modules. Do not replace these.

Unmerged proposals as of this inspection: **#579** game experience/video/knowledge; **#580** streamer director and measured gameplay gate; **#581** stream director, camera-observation admission, motion/latency; **#582** VTuber asset production; **#586** adaptive verified-learning priorities. Reconcile them rather than implementing duplicate models. This patch adds a **different missing layer**: a tiny, deterministic, bounded signal inbox plus one-time playback tickets, designed to sit *between* event producers/stream planner and downstream media adapters. It has no side effects, and it is OFF by default.

## 1. Why realtime systems feel more human

A convincing VTuber isn't a chat-bot that simply talks more. A streamer needs to (a) notice the game before the moment is gone, (b) prioritize owner speech over routine viewer comments, (c) allow quiet concentration and occasional conversational backchannels, (d) speak about what is *currently observable*, and (e) cancel *all pending* voice, subtitles and facial animation after a real interruption. Past-tense reactions delivered late are often worse than silence. Do not falsely claim Star has childhood memories or human experiences; make an explicitly AI character with a consistent fictional persona and genuine, sourced in-game experiences.

**Architecture:** authorized game capture → source-specific adapters that remove raw private content → fast event classifier + timestamps → `LiveInbox` (admission, deadlines, coalescing, fairness) → #581 stream director (intents) → fast speech / deeper background thinking → host-controlled TTS, caption and avatar channels → per-chunk `PlaybackGate.allows(ticket)` → OBS/VTube Studio. Untrusted chat and visual text are data, not privileged instructions. The same current-ticket check must apply to every output mode, even when a model call finishes after an interruption. Explicit owner permission and host-side process isolation are required.

LiveKit's turn-handling documentation provides concrete mechanisms for adaptive interruption, false interruptions and preemptive generation; its defaults and billing differ by deployment, so benchmark before choosing. NVIDIA's PersonaPlex (January 2026) investigates personalized full-duplex conversation; DyaPlex (June 2026) jointly generates speech and coordinated body motion. These are research candidates, **not** evidence they will run well on an 8 GB gaming GPU. The existing #581 audio-mouth/secondary-motion plan can consume explicit playback timing, but does not yet animate a production avatar.

## 2. The implemented realtime control contract

`star/realtime_signal.py` contains pure-Python `Signal`, `LiveInbox`, `PlaybackTicket`, and `PlaybackGate` with no external dependencies.

- `Signal` carries **opaque IDs only**, its lane, monotonic observation and expiry timestamps. No screenshots, viewer names, chat messages, audio or secrets live in queue records.
- `LiveInbox(enabled=False)` rejects all signals until explicitly enabled by a trusted, user-approved host. Max-capacity 1–256; lane limits, expiration, key-based coalescing, atomic replacement, fair access to chat after a configurable burst of ordinary gameplay events, and strict owner/urgent-game precedence. Lower-priority events cannot evict urgent ones; vision and background chatter may be intentionally dropped to preserve freshness. It reports **counts only**.
- `PlaybackGate(enabled=False)` issues session-bound, generation-bound expiring tickets. Calling `interrupt`, `begin_turn`, `close_session`, or `disable` revokes earlier tickets. Audio, captions, gesture and lipsync adapters must ask `allows` immediately **before each output chunk**. These checks cannot forcibly rewind media already handed to a third party.
- All times are supplied monotonic milliseconds from a **single trusted clock domain**; sensors on different computers need timestamp translation at the receiving host. Never use raw wall-clock timestamps without mapping them. Call methods sequentially in the event loop (the class is not thread-safe). Neither class authenticates callers or establishes permissions.

Example, deliberately non-broadcasting:

```python
from star.realtime_signal import LiveInbox, PlaybackGate, Signal

inbox = LiveInbox(enabled=True)  # Trusted host only, after owner opt-in.
inbox.offer(Signal("hazard-1", "urgent_game", 1_000, 1_300, "cue-11"), now_ms=1_020)
candidate = inbox.take(now_ms=1_030)  # Could feed #581's event planner.

gate = PlaybackGate(enabled=True)  # A second explicit host consent boundary.
gate.open_session("private-rehearsal")
ticket = gate.begin_turn(now_ms=1_030, ttl_ms=2_000)
assert candidate is not None and gate.allows(ticket, now_ms=1_040)
gate.interrupt()  # Owner or gameplay preemption; adapters drop stale output.
assert not gate.allows(ticket, now_ms=1_041)
```

The sample **simulates** signals and decisions; it neither sees the screen nor speaks or streams. Unit tests cover opt-in, expiry, dedup/coalescing, priority, pressure, chat fairness, out-of-order events, and interruption/session replay.

## 3. Better gameplay, not just reactions

**Observe:** capture permitted game frames/audio at adaptive rates; infer controls, maps, objectives, hazards, physics and failure causes. Use a small, fast perception model for immediate cues and a stronger model for strategic decisions in spare capacity. Don't try to run a giant vision-language model every 16 ms; choose high-information keyframes and detect changed regions. Any model of state must keep uncertainty explicit.

**Plan:** maintain `(game, scenario, controls, goal, checkpoint, evidence)` state and short-horizon goals with a reversible action budget. Prefer game-authorized APIs, test environments and Studio's guarded MCP playtesting; do **not** bypass anti-cheat or game access controls. A screenshot alone is not a verified kill, checkpoint or win. Require corroboration from game events or an independent referee.

**Act and learn:** compare attempted action versus observed consequences, store only bounded evidence-backed candidate strategies, and retest the same task on fresh *held-out* maps. The frontier pattern: Voyager's curriculum and reusable skill library, DreamerV3's world-model rollouts, and SIMA 2's cross-game instruction following. These architectures are research directions, not drop-in locally runnable intelligence boosters. Treat any self-scored performance as a candidate until independently verified. Avoid contamination of test/eval sets and preserve the existing `star/selfplay_curriculum.py` permission gates.

**Create:** a game-building skill should carry explicit spatial constraints, colliders/anchors and geometry checks, UI pixel-safe layouts, animation timing, asset licenses, *and* actual Studio run evidence. For Roblox, the built-in Studio MCP (March 2026) enables guarded build and playtest loops; April's Roblox announcement discusses the plan/build/test agent workflow. Block publishing until verified ownership and human review. Use image/video understanding as a critic, not as a substitute for actual engine tests.

**General knowledge:** prioritize a provenance graph: source URL, content hash, checked timestamp, scope, expiration/staleness, and conflict pairs. Search retrieval can provide new knowledge without claiming model weight changes; require source quotations to stay within licenses, cache only approved data, and use independent multi-domain evaluations rather than practice fixtures. Incorporate pending #579 general-knowledge lab instead of inventing a second one.

## 4. Performance strategy on the user's 8 GB class GPUs

1. **Measure first:** collect p50/p95/p99 time from game observation → intent → first audible output; monitor dropped/late cues, interruption-to-silence, avatar lip sync drift, game FPS and 1% lows. Compare identical test scenes and load, not abstract token/s claims.
2. **Separate priorities across machines:** reserve the interactive gaming GPU for game/OBS/avatar/frame capture; shift background research, training, embeddings and heavier deliberation to existing other brains *after resource-planner admission*. On one GPU, isolate TTS/vision/LLM allocations and watch OOM rate. Only if hardware observations justify it, experiment with persistent warmed models and dynamic batch/token ceilings.
3. **Reuse prefixes conservatively:** vLLM's automatic prefix caching accelerates reused **prefill**, not decoding; fixed persona and tool prefixes can help, but mixing viewer content into long shared prefixes risks undesirable cache lifetime/privacy issues. Test llama.cpp KV-cache quantization/CPU offload on exact hardware for first-audio latency, memory and answer quality; do not promise 2× speedups without real measurements.
4. **Avoid priority inversion:** background model calls cannot monopolize memory or block a pending owner interruption. Admission, bounded queues, expired cue dropping and ticket revocation do not make inference intrinsically faster; they target *perceived responsiveness and output correctness*.
5. **Real-time interfaces:** OBS includes authenticated obs-websocket in modern installs; VTube Studio exposes a documented plugin/API surface. Both integrations must be loopback-restricted when possible, with owner-held credentials and explicit start/stop buttons. No unattended broadcasting.

## 5. Reproducible acceptance tests, not promotional claims

- **Queue:** bounded size, zero output while disabled, expired vision never narrated, urgent gameplay before normal comments, late high-priority admission during backlog, atomic replacement, bounded counters, chat fairness after ordinary gameplay bursts.
- **Interruptions:** after owner barge-in, *zero* subsequent chunks from the old ticket (tested with fake adapters); session rollover cannot replay old captions or motions; false-positive VAD recovery requires separately verified context, never blindly resurrect old chunks.
- **Game learning:** baseline vs candidate on identical externally verified tasks, with same control budget. Record new-map and new-game heldout success rate, retries, stuck loops and FPS. No training claims from synthetic data or self-graded model text.
- **VTuber human factors:** blind viewer rating of timing, repetition, expressivity, appropriateness and conversational turn-taking; publish metrics for laughter appropriateness, long silences, speech overlapping hazards, mouth/audio alignment, and transparent AI disclosure.
- **Speed:** establish baseline on Brain 1/Brain 2/stream PC; report separate p50/p95 latency, tokens/s, memory, FPS and interruptions. Test for GPU OOM and graceful task deferral. The new queue's small unit tests are **not** native hardware benchmarks.
- **Deployment:** all new primitives remain opt-in and read-only. Merge requires CI and review; native OBS/Studio and avatar tests remain unperformed at this stage. No code here connects to model APIs, OBS, TTS or a game.

## Sources (original research / official docs)

- Google DeepMind, **SIMA 2** (December 2025): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/ ; paper https://arxiv.org/abs/2512.04797
- Google DeepMind, **Genie 3** (August 5, 2025): https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/
- Voyager, open-ended embodied agent (2023): https://arxiv.org/abs/2305.16291
- DreamerV3 official implementation/paper (2025): https://github.com/danijar/dreamerv3
- NVIDIA **PersonaPlex** (January 15, 2026): https://research.nvidia.com/labs/adlr/personaplex/
- NVIDIA **DyaPlex** (June 2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- LiveKit 2026 agent session, turn handling, interruptions: https://docs.livekit.io/agents/logic/sessions/ and https://docs.livekit.io/reference/agents/turn-handling-options/
- Roblox native Studio MCP / automatic playtests (March 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ; April 2026 announcement: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- OBS official WebSocket plugin: https://github.com/obsproject/obs-websocket
- VTube Studio official docs: https://denchisoft.com/documentation/
- vLLM automatic prefix caching: https://github.com/vllm-project/vllm/blob/main/docs/features/automatic_prefix_caching.md
- Python `asyncio.Queue` behavior / backpressure: https://docs.python.org/3.12/library/asyncio-queue.html
