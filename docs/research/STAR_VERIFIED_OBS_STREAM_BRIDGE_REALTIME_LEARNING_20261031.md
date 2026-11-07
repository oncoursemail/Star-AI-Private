# STAR — verified stream-health bridge, gaming intelligence and expressive VTuber system

**Engineering review:** 2026-10-31. **Scope:** local-first, Windows gaming PC (including an 8 GiB GPU), Python host adapters, future offline Star Core Forge. **Implementation status:** opt-in, read-only OBS/host evidence coordinator and synthetic regression tests. This is not a live broadcast, model upgrade, OBS installation, training run or demonstrated inference speedup.

## A. Actual architecture gap closed in this change

Previously STAR had two separately tested components:

- `star/obs_stats_window.py`: verified, ordered **OBS WebSocket v5 GetStats** render/output skipped/total frame *counter deltas* (not a livestream controller).
- `star/stream_admission.py`: hysteretic recommendations for allocating GPU and CPU when game rendering, speech and OBS compete.

A host could in principle feed **zero** OBS lag into admission when no OBS window existed. A stream that stopped producing OBS frames, disconnected, or reset counters might then appear healthy to a naive integration. Reusing one short healthy OBS interval for multiple resource samples could also artificially satisfy overload recovery.

`star/stream_health_bridge.py` explicitly joins these two streams and refuses this shortcut:

1. Authorized host enables the bridge. The bridge itself has **no device, network, game-input, OBS or process-control privileges**.
2. Authenticated local OBS polling produces **two ordered GetStats snapshots** (usually 250–1000 ms apart), proving nonzero frame movement within that interval.
3. The authenticated host reports `StreamTelemetry` with a monotonic host-clock sample. **Live** samples require a recent, distinct, complete OBS interval. Offline samples need not open OBS.
4. A new OBS baseline, incomplete/idle interval, reset/reconnect, malformed trusted sample, or live/offline transition **invalidates the old readiness**. At most one live host sample can consume each OBS interval.
5. Noncritical resource advice remains denied until paired fresh evidence exists; overload hysteresis still requires multiple independent healthy observations. Critical speech/gameplay retains priority advice, never execution authorization.
6. `disable()` resets session evidence. Metrics are anonymous bounded counters, not frames, chat, microphone audio, player names or system paths.

**Boundary:** A `host_verified` boolean is an API contract for an *already authenticated* local host; this module does not cryptographically attest OBS or establish that streaming is active. The Windows host must check process identity, OBS websocket authentication, output-active/record-active status, live camera consent and the correct session; the model and viewers must never be allowed to set the host verification flags.

The new `tests/test_stream_health_bridge.py` exercises missing OBS windows, incomplete output, replayed healthy windows, recovery after real counter progression, unverified observations, OBS reset, live transitions, old evidence, strict clocks, session reset, and non-authorizing output. All values are synthetic. There are no Windows performance results in this change.

## B. Concrete host integration specification (next engineering milestone)

**OBS collector (local, read-only):** connect to `127.0.0.1:4455` with authentication, explicitly request `GetStats`, pass only `responseData` to the bridge, and check `GetStreamStatus` / `GetRecordStatus` separately. Do not expose the OBS websocket on a public interface or place its password in logs or model context. On reconnect, output switch, stream start/stop, process replacement, or sleep/wake, call `obs_reset()`. Avoid claiming zero lag when no valid counter window exists.

**Trusted resource collector:** measure free VRAM and game FPS, voice backlog and whether the target game is actually active. Use the *same monotonic host clock* for both streams. Pass only finite bounded values; do not accept viewer/model-provided metrics as host observations.

**Admission enforcer:** initially shadow-log only anonymous pass/deny reasons. Once Windows load trials show improved performance, a separate allowlisted scheduler may *choose not to start* expensive training/rendering/research when denied. A recommendation must never bypass the existing game-input allowlist, budget gates, emergency stop, or external-action approval.

**Measured acceptance trial:** perform paired 10-minute local recordings, before/after enabling the enforcer, with the same game scene, model, camera, TTS and OBS configuration. Report frame-time p50/p95/p99, OBS rendered/skipped/output counters, host-clock capture-to-dispatch p95, actual audio playback-start p95, dropped frames from OBS output-status network metrics, RAM/VRAM/CPU, successful game objectives, and cancellation recovery. Stress with 1–3-second GPU loads, 2-second OBS disconnect, unresponsive TTS, alt-tab, counter reset and scene change. Do not conflate encoder skips with network drops. Explicitly tag dry-run versus live and publish reproducible anonymized telemetry.

Relevant authoritative references: [OBS websocket GetStats implementation](https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp), [OBS encoding-performance troubleshooting](https://obsproject.com/kb/encoding-performance-troubleshooting/), [OBS websocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

## C. Two speeds for a stronger gaming agent

A strong but slow model is not necessarily the best **live** gamer. The October 14, 2026 [RealtimeBench / TORSI paper](https://arxiv.org/abs/2610.20665) evaluates 180 tasks across six continuously running game types. Its teacher/student strategy reports moving the tested student's average from 13.51 to 24.19 on the paper's 0–100 task-progress scale after two iterations. This is **the research authors' result**, not STAR's.

Proposed STAR implementation:

- **Fast student (on the clock):** compress the game state, choose one bounded action from an approved map, attach observation capture time and predicted outcome, and meet an explicit latency budget. Focus on game objectives rather than unbounded narration.
- **Slow teacher (off the clock):** replay consented session traces, inspect why a maneuver failed, propose a *single* strategy or tool change, and avoid reading sealed evaluation outcomes.
- **Independent verifier:** run the current and candidate on identical practice seeds plus unseen holdouts; require per-game success, progress and p95 latency not to regress. Reject upgrades with weak map coverage, even if an aggregate score improves.
- **Durable skill store:** persist only reviewed solutions with input assumptions, game version, test signature and rollback path in Star Core Forge. Separate actual learned behavior from instructions added to prompts.
- **Live transfer:** test unfamiliar levels, game speed changes and unseen UI layouts with the game running continuously, recording real action dispatch timing and objective completion.

Do not mistake a synthetic policy test, an offline teacher benchmark, or a leaderboard claim for STAR having mastered a live game.

## D. More capable game creation, not just Luau autocomplete

Roblox's October 1, 2026 [OpenGameEval paper](https://arxiv.org/abs/2610.02563) tests 13 models on **84 core tasks**, including exploration, editing and actual simulated playback. The paper reports strong relationships between inspecting affected scene objects before editing and task success. STAR should replicate this process with local skills, not just produce code files.

Proposed autonomous game-build qualification:

- Inspect world tree, asset dimensions, constraints, materials, anchoring, joints, navmesh and available scripts before writing changes.
- Build a minimal functioning vertical slice; use Luau analyzer, StyLua, Studio playtests and automated physics/replication checks.
- Use [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) and [multi-client Studio simulation](https://create.roblox.com/docs/studio/testing-modes) for join/leave, authority, ownership, UI/input replication, reset and failure cases.
- Compare screenshots/videos from known camera poses for missing walls, disconnected torsos, clipping, wrong grips, lighting/texture seams, excessive VFX and readability. Have a separate visual judge and a human taste check for art direction.
- Maintain sealed benchmark tasks and reject supposedly improved game-building strategies that fail unseen projects.

The Windows Studio host still needs to run these tests. External game assets, textures, sound and examples must carry verified provenance/license metadata.

## E. Humanlike VTuber performance: behavior, not a human impersonation

The highest-quality Star is a consistent, expressive **AI entertainer** who naturally focuses on gameplay, makes social decisions, reacts to events, and can say what she remembers doing—without inventing a human biography or secretly pretending to be a person.

1. **Attention planner:** combine gameplay danger, viewer questions, speech backlog, social energy, and stream mode. During intense movement, favor short phrases or silence. Long explanations belong after a checkpoint or safe lull.
2. **Four synchronised clocks:** vision frame capture, action dispatch, actual audible TTS playback, and avatar rig expression. A queued line is not a spoken line; an attempted victory is not a verified victory. A late facial expression must be dropped rather than played after the scene changes.
3. **Conversations:** owner barge-in needs authenticated speaker recognition and actual playback cancellation. Other voices and chat cannot impersonate the owner. Distinguish polite listener acknowledgements from an ended turn. [LiveKit v1-mini turn detection](https://docs.livekit.io/agents/logic/turns/turn-detector/) is locally CPU-executable and free to use; the full model and adaptive interruption are not equivalent local features. Benchmark local turn detection against existing STAR code before replacing.
4. **Speech and expressive animation:** [Kyutai Pocket TTS 4.0.1, released October 21, 2026](https://github.com/kyutai-labs/pocket-tts/releases) includes small CPU-oriented English models; compare them blindly against STAR's current voice for warmth, consonants, laughter, chunk onset, long utterances and interruption latency. Tie lip shape and wavy twin-tail/eye motion to **heard** audio and rig physics, not planned text. Reduced-motion mode stays available.
5. **Genuine memories and personality:** a consent-controlled session journal stores verified game events and accomplishments, with separate fiction/lore, viewer-submitted content and outside knowledge. Bring up a previous checkpoint naturally only if it is relevant, current and approved for broadcast; do not invent earlier sessions.
6. **General knowledge:** keep a vetted local knowledge bank, tool-specific verified skills, reversible experimental hypotheses and persona lore distinct. Fetch sources with freshness and citation fields, compare them on unseen questions, abstain if evidence is weak, and never mix secret notes into broadcast context.

Suggested milestone: a **recorded solo game rehearsal** where Star completes a simple unfamiliar game with objective scores, talks and laughs with coherent timing, remembers one verified event, yields to a real owner interruption, and maintains OBS frame quality. Review the recording blind against a frozen baseline version, including silence, eye movement, speech naturalness, timing and actual success.

## F. Performance hypotheses, with tests

- On 8 GiB GPUs, cap game FPS when OBS is starved; OBS explicitly recommends leaving rendering headroom rather than running games without an FPS cap.
- Benchmark llama.cpp prompt reuse, continuous batching and speculative decoding *with VRAM occupancy and game FPS recorded*. Larger KV caches and speculative drafts may be slower under streaming load, even if standalone inference looks faster.
- Keep TTS/VAD/turn detection CPU-based when tests show it preserves game FPS, but ensure they do not starve the host input loop or encoder threads. Enforce bounded queues and cancellable tasks.
- Move narrow, measured hot paths to Rust only if profiling reveals Python scheduling/copy overhead. Rust alone does not increase model knowledge or game-playing intelligence.
- Promote only changes that pass safety/privacy checks, unseen game challenges, reference UI visual checks, and end-to-end timing tests. GitHub is an **export and review destination**; Star Core Forge should remain the primary offline-first experimental ledger.

## G. Current limits and security

New code is a **join/advice layer** plus regression fixtures. It is not currently wired into Windows OBS, game input, GPU monitoring or the production scheduler; no claimed speedup, new trained model, live game victory or broadcast follows from this commit. The repository is named `Star-AI-Private` but currently reports **public** visibility; never commit OBS credentials, private gameplay recordings, viewer identities or host secrets here.

Next work order: (1) integrate authenticated, loopback-only OBS GetStats with a dry-run bridge; (2) record reproducible Windows baseline/scheduler trials; (3) implement measured job suspension and rollback if successful; (4) add live-game teacher/student and recording-level VTuber evaluations; (5) integrate validated gains into local Star Core Forge before export.
