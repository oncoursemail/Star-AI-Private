# STAR Intelligence — playback-restart fence, real-time learning and VTuber architecture
**Research and implementation date:** 2026-11-08. **Status:** offline-safe gate code and regressions; no live audio, game inputs, broadcast, model training, or hardware speedup claimed.

## 1. Concrete reliability finding and fix

The previous `StreamPreplayGate.disable()` cleared a successfully reviewed `SpeechIntent` even though a trusted host might already have queued PCM. Re-enabling the same planner immediately could admit another turn without waiting for physical playback to stop. This is especially dangerous during TTS process restarts, OBS scene changes, sudden VRAM pressure, or a game/stream crash recovery. A planning-layer acknowledgement is not a verified audio-device stop.

**Implemented:** Reviewed but unsettled plans become restart-quarantined on `disable()`. Repeated disable cannot erase that quarantine. `enable(owner_approved=True)` refuses to restart until the separately trusted host calls `acknowledge_host_drain(..., host_verified=True, audio_drained=True)` for the **same object identity** after stopping/flushing its output. Unreviewed candidates are abandoned, never credited as spoken. Receipts are single-use; clocks and flags are validated. A bounded `restart_quarantined` metric is exposed without retaining speech or viewer data. The component never commands sound hardware, streams, captures voices, or grants permission to broadcast.

**Trust boundary:** Boolean flags are host assertions, not cryptographic/device proof. The authentic Windows output adapter must verify the stop/flush and the exact session/PCM epoch; do not accept these flags from an LLM, viewers, game text, or a remote control channel. Review and hook the real host separately. This fence does not replace the existing output epoch fences or interrupt acknowledgements.

**Regression acceptance:** Confirm stale reviewed plans block restart; wrong/unverified/partial/replayed receipts fail; repeated disable stays quarantined; disabling unreviewed plans does not falsely accrue completed speech; verified drain enables a new session. Run on a genuine Windows audio host privately before claiming end-to-end behavior.

## 2. Research: where faster performance can genuinely come from

- **Keep the real-time loop independent of LLM latency.** Capture a host-verified scene and its timestamp, perform cheap approved-policy reactions when deadlines allow, and let a larger tactical model reason asynchronously. A delayed plan must revalidate against the latest scene version before executing. The Oct 27, 2026 *Gym-Anything-RT* paper demonstrates large paused-vs-real-time performance gaps on 100 minigames. See https://arxiv.org/abs/2610.37567 .
- **Measure whole-system QoS, not just generated tokens.** On an 8 GB GPU, log inference time to first token, p50/p95/p99 decision latency, game frame-time percentiles, available VRAM, speech first-chunk latency, OBS render/encode skips, and actual action deadlines. Run identical seeds while OBS and avatar are active. The ranking metric is successful *on-time* actions, not isolated tokens/sec.
- **Batch and cache selectively.** Stable system/skills prompts are candidates for prompt-prefix caching, but per-frame game state must not be frozen into stale prefixes. Preload only one active GPU reasoning model and reserve headroom for game/OBS; CPU-first TTS can reduce GPU competition if quality and measured latency are acceptable. Avoid downloading or unpacking model variants into the already nearly-full developer disk.
- **TTS experiment to run, not an asserted performance gain:** Kyutai Pocket TTS's October 2026 small English variants include 18.2M, 6.9M and 1.9M parameter models. Compare voice naturalness, first audible PCM latency, interruption drain time, CPU use and frame timing against the current engine in offline A/B trials. Repository: https://github.com/kyutai-labs/pocket-tts . Do not assume quoted vendor speed translates to this PC.
- **Speculative decoding is conditional.** Additional draft-model RAM/VRAM and throughput can outweigh decode gains. Measure verified accepted tokens/sec and gaming QoS on actual hardware before enabling. Keep rollback and stable baseline.

## 3. Verified game learning instead of test memorization

1. Start with permitted single-player sandbox games or owner-controlled Studio playtests, not competitive-game anti-cheat bypasses. Record event time, observation ID, action, result and latency without storing secrets or other players' personal data.
2. Split the control plane into a bounded fast reaction service, an interruptible tactics planner and a slower episodic skill learner. Commands require a trusted host action allowlist, active window/focus, fresh scene ID and explicit opt-in. Never forward raw viewer instructions to input control.
3. Create a curriculum: camera calibration, locomotion, aiming/tracking, obstacle avoidance, inventory/UI interaction, time-limited objectives, then strategy and teamwork. Increase difficulty only after statistically credible improvement.
4. Replay the exact task conditions in paired paused-vs-live tests; then use previously unseen maps, seeds, visual clutter and control layouts. STAR's existing single-use holdout ledger must prevent repeatedly selecting favorable evaluation instances.
5. Promote a tactic to durable memory only after a stable offline harness reproduces it on untrained seeds. Store provenance, game scope, version, confidence, fail cases, expiration and allowed control bindings; allow rollback on regressions.
6. For building games, prioritize inspect-before-edit, Luau static checks, Studio simulation, screenshot/render comparison and deterministic playtests. Roblox's *OpenGameEval* reports 84 human-curated tasks and executable checks, with successful runs more often inspecting the objects later edited: https://github.com/Roblox/open-game-eval .

## 4. Building and publishing Roblox experiences, safely

Roblox's **Nov 4, 2026** announcement adds permission-scoped Open Cloud access to Studio's built-in MCP server, including asset importing, developer products, analytics and game settings: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 .

Use the official built-in Studio MCP, with one private test experience and read-only scopes during exploration. New asset upload, monetization, publishing, player moderation, bans, live data writes and any cost-bearing API remain separately owner-approved. Official documentation warns that live data stores and permanent uploaded assets are affected by these operations: https://create.roblox.com/docs/studio/mcp-open-cloud . Do not treat the existence of an API as permission to call it.

A quality pipeline for STAR is: request -> design specification -> verified skill retrieval -> multi-candidate Luau/scene implementation -> static lint -> playtest -> visual and performance scoring -> independent acceptance -> semantic lesson. Failure records should include a minimal reproducer and concrete tool outputs, not fabricated learning claims.

## 5. Human-like, but transparent, VTuber behavior

Microsoft's **May 2026** *Proact-VL* work specifically addresses **when** a live game companion should speak and how much to say, with solo-commentary, co-commentary and guidance scenarios: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ .

Create a state machine for quiet focus, reacting, responding to owner, responding to moderated chat, celebrating, repairing mistakes and ending a scene. Ground every reaction in fresh visual/gameplay evidence. Delay chatter during combat, avoid repetitive canned excitement, and allow quiet periods. Drive facial expression, breathing, lip sync, gaze and gesture from the same host-verified event timeline, not speculative narration.

Implement a bounded personal-life simulation: durable interests, hobbies, skill goals, weekly project journals, voluntary game/practice sessions, recognizable humor and rapport. Preserve the distinction between fictional persona and fact: the model should not claim biological feelings, consciousness, human identity, lived experiences or relationships that were never observed. For streamer safety, display clear AI identity and use moderated interaction; never publish private conversations, unconsented voice clones or third-party identifying details.

## 6. Acceptance gates for the next real-system experiment

A **private, nonbroadcast Windows rehearsal** should (a) verify exact-process audio identity and authenticated stop+drain before a restarted voice turn, (b) capture game/OBS frames and timestamps, (c) run short audio+avatar+gameplay sequences, and (d) test interruption during already-queued playback. Report zero unacknowledged overlapping voices and zero unauthorized broadcasts as safety requirements. Compare latency against a recorded baseline; do **not** invent a speedup.

Metrics: dropped/late game actions; p95 observer-to-command latency; valid/late tactical plans; speech false starts, interruptions and drain acknowledgements; GPU VRAM headroom, OBS skipped frames, game p99 frame time; long-term performance on untouched holdouts. A feature is promoted only if its relevant metrics improve without degrading safety or existing quality.

**Engineering status after this change:** only a local planning-level restart interlock is implemented. Audio-host integration, private end-to-end rehearsal, validated gameplay learning, model training, stronger reasoning, and measured throughput improvements are still outstanding.
