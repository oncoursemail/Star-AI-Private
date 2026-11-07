# STAR: measured inference, grounded gameplay and humanlike VTuber engineering
Research and implementation note · 2026-10-25 · Draft, disabled unless the owner explicitly runs a test

## Actual change in this revision

The new star/inference_ab.py is a dependency-free, loopback-only streaming benchmark, usable
with Star's existing OpenAI-compatible llama-server runtime. It measures real first-content
latency and full-response latency from an already-running local model. Baseline and candidate
must use the same public synthetic prompts, the same model ID, matching SHA-256 model/server
binary files when supplied, and the same host fingerprint (hashed, never the hostname).
It reports paired medians and nearest-rank p95, rejects failed/unmatched or suspiciously
shorter results, and **never enables speculative decoding or other settings**.

Do not confuse this with an intelligence increase. Neither a short latency test nor matching
output lengths establishes answer quality, improved model weights, better gameplay, or faster
streaming on the actual user's GPU. The gate only returns "promising_only" for repeatable
smoke-test latency improvements without obvious length/tail regressions. Real deployment
requires separate held-out evaluation and prolonged hardware measurements.

### Runbook (opt-in; no automatic server start)

1. On the same computer, with the same local GGUF, the same pinned llama-server.exe,
   the same game/OBS state and same model ID, run llama-server without speculation.
   Confirm the installed binary supports the requested options with --help.
2. From this repository:
   python -m star.inference_ab run --arm baseline --model YOUR_MODEL_NAME \
     --url http://127.0.0.1:8080/v1 --repeats 2 \
     --model-file /path/to/YOUR_MODEL.gguf --binary-file /path/to/llama-server.exe \
     --output baseline.json
3. Stop the server normally, start the exact same binary/model with the experimental
   --spec-type ngram-simple --spec-draft-n-max 16 (or another supported value). Do not
   concurrently run both 8 GB VRAM configurations on the same GPU.
4. python -m star.inference_ab run --arm candidate --model YOUR_MODEL_NAME \
     --url http://127.0.0.1:8080/v1 --repeats 2 \
     --model-file /path/to/YOUR_MODEL.gguf --binary-file /path/to/llama-server.exe \
     --output candidate.json
5. python -m star.inference_ab compare --baseline baseline.json --candidate candidate.json
6. Repeat in reverse start order on a fresh day and test real voice/gameplay quality,
   total FPS, frametime p95/p99, OBS dropped frames, VRAM, temperature and stream audio
   before considering any owner-approved default change. Use the upstream llama.cpp
   SPEED-Bench on diverse categories for a more comprehensive throughput assessment.

For authenticated *local* llama-server, optionally put the key in
STAR_BENCH_LOCAL_API_KEY in the process environment. The key is never written to a
benchmark report. The command connects only to the numeric loopback address, no cloud
URLs or LAN, no proxy, no redirects. Reports include only task IDs, timings, answer length,
hashed output, synthetic fixture hash, hashed host fingerprint and optional file SHA-256s.
Do not commit reports if the host fingerprint is considered private.
A changed answer hash is **not** an automatic quality regression, but must trigger review.
No settings file is modified, no game control is sent, and no broadcast begins.

The current fixture is intentionally eight small tasks and repeated sequentially; it
cannot substitute for a statistically powered benchmark or general-knowledge examination.
Completion-token throughput is recorded only if the server supplies usage; otherwise
character length is a comparison check, not token throughput. This benchmark does not
measure first audible sound (TTS), just first *text content*. It captures timing after
a manual server restart, so power profiles, thermal drift, and cache state must be
controlled. A preliminary "promising" signal is not authorization to deploy.

## Research synthesis: the five highest-leverage systems for STAR

### 1. Budgeted, measured realtime intelligence

STAR needs separate service levels: live speech and gameplay input are deadline-driven;
code quality, long research, self-play and rendering are throughput-oriented background
jobs. Each request should carry explicit priority, maximum stale age and cancellation
token. Reserve room for the game and encoder before loading another GPU model. On a
single 8 GB GPU, adding a second draft model can hurt rather than help; the ngram-simple
approach avoids extra draft-model weights, but can *still* regress on short text or code.

Measure p50/p95 TTFT, prefill throughput, decode rate, speech-end-to-first-audible-sound,
time to stop after interruption, microphone echo false positives, audio underruns,
OBS outputSkippedFrames, and frame time. A fast text model with bad first-audio delay
will still feel robotic. Compute frame time from capture timestamps, not only average FPS.

Do not hard-code arbitrary "faster by 3x" claims. Use pinned builds, prompt classes and
back-to-back A/B on the same hardware; promote only after no held-out accuracy regression
and explicit owner approval. Profile queueing before adding speculative decoding, cache
banks or multi-agent parallelism. The source of the bottleneck matters.

### 2. Learn to play games by verifying consequences

Existing STAR research branches contain navigational belief state, closed-loop practice,
skill records and held-out promotion gates. Do not pretend this is integrated into a live
Roblox client. Next real milestone: an authorization-scoped local game adapter with
observable, time-stamped frame+HUD+position/reward telemetry, allowed control inputs,
stop-switch and stable episode IDs; no anti-cheat bypass, protected games or unauthorized
play. The actuator must acknowledge execution, then the observer must confirm the outcome.

Per-episode record:
 game/version/seed -> initial observation -> objective -> bounded action ->
 observed effect -> external outcome -> error category -> skill proposal.
Keep practice and held-out seeds separate, never train on test runs, and do not count
repeated frames as independent successes. New map layouts and control changes are the
transfer test. Star should know what she *observed*, what she *predicted*, and what remains
uncertain. Voyager's executable skill memory and SIMA 2's self-generated experience
illustrate useful patterns; neither demonstrates that a small local model can generalize
to all games without specialized perception, control and significant training.

Build game-specific adapters first (sandbox platformer -> controlled Studio test place ->
separate authorized game) before aiming at general game play. Use a low-cost model for
fast actions and a slower planner for episode summaries. Make choices conditioned on
observable game state, not ungrounded screenshots or imagined input effects.

### 3. Build quality beyond "AI slop"

Native Roblox Studio test places should have scene grammar, prefab placement bounds,
CFrame/orientation and scale contracts, anchored/attached structure checks, collision
and clipping audits with semantic exceptions, texture/UV and material consistency, UI
safe-area/resolution inspections, lighting checks, and FPS/LOD budgets. Visual regression
requires real Studio screenshots at the same camera, viewport and lighting. A vision
critic can propose edits but cannot certify "perfect" without ground-truth checks and
human aesthetic acceptance. Robot playtests must run after content generation, not just
compile scripts. Use documented Roblox Studio mechanisms, not undocumented CLI flags.

### 4. Natural, expressive, transparent VTuber

Keep STAR's mascot identity and persona stable across sessions (normal, cat, puppy modes);
time laughter, pauses, backchannels and reactions to actual verified events. A short
reactive voice reply may beat a long "smart" answer if a game moment lasts 500 ms. Allow
natural interruptions, but cancel outdated caption/viseme/voice packets atomically so
the face never mouths a cancelled answer. Prioritize avatar eye/head/body gestures,
blink variation, ear/tail secondary motion, phoneme-viseme alignment and hair physics
with reduced-motion accessibility.

Full-duplex audio research (Kyutai Moshi, NVIDIA PersonaPlex) and synchronized speech/motion
research (DyaPlex, June 2026) are relevant architecture references, not integrated
dependencies. The realtime models may exceed the available 8 GB VRAM in full configurations;
benchmark memory before choosing them. A CPU-capable lightweight TTS plus a separate
local LLM may be more feasible than an end-to-end 7B duplex model while gaming. The
first test must be a local, OBS-off rehearsal. Use OBS WebSocket only after explicit
consent; restrict it to localhost or the owner's LAN, require authentication, and never
start a public broadcast by default. A fictional personal history is fine when presented
as fiction; STAR should never claim invented real human lived experiences.

Separate viewer priority queue (owner, moderators, active game instruction, ordinary
chat), persistent verified stream moment memory, and cooldown for repetitive commentary.
Evaluate with recorded, consented synthetic chats: response timing, interrupt accuracy,
repeated jokes, emotional fit, and hallucinated gameplay/identity claims.

### 5. General knowledge that improves instead of bloating

More text in retrieval does not imply more intelligence. Use a provenance-aware source
index with document/version/license/digest, cross-source contradiction checks, retrieval
by task, stale-fact TTL and citation targets. Always distinguish training examples,
retrieved facts, autonomous hypotheses, and independently verified results. Keep
external retrieval default-off unless enabled. Curate a license-compatible dataset;
do not scrape closed/private content. Schedule expensive offline quality evaluations on
Brain 1 and leave the Studio/game/voice machine responsive.

A promotion gate must compare candidate to baseline on held-out general knowledge,
Luau correctness, Roblox rendered-building consistency, multi-turn instruction
following, genuine game episode rewards and streaming conversation quality. Count
independent environments, not merely repeated prompts. Include regression counts,
quality margins, CPU/RAM/GPU costs, and rollback directions. Improvement to an isolated
tool does not demonstrate increased IQ or model parameter capability.

## Engineering next steps and acceptance

P0: After this PR, run the new local A/B harness against the owner's *actual* installed
model in four alternating sessions; pair it with upstream llama.cpp SPEED-Bench, test
short natural voice vs long code separately, and record game/OBS telemetry.
P1: Integrate the existing offline gameplay planner/skill memory and previously added
stream moment memory behind one *real* host observation/control boundary, in an approved
test game. Apply episode IDs to prevent observations from an old action crossing turns.
P2: Add a rehearsal-only OBS/rig adapter using tagged turn epochs: audio, captions,
expressions and mouth motion must share epoch and cancel on barge-in.
P3: Build a curated, licensed and versioned general-knowledge index with blind tests;
only then consider data augmentation/fine-tuning. Performance gates must cover quality,
not only latency. Keep main branch and streaming services unchanged until CI and
owner-review requirements pass.

## Primary sources consulted (checked 2026-10-25)

- ggml-org/llama.cpp, speculative-decoding documentation:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp SPEED-Bench (separate official benchmark; baseline comparison):
  https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- Google DeepMind, SIMA 2 self-improvement in interactive worlds:
  https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager, open-ended skill memory and curriculum:
  https://arxiv.org/abs/2305.16291
- DreamerV3, Nature (2025), learning through imagined environment futures:
  https://www.nature.com/articles/s41586-025-08744-2
- NVIDIA DyaPlex project and paper, June 2026:
  https://research.nvidia.com/labs/amri/projects/DyaPlex/
- Kyutai speech research and Moshi:
  https://kyutai.org/
- OBS WebSocket official authenticated server:
  https://github.com/obsproject/obs-websocket
- Roblox Creator Hub, Assistant for Studio / documented Studio capabilities:
  https://create.roblox.com/docs/assistant/guide
