# STAR: monotonic speech receipts and interactive VTuber intelligence (2026-11-05)

## What changed in code, and what did **not**
A real defect remained after the optional speech-reservation work: a host clock
could jump forward, expire the 60-second audible quota, then jump backward.
Previously, an older event could enter the reopened window; a backward
proposal could replace a valid speech receipt, and a backward failed-audio
acknowledgement could abandon a pending utterance. Three tests reproduced these
behaviors **before** the fix.

When **opt-in proactive pacing** is enabled, STAR now tracks the highest
arbitration time observed in the current enabled session. After the first
proposal, each offer, proposal and playback acknowledgement must use the same
nondecreasing host timebase. Regressed offers are rejected, proposals yield
silence, and regressed acknowledgements preserve the original receipt.
A new anonymous rollback counter supports monitoring; disabling a session
resets its clock watermark. The default configuration (limit=0) retains its
old behavior. Initial intake can still batch events before the first
arbitration without forcing a future event's timestamp onto the speech clock.
This is a **planner reliability** fix, not faster inference, new gaming skill,
speech generation, a microphone controller, or permission to broadcast.

The host should supply `time.monotonic()` for all `now` values, and map
external game/chat timestamps into that same frame before offering events.
Wall-clock time is only for presentation. An observed rollback is a reason
to pause **optional** speech and inspect clock wiring, not to bypass safety
gates or invent a fresh timestamp. Avoid assuming host model inference time
is equal to a remote provider's receipt timestamp.

## Research: interactive spoken behavior is not just TTS quality
The June 9, 2026 Kyutai paper *Multi-Faceted Interactivity Alignment in
Full-Duplex Speech Models* isolates four useful dimensions: **pause handling,
turn-taking, backchanneling and user interruption**. It evaluates these axes
both offline and in real-time dialogue, and argues that token-level audio
likelihood alone is insufficient to optimize interaction. We should benchmark
all four with separate scores; prettier voice audio cannot compensate for
talking over viewers, and an AI that constantly chatters is less believable.

NVIDIA's PersonaPlex (January 15, 2026) demonstrates role-prompted,
voice-conditioned full-duplex conversation; Kyutai's Moshi and its CPU-oriented
Pocket TTS are alternative research baselines. **Do not assume that
PersonaPlex/Moshi's 7B-scale realtime speech processing fits alongside a
Roblox game + avatar + OBS on an 8-GB GPU.** First perform private measured
tests on the owner's actual hardware. Keep STAR's current pipeline as fallback,
treat proposed model changes as opt-in, and compare p50/p95 audible onset,
interruption latency, intelligibility, speaker identity drift, and GPU
memory/fps contention. Distinguish a synthesized-audio **request** from a
verified **played** utterance.

Proposed isolated evaluation: 100 previously recorded/consented interaction
turns (not publicly distributed), balanced across the four axes; mark
time-to-first-audio, interjection overlaps, missed questions, speaking
when silence would be appropriate, and whether the avatar reacts after
the corresponding sound rather than ahead of it. Blindly review naturalness
with short, repeatable clips; exclude private transcripts from diagnostics.

## Game-playing intelligence and authored games
A strong architecture has three tempos, not one giant prompt:
1. **Fast motor controller** consumes authorized HUD/control observations,
   estimates immediate hazards, and handles supported game input within
   approved game policies. Fixed perceptual budgets preserve FPS.
2. **Tactical world model** tracks positions, objectives, inventory, failure
   hypotheses and uncertainty. It requests expensive vision only when an
   observation is expected to change the decision.
3. **Slow skill learner** replays independently verified outcomes, constructs
   progressively harder variants, and measures transfer to hidden levels.
   Store tool versions, seed, game state hash, proof type, and failure reason.

Roblox's October 2026 OpenGameEval paper evaluates 84 curated game-development
tasks with executable edit- and play-mode checks. It shows exploration before
modification correlates with better task success; use this for STAR's
`inspect -> plan -> edit -> test -> evaluate -> rollback` loop. Roblox Studio
ships a built-in MCP server and playtest automation; use those under
scoped project identity with the existing request-bound Studio proofs.
Keep training and evaluation worlds separate so repeated practice cannot
falsely appear to generalize. Reserve unfamiliar tasks, unseen game mechanics,
randomized map layouts, and multiple seeds as holdouts.

Candidate game metrics: success rate on unseen seeds; verified vs reported
success agreement; recovery after a failed attempt; response/action latency;
fps p1/p5/p50; crash rate per hour; regression count per 100 changes; and
whether a human can play and enjoy the produced experience. Do not deploy
automated account gameplay to a live multiplayer service until its rules and
owner consent permit it.

## Speed and scalable general-purpose intelligence
Benchmark **paired full workloads**: game + avatar + local model + voice +
OBS recording versus the same workload with candidate optimization.
Record TTFT, p95 useful reply time, median decode tokens/s, VRAM peak,
OS memory pressure, OBS dropped/late frames, game frametime and CPU load.
llama.cpp's official SPEED-Bench measures latency, throughput and
speculative-token acceptance for server workloads. Compare speculative
decoding, slot counts, prompt caching and KV isolation one at a time.
Refuse a speed "win" if it degrades gameplay or returns the wrong context.
Given only 8 GB VRAM, large speech models and draft models may be infeasible
during gameplay even when a standalone benchmark looks fast.

For general knowledge, STAR needs an offline-first sourced knowledge layer,
not indiscriminate scraping: trusted document snapshots, retrieval receipts,
source date/authority, conflict detection, confidence or abstention,
separate short-term dialogue and long-term episodic memory, TTLs for dynamic
facts, and explicit user controls for private memory. Corrections become
versioned hypotheses evaluated against new independent tasks—not automatic
model-weight updates based on a single chat.

## Personality and streamer naturalness
STAR can be a consistent, charming **AI VTuber** without pretending to be a
human. Build an explicit persona profile, stable hobbies/values, contextually
appropriate humor, verified gameplay memories, continuity across sessions,
multiple expressive facial/body states, and private reflection notes with
uncertainty labels. Preserve genuine silence, notice when viewers do not
want commentary, react to victories and setbacks without fabricating
emotions or game outcomes, and yield promptly to real interruptions.
Separate roleplay/character expression from any claim of human consciousness.

Safety requirements: no fabricated personal relationships or false claims
about being physically present; clear AI identification, moderation of
viewer-provided text, bounded chat ingestion, owner-controlled permissions,
and no unapproved streaming, purchases, external posts, or game-account
actions. Host-observed audio/scene receipts must precede experience memories.

## Next acceptance gates (not completed in this change)
- **P0 — Private end-to-end Windows rehearsal.** Use actual game input, avatar
  animation, generated audio and OBS recording, plus independent timecode and
  resource auditing. Do not start a public stream. Capture p95 round-trip
  interaction latency, barge-in success, speech-vs-avatar sync and FPS.
- **P1 — Clock-contract integration.** Audit every stream and stage host caller
  for monotonic `now` values and source timestamp normalization. If two
  clocks are mixed, add an explicit trusted conversion; do not guess.
- **P1 — Four-axis naturalness suite.** Offline, nonprivate test clips,
  benchmark baselines and blind review; evaluate false interruptions as well
  as failures to yield.
- **P2 — Learning benchmarks.** Run unseen Roblox scenarios and random seeds,
  compare success over repeated attempts and verify improvements with
  executable checks and regression tests.
- **P2 — Verified optimization A/B.** Try CPU TTS, small-model routing,
  speculative decoding and prompt-caching variants **only** when GPU/FPS
  pressure permits and tests show lower end-to-end latency without defects.

## Primary sources
- [Kyutai, multi-faceted full-duplex interactivity, June 2026](https://arxiv.org/abs/2606.11167)
- [NVIDIA PersonaPlex research, January 15, 2026](https://research.nvidia.com/labs/adlr/personaplex/)
- [Kyutai TTS and Pocket TTS](https://kyutai.org/next/tts/)
- [llama.cpp official SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
- [Roblox OpenGameEval repository and October 2026 paper](https://github.com/Roblox/open-game-eval)
- [Roblox built-in Studio MCP and playtest announcement, March 5, 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643)
