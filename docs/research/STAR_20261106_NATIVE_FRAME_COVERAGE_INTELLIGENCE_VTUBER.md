# STAR AI — Native-game frame coverage and research-backed VTuber roadmap
**Date:** 2026-11-06 · **Status:** implemented opt-in Python measurement guard; research directions are proposals, not deployed skills.

## 1. Finding: native roundtrip latency needs a denominator

The prior native Windows roundtrip auditor measures a request after an already-approved game host has captured a frame, reasoned, and dispatched an existing worker/watchdog port. It separately reports *capture-to-decision*, *native call duration including release*, and *capture-to-host-return* p95. That design correctly avoids representing a blocking key-release roundtrip as a key-down timestamp.

However, **an instrument that counts only successfully dispatched inputs can report low p95 while the agent ignores difficult frames**. Measuring fewer actions also conceals a perfectly reasonable control decision—deliberate silence / no-op—that must be accounted for when evaluating reaction policy.

### New implemented contract

An explicitly opted-in `NativeGameRoundtripAudit(require_frame_coverage=True)`:
- Accepts *host-observed* input frames with strictly contiguous 1-based `frame_sequence` values (maximum 256 per bounded window). A gap, replay, duplicate, boolean or out-of-order sequence revokes the **entire** measurement window; legacy callers retain their original unnumbered API.
- Requires `decision_ready()` for every frame. The host must then choose exactly one of `execute(action, hold_ms)` (same existing bounded Windows input port) or `no_action()` (a measured no-op, without OS input).
- Rejects stale no-ops rather than treating them as consequence-free fast decisions; requires an independently sourced, **host-declared** total `seal_frames(expected_frames=N, host_verified=True)` before `finalize()`. Both counts must equal the number of contiguous observed frames and the sum of attempted actions and deliberate no-ops.
- Reports `observed_frames`, `no_action_frames`, `host_frame_coverage_declared`, and **`all_frame_decision_p95_ms` including no-ops**. Native call and full roundtrip p95 still describe only *actual dispatched* inputs and must never be labeled all-frame latency.
- Revokes rather than cherry-picking successful earlier frames whenever a future frame is missing, a late request occurs, the native port fails, focus/key-up cannot be confirmed, or a host deadline is violated.
- **Does not** ingest screenshots, read a live game, spawn models, train, start OBS, manage the OS, or broadcast. No observed action ID, image, speech, player name or model response appears in the report.

**Representative trusted host usage (pseudocode; not a ready-to-run launcher):**

```python
# The host FIRST owns approved game identity, WindowsGameInputPort, OBS
# permissions, independent frame source and physical emergency stop.
audit = NativeGameRoundtripAudit(port, owner_approved=True, require_frame_coverage=True)
for frame in verified_host_frames:  # actual, consecutive engine-host enumeration
    audit.capture(frame_sequence=frame.sequence)
    decision = reason_without_blocking_capture(frame)
    audit.decision_ready()
    if decision.kind == "no_action":
        audit.no_action()
    else:
        audit.execute(decision.action_id, decision.hold_ms)

# Count comes from separate host frame source, NOT from audit.report().
audit.seal_frames(expected_frames=trusted_frame_source.frame_count, host_verified=True)
report = audit.finalize()
# STILL not proof the game saw any key press or changed state.
```

**Threat / epistemic boundary:** A model could falsely claim `host_verified` if an embedding application exposed that parameter to untrusted input. Never do so. This interface checks internal sequence consistency and an asserted external total; it does **not** cryptographically authenticate a frame source or detect frames omitted from *both* the frame source and auditor. The actual game-state observer should use engine/server-owned samples, protected signing keys and an independent scorer. An OS key-release receipt is still not evidence of world movement, a win, skill improvement, or physical hardware state.

## 2. Where real intelligence gains can arise

STAR already has nontrivial foundations: a signed `VerifiedGameStateObserver`, `GameActionOutcomeFeedback`, `TelemetryActuationInterlock`, `GameLearningLadder`, practice evidence, and a held-out paired `game_transfer_eval`. **Connect and measure those foundations instead of inventing another nominal learning loop.** Prefer the following loop:

1. **Reflex lane (bounded deadline):** a tiny action policy (or simple verified state machine) uses the newest trusted game state and can explicitly do nothing. Never block input on a huge context or a web query. Expired frames are discarded, not executed late.
2. **Tactics lane (hundreds of ms to seconds):** a local model chooses a compact, testable plan—route, cover, next jump, resource policy. The host translates proposals only through an approved action vocabulary. Tactical messages cannot bypass game focus, watchdog, or deadline checks.
3. **Learning lane (offline/private):** replay observations with explicit outcome labels. Generate candidate strategies, practice against varied seeds, record failure modes, test A/B against matched baselines. Do not promote candidates based on training success; require independently sealed held-out tasks and multi-game transfer evidence.

**Important nuance:** A model cannot increase its underlying parameters' intelligence merely by adding more agents or writing new memory files. Tool use, verified retrieval, context selection, practice, and scoring can improve *system-level task success*. Weight-level learning requires a separately evaluated fine-tuning/distillation process, curated datasets and hardware. Distinguish the two improvements in all reports.

**Proposed benchmark suite:** timed obstacle-course reactions; navigation with moving obstacles; inventory / puzzle planning; uncertain or unseen mechanics; Roblox Luau debugging; creation/playtesting and visual polish; transferable strategy across different game FPS/physics. Pre-register held-outs, prevent leakage, count **every attempt** including no-ops and timeouts, log p50/p95/p99, frame drops, safety failures, win rates, hallucination counts, and aggregate per-game rather than only per-seed. If 8GB GPU pressure blocks a large model, compare smaller models and CPU offload only with actual quality and wall-clock measures.

## 3. Hardware / inference speed: address bottlenecks, not headlines

STAR's previously inspected Windows RTX 3060 Ti has 8GB VRAM; an earlier read-only snapshot showed ~7,743 MiB used, leaving ~449 MiB. This is a **previous sample**, not today's guaranteed headroom; occupancy was not attributed to any particular process. The connected Linux development root filesystem was ~95% occupied (~12GB free). Do not download multi-GB models or launch simultaneous inference experiments without checking resource availability.

**Prioritized performance architecture:**
- **Protect OBS/game/voice before background workers.** Reuse `StreamLoadGovernor`, `StreamAdmissionGate`, Windows GPU resource windows, and `stream_load_host_bridge`-like scoped readers; keep reserve VRAM and cancel speculative workers under renderer, encoder, speech or frame pressure. Never treat low instantaneous GPU utilization as free VRAM.
- **Use a two-tier model route:** small, short-response local classifier for real-time game/speech decisions; larger coder/research planner only for noncritical requests, potentially on a separate Brain computer. Prefer CPU-first optimizations where they improve portability (compiled hot loops, bounded allocations, stable request context, efficient serialization), but profile Python hot spots before considering Rust migration.
- **Measure first *speakable* text and *audible* speech, not only tokens/second.** Existing `inference_stream_benchmark` measures first visible/speakable deltas; `voice/pocket_benchmark` measures first generated PCM. Neither establishes user-heard latency. A real Windows audio-device callback must independently measure playback, and the OBS recording auditor must check rendered mouth/audio alignment.
- **Cache safely:** stable prefix/prompt cache and model reuse may reduce prefill costs, but cross-session isolation and long/short canary tests are mandatory. Evaluate speculative decoding with the exact target/draft models, acceptance rate, VRAM cost and first-audible timing; it can be slower if the draft model consumes precious shared GPU memory.
- **Resource-aware TTS:** compare Kyutai Pocket TTS CPU profiles with existing voice models, recording quality, response delay, RTF, CPU occupancy, voice stability and game FPS under matched scenes. Do not infer the fastest or most natural voice from model size alone.
- **Storage:** audit cache sizes and reclaim space only with owner-approved, backup-safe procedures. Never blindly delete Git worktrees, models, datasets, release assets, or verification environments.

## 4. Humanlike, transparent VTuber interactions

A convincing Star VTuber is *not* a continuous commentary bot. She needs an embodied timeline and a consistent personality, with **silence treated as an action**:
- **Perception:** host-verified game progress, sound/voice activity, viewer questions, scene changes, remaining speech and camera framing. A vague VLM prediction stays labeled as a hypothesis; never narrate imagined wins.
- **Speech policy:** owner interruption > immediate danger > grounded success > relevant viewer question > optional ambient commentary. `StreamDirector`, `TurnTakingGate` and `StarStage` already offer key safeguards; connect them to actual OBS/TTS/capture pipelines instead of writing duplicate policy engines. Never let chat become tool instructions. Speaking can yield to an authenticated owner, while incidental noise must not derail a reply.
- **Personality:** stable preferences, chosen hobbies, recurring jokes, self-reflection based on authenticated experiences, selective playful mistakes and recovery, conversational variation without a fixed repetitive template. Preserve long-term memories as *attributed beliefs* with confidence, consent, source and expiry; do not invent childhood or biological status. Be up front that STAR is AI even while behaving like a warm fictional streamer.
- **Embodied timing:** synchronize blinks, gaze, turns, excitement, breathing, head bobs and mouth motion to *actual audio-device playout* (existing `StarPlayoutClock`), not text generation timestamps. Reset rig to neutral on dropout, cancellation or context change. Study NVIDIA DyaPlex for simultaneous listening/speaking/motion but treat research benchmarks as hypotheses, not an off-the-shelf working Star integration.
- **Game-and-social multitasking:** if action deadline is tight, stay silent; short verified reactions can use CPU TTS with a lightweight avatar; viewer-chat responses can wait for safe gameplay gaps. Measure missed barge-ins, accidental interruptions, repetitive comments and unnecessary speech during critical gameplay in blinded A/B clips.
- **Safety:** moderated chat, private/streamer mode separation, explicit consent for voices/images, no secrets or player-identifying details in memories, no deceptive impersonation of real people, no uncontrolled public stream automation.

**Quality gate:** independently reviewed matched OBS clips; audible first response latency, p95 playback stop on barge-in, false interrupts, synchronized mouth motion, grounded phrasing, game FPS/render/encoder drops, conversation appeal across multiple episodes. The research goal is *natural, personable interaction*, not a claim of human consciousness.

## 5. Roblox authoring + general knowledge expansion

Roblox's **2026-11-04 Studio MCP expansion** provides the `open_cloud_invoke` route to Open Cloud with per-game scopes for asset import, game settings, monetization and analytics. Build a private-authorized **inspect → plan → generate → static-analyze → Studio-test → visual-inspect → repair → rollback** pipeline, where:
- Luau is checked with analyzer / LSP / Selene / StyLua and a deterministic test suite before Studio; visual screenshots detect badly placed joints/UI elements that syntax tests cannot.
- Blender geometry, animations, UI/VFX/audio and reusable verified implementation patterns have explicit provenance; source claims are separated from observed render and verified test results.
- Studio MCP uses the smallest permissions for each game. Roblox documentation explicitly warns Studio data-store operations can affect live player data; never enable production DataStore writes as a private experiment.
- Local learning bank indexes **tested outcomes** (with game version, engine version, constraints, failure signatures), not arbitrary unverified web snippets. Context must respect privacy and proof scope.
- Generalist abilities—research, writing, math, troubleshooting, coding, music, visuals, social conversation, games—should be checked with task-specific, independent evals. Shared long-term state can help recall but does not replace cross-domain correctness.

## 6. Integration / acceptance checklist

**Implemented in this change:** opt-in native frame enumeration, valid no-op accounting, all-frame decision p95, host-declared sealing and fail-closed tests. Existing unnumbered callers remain unchanged by default.

**Not implemented or independently verified:** direct Windows real-game frame source; signed frame-count origin; actual game-state change correlated with these calls; private synchronized OBS+TTS+avatar+game recording; faster model inference; weight updates; transfer learning gains; humanlike full-duplex live dialogue; live broadcasting.

Before declaring a real improvement:
1. Integrate the native host bridge with a trusted independently counting private game engine/Studio test; record failures, missed frames, cancellations and frame outcomes.
2. Run a precommitted baseline vs candidate in private, same game/mod versions, same GPU/process states and controlled randomized conditions. Verify source identity and distinct capture receipts.
3. Require stronger verified win/skill transfer, *without* regressions in p95/p99 latency, OBS render/encode/network drops, memory use, false barge-ins and human reviewer scores.
4. Roll back automatically on observed regressions, but **do not autonomously approve production deploy, live broadcasting or permissions**.

## Research sources (checked November 6, 2026)

- Roblox Developer Forum, **Nov 4, 2026**: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- Roblox Creator Hub, scoped Open Cloud permissions and live data-store warning: https://create.roblox.com/docs/studio/mcp-open-cloud
- NVIDIA DyaPlex full-duplex speech-and-motion research, **June 2026**: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- Kyutai Pocket TTS official information: https://kyutai.org/next/tts/ and https://github.com/kyutai-labs/pocket-tts
- llama.cpp inference/speculative decoding repository: https://github.com/ggml-org/llama.cpp
- OBS-WebSocket / stats for render, encode and network frame loss: https://github.com/obsproject/obs-websocket and https://obsproject.com/kb
- Existing repository source: `star/native_game_roundtrip_audit.py`, `star/game_action_outcome_feedback.py`, `star/game_state_transition_witness.py`, `star/stream_load_governor.py`, `star/stream_turntaking.py`, `star/stream_playout_clock.py`, `star/game_transfer_eval.py`.
