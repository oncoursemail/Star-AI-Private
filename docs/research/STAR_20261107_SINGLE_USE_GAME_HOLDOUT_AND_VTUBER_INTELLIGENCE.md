# STAR AI — Single-use evaluation cohorts and the path to real gaming/VTuber intelligence
Research and implementation: November 7, 2026

## Why this change

PR #1056 added an offline paired paused-versus-realtime gameplay audit. PR #1057 added anonymous scenario stratification. Both can diagnose failures, but a protocol SHA-256 digest on its own cannot stop one agent from repeatedly inspecting the same held-out cases and optimizing toward their answers. Such adaptive peeking creates false apparent progress.

This upgrade adds the stdlib-only, private HoldoutOnceLedger in star/game_holdout_once_ledger.py. A trusted owner host must reserve its complete, immutable, preregistered 20–256-case cohort BEFORE the paused or real-time engine run begins. Atomic SQLite uniqueness prevents reuse of an individual case, including overlap between different protocols and across simultaneously open ledger connections.

Reservations are permanently consumed even if the run is abandoned, crashes, or submits malformed/incomplete evidence. The first finalization attempt is sealed before results are inspected, so an invalid attempt cannot be retried with selectively improved numbers. A valid attempt produces the existing failure atlas strictly for owner review, with no permission to train, promote models, press inputs or broadcast. Default owner approval is OFF.

The ledger stores a protocol digest, opaque random reservation receipt, count, state and HMAC-SHA256 of each canonical game-scope/scenario/seed triple. Raw scenario IDs, seeds, gameplay, video and viewer data are not stored. The key must be independently generated, secret, stable, safely backed up and managed by the host; reopening with a different secret fails.

### Host-side integration (no automatic live actions)

1. Prepare an independent private testing host. Freeze game build, canonical game/version scope, holdout scenario/seed list, timing budgets and outcome verification methods.
2. Load a stable 32-plus-byte random HMAC key from protected local storage, then create HoldoutOnceLedger using a fixed absolute SQLite path in a protected directory.
3. Explicitly reserve the protocol with owner_approved=True BEFORE running either evaluation mode. Pin the opaque receipt to the exact engine session in a separate host log.
4. Run every planned case in both modes with independent resets and outcome/acknowledgement witnesses. Include losses, timeouts, crashes and other poor results; do not feed raw holdouts to the agent.
5. Finalize ONCE with the complete list of GameModeGapPair results. The result is an owner-only descriptive atlas. If the run cannot complete, abandon the receipt so the cases cannot be reused.
6. Use the atlas to suggest only broad follow-up **practice** experiments on NEW seeds, never to tune the model to the evaluated scenario/seed identities. Reserve fresh holdouts for a later, independently planned evaluation.

### Threat model and limitations

This implementation is a local anti-replay safeguard, **not** a proof of result independence, signed engine attestation, secure enclave, model improvement or a tamper-proof ledger. An adversary with DB write/delete privileges can roll back or destroy the ledger; aliases for the same physical game/scope can evade its canonical case index. A secret leaked to an attacker who also controls the database undermines the index. A crash after marking a run sealed intentionally consumes its cohort. For stronger evidence use independent append-only/off-host log replication, filesystem permissions, version-pinned games, authenticated engine reset/outcome receipts and a frozen evaluator not accessible to the AI being assessed. Never use a transient in-memory ledger as persistent evaluation provenance.

## Research-to-build plan

### 1. Actual real-time gaming competence

[Gym-Anything-RT, October 27, 2026](https://arxiv.org/abs/2610.37567) evaluates 100 minigames under moving versus paused-world conditions and finds substantial gaps between these settings. For Star this means model throughput alone cannot establish gameplay competence. Separate fast visual/event detection and reactive policy from background tactical planning and memory consolidation. Measure image capture, transport, preprocess, inference, input acknowledgement and world-state changes using one monotonic host clock.

Build an opt-in private Windows experiment on NEW paired scenario seeds. Compare a compact reactive baseline to a predictive candidate on obstacle avoidance, navigation, target tracking and uncertain mechanics. Freeze action deadlines, model builds and acceptance metrics. Count all attempted cases. Use the new ledger before first frame. Do not attribute failures to latency alone when perception or strategy might also be wrong.

### 2. Game creation and general knowledge

[Roblox OpenGameEval, October 2026](https://github.com/Roblox/open-game-eval) tests agents inside stateful Roblox Studio sessions with executable scene and simulated-play checks. Before editing a scene, Star should inspect relevant instances and scripts, create bounded diffs, run luau-analyze, Selene, StyLua, pure-Luau tests and Studio play tests, then inspect the rendered gameplay and repair observed failures. Store verified fixes as retrievable lessons; stale or unverified web claims should never become ground truth.

Longer-term, give Star an evidence-first retrieval layer with citation provenance, version timestamps, uncertainty, contradiction checks and contextual caching. A learning curriculum should train only on signed practice data, use spaced reviews and verify generalization on fresh single-use tests. Avoid claiming weights have improved without independent evidence.

### 3. Faster local inference with low memory contention

[llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures prompt/decode throughput, end-to-end latency and speculative acceptance, including draft-model, n-gram, MTP and EAGLE-style variants. On an 8GB class GPU, benchmark REAL available VRAM with game and OBS running rather than assuming a model fits just because its GGUF file is small. Compare baseline vs speculative on identical prompts, context lengths, quantization, concurrency and GPU pressure. Prioritize p95/p99 end-to-end action delay, game frame time and stable OBS video over synthetic standalone tokens/second.

Evaluate prompt prefix/KV reuse, bounded context retrieval, CPU-resident voice models, adaptive model routing and admission queues. Stop or defer background analysis when gameplay input deadlines or OBS frame budgets are at risk. GPU/CPU resource allocations must be measured and reversible; no fixed promised speedup from any inference technique.

### 4. Natural, AI-transparent VTuber behavior

[Proact-VL (ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) treats when to talk and how much to say as essential real-time abilities. Star needs speech-salience arbitration: event-to-reaction latency, non-repetitive contextual jokes, meaningful silence during difficult gameplay, explicit listener turn detection, proper interruption/cancellation, synchronised eye/face/lip gestures and honest memory about what was actually seen. Test with opt-in private nonbroadcast OBS recordings and real on-device voice capture before any public streams.

The goal is a distinctive, entertaining AI streamer with consistent character and independently verified experiences. A human-like presentation does not require pretending to be a human or fabricating subjective feelings.

## Acceptance and next measured milestone

The code is intentionally OFF until an authorized host creates a private reservation. Tests must demonstrate cross-connection blocking, duplicate and partial-cohort rejection, invalid-run consumption, key/path validation and absence of raw holdout identifiers in the DB. This is not a claim that STAR currently plays games better, becomes more intelligent, streams naturally, or decodes faster.

Next objective: run an owner-controlled nonbroadcast game/OBS/voice/avatar rehearsal on a dedicated Windows machine and publish an owner-only scorecard comparing preregistered real-time success, p95 capture-to-engine latency, missed action deadlines, OBS dropped frames, FPS frame-time tails, GPU memory and viewer-rated voice naturalness. Follow it with fresh training cases and a new one-time held-out confirmation cohort.
