# STAR Research — Resource-Aware Streaming, Inference and Game-Agent Runtime

**Research date:** 2026-11-11  
**Implementation branch:** `feat/stream-workload-admission-20261111`  
**Working source repository:** `oncoursemail/Star-AI-Project`  
**Release/download repository:** `oncoursemail/Star-AI`

## Executive summary

STAR needs to become a coordinated real-time system, not a collection of agents that all compete for the same CPU, RAM, VRAM, model slots, audio device and GPU. The highest-leverage infrastructure improvement in this change is a bounded workload-admission policy that protects audio, voice, avatar and game-control work from research, memory consolidation, asset generation and other background jobs.

This PR adds the policy and offline tests only. It deliberately does not start processes, control devices, change model settings, or connect OBS/VTube Studio/Roblox. A Windows host adapter must first measure real resource use, calibrate a per-machine budget, and supply a fresh health signal. The feature must remain disabled until that adapter and the private-stream acceptance suite exist.

## Repository facts discovered during the audit

The current source README describes STAR v1.0 as a Windows 11, local-first, chat-first application. It already has a local llama.cpp path, an optional CPU-only STAR Server, an opt-in provider list, Roblox documentation and Studio tooling, design checks, Blender adapters, Discord, and a 300-task night-school loop with a paired statistical gate.

The README explicitly marks the full voice experience and Studio Lab as coming soon. It does not claim that a production VTuber runtime, always-on game controller, VTube Studio adapter, or autonomous live streamer is shipped.

The source architecture and code also establish important constraints:

- `star/local_runtime.py` starts one managed model router, uses `--models-max 1`, and currently passes `-np 1`. This is a conservative single-slot baseline, not proof that one slot is optimal.
- `star/providers.py` gives local inference one parallel call by default; the STAR Server allows an owner-configured one or two calls. Provider ceilings should remain separate from the new cross-workload scheduler.
- `star/context_layout.py` and `star/agent.py` preserve a byte-stable prefix and append-only history to support llama.cpp prompt-cache reuse. New per-turn material belongs in volatile context, not in the stable prefix.
- `star/orchestration.py` is a deterministic dependency/resource-scope planner. Its own module documentation says it does not spawn subagents.
- The v1.0 README reports that answer quality is about the same as v0.9.0 and that the bundled lesson file is empty. Night school and lesson review are the correct existing path for verified improvements; this PR does not change model weights or claim a smarter model.
- The recent rehearsal/memory work is still an unmerged PR stack. PRs #1135–#1139 add offline evaluation, recording, diagnostics and optional cross-session continuity. They do not yet wire a live streamer or Windows device adapters.

The code source is `oncoursemail/Star-AI-Project`; `oncoursemail/Star-AI` is the small public website/download repository. New source code belongs in the former, not in the release repository.

## Implementation in this PR

### `star/stream_workload_admission.py`

A pure, bounded admission controller for these work lanes:

| Lane | Purpose | Reserve access |
|---|---|---|
| `audio` | Already-scheduled speech playback work | Yes |
| `game_control` | Time-sensitive input/observation step | Yes |
| `voice` | Interactive speech turn and low-latency inference | Yes |
| `avatar` | Time-sensitive avatar parameter updates | Yes |
| `interactive` | User-facing chat/tool work | No |
| `research` | Web/research and long-form analysis | No |
| `learning` | Night school, memory consolidation and evaluation | No |
| `asset_generation` | Image/video/3D generation and other heavy creative jobs | No |

Resource claims are explicit vectors of CPU millicores, RAM MiB and VRAM MiB. The host supplies a **STAR allocation budget**, not raw installed hardware totals. That budget must already leave room for Windows, the game, OBS, graphics drivers and other fixed work.

The controller provides:

- A configurable reserve for latency-sensitive lanes.
- Strict deterministic priority and FIFO ordering within a priority; a blocked higher-priority request fences lower-priority lanes, while another fitting request at the same priority may still proceed.
- Bounded queues, active leases and replay-ID history.
- Request deadlines and lease expiry.
- Explicit release and queued cancellation; an expired lease continues reserving capacity until the host confirms the worker has stopped.
- A fresh host-health requirement before non-protected work is admitted.
- Fail-closed behavior for missing, stale, future-dated or degraded health.
- Aggregate snapshots with no request IDs, task text, prompts or user content.
- No automatic preemption: the host must own cancellation semantics for active workers.

### Why this policy is deliberately not a process manager

The controller does not know whether a claimed 1,000 CPU millicores actually costs one core on a particular model, or how much VRAM a specific generation request needs. Those values must come from measured, versioned host profiles. Inventing them inside a generic library would create false safety.

The policy therefore separates three layers:

1. **Measurement adapter:** reads approved Windows/OBS/game/audio/model counters and emits bounded aggregates.
2. **Admission policy:** decides whether a declared workload can be admitted under a calibrated budget.
3. **Host executor:** starts, cancels and monitors the real task using existing permissions and cancellation rules.

The new module implements only layer 2.

## Research findings and design implications

### 1. Inference throughput is not the same as interactive latency

The official llama.cpp server supports parallel decoding, continuous batching, monitoring endpoints and speculative decoding. Those capabilities are worth testing, but STAR's current local router deliberately uses one parallel slot. Increasing `-np` without measuring context/KV-cache pressure, time-to-first-token and inter-token latency could make the live experience worse.

Recommended experiment matrix:

- Keep the current single-slot configuration as the baseline.
- Test two slots only on a repeatable workload and with the same model, quantization, context and prompt set.
- Measure TTFT, time per output token, end-to-end duration, throughput, queue delay, peak RAM/VRAM and task quality.
- Repeat with simultaneous voice, gameplay, OBS and background activity.
- Reject any candidate that increases task throughput but violates the interactive latency or game-frame budget.

Official llama.cpp server documentation: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

OpenTelemetry's current GenAI conventions define server request duration, time-to-first-token, time-per-output-token and token usage. These should be recorded as separate measurements. Do not report process-wide tokens/second as per-request latency.

OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

### 2. Prefix caching only helps the work it actually caches

vLLM's Automatic Prefix Caching documentation explains that a shared prefix can skip repeated prefill, but it does not make autoregressive decoding faster. STAR already has a stable-prefix/context-layout design for llama.cpp. Preserve that design, measure cache hits and prefill time, and do not promise a decode-speed improvement from prefix caching alone.

vLLM APC documentation: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/

### 3. Real-time voice requires turn policy, not just faster text generation

LiveKit's turn-taking documentation covers adaptive interruption handling, false-interruption recovery and playback truncation to the portion the listener actually heard. Its tuning reference also documents preemptive generation and preemptive TTS; preemptive TTS is a compute/latency tradeoff, not a free optimization.

For STAR:

- Separate speech detection, turn confirmation, model generation, TTS generation, queue submission and actual playback acknowledgement.
- Treat short acknowledgements ("mm-hmm", laughter, coughs and background noise) differently from a real barge-in.
- If a false interruption is detected, resume only the unheard remainder; do not replay already-audible speech.
- Keep preemptive TTS off until paired tests show that its latency benefit exceeds wasted compute and cancellation cost.
- Preserve silence as a valid action. Do not make Star speak continuously just to appear active.

LiveKit turn handling: https://docs.livekit.io/agents/logic/turns/  
LiveKit turn tuning: https://docs.livekit.io/agents/logic/turns/tuning/

### 4. OBS has distinct rendering and output failure modes

OBS WebSocket's `GetStats` response exposes separate render-thread and output-thread skipped-frame counters. These must not be combined into a single "stream lag" score: render pressure and encoder/output pressure point to different bottlenecks.

For STAR's host adapter, collect deltas within a single OBS process epoch, keep render and output counters separate, and report rate over a recent interval rather than alarming forever because of an old cumulative count. Never send the OBS password to the model.

OBS WebSocket source: https://github.com/obsproject/obs-websocket  
GetStats implementation: https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp

### 5. VTube Studio control is an explicit plugin permission

The official VTube Studio API requires plugin authentication and an in-app user approval step before the plugin can control the application. STAR should use a dedicated local adapter with an allowlist of parameter IDs and hotkeys, bounded values, rate limits, connection-state checks and revocation handling. Tokens belong in OS-backed credential storage and must never enter prompts, logs or repository files.

Official API README: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

### 6. Game mastery needs observation, practice, held-out evaluation and transfer

OpenGameEval runs agents in reproducible Roblox Studio sessions and scores both edited scenes and simulated play. Its October 2026 paper reports 84 core tasks and finds that inspecting objects before editing correlates with better task success. This supports an inspect-first workflow and an executable game-development benchmark, not blind code generation.

STAR should:

1. Observe the actual place and relevant objects.
2. Form a bounded plan.
3. Edit only the selected disposable/test place.
4. Run executable checks and simulated play.
5. Inspect failures and repair.
6. Store only verified practice skills.
7. Evaluate transfer on held-out tasks and different game versions.

Keep observation tools separate from editing tools. Keep practice, development and holdout results in separate evidence lanes. Never use a model's own self-rating as the only proof that a game works.

OpenGameEval paper: https://arxiv.org/abs/2610.02563  
OpenGameEval code: https://github.com/Roblox/open-game-eval

SIMA 2 demonstrates a research direction for agents that perceive, reason and act in 3D worlds. Voyager demonstrates automatic curricula, an executable skill library and iterative environment-feedback loops. These are architectural inspirations, not plug-and-play game controllers for STAR.

SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/  
Voyager: https://arxiv.org/abs/2305.16291

### 7. General knowledge and procedural skills should remain distinct

A factual answer should be supported by retrievable sources and freshness metadata. A procedural skill should be supported by repeatable execution evidence. An episodic memory should describe a verified past event. These are different evidence types and should not be collapsed into one "confidence" score.

Recommended general-knowledge loop:

- Retrieve sources with publication/update dates.
- Prefer primary references and authoritative documentation.
- Store source provenance and version.
- Generate a concise explanation.
- Ask a held-out question or run a task that tests application, not verbatim recall.
- Mark uncertain, conflicting or outdated facts as such.
- Require independent review before converting generated material into a durable lesson.

This builds on STAR's existing project knowledge, citations, 300-task night school, correction-to-test workflow and paired lesson gate. It does not require model-weight changes.

## Recommended unified STAR runtime

The eventual host architecture should be:

```text
Windows host telemetry
  ├── CPU / RAM / VRAM budget
  ├── model server queue, TTFT, output-token time
  ├── audio queue / playback acknowledgement
  ├── OBS render and output counters
  └── game frame-time / input acknowledgement
             |
             v
     Health + budget adapter
             |
             v
   WorkloadAdmissionController
      ├── protected: audio / voice / avatar / game control
      ├── interactive: chat / user tools
      └── background: research / learning / asset generation
             |
             v
       Host-owned executor
      ├── model/provider limits remain enforced
      ├── existing tool policy remains enforced
      ├── task write scopes remain enforced
      └── cancellation and shutdown remain host-owned
```

Do not let a model assign itself resource claims or override the scheduler. The host maps known task types to reviewed resource profiles. Unknown task types are rejected until a profile is reviewed.

## Human-natural VTuber behavior: target loop

"Human-like" should mean natural interaction quality, not deception about being a human. The stream loop should be grounded in real input and verified game events:

1. Listen to the current conversation.
2. Determine whether Star is being addressed and whether a turn is complete.
3. Decide to respond, acknowledge briefly, or remain silent.
4. Generate a response using only relevant, current context.
5. Produce speech and schedule it under the audio lane.
6. Wait for playback acknowledgement.
7. Drive avatar mouth/expressions from actual speech and selected bounded expression events.
8. Update only approved session/game memories.
9. Avoid repeating a callback already spoken in the current stream.

Viewer-level memory, private messages and personal details should not become permanent stream memory by default. A public persona can have stable interests and continuity without pretending to possess human consciousness or a human biography.

## Phased implementation plan

### Phase A — this PR
- Add pure workload lanes, resource vectors, reserves, bounded queue/lease lifecycle and aggregate diagnostics.
- Add offline tests for resource accounting, priority, health staleness, expiry, duplicate IDs and no-preemption behavior.
- No runtime wiring or default changes.

### Phase B — Windows measurement adapter
- Use process/system counters for CPU and RAM.
- Use supported GPU telemetry for VRAM/engine pressure.
- Use OBS WebSocket GetStats with local authentication.
- Use the audio host's queue and playback acknowledgements, not raw audio capture.
- Use PresentMon/ETW or a supported game telemetry adapter for frame-time observations.
- Normalize producer restarts with epochs; never difference cumulative counters across epochs.
- Store aggregate metrics locally with bounded retention; no viewer content or credentials.

### Phase C — calibrated host profiles
- Measure the machine while idle, while the game runs, while OBS renders, and under mixed stream load.
- Set STAR's allocation budget below measured safe capacity.
- Set real-time reserve from observed p95/p99 burst demand plus an operator-selected safety margin.
- Version every profile by machine, model, quantization, context length, server build, OBS scene and target game.
- Recalibrate when any of those change.

### Phase D — host executor integration
- Route only known task types through the controller.
- Keep existing provider call limits and tool policy as independent hard limits.
- Add cancellation tokens and graceful shutdown for background workers.
- Never preempt an active process merely because a new request has higher priority.
- Add an owner-visible "stream protection" status and reason for deferred work.

### Phase E — private-stream acceptance
Run repeated, matched sessions with:
- Chat only.
- Game + OBS.
- Voice + avatar.
- Game + OBS + voice.
- Full mixed load with background research/learning enabled.

Record p50/p95/p99 for first content, first audible, inter-token time, game frame time and playback/avatar synchronization. Record audio underruns, OBS render skips and output skips separately. Compare the same workload with background work disabled and enabled.

A candidate is accepted only if:
- No protected-lane deadline miss or audio underrun regression occurs.
- Game frame-time and OBS limits remain inside operator budgets.
- Voice turn precision/recall and task recovery do not regress.
- Background work is deferred during degraded health and resumes only after a fresh healthy signal.
- Task quality and held-out game-skill transfer are non-inferior.
- The measured improvement is repeatable across multiple runs.

## Acceptance and limitations

- The new controller is a policy primitive, not a running scheduler or OS resource governor.
- Resource values are abstract host allocations; no actual CPU/RAM/VRAM telemetry is read.
- No Windows, RTX 4060, OBS, audio, VTube Studio, Roblox Studio, gameplay or livestream test was performed in this PR.
- No measured speedup, intelligence gain, game mastery or production readiness is claimed.
- The controller does not change provider/model selection, model parallelism, prompt caching, permissions, memory retention, stream behavior or installer defaults.
- The new feature must remain unwired until a trusted host adapter supplies calibrated budgets and health.
- All changes remain on a draft PR stacked on the existing stream-continuity work; production `main` remains unchanged.

## Sources

1. llama.cpp server documentation — https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
2. OpenTelemetry GenAI metrics — https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
3. vLLM Automatic Prefix Caching — https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
4. LiveKit turn handling — https://docs.livekit.io/agents/logic/turns/
5. LiveKit turn tuning — https://docs.livekit.io/agents/logic/turns/tuning/
6. OBS WebSocket — https://github.com/obsproject/obs-websocket
7. OBS GetStats — https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp
8. VTube Studio API — https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
9. OpenGameEval paper — https://arxiv.org/abs/2610.02563
10. OpenGameEval source — https://github.com/Roblox/open-game-eval
11. Google DeepMind SIMA 2 — https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
12. Voyager — https://arxiv.org/abs/2305.16291
