# STAR AI — Task-to-Delivery Integration, Streaming Naturalness, and Capability Research

**Research date:** 2026-11-12  
**Implementation branch:** `feat/delivery-ledger-sqlite-recovery-20261112`  
**Scope:** task-result delivery, interruption-aware VTuber streaming, local inference performance, Roblox/gameplay learning, game creation, and general-knowledge transfer.

## Executive summary

This run audited draft PR #1157 against its exact GitHub Actions head. The audit found a real correctness defect in the parent delivery ledger: `DeliveryLedger.claim()` referenced `host_confirmed_stopped`, which is not a parameter or local in that method. Pyright and Ruff both reported the same undefined name, and the offline test job stopped at lint before running the test suite.

The defect is fixed by keeping ordinary claims on the normal deadline path. Only `reconcile_after_restart()` may pass `allow_recovery_required=True`, and only after it has required explicit host confirmation that old synthesis/playback workers have stopped.

The same audit found an idempotency edge case: an exact enqueue retry after its original deadline was rejected by deadline validation before the existing delivery contract was checked. The create path now checks for an exact existing contract first. An exact retry returns the existing record, including an expired one; a different contract still conflicts. This avoids accidentally creating a second obligation or masking the original terminal state.

A small typed bridge, `star/task_delivery_dispatch.py`, now connects a completed TaskLedger record to the DeliveryLedger. It accepts only the exact current completed task version and derives the result digest from that authoritative TaskRecord. Five tests cover the bridge and the retry behavior.

## 1. Implementation added

### CI correctness repair

The exact PR #1157 CI run reported:

- `star/delivery_ledger.py:279:42`: undefined `host_confirmed_stopped` in Pyright.
- Ruff F821 on the same expression.
- Python compilation passed.
- React UI checks passed.
- The offline test job stopped at Ruff, so the full offline suite did not run on that failed run.

The repaired claim path calls `_expire_deadline(record, now)` without bypassing the recovery fence. Restart reconciliation remains the only path that may expire a RECOVERY_REQUIRED record, after host stop confirmation.

### Task-to-delivery bridge

`enqueue_completed_task()` enforces:

1. The expected task version is a positive integer.
2. The task still exists at that exact version.
3. The task state is COMPLETED.
4. The result digest comes from the completed TaskRecord.
5. The delivery ledger receives only opaque IDs and segment digests.
6. Repeated enqueue of the same contract is idempotent.
7. Reusing a delivery ID with different segments or a different task contract is rejected.

This is deliberately an at-least-once in-process bridge, not a claim of distributed atomicity. TaskLedger and SQLiteDeliveryLedger are separate stores. A crash after task completion but before delivery enqueue is still a gap because TaskLedger itself is in-memory. The next durability milestone should persist task completion and a delivery-outbox row in one SQLite transaction, then dispatch the outbox idempotently. Do not pretend two independent ledgers form one atomic transaction.

## 2. Natural VTuber streaming: evidence and design

### Adaptive interruption instead of raw VAD-only barge-in

LiveKit's current Agents documentation distinguishes genuine interruptions from short backchannels such as "uh-huh", "okay", and "right". Its adaptive mode uses audio context to decide whether to yield instead of interrupting on every VAD speech detection. The documentation also describes boundary cooldowns and false-interruption recovery, because a genuine correction immediately after speech begins must not be discarded and a cough/noise false positive should not permanently truncate the response.

Sources:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://docs.livekit.io/reference/agents/events/

STAR acceptance gates:
- Measure genuine barge-in stop latency from captured audio, not only from internal callbacks.
- Measure false interruptions per hour and missed true interruptions.
- Include paired cases where identical overlapping words require different decisions because the prior conversational context differs.
- Preserve a short turn-boundary correction window.
- Resume after confirmed false interruptions without regenerating already-played segments.
- Keep the Delivery Ledger as the authority for local playback progress; the Social Director decides whether to speak, yield, or wait.

A useful external diagnostic is ECHO, a matched-contrast benchmark that pairs the same overlap transcript with different preceding dialogue contexts. It is designed to catch agents that always yield or always keep speaking:
https://arxiv.org/abs/2609.17360

### Playback completion is not transcript completion

LiveKit exposes a playback-finished event on the audio output path. A final transcript indicates generated text is complete; it does not prove the output device finished playing that text.

Source:
https://kb.livekit.io/articles/8142160213-how-to-detect-when-an-agent-has-finished-speaking

STAR should connect the event to the delivery ledger only after validating the playback ID, generation, segment, and clock epoch. The local event proves local playback completion, not that every remote viewer heard the stream.

### Avatar synchronization

VTube Studio's API requires plugin authentication and explicit user approval. It supports event subscriptions as well as state polling; permissions can be granted or denied by the user.

Sources:
- https://github.com/DenchiSoft/VTubeStudio
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

STAR should request only the minimum permissions required for model parameters, hotkeys, and events. Avoid requesting item/image loading permissions unless the user explicitly enables that feature. Mouth/viseme animation should follow the actual playback clock; emotion and gaze can be driven by the Social Director but must not falsify what was spoken.

### OBS control boundary

OBS WebSocket is included in OBS 28+ and supports remote RPC/events. Its upstream project strongly recommends password protection.

Sources:
- https://github.com/obsproject/obs-websocket
- https://github.com/obsproject/obs-websocket/blob/master/docs/docs/partials/introduction.md

Use read-only stream/scene health monitoring by default. Keep scene changes, starting/stopping a broadcast, and other externally visible operations behind separate explicit user settings and runtime authorization.

## 3. Local inference speed without quality regression

The upstream llama.cpp server documents:
- parallel decoding and multi-user support;
- continuous batching;
- monitoring endpoints;
- constrained JSON and tool calling;
- speculative decoding;
- prompt-prefix reuse through `cache_prompt`.

Source:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

The server documentation notes that cache reuse can produce nondeterministic results on some backends when batch sizes differ, because logits may not be bit-identical between prompt-processing and token-generation paths. Therefore STAR must benchmark both speed and output quality.

### STAR's paired experiment matrix

On the target 8 GB VRAM / 32 GB RAM class, vary one setting at a time:

- model quantization and context length;
- prompt-prefix stability and cache-hit rate;
- KV-cache type and memory residency;
- speculative decoding draft model, acceptance rate, and extra VRAM;
- CPU/GPU layer placement;
- model cold-start versus resident warm path;
- actual server slot count and continuous-batching concurrency;
- interactive-priority scheduling while game, OBS, avatar, and audio are active.

Record paired p50/p95/p99:
- time to first useful token;
- decode tokens per second;
- time to first audible response;
- end-of-turn to first audible response;
- peak VRAM and RAM;
- game frame-time p99;
- OBS render/encode drops;
- audio underruns;
- tool success and answer quality.

Do not promote a configuration solely because tokens/s improved. It must preserve answer correctness and interactive audio/game/stream SLOs. Use pinned model/runtime revisions, identical prompts, warm/cold splits, fixed concurrency, and repeated paired runs.

## 4. Gaming and game-development intelligence

### Roblox Studio: inspect before edit, then execute

OpenGameEval runs agents in reproducible, stateful Roblox Studio sessions and evaluates both scene changes and simulated gameplay. Its October 2026 paper reports 84 human-curated core tasks and finds that runs inspecting the objects they later modify pass more often than runs that do not inspect them.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

STAR should separate observation tools from editing tools and require a pre-edit inspection record for every object/property the action will touch. Then verify the result in a simulated play session.

### General game skill learning

Voyager demonstrates a useful pattern: an automatic curriculum, an executable skill library, environment feedback, and iterative self-verification.

Source:
https://github.com/MineDojo/Voyager

STAR's Gamer should have:
- a high-frequency reactive controller for movement/aim/camera/actions;
- a strategic planner for objectives, map knowledge, resource use, and practice;
- versioned skills with preconditions, control bindings, game/build/map scope, expected observations, recovery branches, and failure traces;
- held-out maps/seeds for skill promotion;
- explicit uncertainty when a skill has not transferred to a new game.

A single successful playthrough is not mastery. Promotion requires repeated success across held-out conditions and a regression set.

### Complete game creation

GameDevBench contains 333 Godot tasks spanning 2D/3D graphics and animation, UI, and gameplay logic. Its published study reports that image/video feedback improved one tested configuration from 41.1% to 52.0%.

Source:
https://github.com/waynchi/gamedevbench

STAR Creator should capture visual before/after evidence, inspect the actual engine scene, run real input playthroughs, test progression and endings, test save/reopen, and replay affected routes after fixes. Compilation alone is not completion.

## 5. General knowledge and durable learning

Do not equate document ingestion with learning. Store reusable knowledge with:
- source/provenance and retrieval date;
- confidence and scope;
- last verified date and freshness policy;
- known exceptions/counterexamples;
- links to evidence;
- privacy/retention class;
- a test that demonstrates the fact or skill can be applied.

Separate stable knowledge (mathematics, physics, programming fundamentals, history) from volatile facts (current software APIs, prices, versions, events). Volatile facts need freshness checks before use. Evaluate recall, reasoning, and practical transfer separately. Prefer the existing STAR memory and skill infrastructure over introducing another vector database without an ablation showing a measurable benefit.

## 6. Recommended integrated architecture

```text
                 STAR INTERACTIVE LOOP
          audio/video | floor control | avatar | game input
                            |
                    conversation state
                            |
                       task ledger
                            |
                 verified task completion
                            |
                   task-delivery bridge
                            |
                    durable delivery ledger
                            |
                 playback host acknowledgements
                            |
                 actual local output / metrics

                 STAR DELEGATED LOOP
          research | coding | game planning | memory
                            |
                    versioned artifacts
                            |
                 freshness + quality checks
                            |
                   interactive loop decides
                    whether/when to deliver
```

## 7. Next milestones and acceptance

| Priority | Milestone | Acceptance |
|---|---|---|
| P0 | Re-run PR #1157 exact-head CI | Ruff, Pyright baseline, full offline tests, React all pass |
| P1 | Durable task-completion outbox | Task completion and outbox enqueue share one SQLite transaction |
| P1 | Playback host adapter | Real completion/interruption events; stale receipts rejected |
| P1 | Restart supervisor | No replay until orphaned synthesis/audio workers are confirmed stopped |
| P2 | Social Director | Paired interruption/backchannel accuracy; false barge-in and omission rates |
| P2 | Avatar Director | Mouth follows playback timing; minimal user-approved VTS permissions |
| P2 | OBS adapter | Authenticated read-only health telemetry by default |
| P3 | Gamer benchmark lane | Held-out game/map success, repeatability, failure recovery |
| P3 | Creator completion gate | Real engine playthrough, ending, save/reopen, regression replay |
| P3 | Inference A/B harness | Faster first-audible latency without quality, audio, OBS, or FPS regression |

## Validation boundary

This branch adds a typed task-to-delivery bridge and focused tests, and repairs the exact CI-reported undefined name and retry-order bug. The next exact-head GitHub Actions run is the authority for repository test/type/lint status.

No real Windows audio device, TTS engine, LiveKit room, OBS broadcast, VTube Studio model, GPU inference benchmark, Roblox Studio playthrough, or livestream was run in this change. External benchmark results above are research evidence, not STAR performance claims. The bridge is not a durable outbox; TaskLedger remains in-memory. Production `main`, model weights, routing defaults, runtime permissions, and broadcast settings remain unchanged.


## 8. Cross-domain intelligence: generalist perception plus specialist control

### SIMA 2: learn actions across unfamiliar worlds

Google DeepMind's SIMA 2 combines visual observation, language instructions, high-level reasoning, and ordinary game controls. Its report describes generalization to held-out worlds and an open-ended skill-learning loop. The same report is explicit about limitations: very long-horizon tasks, short interaction memory, precise low-level keyboard/mouse control, and robust visual understanding remain difficult.

Sources:
- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- https://arxiv.org/abs/2512.04797

STAR should borrow the architecture pattern, not assume the reported capability transfers automatically:
- multimodal observation is a separate input stream from the planner;
- high-level goals are decomposed into short, verifiable action horizons;
- the controller receives explicit action bounds and stop conditions;
- observations after each action update the world state;
- skills are promoted only after held-out evaluation;
- long-horizon memory is externalized into task/skill state instead of relying on one giant context window.

### Agent S2: specialist tools for computer use

Agent S2 studies a compositional generalist/specialist computer-use architecture with hierarchical planning and multiple grounding strategies. This suggests a useful STAR desktop pattern: a planner should decide *what* to do, a grounding component should identify the exact UI target, and a constrained executor should perform the action and verify the resulting state.

Source:
https://arxiv.org/abs/2504.00906

For STAR, every desktop action should carry:
- target application/window identity;
- observed target evidence;
- intended action and precondition;
- timeout and cancellation token;
- expected postcondition;
- screenshot/state evidence after execution;
- rollback or safe-stop behavior.

Do not let a model invent coordinates and click blindly. Re-observe after layout changes, modal dialogs, focus changes, or unexpected results.

### One reusable skill format across games and desktop tools

A skill should be a small, versioned executable contract:

| Field | Purpose |
|---|---|
| Skill ID/version | Stable identity and change tracking |
| Domain | Game, Roblox Studio, Blender, desktop, research |
| Preconditions | Required app/game/build/map/control mode |
| Observation schema | What the skill must inspect first |
| Action schema | Bounded permitted actions |
| Expected effects | Observable success conditions |
| Recovery branches | What to do after a known failure |
| Evidence | Test runs, screenshots, state diffs, traces |
| Confidence | Empirical success rate and sample count |
| Scope | Environments where it is known to work |
| Expiry/revalidation | When an API/game version makes it stale |

This is more reliable than storing a paragraph that says "STAR knows how to play/build X." A skill should be searchable, composable, executable, and falsifiable.

## 9. Natural streamer behavior: social policy, not just voice synthesis

A convincing AI VTuber needs more than a human-sounding voice. The Social Director should maintain a compact, explicit conversation state:

- current floor owner and whether STAR has the floor;
- active speaker IDs scoped to the current session (not biometric identity);
- addressee confidence: STAR, another viewer, or ambiguous;
- current topic and unresolved questions;
- whether a viewer is giving a backchannel or taking the floor;
- active delivery obligations and playback progress;
- whether a delegated task result is still relevant to the current conversation;
- stream mode (gameplay, just chatting, tutorial, break, offline rehearsal).

The director should choose among SPEAK, LISTEN, YIELD, RESUME, and SILENT. "SILENT" is a valid successful decision: it prevents constant chatter and lets viewers talk to each other.

### Speech and avatar coordination

- Generate short semantic speech chunks rather than one long monologue.
- Keep the actual playback clock as the authority for mouth movement and segment completion.
- Drive gaze and expression from the current speaker/addressee and conversational intent, not from random idle animation.
- Use prosody (pace, pause, emphasis, pitch contour) to communicate intent; avoid inserting filler words or fake laughter on a timer.
- Resume only the unplayed/partial segment after a confirmed false interruption; never replay already acknowledged segments.
- Keep the AI identity transparent in the channel/about panel and when directly asked. Natural presentation must not imply a human operator is secretly speaking.

### Privacy and safety for a public stream

- Use ephemeral per-session speaker labels; do not build voiceprints or infer real-world identities.
- Keep raw microphone/chat audio out of durable memory by default.
- Store only the minimum consented viewer preferences needed for continuity, with a retention/forget policy.
- Treat viewer chat, usernames, links, and on-screen text as untrusted input; prompt injection in chat must not grant tools or alter system policy.
- Keep broadcast start/stop, scene switching, external messages, purchases, file deletion, and account changes behind separate explicit permissions.
- Use a rehearsal mode with synthetic chat and prerecorded audio before public deployment.

## 10. Model routing and intelligence allocation

Use the cheapest reliable controller for each time scale:

| Workload | Preferred control path |
|---|---|
| Frame-level movement / aiming | Deterministic or trained low-latency controller |
| Audio VAD / playback clock | Native real-time audio pipeline |
| Simple intent classification | Small fast model or rules |
| Conversation response | Low-latency conversational model |
| Strategic gameplay | Stronger planner on a bounded cadence |
| Coding / research / game creation | Strong reasoning model plus tools and tests |
| High-impact result verification | Independent checker, deterministic tests, or second model |
| Knowledge retrieval | Search/index first; model synthesizes with provenance |

Escalate when the fast path reports low confidence, conflicting evidence, a failed postcondition, or an unfamiliar environment. Do not use one model for every task, and do not let a slow strategic planner block the audio or input loop.

For every route, log model/runtime revision, task class, input/output token counts, cache hit, queue wait, first-token latency, completion latency, tool success, verification result, and memory use. Keep raw prompts/audio out of telemetry unless the user explicitly enables a protected diagnostic capture.

## 11. Final acceptance matrix

| Capability | Minimum evidence before calling it ready |
|---|---|
| Natural conversation | Paired backchannel/barge-in cases, false interruption rate, omission rate, p95 stop latency |
| Avatar synchronization | Mouth/viseme follows captured output; expression/gaze tests; reconnect behavior |
| Streaming | Authenticated OBS telemetry, dropped-frame/audio-underflow monitoring, safe-stop behavior |
| Gaming | Held-out maps/seeds, repeated success, action latency, recovery traces |
| Roblox creation | Inspect-before-edit trace, scene assertions, simulated play session |
| Game creation | Real engine launch, playable core loop, endings, save/reopen, regression replay |
| General knowledge | Provenance, freshness, calibrated uncertainty, delayed practical transfer |
| Desktop autonomy | Target grounding, preconditions, postconditions, cancellation, rollback/safe-stop |
| Faster inference | Paired p50/p95/p99 improvements with unchanged quality and no game/audio/OBS regression |
| Self-improvement | Offline experiment, independent verification, versioned result, rollback, no automatic production promotion |


## 12. Existing STAR runtime audit — extend, do not duplicate

The branch already contains substantial streaming, avatar, telemetry, and game-control primitives. The next work should wire these together rather than create parallel "Social Director", "Avatar Director", or "Gamer Brain" modules.

| Existing module | Verified responsibility | Remaining boundary |
|---|---|---|
| `star/stream_director.py` | Bounded, consent-gated speech arbitration; priority, expiry, cooldown, untrusted viewer context, session epochs | No chat transport, speech generation, TTS, or automatic tool execution |
| `star/stream_turntaking.py` | Deterministic VAD-frame advisor; stale/missing input fails closed; owner-yield is separate from guest hold | Host supplies preprocessed VAD and must authenticate the owner source |
| `star/stream_interrupt_host.py` | Coordinates stage invalidation, physical audio-stop callback, animation flush, and avatar neutral reset; latches faults on missing acknowledgements | Does not capture microphones or own the audio device; callbacks are host attestations |
| `star/vtube_local_host.py` | Local-loopback VTube Studio WebSocket, explicit owner pairing, token handling in caller memory, 14 parameter registration, stale-frame drop | Requires optional websocket transport and a real owner-configured Live2D rig; no automatic retries or model-tool access |
| `star/stream_hardware_telemetry.py` | Off-hot-path CPU/RAM/GPU probes, host-provided frame-present intervals, speaker backlog, immutable QoS snapshots | Real FPS depends on a trusted PresentMon/engine callback; voice backlog depends on the actual local output host |
| `star/obs_stream_status.py` | Strict parser and epoch-safe sampler for OBS GetStreamStatus, preserves unknown congestion as unknown | Authenticated OBS WebSocket connection is still a separate host transport |
| `star/stream_workload_runtime.py` | Composes stream pressure hysteresis with CPU/RAM/VRAM admission leases | Policy only; no process start/stop, inference launch, or authorization |
| `star/game_closed_loop.py` | One-step observe → offer → host-dispatch → verify protocol; stale/mismatched movement latches stop | Does not send game inputs or capture game frames itself |
| `star/game_skill_promotion.py` | Held-out skill evidence, scenario/session deduplication, lower confidence bound, unsafe-trial veto, owner-review status | Host must reserve holdout scenarios and independently score trials; evidence is in-memory |
| `star/game_skill_memory.py`, `star/game_transfer_eval.py`, `star/gameplay_skill_bank.py` | Existing reusable game-skill and transfer foundations | Need a real game adapter and repeatable held-out evaluations |
| `star/agent_runtime.py`, `star/agent_fleet.py`, `star/agent_resource_planner.py` | Existing agent execution, fleet and resource planning | Task completion still needs durable outbox delivery and unified host supervision |

### Integration graph to implement next

```text
actual OBS WebSocket -----> obs_stream_status parser
actual OS/NVIDIA probes --> RealtimeTelemetryHost
actual PresentMon/engine -> presented_frame()
actual speaker host ------> report_audio_backlog()
actual TTS playback ------> DeliveryLedger / SQLiteDeliveryLedger
                                |
                                v
                        task-delivery bridge
                                |
                                v
                         StreamDirector
                                |
                      voice generation / TTS
                                |
                     StreamInterruptionHost
                          /           \
                   audio device     VTubeLocalHost
                                |
                         playback receipt

game screen/input adapter -> ClosedLoopPilot -> verified frame
                                  |
                         SkillPromotionGate
                                  |
                         gameplay skill bank
```

### Critical gap ranking

1. **Durable task completion outbox:** TaskLedger is in-memory. Persist the task terminal transition and pending delivery row in one database transaction; dispatch to SQLiteDeliveryLedger with an idempotency key. This closes the crash gap that the new helper alone cannot close.
2. **Single Windows host supervisor:** one trusted service owns OBS, VTube Studio, TTS/audio process epochs, telemetry, and worker start/stop acknowledgements. No model or chat event receives these callbacks directly.
3. **Actual transport adapters:** connect OBS WebSocket with password authentication; connect actual Windows audio output/playback events; use real process/frame counters. Keep parser/policy modules pure.
4. **Voice delivery wiring:** on task completion, enqueue only the current task version; StreamDirector chooses whether to speak; TTS produces short segments; playback-finished callbacks acknowledge them; interruption host stops and flushes the exact playback epoch.
5. **Game adapter:** feed authoritative screen/frame and input results to ClosedLoopPilot; score with a host-owned held-out scenario inventory; only then submit evidence to SkillPromotionGate.
6. **Cross-system trace:** correlate task ID, conversation turn, delivery ID, playback epoch, OBS stream epoch, game session, model revision, and workload lease using opaque IDs. Export timings/counters, not prompts, audio, chat text, or viewer identity.

This audit is based on the code present in the PR branch. It does not assert that the host callbacks are connected to real devices in a packaged Windows run. The existing components are valuable foundations, but their class-level tests and host-supplied booleans are not a substitute for end-to-end hardware verification.
