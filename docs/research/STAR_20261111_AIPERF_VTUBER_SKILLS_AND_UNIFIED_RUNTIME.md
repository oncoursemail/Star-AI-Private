# STAR research refresh: AIPerf, natural VTuber behavior, reusable skills, and unified runtime

**Research date:** 2026-11-11  
**Target:** STAR's existing local-first Windows desktop + optional Linux STAR Server architecture  
**Status:** Research and development guidance. This document does not claim that the proposed integrations are shipped.

## Executive findings

The highest-value next step is not to add many independent agents. STAR needs a **measured, deadline-aware runtime** that coordinates a small number of specialized capabilities while preserving the voice, game-rendering, and owner-control budgets.

This research refresh identifies five concrete corrections/opportunities:

1. **Use NVIDIA AIPerf for new inference benchmarking.** NVIDIA's GenAI-Perf repository now says it is being phased out and recommends AIPerf for new work. STAR's own stream probe remains useful for a lightweight local smoke test, but must not be presented as token-level ITL.
2. **Measure more than first response.** Add time-to-second-content (implemented in this branch), and compare it with AIPerf's TTFT, TTST, TTFO, ITL, inter-chunk latency, token counts, and server telemetry where available.
3. **Treat multiparty streaming as a hard intelligence problem.** MP-Bench, tau-Voice, Full-Duplex-Bench v3, LTS-VoiceAgent, and ModeratorLM point to separate requirements for comprehension, turn-taking, spoken task completion, interruption recovery, and role-aware participation.
4. **Build a versioned skill system, not a prompt scrapbook.** Voyager, SIMA 2, OpenGameEval, GameDevBench, SkillLearnBench, SkillRet, and Skill Retrieval Augmentation suggest an evidence-backed loop: retrieve → execute → verify in the environment → test on held-out situations → version or retire.
5. **Connect avatar, voice, game, and social state through one event timeline.** Live2D and VTube Studio provide practical parameter/event interfaces. The avatar should follow playback and current interaction state, not speculative generated text.

## 1. Repository reality and scope

The public README describes STAR v1.0.0 as a local-first Windows 11 chat application with optional local/server models, Roblox tooling, image generation, web search, Discord, and a reviewed Night School learning loop. It explicitly marks Studio Lab and advanced voice work as coming soon and warns that open PRs and passing CI do not mean features are in the installer.

The currently inspected development work includes separate draft PRs for live QoS, speech CPU reservation, audio device timing, callback metering, and streaming inference. These are useful foundations, but they are not a unified production VTuber runtime. Keep this distinction in release notes and user-facing capability claims.

A separate development PR (#1097) describes a 24-task broad general-knowledge evaluation. The checked-out inference branch's current `star/general_knowledge_benchmark.py` still contains a ten-task artifact-consistency suite. Reconcile that branch with #1097 before claiming the larger suite is part of the same integrated baseline; do not silently duplicate or overwrite the work.

## 2. Inference benchmarking update: AIPerf replaces GenAI-Perf for new work

NVIDIA's current GenAI-Perf README says the tool is being phased out and directs new performance benchmarking to **AIPerf**.

AIPerf's metrics reference distinguishes:
- **TTFT:** request start to first qualifying streamed token/chunk.
- **TTST:** time to the second qualifying streamed response.
- **TTFO:** time to first non-reasoning output, useful when a model emits reasoning before user-visible text.
- **ITL:** token-level inter-token latency when the token-count assumptions/telemetry support it.
- **ICL:** inter-chunk latency, explicitly different from token-level ITL.
- **Decode duration, input/output token counts, per-user throughput, and aggregate throughput.**

Important caveat: a streamed response chunk may contain multiple tokens. AIPerf documents assumptions for ITL and supports usage-based correction when the server provides the necessary per-chunk usage. Do not compare an API's arbitrary chunk gap to true token-level ITL.

### STAR implementation in this branch

`star/inference_benchmark.py` now reports:
- first non-whitespace content p50/p95;
- **time to second non-whitespace content chunk p50/p95**;
- request latency p50/p95;
- inter-chunk gap p50/p95;
- request and content-chunk throughput;
- success/failure counts.

The new second-content metric is a chunk-level analogue of TTST, **not** AIPerf TTST and not token-level timing. It helps identify a stream that starts quickly but stalls immediately after the first chunk.

The benchmark now rejects booleans/floats where integer request/concurrency limits are required, rejects non-string/empty endpoint and model labels, and validates that first-content time plus measured gaps cannot extend past request completion. These checks prevent misleading synthetic reports and ambiguous load profiles.

### Recommended AIPerf/STAR paired protocol

1. Pin STAR commit, backend build, model SHA-256, quantization, tokenizer, context, sampling options, GPU backend, CPU threads, KV type, slot count, and prompt-cache settings.
2. Run a warm-up phase not included in reported samples.
3. Use fixed prompts and output budgets; randomize baseline/candidate order.
4. Test concurrency equal to server slots, then a separately labelled overload point.
5. Capture TTFT, TTST, TTFO, ITL, ICL, request latency, output tokens/sec, request/sec, failures, and p50/p95/p99 where supported.
6. Compare the lightweight STAR probe to AIPerf on the same endpoint. Differences should be explained, not averaged together.
7. Repeat under idle, game-only, game+OBS+avatar, and full voice+game+OBS workloads.
8. Keep model quality checks paired with performance results. A faster but less accurate model is not a free speedup.

### llama.cpp server telemetry

The llama.cpp server documents an optional Prometheus-compatible `/metrics` endpoint. Depending on the exact pinned build, metrics include prompt tokens, predicted tokens, prompt/decode rates, KV-cache usage/tokens, requests processing, and requests deferred. The server also exposes slot monitoring.

Use this telemetry only when the owner explicitly enables it and the server build exposes it. Treat counters and gauges according to their semantics; do not subtract unrelated snapshots or infer per-request latency from aggregate rates. Record the server build and metric schema with each benchmark. Never expose an unauthenticated metrics endpoint to the public internet.

## 3. Local model speed: a hardware-aware experiment matrix

STAR's documented local target includes an 8 GB consumer GPU. The llama.cpp feature matrix updated 2026-11-08 lists backend support for K-quants, KV-cache quantization, MoE, and Flash Attention, but also notes backend performance differences; it says CUDA/ROCm are generally faster than Vulkan in many cases while acknowledging exceptions.

This is a reason to benchmark backend choices on the exact PC, not a reason to blindly change the shipping backend.

### Experiment order

| Experiment | Hypothesis | Must measure | Main risk |
|---|---|---|---|
| Shorter dynamic context | Less prefill and KV pressure | TTFT, quality, truncation | Lost context |
| Stable prompt prefix | More cache reuse | prompt tokens/s, TTFT, cached tokens | Cache invalidation / prompt drift |
| KV-cache quantization | Lower memory use, possibly more concurrency | VRAM/RAM, ITL, quality | Accuracy/latency regression |
| Speculative decoding | Draft accepted tokens reduce decode work | accepted/proposed tokens, ITL, total latency | Draft overhead / low acceptance |
| CUDA vs Vulkan build | Backend-specific kernel advantage | same model, prompts, power, VRAM, ITL | Build/driver variance |
| CPU/GPU layer placement | Better memory and compute balance | CPU per-core, GPU, PCIe, ITL | CPU bottleneck |
| Model residency policy | Avoid reload thrash | load time, VRAM, first-token tail | Stale or unavailable model |
| Slot/concurrency tuning | Balance throughput and latency | TTFT/ITL p95, deferred requests | Queueing / voice starvation |

For speculative decoding, llama.cpp documents draft-model and n-gram-cache approaches. A draft mechanism can accelerate generation when predictions are accepted, but the draft model itself consumes compute and memory. Test acceptance and end-to-end latency; do not infer benefit from the feature being enabled.

### Recommended model-router policy

Use a small, explicit capability matrix rather than loading every specialist simultaneously:

- fast conversational model for short acknowledgements and low-risk chat;
- stronger reasoning model for planning and difficult questions;
- coding model for repository/Roblox implementation;
- vision model only for image/screenshot tasks;
- speech models as separately budgeted realtime services.

Add residency hysteresis: do not unload/reload a model during a live stream merely because a background request arrived. Reserve VRAM for the game, OBS, avatar and active voice path. A route should be selected using measured p95 latency and current resource telemetry, not model-size labels or a static "best model" ranking.

## 4. Natural streaming: separate social intelligence dimensions

### MP-Bench

The October 2026 Findings of EMNLP paper evaluates voice agents as active multiparty participants. It measures turn-taking awareness, response appropriateness, and comprehension. Its evaluation of 12 agents found multiparty comprehension at or below 22% and turn-taking near chance. This shows that "transcribe chat and answer the latest message" is not enough for a natural VTuber.

### tau-Voice

The ICML 2026 paper evaluates grounded, full-duplex voice tasks with realistic audio and task completion. It reports a large gap between text and voice performance under clean and noisy conditions. Use it as a reminder to evaluate spoken task success, not just transcription or subjective naturalness.

### Full-Duplex-Bench v3

FDB-v3 uses human-recorded spoken requests, disfluencies, chained tool calls, latency and turn-taking. It is useful for testing whether STAR can handle self-correction and multi-step spoken requests without losing task state.

### LTS-VoiceAgent

LTS-VoiceAgent proposes a Listen–Think–Speak split: a background Thinker maintains state and reasons incrementally while a foreground Speaker owns the current spoken turn. Apply this cautiously:
- background predictions are speculative and cancellable;
- only the foreground turn may commit speech;
- interruption invalidates stale speech and stale tool proposals;
- completed facts remain recorded;
- unfinished work remains explicitly pending;
- STAR never reports a tool action complete merely because it narrated the action.

### ModeratorLM / role-aware turn-taking

Amazon Science's 2026 ModeratorLM publication describes conditioning a streaming voice agent on an explicit conversational role and reports improved turn-taking precision/recall on its evaluation setup. This suggests that STAR should have a declared stream role (host, co-op player, commentator, Q&A helper, quiet companion) rather than one generic policy. Treat the reported gains as a research result to replicate, not a guaranteed gain for STAR.

### Social Director state

Maintain a bounded, session-local conversation graph:
- anonymous speaker labels;
- who-addressed-whom hypotheses;
- current topics and unresolved questions;
- viewer-to-viewer vs viewer-to-STAR speech;
- confidence and expiry for each event;
- current stream role and owner override.

The Social Director should choose among **speak, backchannel, react silently, wait, ask a clarifying question, or yield**. Silence is a valid high-quality action. Do not maximize reply count.

Evaluate dyadic end-of-turn, interruption precision/recall, multiparty comprehension, response appropriateness, false interruptions, silence preservation, and task continuity separately. Do not collapse them into one "human score."

## 5. Avatar embodiment: VTube Studio + Live2D, playback-synchronized

Live2D Cubism documents mapping lip-sync effect IDs from the model's `.model3.json` and driving them with audio level or motion data.

VTube Studio's public API uses a local WebSocket plugin interface. Authentication is an explicit user approval flow; the API also supports event subscriptions and parameter/hotkey control. STAR should not bypass that approval.

### Proposed adapter boundary

`AvatarAdapter` should accept a small typed event stream, not raw LLM thoughts:
- `speech_started(turn_id, playback_epoch)`;
- `speech_level(turn_id, rms, timestamp)`;
- `viseme(turn_id, phoneme, timestamp)` when TTS alignment is reliable;
- `speech_cancelled(turn_id)`;
- `listening`, `thinking`, `laughing`, `surprised`, `confused`, `idle`;
- `attention_target(session_local_id)`.

Drive mouth movement from device/loopback playback time. If the voice is queued but not playing, the avatar should not lip-sync. On interruption, cancel the matching turn's viseme/envelope events and return to listening. Keep idle motion on a separate low-cost animation clock. Do not let expression intensity imply factual confidence.

## 6. Game mastery: from screenshots to reusable, verified skills

### SIMA 2

Google DeepMind's SIMA 2 research demonstrates a direction for language-guided action and learning in diverse 3D worlds. It is a research system, not a drop-in local package for STAR. Reuse its evaluation mindset: unseen environments, grounded actions, explicit goals and improvement through feedback.

### Voyager

Voyager's open-ended Minecraft agent combines automatic curriculum, an executable skill library, and iterative improvement using environment feedback and execution errors. The important transferable idea is a library of versioned procedures that can be composed—not an unverified memory of what the model said.

### OpenGameEval

Roblox's October 2026 OpenGameEval paper evaluates agents inside reproducible, stateful Roblox Studio sessions. It separates observation from editing and checks both scene changes and simulated play. The paper reports 84 core tasks, 13 evaluated models and 16 attempts per task; the best single-attempt pass rate was 51.7%, while five-of-five consistency was 39.4%. It also reports that inspecting touched objects before editing correlated with materially higher task success.

**Application:** require an exploration plan and read-only inspection before edits. Then make the smallest change in an isolated test place, run Luau checks, playtest, inspect screenshots/video, repair, and repeat on held-out scenarios.

### GameDevBench

The ICML 2026 benchmark contains 333 Godot game-development tasks across 2D/3D graphics and animation, UI and gameplay. The authors report that visual/image/video feedback improved task performance in their experiments. STAR Creator should therefore use screenshots and short clips as first-class test evidence, not merely ask a model whether its scene "looks right."

### Reusable skill artifact

Each skill should contain:
- stable skill ID and semantic tags;
- game/engine/version and control-map fingerprint;
- preconditions and required observation signals;
- bounded action sequence or executable procedure;
- expected state transition;
- success/failure checks;
- known failure modes and stop conditions;
- provenance and environment evidence;
- held-out transfer results;
- created/verified/last-used timestamps;
- superseded-by version.

Separate practice episodes from sealed validation. A skill is not mastered after one win. Re-run it across maps, seeds, opponents and game versions. Expire it when the game version or control/physics fingerprint changes.

### Skill retrieval and continual learning

SkillRet and Skill Retrieval Augmentation research show that retrieving the right skill from a large library is itself difficult. SkillLearnBench finds that skill generation quality must be evaluated at the skill, trajectory and outcome levels, and that self-feedback alone can drift. STAR should therefore:
1. retrieve a small candidate set;
2. check applicability and version;
3. execute in a sandbox/test environment;
4. score with external state checks;
5. revise from concrete errors;
6. evaluate on held-out tasks;
7. keep, version, or discard through the existing review gate.

Do not let an agent rewrite its own grader, sealed tests, signing keys, or promotion rules.

## 7. Game Creator and general knowledge

### Creator workflow

Use the same evidence discipline for Roblox, Blender, Godot and Unity:
1. inspect repository/scene and dependencies;
2. build a compact plan;
3. make isolated edits;
4. run static checks;
5. launch the real engine;
6. capture visual evidence;
7. play through the relevant mechanic;
8. inspect failures;
9. repair and rerun;
10. test an unseen scenario.

### Knowledge Lab

Route questions by evidence type:
- stable fact;
- current/time-sensitive fact;
- specialist reasoning;
- research synthesis;
- multimodal interpretation;
- action/task completion.

Store claims with source URL, publisher, publication date, retrieval time, exact supporting passage, scope, and confidence. Keep contradictory claims with provenance instead of silently merging them. Use freshness windows by domain: software APIs, game balance and prices expire much sooner than arithmetic or established history.

Evaluate factual accuracy, false-premise correction, citation support, stale-answer rate, calibrated abstention, domain balance and paraphrased holdouts. Keep answer keys outside the model and tool sandbox. Do not turn private viewer conversations into training data without explicit consent.

## 8. Unified runtime design

Prefer a single event-driven runtime with bounded workers over a swarm of always-on agents.

### Priority lanes

| Lane | Examples | Policy |
|---|---|---|
| P0 realtime | audio callback, playback, stop/interrupt, avatar timing | minimal bounded work; never wait on LLM |
| P1 interactive | speech inference, immediate game control | deadline-aware; reserve CPU/VRAM |
| P2 foreground | current viewer question, game strategy, tool result | bounded concurrency; cancellable |
| P3 background | research, skill distillation, long game analysis | pause/defer under live pressure |
| P4 maintenance | indexing, training experiments, backups | idle windows only |

Every task should carry a task ID, creation time, deadline, cancellation token, resource estimate, provenance and state:
`requested → accepted → running → paused/superseded → completed/failed → communicated`.

A task can be completed but not yet communicated. An interruption should supersede stale work without erasing completed evidence. Event messages need sequence numbers and TTL so delayed game observations or chat replies cannot be spoken as if current.

### Resource governor

The governor should observe CPU per-core load, RAM/commit, GPU utilization/VRAM, game frame time, audio underruns, OBS render skips, encoder skips and network drops. Keep the three OBS loss channels separate. Use hysteresis and cooldowns; avoid rapid model unload/reload oscillation. Defer research/training before degrading active speech or gameplay.

### Owner control and privacy

- Local-first remains the default; no silent hosted-model fallback.
- Voice, camera, screen, game control, Studio editing, VTube Studio, OBS control and public broadcasting are separate opt-in scopes.
- Read-only inspection before editing.
- Owner confirmation for publishing, monetization, public posts, purchases, account changes and destructive data operations.
- Credentials stay in OS credential storage; no secrets in prompts, logs or Git.
- Default telemetry is aggregate timings/counters; raw viewer audio/chat is not retained unless explicitly enabled with a clear purpose and retention policy.
- Provide a visible live indicator and immediate stop control.

## 9. Acceptance protocol

Run a private 60-minute session using a pinned game build, avatar, model, backend, OBS scene and hardware profile. Include quiet periods, busy chat, overlap, interruptions, combat, scene changes and background research.

Report:
- AIPerf TTFT/TTST/TTFO/ITL/ICL where supported;
- STAR first-content and second-content chunk timings;
- device/DAC/loopback first-audible timing;
- interruption-to-silence and audio underruns;
- multiparty comprehension and response appropriateness;
- avatar lip-sync error and cancellation correctness;
- game objective success, action freshness, p95/p99 frame time and 1%-low FPS;
- OBS render skips, encoder skips and network drops separately;
- CPU/RAM/VRAM peaks and deferred work;
- knowledge accuracy, source support, freshness and abstention;
- skill transfer on held-out maps/scenarios.

Use at least 20 matched baseline/candidate pairs for any configuration-promotion claim, with randomized order and identical task opportunities. A candidate must not win by speaking less, skipping difficult tasks, lowering game FPS, changing the scene, reducing output quality, or dropping audio. Passing makes a configuration eligible for a manually approved pilot; it does not automatically change live settings.

## 10. Recommended implementation sequence

1. Finish and verify the current streaming inference probe changes.
2. Add a version-pinned AIPerf invocation/export adapter (opt-in; do not add AIPerf as a runtime dependency).
3. Add llama.cpp metrics/slots snapshot support behind an explicit local-server diagnostics toggle.
4. Integrate the host's existing same-clock audio/OBS recorder with the benchmark manifest.
5. Add TurnBench-compatible dyadic scoring and MP-Bench-style multiparty scenarios.
6. Add task-state reconciliation for interruptions and superseded plans.
7. Implement the authenticated local VTube Studio adapter with an owner-visible permission flow.
8. Extend the existing game skill bank with applicability fingerprints and held-out transfer evidence.
9. Reconcile the 24-task general-knowledge PR with the current ten-task branch baseline.
10. Run the private mixed-workload acceptance protocol before changing defaults or publishing a new installer.

## Sources

- NVIDIA AIPerf metrics reference: https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- GenAI-Perf deprecation notice: https://github.com/triton-inference-server/perf_analyzer/blob/main/genai-perf/README.md
- llama.cpp server README and metrics: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp feature matrix (updated 2026-11-08): https://github.com/ggml-org/llama.cpp/wiki/Feature-matrix
- MP-Bench, Findings of EMNLP 2026: https://aclanthology.org/2026.findings-emnlp.1437/
- tau-Voice, ICML 2026: https://proceedings.mlr.press/v306/ray26a.html
- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- LTS-VoiceAgent, EMNLP 2026: https://aclanthology.org/2026.emnlp-main.1712/
- Adaptive turn-taking / ModeratorLM, Amazon Science: https://www.amazon.science/publications/adaptive-turn-taking-for-real-time-multi-party-voice-agents
- Live2D Cubism lip-sync manual: https://docs.live2d.com/cubism-sdk-manual/lipsync/
- VTube Studio official API repository: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket repository: https://github.com/obsproject/obs-websocket
- SIMA 2, Google DeepMind: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- OpenGameEval, Roblox: https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563
- GameDevBench, ICML 2026: https://github.com/waynchi/gamedevbench
- Voyager: https://arxiv.org/abs/2305.16291
- SkillLearnBench: https://arxiv.org/abs/2604.20087
- SkillRet: https://arxiv.org/abs/2605.05726
- Skill Retrieval Augmentation / SRA-Bench: https://arxiv.org/abs/2604.24594

## Evidence boundary

This document is a research and engineering plan. It does not claim benchmark wins, improved model weights, a faster RTX 4060, a live VTuber rehearsal, real game mastery, a production VTube Studio/OBS integration, or a shipped installer change. Only the code and tests committed on this branch are implementation changes; hardware and end-to-end validation remain outstanding.
