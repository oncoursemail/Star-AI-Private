# Star AI: Fail-Closed Voice-Capture Liveness, Fast Gaming Intelligence & Natural VTuber Research
**Research and engineering date:** November 3, 2026. **Status:** offline-tested prototype, **not** a live Windows streaming demonstration.

## 1. Newly identified integration failure

Star's prior `stream_preplay_fence` checks voice activity, game urgency, OBS load,
and output readiness immediately before the **first** audible PCM. Her
`StreamInterruptionHost` can then handle **authenticated owner barge-in**
on new VAD frames. However, an owner cannot interrupt audible Star when the
microphone/VAD feeder itself silently crashes or stops emitting callbacks.
The old event-only path had no opportunity to recognize that disappearance.
A warm, natural VTuber must listen as she speaks, not merely check once.

**Code added in this iteration:**
- `StreamInterruptionHost.enable(..., require_live_voice=True)` opts into a
  stronger capture-continuity contract. Existing integrations remain OFF by
  default. Strict mode also requires observed, echo-cleared quiet before arming.
- Every accepted VAD frame supplies a monotonic timestamp. `tick()` can run
  independently of VAD events and checks the last accepted frame against a
  configurable `maximum_voice_gap_ms` (100–1000 ms, default 250 ms).
- On loss during an active utterance, Star revokes that plan, requests a
  **playback-epoch-specific physical stop and animation flush**, and latches a
  fault that forbids automatic rearming until a trusted owner confirms device
  recovery. If physical stop fails, the outcome is **fault**, not success.
- A superseded scene/utterance causes an **old-epoch-only** stop; the live
  replacement's avatar rig is not neutralized by a stale callback.
- `StreamVoiceLivenessSupervisor` owns an independent 50-ms daemon tick loop,
  and exposes guarded `observe`, `arm`, `health`, `stop` and privacy-minimal
  counters. The loop must sample at least three times per allowed VAD gap.

This is **not** independent proof of sound cessation: callbacks attest to
device stop, and the Python thread cannot survive process crashes, GIL wedges,
OS stalls, or a power loss. The Windows adapter must actually verify stopped
WASAPI/PortAudio playback, clear OBS audio/overlay state, and provide an
out-of-process mute/emergency stop for process-failure scenarios.

**Offline acceptance**: contiguous 30-ms quiet frames permit one approved
speech turn; advancing host time beyond the VAD limit without new frames
triggers stop/flush exactly once and prevents rearm; a failed stop latches a
fault; stale epoch stop never resets a replacement; watchdog stopping is
explicit and owner-bound. No actual microphone, speaker, OBS, game or
VTube Studio process is run by these tests.

## 2. Why this improves apparent humanity (without pretending to be human)

Prioritize responsiveness and timing rather than canned 'human' tics.
Naturalness is an emergent perception produced by *behavior grounded in
the ongoing situation*:

1. **Listen during speech:** continuously update local turn and liveness state.
   Let verified owner interruptions win; never make guest or chat messages
   into untrusted OS-level controls. After a false interruption, resume only
   after an independently confirmed quiet window.
2. **Speak at relevant moments:** classify a moment's urgency and social
   importance. Short alert for danger, quiet during a precise jump or aim,
   specific happiness after an independently verified achievement; do not
   manufacture danger, winning, embarrassment, or other memories.
3. **Synchronize mouth, gaze, body and captions to played—not generated—PCM:**
   use consumed output samples and revalidate render tickets before dispatch.
   When interrupted, immediately cancel queued speech/text/rig frames.
4. **Develop continuity:** persistent interests, narrative arc, harmless
   personal projects and verified episode recall. Keep private viewer data
   out of long-term memory by default; don't fabricate subjective experiences.
5. **Voice quality:** tune expressive pronunciation, prosody, breath groups,
   speech durations and short latency; do not imitate a real person's voice
   without rights/consent. Star should be transparent that she is AI.

LiveKit's turn-taking architecture provides concrete models for interruptions,
false-positive recovery and transcript truncation to *actually heard* speech
([LiveKit turns](https://docs.livekit.io/agents/logic/turns/);
[turn-tuning reference](https://docs.livekit.io/agents/logic/turns/tuning/)).
**Do not** copy its assumptions blindly: a loud game, voice chat and TTS echo
are not equivalent to a clean voice call. Star needs host-signed identity and
echo cancellation as separate signals.

## 3. Speed improvements: test a full pipeline, not tokens per second

**One system is not always one neural model.** Keep a lightweight, bounded
real-time lane for combat/navigation reactions, a tactical worker for
midrange plans, and a slower, stronger research/learning lane scheduled
between matches. Give game render, physical audio and OBS priority over
background inference, screenshots and training.

Suggested **measured** goals for a private Windows pilot (engineering targets,
**not** observed performance):
- Report p50/p95/p99 screenshot-to-actual-input-ack latency with the game
  clock advancing throughout inference; record stale/cancelled actions.
- Track game FPS p1/median, OBS missed/render-lag frames, actual first audible
  chunk latency, audible-interruption stop p95 and A/V sync.
- In each hardware regime, record CPU utilization, physical RAM, total VRAM,
  peak KV cache, active layer offload, model quantization and simultaneous
  OBS/game load. On an 8 GB GPU, admit workloads only if measured headroom is
  preserved; **do not assert** a universal model/tokens-per-second optimum.
- Evaluate paired experiments over the same randomized seeds and game states.
  Require independent evidence of *better decisions*, not just fewer tokens.

**Candidate experiments (all OFF by default):** immutable prompt-prefix cache
per persona/game epoch; compact intent-only reactive model; CPU TTS on a
bounded core budget; long-context retrieval into a short verified working
set; n-gram/draft/EAGLE-compatible speculative decoding **only where the
current llama.cpp backend supports it** and its draft overhead improves
measured end-to-end delay; separate rendering and inference admission.

Kyutai's Pocket TTS repository documents October 2026 tiny English
approximately 18.2M/6.9M/1.9M parameter models and CPU/audio-streaming
operation, but Star must compare intelligibility, character fit, PCM timing
and *on-device* real-time factors rather than assuming a listed model is
best on her 3060 Ti/4060 PCs.
([Pocket TTS official](https://github.com/kyutai-labs/pocket-tts);
[technical report Jan 13, 2026](https://kyutai.org/pocket-tts-technical-report/)).
For speculative inference, verify against the **actual pinned llama.cpp
revision**, because speculative formats, KV reuse and backend support
change quickly ([ggml speculative implementation](https://github.com/ggml-org/llama.cpp/blob/master/common/speculative.cpp)).

## 4. Self-learning across games: a verifiable curriculum

**Observation → hypothesis → trial → execution → feedback → stored skill**:
- Keep source-signed game telemetry separate from model-generated descriptions.
  Only retain verified wins, failures, damage, position and milestones.
- Begin with owner-controlled practice games: platforming timing, short combat
  loops, inventory navigation, camera aiming, social obstacle-solving.
- Split trials by *game family, map, enemy policy and date*, preventing one
  level's memorization from masquerading as new-game transfer.
- Track independent win rate, action economy, damage avoided, navigation
  completion, latency costs and rule violations. Compare against simple
  scripted and human-controlled baselines under the same test conditions.
- Vary physics, latency and visual clutter only after baseline mastery.
  When a newer failure arrives, invalidate stale progress and run sustained
  independent recovery trials before advancing difficulty.
- Build and test **real** reusable skills (wall jumps, objective search,
  cover usage, teamwork callouts), not optimistic descriptions of skill.

For socially engaging streams, narrate *actual plans, surprises and repairs*;
a loss followed by an interesting lesson is a valid entertaining episode.
Game auto-play must remain bounded by the platform rules and explicit owner
control; do not deploy bots into competitive multiplayer games without
permission.

## 5. Roblox / game creation: from code completion to artifact verification

Roblox's Studio-integrated MCP server can inspect scripts/data-model objects,
edit Luau, execute in declared contexts, and start/stop playtests. Its
`studio_id` targeting supports multiple simultaneous Studio sessions.
([official Studio MCP guide](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md);
[March 5, 2026 announcement](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643)).

Recommended high-confidence build loop:
1. Snapshot the place, intended player experience, and server/client object
   graph before making edits.
2. Generate 4–8 independent designs, then gate through Luau analyzer,
   Selene, StyLua, targeted Lune tests and automatic StudioTestService or
   isolated Studio playtests when available.
3. Run deterministic multiplayer client-server cases, physics scenarios,
   camera and grip checks, latency/packet-loss simulations and FPS budgets.
4. Compare independent screenshots/recorded frame sequences to a brief
   design rubric; reject invisible VFX, detached shoulders, bad hand grips,
   incorrect anchors, collision gaps, UI overlap and broken input navigation.
5. Promote **only** the verified improvement to Star's local version store;
   preserve diffs, provenance, test receipts and immediate rollback. GitHub
   is optional publication/export; internal improvement must be independently
   testable offline.

Roblox's documentation explicitly describes network simulation, scripted
testing and multiplayer Studio playtest modes
([testing modes](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md)).
Larger-scale 2D/3D authoring should follow the same evaluate-and-repair path,
not merely generate prettier assets.

## 6. Near-term backlog with falsifiable acceptance criteria

| Priority | Change | Proof of value |
| --- | --- | --- |
| P0 | Windows *nonbroadcast* microphone/VAD + WASAPI sample monitor, host epoch stop, VTube rig, OBS private recording | Owner interruption and synthetic capture dropout physically silence PCM, clear captions/rig; logs show p95 stop delay and zero stale epoch leaks. |
| P0 | Out-of-process audio mute/stop on process crash or watchdog failure | Kill host process mid-sentence in a disposable private rehearsal; secondary watcher confirms physical output stopped; handle false alarms. |
| P1 | Adaptive CPU TTS comparison: current engine vs Pocket TTS variants | Paired 30-utterance tests: first audible PCM, full real-time factor, pronunciation and blind naturalness ratings, game FPS and OBS frame loss. |
| P1 | Reactive/tactical model routing; eliminate unnecessary vision inference | Paired continuous-game trials with at least 30 holdout seeds, same game version/hardware, p95 capture-to-action and actual game score. |
| P1 | Verified game observer connected to one owner game engine | Every action has a recent signed game epoch; no phantom accomplishments; automatic stop on observation failure. |
| P2 | Studio multi-client build/test/repair with visual evaluation | Generate one complete minigame from an approved brief; pass Luau tests, multiplayer flows, visual rubric, FPS and gameplay success. |
| P2 | Episodic personality + grounded stream narrative | Human blind review of 30 opt-in recorded sessions rates relevance, silence, natural timing and no invented memory; no raw private chat retained. |

## 7. Boundaries and what remains unverified

This PR does **not** install a real microphone driver or Windows playout
callback, run OBS, perform a game win-rate experiment, demonstrate increased
model speed or establish a human-level personality. A daemon tick is neither
an OS emergency-stop service nor a reliable bound under CPU starvation. All
runtime knobs remain explicit, opt-in and auditable. The useful contribution
is closing a specific gap between event-driven VAD and continuous listening
while audible, backed by offline adversarial tests.
