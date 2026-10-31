# STAR — OBS-native frame-loss accounting and a measurable path to a better gaming VTuber
**Research/engineering note — 2026-10-31.** Draft development only. Star Core Forge remains the primary local experiment ledger; GitHub is an optional review/export surface.

## Verified code finding: a percent-of-frames bug

STAR's `ObsStatsWindow` initially computed an OBS frame-loss percentage as `100 * skipped_delta / (skipped_delta + total_delta)`. This is **not** the convention OBS uses. Its own status-bar implementation uses `skipped / total * 100`, with the total counter already acting as the denominator. The public OBS WebSocket v5 `GetStats` fields are `renderSkippedFrames`, `renderTotalFrames`, `outputSkippedFrames`, and `outputTotalFrames`. The first two represent rendering pressure; the second pair are output-thread/encoding pressure, *not* uplink packet loss.

Primary evidence:
- OBS Studio source (status bar, `UpdateStatusBar()`): https://github.com/obsproject/obs-studio/blob/master/frontend/widgets/OBSBasicStatusBar.cpp (search for `double percentage = double(skipped) / double(total) * 100.0;`)
- OBS WebSocket v5 `GetStats` field contract: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md#getstats
- OBS's GPU-lag troubleshooting: https://obsproject.com/forum/resources/status-indicators-and-what-they-mean.957/

### Impact and correction

For a sampled interval of 50 rendered frames with 10 skipped, the old code returned **16.67%**; OBS's native ratio is **20%**. If 100 of 100 frames were skipped, the old code returned **50%**, when the correct reading is **100%**. The error would understate extreme frame loss and could lead the load-admission gate to permit an unnecessary workload.

The implementation now divides each skipped-frame delta directly by its corresponding total-frame delta. It rejects zero-total intervals as missing evidence, and rebases after impossible intervals where skipped deltas exceed total deltas. The bridge also discards an earlier OBS baseline after a *trusted but malformed* counter report, requiring two fresh valid samples before it can recommend resource admission again.

The revised deterministic regression suite checks real percentages, full-loss intervals, impossible counter epochs, and absence of recovery via a pre-error baseline. This change improves the **correctness of streaming-load advice**; it is *not yet a measured stream-FPS or inference-speed improvement*.

## Why this is particularly valuable for STAR's 8 GB gaming GPU

During an authorized gaming stream, one machine may concurrently run (1) the game, (2) OBS, (3) avatar/physics rendering, (4) speech synthesis, (5) image perception, and (6) local LLM prefill/decode. For this hardware target, what matters is end-to-end game action delay and smooth rendered/sent frames, not raw tokens per second alone.

Recommended priorities:
1. **Realtime lane:** game input acknowledgment and scene capture deadlines, turn-taking, speech playback, and essential avatar animation. Bound queue size; discard superseded observations.
2. **Interactive lane:** concise grounded chat replies, on-demand retrieval, scheduled focused vision samples. Reduce work on semantically unchanged frames rather than running full perception every render frame.
3. **Background lane:** stronger reasoning, source ingestion, offline game practice, Star Core Forge experiments, Blender renders, dataset generation. Pause while resource advice reports overloaded, stale OBS evidence, or missing telemetry.
4. **Hardware contract:** compare wall-clock p50/p95 observation-to-action, spoken turn-to-first-audio, GPU VRAM headroom, delivered FPS, OBS rendering/encoding frame losses, and Win11 scheduler responsiveness on the actual Star PC. Do not accept a faster token rate that causes delayed player actions, audio stutter, or dropped frames.

The read-only policy is not an executor: only the owner-authorized Windows host may collect OBS status and device data and make actual scheduling decisions. Reject missing or forged attestation, stale/reordered clocks, and stream lifecycle changes. Heavy work is offline by default.

## An autonomous game-playing learner: fast operator, slow teacher, independent referee

RealtimeBench/TORSI (October 14, 2026) directly addresses continuous environments in which the game does not pause for inference. Its research reports that a faster student guided by offline teacher-generated reusable skills can outperform longer inline deliberation under a live clock. Paper: https://arxiv.org/abs/2610.20665 . These research numbers are **not evidence that STAR already wins games**.

STAR-specific design, using the existing `game_action_gate`, `game_action_freshness`, `game_skill_gate`, signed/verified gameplay evidence, and Star Core Forge:

- **Fast operator:** obtain bounded game state + trustworthy capture epoch; select a game-allowed action from a trained/retrieved skill; reject actions missing a valid permit, too old, or superseded.
- **Slow teacher:** at a pause or in a simulated episode, inspect action/outcome timelines, identify specific failure hypotheses, propose a compact skill revision, and generate fresh tests *before* observing holdout results.
- **Independent referee:** evaluate whole-game progress, failures by map and mechanic, worst-case p95 latency, and transfer to unseen maps/seed values. Reject improvements that regress a scenario even if averages rise.
- **Curriculum engine:** start with controls and goals, then navigation, timing, planning, cooperation, and new game-specific mechanics. Preserve skill identity, evidence source, version, and explicit expiration.
- **Anti-cheating boundary:** practice only in approved games/sandboxes or via supported game automation APIs; no anti-cheat evasion, exploit tools, or covert participation in multiplayer.

Latency-adaptive routing: when a game frame has an immediate action deadline, select the strongest *fast enough* policy. If the deadline has passed, observe/skip rather than emit a late action. Use a slower model to learn from the miss later.

## Humanlike but truthful VTuber behavior: a synchronized, cancellable performer

The target is engaging natural behavior rather than pretending to have biological memories or concealing that STAR is an AI.

- **Turn director:** distinguish viewer chat events, trusted owner speech, game-critical state, and planned monologue. Do not read every message; respond selectively. During intense play, a short reaction or silence is more natural than a lengthy answer. Current owner barge-in and interruption epochs should control *actual audio playback*, not just text generation.
- **Audio-first avatar:** bind a speech utterance ID to the played audio stream, viseme timeline, expression cues, and interrupt epoch. Stop all four together on interruption. This prevents mouth motion, gestures, or subtitles from continuing after the audible response ends.
- **Gesture grounded in cause:** win/loss, surprise, concentration, difficulty, and confidence may drive eye gaze, blinking, head turns, hair physics, and subtle body reactions. Keep microexpressions sparse; a constant random blink/gesture stream is less convincing than contextual animation.
- **Performance-first renderer:** minimize physics and animation allocations on the realtime thread; measure animation p95 CPU time and browser/OBS cost. Honor reduced-motion settings and leave intensive rendering to offline sessions.
- **Episodic truth:** recollections originate in host-observed game events with consent and a source label; do not invent friendships, real-world experiences, or viewer identities. Persona and fictional backstory must be explicitly recognizable as such.

Relevant existing implementation references to evaluate without blindly replacing STAR's mascot renderer:
- TalkingHead: real-time GLB avatar, stream-aware audio, viseme, gesture and interruption APIs, with dynamic bones: https://github.com/met4citizen/TalkingHead
- HeadAudio: audio-worklet-driven visemes from actually played sound; its authors explicitly warn that it is less accurate than text-based alignment under some conditions: https://github.com/met4citizen/HeadAudio
- Any alternative requires a license/dependency review, asset review, end-to-end lip-sync measurement, and a measured GPU/CPU budget before adoption.

## General intelligence, knowledge and polished game creation

Adding more web pages to a vector database is not the same as becoming more intelligent. Build a layered retrieval system: versioned manuals and verified API docs -> high-quality worked examples -> learned skills backed by independent replay -> experimental observations quarantined from facts -> owner-permitted episodic experiences. Cite retrieval provenance, store uncertainty and validity windows, and reject unreviewed pages as authority for executable actions.

For game creation, the acceptance gate must include (a) inspect the actual existing Studio object hierarchy, (b) generate independently structured scenes or code, (c) run executable tests, (d) inspect camera screenshots for missing/intersecting/incorrectly placed pieces, (e) playtest mechanics and multiplayer transitions, and (f) repair on failures. Do not mark a game polished solely because the Luau code parses.

Reference implementation/evaluation: Roblox OpenGameEval https://github.com/Roblox/open-game-eval and Roblox's benchmark explanation https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio .

## Inference speed: prioritize *correct* caching and measurable wins

llama.cpp's RAM/slot cache mechanisms can save expensive prefill, but the exact version and model architecture matter. A current upstream bug report opened **October 22, 2026** describes cached-prompt restore timing under unified KV cache and multiple slots, leading to cold-prefill despite apparent restore success: https://github.com/ggml-org/llama.cpp/issues/30961 . Another report opened **August 15, 2026** describes unrelated-context cache contamination in some multi-slot configurations: https://github.com/ggml-org/llama.cpp/issues/27148 . These are **upstream reports**, not proof that STAR is affected.

Proposed controlled matrix for a pinned local llama.cpp build: single vs multi-slot; cache enabled vs disabled; identical/mixed prefixes; long/short contexts; candidate draft model on/off; concurrent assistant/game/knowledge requests. Record `prompt_n`, `cache_n`, token/s, first-audio p95, end-to-end latency, canary isolation, response correctness, and VRAM peak. Reject any speed trick that fails context isolation or unseen-task accuracy checks. Optimize CPU/RAM behavior first to preserve performance across machines without a GPU.

## Proposed measurable Windows acceptance (not executed here)

1. **OBS math gate:** deterministic synthetic regression verifies native `skipped_delta/total_delta` and no false healthy admission after malformed or impossible counter epochs.
2. **Stream safety gate:** authenticated host provides fresh stream-active status and two successive OBS counter samples after each restart or reconnect. No background work allowed during missing/contradictory evidence.
3. **Gaming gate:** real approved test level; compare goal completion, action deadlines, unknown-map holdouts, and p95 capture-to-claim/action timing against a frozen baseline.
4. **Persona gate:** record an opt-in local rehearsal and grade barge-in correctness, end-of-audio lip-sync alignment, game-state reactions, normal silence, and avatar frame-time jitter; obtain human judgments for naturalness without suggesting the AI is human.
5. **Core Forge gate:** fixed hardware/budget/model/seed where possible; demonstrate reproducible gains across multiple runs and unseen tasks, with no scenario regressions. Keep rollback ready.
6. **Publication gate:** GitHub PR remains draft until checks and hardware tests justify promotion. The repository named `Star-AI-Private` currently reports **PUBLIC** visibility: never commit OBS credentials, raw viewer recordings, personal data, or protected prompt contents.

**Status:** Code changes and deterministic tests are published to the open draft PR for review; GitHub CI and independent Windows hardware/streaming evidence must be verified separately. No actual game, speech, model replacement or OBS broadcast was conducted as part of this note.
