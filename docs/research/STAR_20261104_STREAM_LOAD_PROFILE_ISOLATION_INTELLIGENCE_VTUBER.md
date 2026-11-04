# STAR AI — isolate gaming/streaming latency calibration before accepting new inference work
**Engineering note · November 4, 2026 · stacked draft after PR #959**

## Executive finding: a real scheduler calibration bug

The existing `AdaptiveQoS` correctly isolates latency samples from **idle** and **game-active** regimes, but until this change its `_regime` classified all active-game samples identically, regardless of whether the PC was **also streaming**. Thus five fast samples collected with the game running alone could make a vision worker look *measured and deadline-safe* during game + OBS + animated avatar + speech. The code then treated the game-only p95 as a meaningful live p95. This is not a sound comparison under contested GPU/CPU hardware.

The code in this PR now uses four separate measured-latency buckets:

| Calibration profile | What must genuinely be running | May certify |
| --- | --- | --- |
| `idle` | No game or streaming load | Idle requests only |
| `game_only` | Active game, without verified recording/stream load | Game-only requests |
| `stream_only` | Live stream or separately confirmed private stream-equivalent rehearsal, no game | Streaming without game |
| `game_stream` | Game **and** live stream, or game **and** independently verified equivalent private rehearsal | Game + stream-time load |

Only **successful host-acknowledged** runs in the same profile feed its latency p95; existing admission limits for FPS, speech backlog, VRAM reserve, CPU load, job deadlines, one-shot tickets, quarantine of timed-out workers and owner opt-in remain in force.

A new optional `QoSSnapshot.private_stream_rehearsal` field defaults to **False**. The trusted native host can set it to `True` **only** for a manually enabled, nonbroadcast recording rehearsal where game, OBS/local recording, avatar and comparable speech/model pressure are independently observed. A user prompt, model-generated statement, mere OBS executable installation, or unvalidated `GetStats` payload must never toggle it. The flag is not a cryptographic proof and does not authorize streaming, machine control, speech or new model execution. For a real stream, existing `stream.live` already supplies the correct profile.

### What the correction protects

1. **Gameplay responsiveness:** a controller or visual model may be quick with OBS absent yet cause missed frames or late inputs while recording. Never borrow `game_only` p95 to certify `game_stream`.
2. **Voice naturalness:** speech that finishes rapidly in an idle desktop may stutter, delay the first audible phoneme or collide with a viewer when a game and stream are active. A **matched** route is needed before using historical p95 to reject a deadline or advertise a low-latency capability.
3. **Real intelligence:** declining speculative vision work when evidence is missing leaves headroom for a responsive controller, deeper tactical reasoning **between** action windows, and verified skill learning outside live gameplay. Throughput alone is not game intelligence.
4. **Measurement integrity:** a private local recording can build valid calibration data without forcing the system to broadcast to viewers merely to collect enough successful measurements. Nonbroadcast status does **not** mean `no recording burden`.

**Important nuance:** The speech path still allows a conservative unmeasured attempt when capacity/slack rules permit, explicitly labeling it `unmeasured_host_must_verify`. Live *vision* continues failing closed without matched calibration. This patch does not pretend the optional private-session flag itself authenticates capture, OBS or avatar load.

## Connected Windows host observation

On **November 4, 2026**, the connected **Main** computer reported an **RTX 3060 Ti, 8,192 MiB VRAM**. A prior window published in PR #959 found **38 MiB free and 98% utilization** while a `llama-server` process was present. A later read-only five-sample window, approximately **02:02:45–02:02:48 America/Chicago (08:02:45–08:02:48 UTC)**, reported **6,384 MiB free and 38–39% GPU utilization**, with the same GPU UUID. Neither observation involved an actual full game + OBS + avatar + voice rehearsal; this difference establishes changing load, not a causal explanation or a stable speed boost. NVIDIA's per-process VRAM accounting can be unavailable on WDDM systems; a Windows `[N/A]` process reading does not prove zero per-process allocation. No process was terminated or reconfigured.

For a useful live performance claim, record separate **idle / game only / game plus private recording / game plus recording plus speech and avatar** traces, with a fixed game build, model, driver, graphics settings and power profile. Require independent end-to-end **frame capture → model → input acknowledgment → observed game outcome** measurements, not LLM token speed. Include p50/p95/p99, timeout frequency, 1% low FPS, OBS render/encoder skips, first *audible* speech, audio/video lip-sync offset and minimum available VRAM under load. Reject missing or changed GPU identity and mix neither workstations nor workload profiles.

## Applied implementation

- Updated `star/stream_qos.py` to preserve four independent latency buckets and a private stream-load witness field.
- Connected the optional owner-controlled label through `RealtimeTelemetryHost.set_context()`, its `snapshot()`, and `StreamBrainGovernor.enable()`, so the normal host telemetry path can supply nonbroadcast rehearsal samples to the existing scheduler. A context transition clears old resource/game/audio samples and resets the label; the label is still a host assertion rather than independent recording proof.
- Updated existing scheduler regression fixtures so formerly implicit game-only-to-live leakage is no longer treated as acceptable. Legacy idle tests still use the original default settings.
- Added adversarial tests to demonstrate that game-only observations cannot certify live-game vision; a private, explicitly marked equivalent recording *can* populate the proper bucket; non-game streaming cannot certify gaming; unmeasured speech is never falsely described as measured; invalid flags are rejected; and the owner opt-in still applies.
- **Not changed:** `AdaptiveQoS` admission authority, host sensor I/O, OBS websocket operations, actual game input, microphone capture, broadcasting, model/weights, live settings or background services.

## Next intelligence, performance and VTuber experiments (not yet implemented here)

### Resource-constrained model routing

The highest value experiment is a **paired local A/B test of placement**, not adding another simultaneously resident large model. On an 8 GB gaming machine compare a compact CPU speech worker against a GPU TTS worker while holding the game/OBS/avatar load fixed. Measure first audible speech **and** the game's p99 frame time. Compare llama.cpp inference parameters on the same task set and host using its official SPEED-Bench, including speculative decoding acceptance and latency. Treat model warmup, prefill, KV-cache slots, memory mapping and context size as part of the profile. The llama.cpp benchmark client assumes an already-running server; it does not establish any specific RTX 3060 Ti speed or memory fit.

Only promote a candidate when it meets **both** measured speed/VRAM guardrails and independent quality checks. For gaming, include unfamiliar levels, success receipts, causal attribution limits and latency-contended runs; for Roblox, run Studio test passes and simulated multiplayer clients; for general knowledge, test sourced answers, abstentions and difficulty-shift robustness; for dialogue, independent grounding, repetition, interruption and naturalness assessment. Preserve each prior champion and roll back on regression. Avoid automatic self-promotion based on the model scoring its own prose.

### More natural conversational streaming

Create a higher-level **intent-to-speak** policy fed by host-vetted game events and turn-taking state: viewer question > owner barge-in > urgent game control > grounded brief commentary > intentional silence. Comment on *observed* wins and setbacks, not imagined ones. Let physically consumed PCM drive mouth movement, natural blinks and subtle gaze; suppress big gestures during timed actions. Use independent audio capture to ensure playback actually began or stopped. Add opt-in, privacy-scoped episode memory, stable preferences, distinctive comedic timing and honest AI identity. Distinguish small backchannels from genuine interruptions without assuming paid LiveKit Cloud inference is a local model.

A useful controlled A/B compares matched scenarios (question, joking response, critical gameplay, genuine owner interruption and background noise), with blind human ratings for relevance, interruption timing, expressive delivery and repetition. An AI is not literally human; the realistic engineering target is a credible, memorable performer and gamer.

### Game creation and general knowledge

Roblox's March **5, 2026** built-in Studio MCP integration provides external playtest, input and debugging workflows. On May **28, 2026**, Roblox added scriptable device simulation, multiplayer test orchestration and virtual input APIs. Integrate these as *authorized, instrumented game-lab skills* on the Windows Studio host: inspect project, propose at least two candidate repairs, apply in an isolated lab, run scripted tests, inspect logs and real visuals, compare frame performance, then keep only successful changes. Separate approved experiments from any public game publishing. Apply the same evidence-and-holdout method to non-game research, coding and visual work.

## Acceptance protocol before moving beyond this draft

1. Run the offline QoS regression tests and the broader streaming/game/OBS/Windows suite; check Python compilation and Ruff; compare any Pyright diagnostics with the repository baseline.
2. On an explicitly approved Windows private session, capture at least **20 distinct successful samples** per route/profile before considering a lower-latency routing policy. The code's p95 mathematical minimum of five samples is just a smoke-test threshold, not production statistical confidence.
3. Verify actual in-game input acknowledgment, matched game version, OBS recording stats and real PCM-consumed timestamps; failure or missing evidence must not become a speed success.
4. Never auto-start a broadcast or terminate the owner's existing model process. Keep all new host functionality opt-in.
5. Compare measured holdout task success before asserting Star is smarter; a bug fix in a scheduler is not evidence of more capable model weights.

## Primary sources (accessed November 4, 2026)

- NVIDIA `nvidia-smi` and WDDM accounting limitations: https://docs.nvidia.com/deploy/nvidia-smi/index.html
- Official llama.cpp SPEED-Bench README: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- LiveKit interruption semantics and cloud requirements: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Roblox Studio built-in MCP/playtests announcement, March 5, 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox testing APIs announcement, May 28, 2026: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854

This document is architecture research plus a concrete scheduler correctness fix, **not** a claim that Star now streams, games more skillfully, learns autonomously from live play, speaks more naturally or infers faster.
