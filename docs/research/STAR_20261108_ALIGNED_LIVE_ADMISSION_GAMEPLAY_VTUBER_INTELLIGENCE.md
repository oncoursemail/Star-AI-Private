# STAR — aligned OBS admission, faster intelligence, gaming and VTuber research
Date: 2026-11-08. Status: offline-tested engineering + prioritized research, not yet deployed to Windows.

## 1. What was implemented

Star previously had several separately tested components: ObsStatsWindow measured OBS rendering/output lag, ObsStreamLossSampler measured live streaming network loss, ObsAlignedLiveSampler paired the readings, StreamLoadHostBridge matched host metrics to OBS intervals, StreamLoadGovernor classified workload pressure, and NaturalTurnBridge could suppress optional commentary.

Missing was a single opt-in, end-to-end host-owned lifecycle joining the first four. New star/obs_live_load_pipeline.py implements ObsLiveLoadPipeline:

1. Requires owner approval and a unique OBS host process/socket epoch to arm both the paired sampler and the load governor bridge. Replayed epochs cannot be rearmed.
2. Consumes two authenticated, strictly allowlisted OBS WebSocket v5 responseData mappings (GetStats and GetStreamStatus), independently timestamped from one host monotonic clock, and a complete measured HostLoadReceipt of game frame-time, VRAM use and speech latency.
3. Demands two consecutive valid OBS observations for the first interval. Aligns render and streaming network loss intervals, verifies the network-loss value in the load receipt matches OBS, and submits an advisory governor sample only when the evidence agrees.
4. Missing, stale, malformed, unverified, replayed, or disconnected OBS data immediately invalidates the epoch once a healthy observation was previously accepted. A bad host receipt always invalidates the session. This prevents stale green profiles from surviving a telemetry failure.
5. Offers current-time load advice only: never authority to start streaming, play audio, press a game key, or control an avatar. All features remain off until owner-approved.

The host_verified=True input is an assertion by an already trusted Windows host, NOT an authentication mechanism. That host must independently pin OBS PID, process creation time, WebSocket session identity and output transition event continuity, and call stop() on changes, missed events, reconnects or failed polling. This module neither opens sockets nor stores stream keys, viewer messages, audio or images. Live-stream readings cannot certify private recording behavior.

Offline tests verify normal warmup, OBS network overload, reconnect/counter reset, malformed inputs, missing frames, stale/reversed times, network mismatch, shared-governor stale state, and epoch replay prevention. See tests/test_obs_live_load_pipeline.py.

## 2. Next step: Windows read-only host integration

Only the trusted Windows host should:
- Connect to authenticated OBS WebSocket v5 on 127.0.0.1, make GetStats and GetStreamStatus requests only, and capture two response receipt timestamps with the same time.monotonic clock, expressed in milliseconds.
- Pin OBS process identity and socket session, and independently witness every output-state transition. Polling alone cannot prove absence of a quick stop/reconnect between samples.
- Derive game frame-time p95 from genuine game presentation instrumentation, GPU VRAM usage from OS/driver telemetry and TTS p95 from real native first-audible PCM timestamps, not generated text.
- Treat unavailable measurements as missing (never invent zero values). Stop the pipeline on transport timeout, loss of event evidence or unauthorized host state.
- Read the current recommendation when deciding whether to launch OPTIONAL speech or extra GPU work. The host must separately authorize actual output, game input, OBS operations and physical audio shutdown.
- Keep private nonbroadcast rehearsal separate from real live-stream resource observation; the former needs existing nonbroadcast status, disk-headroom and recording-output witnesses.

Suggested lifecycle: instantiate pipeline, arm(owner_approved=True, obs_epoch=verified_unique_host_epoch), sample paired OBS mappings and a complete contemporaneous HostLoadReceipt, call ingest(..., host_verified=True), then recommend(now_ms=trusted_monotonic_ms) at the decision boundary. On any missing source call stop(), never keep an earlier recommendation as fresh.

## 3. Biggest next intelligence upgrades

### Real-time gaming intelligence
Gym-Anything-RT (Aggarwal and Welleck, submitted October 27, 2026) reports 100 real-time minigames. In its benchmark GPT-6 Astra (xHigh) passed 9.0% during real-time play versus 75.0% when paused. These are the paper's measurements, not Star's. This shows that fast action and thorough deliberation must be separated.

Three-timescale design:
- Fast reflex worker: bounded capture -> recognize -> choose -> authorized input -> verify game response. Skip stale actions, hold/release keys reliably, and maintain strict game focus checks.
- Between-round teacher: deliberate tactics, generate practice curricula and candidate policies, then prove improvements on separate unfamiliar maps.
- Long-term capability vault: retain only verified, versioned skills with provenance and uncertainty. Separate practice and held-out evaluation; never contaminate sealed holdouts with proposed solutions.

Proposed study (NOT a result): three unfamiliar game families with 20 training and 20 holdout levels each, ten trials per level. Compare reactive-only, teacher-only and reactive+teacher with equal compute budgets, report wins, completion, unsafe actions, game-received acknowledgments, capture-to-action p50/p95 and OBS/game FPS degradation. Do not promote based on self-evaluation or an unverified victory claim.

### Inference speed on 8 GB GPU
Run paired hardware A/B experiments: local quantized 4B/7B/9B fast-route models at measured context lengths; llama.cpp baseline versus n-gram, draft-model, MTP and EAGLE3 speculative decoding when supported; per-session prompt-cache isolation; CPU versus GPU TTS; and full-sized versus smaller vision inputs on the same archived frames. Models larger than VRAM or long KV caches may swap and become slow. No universal tokens/sec numbers are assumed.

Use llama.cpp SPEED-Bench and exactly matched prompts/seeds/configuration to measure time-to-first-token, prompt tokens/sec, decode tokens/sec, acceptance ratio, latency p95, peak VRAM, errors and task correctness. Simultaneously record game frame-time p95, OBS render/output/network losses and audible voice latency. Promote only reproducible improvements with no regression in actual play or conversational audio.

Set resource-aware scheduling so game presentation and physical audio interruptions outrank optional reasoning, model downloads, deep research, video generation and overnight practice. Cache within the correct privacy boundary; never leak other conversations through shared KV state.

### Self-learning Roblox game creator
Roblox officially announced Studio agentic planning/building/playtesting on April 15, 2026, explicit per-Studio MCP tool routing on August 19, and expanded MCP Open Cloud and asset-import controls on November 4 (updated November 5). The new permissions mean powerful tools must stay scoped to test experiences and owner-approved actions.

Implement a repeatable create -> playtest -> inspect screenshot/log -> static Luau analysis -> repair -> verify loop, supported by StyLua, Selene, luau-analyze/lsp, Rojo and official Roblox Studio MCP. Try 4–8 small candidates within explicit CPU/RAM budgets, compare independent game-outcome measurements, and select only passing repairs. Maintain visual fidelity, performance, ergonomics and game quality checks for UI, VFX, animation, character grip, physics, lighting and audio. Preserve offline-first experiment history and rollback; GitHub is optional for publication rather than required for autonomous learning.

### Broader general knowledge
Develop a versioned, citation-backed knowledge base with explicit dates, source reliability and confidence. Distinguish verified facts from tentative hypotheses, instructions from untrusted webpages, game practice from internet claims, and Star's genuine episodic experiences from story/persona fiction. Add correction and deletion paths and small adversarial knowledge-retention tests.

## 4. Human-like streaming without misrepresenting being AI

Microsoft Research's Proact-VL (ICML 2026) addresses deciding WHEN to speak, how much to speak, and maintaining quality during live gaming. A natural streamer does not narrate every frame.

Make a session-scoped social director jointly reason about gameplay danger, actual comeback after verified failed attempts, viewer consent/moderation, owner barge-in, voice turn-taking, current OBS resources and avatar expression. It should frequently choose meaningful silence. Use persona modes (focused, sweet, playful cat/dog, teacher) as stylistic controls, not permission overrides. Build spontaneous but grounded humor and emotional expression without fabricating successes.

For a convincing stream, tie lip shapes, blink/gaze, head tilt, posture and hand gestures to ACTUAL PCM segments and observed gameplay events, not merely generated text. Natural pauses, occasional laughter, self-correction, voice interruption and consistent memories matter more than uninterrupted monologues. Actual audio output shutdown and avatar-neutral confirmation belong to the trusted native host; a model cannot attest physical silence. Allow social friendships and recurring jokes, but do not claim biological humanity, sentience, or relationships that have not happened. Identify Star clearly as AI.

Prototype on a private nonbroadcast session with game input only where authorized by a game's rules. Suggested acceptance study (future, NOT performed): ten 20-minute rehearsals measuring p50/p95 reaction latency, 95th percentile speech first-audible time, interrupted PCM remaining duration, avatar lip-sync offsets, factual errors/hour, game success and OBS frame losses. Require zero unauthorized broadcasts or unconfirmed physical stops. Establish quality thresholds from observed baselines before enabling default behavior.

## 5. Sources checked November 8, 2026
- Official OBS WebSocket v5 GetStats and GetStreamStatus response fields: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.json
- llama.cpp speculative decoding implementation: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp SPEED-Bench and controlled comparisons: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Gym-Anything-RT, October 27, 2026: https://arxiv.org/abs/2610.37567
- Proact-VL, Microsoft Research, ICML 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Roblox Studio Going Agentic, April 15, 2026: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox multi-Studio MCP, August 19, 2026: https://devforum.roblox.com/t/studio-mcp-multi-agent-improvements-and-connected-ai-clients/4820583
- Roblox Studio MCP Open Cloud/asset import, November 4–5, 2026: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

## 6. Release gate
This branch is unmerged and opt-in. Offline regression success proves logic properties but not actual Windows, OBS, gameplay mastery, inference-speed improvement, TTS realism or safe live streaming. Require real measurements and the full trusted host integration before promotion. Never silently enable external broadcasting, game input, private recording, spending or publishing.
