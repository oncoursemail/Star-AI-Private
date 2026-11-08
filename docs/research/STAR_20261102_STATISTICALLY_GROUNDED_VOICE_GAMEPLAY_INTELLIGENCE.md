# STAR AI — statistical streaming naturalness, real-time game intelligence and local performance
**Research and engineering audit: November 2, 2026.**

## One new, reproduced engineering finding: zero mistakes is not zero risk

STAR's new offline end-of-turn evaluator in PR #898 checked matched, reviewer-labeled
mid-utterance pauses and true turn endings. It correctly rejected individual new
interruptions and severe latency regressions, but treated **zero premature speech
responses on just 20 hesitations** as sufficient for a 5% false-cutoff budget.
This was reproduced against the unmodified parent evaluator before implementing
this patch. The candidate was reported as eligible for manual rehearsal.

For 0 false cutoffs out of 20 *independent* trials, the one-sided 95% exact
binomial upper confidence limit is **13.91%**, not 0%. With 0 out of 60
independent trials, it is **4.87%**. The minimum clean independent count to
cross a 5% bound is 59. With one false cutoff, the required independent sample
count is larger. A naive 0/20 pass could create false confidence in a VTuber
that frequently talks over viewers after one too-small synthetic test.

### The implemented correction

In `star/stream_endpointing_eval.py`:
- Calculate a **one-sided 95% exact Clopper–Pearson upper limit**, via a
  numerically stable log-binomial CDF and bounded binary search, in stdlib
  Python. No SciPy installation or external API is required.
- Require the upper limit to be within the pre-registered false-cutoff budget
  before reporting `eligible_for_manual_rehearsal`. An inconclusive result
  returns `insufficient_evidence`, rather than inventing a voice-quality win.
- Add an opaque `source_turn_id` to each pause, matching across baseline and
  candidate. All pauses from a single real human speech turn contribute **one**
  binary trial: any premature cutoff makes that turn a cutoff. This avoids
  pseudoreplication when someone hesitates ten times in the same conversation.
- A missing source-turn ID, an unmatched source identity, a reused final
  endpoint, or too few distinct source turns blocks qualification.
- Preserve original per-*pause* rates and paired latency metrics while adding
  `independent_mid_turns`, `candidate_turns_with_false_cutoff`, and
  `candidate_false_cutoff_upper_95` to the report.
- No model, microphone, viewer identity, audio, transcript, OBS broadcast, or
  game input is accessed. `authorized_to_stream` stays false.

The confidence procedure assumes independently sampled source turns and a
pre-registered, hidden holdout. Source IDs and `independently_reviewed=True`
are **host attestations**, not cryptographic proof. Repeated re-testing,
reusing data for tuning, aliasing one conversation as many, or evaluating only
easy speakers invalidates any statistical interpretation. Confidence is about
repeated-sample coverage, not a posterior probability of being safe.

### Reproduction and regression matrix

| Synthetic reviewed holdout | Prior implication | New result |
| --- | --- | --- |
| 0/20 distinct source turns, 5% budget | Candidate eligible | Inconclusive; 95% upper bound ~13.91% |
| 0/60 distinct source turns | Candidate eligible | Eligible for **manual nonbroadcast** rehearsal; bound ~4.87% |
| 1/60 distinct source turns, also present in baseline | Candidate eligible | Inconclusive due to uncertainty |
| 1/120 distinct source turns, also present in baseline | Candidate eligible | Can qualify when all latency/quality gates pass |
| 80 hesitation spans from ONE source turn | Mistaken as 80 independent opportunities | Inconclusive: one independent source turn |
| Missing provenance, mismatched pairs, repeated final turn | No source-turn guarantee | Block or reject |
| Candidate introduces any new cutoff, misses true endings or creates a hidden tail regression | Rejected | Still rejected |

Tests use no audio, no user data, and deterministic pre-registered timing
fixtures. They cannot certify *actual* natural speech.

## Ranked priorities for a truly fast, competent, believable STAR

### P0 — finish nonbroadcast end-to-end evidence on Windows

Do not call isolated module tests a successful stream. Connect real trusted
Windows game capture, voice activity timestamps, PCM playback acknowledgments,
VTube Studio model parameters, and OBS read-only stats in a **nonbroadcast**
rehearsal. Measure separately:
1. Game capture timestamp -> vision -> state confidence -> fast policy advice ->
   permitted action -> actual host-confirmed key-up and action receipt.
2. Voice capture -> VAD -> true end-of-turn -> STT/LLM/TTS -> first audible PCM;
   explicitly measure cutoffs on *mid-turn* hesitations and latency at true ends.
3. Frame time p50/p95/p99, GPU VRAM free and peak, GPU utilization, dropped
   OBS frames, audio underruns, and time spent waiting for model answers.
4. Wrong-scene responses, wrong-game memories, unverified claims, stale
   microphone frames, key-release failures, and unacknowledged worker stops.

Acceptance must be multi-dimensional: lower latency only counts if measured
speech interruptions, gameplay stability, and accuracy do not regress.
Compare paired A/B runs on the same hardware and game/voice workloads. Keep
all new features disabled by default until hardware-host attestations pass.

### P1 — two-timescale gaming intelligence (fast student, offline teacher)

October 14, 2026 RealtimeBench introduced 180 continuously running tasks
across six game types. Its slow teacher studies failed gameplay between rounds
while a fast student acts against a live clock. Published task score for its
student increased from 13.51 to 24.19 after two learning rounds; this is
**not** a measured result for STAR.

STAR's next benchmark should use already-existing `game_realtime_loop`,
`game_deadline_router`, `game_action_freshness`,
`game_skill_gate` and `gameplay_skill_bank` as the control plane:
- **During gameplay:** small fast policy using trusted observation age, a
  scene-specific action space and a deadline. If the action would arrive stale,
  skip or choose a separately approved safe fallback, not a slow arbitrary plan.
- **Between episodes:** stronger teacher reconstructs a failure, searches game
  mechanics, proposes a *testable* skill change, and rehearses it in a resettable
  environment with no live viewers or uncontrolled inputs.
- **Promotion:** compare the exact same held-out scenario seeds, never reuse
  practice scenarios as test; retain baselines, confidence, time-to-success,
  game FPS, action age, crashes, and number of attempts. Roll back strategies
  that fail on unseen maps.
- **Knowledge transfer:** store the versioned game and objective scope and
  mechanical abstractions (jump window, obstacle timing, navigation), but do
  not blindly apply game-A coordinates or actions to game-B.

Proof of mastery is win/progress improvement on new seeds at an equal latency
budget, not more saved thoughts or more training hours.

### P1 — voice perception and humanlike conversational timing

LiveKit's open `eot-bench` uses real conversations and separately measures
premature interruptions and endpoint delay. Its published English comparison
reports v1 at **4.5%** false cutoffs versus v1-mini at **12.1%** at a 600ms
latency budget. These are third-party benchmark results; STAR's own hardware,
capture path, languages and conversation styles may differ.

**New local candidate:** p99lab's October 2026 `turn-1-mini` is a
5.3M-parameter, English-only model with a 7 MB int8 ONNX streaming graph
and an Apache-2.0 license. Its authors report 849ms mean endpoint delay at
a 5% false-cutoff operating point versus 1,070ms for LiveKit v1-mini on the
same 400-turn English benchmark. They report 1.29ms per 160ms audio step
on an Apple M4 Pro CPU; **those numbers are not on STAR's Windows CPU**.
Its 95% intervals overlap comparators, its threshold is not calibrated for
STAR, and their report does not test echo, overlap or accents. Investigate
this as an **offline A/B candidate**, not an untested drop-in replacement.
Retain the existing trusted VAD and stop/flush acknowledgments; never let
the model's score directly grant speech or game-input permission.

Run a *paired, preregistered* STAR voice study with source-turn IDs covering:
- gameplay tension and ordinary relaxed talking;
- stutters, mid-sentence thinking pauses, overlapping game sound and TTS echo;
- viewer questions, owner interrupts, guest speech, loud celebrations;
- fast and slow speakers, multilingual turns where supported;
- actual PCM output start/stop and Live2D speech-motion consistency.

Evaluate an end-of-turn predictor by **cutoff upper bound + true-turn p95 +
worst-case paired regressions + missed turns**, never just token speed or VAD
confidence. The bound implemented here is intended for *independent source
turns*; per-language and per-game slices require their own sufficiently large
holdouts before quality claims are made.

Kyutai's Pocket TTS (official project; small English variants were added in
October 2026) is worth testing as CPU-oriented speech. Evaluate first audible
PCM, output real-time factor, audible artifacts, voice consistency, and CPU
contention **while a game is actually running**. A 1.9M parameter model is not
automatically better than a 100M model; apply a blind human preference test.
Prefer Star's own created/authorized voice references rather than unlicensed
voice imitation.

For the avatar, use VTube Studio's authenticated local plugin API for
host-verified gaze, blink, visemes, head turns and emotional expression.
A good personality architecture has stable preferences, memory consent,
meaningful silence, playful and situational humor, smooth animation,
individual histories for Star/Astro/Amber, and truthful statements about what
she actually saw and did. Do not fabricate human experiences, viewer quotes,
feelings as facts, or playthrough accomplishments.

### P1 — 8 GB GPU performance engineering, not benchmark mythology

For the observed 8 GB RTX 3060 Ti streaming computer and the owner's
separate RTX 4060 8 GB ambition, VRAM is a **shared hard budget** across
game rendering, local LLM inference, avatar rendering, and OBS. A model
that occupies most of 8 GB at idle may be unusable while the game runs.
Never promise a Q4 model's token/sec without measuring context/KV memory,
GPU resident layers, concurrency and real game frame timings.

A practical A/B matrix, in increasing cost:
1. Baseline current `llama-server`; record model hash, quantization,
   GPU-layer count, prompt/context length, KV type, concurrency, prefill
   tokens/sec, decode tokens/sec, first token p50/p95, VRAM peak.
2. Prefix/cache-stable prompts and read-only slot-cache reuse under identical
   prompts; measure cache hit rate and stale-context mistakes.
3. Shorter reactive prompts, cheap first-pass routing and bounded retrieval
   from *reviewed* game/voice knowledge; evaluate answer correctness.
4. Compare n-gram speculation versus no speculation; optionally test a
   tiny draft model only if its extra memory does not spill the target from VRAM.
5. CPU speech and small VAD/end-turn model while GPU handles game/LLM;
   compare end-to-end responsiveness with realistic CPU contention.
6. Offload slow teacher research, high-resolution vision and training to Brain
   1/other idle computer **off-stream**, with explicit LAN privacy and host
   permissions. Avoid network-dependent inference inside frame deadlines.

A gate should reject any new tuning if FPS p95/OBS dropped frames,
speech timing, verified answer quality, thermal stability, or effective VRAM
headroom is worse. Rust may improve hot-path scheduling or binary parsing
when profiled; it does not change the intelligence of a fixed model by itself.

### P2 — make STAR a better autonomous creator and generalist

For Roblox game design, Roblox announced a Studio-native MCP server in March
2026 and expanded plan-build-test workflows in April. Use Studio's official
playtest, synthetic input, and authorized tool APIs rather than uncontrolled
OS keystrokes. STAR's authoring cycle should be:
1. Read the existing game's architecture and dependencies; form a structured
   change plan with constraints and provenance before generating.
2. Produce 4–8 bounded candidate Luau/UI/VFX implementations only when
   verification capacity is available; static-analyze, lint and run isolated
   Studio tests. Keep verified winners, not the longest outputs.
3. Test physics and collision, player spawn, multiplayer joins/leaves,
   accessibility, performance on target devices, audio sync and UI visual
   consistency. Use repeatable screenshots/frames for visual critique.
4. Have independent agents inspect changes, reject unverified geometry and
   game-economy exploits, then promote only on test outcomes. Retain rollback.
5. Build an original reusable asset and mechanic library with licensing and
   source metadata, not scraped copyrighted assets.

General knowledge should use an indexed source store with citations,
source/version freshness, per-audience privacy classification, explicit
uncertainty and untrusted-input isolation. Successful retrieval is *not* proof
that a claim is true; check provenance and independent corroboration.

### P2 — autonomy that actually stays reliable

Use offline-first snapshots, atomic experiments, controlled permissions,
persistent goal/task history, bounded learning loops, and a watchdog that
can recover crashed local services without falsely claiming success.
Practice loops should be interruptible, resource-bounded and capped by a
separate streaming QoS governor. Self-modification requires unit/integration
tests, isolated trials, semantic review and rollback. GitHub is optional for
release review; the internal forge can retain branch/patch history locally.

STAR can become convincing as an entertaining, personable AI VTuber while
being transparent that she is an AI persona. A believable character is
consistent, capable and attentive, not one that pretends to be a real human.

## Specific next acceptance checks

1. **Voice evidence:** >=59 *independent* reviewed source turns with zero
   cutoff under a 5% one-sided 95% bound, or a larger holdout for nonzero
   cutoffs; no new cutoffs against baseline, no silent true-turn misses,
   no hidden >250ms pair regression. Pre-register thresholds and avoid
   repeated selection against the same held-out conversations.
2. **Gaming:** same seeded runs with fast/slow teacher A/B, tested on unseen
   maps, no unapproved inputs and p95 observation-to-action under verified
   scene TTL; teacher never causes streaming stalls.
3. **Streaming:** OBS stays inactive during acceptance rehearsal; verify
   actual PCM heard, viewer interruption timing, Live2D expressions, FPS and
   VRAM concurrently. Manually approve any subsequent public stream.
4. **Game development:** run full multiplayer and visual tests on at least
   one small playable game, then a blind independent scene-quality review.
5. **Honest reporting:** separate implemented/tested code, proposals,
   model quality, hardware speed, and successful real-world demonstrations.

## Sources (consulted Nov 2, 2026)

- NIST, exact one-sided binomial confidence limits:
  https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm
- LiveKit's reproducible `eot-bench` and English comparison:
  https://github.com/livekit/eot-bench
- LiveKit turn detector configuration and timeout/fallback behavior:
  https://docs.livekit.io/agents/logic/turns/turn-detector/
- p99lab `turn-1-mini` October 2026 model card, license, performance and limits:
  https://huggingface.co/p99lab/turn-1-mini/blob/main/README.md
- RealtimeBench, released October 14, 2026, arXiv 2610.20665:
  https://arxiv.org/abs/2610.20665
- llama.cpp official speculative decoding and server docs:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Kyutai Pocket TTS primary project:
  https://kyutai-labs.github.io/pocket-tts/
- VTube Studio public API (custom parameter injection and authentication):
  https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- OBS official WebSocket project and password guidance:
  https://github.com/obsproject/obs-websocket
- Roblox Studio-native MCP, announced March 5, 2026:
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox plan/build/test agentic workflow, April 15, 2026:
  https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
