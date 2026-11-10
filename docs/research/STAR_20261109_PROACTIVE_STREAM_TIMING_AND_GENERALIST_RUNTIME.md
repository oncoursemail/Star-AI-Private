# STAR — Proactive VTuber timing, real-time intelligence, and performance roadmap

**Research date:** 2026-11-09  
**Implementation branch:** `feat/star-stream-response-eval-20261109-auto193`  
**Scope:** local-first inference, live gaming, interactive streaming, game learning, Roblox creation, and privacy-safe evaluation.  
**Status:** one offline response-timing evaluator is implemented and tested; native Windows audio/avatar wiring and hardware performance experiments remain future work.

## Executive finding

The most important gap in a natural AI streamer is not simply response speed. It is deciding **whether to respond, which modality to use, and when the response is still relevant**.

A fast but premature comment is disruptive. A correct comment delivered after a round has changed is stale. A system that speaks continuously may have low latency but poor conversational judgment. A nonverbal acknowledgement can be better than speech while another person owns the floor. Silence can be the correct outcome.

This update adds an offline evaluator for those decisions. It measures independently labeled event windows against host-observed decision and output timestamps. It reports response precision/recall, silence precision/recall, early/late outputs, duplicate outputs, grounding failures, separate audio/avatar latency percentiles, and an event-kind breakdown.

The evaluator is deliberately not an execution authority. It cannot start TTS, inject avatar parameters, control OBS, press game keys, or broadcast.

## 1. New research: proactive interaction must score silence as well as speech

### ProactiveBench (arXiv:2609.12658)

The paper *ProactiveBench: Can Streaming Video Models Really Interact Like Humans?* evaluates a model at one-second intervals under a standing request. It distinguishes early, in-window, missed, and duplicate responses, and combines response and silence behavior rather than rewarding a model merely for staying quiet.

Its key lesson for Star is that timestamp-selected question answering misses a major part of live interaction: deciding when the event has happened and when it has not happened yet.

**Engineering implication:** Star needs an event window, a deadline, a response modality, and a measurable silence outcome for every annotated event. The new evaluator models those fields without retaining the underlying video, chat, transcript, or prompt.

Source: [ProactiveBench, arXiv:2609.12658](https://arxiv.org/abs/2609.12658) (submitted 2026-09-11).

### LiViBench (AAAI 2026)

LiViBench contains 24 tasks for interactive livestream understanding. Its videos include audio, speech, and real-time comments; the paper emphasizes that livestream-specific understanding is distinct from ordinary video QA.

**Engineering implication:** game frames, game audio, ASR, and viewer comments should be separate evidence streams on a shared monotonic timeline. A viewer comment is a claim, not proof of a game event. Retrieval should be time-bounded so a comment about the previous round cannot ground a reaction to the current round.

Source: [LiViBench, AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/39859) (published 2026-03-14).

## 2. Implemented: privacy-safe response-timing evaluator

New files:

- `star/stream_response_timing_benchmark.py`
- `tests/test_stream_response_timing_benchmark.py`

Run it with two sanitized JSONL files:

```bash
python -m star.stream_response_timing_benchmark windows.jsonl observations.jsonl --minimum-events 20
```

### Input contract

Each event window contains only:
- opaque session and event IDs;
- an allowlisted event kind;
- host-clock observation/open/deadline timestamps;
- an independently labeled expected action (`speak`, `backchannel`, or `silence`);
- an explicit independent-scoring flag.

Each observation contains only:
- opaque session and event IDs;
- the planner decision and decision timestamp;
- host-observed emitted mode (`speak`, `backchannel`, or `none`);
- output count;
- first host-observed audio and/or first avatar-output timestamps;
- an independent grounding result when output occurred.

Unknown JSON fields are rejected. In particular, transcript, prompt, viewer-name, raw-audio, and image/video fields cannot be silently ingested.

### Metrics

- timely grounded responses;
- correct silence;
- missed and false-positive responses;
- early and late output;
- planner decision mismatches;
- emitted-modality mismatches;
- duplicate outputs;
- ungrounded and unverified outputs;
- decision-to-event latency p50/p95;
- first-audio latency p50/p95;
- first-avatar latency p50/p95;
- response precision/recall and silence precision/recall;
- the same core metrics broken down by event kind, so danger reactions cannot be hidden by easy ambient cases.

A report is `inconclusive` when the independently scored cohort is below the configured minimum, contains unscored windows, or is missing observations. A `measured` report is still only a measurement; it is not a model-promotion gate or permission to stream.

### Important boundary

The evaluator trusts its input timestamps and labels as host-provided observations; it does not authenticate them. The Windows host must bind audio receipts to Star's own output route and bind avatar receipts to the VTube Studio session. A generated text response, queued TTS request, or model self-report is not proof that a viewer heard or saw it.

## 3. Recommended VTuber runtime: one causal media timeline

Use a single session epoch and monotonic clock across:
1. game capture and game-state events;
2. audio endpoint capture and ASR partials;
3. moderated viewer comments;
4. response planning;
5. TTS chunks and physical PCM submission;
6. avatar expression/motion;
7. OBS scene/stream state.

Every event should carry an opaque event ID, increasing sequence, source, event kind, observed-at monotonic time, expiry deadline, and an evidence reference. The host—not the model—owns timestamps and route identity.

Recommended coordinator decisions:
- **speak** when a grounded verbal response fits the current window;
- **backchannel** when a small nonverbal acknowledgement is appropriate and another speaker owns the floor;
- **defer** when the information may still be useful but the current conversation/game workload is unsuitable;
- **silence** when evidence is weak, the event is stale, the event is duplicate, or no response adds value.

Hard invariants:
- stale events never become fresh after a slow model response;
- newer observations supersede queued commentary about the same replaceable state;
- owner speech and barge-in preempt optional commentary;
- critical gameplay preempts ambient commentary and optional animation;
- text approval, TTS completion, PCM submission, physical audio, and remote viewer audibility are distinct milestones;
- route changes and session restarts invalidate pending media from the previous epoch;
- cancellation propagates through text, TTS, PCM, avatar, and host output.

### Human-like streaming behavior

Prioritize conversational judgment over talk-time:
- short reactions to verified game events;
- natural silence during focus, loading, or low-information gameplay;
- varied but restrained acknowledgements;
- no repeated catchphrase loops;
- clarification when perception or ASR is uncertain;
- clear distinction between viewer claims and independently observed facts;
- continuity grounded in actual recorded sessions, with fictional persona lore kept separate;
- AI identity disclosure when relevant rather than fabricated human offline experiences.

## 4. Voice and avatar integration

### Windows audio

Use WASAPI loopback only as an output-observation source; the loopback mix can include game audio, music, browser audio, alerts, and Star's voice. The host must identify Star's own playback stream or route rather than infer that all captured audio was spoken by Star.

Track:
- selected endpoint identity and generation;
- sample rate, channel count, and format;
- TTS chunk enqueue time;
- PCM submit time;
- first device-rendered sample when available;
- endpoint invalidation/device-change notifications;
- underruns, dropped chunks, and cancellation latency.

A device change must invalidate pending output and require a fresh route-bound calibration.

### VTube Studio

The VTube Studio plugin API can activate hotkeys, control face parameters, and inject custom tracking parameters. API access is local WebSocket and requires the user to enable the plugin API and approve the plugin. Keep the port configurable, store the granted token securely, and use a narrow allowlist of parameters and hotkeys.

Use expressions for discrete emotions/poses and injected parameters for continuous mouth/eye/head motion. Do not let model text directly set arbitrary Live2D parameters. Apply a host-side motion envelope, rate limits, and a neutral reset after cancellation.

Sources:
- [VTube Studio plugin API overview](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins)
- [VTube Studio expressions and hotkeys](https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-%28a.k.a.-Stickers-or-Emotes%29)

### OBS

OBS WebSocket is built into OBS Studio 28+. Its official guide strongly recommends password authentication. Keep the socket on loopback unless remote control is explicitly needed; never expose it unauthenticated to a LAN or the public internet. Separate read-only stream health observations from scene-changing commands, and require owner approval for live scene, stream, recording, or broadcast actions.

Source: [OBS Remote Control Guide](https://obsproject.com/kb/remote-control-guide).

## 5. Inference speed: new cache research and the right benchmark

### SGLang session-aware Radix Cache

SGLang documents a session-aware UnifiedRadixCache mode that prioritizes KV associated with active multi-turn sessions over unrelated cache entries under memory pressure. The protection is soft, not a pin: referenced KV can still be evicted when needed. The top-level `session_id` labels cache references only; it does not reconstruct the prompt. Applications must still send the full intended prompt and close sessions on normal, error, and cancellation paths.

This is a promising experiment for a long-lived Star conversation, but not an automatic runtime switch. It is implemented only for `UnifiedRadixCache`; it may not fit an 8 GB gaming GPU once model weights, game rendering, OBS, vision, and TTS are accounted for.

Source: [SGLang Session-Aware Radix Cache](https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/session_radix_cache.mdx).

### What to benchmark before changing runtimes

Compare the existing local backend against any SGLang/vLLM candidate using identical models, quantization, prompts, sampling settings, and game scenes. Record:
- time to first token (TTFT);
- time per output token (TPOT) and total decode time;
- time to first audio and first avatar response;
- p50/p95/p99 under concurrent load;
- KV cache hit rate and eviction behavior;
- VRAM peak/headroom and CPU/RAM usage;
- game frame-time p95/p99, not just average FPS;
- OBS dropped frames and audio underruns;
- response quality and task success.

Test four stages: model only; game + model; game + model + OBS; game + model + OBS + TTS + avatar. Use a cold-start run and a warmed multi-turn session. Randomize or counterbalance candidate order, and isolate server processes when testing cache-state effects.

Do not optimize only tokens/second. A faster decoder that starves the game or increases first-audio latency is a regression for Star's actual workload.

## 6. General intelligence, memory, gaming, and creation roadmap

### Evidence-backed general knowledge

Keep typed memory records:
- fact (source, version, retrieval date, expiry);
- observation (host/tool evidence, freshness, scope);
- experience (action actually taken and result receipt);
- skill (procedure validated on repeated and held-out tasks);
- hypothesis (explicitly unverified);
- preference (owner- or user-stated, scoped);
- fictional persona lore (never mixed with real experiences).

Retrieval should combine lexical, vector, temporal, and project/game filters, then rerank only when the latency budget permits. Preserve superseded facts as history. Evaluate whether memory improves later tool choice and task success—not merely whether a model can repeat a stored sentence.

### Gaming skill development

Use two coordinated loops:
- **Reflex loop:** latest valid observation, compact state, small allowlisted action set, hard action deadline, immediate acknowledgement, interruptible control.
- **Tactical loop:** game rules, maps, mechanics, strategy hypotheses, targeted practice, loss analysis, and transfer to unseen scenarios.

A skill should be promoted only after repeated success across held-out maps/variants and a resource-loaded rehearsal. Keep scenario diversity balanced. A high score on one easy level is not broad mastery.

### Autonomous game creation

For Roblox and other engines:
**Inspect → Clarify intent → Plan → Build → Static checks → Run → Playtest → Visual compare → Repair → Held-out regression → Owner-reviewed release.**

Evaluate actual gameplay, UI reachability/scaling, client/server authority, collision, animation, audio, multiplayer behavior, exploit resistance, and performance on lower-tier hardware. Keep publishing, live datastore writes, monetization, moderation, secrets, and production changes behind explicit owner approval.

## 7. Privacy and observability

OpenTelemetry's GenAI conventions are useful for naming model operations and token/latency metrics, but the GenAI event guidance explicitly says user inputs and model outputs should not be captured by default because of privacy, size, and performance concerns.

Star should export aggregate counters and durations by default. Raw prompt, transcript, viewer comment, audio, video, and tool-argument capture must remain separately opt-in, local, access-controlled, and retention-bounded. This new benchmark follows the safer default: opaque IDs in inputs, aggregate-only output, and strict rejection of unknown content fields.

Sources:
- [OpenTelemetry GenAI event conventions](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/gen-ai/gen-ai-events.md)
- [OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)

## 8. Acceptance plan

Before any feature is enabled for public streaming:

1. Collect at least 20 independently labeled event windows per rehearsal; include speech, backchannel, and silence cases.
2. Include owner interruption, viewer question, viewer comment, game danger, game success, and ambient/no-action windows.
3. Run the JSONL evaluator and inspect early, late, missed, duplicate, ungrounded, and modality-mismatch counts.
4. Verify actual first-audio and first-avatar timestamps on the Windows host.
5. Test owner barge-in and cancellation during TTS and avatar motion.
6. Test VTube Studio and OBS authentication, reconnection, and endpoint changes.
7. Run a 30–60 minute private rehearsal with the game, inference, OBS, TTS, and avatar active.
8. Require no critical audio/OBS regressions and compare game frame-time percentiles with a model-only baseline.
9. Keep results inconclusive when evidence is missing; never promote from a synthetic-only or model-self-reported run.

## 9. Limitations and next engineering steps

Implemented now:
- dependency-free response-window and output-receipt schemas;
- strict JSONL parser with bounded records and unknown-field rejection;
- offline metrics for response timing, silence quality, duplicates, grounding, and audio/avatar latency;
- focused regression tests.

Not implemented by this change:
- Windows WASAPI capture or per-process audio attribution;
- VTube Studio WebSocket authentication/parameter injection;
- OBS WebSocket connection;
- ASR or viewer-chat ingestion;
- model training, fine-tuning, or increased foundation-model intelligence;
- game-control or Roblox Studio automation;
- hardware inference benchmarks or a demonstrated speed increase.

Next engineering priority: wire host-owned audio/avatar receipts into the evaluator, then run the full private streaming rehearsal. Only after that should Star compare local inference backends and promote a new configuration.