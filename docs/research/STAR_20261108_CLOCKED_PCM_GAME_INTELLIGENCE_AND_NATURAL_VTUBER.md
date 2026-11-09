# STAR 2026-11-08: Clocked PCM submissions, measurable gaming intelligence, and natural streaming

**Status:** Research plus opt-in, offline-tested PCM safeguard. Not production deployment, autonomous game mastery, measured neural inference acceleration, or evidence of human emotions.

## Finding and code change

The existing `StreamPreplayPCMBridge` has two important turn limits: an absolute PCM byte allowance and a wall-clock watchdog. However, until this update the wall-clock bound required a **separate cooperative host** to call `watchdog()`. If a TTS worker continuously submitted *short* PCM chunks while its separate watchdog was stalled, it could keep filling the audio queue until the byte budget was consumed, even after the time budget expired. The model's turn could therefore become a long, delayed, unnatural monologue in gameplay.

Added opt-in `require_submit_clock=True` in `star/stream_preplay_pcm_bridge.py`. The trusted owner-host now supplies its **own current monotonic seconds** to *every* PCM `submit(..., now_s=...)`; each chunk must pass the existing wall-clock watchdog before it reaches the native sink. Expired, reversed, nonfinite, missing, or mistyped clocks cause STOP+FLUSH request and quarantine, not a bypass. Physical quiet must be acknowledged separately before rearming; a failed native stop requires manual recovery. Default remains OFF to avoid changing existing speech integrations silently.

This is a **defense in depth** admission check, not a replacement for independent audio interruption detection, native voice activity detection, OS speaker ownership, timely `watchdog()` calls when there are no new PCM chunks, or a native callback-time watchdog. A model must never mint host timestamps.

Offline regression probes include deadline exactly at the edge, a sequence of legal chunks, missing clock, reversed clock, NaN, native stop failure, legacy compatibility, and rejection after STOP without counting any audible completion.

## Why this matters for natural VTubing

A natural conversational agent needs coherent turn timing more than nonstop talking. **Proact-VL** (ICML 2026) explicitly evaluates whether gaming companions speak appropriately and with real-time responsiveness, not simply how many words they produce: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ .

**VoiceChat-TTS**, submitted August 13, 2026, explores continuous speech, explicit interruption control and silence generation: https://arxiv.org/abs/2608.13831 . It is **not** an installed Star component and its published latency does not transfer to an RTX 4060 automatically. An interrupted model stream can still leave already queued native PCM; the host must stop actual output and attest quiet, rather than accepting a model-level cancellation as proof.

### Human-like streaming design, in priority order

1. **Event-grounded reactions:** live host events scoped to the correct game and frame, with source freshness and independently checked outcomes; never claim a win because the model merely predicts one. Maintain silence for weak evidence and during viewer/owner barge-ins.
2. **Conversation pacing:** one in-flight speech preparation, final preplay review, an audio epoch for each utterance, a per-chunk clocked playout deadline, and an immediate owner/guest interruption path. Distinguish thought/analysis from an externally audible utterance. Speak only when the current scene or a direct question makes it useful.
3. **Expressive avatar:** stream low-latency visemes from actual PCM, gaze toward actual in-game focal points, blend authored motions, respect reduced-motion preferences, and compare recorded output against audio on one clock. Don't infer consciousness from expressiveness.
4. **Social memory:** persist only permissioned, verified interaction summaries with correct source, expiry and privacy classification. Store *what Star witnessed*, not invented anecdotes or private viewer identities. Distinguish uncertain hypotheses from confirmed facts.
5. **Editorial agency:** give Star opt-in choice among supported hobbies, games, commentary styles and creator projects. Routine tasks may self-schedule; publishing/broadcasting, spending, external contacts and destructive operations remain separately authorized.

## Architecture for smarter gaming (no shortcuts on actual skill)

The **Gym-Anything-RT** paper (October 27, 2026) uses 100 minigames with live and paused modes; live action under changing environments is a fundamentally distinct challenge: https://arxiv.org/abs/2610.37567 . Integrate or benchmark *against*, do not assume an LLM that excels offline can respond within game frame deadlines.

Three-tier agent plan:
- **Reflex lane:** bounded-latency perception and allowed actions; snapshot frame, identity, focus and deadline. Missed deadlines imply no action. Keep LLM planning, disk I/O and commentary off the hot input path.
- **Tactics lane:** maintain a compact evolving scene state, object persistence, short-horizon strategy and uncertainty. Replan when the scene changes; never consume stale action permits.
- **Learning lane:** offline safe practice on preregistered scenarios, independently verified wins/losses, reflection on failures, and versioned reusable game skills. Hide validation seeds from both the practice agent and any online speech system. Prefer AB/BA matched comparisons; report candidate performance on **previously unseen** games and seeds.

Suggested **first real experiment**: two games (one fast reaction, one navigation) on the same exact machine, same game version and seeds. 20+ unseen matched cases split across at least two scenarios, precommit the metrics; separately collect pass@1, win rate, action-deadline misses, 50th/95th/99th capture-to-input delay, focus/permission violations (target zero), training/test leakage (target zero), FPS and recovery after failures. Include pauses versus full-speed trials to isolate real-time capability. A high pass rate in a paused test does not demonstrate real-time skill.

## Making games and verifying what was built

**OpenGameEval**, released October 1, 2026, reports 84 human-curated Roblox Studio tasks, executable state/playtest checks, and evidence that inspection before edits correlates with better results: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval .

Star should enumerate objects and scripts before proposing edits, perform a constrained change in a disposable copy, run Luau linters/unit checks plus actual Studio playthrough, compare visual and gameplay acceptance snapshots, and repeat until checks pass. No "I made a great game" claim without verified artifacts and independent tests.

Roblox's **November 4, 2026** Studio MCP/Open Cloud update expands permission-controlled work on game resources, imports, settings and asset workflows: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 . Roblox documents that data store access can touch live player data, so use a **separate test universe** and narrow, non-destructive permissions: https://create.roblox.com/docs/studio/mcp-open-cloud . No unrestricted account access and no accidental production publishing.

## Higher intelligence and faster inference — experiments, not magical settings

Star's 8GB RTX 4060 budget calls for careful admission control; game renderer + OBS hardware encoder + local inference + speech/avatar share scarce resources. The true optimization target is **observed time to correct output at acceptable gameplay FPS**, not raw token throughput alone.

Rank prospective experiments using matched input batches:
- Model routing: tiny low-latency reflex classifier or specialized policy versus full general-reasoning model for difficult reasoning, with confidence rejection and task-specific quality checks.
- Smaller quantized local models with measured exact peak VRAM under **actual Windows game + OBS** load; account for context KV cache and GPU memory fragmentation. Avoid declaring "entire model fits in VRAM" without measurements.
- Prompt prefix/KV reuse, cache-stable context windows, speculative decoding where supported and verified; benchmark full prompt processing, first-token, decode and final correctness. Inference acceleration might consume additional memory or produce a net regression when the GPU is contended.
- CPU-oriented interruptible TTS if GPU time is more valuable for live play; compare character naturalness and owner barge-in stop latency against baseline. Don't transfer performance numbers from other CPUs/GPUs.
- Offline/night practice on separate worker devices; no live-model weight updates without a held-out test battery, reversible versions and owner-visible change receipts.

Measure at minimum: generation tokens/sec, time-to-first-token p50/p95, valid answers/sec, total VRAM peak, GPU frametime p95/p99, OBS rendering/encoding/network losses, end-to-end first **audible** speech p50/p95, interruption-to-native-silence p95, avatar A/V offset. Run separate load cases (idle; game only; game+OBS; game+OBS+Star; and gaming+viewer barge-ins). A speed win that breaks video/game/voice quality is **not** an accepted improvement.

## Native host integration and acceptance contract

Recommended integration order:
1. Keep **OFF** in production and all public streams. Run only on the explicitly authorized local test device.
2. Bind one trusted `StreamPreplayGate`, `LocalEpochPCMSink`, and `StreamPreplayPCMBridge(require_submit_clock=True)` to one native output owner.
3. Use native monotonic clock for admission, every `submit(now_s=...)`, and watchdog polls; do not proxy clock from the model/remote server or mix clock domains.
4. Only send PCM for the exact current `SpeechIntent` and epoch. Once a chunk submission fails, do not retry under the old epoch.
5. On timeout/invalid clock, request native **STOP+FLUSH**, independently confirm the audio queue and OS output have drained, then acknowledge quiet. Never infer quiet from a stopped generator.
6. Induce STOP failure, clock reversal, worker stall, OBS output transition, owner interruption, and cross-epoch replay in a **nonbroadcast** Windows rehearsal. Inspect both captured PCM and actual speaker loopback.
7. Run matched A/B with old bridge and clocked bridge: timeout-overshoot PCM frames (target zero when strict), stop request latency, speech completion coverage, first-audible latency, GPU/CPU cost of clock checks, game p95 frametime and OBS losses. Do not enable by default unless no regressions.

**Boundaries:** Code cannot make Star human, prove subjective feelings, verify host telemetry cryptographically without independently held secrets, or guarantee zero OS audio leakage if the native player ignores STOP. This update publishes source, tests, and a deployment specification; it does not control the native output or a game automatically.
