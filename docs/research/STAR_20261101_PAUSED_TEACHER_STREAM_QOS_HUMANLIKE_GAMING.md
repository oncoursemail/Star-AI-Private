# STAR — Paused-game teacher admission, streaming QoS, fast intelligence and natural VTubing
**Research and implementation audit: November 1, 2026.** Status: code and synthetic tests on draft branch; no Windows streaming deployment or demonstrated model-quality gain.

## 1. Concrete problem closed this run

The existing `GameDeadlineRouter` separated quick gameplay decisions from offline teacher study. Its teacher path checked `game_active=False`, an independently supplied `stream_live=False`, explicit owner approval, and CPU/GPU pressure flags. But **it returned before considering `StreamLoadGovernor`**, even when that governor said `pause_background_workers=True`. A paused game is not an idle machine: OBS, TTS, and avatar compositing may still be active.

Change in `star/game_deadline_router.py`:
- The game's last monotonic advisory clock now also covers the offline-teacher path. A backward host clock cannot turn a previous study recommendation into an apparently valid new one.
- If a stream governor is attached, teacher advice requires a comparable host clock and a fresh `normal` governor profile. Stale, disabled, warming, constrained, critical or clock-mismatched governor evidence fails closed.
- **A normal resource profile never overrides `pause_background_workers`**. The caller must honor this explicit governor policy, even when OBS seems healthy.
- The preexisting separately owner-approved, non-streamed teacher path remains available when no stream governor is attached, and the live streaming exclusion remains first priority.
- Every result remains an advisory; no model launches, player input, recording, streaming, network access or training is authorized by this function.

Added four deterministic regressions for normal-but-paused background work, stale/disabled/missing-clock headroom, rollback, and a mismatched governor clock. The trusted Windows host still needs to wire together its OBS state, game clock, process scheduler and permission check.

## 2. Why the right performance metric is not maximum tokens per second

An 8 GiB GPU may run a game, OBS graphics and encoding, avatar animation, a local vision model, and an LLM. Maximizing offline throughput can increase **time until Star speaks** or cause frame drops. Prioritize observable outcomes in this order: no crashes or unsafe inputs; stable game/OBS performance; punctual reactions; audible and interruptible speech; reliable grounded answers; only then token throughput.

Instrument without personal content:
- **Game:** frame-time p50/p95/p99, fps lows, age of observed frame at decision, missed action deadlines and win rate on held-out matches.
- **Inference:** time-to-first-visible, first sentence-ready, first *audible* sample, completion p95, queue wait, cache-hit evidence, speculative draft acceptance, timeout frequency, and peak VRAM.
- **OBS:** deltas for render skipped, encoder skipped and network dropped frames, plus independently attested output state and A/V sync in actual recordings. Preview-only frame counters are not broadcast proof.
- **Persona:** interruptions that stop audible playback, false interruptions on breaths/noise, overlap time, ungrounded spoken claims, silent critical gameplay and viewer question coverage.

Evaluate all four workloads already recognized by `stream_workload_quality_matrix`: gameplay commentary, general knowledge, Roblox creation and live dialogue. Compare fixed matched scenarios with independent review. Do not promote a change when one workstream regresses even if aggregate throughput rises.

## 3. Architectural pattern: three distinct timescales

**Reflex lane (milliseconds):** game engine state / lightweight visual signals -> deterministic safety-and-action rules, not an expensive language model. A host checks input freshness and game permissions at the moment of actuation. Never claim a stale observation is current.

**Realtime commentary lane (hundreds of milliseconds):** small reactive language/vision worker; bounded speech planner; CPU-friendly TTS; sample-accurate playback receipt; star/astro/amber avatar motions grounded in real audio and events. Admission comes from owner-supplied telemetry, not from model prose. Under OBS pressure suppress optional commentary before essential gameplay and owner interruptions.

**Study lane (between sessions, not just between actions):** a stronger teacher analyzes signed gameplay records, formulates skills, generates increasingly difficult drills and tests hypotheses. Do not run while OBS or the live governor forbids background work. Study cannot mutate shipping code or skill scores without independent holdout evaluation and the Forge review/rollback gate.

The October 14, 2026 RealtimeBench paper [The World Won't Wait](https://arxiv.org/abs/2610.20665) tested 180 continually running game tasks and reported gains from a slow teacher studying *between attempts*, with a fast student doing live actions. Its gains apply to that benchmark; **STAR has not reproduced them**. The practical rule is that both *learning validity* and *meeting live deadlines* are necessary to claim better game intelligence.

## 4. High-payoff CPU, GPU and Rust experiments

### Existing llama.cpp can move first
Official llama.cpp [speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) supports draft-model, EAGLE-3 and n-gram approaches. The [SPEED-Bench server client](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures latency, throughput and draft acceptance using an already-running server. Test one variable at a time: no draft vs small draft vs n-gram; separate streaming slot from study; cold and warm prompt cases; 1 and 2 concurrent requests; identical model/quantization/context and reproducible workloads.

A draft model consumes RAM/VRAM and CPU or GPU cycles and may *hurt* latency if token acceptance is low. KV-cache reuse needs session-scoped identity and isolation tests. Report p95 first-audible delay and missed game deadlines alongside tok/s; if either regresses, revert.

### Selective Rust, not an unsupported language rewrite
Profile CPU hotspots in high-frequency pixel preprocessing, OBS counter parsing, packet filtering, audio buffers and scheduler bookkeeping. Move only measurable bottlenecks into PyO3/maturin Rust extensions or a standalone isolated Rust service. Keep Python orchestration and external model APIs initially. Require reproducible parity tests, timeout behavior and sampled CPU/RAM/VRAM evidence before switching a path. A rewrite does not make underlying model weights more intelligent.

### Adaptive GPU residency
Reserve VRAM for the game, graphics and OBS; never treat apparent free memory as guaranteed allocatable. Prefer CPU TTS under GPU stress after a measured comparison. Consider preloading the small speech model and keeping the large study model offline while broadcasting. Multi-process full-model residency may cost more than moving lightweight work to CPU. No change here auto-tunes clocks or bypasses system safety.

## 5. Natural but truthful AI VTuber: concrete interaction stack

**Perception:** gameplay events and selective grounded visual recognition -> event confidence + recency -> reaction. Don't invent game wins, enemy positions or remembered conversations.

**Dialogue:** adaptive pause detection, interruption handling, safe viewer admission, short responses while game focus is high, and intentional silence. The official [LiveKit audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/) offers a local CPU `v1-mini`, but cloud `v1` and adaptive interruption availability depend on deployment and SDK mode; do not assume local mode includes cloud-only features. A VAD/STT fallback must be benchmarked for noises, backchannels and owner interruption. Measure *audible playback stop*, not only a logical stop command.

**Voice:** [Kyutai Pocket TTS v4.0.0 (October 20)](https://github.com/kyutai-labs/pocket-tts/releases) introduced 18M, 7M and experimental 2M English model variants; v4.0.1 (October 21) updated small models. These offer CPU-first candidates, not proof of a better voice than Star's current engine. Audition expressiveness, laughter/prosody, pronunciation, CPU burden, speaker consistency and first audible frame on the target host.

**Motion:** map verified speech phonemes and energy to mouth, eyes, blinks, gaze, head turns and lightweight hair physics. Important facial cues must come from actual play or speech, with blend/decay rules to prevent jitter and repeated looping. VTube Studio's [official documentation](https://denchisoft.com/documentation/) links to its authenticated parameter-injection API, suitable for a controlled avatar adapter. A real-time visual audit must catch clipping, extra/missing limbs, desynchronization and idle frozen poses.

**Continuity and social presence:** owner-allowlisted verified episode memories; the ability to say “I haven't seen that” or “I don't know”; consistent preferences and personality; viewers can tell she is AI. An expressive functional self-model is feasible, but simulated emotion should not be presented as scientifically verified human consciousness. External interactions remain consent-, privacy- and policy-bounded.

## 6. General knowledge and game creation must be tested as skills

For knowledge, pair each fact with provenance, retrieval freshness, citation scope and a confidence/abstention path. Use a fixed holdout set with adversarial contradictions and changing facts. Separate prompts that test factual retrieval, reasoning, tool correctness and social dialogue; avoid reusing training/practice questions for validation.

For games, collect a signed gameplay event ledger: scene, observation age, control action, result, and authoritative success/failure. The teacher proposes compact strategy improvements; the fast worker is tested on unfamiliar seeds, maps, opponents and frame rates. A win on one scripted map must not count as general mastery.

For Roblox creation, Roblox's [OpenGameEval](https://github.com/Roblox/open-game-eval) (October 1, 2026 paper) evaluates 84 tasks in reproducible Studio sessions, including executable scene and playtest checks; observed scene inspection before editing correlates with improved success. Star should inspect first, plan changes, build, validate geometric integrity and collisions, run real multiplayer playtests using [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers), and independently review look, motion and gameplay. Keep prompt templates, project-specific assets and verified lesson results separate from hidden evaluation scenes.

## 7. Release gates and implementation order

1. **Now (completed):** forbid offline teacher advice against the attached governor's background pause, even in nominally normal conditions; require monotonic time and fresh hardware evidence. Dedicated regression coverage, feature still opt-in and advisory-only.
2. **Windows integration:** connect the host's verified OBS output status, GPU telemetry, game focus and the actual worker launch/stop authority. Add a supervised OBS+game+TTS rehearsal with automatic nonessential-work suspension, no broadcast by default.
3. **Performance:** run identical CPU/GPU inference baselines and candidate configurations with reported p50/p95/p99 game frame times, first audible latency, GPU free/peak VRAM, OBS dropped/render/encode percentages, and verified completions. Stop when live workloads degrade.
4. **Learning:** evaluate held-out game skill changes and general-knowledge accuracy before promoting new lessons or code in Star Core Forge; use provenance and rollback, not self-awarded scores.
5. **Persona:** pair independent social turn benchmark cases with a real OBS recording, TTS playback-stop timestamp and visual avatar review. No shortcut from offline tests to unattended broadcasts.

Suggested *targets to qualify* (not measurements): response first audible <=1500ms p95 for measured interactive questions; authenticated owner interruption playback cessation <=350ms; OBS output/render skipped frames under 1% each where possible; zero unsupported claims in reviewed critical events; no priority inversion while background teacher is eligible. The target FPS and allowable frame-time must be selected per actual game/hardware; no universal 60fps promise. Avoid using a single p95 threshold to conceal individual case regressions.

### Current evidence and limitations
The source changes and synthetic tests are published on a draft branch; a live Windows OBS rehearsal, a trained model, a Rust rewrite, autonomous gameplay benchmark improvement, and a measured inference speedup are **not** delivered by this document. The GitHub repository is public: do not store credentials, personal recordings, viewer messages, private model prompts or device-identifying diagnostics here. Maintain default-off switches and host-reviewed high-impact permissions.
