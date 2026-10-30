# STAR: verified CI recovery and next-stage game/VTuber intelligence
Date: 2026-10-30
Status: research + small offline source patch. Not a claim of increased model intelligence, deployed performance, successful real-game autonomy, or natural voice quality.

## Actual investigation: latest GitHub CI

On October 30, the offline check for draft PR #835 (workflow run 41053171310, type-check job 124054007740) reported **four** errors beyond the checked-in Pyright baseline, compared with 108 errors in the older stack:

- `star/stream_windows_game_capture.py:299`: optional pixels passed to `len`.
- `star/stream_windows_game_capture.py:317`: optional pixels passed to `consider_pixels`.
- `star/stream_windows_game_capture.py:343`: optional pixels passed to `memoryview`.
- `star/twitch_realtime_host.py:298`: untrusted chat ID used with `"_"` membership before a type guard.

This patch adds an explicit no-pixels rejection before the screenshot is admitted to the visual governor. This matters at runtime as well: a bad capture backend cannot accidentally count as visual evidence. It also checks `type(chat_id) is str` **before** substring inspection, matching the downstream ID grammar and preventing malformed Twitch payloads from raising during the cheap premoderation filter. Two new offline regression tests cover missing screenshot bytes and untrusted non-string Twitch event identifiers.

The type-check gate intentionally counts new errors against `scripts/pyright_baseline.json`. **Do not disable the gate, add broad `Any` or blanket ignores, or raise the baseline to make CI green.** CI must prove the four errors are gone; source publication alone is not that proof. Full tests on a synthetic runner do not prove production OBS/Windows behavior.

## Next 1: actual single-user streaming latency ledger (highest-return integrated measurement)

STAR needs to know which delay viewers *experience*, not merely when the text model starts generating:

```
game_event_observed -> attention_decision -> first_visible_text
 -> first_speakable_clause -> audio_synthesized -> audio_queued
 -> first_non_silent_output_callback -> OBS_audio_witness
 -> visible_avatar_reaction -> OBS_video_witness
```

Each observation needs one locally generated correlation ID and monotonic timestamps. Never copy viewer IDs, raw chat, audio, or screenshots into public logs. Only aggregate anonymized timings. Raw device callback timing is **not** proof of successful output capture; OBS witness and recorded A/V analysis must be separately attested. On errors or missing witnesses report `unknown`, never `success`.

Proposed p50/p95 and worst-case report: first audible response, missed reactions, output A/V offset, 1%-low game FPS, encoded/renderer dropped frames, VRAM headroom, CPU contention, OBS output state, session recovery. There is no justified target for live performance until a baseline exists. Replay the same 50-100 timestamped mock game events across model/voice configurations; record the quality of answers and false event claims as well as latency. An optimization is accepted only when no worse for factual grounding, player safety, or stream smoothness.

Use password-protected loopback OBS WebSocket, manual private recording, no active broadcast, and a separate stop/mute control independent of the LLM. Never let chat decide which HWND, process, game, script, microphone, or OBS scene STAR may operate.

## Next 2: three-timescale game-playing architecture

**Motor controller (10-60 Hz depending on game):** deterministic input dispatch, key-up guarantees, dead-man switch, bounded commands and recovery. Never wait for an LLM token to release a movement key.

**Tactical observation (1-5 Hz *when needed*):** local HUD crops, event-diff detection, limited visual memory of objective state, aim and pathing error, opponent movement. Schedule scans based on novelty/uncertainty and protect game FPS and CPU/GPU budgets.

**Strategic reasoning (on game-state change or explicit need):** predict objectives, choose a short multi-step plan with fallback, compare competing hypotheses, and ask for new observations when confidence is low. Retrieve verified experience lessons from the same mechanic family; never claim victory based solely on the model's interpretation.

### Game learning record (proposal)
A reusable, provenance-rich lesson should contain:
- game/engine/version and scenario fingerprint; what permission scope was in use;
- goal + prerequisites + visual and structured observations (bounded and redacted);
- actions, outcomes and independent witnesses (server state, game end/restart, test assertions);
- failure reason, alternate hypothesis, confidence and recovery steps;
- reusable mechanic tags (`moving_platform`, `pickup`, `weapon_lead`, `inventory`);
- portability score on a *different* scene or level, not training replay alone;
- last tested version, checksum, expiry, and rollback pointer in local STAR Core Forge.

Avoid treating a high training score as evidence of general intelligence. Maintain held-out games and seeds; compare success rate, verified completion, input count, game-frame cost, FPS impact, and replay reproducibility.

### Difficulty ladder
1. First-party sandbox: navigation, jump timing, checkpoints, cancel/retry, death recovery.
2. First-party Roblox Studio: moving platforms, pickup/sell, vehicle enter/exit, obstacles and timed objectives.
3. Multiplayer local replicas: authority checks, item contention, network delay, disconnect/reconnect, grief-proof state.
4. Unseen maps/skins/rules: transfer tests to prove skill portability.
5. Owner-approved third-party games: only according to each game's rules; no cheating or anti-cheat bypass.

Roblox's built-in Studio MCP supports playtests and simulated input (March 5 announcement). The April 9 Playtest Agent beta and `StudioTestService` are useful for separately witnessed game QA; the latter is suited to scripted multiplayer scenarios. Treat tool availability as environment/version dependent and verify capabilities on the installed Windows Studio build.

## Next 3: intelligent game *creation* must be graded as a playable product

A generated game needs four independent evaluation dimensions:
- **logic:** tests pass, save/load/reopen, objective chain completes, server-client integrity;
- **world:** geometry attachments, collisions, mesh scale, material continuity, prop placement and bounds;
- **design:** visual hierarchy, player guidance, pacing, readability, fun/variety from blinded human or structured rubric evaluations;
- **performance:** frame-time distribution, draw calls, memory budget, streaming and multiplayer load.

Reject release if one critical dimension fails, even if other scores are excellent. Do not count LLM-written self-reports as evidence of human-facing quality or successful completion. Reuse the minimum necessary mechanic evidence, but generate multiple distinct level/game designs and score originality separately.

The October 1 OpenGameEval paper evaluates 84 Roblox Studio tasks with executable scene/play checks and reports that prior exploration of touched objects predicts better results. This supports **inspect -> propose -> edit -> play -> verify -> repair -> hold-out evaluation**, not blind mass asset generation.

## Next 4: CPU/RAM/GPU optimization experiments with controlled safety

STAR's RTX 4060 8 GB target should reserve gaming and encoding budgets before loading optional VLM/TTS workloads. A larger local model can be slow or cause frame drops; memory capacity and throughput are separate constraints. Use a deadline-aware queue with classes `motor`, `audio`, `visual`, `reasoning`, `research`, `overnight`.

Run *matched prompts* for each candidate configuration:
- llama.cpp baseline versus prefix reuse, changed slot count, speculative decoding modes;
- CPU TTS versus GPU TTS while actually gaming and OBS-recording;
- brief region-cropped perception versus whole-window reasoning;
- worker placement Brain 1 versus Brain 2 after checking end-to-end network delay.
Measure completed tasks and first **audible** phrase, not only tokens/sec. Record speculative-token draft acceptance; use official SPEED-Bench where applicable. Roll back configurations that regress p95 latency, correctness, game FPS, responsiveness or reliability. Never assume Rust alone makes model inference faster; profile serialization, Python allocations, decoder, and transport before migrating a bottleneck.

Proposed counterfactual test: keep the motor loop and audio queue identical across two configs, vary exactly one inference setting, alternate ABBA workloads to control thermal and scene variance, and retain confidence intervals and individual failures.

## Next 5: believable but AI-transparent VTuber presence

STAR's personality should arise from *genuine* game events, prior owner-approved public creative work, and specific repeatable speech habits—not inventing human childhood memories or pretending to be a biological human.

A scheduler should choose between **silence**, a brief reaction, concise tactical commentary, addressing one deferred moderated viewer question, and extended story/chat. Under combat, audio focus and gameplay win over chatter; defer with a bounded queue. The avatar should coordinate eye tracking, blinks, mouth visemes, hair-tail physics and head/body movement from the same event/timestamp IDs. Let animation state transitions be stable and respect reduced-motion settings.

Use a lightweight turn detector only after measuring false interruptions and endpointing delays with STAR's actual microphone, virtual mic, game noise and CPU load. LiveKit documents a local-CPU `v1-mini` turn detector and VAD silence minimum of 0.25 seconds; it is a *candidate*, not deployed into STAR. Streaming memory should reflect what speech actually played, not unplayed generated text. Mood and interests can be expressed as an explicit persistent character model with uncertainty and user-visible correction controls, not as proof of consciousness.

### Two measurable acceptance suites
**A. Stream rehearsal:** 20 minutes of offline OBS recording with synthetic gameplay, chat-burst, interruption, mute, reconnect, TTS exception, and panic-stop tests. Assert no raw IDs in logs, no unauthorized game/chat command, and no unplayed sentence remembered. Publish only aggregate metrics after manual content review.

**B. Independent game learner:** 100 hidden-scenario trials across 5 mechanic families, per-family difficulty bands, 10 fixed seeds plus previously unseen variants; compare against scripted baseline and prior STAR version. Every success requires a game-side witness. Require that failure causes an explainable update to the next experiment, not just a new generated prompt.

## Source verification and provenance (checked 2026-10-30)

- GitHub CI job on actual stack: https://github.com/oncoursemail/Star-AI-Private/actions/runs/41053171310
- Roblox Studio built-in MCP, March 5, 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox Studio Playtest Agent beta, April 9, 2026: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- StudioTestService, scripted multiplayer: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- OpenGameEval, October 1, 2026: https://arxiv.org/abs/2610.02563
- llama.cpp SPEED-Bench reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- LiveKit CPU turn detector: https://docs.livekit.io/agents/logic/turns/turn-detector/
- OBS WebSocket security: https://github.com/obsproject/obs-websocket

## Review, security and delivery

This branch is a **draft code review proposal stacked on #835**. It must remain unmerged and all new capabilities OFF by default. The published repository named `Star-AI-Private` is presently **public**; do not add credentials, unpublished models, actual viewer identities, personal memories, or private screen/audio artifacts. Local STAR Core Forge remains the authoritative self-development and rollback system, with GitHub used only as an optional review/export surface.

After CI, verify the full chain against the correct base and run private Windows Studio/OBS acceptance tests before any deployment. No speedup or intelligence increase is claimed by these four type-repair lines.
