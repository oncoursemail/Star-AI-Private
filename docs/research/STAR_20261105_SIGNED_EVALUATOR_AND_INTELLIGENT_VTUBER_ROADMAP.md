# STAR Intelligence — Signed Evaluation Evidence, Real-Time Game Intelligence and VTuber Roadmap
**Implementation and research audit — November 5, 2026.** This document distinguishes functioning offline code from experimental ideas. It does not claim a live gaming/OBS recording, improved neural weights, faster real GPU inference, or human consciousness.

## 1. Verified issue and the implemented security improvement

PR #995 introduced host-assigned `eval_cohort_sha256` to bind a baseline model, faster model, and ordered gameplay-verdict receipt to one experiment. A malicious or buggy producer could still simply set the same cohort digest and `host_verified=True` on fabricated records. Those are *assertions*; neither a suite hash nor an arbitrary cohort string authenticates the producer.

**This change implements a standard-library HMAC-SHA256 seal** for one immutable comparison bundle. `star/stream_route_evidence_seal.py` canonicalizes the complete aggregate and per-case evidence, domain-separates the signed message, and binds:
- one exact cohort, host evaluator build SHA256, raw artifact-manifest SHA256 and issuance timestamp;
- both routes' exact catalog model/runtime/voice fingerprints, workload and suite digest;
- trial counts, actual measured end-to-end p95 latencies and GPU peaks;
- every binary outcome, pre-registered critical-case flag, observation timestamp and host-verification state.

`sign_route_evaluation()` is **trusted evaluator-side only**; never expose this capability/key through model-generated code, Discord tools or a chat endpoint. `verify_route_evaluation()` rejects altered evidence using constant-time signature comparison. It rejects mismatched cohorts, out-of-order timestamps and raw evidence marked unverified.

`QualityGatedRouteSelector` gains **optional strict verification** through `require_signed_evidence=True` plus a seal and host verification key. The strict path returns `signed_evaluation_unverified` on bad/missing seals and `signed_evaluation_stale_or_future` on invalid issuance time; the prior owner-opt-in remains a prerequisite. Existing unsigned callers remain backward-compatible when strict mode is not enabled. Even signed success returns only *manual pilot advice* — no model launch, input injection, public broadcast, spending or self-improvement authority.

A seal authenticates a reporter who knows the key and prevents silent alteration. It does **not** prove that a GPU benchmark really ran, that hidden tests stayed hidden, or that outcome grading was correct. A responsible evaluator must create the raw artifact digest from **real sealed, independently graded evidence**; issue a random one-time cohort ID; protect the key outside the repo; pin evaluator and driver versions; and allow the owner to rotate/revoke keys. Keep a tamper-evident append-only used-cohort journal to prevent replay across evaluations. The present code checks bounded issuance and elapsed time, **not** global nonce uniqueness or independently verified raw artifact bytes.

### Host integration order (not automatically configured)
1. Before running a preregistered benchmark, create a host-generated random cohort and freeze task order, critical-case flags, exact evaluator version and scoring rubric.
2. Evaluate existing and candidate routes on the same hidden cases under **the same game/OBS workload**; capture timestamped raw output and independent pass/fail evidence.
3. Hash an immutable manifest of those artifacts; create the two `VerifiedRouteTrialSummary` receipts and `VerifiedPairedRouteCases` from host-scored data.
4. In the trusted host process only, sign the bundle with an independently generated 256-bit or stronger HMAC key, securely stored outside the Git worktree.
5. Pass the seal, matching immutable evidence and verification key to `QualityGatedRouteSelector` with `require_signed_evidence=True`. Validate all normal quality, resource and freshness gates, then separately seek owner approval for any manual pilot.
6. Never store the key in JSON, PR comments, Discord logs, model context, screenshots, documents, source code or a public release. Public seals may be inspected without revealing the key.

## 2. Highest-leverage performance architecture

STAR needs **measured end-to-end correctness per second**, not an unspecific 'intelligence multiplier'. Split into three bounded execution classes:

| Class | Examples | Budget and control |
| --- | --- | --- |
| Real-time control | dodge, interact, interrupt speech, respond to urgent player event | event loop that cannot block on LLM output; bounded action deadline and safe no-op fallback |
| Interactive intelligence | viewer answer, game tactical plan, Roblox Studio code task | quality-aware router with host-signed paired held-outs, realtime VRAM/FPS/OBS admission |
| Offline learning | practice variants, code review, model evaluation, skill curation, memory consolidation | low-priority jobs that yield CPU/GPU immediately to games and recording |

Use a bounded event bus with explicit `observed_at`, `deadline`, `scene/session`, `source`, `confidence`, `verified outcome` and deduplication key. Expire stale observations before they become game actions; do not let chat or a VLM invent a state assertion. Keep a small fast tactical working set, retrievable project docs and an append-only verified lesson store. Allow parallel best-of-N candidate generation only when there are independent, resource-bounded validators and actual improvement compared with a simpler baseline.

**Measurement harness:** Compare tokens/sec, first-token latency, p50/p95 action-to-effect, p50/p95 first *audible* phoneme, correct verified game actions before deadline, game 1%-low FPS, VRAM peak/free headroom, OBS render/encode lag, temperature and queue wait. Evaluate with and without simultaneous OBS/VTuber/avatar tasks. Re-run every candidate with fixed seeds plus sealed unseen challenges, and do not promote when any registered critical task worsens. Practical `llama.cpp` starting points: [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md), [llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md). Speculative decoding is **not** a universal speedup: draft-model compute and VRAM can worsen total stream quality.

**8 GB VRAM operational detail:** The 3060 Ti/4060 are materially constrained by concurrent LLM KV cache, game textures/framebuffers, capture and avatar renderer. Prefer starting with one quality-verified, right-sized inference worker; favor CPU speech when it improves *actual* latency without inducing CPU scheduling failures; defer background learning or large models on GPU under stream load. No model-memory figure or tokens/sec claim in this note is asserted for Star's hardware.

## 3. Game-playing intelligence that improves through practice

Research: [GameWorld-RT](https://gameworld-project.github.io/) emphasizes that interactive worlds keep moving during the agent's inference. [Roblox OpenGameEval](https://github.com/Roblox/open-game-eval), updated October 2026, grades actual Studio state changes and play sessions across 84 curated tasks; inspecting relevant objects before editing correlates with better results. [GameDevBench (ICML 2026)](https://sethkarten.ai/papers/gamedevbench.html) evaluates 132 real game-development challenges and finds major limitations on graphics-focused work.

**Curriculum design:** Build reproducible, offline/private exercises across platforming, pickup/drop, movement, combat timing, inventory, shops, vehicle entry/exit, puzzle solving, checkpoints, co-op, camera control and UI use. Each skill has a goal checker based on privileged game/server state (when available), not on Star's own narration. Randomize safe development levels, freeze 20% as untouched holdouts and log every attempt's action deadlines, recovery paths and evidence. If ground truth is unavailable, mark outcomes 'unverified' rather than inventing a win.

**Practice loop:** Observe → propose 2–4 bounded plans → select under latency/resources → execute only authorized game actions → record state transitions → independently check success → replay failures off-stream → extract lessons only from verified outcomes → test again on hidden levels. Promote learned skills only when new held-out wins exceed regressions and the owner-approved safety envelope still applies.

**Roblox creation loop:** Studio's built-in MCP and April 2026 Playtest Agent beta offer inspection, scripted editing and automatic player tests [official announcement](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic), [beta details](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767). Use inspect-before-edit, Lua type/lint checks, saved place snapshots, authorized private playtests, object/physics assertions, screenshots plus *actual* output verification and instant rollback. Do not treat an attractive screenshot as proof that a game works.

## 4. More natural, grounded and expressive VTuber streaming

Research: [Microsoft Proact-VL (ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) explicitly studies when to speak, when to stay silent, and how much to say during games. [NVIDIA PersonaPlex (January 15, 2026)](https://research.nvidia.com/labs/adlr/personaplex/) explores full-duplex conversation, role and voice conditioning; [DyaPlex (June 2026)](https://research.nvidia.com/labs/amri/projects/DyaPlex/) studies joint streaming speech and motion. These are research directions and may not fit an 8 GB concurrent gaming GPU.

**Near-term behavioral system:** Give Star a stable, explicitly AI identity, habitual greetings without repetition, event-grounded jokes, speech interruption handling, turn-taking, appropriate 'hmm' and laughter, attention-aware gaze, speaking only when useful, and memory tied to *real* witnessed game/chat events. Do not claim genuine human feelings or impersonate people. Preserve viewer privacy: consented, scoped memory with expiry, delete options and no extraction of secrets from chat. Treat chat as untrusted text. Use server-side chat rate limits and offline speech tests before opening any public channel.

**Voice trial:** [Kyutai Pocket TTS v4.0.0 (released October 20, 2026)](https://github.com/kyutai-labs/pocket-tts/releases) adds English 18M, 7M and experimental 2M-class voices plus CPU runtime binaries. Run controlled private A/B against current voice on the same English scripts: intelligibility, expressive range, first audible audio, real-time factor, CPU load, game FPS, interruption cut-off, correct avatar lip-sync and owner-approved voice identity. Smaller models may sound worse; select only on blinded listening plus measured responsiveness.

**Streaming sequencing:** Start with prerecorded private rehearsal; validate microphone permissions, separate audio output, virtual microphone loopback, avatar visemes and camera cues, OBS record-progress proof and local transcript matching *captured waveform*. Only later consider an explicitly owner-authorized public stream. If GPU/OBS performance degrades, cut optional background inference first, not the game or audio safety path.

## 5. Testable acceptance checklist

- **Signed routing:** strict mode refuses unsigned, mutated, mismatched, wrong-key and stale attestations; still requires explicit owner opt-in; never dispatches models/actions.
- **Intelligence:** independently verified win/correctness percentage improves on sealed unseen tasks; no critical regression even when latency improves.
- **Gaming:** at least 20 distinct scenarios and multiple unseen procedural seeds each; log input deadlines and actual world-state success.
- **Roblox coding:** savepoint, inspect before edit, lint/type check, genuine Studio playtest, rollback on independent failure.
- **Speech:** private audible recording with verified first-audio onset and interruption response; silence is acceptable when helpful.
- **VTuber:** 30-minute private combined gameplay + avatar + real TTS + OBS run, no hidden broadcast; GPU/CPU/OBS telemetry proves stability; human review of naturalness.
- **Infrastructure:** the owner knows where encryption keys live, how to rotate them, how to audit a signed cohort and roll back a failed feature.

### Evidence scope
This PR ships signed **offline evidence integrity** and regression tests. It does **not** implement the trusted training runner, replay-prevention journal, independent hidden grader, hardware benchmark, live gaming loop, full-duplex model, or private recording itself. Existing live worker catalogs and permission gates remain unchanged.

**Research checked:** November 5, 2026. Publication dates above refer to when the cited research was released, not when Star adopted it.
