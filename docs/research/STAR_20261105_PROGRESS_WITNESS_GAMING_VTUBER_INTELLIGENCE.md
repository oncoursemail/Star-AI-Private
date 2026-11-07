# STAR: Progress-witnessed navigation, real-time intelligence, and VTuber research

**Engineering and research record — November 5, 2026.** This change is a narrow, verifiable improvement to STAR's existing **private, symbolic** gaming navigator. It does not claim a new foundation model, an automatic game player, a live stream, or a speedup on the owner's GPU.

## 1. Evidence-driven bug and capability gap

A navigation recommendation was previously generated repeatedly as newer frames arrived even when those frames showed that the player's **position had never changed**. It was correct not to assume a key was pressed, but recommending the same direction forever is a poor basis for an autonomous learner. Separately, a caller could request advice at a time that expired a frame and then rewind the supplied clock to make that stale frame eligible again. The admission path checked clocks from accepted observations but not from advisory calls.

The new `max_stalled_captures` option (OFF by default) conservatively limits repeated **move recommendations** without witnessed player-position change. Allowed thresholds are 1–32 verified new captures. Advice is then suspended with `await_observation/no_witnessed_position_progress` until a subsequent accepted capture witnesses a different position or the owner explicitly starts another episode. New frames that fail host verification do not count. The guard cannot claim the action was actually dispatched or that any skill failed; a known game may require a separate safe recovery operation.

The same monotonic host-time fence now advances on successful `advise()` calls. Once a frame expires under a later host time, asking again with an earlier timestamp cannot revive it. Older `ingest()` timestamps are rejected until a genuinely fresh capture on the forward timeline arrives.

```python
nav = GroundedNavigationMemory(
    max_observation_age_ms=600,
    max_tile_age_ms=300,
    single_move_per_capture=True,
    max_stalled_captures=2,  # opt-in; two new static captures require recovery
)
nav.start(game_id="private_lab", game_version="v1",
          episode_id="e1", owner_approved=True)
# Only the isolated, trusted host supplies observations, clock and witnesses:
assert nav.ingest(frame1, now_ms=host_now_ms, host_verified=trusted_witness)
hint = nav.advise(now_ms=host_now_ms)
# hint is symbolic. It never authorizes OS input, publishing, or skill credit.
```

**Security boundary:** `host_verified=True` remains a *host-only adapter contract*. If a model, prompt, chat message, game-client script, or arbitrary screenshot can set this flag, authenticity is not established. The existing `GameActionGate`, `RealtimeGameLoop`, signed `VerifiedGameStateObserver` and `GameActionOutcomeFeedback` already provide separate action/engine-evidence machinery; only a trusted game host should join them. An action's subsequent observed outcome is not automatically proof of causality.

### Required negative tests

- Continuous fresh observations showing no movement: stop issuing move hints at the configured threshold, even if the map itself changes.
- New position on a strictly ordered host capture: release the conservative stall guard.
- Untrusted or replayed capture: must not advance stall counts or reset them.
- No prior move hint: repeated still frames alone must not be treated as an attempted action.
- Episode reset: no stale player position or suspended advice leaks into the next owner-approved episode.
- Reversed-clock attack after a frame expired: fail closed, including on an attempted subsequent ingest.
- OFF-by-default compatibility: existing navigator consumers continue to receive the same advice.

## 2. The genuine closed-loop gaming architecture

**Trusted observation → short-horizon plan → optional advisory hint → independent game-input permit → input receipt → authoritative next game state → outcome assessment → memory admission.** Keep these steps in separate trust domains:

| Tier | Owner | Success signal | Must never do |
| --- | --- | --- | --- |
| Source of truth | Private engine/Studio host | Sequence-bound position, world state, game outcome, monotonic time | Accept a model's statement that a frame was witnessed |
| Reflex lane | Deadline-bounded small policy | Correct safe action before per-frame deadline | Block frames behind a slow research model |
| Navigator | Observed grid/vision state | Reduced revisits/stalls, safe frontier progress | Cross unknown or stale territory by conjecture |
| Input gate | Authorized desktop host | Claimed permit and verified key release | Run an old hint after focus/game/OBS changes |
| Outcome witness | Signed game-state transition pipeline | Independently corroborated checkpoint, win or loss | Equate a key release or nearby event with success causation |
| Learner | Offline curriculum, independent scoring | Hidden-map success, new-mechanic transfer, lower severe-error rate | Reward itself from generated prose |
| Personality/stream director | Captions, voice, animation and conversation | Timely meaningful responses, good silence, synchronized expressions | Fabricate wins, simulate human biography or misrepresent AI nature |

**Next engineering connector:** A private-host integration test should combine the symbolic advice with the existing `GameActionGate` and signed state witness, replaying a real or instrumented engine trace. Keep action permission and scoring outside the LLM. Test withheld frames, input focus loss, signed wins, latency spikes, stale audio, OBS scene changes and termination. Fail closed without taking over public games.

## 3. Research evidence and implications

### Cross-game mastery

Google DeepMind published **SIMA 2 on November 13, 2025**. It combines perception, reasoning, language-directed goals and learning across 3D game environments. STAR should borrow the **research method**: a small set of reusable actions, structured demonstrations, generated but independently checked challenges, and holdout environments. STAR has not acquired SIMA 2's trained model or its demonstrated competence.

- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**GameWorld**, released **April 8, 2026**, offers a distinct objective: 34 browser games and 170 state-verifiable tasks across computer-use and semantic-action interfaces. This strongly favors a private held-out benchmark that tracks real outcomes, not self-graded textual explanations.

- https://arxiv.org/abs/2604.07429

Roblox's **OpenGameEval (October 2026)** evaluates stateful Studio editing and playtesting with executable checks over 84 curated tasks. STAR's game-builder should inspect instance/script state before editing, run Luau static checks, then grade the modified scene in actual play mode. Combine functional metrics with before/after images and direct input/output checks.

- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

### Responsiveness while playing and streaming

llama.cpp's **SPEED-Bench** provides per-category latency, throughput and speculative draft acceptance for an already-running `llama-server`. Speculative decoding may improve decoding *or* steal memory/compute from the game. Do not choose a configuration from raw token rate alone.

- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Kyutai released **Pocket TTS v4.0.0 on October 20, 2026** (new compact English model variants) and **v4.0.1 on October 21** (fix for sub-20M models). CPU-first TTS is a candidate for reducing 8 GB GPU contention, but audio naturalness, first-chunk latency, startup time and CPU interference must be measured on STAR's own Windows system.

- https://github.com/kyutai-labs/pocket-tts/releases

**Recommended reproducible profiling protocol (not benchmark results):** compare existing baseline with CPU voice versus GPU voice and with/without speculative decoding, while a private game, local avatar, audio capture and OBS recording are actually active. Log p50/p95 capture-to-recommended-action latency, input-ack latency, first audible speech, real-time factor of TTS, CPU utilization, VRAM, game 1% low FPS, encoder drops, and correct outcomes. Use matched game traces and hardware counters. Run one model candidate at a time under 8 GB VRAM; permit background training only when the real-time budget has headroom.

### Humanlike but honest VTuber interaction

Microsoft's **Proact-VL (ICML 2026)** studies when a live gaming companion should respond, including commentary and guidance. Being silent at the correct moment matters as much as filling pauses. Its evaluation scenarios are a good source of private A/B conversation tests.

- https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

NVIDIA's **PersonaPlex (2026)** explores natural overlapping speech, interruptions and backchannels. NVIDIA's **DyaPlex (June 2026)** researches synchronized full-duplex speech and motion. Their architectures may be too expensive to run alongside games on 8 GB VRAM; borrow the design principles first, use a lighter speech director until hardware profiling supports an upgrade.

- https://research.nvidia.com/labs/adlr/personaplex/
- https://research.nvidia.com/labs/amri/projects/DyaPlex/

Build a **witnessed moment journal** for the VTuber: what she actually saw and did in a session, her current goal, uncertainty, allowed viewer-safe memories, and a small personality state. A reaction such as "I tried the left path twice; still stuck" should require real, session-bound trace evidence; otherwise say "I'm not sure why the movement didn't register" rather than pretending a specific input or win happened. Make eyes/gesture/lip-sync follow **audible playback timestamps**, not text-plan time. Keep a bounded viewer-turn queue with an owner interruption lane and meaningful silence. Disclose that Star is an AI character; rich style and continuity do not require pretending to be human.

## 4. High-value feature backlog, prioritized

1. **Windows private-host rehearsal harness.** Run one authorized and instrumented game with independent position/outcome telemetry, GameActionGate, verified key-up, offline OBS recording, VTuber avatar, voice audio and hardware metrics. No broadcast or unauthorized public matches. Build a signed, replayable trace fixture from this first experiment.
2. **Game learning with actual rewards.** Construct an escalating practice curriculum (movement, timing, platforming, object interaction, puzzle solving and simple multiplayer coordination in allowed test sessions). Compare policies on unseen seeds, using win-rate, episodes to mastery and error rate. Require authenticated outcome evidence before long-term skill promotion.
3. **Roblox inspect→build→playtest→repair pipeline.** Integrate Studio MCP, Luau tooling, independent game simulator, screenshot comparators and staged rollback. Record task-scoped evidence and use human-approved promotion for external deployment.
4. **Predictive vision and world model.** Track movable objects, collision timing, camera uncertainty and visual occlusion. Test forecasts against future captured frames; disallow speculative unsafe movement when confidence drops.
5. **Dual-speed thinking.** A fast low-latency reflex policy should continue while a strategic planner reasons in the background. The planner's results are leases requiring freshness checks; never force game controls from unverified delayed plans.
6. **Multimodal general knowledge.** Source-grounded retrieval, version-specific Roblox/Blender/Windows references, citations, explicit uncertainty, tool-assisted mathematics and structured memory. Evaluate fresh unseen questions rather than measuring context length alone.
7. **Streamer personality and social skills.** Distinguish owner, viewer, teammate and game audio; develop interests and jokes grounded in real events; choose when to speak; use correct affect and gesture timing. Add moderated opt-in social features and privacy-aware memory retention, not invented human experiences.
8. **Local-first continuous improvement.** STAR Core Forge tracks experiment manifests, policy/model hashes, isolated tests, reversible changes, pre-registered holdouts and auditable promotion approvals. GitHub is an optional publication mirror, not the engine of learning.

## 5. Proposed release gates

The following are **target criteria for an upcoming owner-approved rehearsal**, not measurements from this change:

- On a deterministic held-out private maze, report actual completion, collisions, route length, stalled-position events and number of repeated hints, not just generated commands.
- A stale, reordered, unverified or invalid observation must never permit new movement.
- Once a capture has expired, clock rewind must not make it usable again.
- No synthetic reward or uncorroborated speech memory may be promoted as a witnessed gameplay achievement.
- During simultaneous OBS/game/TTS/avatar activity, record **real** p50/p95 latencies, game FPS and 1% lows, OBS drop percentages, VRAM peaks and audio-avatar offsets. Refuse production rollout if relevant baseline regressions appear.
- A private blinded review compares naturalness, useful silence, interruptions, trustworthiness and source grounding of Star's voice/avatar reactions.
- CPU/GPU optimization promotions require matching configuration hashes and separate model-quality gates, not solely measured speed.

**What was implemented here:** bounded opt-in stall-advice suspension; unified monotonic clock fencing for fresh advisory calls; adversarial offline tests. **Not implemented or demonstrated:** a physical input driver, a signed Windows game host adapter, autonomous wins, improved model weights, faster GPU inference, synthetic voice quality, or human consciousness.
