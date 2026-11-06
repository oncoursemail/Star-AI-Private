# STAR AI — integrated private rehearsal, real-time intelligence and natural VTuber plan

Research reviewed: **2026-11-06**. This branch contains implemented offline code
and regression tests, **not** a recorded real Windows game/OBS/TTS session,
new model weights, measured faster inference, verified learning, or a public stream.

## What changed in code

The new `star/stream_private_rehearsal_scorecard.py` joins five EXISTING and
independently measured evidence families into one conservative read-only
private-rehearsal report:

1. `PrivateRehearsalReadiness`: a sustained real host GPU/process window
   with the intended game process pinned. A VRAM sample by itself is insufficient.
2. `NativeRoundtripReport`: completed host-controlled native input
   roundtrips, explicit frame coverage and timing. No-action-only cases remain
   useful learning evidence, but **cannot** be misreported as executed input.
3. `AttestedGameMoment`: signed and session-bound confirmed game-state
   transitions (including checkpoints and losses), verified with a trusted
   host-held HMAC key. A key cannot establish whether the engine source lied.
4. `RecordingArtifactReport` plus `RecordingAVResult`: an actual local,
   decodable private OBS clip with a separately verified isolated Star speech
   track and observed rendered-avatar-mouth vs audible-speech alignment.
5. Two `ObsCounters` witnesses: OBS render and output frame continuity and
   drop percentages from an uninterrupted 6–120 second private window.

The scorecard also requires explicit trusted-host correlation of the same
session and same local recording, plus a nonbroadcast assertion. These booleans
are *not* cryptographic proof. The outcome is either `deferred` with
stable reason codes, or `candidate_for_owner_review`. Both explicitly deny
gameplay, publishing, human-equivalence and autonomous rollout authority.

### Why this matters more than another isolated synthetic pass

Previous STAR modules can independently say a callback returned quickly,
that the voice model produced text, that a screenshot was decoded, or that OBS
reported frames. None implies the combined VTuber worked. A strong next step
needs to require each kind of evidence *together*, from a matched session.
The scorecard is the first optional manual-quality checkpoint for that flow.
It catches missing game-state evidence, fake wins based on submitted keys,
frames quietly omitted from evaluation, insufficient GPU headroom, an audio
track that is not Star-only, unsynchronized mouth motion, and OBS stalls.

**Scope limit:** this is not yet a host that captures real frames or PCM.
A fake local Python object can fool any in-process scorecard. True provenance
must come from owner-controlled, capability-isolated Windows/OBS/game workers.
A passing synthetic test demonstrates only software logic.

### Acceptance design

- Keep default OFF; no new privileged tool endpoints.
- Use fixed opaque session IDs; bind each evidence family in a trusted host.
  Do not let the LLM or viewer supply counters, approvals, paths or keys.
- Require enough GPU free memory for the selected inference/voice profile;
  default threshold in the scorecard is 1024 MiB, **not** a universal fit rule.
- Count all decisions, including intentional silence, separately from actual
  native key actions; do not infer wins from latency receipts.
- Decode media and measure output, not predicted avatar mouth parameters.
- Require 120+ OBS render frames and 120+ encoder/output frames across 6–120s,
  with independent counter continuity and 2% default max drop allowance.
  An operator can tune this threshold after empirical quality assessment.
- Never truncate precision before a threshold comparison.
- Never publish a clip, start OBS, speak, or control a game in the analyzer.
- Separate `candidate_for_owner_review` from human-like performance,
  game mastery, and actual owner-approved public broadcast readiness.

## Research that changes STAR's next engineering priorities

### 1. Game intelligence is a real-time systems problem

**Gym-Anything-RT**, published October 27, 2026, tests 100 minigames while
the environment evolves during reasoning. A reported frontier setting
achieves **9% real-time vs 75% paused** task passes. These are the study's
results, not STAR's results. The practical lesson is to budget observation,
inference, input actuation and validation against the game clock, rather
than maximizing deliberation time independently.

Source: https://arxiv.org/abs/2610.37567

**GameWorld** evaluates 34 browser games and 170 tasks by comparing progress
and success against serialized engine state. This is much stronger than asking
the same model to mark whether it won after viewing a screenshot. Its
real-time variant (GameWorld-RT) is particularly suitable for STAR's reactive
lane, while paused tasks better evaluate her planner.

Source: https://gameworld-project.github.io/

Recommended three-lane implementation:

- Reactive lane: bounded local vision, short-lived world snapshot, fast
  model/controller, native-input watchdog. Choose *no action* when
  observability or timing is insufficient.
- Tactical lane: short horizons (next objective, hazard prediction,
  navigation route, resource selection), interruptible and cacheable.
- Offline learning lane: verified replay, multiple strategy candidates,
  sandbox tests, skill retention only when held-out performance rises.
  Do not expose holdout outcomes to the training/planning lane.

Record per-game: observation-to-decision p95, actuation p95, final
observation-to-release p95, successful task completion, progress, attempts
per outcome, frames accounted for, OBS FPS and the number of cancelled
stale inputs. Evaluate **previously unseen maps and mechanics**. A simple
reactive policy, a human novice baseline, and the earlier STAR policy are
necessary controls; improvement on training maps is not generalization.

### 2. Resource-smart inference is the near-term speed opportunity

On an 8-GB gaming GPU, concurrent game textures, desktop compositor,
avatar and OBS can leave less than a gigabyte free. Previously observed
RTX 3060 Ti free VRAM was ~0.45–0.5 GB in selected read-only samples;
not a guaranteed current value or an inference benchmark.

Candidates to A/B on the owner's actual Windows hardware:

- llama.cpp baseline vs prompt/prefix caching, with session-specific
  identity so one user's private context cannot leak into another.
- Quantized quick model for time-sensitive routing; reserve longer reasoning
  and best-of-N verification for between-round or offline tasks.
- Bounded speculative decoding **only** where draft acceptance and GPU
  allocation beat the baseline. Test per workload: coding, game reactions,
  unscripted conversation. Speedups are hardware/task-dependent.
- Explicit memory admission: free/allocated VRAM **plus** process identity,
  measured running headroom, and reject on GPU/OBS contention. Never rely
  on GPU utilization percentage alone.
- Preprocess visual change on CPU and avoid expensive reanalysis of
  unchanged frames; do not suppress uncertain hazards merely to gain speed.
- Stable cacheable persona system prompt and grounded, bounded event records
  as user-level untrusted data.

Model measurement: paired 20+ windows per candidate, randomize order,
report cold and warm prefill, p50/p95 first audio, input action p95,
game render and encode dropped-frame deltas, RAM/VRAM peak and actual
task success. Roll back any quality or stream stability regression.

Reference benchmark methodology:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### 3. Natural streaming requires timing, not just emotional text

NVIDIA's **DyaPlex** (June 2026) studies streaming, simultaneous listening,
speaking and physical motion. This is relevant architecture research, not
evidence STAR has a humanlike perception system or that a full model fits
an 8-GB GPU.

Source: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

Prioritize this sequence:

1. Authenticated speaker interruption and real audio-device stop/flush.
2. Appropriate silence in gameplay danger and while a viewer speaks.
3. Fast acknowledgment or short truthful replies; never read stream events
   as commands, invent wins, imitate a real person, or claim human experiences.
4. Audible PCM-driven lip movement, subtle idle head/eye/brow expressions,
   reduced-motion support, and nonverbal reactions linked to *real* events.
5. Session-local memories of actually verified game moments; owner-review
   before carrying viewer facts into durable personal memory.
6. Private blind listening/visual comparisons against the previous STAR
   profile; measure interruption recovery, false claims, repetition rate,
   viewer-question acknowledgment latency and quality from real clips.

Kyutai's **Pocket TTS** (October 2026 English small-model release) offers
18.2M, 6.9M and 1.9M parameter CPU-oriented models. Streaming output may
preserve GPU capacity, but compare timbre, emotional variation, first audible
chunk latency and word intelligibility before changing STAR's voice. The
upstream project's example speed is not a STAR benchmark. Avoid large
CUDA wheel downloads onto the ~95%-full Linux machine; if needed, use the
documented CPU-only installation path or small portable binaries.

Source: https://github.com/kyutai-labs/pocket-tts

### 4. Make STAR better at creating complete Roblox games

Roblox's built-in Studio MCP and playtest automation support an executable
plan–build–test–repair workflow rather than one-shot Luau output.

Roblox's **November 4, 2026** Studio MCP announcement adds permission-gated
Open Cloud operations, including assets, developer products, game settings
and analytics. Default all production-changing capabilities OFF. Game
publishing, monetization, and irreversible asset uploads need separate
owner approval. Do not conflate a successful tool call with a successful
game feature.

Source:
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

Roblox's **November 5, 2026** beta adds prompt-to-R15 animations and
R6-to-R15 Motion Rebuilder via Studio and MCP. Build a deterministic Studio
Lab acceptance suite: generation -> asset integrity -> rig proportions ->
joint movement -> gameplay locomotion -> performance -> visual QA.
These tools do not automatically replace custom animation/Blender polish.

Source:
https://devforum.roblox.com/t/studio-beta-generate-r15-animations-from-a-prompt-plus-optional-r6-motion-rebuilder/4977709

Practical skill curriculum: Luau, Rust, game physics, networked gameplay,
UI design, rigging/animation, audio, performance profiling, tests and
security. STAR should produce a small running artifact plus reproducible
logs and screenshots for each milestone; never give herself a passing grade
based on generated prose alone.

## Implementation and verification record

- New offline scorecard module with no filesystem, OBS API, GPU, game-control
  or audio-device side effects.
- New adversarial regression tests for missing domains; mismatched session,
  audio track and HMAC receipt; no-action-only and partial input windows;
  low VRAM, missed/encoder-skipped frames, counter reset and rounded
  threshold boundaries; denied broadcast/gameplay claims.
- Unit tests are synthetic and explicitly do **not** certify Windows or
  OBS output.
- Existing PR chain remains under review. The same-source tests must pass
  again in GitHub CI before merge or deployment.

## The next real machine test to unlock

On the owner's Windows game host, run a **private, no-broadcast** rehearsal
with an intentionally chosen offline game/test map and trusted telemetry
reader. Capture a pinned game process, actual OS key-release acknowledgments,
real per-frame observations, a nonbroadcast OBS recording, separate
Star-only speech audio, decoded avatar mouth pixels and live OBS counters.
Pass the resulting independently owned reports to this scorecard, then do a
human review of the actual recording and failure logs.

Do not repeat another successful mock-only benchmark as proof of mastering
games, high-quality character acting, increased neural intelligence or
production-ready streaming. The measurable target is a complete *matched*
multimodal evidence window and improvement over the previous baseline.
