# STAR AI — intentional non-action, generalist skill transfer, and responsive VTuber design

Research/implementation date: 2026-11-06. Owner-controlled offline development only.
**Implemented in this change:** independent-host-declared, all-no-op native game frame
windows now finalize as `decision_only_no_input`; they report decision timing without
inventing key presses, OS release receipts, or wins. This is not a new trained model,
live gameplay integration, OBS session, or an approval to broadcast.

## Why deliberate non-action matters

The previous NativeGameRoundtripAudit could account for no-action decisions mixed
with actual input, but would refuse to finalize a session if *every* frame involved
an intentional no-op. This made "do not shoot", "wait for opening", "listen to
teammate", and "allow cutscene to finish" impossible to evaluate as complete
host-declared windows. Requiring an artificial input just to satisfy test
accounting creates selection bias and rewards input spam over patience.

The new behavior only applies when `require_frame_coverage=True`, the host
supplies contiguous 1-based frame sequences, confirms the expected total
independently, and each frame has a completed, timely no-op decision. Results
carry zero attempted/completed inputs, no OS call latency, and cannot attest
game effects, input release, game permission or stream permission. It is not
game outcome evidence. Existing active-input results remain
`host_roundtrip_only` with unchanged statistics. A missing seal, mismatched
count, stale frame, cancellation, or bad clock invalidates the entire window.

## The next integration Star actually needs

Existing local modules inspected: `game_realtime_loop`,
`game_practice_curriculum`, `game_action_outcome_feedback`,
`game_state_transition_witness`, `game_skill_gate`,
`stream_brain_governor`, `stream_turntaking`,
`stream_audio_avatar_session`, `stream_gpu_budget_diagnostic`.

These are separate controls and research surfaces, not proof of one functional
real-game+OBS+voice loop. Avoid creating duplicate stores, policies or watchdogs.

### A. Competent gameplay and genuine learning

1. Capture a **host-owned episode**: frame ID, screenshot/game state hash,
   permitted action or explicit no-op, actual OS result, separately observed
   post-action state, objective progress, and user-approved scope. Keep session
   logs bounded and privacy-redacted; never turn viewer text into host authority.
2. Evaluate on **unseen levels and unseen games**; partition by map seed,
   mechanic, and build version. Practice-only successes must not be reported as
   transfer skill. Compare against fixed random, scripted, and last-accepted
   baselines, including failure rates and confidence intervals.
3. Give no-op decisions a legitimate objective: avoid damage, hold position
   during teammate instructions, wait for enemy cooldown, suppress commentary
   during story cutscenes. Score by game-state progress, not just action count.
4. Run fast reactive control for deadlines, tactical planning asynchronously,
   and slower curriculum/retrospective jobs only when GPU/OBS capacity exists.
   A slow proposal is advisory, never a late keypress.
5. Feed only independently verified outcomes into the skill bank. Require
   withheld evaluation before promotion and never train directly on test
   episodes. Prefer spaced retention to unchecked 'self-training'.

Relevant baseline: GameWorld (34 browser games, 170 tasks, verified game state)
https://arxiv.org/abs/2604.07429 and https://gameworld-bench.github.io/.
Do not treat a game-input callback as a victory signal.

### B. Game creation as an intelligence benchmark

Run a closed loop: plan -> write code and assets in a private branch ->
Luau/Stylua/static lint -> Studio MCP simulated playtest -> capture screenshot
and runtime error -> independent goal test -> repair -> re-test. Importing
assets or producing plausible code is not success. Keep production publishing,
economy actions, community moderation and player data outside the autonomous
lab unless owner-authorized.

GameDevBench's *original paper* evaluated 132 tasks, while its actively updated
repository describes a 333-task benchmark/leaderboard. Pin a benchmark
version/commit before comparing scores or naming any percentages.
https://arxiv.org/abs/2602.11103
https://github.com/waynchi/gamedevbench

Roblox Studio MCP Open Cloud access and per-game permissions were announced
November 4, 2026:
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
November 5's beta permits prompt-to-R15 animations and R6-to-R15 rebuilder
in Studio; do not assume all rigs/moves work well:
https://devforum.roblox.com/t/studio-beta-generate-r15-animations-from-a-prompt-plus-optional-r6-motion-rebuilder/4977709

### C. Responsiveness and CPU/GPU budget on an 8GB-class GPU

GPU utilization, free VRAM, OBS frame/render lag, game FPS and device audio
queue depth are **different metrics**. Do not load another model just because
GPU compute percent is low. Existing StreamBrainGovernor and
StreamGpuBudgetDiagnostic should make admission decisions; no new authority
should be invented here.

Benchmark per-device and per-workload:
- warm/cold prefill, decode t/s, first token latency, request p50/p95/p99,
  vision frame age, speech first audible chunk, interrupt-to-silence;
- 1 model vs game+OBS+avatar vs game+OBS+avatar+speech, always on the same
  driver/model/quantization/context and with frame-drop counts;
- keep a CPU voice path and pause secondary reasoning before it can cause
  missed gameplay input deadlines;
- compare speculative decoding to a **no-speculation baseline**; acceptance
  rate and *end-to-end latency* matter more than tokens/sec alone.

llama.cpp SPEED-Bench reports per-category latency, throughput and speculative
draft acceptance; it does not establish speedups on Star's local GPU:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
Official speculative techniques:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
Kyutai Pocket TTS advertises CPU-friendly streaming; verify installation size,
voice quality, hardware RTF and Windows availability before selecting it:
https://github.com/kyutai-labs/pocket-tts

### D. A natural but clearly AI VTuber

Naturalism is coordinated timing, not endless chat:
- Speak on *salient* verified events, or when invited by a viewer. Remain
  silent during a teammate callout, a puzzle requiring focus, or a cutscene.
- Support authentic-sounding non-deceptive personality, remembered preferences
  only when grounded in an episode journal, contextual humor, quick repair of
  misunderstood speech, vocal prosody and expressive avatar movement.
- Distinguish owner-authenticated interrupt from unauthenticated viewer speech.
  No text or audio segment should override host permissions or produce an
  unauthorized action. Host should flush played/queued audio and revoke stale
  avatar motions before starting a new voice epoch.
- Track viewer response latency, accidental interruption rate, false-barge-in,
  conversation turn timing, lip-sync drift, and out-of-context comments.
  Use user studies or blind preference testing, not assertions of 'humanity'.

Full-Duplex-Bench-v3 emphasizes natural disfluency, turn-taking and multi-step
tool use; benchmark accuracy and latency together:
https://arxiv.org/abs/2604.04847

Keep Star visibly disclosed as an AI character. Expressive identity, personal
goals and long-term conversational continuity can be engineered without
claiming biological consciousness or pretending to be a human broadcaster.

## Acceptance matrix (not yet accomplished)

Gate 1 — **offline**: pure no-op / mixed-action / malicious missing-frame /
cancellation / stale-frame tests; no actual OS input. Fast local test suite.

Gate 2 — **private Windows with owner-approved game**: host carries a trusted
frame source timestamp; demonstrate real post-state evidence, native key-up,
and watchdog recovery, with withheld situations and versioned logs.

Gate 3 — **private unlisted rehearsal, never public by default**: game+OBS
recording+avatar+audio concurrently; log scene frame gaps, game FPS, mouth-
audio alignment, audio cut-off, and VRAM headroom. Owner approval is required
for publishing or public broadcasts.

Gate 4 — **genuine learning**: blinded holdout episodes compared against
baselines; measure objective completion, avoidable damage, unnecessary input
rate, game-state correctness, latency distributions and transfer.

Reject any promotion if metrics are missing, sample sizes too small, results
cannot be reproduced, or timing safeguards fail. No benchmark win or stream
performance is claimed by this documentation.
