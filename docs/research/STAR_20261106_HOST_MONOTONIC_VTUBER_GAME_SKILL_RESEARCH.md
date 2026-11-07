# STAR: Real Host Clock Instrumentation, Gaming Mastery, Streaming Personality and Resource-First Intelligence

**Research / engineering:** November 6, 2026
**Parent:** Draft PR #1009, measured interval adapter. **This branch** adds host-side, monotonic event measurement and explicit incomplete-window handling.
**Status:** opt-in private diagnostic, no real game control, OBS broadcast, audio capture, training, or verified Windows game performance. All external research is a design input, not deployed functionality.

## 1 — Concrete implementation: stop accepting unmeasured, success-only latency samples

The prior `star/measured_game_latency.py` validates samples *provided by the caller*. That catches bad timestamps but does not give an authorized host a safe way to collect its own event timestamps. A caller could omit slow/missing ACKs and manufacture unrealistically fast results.

New `star/host_monotonic_game_probe.py` offers a single-use host-side event recorder:
- `capture()`: host receives captured frame and obtains an internal sequence number.
- `decision_ready(sequence)`: actual decision is available (not a movement authorization).
- `action_submitted(sequence)`: host **already** submitted the approved action (the recorder submits nothing).
- `action_ack(sequence)`: host has observed an acknowledgment (not evidence that a character moved).
- `finalize(tick_ns=...)`: rejects incomplete frames or failed clock/phase invariants, then calls the preceding adapter and destroys stored raw timestamps.
- `status()`: counts and booleans only, without screenshots, player names, prompts, chat, audio, key presses, or raw clock origins.
- `abort()`: revokes the whole window, including completed samples, instead of hiding an interruption and showing only fast surviving frames.

Timing uses a **single process-local `time.monotonic_ns`** clock. It checks nonnegative int64 timestamps, monotonic progression, stage order, one ACK per sequence, 256-frame bounds, 30-second frame duration and synthetic 24-tick replay limits. Handles overlapping capture requests but requires ACKs in sequence because the downstream private replay currently requires ordered acknowledgments. All stages are local methods, with no arbitrary callbacks, network clients, desktop input, or media processing. The clock can be injected for deterministic tests; such data must never be presented as a hardware measurement.

The output is still **self-reported host telemetry, not cryptographically authenticated game-state evidence**. In particular:
1. Host callbacks must be sourced from a trusted game integration. A language model can never certify an ACK.
2. Host ACK != input execution; input execution != game progress; game progress != goal success.
3. A 100 ms synthetic tick is a test configuration, not the actual game tick.
4. Replay cycles delays; it is an *approximate timing stress-test*, not frame-accurate chronological playback.
5. Private event timestamps are destroyed after finalization; the duration-only report must not be treated as publishable independent gameplay proof.
6. Missed callbacks, dropped frames, cancellations, and clock failures revoke the window; they are *not quietly excluded from averages*.

### Host-only private integration example

```python
from star.host_monotonic_game_probe import HostMonotonicGameProbe

probe = HostMonotonicGameProbe(owner_approved=True)
seq = probe.capture()           # After host obtains a frame.
# ...host runs its approved game-state reader / policy...
probe.decision_ready(seq)       # After the decision exists.
# ...separate permission and freshness gates; host may or may not submit...
probe.action_submitted(seq)     # ONLY when the host actually submits.
# ...host receives an actual action acknowledgement...
probe.action_ack(seq)
result = probe.finalize(tick_ns=100_000_000)
print(result.private_report())  # Duration-only, not independently attested.
```

If the decision is denied, no ACK arrives, or game control is not permitted, call `abort()`, NOT `action_ack()`. The example demonstrates plumbing only; it does **not** connect Star to Roblox or a computer game.

## 2 — Fresh research: why completion isn't enough in real-time games

**Gym-Anything-RT (Aggarwal & Welleck, Oct 27, 2026):**
https://arxiv.org/abs/2610.37567

Evaluates 100 dynamically evolving minigames with pause/unpause variants; for one cited model, 9% real-time success vs 75% success when the environment was paused. These are **published research results, not STAR's score**. The real-world lesson is that model reasoning time and world motion must be coupled.

Engineering recommendations for a true generalist gaming agent:
- **Fast lane, continuous:** perceptual anomaly/hazard detection, confidence-ranked next action, short deadlines and cancel-on-newer-frame; no multi-second language-model think loop while holding a movement key.
- **Tactical lane, event-driven:** plan goals/subgoals, track object permanence, infer mechanics and adapt after observed failure; propose options to fast lane, never bypass host safety.
- **Learning lane, opportunistic:** convert only witnessed actions/outcomes into episodes; curriculum grows from one-step reactive control to platformer timing, fighting-game neutral, navigation, resource economy, multiplayer cooperation, and strategy.
- **World-model calibration:** predict opponent trajectory with uncertainty intervals. Test predictions against unseen frames, not against self-labeled descriptions.
- **Independent promotion:** pre-register A/B evaluation seeds and objective checks. Compare illegal actions, death rate, time-to-completion, p95 latency and *all* failed episodes; do not use one easy maze as evidence of mastery.
- **Legal game controls:** prefer private games and test harnesses; never bypass anti-cheat or automate third-party competitive games in violation of their rules.

### Training curriculum with verification

| Stage | Practice | Independent pass criterion |
| --- | --- | --- |
| 0 | Synthetic partial observation | Goal reached and no false credits for late moves |
| 1 | Trusted private game-host replay | Same-clock full lifecycle, no missing ACKs, completed host witness |
| 2 | Private authorized platformer | Held-out level completion and collision checks; measure input deadlines |
| 3 | Combat/strategy | Opponent response, cooldown timing, objective and legal-action metrics |
| 4 | Social/multiplayer | Correct turn-taking and teammates' consent; privacy-preserving transcripts |
| 5 | Transfer | Unseen mechanics and environments improve vs frozen prior policy |

A successful stage does not automatically prove any later stage.

## 3 — Faster intelligence: measure *experience* rather than theoretical TFLOPS

I inspected an authorized Windows machine's GPU **read-only** on November 6, 2026. Its 8 GiB NVIDIA GPU reported approximately **7,880 MiB in use (of 8,192 MiB)** in three consecutive samples, with **95–99% utilization**. A `llama-server` process was running; OBS and Roblox Studio were not observed in the inspected process set. This is a short snapshot. The GPU driver did not expose per-process VRAM attribution, so **do not assert which process accounted for how much**.

**Operational consequence:** Do not start game+avatar+OBS+model benchmark as if VRAM headroom were available. Use a dry-run admission check first, with GPU memory pressure, encoder/render queue, CPU headroom and disk headroom; wait for or select a lighter model profile when necessary. Do not kill existing workloads without owner authority.

Design A/B candidates for an 8GB-class GPU:
- Read-only GPU/CPU/OBS p50/p95 sampling -> reserve substantial **measured** graphics/encode headroom before model admission.
- Small reaction policy + cached retrieval memory on CPU; deeper model invoked asynchronously only at subgoal boundaries.
- llama.cpp prompt/KV cache and n-gram speculative decoding measured under *identical* quality gates. Draft models may **hurt** VRAM availability and tail latency; never claim speedup without device A/B data.
- Kyutai Pocket TTS's compact CPU-oriented variants as an opt-in speech candidate; compare intelligibility, character voice, first-audio p95, CPU utilization, game 1% lows, and OBS dropped frames. Do not assume fast in all voices.
- Move high-cost video generation, self-play training, and large data retrieval outside actual streams. Preserve runtime rollback and all telemetry provenance.
- A proof of higher intelligence must be a higher held-out task pass rate at comparable compute / error cost. Faster decoding alone is not higher intelligence.

Sources: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
and https://github.com/kyutai-labs/pocket-tts/releases

**Infrastructure:** the authorized Linux development host had about 11 GiB free of a 218 GiB root volume on this date. Avoid large model downloads or unbounded worktrees. Inspect storage and obtain approval before destructive cleanup; retain reproducible test artifacts and rollbacks.

## 4 — Making STAR more naturally humanlike as an AI VTuber

Sources and interpretation:
- **Proact-VL:** https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
  explores deciding *when* a gaming companion should speak, rather than always narrating.
- **PersonaPlex:** https://research.nvidia.com/labs/adlr/personaplex/
  explores voice/role-conditioned full-duplex interruptions and backchannels, but is not free to run alongside an 8GB-card game.
- **DyaPlex (June 2026):** https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
  studies causal synchronized speech and motion.
- **Microsoft CompanionX:** https://www.microsoft.com/en-us/research/project/companionx/
  studies socially cooperative agents with evaluation and guardrails.

Implement a **grounded social director**, not a chatbot that claims to be human:
- Maintain a stable character bible, personal narrative, recurring hobbies, and episodic memory, labeled clearly as AI persona/story. Explicitly disclose AI identity in channel/profile.
- Allocate social turns by context: viewer question > urgent gameplay callout > co-host reaction > spontaneous commentary > intentional silence. Don't narrate repeatedly during high-danger maneuvers.
- Ground emotional *expressions* in actual verified events (missed jump -> surprise; victory -> excitement). No claims of literally feeling pain or of private experiences that did not happen.
- Use voice activity detection, interruption windows, listener backchannels, and speech-time acknowledgment before moving lips or switching subtitles.
- Express micro-motion and gaze with head/eyes while speech arrives. Preserve consistent character proportions, avoid random body jitter; game reactions take priority over idle poses.
- Remember only viewer-approved recurring details and public chat events subject to retention/opt-out; never leak desktop notifications, private DMs, tokens, locations, or screen contents.
- Offline private rehearsal first. Require host-approved voice input, capture sources, overlays, games and broadcasting. Keep a visible emergency stop.

Humanlike quality metrics: 10-minute offline recordings with timestamped event-to-speech p95, interruption latency, false-claim count, repetitive phrases/minute, expressive motion/audio skew, human rubric scores, mute/silence appropriateness, OBS render/encode misses. These are *proposed measurements*, not results from this PR.

## 5 — Better Roblox + generalist knowledge

Roblox OpenGameEval (Oct 2026): https://github.com/Roblox/open-game-eval
compares executable Studio modification and simulated play, not just generated code. Build STAR's **inspect -> spec -> isolated 4-8 candidates -> lint/typecheck -> executable Studio test -> critique -> rollback/promote** pipeline. Expose failed regressions as next practice tasks.

Roblox's **Nov 4, 2026** Studio MCP Open Cloud addition supports per-game least-privilege API scopes and asset upload-directory controls:
https://create.roblox.com/docs/studio/mcp-open-cloud
Keep scene inspection read-only by default. Asset publishing, datastore mutation, real player consequences and monetization require separate explicit controls. An AI-generated place is *not* complete until spawn, gameplay loop, camera, combat, multiplayer replication, UI and performance have independently passed.

For broad knowledge beyond games: source-provenance document retrieval, searchable personal skill graph, offline-first memory with age/TTL, contradiction tests, vision/audio understanding with permissions, versioned verified examples, and withheld test cases. Use targeted retrieval and compiled context instead of ever-growing raw chat histories.

## 6 — Acceptance gate and next integration

1. Do NOT claim a completed Windows gaming-and-VTuber rehearsal yet. The currently tested component only instruments host event boundaries using a local monotonic clock; tests include a real *host clock plumbing* smoke test, not a real game.
2. In an approved private host, connect capture and action ACK callbacks and independently validate state changes; retain lost/incomplete samples.
3. Build a **local-only, bounded** data collector, no raw frames or chat in the report. Calibrate engine ticks; gather p50/p95/p99 under concurrent game+TTS+avatar+OBS.
4. Paired A/B profile on a fixed known-safe GPU workload with headroom; no stealth model/process shutdown.
5. Test supervised social director in OBS **record-only** rehearsals with feedback and kill switch, before ever enabling broadcast.

This change establishes a more trustworthy instrumentation foundation. It does not train new weights, lower inference latency, prove social intelligence, control a live game, or enable streaming.
