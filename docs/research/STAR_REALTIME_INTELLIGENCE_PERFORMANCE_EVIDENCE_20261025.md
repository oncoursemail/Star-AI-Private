# STAR: realtime intelligence, gameplay and VTuber performance engineering

Date: 2026-10-25. Status: research plus offline-tested safety and comparison tooling.
No hardware speedup, neural intelligence increase, game performance or human-quality voice has yet been demonstrated by this patch.

## Engineering finding

STAR has experimental advisory layers for game actions, gameplay skill evidence, stream turn-taking, audio motion and inference QoS. Their value depends on real observations, not more unconnected prompts. The immediate bottleneck risk is concurrent model workers consuming 8 GB GPU headroom while a game runs. The immediate intelligence gap is independently verified outcomes on previously unseen games.

This patch fixes a real QoS correctness issue: disabling its advisor previously erased the reservation ledger even when CPU/GPU workers could still be running. A later re-enable could mistakenly admit overlapping work in that same resource slot. Reservations now survive disable until an explicit host acknowledgement of worker stop; re-enable refuses outstanding leases. Old completions do not become successful latency evidence.

This patch also adds a strictly offline, paired A/B analysis tool for host-observed first audible speech, real game frame times and peak GPU memory. The tool outputs advisory results only. It never changes routes, starts models, controls a game or broadcasts.

## Evidence-backed research directions

### Faster inference on the owner's 8 GB GPUs

The llama.cpp speculative decoding documentation describes producing several draft tokens and batch-verifying them with a target model. Speed depends on draft cost, acceptance, target model, context length, model format, memory traffic and CPU/GPU contention. Measure effective tokens per wall-clock second, time to first token and full-answer accuracy; report idle versus active game results separately.

Official reference: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

Recommended A/B matrix: baseline decoding, prompt lookup, small draft models, shared-prefix KV reuse with strict ownership and content hashing, quantization, CPU/GPU layer balance, short and long contexts, and concurrent Studio rendering. Never reuse another user's private cache or a busy model slot. Require equal-or-better independently graded code, UI and game outcomes before speed claims.

### Natural voice without interrupting gameplay

Kyutai Pocket TTS added 18.2M, 6.9M and 1.9M parameter English variants in October 2026. Its reported up-to-25x realtime performance on one CPU thread is Kyutai's result, not a measured result on STAR's hardware. Compare clarity, expressions, laughter and first audible latency on actual devices; tiny models may be less natural. Keeping model and authorized voice state warm can reduce setup time.

Official reference: https://github.com/kyutai-labs/pocket-tts

Kyutai Moshi offers an open full-duplex spoken dialogue architecture. Its ~200 ms latency on a server-class L4 GPU does not establish that its 7B model will work well beside Roblox on an 8 GB gaming card. Borrow the ideas of sustained listening, interruptions, turn timing and parallel incoming/outgoing audio without asserting a local deployment.

Official reference: https://github.com/kyutai-labs/moshi

Avatar expressions must be synchronized with actually heard output rather than token generation. Keep a unique playback-epoch ID and throw away movement from an interrupted speech turn. Reset old mouth/cue frames, preserve deliberate pauses, avoid automatic victory reactions to unverified events, and gate cat/puppy ears and tail by rig limitations. VTube Studio documents supported input-to-Live2D parameter mapping; verify each model's actual bindings.

Reference: https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings

Keep Star transparently an AI VTuber even when her timing and performance feel natural. A consistent fictional character history can be charming, but should not be presented as a true human biography.

### Real Roblox gameplay and game construction

Roblox announced a built-in Studio MCP server on March 5, 2026. Its documentation details Studio state, playtesting, script inspection, instance exploration and authorized tool calls. This gives Star an engineering route to independently inspect places, run tests and capture meaningful outcomes on Brain 2.

Announcements: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
Creator documentation: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

Use separate disposable test places. Collect actual player position, velocity, collision/grounded flags, checkpoints, goal triggers and logs, not only screenshots. Host-authorized symbolic actions must obey key-up watchdog, game focus and multiplayer terms. Let an independent evaluator sign observed practice and withheld validation results, as STAR's gameplay skill bank already supports. Never reveal held-out answers to the practice planner.

Benchmark 10+ unseen levels per genre, multiple seeds, successes with confidence intervals, completion time, invalid actions and recovery from mistakes. Run baseline, retrieval-only, practice-only and combined policies. For generated scenes, measure wall continuity, missing props, z-fighting, meshes, scale consistency, collisions, clipping, visual hierarchy and UI safe areas; verify on actual Studio screenshots and playtests.

### General intelligence and infrastructure

Use a fast game reflex loop for trusted observations, approved short actions and compact skills; keep slower research, asset curation, code generation and model retraining in separate queues. Dynamically select a few permission-reviewed tools instead of injecting a massive tool catalog into every prompt. Give knowledge memories provenance, license, last-verified time, uncertainty and expiry. Verify claims against multiple independent sources when practical.

Build a paired evaluation portfolio: unseen game skill retention, code tests, factual QA with citations, layout comparisons judged by humans, context isolation, streaming interruptions, latency and resource budgets. Prevent dataset leakage, unlicensed assets, chat-originated tool instructions and secret-bearing model context.

## Offline A/B evaluation usage

Run: python -m star.stream_realtime_benchmark path/to/host-traces.jsonl --gpu-budget-mib 6656

Each local JSONL object has exactly eight fields: pair_id, variant (baseline or candidate), game_id, game_version, first_audio_ms, frame_times_ms (120 through 5000 numerical frame-presentation durations), gpu_peak_mib and audio_finished. Opaque IDs only, no audio/text/screenshots/player names. Same-clock host capture and real sound-device playback acknowledgements are prerequisites.

Capture at least 20 pre-registered matched baseline/candidate runs in exactly the same game version and scene. Counterbalance experiment order, warm both model routes, randomize assignment, record every failure and interruption rather than cherry-picking good runs. Include active gameplay, high GPU load, owner interrupts and long utterances.

The evaluator computes p95 first-audible latency, a descriptive 1-percent-low FPS proxy derived from p99 frame time, and paired deterministic bootstrap confidence intervals. Manual pilot eligibility requires 20+ complete pairs, zero speech failures or missing pairs, lower 95% bound of TTFA improvement above 30 ms, non-worse p95 TTFA, a lower FPS difference bound no worse than -3 FPS, and candidate GPU peak below the configured host budget. A regressed or inconclusive result cannot trigger automatic use.

For 8 GB GPUs, the default 6656 MiB candidate budget is a conservative starting test value, not a substitute for measured free VRAM and game headroom. Bootstrapped sampling uncertainty does not address measurement bias, changing scenes, randomization defects or causality. Inspect naturalness, articulation and factual correctness separately with blinded human ratings.

## Next engineering gates

1. Implement a trusted host telemetry collector that records actual frame presentation times and first audible PCM without saving private voice/chat.
2. Test baseline versus candidate Pocket TTS and inference paths on both RTX 3060 Ti and RTX 4060 while games are active; separate GPU/CPU routes and report p95, p99 and failures.
3. Connect Studio's official MCP playtests to owner-authorized game observation and independent validation; only then claim self-improving game-playing.
4. Wire playback acknowledgements into avatar motion so the character never lip-syncs silently when speech was cancelled.
5. Maintain opt-in approvals, source and sound/model licenses, audience disclosure, held-out evaluation, privacy and redacted diagnostics.

Security: no new network endpoints, key bindings, broadcasts, private media, secrets or model downloads were added in this change. The GitHub repository named Star-AI-Private must not be assumed private from its name.
