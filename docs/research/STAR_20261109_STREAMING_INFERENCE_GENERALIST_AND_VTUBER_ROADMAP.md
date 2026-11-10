# STAR — Mixed-Workload Inference, Generalist Intelligence, Game Mastery and Natural VTuber Runtime

**Research date:** 2026-11-09  
**Status:** research-backed engineering plan; one local-only streaming benchmark implemented in this change.  
**Scope:** STAR's existing local-first Windows desktop, Linux STAR Server, Roblox Studio workflows, and optional VTuber/gameplay runtime.

This document is an integration plan, not a claim that STAR has become a frontier foundation model, a human, a master gamer, or a production streamer. STAR's model weights are not changed by the benchmark or by the learning systems described here.

## Executive recommendation

Stop treating speed, intelligence, gaming, game creation, and streaming as separate feature checklists. Build one measurable runtime with five cooperating layers:

1. **Perception:** acquire fresh, permission-scoped observations from the current game, conversation, desktop, and stream.
2. **Working state:** maintain a short-lived, time-stamped scene and conversation state with provenance and expiry.
3. **Decision:** choose between act, ask, speak, backchannel, defer, or remain silent under an explicit deadline and resource budget.
4. **Execution:** dispatch only through existing owner-approved adapters; model output is never itself permission to control the PC, Studio, audio device, OBS, or a live game.
5. **Verification and learning:** compare host-observed outcomes with independently scored expectations; retain only reviewed, reproducible skills and memories.

The fast path should handle urgent game reactions and conversational turn-taking. The slower path should handle research, planning, code generation, memory retrieval, tool calls, and post-round reflection. Both paths share evidence and resource budgets, but the deep path must not block the fast path.

## New implementation in this change

### star/inference_workload_benchmark.py

The existing star/inference_benchmark.py sends one repeated, non-streaming prompt. That is useful as a smoke test but does not reveal first visible response latency or whether a model behaves differently across STAR's actual workload shapes.

The new benchmark adds a deterministic synthetic workload mix:

- short chat
- general knowledge
- simple reasoning
- Luau generation
- debugging
- game-strategy explanation
- concise stream commentary
- summarization

It warms the local model once, then measures streamed requests. It reports per-category and overall:

- client-observed first nonempty text-chunk latency (p50/p95)
- end-to-end request latency (p50/p95)
- inter-chunk gap p95
- output characters per second
- completion tokens and client-observed output tokens/second after first content only when the server returns valid usage metadata
- success/failure counts and bounded exception class names
- warm-up time, workload order, concurrency and wall time

The implementation is deliberately conservative:

- Settings.validate() enforces STAR's loopback-only local endpoint policy.
- Default concurrency is one; maximum concurrency is two.
- Requests are capped at 32.
- The prompt catalog is synthetic and fixed.
- Generated text is counted and discarded; it is not placed in the report.
- Missing token usage stays null; character rate is not mislabeled as token rate.
- The benchmark never changes model settings, launches a server, selects a faster model, or grants game/stream permissions.

Run against an already-started local model with: python -m star.inference_workload_benchmark --endpoint http://127.0.0.1:8080/v1 --model star-fast --requests 8 --parallel 1 --output inference-stream.json

**Interpretation limit:** first-content latency is the time to the first nonempty text chunk received by the client, not a tokenizer-level first-token timestamp. The post-first-content token rate is client-observed and includes network/chunk scheduling; it is not raw engine decode speed. Token counts are reported only from server-provided completion-token usage. The synthetic prompts do not grade correctness. Compare the same model/runtime revision, prompt catalog, hardware, context settings, warm-up policy, and concurrency.

### Focused verification

On the connected starai Linux development workspace:

- 30 focused tests passed across the existing inference benchmark, the new streaming workload benchmark, and PR #1097's response-timing evaluator.
- Ruff passed for all four changed Python modules/tests.
- Python compilation passed.
- git diff --check passed.
- Pyright was not available in this workspace; GitHub Actions remains the independent type-check gate.
- No live model, RTX 4060, Windows audio, OBS, or gameplay benchmark was run in this change.

## Research findings and design consequences

### 1. Faster local inference: optimize the whole request, not one tokens/second number

llama.cpp SPEED-Bench is a useful reference because it separates workload categories and reports prompt processing, generation throughput, latency, and speculative acceptance. Its documented comparison procedure keeps the benchmark, category, output length, concurrency, and samples identical between baseline and speculative runs. See the [SPEED-Bench guide](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) and [speculative decoding guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).

Recommended experiment order for STAR's constrained gaming GPU:

1. Establish a no-speculation baseline on the exact installed model and runtime.
2. Measure prompt prefill separately from decode.
3. Measure warm and cold first-content latency.
4. Try n-gram speculation before loading a second GPU-resident draft model.
5. Compare draft-model speculation only if VRAM headroom and game/OBS frame-time remain healthy.
6. Keep the same prompt corpus, context length, output cap, concurrency, and thermal/power state.
7. Run AB/BA order, repeated sessions, and a no-regression quality suite; do not select on one lucky run.

Speculative decoding is conditional, not magic: it helps when draft proposals are cheap and accepted often enough. A second model can compete for VRAM, memory bandwidth, and compute; on a gaming PC that can make the game or OBS worse even when isolated token speed improves. The correct target is **quality-adjusted first-audio latency under real stream load**, not maximum idle tokens/second.

Prompt-prefix caching should be preserved by keeping stable system instructions and tool schemas byte-stable and placing per-turn context after the stable prefix. Caching mainly reduces repeated prefill; it does not guarantee faster autoregressive decode.

### 2. Real-time gameplay: separate reflexes from deliberation

[Gym-Anything-RT](https://arxiv.org/abs/2610.37567), published 2026-10-27, evaluates 100 minigames in live and paused counterparts. The paper reports a large live-vs-paused gap for a frontier agent (9% live versus 75% paused in one reported configuration). The lesson is not that one model is universally poor; it is that a model can reason about a state yet miss the deadline while the world continues changing.

Build two loops:

**Fast loop**
- fresh frame/telemetry intake
- lightweight event and hazard detection
- bounded action proposal
- host-side action acknowledgement/deadline check
- emergency stop and stale-observation rejection

**Deep loop**
- learn mechanics and controls
- inspect map and objectives
- compare strategies and routes
- review mistakes after the action/round
- prepare practice plans
- test skill transfer on held-out maps and difficulty levels

The deep loop must not write to the fast loop's current action or mutate its evaluation labels. A delayed model answer must be discarded when its source frame, game scene, or action lease has expired.

### 3. Roblox creation: inspection and playtesting are core intelligence

[OpenGameEval](https://arxiv.org/abs/2610.02563) (2026-10-01) evaluates agents inside reproducible Roblox Studio sessions, with executable checks on both the edited scene and a simulated play session. Its 84 curated tasks and 13-model evaluation show that the benchmark remains difficult; runs that inspect relevant objects before editing succeed more often.

STAR's creation loop should therefore be:

**Inspect scene → identify dependencies → plan small edit → edit isolated test place → static-check Luau → run playtest → inspect logs/scene → verify behavior → repair → compare against baseline.**

Do not accept "script compiled" as proof that a game feature works. Require actual scene checks, server/client behavior checks, playtest observations, and performance checks.

Roblox's **2026-11-04 Studio MCP update** adds open_cloud_invoke, asset import workflows, and per-game permissions. The official [announcement](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849) and [Open Cloud MCP documentation](https://create.roblox.com/docs/studio/mcp-open-cloud) are the source of truth. Use the narrowest per-game permission, keep upload folders explicit, and require owner confirmation for permanent asset uploads, monetization, publishing, live data-store writes, or actions affecting players. Never work around a disabled permission. Some endpoints do not accept the Studio-issued token, and live data-store writes can affect real player data.

### 4. Natural VTuber interaction: timing, silence, interruption, and visible response

[Proact-VL](https://proact-vl.github.io/) (ICML 2026) frames a proactive companion as continuous perception plus response triggering and controllable commentary. It supports solo commentary, co-commentary, and guidance. This matches STAR's need to choose when to speak, not merely generate text after every frame.

[VoiceChat-TTS](https://arxiv.org/abs/2608.13831) (2026-08-13) studies continuous, streamable speech driven by LLM text tokens, with explicit interruption and silence behavior. It is a research candidate, not a drop-in guarantee for STAR's current voice.

The Windows runtime should eventually coordinate:

- incremental ASR/VAD with speaker and consent boundaries
- turn-taking state: listen, continue, backchannel, respond, interrupt, silence
- event salience and relevance windows for gameplay commentary
- bounded response length and measured voice-route pacing
- immediate STOP+FLUSH on owner interruption, critical game events, route changes, or stale output epochs
- actual first-audible device receipts, not just TTS completion or PCM queue acceptance
- VTube Studio expression/motion receipts tied to the same event and time window
- OBS telemetry and stream-state observation with authenticated loopback and least privilege

Use the official [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio) and [OBS WebSocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md). Keep avatar and OBS control behind owner-approved local adapters. A viewer message or model-generated plan must never grant control authority.

Naturalness should be evaluated by independent human review of timing, interruption handling, repetition, grounding, and personality consistency—not by a model grading itself. Silence is a valid and often correct action. Backchannels should be subtle, sparse, and suppressed during owner speech or critical gameplay.

### 5. General knowledge and memory: retrieval must improve action, not just recall

[APEX-MEM](https://arxiv.org/abs/2604.14362) (2026-04-15) explores append-only, temporally grounded, entity-centric memory and retrieval-time conflict resolution. [Mem2ActBench](https://arxiv.org/abs/2601.19935) (2026-01-13) focuses on whether an agent uses remembered information to select tools and ground parameters, rather than merely answer an explicit recall question.

For STAR, retain typed records:

- **fact:** externally verifiable claim, source, checked time, version/expiry
- **experience:** what STAR actually observed or did, with host evidence
- **procedure:** reproducible steps and preconditions
- **skill:** task family, practice history, score, held-out transfer evidence
- **preference:** explicitly owner-provided, scoped, revisable
- **hypothesis:** uncertain explanation that must not be promoted to fact
- **persona lore:** fictional character facts kept separate from real-world claims

Retrieval should rank by relevance, recency, authority, and task scope. Conflicting facts should remain versioned; do not silently overwrite the past. A memory candidate should only become durable after source validation or owner review. Evaluate with LongMemEval-style temporal/update/abstention questions and Mem2ActBench-style tasks where memory is needed to perform an action.

Generalist curriculum should span science, mathematics, history, writing, research, planning, computer use, software engineering, creative design, and practical knowledge. Each task needs a source or executable grader, an explicit uncertainty/abstention path, and a sealed holdout. More stored text is not the same as more intelligence.

## Proposed integration architecture

| Runtime | Responsibilities | Deadline behavior |
|---|---|---|
| Fast perception | fresh game/audio/desktop events, event deduplication | drop stale observations |
| Reflex controller | bounded game action proposal and acknowledgement | stop/defer on missed deadline |
| Conversation arbiter | listen/speak/backchannel/silence and interruption | owner interruption preempts |
| Deep planner | research, code, strategy, game creation | asynchronous; never blocks reflex path |
| Memory/retrieval | provenance, time, task scope, contradiction handling | retrieval budget and evidence |
| Verifier | tests, playtests, host receipts, paired comparisons | no evidence means inconclusive |
| Resource governor | CPU/GPU/VRAM, frame time, OBS and audio health | protect game/stream first |

Use a single task envelope across these layers: task ID, source/session epoch, event timestamp, deadline, workload class, resource reservation, evidence references, cancellation token, and expected output type. Every asynchronous result must be revalidated against the current epoch before it can affect the UI, voice, avatar, game, or project.

## Prioritized engineering roadmap

### P0 — Establish reproducible performance baselines
- Run the new mixed-workload streaming benchmark on the actual local model.
- Run llama.cpp SPEED-Bench against the same model/runtime revision.
- Save only aggregate reports and pinned configuration metadata.
- Compare sequential and low concurrency; keep default concurrency at one until evidence supports more.

### P1 — Windows private rehearsal
- Connect trusted WASAPI output observation, TTS route identity, VTube Studio and OBS local telemetry.
- Verify stop/flush, device-change, stale-epoch, audio-underrun and avatar-sync behavior.
- Run a 30–60 minute **nonbroadcast** game + inference + TTS + avatar + OBS rehearsal.
- Record game FPS/frame-time, VRAM, CPU, OBS dropped frames, first audible latency, interruption latency and voice consistency.

### P2 — Real game mastery
- Use the same game/seed/scenario in live and paused modes.
- Separate perception, action, and strategy scores.
- Require scenario-balanced attempts and sealed maps.
- Measure objective success, progress, action acknowledgement p95, stale-action rate, recovery, and skill transfer.

### P3 — Roblox creator loop
- Integrate Studio MCP with read-only inspection first.
- Build and playtest only in an owner-selected unpublished/test place.
- Use static Luau checks, scene invariants, simulated playtests, and visual evidence.
- Keep uploads, monetization, publishing, and live player-data writes separately gated.

### P4 — Generalist memory and learning
- Add temporal provenance and conflict-aware retrieval.
- Build domain-balanced practice and memory-to-action evaluations.
- Preserve independent graders and sealed holdouts.
- Promote lessons only through the existing reviewed/paired gate; never let the model edit its grader.

### P5 — Natural, long-session VTuber
- Add incremental listening and interruption-safe speech chunking.
- Coordinate event-aware commentary with subtle avatar expression.
- Track voice consistency and grounding across long sessions.
- Use independent reviewer labels; do not infer emotion from a viewer's identity or claim human feelings.

## Acceptance gates (do not skip)

**Inference:** same prompt suite and model revision; cold/warm runs; AB/BA order; p50/p95 first-content and end-to-end latency; usage completeness; quality non-regression; no game/OBS/audio regression.

**Gaming:** real-time versus paused comparison; at least three meaningfully different scenarios; held-out maps/seeds; actual host action acknowledgements; objective outcome and recovery; no stale action after a scene change.

**Game creation:** inspect-before-edit trace; clean static checks; scene invariants; playtest pass; independent visual review; performance budget; rollback evidence.

**Memory/general knowledge:** source/provenance accuracy; temporal updates; contradiction handling; abstention; memory-to-action task success; sealed cross-domain holdout.

**VTuber:** correct speak/backchannel/silence decisions; first-audible and first-visible receipts; owner barge-in stop latency; no stale PCM/avatar output; low duplicate/repetition rate; independent naturalness and grounding review; stable 30–60 minute rehearsal.

## Source register

- Aggarwal & Welleck, [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), 2026-10-27.
- Turkel et al., [OpenGameEval](https://arxiv.org/abs/2610.02563), 2026-10-01; [Roblox evaluation repository](https://github.com/Roblox/open-game-eval).
- Yan et al., [Proact-VL](https://proact-vl.github.io/), ICML 2026.
- Casanova et al., [VoiceChat-TTS](https://arxiv.org/abs/2608.13831), 2026-08-13.
- Banerjee et al., [APEX-MEM](https://arxiv.org/abs/2604.14362), 2026-04-15.
- Shen et al., [Mem2ActBench](https://arxiv.org/abs/2601.19935), 2026-01-13.
- [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) and [speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).
- Roblox, [Studio MCP Open Cloud and asset-import update](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849), 2026-11-04; [official Open Cloud MCP docs](https://create.roblox.com/docs/studio/mcp-open-cloud).
- [VTube Studio public API](https://github.com/DenchiSoft/VTubeStudio); [OBS WebSocket v5 protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

## Honest status

Implemented here: a deterministic, local-only, mixed-workload streaming inference benchmark plus focused tests.

Not implemented or demonstrated here: automatic model routing, model-weight training, faster inference, higher model intelligence, live gameplay mastery, a complete Roblox autonomous creator, Windows WASAPI/TTS/VTube Studio/OBS integration, or public broadcasting. Those require separate code, independent review, and the hardware acceptance evidence above.
