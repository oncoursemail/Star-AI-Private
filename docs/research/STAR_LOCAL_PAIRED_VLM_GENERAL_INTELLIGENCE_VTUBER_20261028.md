# Star Intelligence: Paired Local Vision, Autonomous Gaming, Knowledge, and Natural VTuber — 2026-10-28

## Scope and verified status

This review follows the stacked, unmerged vision work in draft PRs #719–#732 and
does **not** rewrite their infrastructure. The new implementation is
`star/stream_local_vlm.py`: an opt-in, bounded **two-frame local llama.cpp
multimodal worker** that is directly compatible with the existing
`WindowsGameCaptureHost(trusted_worker=...)` callback. It is the first concrete
host-side protocol adapter in this stack for communicating with a VLM, rather
than merely accepting an abstract callback result.

It **has not** loaded a vision model, captured a real Roblox frame, performed a
real VLM inference, played a game, trained a model, deployed to Windows, started
OBS or generated natural speech. Contract tests exercise in-memory synthetic
frames, model-shaped responses, HTTP protocol constraints and failure modes.
Actual image understanding and performance need a Windows acceptance trial.

Previous work already provides: authorized pinned-HWND Windows capture;
hardware/VisionLease scheduling; foveated + temporal change detection; a
`VisualPacket` categorical schema; a reported-evidence stream cue gate;
verified game memory and randomized practice experiments. New work should
**connect and evaluate** these components, not add redundant abstract layers.

## The concrete missing link

The earlier vision bridge accepts a host-supplied `trusted_worker(frame)`, but
does not select or call a real VLM. Also, a single screenshot cannot generally
prove that a menu, scene or HUD *changed*. Asking a model to infer change from
one frame creates a high-confidence hallucination risk. This patch makes the
comparison explicit:

```text
owner + window authorization (existing, OFF by default)
  -> pinned Windows game-window frame (existing)
  -> measured hardware/FPS/VRAM admission (existing)
  -> LocalLlamaComparisonWorker (new, OFF by default)
       -> keep one bounded previous JPEG in RAM
       -> compare older and newer frames ONLY if same dimensions/fresh clock
       -> synchronous POST to 127.0.0.1:<owner-selected-port>/v1/chat/completions
       -> llama.cpp multimodal images + constrained JSON schema
       -> parse into strict VisualPacket from trusted host frame metadata
       -> scrub reference bytearrays, return WorkerReport
  -> host verifies pinned window, epoch and physical worker-stop evidence
  -> optional GameVisualCueHost (existing, OFF by default)
       -> second distinct agreeing observation, deliberate silence
       -> reported (not verified) evidence; no speech or win animation
```

Both images are resized in memory (default maximum side 512 px) and
lossy-compressed as JPEG to bound bandwidth/prompt cost. Their bytes are never
written to disk or logged by this module. Python/Pillow and base64 can create
temporary copies, so **perfect secure memory erasure is not claimed**.
A previous-frame bytearray is explicitly wiped on replacement, disable,
window mismatch, error or quarantine. Worker configuration accepts *only* a
numeric local port and bounded model alias; no arbitrary hostnames, IPs, URLs,
redirects, shell commands, upload destinations or cloud endpoints. This adapter
does not provision a model or server.

### Why a timeout cannot mean success

A local HTTP **client** that times out may have disconnected while llama-server
is still computing. On timeout, mid-response failure, unexpectedly oversized
HTTP response or ambiguous transport failure, the worker returns
`WorkerReport(stopped=False, succeeded=False)` and quarantines itself.
The existing `StreamVisionHost` also retains its lease until the trusted host
confirms that server-side request/inference has physically stopped.
`clear_quarantine` alone never acknowledges or releases that upstream lease.
A *complete* synchronous HTTP response is evidence the request finished, not
that the long-lived llama-server was shut down. This distinction matters in a
GPU-constrained live stream. No automatic restart/retry is authorized.

A first frame creates a local baseline but cannot claim a change. Unknown or
invalid JSON remains silence; a VLM's own confidence score cannot assert
game success or trigger privileged input. The model is never given authenticated
game API access. Raw game pixels, UI text and chat are untrusted data.

### Practical integration (trusted host only)

```python
from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import WindowsGameCaptureHost

vlm = LocalLlamaComparisonWorker(
    model="OWNER_SELECTED_LOCAL_VISION_ALIAS", port=8080,
    max_image_side=512, timeout_seconds=8.0,
)
# Independently from the existing vision/capture approvals:
vlm.enable(owner_approved=True, local_model_approved=True)
capture = WindowsGameCaptureHost(
    enabled_vision_host, hwnd=host_selected_hwnd, pid=verified_game_pid,
    trusted_worker=vlm,
)
# The host separately enables the capture and vision governors, refreshes real
# hardware telemetry and runs capture.capture_and_process_once() on its worker.
# On stop: disable capture, stop/join any in-flight inference, retire leases,
# disable vlm, then shut down the stage/audio/renderer as appropriate.
```

This is **illustrative**. The caller must select and provision a tested
llama.cpp multimodal model/projector; correct owner permissions and physical
worker stop cannot be inferred by this module. Do not connect to a public or
remotely exposed server; bind llama-server to loopback, protect its process,
keep cloud access OFF, and do not embed API keys in the repository.

## Current external evidence (checked October 28, 2026)

1. [llama.cpp multimodal guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)
   documents multimodal input through `llama-server`, model-specific image
   projectors and optional CPU/GPU offload. The official
   [server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
   documents image data URLs for `/v1/chat/completions` and schema-constrained
   `response_format`. **This is API evidence, not model accuracy validation.**
2. [Roblox Studio's built-in MCP server / Playtest Agent announcement,
   March 5, 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643)
   describes Studio playtest control and simulated player input. Use approved,
   private test places and executable checks, not screenshots as a substitute
   for game truth.
3. [OpenGameEval, October 1, 2026](https://github.com/Roblox/open-game-eval)
   evaluates 13 frontier models on 84 Roblox Studio tasks in 16 attempts per
   task. The top tested model solves only 51.7% of tasks in one attempt.
   Inspection coverage correlates with successful outcomes (reported +13.4pp
   scene-only, +9.8pp script-only holding model and task fixed; association is
   not causation). Benchmark Star on held-out executable outcomes, not vibes.
4. [Kyutai Pocket TTS, October 2026](https://github.com/kyutai-labs/pocket-tts)
   now includes 18.2M, 6.9M and experimental 1.9M English models and CPU
   streaming. This suggests an option for conserving the RTX 4060's 8 GB VRAM;
   pronunciation, expressive range, first audio latency and commercial terms
   must be measured and reviewed before using a voice in public streams.
5. [LiveKit local and cloud audio turn detection](https://docs.livekit.io/agents/logic/turns/turn-detector/)
   distinguishes the lightweight local `v1-mini` from hosted full inference,
   and documents adaptive endpointing. A natural streamer should not equate
   every silence or VAD spike with an interruption.
6. [VTube Studio official API](https://github.com/DenchiSoft/VTubeStudio)
   defines opt-in local WebSocket parameter and hotkey operations; use
   authenticated plugin permissions, never let game/chat text choose raw
   hotkey IDs. [Live2D Cubism SDK docs](https://docs.live2d.com/en/cubism-sdk-manual/top/)
   show motion/physics and MotionSync infrastructure; licensing applies to
   its proprietary core and produced assets.
7. [MLPerf Client benchmark methodology](https://mlcommons.org/benchmarks/client/)
   separates time-to-first-token, output throughput and end-to-end agent
   latency. Throughput alone is not a measure of Star's correctness or
   responsiveness during gameplay.

## Recommended next projects, ranked by demonstrated value

**P0 — Close the Windows gaming loop, without pretending screenshots are wins.**
On Brain 2, connect the pinned window capture to a *host-installed* local
multimodal model on loopback, then to the existing VisualPacket bridge. Record
game event timestamps, target FPS and 1% low, actual VRAM, CPU memory, cue
delay, perception precision and false reaction rate. Evaluate two-frame versus
single-frame observations on a withheld synthetic+authorized game corpus.
Compare model output to **independent Studio engine state**. Block any action
based only on VLM conjecture. Authorize game inputs separately.

**P0 — Real control and outcome telemetry.** Wrap an approved Roblox Studio
MCP playtest session with an observation -> action -> game-engine assertion ->
event ledger interface. Existing GameVisualEffectProbe, GameRecallAudit and
PairedGameStudy then have real, game-state-grounded material. Define a
reproducible starting state and evidence receipt for every attempt. Reject
replay, stale windows, redirected HWND and scene mismatch. Only then consider
action policy search / imitation / offline RL.

**P1 — Adaptive multitask scheduling on 8 GB VRAM.** Keep the existing
Litha compute-mesh work (#730/#731) independent. Use a fixed stream-time VRAM
reserve and separate priority queues: (1) game/render/audio, (2) short speech
turn, (3) bounded vision, (4) deeper knowledge/reasoning off-peak. Run A/B
measurements for small CPU vision, low-bit GPU multimodal and remote Brain 1
workers *only on owner-controlled nodes*. Never assume moving a model to CPU
wins overall: measure PCIe traffic, tail latency, dropped frames, speech
backlog and memory pressure. Reuse static prompts/KV cache if verified and
never expose screenshots through shared caches.

**P1 — Performance-driven candidate verification.** Star's bigger improvement
will come from generating 4–8 candidates, executing safe Luau/Studio tests,
reranking by held-out outcomes and promoting only proven results. Add
visual-geometry checks (floating props, wall gaps, z-fighting, wrong grips,
collisions, animation deformation), design-specific image comparisons, physics
tests and human taste review. OpenGameEval's executable harness should anchor
the first test suite; do not overfit to the published benchmark tasks.

**P1 — Genuine, expressive streaming.** Use the existing Stage, Director,
TurnTakingGate and QuietAttention rather than installing another competing
speech planner. Integrate host-side local Pocket TTS in a separate OFF-by-default
adapter; measure first audio chunk latency and human-rated naturalness. Only
animate phoneme/lip parameters after audible playback is acknowledged. Give
Star's final chibi star-themed look physically plausible but restrained
twin-tail/ribbon spring dynamics, asymmetry, eye darts and recovery from laughs.
Rate-limit reactions, avoid performing constant commentary and use local VAD
echo cancellation. Her consistent birthday, modes and personal interests are
**character continuity**, not a claim to human consciousness or fabricated
offline experiences. Disclose that she is AI.

**P2 — Long-horizon learning across games and domains.** Store separate
verified episodic memory, procedural gameplay skill, source-backed general
knowledge, spatial/scene maps and tentative hypotheses. Every retrieval carries
source, time, confidence, revocation path and *which machine/game instance* it
came from. Expire stale information, merge duplicates, test recall against
held-out game episodes and compare new strategies using pre-registered
game-state-matched experiments. Star should be curious but should not treat
self-generated answers as training labels without an independent evaluator.

**P2 — Star Core Forge as an offline autonomous lab.** Use local immutable
version history, signed test receipts, worktree isolation, semantic diffs,
blinded evaluations, resource-constrained experiment scheduling, rollback,
and deployment authorization. GitHub is optional review/publication. Run
non-critical practice and evaluation autonomously; route real external
publishing, money, credential and account permissions through owner-set
limits. Never let a candidate change its own evaluator to claim success.

## Acceptance gates (do not confuse a passing unit test with deployment)

| Gate | Minimum evidence |
|---|---|
| Source and safety | Ruff, compileall, offline unit tests, diff check, no credentials or captured frames |
| Protocol | Correct loopback-only POST, two distinct frames, schema-constrained output, rejected hostile text |
| Stop safety | Timeout and truncated response remain quarantined until physically stopped; no accidental lease release |
| End-to-end Windows | Approved game HWND/PID only; no desktop fallback; owner toggles OFF by default; measured capture-to-cue p50/p95 |
| Gaming truth | Test against Studio state, compare independent ground truth, blind held-out gameplay challenges |
| Stream realism | Human-scored timing, repetition, false-react rate, interruption latency, perceived naturalness |
| Hardware | 1% FPS low, p95 model latency, CPU/GPU/VRAM/RAM power; no stream regressions at 8 GB VRAM |
| Learning claims | Cross-game generalization, seed-controlled paired studies, held-out recall and statistical confidence |

### Suggested initial acceptance experiment

On an owner-approved, unpublished Roblox Studio test level, perform 100
pre-registered transitions (50 real HUD/scene changes, 50 no-change or
distractor events). Hold out the labels until evaluation. Capture exact game
state with Studio checks; compare with VLM output and timestamp. Evaluate
precision, recall, false-celebration rate, cue latency, frame-time impact and
VRAM. Repeat with downscale sizes 256, 384, 512, 768 and the same model/seed.
Use no names, Discord messages, external player data, private desktop surfaces
or persistent video recordings. This is a proposed trial, **not a performed
test**.

## Publication boundaries

The stacked branch is **draft only**. Nothing in this change has been merged,
deployed or enabled on a streaming PC. Source tests do not prove model
availability, inference speed or human-quality speech. In particular,
`oncoursemail/Star-AI-Private` currently reports *public* visibility despite
the name. No credentials, model weights, game screenshots, human recordings,
viewer identities or runtime config secrets belong in this PR.
