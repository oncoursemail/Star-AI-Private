# Star AI — OBS batch freshness, recording continuity, gameplay intelligence and VTuber latency

**Research/implementation checkpoint: 2026-11-05.** Focus: prevent *false positive* success evidence in a private Windows game + VTuber rehearsal, not add superficial complexity. Every proposal below is distinguishable from what is implemented; no public broadcast, game input, mic activation, model download, or actual model retraining occurred in this change.

## Two reproducible observational errors (implemented)

**A. Batched OBS evidence had no time window.** Our opt-in authenticated OBS websocket v5 probe combines GetStats, GetStreamStatus and GetRecordStatus through a read-only SerialRealtime RequestBatch. The pre-change adapter gave all three results the *single receive timestamp*. That collapses a potentially slow batch spanning multiple OBS states into apparently simultaneous observations. The evidence gate rejects >750-ms spans between unbatched results but cannot detect this collapse. This change records the host's monotonic time *before sending* the batch and *after the complete reply*, rejecting any reversed, malformed or >750-ms exchange before accepting its contents. This is a conservative upper bound on the span between internal reads, not proof of continuous nonbroadcast status. The default sequential-read path and absence of OBS write commands remain unchanged.

**B. Strict recording-progress certification used an existential rather than per-interval check.** In strict private mode, progress was considered verified if the output-byte counter advanced at least once anywhere in the observation window—even if the final interval stopped producing output bytes. The updated gate requires positive byte progress on **every** consecutive interval while preserving the prior monotonic-duration and never-regress checks. Because output buffering can delay file-byte accounting, strict mode may defer a genuinely working recorder; it is opt-in *conservative evidence*, not authorization or proof of media content. When a window is deferred, capture and inspect a completed private media file with the independent offline decoding and synchronization checks; do not silently turn a weak sample into a green light.

**Reproduction:** three new adversarial cases failed before code changes: slow batch accepted despite invalid evidence span, and 3-sample intermittent writer stalls accepted in both serial and batch modes. Prior tests expecting late recovery of a stalled strict window were updated to match its clarified per-interval contract. This is *synthetic* validation and not a real observed OBS problem.

**Security boundaries:** Only the trusted host supplies the clock, websocket credential and random correlators. The parser emits aggregate sanitized results and does not return OBS output paths, frame contents, speech, identity or the password. It performs only GetStats, GetStreamStatus and GetRecordStatus and must never start streams, recordings, microphones or gameplay. RequestBatch remains optional. A timed read-only sample does not prove the whole episode was never broadcast.

## Testable next experiments, in impact order

### 1. One complete Windows rehearsal with provenance

Run a host-authorized private 5-minute session of **game + avatar + voice + OBS** with broadcasting disabled. Host attests source window, input policy, recording path, OBS status, voice track and process identity. Collect timestamped gameplay frame presents, OBS render/encode lag deltas, actual audible PCM start time, mouth events, TTS/backlog, resource pressure and task outcome from the *same monotonic clock*. Fingerprint the completed file separately, decode video+selected voice audio, and compare visible avatar mouth movement against isolated voice. Calibrate camera/avatar capture, privacy redaction, and recording start/stop; do not infer OBS provenance from file extension or hash alone.

Stop/reject on active broadcast, impossible timestamps, stale graphics telemetry, missing file provenance, absent audio/video, severe encode drops or wrong game outcome. Publish **only aggregated evaluation**. Match game seed, scene, avatar and voice across baseline/control; alternate test order and randomize unseen challenge assignment.

### 2. Faster useful responses on the actual 8-GB GPU

Treat speech first-audible-chunk latency, viewer acknowledgement p95, gameplay 1%-low FPS and contextually correct decisions/second as the *primary* metrics. Tokens/second is secondary. Set two lanes: (i) latency-sensitive speech+low-cost social acknowledgement and bounded game policy, (ii) interruptible deliberation/research/training, paused under VRAM/OBS pressure. Benchmark warmed and cold cache conditions with the exact model, quantization, prompt, OS and llama-server build. Compare CPU TTS vs GPU TTS, and speculative decoding ON/OFF; a draft model can **lose** speed on an 8-GB card if memory or acceptance rate is poor. Never assert a fixed throughput without measuring it on Star's machine.

Useful upstream tooling: llama.cpp's **SPEED-Bench** benchmarks server-level latency, throughput and draft acceptance (https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench); llama-bench isolates batch/model performance (https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench). Kyutai's Pocket TTS added 18M/7M/2M English models in release v4.0.0 on **2026-10-20**, with a v4.0.1 correction on **2026-10-21** (https://github.com/kyutai-labs/pocket-tts/releases). These warrant **voice quality and CPU-load AB tests**, not automatic model replacement. Test interruptions, pronunciation, prosody, and whisper/vad reliability alongside RTF and time to first audible chunk.

### 3. Gameplay learning that transfers, not just benchmark gaming

Use a three-tier perception/action architecture: a fast bounded policy for immediate moves; a tactical subgoal tracker for prediction/correction; and an offline learner that classifies failures and proposes *reversible* lessons. Log episode IDs, signed seed/level versions, action timings and game outcome receipts; prohibit Star from selecting held-out test cases or signing her own wins. Train on varied seeds/environment perturbations; evaluate with previously unseen seeds and counterbalanced baseline-vs-candidate order. Track task success, deaths, time to goal and intervention count with confidence intervals. Avoid online multiplayer automation outside explicit game permissions or safety rules. No external game wins were demonstrated in this change.

For **game building**, Roblox's Studio built-in MCP server and playtest automation supports a plan/build/test loop (official March 5, 2026 release: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and April 15, 2026 overview: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic). Use Studio-specific nonce/pinned-identity verification, static Luau/LSP/type checks, reversible edits, real playtest receipts and visual inspection. Run isolated candidate projects rather than guessing success from generated code.

### 4. Humanlike *performance*, not false claims of personhood

An entertaining stream needs natural turn-taking, intentional silence, grounded reactions to actual gameplay, interruptions, temporal continuity, believable surprise/failure, contextually appropriate humor, and stable voice/gesture expression. Give her a consistent persona and **episodic memory anchored to verified events**, plus controlled topic interests that can evolve and be corrected. Let the host decide *whether to speak* before asking the language model *what to say*; avoid continuous narration. A social interruption should cancel an unspoken response before TTS audio starts; an audible interruption should finish a natural phrase or quickly fade, avoiding half-uttered duplicate replies.

Microsoft's Proact-VL (ICML 2026, https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) investigates proactive gaming commentary and real-time response selection. The upstream repo (https://github.com/microsoft/AnthropomorphicIntelligence/tree/main/Proact-VL) is research reference, not proof that Star already runs it. Evaluate human preference for conversational timing using blinded short clips *from actual private rehearsals*, then check repeatability, audio-mouth lag and FPS. Star may be highly expressive while being **clearly disclosed as AI**; no human-identity deception.

## Acceptance matrix (not yet measured)

| Layer | Proposed go/no-go evidence |
|---|---|
| OBS observation | Correlated authenticated read-only triplets with <=750-ms span, never active broadcast. |
| Strict recording | Active/unpaused private OBS status and byte+duration progress on every interval; media artifact separately validated. |
| Graphics | Game FPS p50/p95/p99, OBS render/encode skipped deltas, VRAM headroom, no misleading stale probes. |
| Voice/avatar | Actual audible first chunk, mouth/voice sync error, no unintended mic/source leakage, interruption completion. |
| Gameplay | Held-out success improvement with precommitted scenarios, independent outcome receipts and control policies. |
| Coding | Roblox scripts pass static checks, Studio identity pin, simulated-player checks and reversible visual acceptance. |
| Safety | No automatic public broadcast, account creation, spending, forbidden multiplayer botting or use of private chats as streaming content. |

**Limitations:** The present change fixes deterministic verification behavior. It does not run OBS, produce a real private recording, speed up neural inference, upgrade model weights, produce gameplay wins, or make consciousness claims. Those require separate operator-approved evaluations and measured outcome receipts.

## CI debt observed outside this patch

GitHub's **preceding PR #986** (head `690c3f3c`) completed its offline Python checks with **15 failures, 16,157 passes, 331 skips and 817 passing subtests**. The failed cases were in `test_resource_planner.py`, `test_portfolio_studio_bridge.py` and `test_studio_practice_runner.py`, not in these OBS files. Its separate React UI and Pyright jobs passed. Several Studio tests expected a feedback-ready post-action image but received a `usable_post_action_scene_missing`/fresh-visual-evidence reason. The source of those failures must be reproduced on their own scope and corrected without weakening the new Studio nonce/identity pin. Consequently this OBS change's targeted offline tests are **not** evidence that the repository-wide CI baseline is healthy. Prior CI status: https://github.com/oncoursemail/Star-AI-Project/pull/986/checks.
