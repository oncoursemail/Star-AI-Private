# STAR: Device-Clock Evidence, Real-Time VTuber Runtime, and Generalist Learning

**Research date:** 2026-11-11  
**Scope:** Windows local-first voice, streaming, gaming, game creation, inference, memory, and general knowledge.

## Executive summary

STAR already contains substantially more of the required foundation than a fresh design would suggest. The current `star/next` tree includes a streaming call pipeline, PortAudio speaker, local hardware telemetry, stream QoS, a stream brain governor, interruption/Live2D bridges, Twitch EventSub, game closed-loop control, game-skill memory, paired game-transfer evaluation, a general-knowledge curriculum, model routing, and resource-aware agent planning.

The main engineering opportunity is therefore **integration with trustworthy end-to-end evidence**, not another large collection of disconnected feature modules.

This change addresses one precise gap: voice-call metrics previously stamped `first_audio_at` when PCM was submitted to the speaker queue. That is useful queue telemetry, but it is not the same as the time the output device is scheduled to play the first buffer. The PortAudio callback exposes both callback time and the DAC time for the first sample in its output buffer. STAR now maps that stream-clock difference onto the host monotonic clock and records it separately.

The new value is deliberately called `first_device_output_at`, not “human heard it.” It is a device-output estimate, not acoustic loopback and not proof that a remote stream viewer received the sound.

## Repository audit: reuse what already exists

The audit was performed against the `star/next` branch at base commit `88a9843865f729bee026f759a6dab719f757e14f` and the v1.0.0 release notes on `main`.

| Existing component | Current responsibility | Integration opportunity |
|---|---|---|
| `star/voice/call.py` | Streaming ASR, LLM tokens, sentence chunking, TTS, speculative ASR/reply, interruption, heard-text history | Carry device-output evidence through the same turn lifecycle |
| `star/voice/devices.py` | PortAudio microphone and interruptible speaker queue | Correlate callback time with scheduled DAC time |
| `star/voice/metrics.py` | Per-turn stage timings and aggregate latency summaries | Keep queue submission and device output as separate metrics |
| `star/stream_latency.py` | Bounded host-provided first-audible milestone window | Feed it only from a verified same-clock host adapter |
| `star/stream_hardware_telemetry.py` | Read-only CPU/RAM/VRAM, frame-present and local speaker-backlog telemetry | Keep all blocking probes off render/audio hot paths |
| `star/stream_qos.py` / `star/stream_brain_governor.py` | Measured inference admission and stream/game orchestration | Couple admission to fresh, real telemetry and worker-stop acknowledgements |
| `star/stream_interrupt_host.py` / `star/stream_stage.py` | Epoch-scoped audio stop, animation flush, avatar stage plans | Make audio and avatar cancellation one observable transaction |
| `star/stream_director.py` / `star/twitch_realtime_host.py` | Conversation signals and opt-in Twitch EventSub connection | Improve addressee, turn-taking, moderation and silence decisions |
| `star/game_closed_loop.py` | One-step observation/action/verification protocol | Keep action proposals fresh and non-blocking |
| `star/game_skill_memory.py` / `star/game_transfer_eval.py` | Evidence-backed skills and sealed paired holdout evaluation | Measure transfer across games and versions, not only practice success |
| `star/general_knowledge_lab.py` | Source-first knowledge curriculum | Add retrieval, provenance, freshness and transfer evaluation |
| `star/brain_router.py` / `star/agent_resource_planner.py` | Deterministic model routing and resource-aware specialist planning | Route by deadline, quality need, trust boundary and measured load |

### Shipping boundary

The root README on `main` describes STAR v1.0.0 as a Windows chat-first release. It labels advanced voice and Studio Lab capabilities as coming soon and explicitly says that open PRs, CI artifacts and passing tests do not mean a feature is in the installer. Treat this research branch as development work, not as a shipped VTuber product.

## Implemented in this branch: separate speaker submission from device output

### Why the distinction matters

The previous voice metric `first_audio_at` is recorded immediately before `speaker.play(...)`. In `SoundSpeaker`, that method appends PCM to an application-owned byte buffer. The PortAudio callback later removes bytes from that buffer and supplies an output buffer to the audio backend.

These are separate events:

1. Text was generated.
2. TTS produced PCM.
3. PCM was submitted to STAR's speaker queue.
4. PortAudio invoked the output callback.
5. The callback buffer was scheduled for DAC output.
6. The operating system/device rendered it acoustically.
7. OBS encoded/muxed it.
8. A remote viewer received and decoded it.

A single “first audio” timestamp cannot truthfully represent all eight.

### PortAudio timing model

PortAudio's `PaStreamCallbackTimeInfo` provides:

- `currentTime`: when the callback was invoked.
- `outputBufferDacTime`: when the first sample in that output buffer will be sent to the DAC.

The values share the stream time base. STAR samples host `time.monotonic()` at callback entry and estimates:

```text
estimated_host_dac_time =
    host_monotonic_at_callback
    + max(0, outputBufferDacTime - currentTime)
```

The implementation rejects missing, non-finite or implausible clock offsets rather than fabricating a timestamp.

### Code changes

- `star/voice/devices.py`
  - Adds a bounded PortAudio-to-host monotonic clock conversion helper.
  - Captures the first non-empty callback buffer's scheduled DAC time.
  - Resets that observation with the speaker's per-reply reset.
  - Exposes it through an optional `first_device_output_at()` method.
- `star/voice/call.py`
  - Reads the optional measurement when a reply settles.
  - Uses it only when the call uses the default `time.monotonic` clock, avoiding accidental comparison of unrelated clock domains.
  - Preserves compatibility with speakers that do not implement the optional method.
- `star/voice/metrics.py`
  - Adds `first_device_output_at`.
  - Keeps `total` as the legacy speech-end-to-speaker-submission metric.
  - Adds separate submission-to-device and speech-end-to-device measurements.
  - Rejects a device-output stamp that precedes the earliest recorded audio submission.
- Tests add deterministic clock-mapping, metrics and fake-speaker integration coverage.

### Evidence boundary

This timestamp is a PortAudio scheduled-DAC estimate. It does **not** prove acoustic output, account for every device/driver buffering behavior, establish that a human heard the sound, or prove that OBS or Twitch delivered it. A Windows WASAPI loopback/IAudioClock adapter and an OBS/remote-monitor measurement remain necessary for stronger end-to-end evidence.

## Research findings and design implications

### 1. Voice: think incrementally, speak only when the turn is stable enough

**LTS-VoiceAgent (arXiv:2601.19952, 2026-01-26)** proposes a Listen-Think-Speak architecture with semantic triggers, a background thinker, a foreground speaker and speculative work that can be rolled back. It addresses the latency/quality tradeoff in cascaded ASR → LLM → TTS systems.

Implications for STAR:

- Preserve the existing speculative ASR path.
- Keep speculative replies opt-in until interruption and rollback tests pass on real microphones and speakers.
- Let a background state-maintenance path track context while the foreground path handles the next spoken clause.
- Start work on meaningful semantic prefixes, not arbitrary tiny token fragments.
- Cancel stale speculative work immediately when the speaker resumes.
- Measure accuracy, cancellation waste, first-device-output latency and turn errors together. Lower latency alone is not a win if the wrong words are spoken.

### 2. Real-time gaming: the world must not wait for the model

**ROAR (arXiv:2610.24282, 2026-10-16)** studies multimodal agents in multiplayer action-shooter settings where the environment advances while inference is running. Its asynchronous environment/agent interface highlights a core problem: a correct action that arrives after the situation changes may no longer be useful.

Implications for STAR:

- Keep game simulation/presentation and model reasoning on separate clocks/threads.
- Every proposed action should include the observation sequence, game/session identity, creation time, deadline and expected state transition.
- Drop an action when its source frame is stale, the game/session changes, the player state diverges or its deadline expires.
- Prefer a fast reactive controller for movement/reflexes and an asynchronous strategic planner for map/objective reasoning.
- The strategic planner may suggest goals, but it must not overwrite a newer reactive observation.
- A host-owned game adapter remains the only component allowed to dispatch approved input.

### 3. Game mastery: verify state, not persuasive explanations

**GameWorld (arXiv:2604.07429, 2026-04-08)** contains 34 browser games and 170 tasks with state-verifiable outcomes. The authors report that the evaluated agents still fall well short of human gameplay capability and identify latency, context memory and action validity as important issues.

Implications for STAR:

- Evaluate objective completion, damage/deaths, resource use, route efficiency and action validity from environment state where possible.
- Keep game/version/level/seed cohorts separate.
- Compare candidate skills against a baseline on matched, sealed holdout situations.
- Count missing runs as incomplete, never as wins.
- Test skill transfer to a different map, version or game mechanic before promoting a skill.
- Use screenshots/video for visual diagnosis, but use authoritative game state for scoring whenever available.

### 4. Continual learning: distinguish reusable knowledge from memory interference

**AGENTCL (arXiv:2606.02461, 2026-06-01)** argues for controlled task streams that deliberately test whether prior solutions transfer to later tasks. It also highlights that memory can degrade performance when irrelevant or unreliable experiences are reused.

Implications for STAR:

- Store experiences with source, task, software/game version, environment, outcome, confidence and expiry/revalidation conditions.
- Separate episodic memory (what happened), semantic memory (what is supported) and procedural memory (how to do a verified task).
- Test transfer and interference, not just retrieval accuracy.
- Keep practice, validation and sealed holdout splits separate.
- A memory retrieved successfully is not automatically true or current.

### 5. Local inference: optimize the real mixed workload

The upstream llama.cpp server architecture documents multiple request slots, shared batching, prompt checkpoints and router mode. The project also documents speculative decoding and prompt-cache controls.

Implications for STAR:

- Pin the exact llama.cpp build, model file/hash, quantization, context, slot count, batch settings and device split for every benchmark.
- Measure prompt processing, time-to-first-token, inter-token latency, p50/p95 end-to-end response and peak RAM/VRAM.
- Test the actual concurrency Star uses: voice, chat, game control, vision and background agents.
- Match benchmark concurrency to configured server slots.
- Compare prompt-cache and speculative-decoding configurations with paired workloads; keep them only when quality is unchanged and end-to-end latency improves.
- Avoid importing speed claims from datacenter GPUs to an 8 GB consumer GPU.
- Use deterministic lightweight routing for simple acknowledgements; reserve stronger reasoning for strategy, code, research and unfamiliar tasks.
- Keep provider/trust boundaries explicit. A local-only request must never silently route private context to a hosted model.

### 6. Streaming health: diagnose the correct bottleneck

OBS distinguishes rendering lag, encoding lag and network-dropped frames. They occur at different pipeline stages and require different fixes.

Implications for STAR:

- Record OBS render lag, encoder lag and network drop separately.
- Record game frame-time p50/p95/p99 and 1% low, not just average FPS.
- Record audio underruns, speaker queue depth, interruption-to-device-stop, CPU/GPU/VRAM/RAM and inference latency.
- Degrade background vision/research/training before sacrificing the live speech path.
- Use hysteresis so a single healthy frame does not restore expensive workloads.
- Do not assume a high FPS average means a smooth stream.

### 7. Roblox and creator autonomy: granular permissions, separate environments

Roblox's Studio MCP Open Cloud documentation (updated November 2026) states that scopes are configured per game and per person. It distinguishes safe, balanced, full-access and custom levels and identifies high-risk capabilities such as publishing, monetization, player restrictions, secrets and live data-store writes.

Implications for STAR Creator:

- Default to read-only inspection and disposable test experiences.
- Grant only the scopes required for the current task.
- Treat asset uploads, publishing, monetization, player consequences, secrets and live data writes as separate operations.
- Build → run → playtest → inspect → repair → retest.
- Verify the actual Studio result, not only generated Luau or successful API responses.
- Record asset provenance and the target experience/version.

## Target architecture: one real-time runtime, several specialist brains

```text
                    TRUSTED LOCAL HOST
                           |
       +-------------------+-------------------+
       |                   |                   |
   Audio/Voice         Game/Window          OBS/Avatar
   capture/output      observations         telemetry
       |                   |                   |
       +-------------------+-------------------+
                           |
                    EVENT / CLOCK BUS
                           |
       +-------------------+-------------------+
       |                   |                   |
  Social Director     Reactive Game       Stream QoS /
  & Turn Manager      Controller          Deadline Scheduler
       |                   |                   |
       +-------------------+-------------------+
                           |
                STRATEGIC / RESEARCH BRAINS
                           |
       +-------------------+-------------------+
       |                   |                   |
   Game Strategy       Creator Brain       Knowledge Lab
       |                   |                   |
       +-------------------+-------------------+
                           |
                Evidence + Memory Fabric
                           |
             independent scoring / holdouts
                           |
               owner-reviewed promotion
```

The event bus should carry bounded typed events and same-host monotonic timestamps. It should not carry raw microphone audio, full chat logs, private viewer data or model-generated “proof” of hardware state into the scheduler.

## Capabilities to build next

### Social Director and natural VTuber behavior

- Speaker/addressee tracking for owner, guests and viewer-to-viewer conversation.
- Turn-taking, silence preservation, backchannel and interruption policies.
- Conversation topic continuity without responding to every message.
- Natural prosody, pacing, laughter and short acknowledgements with rate limits.
- Emotion as a bounded expression cue, not a factual claim about a viewer.
- Avatar mouth/viseme motion synchronized to actual playback epochs.
- On interruption: cancel generation, stop the correct audio epoch, flush stale avatar frames, confirm both acknowledgements, then return to listening.
- Clear disclosure that Star is an AI character; natural interaction should not depend on pretending she is a human operator.

### Gamer and game-learning systems

- Visual perception plus semantic game-state extraction.
- Fast reactive movement/combat controller.
- Asynchronous strategic planner.
- Skill library with preconditions, state transitions, recovery and game-version scope.
- Practice curriculum that varies maps, seeds, opponents and objectives.
- Independent outcome scorer and sealed transfer tests.
- Human-readable post-game review: what worked, what failed, what changed and what to practice next.

### Creator Brain

- Roblox/Luau, Blender, animation, VFX, audio, lighting, UI, networking and level design.
- Project inspection before editing.
- Asset budgets and provenance.
- Disposable Studio test place and multi-client playtests.
- Screenshot/recording inspection plus authoritative game-state checks.
- Automated regression tests for gameplay, UI scaling, performance and server/client trust.
- Never promote a project merely because scripts compile.

### Knowledge Lab

- Source-grounded research with date, author, version and primary-source preference.
- Claim/evidence separation and conflicting-source tracking.
- Freshness policies for APIs, libraries, products and current events.
- Retrieval tests and cross-domain transfer tasks.
- Keep general knowledge separate from personal memory and game-specific procedural skills.
- Do not fine-tune on unreviewed chat, viewer messages or model-generated claims.

## Mixed-workload acceptance protocol

Run on the actual Windows 11 target machine, with the exact model/runtime build recorded. Repeat each configuration at least three times after warm-up; use paired baseline/candidate runs and do not pool different games, scenes or model versions.

Record:

| Area | Required measurements |
|---|---|
| Voice | Speech-end→first token, first TTS chunk, speaker submission, estimated DAC output, WASAPI loopback output, interruption→confirmed silence |
| Conversation | Addressee accuracy, false interruption, missed response, silence precision, answer quality |
| Game | Frame-time p50/p95/p99, 1% low, objective success, deaths/failures, action expiry rate |
| OBS | Rendering lag, encoding lag, network drops, reconnects |
| Runtime | CPU, RAM, GPU utilization, VRAM, audio underruns, worker restarts |
| Inference | Prompt tokens, TTFT, inter-token latency, tokens/sec, p95 request latency, cache hit/restore behavior |
| Learning | Baseline vs candidate on sealed matched holdouts, transfer to unseen maps/versions, regression rate |
| Creator | Engine test pass, visual regression, server/client security checks, performance budget |

### Promotion gates

- No background task may degrade the speech or game frame-time guardrails.
- A device-output timestamp is not accepted as remote-viewer delivery evidence.
- Any clock-domain mismatch or stale telemetry makes the relevant metric unknown.
- A route that has insufficient measurements is not declared faster.
- A candidate model/skill is not promoted on practice data alone.
- A failed or incomplete trial cannot be silently omitted from the report.
- No automatic live publishing, monetization, player-data writes or public broadcast is enabled by a benchmark pass.

## Source register

1. PortAudio, `PaStreamCallbackTimeInfo`: https://files.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html — documents callback/current time and first-sample DAC time in the stream time base.
2. python-sounddevice callback documentation: https://python-sounddevice.readthedocs.io/en/latest/api/streams.html — callback time information and real-time callback constraints.
3. PortAudio callback contract: https://github.com/PortAudio/portaudio/blob/master/include/portaudio.h — callback runs at high/real-time priority; avoid blocking, file I/O and unpredictable work.
4. LTS-VoiceAgent, arXiv:2601.19952 (2026-01-26): https://arxiv.org/abs/2601.19952 — semantic-triggered Listen-Think-Speak orchestration.
5. ROAR, arXiv:2610.24282 (2026-10-16): https://arxiv.org/abs/2610.24282 — asynchronous real-time multiplayer game-agent evaluation.
6. GameWorld, arXiv:2604.07429 (2026-04-08): https://arxiv.org/abs/2604.07429 — 34 games, 170 tasks and state-verifiable outcome evaluation.
7. AGENTCL, arXiv:2606.02461 (2026-06-01): https://arxiv.org/abs/2606.02461 — controlled continual-learning streams and memory interference.
8. llama.cpp server development documentation: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md — slots, shared batching, prompt checkpoints and router mode.
9. llama.cpp speculative decoding documentation: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md — draft/verification modes and benchmark caveats.
10. OBS encoding performance troubleshooting: https://obsproject.com/kb/encoding-performance-troubleshooting/ — game frame caps and GPU headroom.
11. Roblox Studio MCP Open Cloud permissions: https://create.roblox.com/docs/studio/mcp-open-cloud — per-game/per-person scopes and risk tiers.

## Implementation status and limitations

- This branch adds a PortAudio scheduled-DAC estimate to the existing voice metrics and tests the clock conversion without opening a real audio device.
- GitHub Actions on this branch must complete before the code is considered CI-verified.
- No physical Windows audio device, WASAPI loopback, OBS, RTX 4060, Roblox Studio, game session or public livestream was exercised by this change.
- No measured speedup, improved game win rate, human-equivalent behavior or remote audience delivery is claimed.
- The existing v1.0.0 installer remains unchanged until reviewed changes are merged through the normal release process.
