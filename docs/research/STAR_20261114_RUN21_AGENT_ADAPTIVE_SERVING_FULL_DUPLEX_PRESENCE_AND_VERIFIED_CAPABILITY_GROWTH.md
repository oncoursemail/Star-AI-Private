# STAR Run 21 — Agent-Adaptive Serving, Full-Duplex Presence & Verified Capability Growth

**Research date:** 2026-11-14  
**Target branch:** `feat/resource-admission-20261113-run21`  
**Scope:** inference efficiency, real-time voice, multi-person streaming, temporal audiovisual grounding, gameplay learning, creator workflows, general knowledge, and runtime reliability.

## Executive decision

STAR's next major improvement should be **better coordination and better evidence**, not another large model or another independent scheduler.

The repository already has important foundations: a lease-based resource planner, stream-pressure governance, a bounded room host, a natural streaming persona, a sealed-holdout skill-evolution lab, a Roblox Studio benchmark, and a deterministic general-foundation checker. Run 21 therefore does not add a competing scheduler or duplicate memory/room authority.

This run adds:
1. A research-backed design for agent-aware inference and KV-cache retention.
2. A full-duplex interaction architecture with one causal timeline shared by audio, chat, game events, background tasks, and avatar playback.
3. A measured path to multi-speaker diarization and temporally grounded audiovisual understanding.
4. A transfer-safe plan for gameplay and game-creation learning.
5. An actual runtime observability improvement: aggregate PortAudio input/output health counters, exposed through `voiceStatus.audioDiagnostics`, with deterministic callback tests.

No model weights, external streaming credentials, platform integrations, model-routing defaults, or hardware settings are installed or changed in this run.

## Repository facts and architecture boundaries

The current development stack already includes:

- `star/resource_planner_service.py` and the lease-based resource admission work in PRs #1140/#1142 as the intended single admission path.
- `star/voice/room_host.py` as the trusted, opt-in ingress for final classified audio/chat/game cues. It applies source consent, bounded payloads, deduplication, rate limits, and mandatory chat moderation.
- `star/voice/persona.py` as the character/delivery layer. The room director and host—not the prompt—decide whether STAR has the floor.
- `star/skill_evolution_lab.py` with frozen candidate selection and sealed holdout evaluation.
- `benchmarks/roblox` with 20 real-Studio-checked tasks.
- `docs/GENERAL_KNOWLEDGE_BENCHMARK.md` with ten authored foundation tasks. That checker is not a broad general-intelligence benchmark and does not itself call a model.

The current voice ASR interface remains one-shot `transcribe(pcm)`. Partial previews can repeatedly process growing audio snapshots; they are not yet a persistent incremental streaming-ASR session. `first_audio_at` currently means audio was handed to the local speaker queue, not confirmed audible to a viewer or through OBS.

These facts define the next integration boundaries. New diarization, ASR, screen/game observers, Twitch/YouTube, OBS, and VTube Studio integrations must be adapters that submit authenticated, bounded, provenance-bearing events to the existing host. They must not become parallel floor-control, scheduling, or permission authorities.

## 1. Evolving Infra: agent-aware inference and cache management

### Research

**Evolving Infra: Agent-Adaptive LLM Serving at Scale** (arXiv:2611.12304, submitted 2026-11-09) studies dynamic agent workloads. It separates compute allocation from KV-cache management, predicts prefill/decode demand, and uses agent context-management signals to decide which KV entries should be retained, transferred, or evicted. The paper reports up to 4.1x lower mean end-to-end latency and 14x lower P95 TTFT than Dynamo in its evaluated cluster, using up to 256 GB300 GPUs.

The important insight is not the headline speedup. It is that **cache value depends on whether an agent branch will reuse the context**, not merely on how recently the cache entry was used. A finished sub-agent, a compacted history, and an active branch have different future reuse probabilities.

Sources:
- https://arxiv.org/abs/2611.12304
- https://github.com/mit-han-lab/EvolvingInfra

### STAR adaptation

STAR's local PC is not a 256-GB300 cluster. Do not copy Evolving Infra's prefill/decode disaggregation, cluster planner, or speedup claims into the local 8 GB GPU deployment.

Adapt only the signals and policies that fit the existing resource planner:

1. Label requests by task class, model/backend, prompt length, expected output range, and interaction priority.
2. Record actual prompt tokens, output tokens, TTFT, inter-token latency, queue wait, peak VRAM/RAM, and cache hit/miss data when the backend exposes them.
3. Link each cached context to a live task/agent branch and its compaction/replacement lifecycle.
4. Prefer retaining prefixes for active interactive conversations and live task branches over completed or superseded branches.
5. When the backend cannot expose cache residency, mark it unknown; do not fabricate a hit-rate estimate.
6. Feed calibrated demand estimates to the existing lease/admission controller as hints. Hard resource ceilings and interactive reserves remain authoritative.
7. Pause background work only at safe task/turn checkpoints. Never suspend an audio callback, partially applied file write, or external action in flight.

### Acceptance

Replay the same mixed workload against the current static policy and the candidate policy. Compare p50/p95/p99 TTFT, end-to-end latency, inter-token latency, cache reuse, queue wait, starvation, task success, CPU/RAM/VRAM, and recovery after bursts. Reject any policy that improves average latency while worsening p99, starvation, or interactive success.

## 2. FlashOffloading: when RAM offload helps—and when it hurts

### Research

**FlashOffloading** (arXiv:2611.07542, submitted 2026-11-05) explores host-DRAM-centric KV-cache offload, rolling GPU caches, sparse indexing, and overlap of data transfer with compute. Its reported end-to-end results use GLM-5.2 with speculative decoding on a multi-server Ascend910C prefill/decode cluster.

The paper explicitly identifies the tradeoff: host DRAM can free scarce accelerator memory, but host-to-device transfer and cache management can increase latency. Its published throughput gains are specific to the tested Ascend hardware and cluster topology.

Source: https://arxiv.org/abs/2611.07542

### STAR adaptation

For an 8 GB RTX-class GPU, treat CPU/RAM offload as a capacity technique, not an automatic speed optimization.

Benchmark, on the exact STAR model/backend:
- GPU-resident KV cache.
- CPU/DRAM offload.
- Short versus long contexts.
- Cold versus warm prefixes.
- One interactive request plus queued background work.
- Repeated turns that reuse a prefix.
- Contexts that are immediately discarded after a tool result.

Do not put SSD/NVMe KV offload on the live speech path until it proves a p95/p99 benefit under realistic stream load. Prefer prompt-prefix stability, bounded context, quantized weights, and low-concurrency interactive admission before adding storage tiers.

## 3. Realtime-Venus: full-duplex conversation plus asynchronous delegation

### Research

**Realtime-Venus** (arXiv:2609.13814, September 2026) combines two 9B conversational frontends—an audio-visual model and an audio model—with a shared causal timeline and an asynchronous task harness. The foreground conversation continues while delegated reasoning/tool tasks run, and the frontend decides when a prepared result should be spoken. The official source repository is Apache-2.0 except for separately noticed assets/components.

Sources:
- https://arxiv.org/abs/2609.13814
- https://github.com/inclusionAI/Realtime-Venus
- https://realtime-venus.github.io/

### STAR adaptation

The architecture is valuable; the 9B checkpoints are not a sensible default on an 8 GB GPU. Do not install both models or assume their benchmark results transfer to STAR.

Use the design pattern:

- **Foreground interaction:** low-latency audio events, current speaker/addressee, current game event, room floor control, TTS and avatar playback.
- **Background delegation:** research, long reasoning, game planning, code generation, asset creation, and skill analysis.
- **Shared causal timeline:** every event has a monotonic timestamp, source, session/turn ID, provenance, confidence, and expiry.
- **Return-to-conversation:** a background result is prepared with the original request/context ID; the room director decides whether it is still relevant and whether STAR has the floor.

A result that arrives after the game state, viewer question, or conversation has changed must be revalidated or discarded. The task harness must not speak directly or bypass the room director.

For long streams, store selected frames/events by scene change, novelty, HUD/objective change, and explicit interaction—not every frame. Keep raw video/audio transient unless the owner has explicitly enabled a retention feature with a clear purpose and retention period.

## 4. Nemotron 3 Diarization: a promising speaker-separation candidate

### Research

NVIDIA's **Nemotron 3 Diarization** paper (submitted 2026-11-09) extends streaming Sortformer to up to eight speakers. It describes 80 ms internal representations with 10 ms output resolution and an arrival-order speaker cache that carries speaker tracks across chunks. The paper reports improved accuracy/efficiency over its predecessor; the NVIDIA model card identifies the OpenMDW-1.1 license and provides a 199 MB checkpoint.

Sources:
- https://arxiv.org/abs/2611.12246
- https://huggingface.co/nvidia/Nemotron-3-Diarization

### STAR adaptation

This is a benchmark candidate, not an automatic dependency. Compare it with the current room pipeline on:
- CPU-only and GPU mixed-load inference.
- Warm-up and chunk look-ahead.
- Speaker changes and overlapping speech.
- False/phantom speakers.
- Short acknowledgements and background speech.
- Identity stability across reconnects.
- Memory footprint and CPU thread contention with the game/voice runtime.

Diarization answers **which temporary acoustic stream** a segment belongs to. It does not identify a real person, prove that the person is addressing STAR, or authorize a response. Keep opaque session-scoped speaker IDs; never infer or persist real-world identity from voice.

## 5. SONIC-O1: temporal audiovisual grounding, not just transcript understanding

### Research

SONIC-O1 was accepted to EMNLP 2026. Its evaluation spans 231 videos (~60 hours), 4,958 human-verified questions, and 13 conversational domains. It separates long-form summarization, evidence-grounded question answering, and temporal event localization. Its findings show that identifying what happened is easier than locating exactly when it happened.

Sources:
- https://aclanthology.org/2026.emnlp-main.767/
- https://github.com/VectorInstitute/sonic-o1
- https://huggingface.co/datasets/vector-institute/sonic-o1

**License boundary:** the dataset uses the Vector Institute License and is restricted to academic non-commercial research and Vector Institute sponsors/partners. Do not bundle it into STAR, use it for commercial training, or assume the repository code license grants dataset rights. Use the task taxonomy to create an owner-controlled, consented, separately licensed STAR evaluation set.

### STAR adaptation

For a stream, test whether STAR can:
- Summarize a 10–30 minute session without inventing events.
- Locate a game event within a time interval.
- Distinguish an event before/after a viewer comment.
- Link a response to the actual speaker and game state.
- Say “I don't have enough evidence” when the relevant frame/audio was not observed.

Record event start/end timestamps, evidence references, source confidence, and whether the event was directly observed or inferred. Do not store raw viewer audio/video by default.

## 6. Natural VTuber presence: a measurable interaction contract

Human-like streaming should mean **natural timing, social awareness, continuity, expressive delivery, and reliable grounding**—not fabricated human biography or pretending to have experiences or senses that the host did not provide.

Build on the existing persona and room director:

- Use a local end-of-turn detector plus semantic evidence; measure false endpoint and late endpoint separately.
- Distinguish backchannels, other-directed speech, background speech, direct address, explicit questions, and human resolution.
- Keep the floor-control decision separate from language generation.
- Allow natural silence and short acknowledgements; do not narrate every game frame.
- Cancel the exact response generation when interrupted or when another person resolves its exact question.
- Synchronize mouth movement/captions to actual playback events, not merely generated text.
- Map game events to bounded expression cues (surprise, concentration, joy, disappointment) and allow the avatar to return to idle smoothly.
- Keep persona style stable across sessions without inventing human life events or viewer relationships.

### New long-session acceptance suite

Create consented owner-authored recordings with 2–4 speakers and cover:
- Explicit and implicit addressing.
- Viewer-to-viewer conversation.
- Backchannels while STAR speaks.
- Overlapping speech.
- False interruptions.
- A human resolving STAR's question.
- A viewer changing the subject.
- Game sounds without speech.
- Chat and audio arriving in different orders.
- A 20+ turn conversation with follow-up references.

Measure comprehension, correct speaker attribution, addressee precision/recall, answer accuracy, appropriate silence, interruption recovery, client-heard latency, and groundedness. A model that responds quickly but speaks at the wrong time is not a better streamer.

## 7. Roblox and game creation: plan/build/test with real environment feedback

Roblox's official agentic Studio workflow exposes a built-in MCP server and playtesting support. The Studio workflow is designed around project inspection, a reviewable plan, edits, playtests, logs, and visual feedback.

Sources:
- https://create.roblox.com/docs/ai/accelerated-workflows
- https://create.roblox.com/docs/studio/mcp
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

### STAR Creator acceptance loop

1. Inspect the current DataModel, scripts, assets, and project conventions.
2. Create a bounded task plan and acceptance criteria.
3. Edit a disposable/test copy or explicitly selected test place.
4. Run Luau analysis and static checks.
5. Execute in Studio's correct Edit/Client/Server context.
6. Start a playtest and simulate the required player input.
7. Capture console output, state, and viewport evidence.
8. Compare behavior and visuals to the acceptance criteria.
9. Repair one defect class at a time.
10. Re-run the original and regression scenarios.

For game agents, separate reflex control from tactical and strategic planning. Each action needs a recent observation ID and expiry. Reject an action if the game state changed, the player died/respawned, the objective changed, or its observation is stale.

### GameDevBench version discrepancy

The current repository README reports 333 tasks, while the canonical ICML paper page currently describes a 132-task benchmark. Treat these as different snapshots/definitions until the task manifest and commit history are reconciled. Every STAR comparison must pin the repository commit, task manifest hash, Godot version, harness, and evaluation flags. Do not quote a task count or leaderboard score without those pins.

Source pages:
- https://github.com/waynchi/gamedevbench
- https://sethkarten.ai/papers/gamedevbench.html

## 8. Continual learning and agentic evolution

A-Evolve's work on agentic evolution demonstrates an open infrastructure for proposing changes to an agent harness and evaluating evolved variants across benchmarks. Its public leaderboard figures are project-reported and should not be treated as independent proof that every evolution strategy generalizes.

Sources:
- https://arxiv.org/abs/2602.00359
- https://github.com/A-EVO-Lab/a-evolve

### STAR adaptation

Use the idea of a repeatable evolution cycle, but retain STAR's stricter safety and holdout boundaries:

1. Freeze the baseline and its environment.
2. Generate one bounded candidate change in an isolated workspace.
3. Run deterministic unit/integration tests.
4. Run a public development suite.
5. Freeze candidate selection.
6. Run sealed holdouts that the proposer cannot inspect.
7. Measure cross-task and cross-game transfer.
8. Inspect semantic diffs, dependencies, permissions, and side effects.
9. Promote only if the candidate improves the target metric without regressions.
10. Keep rollback and a signed/provenance-bearing experiment record.

Never allow an optimizer to modify its own grader, read sealed expected outputs, promote its own candidate, rewrite production policy live, or access external credentials. Runtime policy evolution should run in shadow mode first and require explicit approval before changing production scheduling or permissions.

## 9. General knowledge: separate knowledge, reasoning, and execution

STAR's current ten-task general-foundation checker is a useful deterministic regression suite, not a measure of broad general intelligence.

Expand the evaluation into separate tracks:

| Track | What to measure |
|---|---|
| Knowledge | Source quality, date validity, contradiction detection, provenance |
| Reasoning | Multi-step correctness, assumptions, counterexamples, uncertainty |
| Execution | Whether STAR can actually perform the task in a sandbox |
| Transfer | Whether a learned procedure works on a new task/environment |
| Retention | Whether useful knowledge survives compaction and later sessions |
| Calibration | Whether confidence tracks actual correctness |

Every durable knowledge item should retain source, retrieval date, claim, validity interval, confidence, contradiction status, and supersession link. A fluent explanation is not proof of execution skill.

## 10. Actual runtime improvement in this run: audio-device health counters

The real PortAudio adapters previously exposed no aggregate driver-underflow/overflow counters. That made it difficult to distinguish model/TTS delay from audio-device problems.

Run 21 adds:

- Microphone: input overflow, input underflow, bounded Python queue drops, and queued-frame count.
- Speaker: output underflow, output overflow, queued seconds, played seconds, and sample rate.
- `voiceStatus.audioDiagnostics`: separate microphone and speaker diagnostic objects.
- Deterministic callback tests using synthetic PortAudio status flags; no physical microphone/speaker or sounddevice import is required by the tests.

The counters are aggregate only. They do not retain audio, transcripts, device names, or viewer identities. They do not change audio buffering, queue policy, device selection, model scheduling, or production defaults.

**Interpretation:** PortAudio output-underflow flags are a local device health signal. They do not prove that OBS, a stream encoder, or a remote viewer received or heard the audio. The next observability layer should separately measure playback start/end and, where available, OBS/encoder output timing.

## 11. Mixed-load performance experiment

Use a fixed, reproducible 30-minute workload with:
- One active voice interaction.
- Two to four simulated chat speakers.
- One game capture stream at a pinned frame rate.
- One low-priority research task.
- One bounded creator/build task.
- A fixed model, backend, quantization, context limit, and warm/cold cache protocol.

Record:
- TTFT p50/p95/p99.
- Inter-token latency/TPOT p50/p95/p99.
- Time from final transcript to first audio enqueue.
- Local playback start and completion.
- PortAudio input/output underflows and queue drops.
- OBS skipped frames and render lag when OBS is connected.
- Game frame-time p50/p95/p99.
- CPU, RAM, VRAM, and model-server queue depth.
- Task completion and correctness.
- Background-task starvation and recovery after a synthetic burst.

Compare one change at a time. Preserve an interactive resource reserve. Reject a speed optimization if it causes audio underruns, game stutter, unsafe concurrency, lower answer quality, or unfair starvation.

## 12. Prioritized implementation roadmap

| Priority | Work item | Gate |
|---|---|---|
| P0 | Run exact-head CI for device diagnostics | Linux + Windows test suites pass |
| P1 | Add playback-start and playback-end acknowledgements | Fake speaker tests, then physical device test |
| P1 | Persistent streaming ASR session interface | Chunked audio, cancellation, bounded queues, final transcript authority |
| P1 | Streaming diarization adapter benchmark | CPU/GPU RTF, DER, speaker switches, memory |
| P1 | Shared causal event timeline | Monotonic timestamps, provenance, stale-event rejection |
| P2 | Full-duplex Social Director evaluation | 2–4 speakers, 20+ turns, silence/interrupt accuracy |
| P2 | Agent-aware KV/task retention hints | Matched mixed-load benchmark; existing planner remains authority |
| P2 | Roblox MCP Creator integration | Real Studio test place, playtest and visual evidence |
| P2 | Gamer reflex/tactical/strategic controller | Held-out maps, action freshness and task success |
| P3 | Cross-task skill transfer suite | Sealed holdout and rollback |
| P3 | General knowledge/temporal grounding suite | Source-backed answers and execution checks |

## Explicit non-claims

- No 4.1x/14x Evolving Infra speedup is claimed for STAR's local GPU.
- No FlashOffloading speedup is claimed for RTX hardware.
- Realtime-Venus 9B checkpoints were not installed.
- Nemotron 3 Diarization was not installed or benchmarked on STAR hardware.
- SONIC-O1 restricted dataset files were not downloaded or bundled.
- No Twitch/YouTube OAuth, OBS, or VTube Studio integration was connected.
- No real microphone, physical speaker, RTX 4060, OBS, gameplay, or livestream hardware test was run.
- The new audio counters establish instrumentation behavior under synthetic callback tests, not production audio quality.

**Run 21 decision:** keep one resource planner, one room/floor authority, one skill-promotion gate, and one event timeline. Improve the signals and tests around those existing systems before introducing another large model or agent framework.
