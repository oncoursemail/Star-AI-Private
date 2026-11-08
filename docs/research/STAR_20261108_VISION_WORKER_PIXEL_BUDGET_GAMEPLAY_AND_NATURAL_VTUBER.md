# STAR — cheaper game vision without sacrificing capture provenance (2026-11-08)

**Change type:** implementable, opt-in Windows vision-worker path + independent offline tests. **Not** a new model, real gameplay breakthrough, measured hardware speedup, successful stream, or self-awareness claim.

## Why this increment matters

Star's Windows game capture already pins the exact approved HWND/PID, checks window identity before and after capture, uses a real measured vision governor, fingerprints the source image for novelty, and quarantines unfinished model workers. Yet a permitted 1920×1080 RGB frame delivers **6,220,800 input bytes** to a model worker even if a 640×360 image would suffice for that specific game.

The new opt-in `worker_max_pixels` limit on `WindowsGameCaptureHost` leaves **capture, window checks, full-resolution pixel fingerprint, and novelty admission unchanged**. Only after admission does the host downscale the *synchronous trusted worker's* copy. A 1920×1080 source sent to a 230,400-pixel worker budget yields ~640×360 RGB, **691,200 bytes** — 9× fewer input bytes for the model worker. These are calculated byte counts, NOT measured inference time, latency, quality, VRAM savings or FPS improvement. Resize itself incurs CPU cost.

It is OFF by default; existing callers continue seeing native image dimensions. No model, screenshot, webcam, OBS, game action or stream is launched by this patch.

### Implemented behavior

- Reject invalid worker pixel budgets; allow only 72 through 8,294,400 pixels. Without an explicit budget, legacy full-resolution behavior is preserved.
- Keep independent full-resolution fingerprinting, focus/novelty policy and host telemetry admission. Never treat a downscaled preview as independent game-truth evidence.
- Send a properly dimensioned, temporary read-only RGB view to the installed trusted worker. Include the original source size separately so it can correctly interpret coordinate scaling; accepted categorical `VisualPacket` output must match the **worker** dimensions/timestamp, not the native input dimensions.
- Reject stale resize operations before invoking a worker. Settle a timed-out, unused vision lease as unsuccessful; a **reversed host clock** cannot attest an orderly release, so it returns a named error and preserves the lease until the trusted clock recovers and the host explicitly settles it.
- Scrub both the original bytearray and resized worker bytearray on completion/failure, close image resources, and keep worker-nontermination quarantine intact. Do not log pixel data or private window identities.
- Add 13 deterministic mocked tests: budget admission, default behavior, source/work dimensions, source full-resolution fingerprint, byte zeroization, geometry mismatch, duplicate suppression, failed resize lease release, slow resize, and unconfirmed worker stop.

**Usage sketch (authorized host only):**

```python
capture = WindowsGameCaptureHost(
    vision, hwnd=trusted_hwnd, pid=trusted_pid,
    trusted_worker=trusted_sync_worker,
    worker_max_pixels=230_400,  # optional: at most ~640x360 on 16:9
)
# The host must separately enable the vision governor and capture, authenticate
# the window, hold capture permission, and physically join its worker.
```

The budget is an upper bound, not a promise of a particular target aspect ratio or sufficient readability. Small inventory text, minimaps and health UI can be missed at reduced resolution; test the intended game task before retaining this setting. The full-res host novelty path is still protected, but the *model's understanding* can be degraded at smaller input sizes.

## Speed engineering — test before applying to Star's 8GB GPU

1. Select two exact allowed games/scenes including a low-text motion scene and a text-heavy inventory/HUD scene. Freeze a holdout set and compare native source, 960×540, 640×360 and 384×216 model inputs in a **private offline** rehearsal.
2. On the **same** graphics/OBS/model build, randomize trial order and measure capture→fingerprint→resize→vision-worker→verified output p50/p95, misses, GPU free MiB, CPU use, game 1% low FPS and OBS skipped frames. Compare both gaming only and game+OBS+TTS+avatar workloads. A smaller image can reduce model prefill cost but also slow CPU resizing or lose visual details.
3. Promote the fastest *verified-accurate* route only if independent categorical game-event recall and downstream action accuracy match baseline. A faster wrong perception must not earn a deployment.
4. Build a multi-scale repair: when the host verifies a genuine HUD target, prefer a fixed owner-configured high-res HUD ROI in the existing vision pipeline rather than enlarging every frame; do not let a model choose an arbitrary desktop/window location. Never infer game success from VLM confidence alone.
5. Pair this with existing `GameDeadlineRouter`, `RealtimeGameLoop`, `GameplaySkillBank`, `GameLearningLadder`, and independent holdout transfer tests. Avoid duplicate route controllers, new unfounded skills, or holding game keys while waiting for a slow VLM.
6. For inference, benchmark prompt caching (separate public/private session caches), CPU/GPU placement and speculative decoding **under gaming load**. A published fast token/sec result does not establish whole-loop speed on Star's machines.

**Relevant evidence:** Gym-Anything-RT, submitted **October 27, 2026**, tests 100 real-time minigames and documents serious differences between paused and active environment evaluation. This motivates the end-to-end frame-to-effect metric, not any claim that this patch improves the benchmark: https://arxiv.org/abs/2610.37567

## VTuber naturalness and practical voice design

Human-like presence comes from appropriate timing, attention, mistakes acknowledged aloud, continuity of memory, meaningful silence, believable nonverbal expressions, and physical interruption, **not** pretending Star is human.

- Use event-driven, short gameplay reactions based on verified recent game-state transitions. When nothing noteworthy happens, silence is a better outcome than generic chatter.
- Run turn-taking and speech output through Star's existing `TurnTakingGate`, `StreamPreplayPCMBridge` and independent audio watchdog. Have an authorized host verify actual audible completion and owner interruption before recording an episode as spoken; model-generated text is not proof of speech.
- Keep speculative dialogue private until final turn intent; discard canceled audio and its speech-memory claims. Voice-Light (**September 2026**) describes this pattern and the limits of a purely learned end-of-turn detector: https://arxiv.org/abs/2609.20995
- Proact-VL (**ICML 2026**) evaluates *when* an AI gaming companion should speak as well as generated response quality; adapt the research direction, not its benchmark claims: https://proceedings.mlr.press/v306/yan26c.html
- Benchmark Kyutai Pocket TTS's **October 2026** CPU-oriented 18.2M/6.9M/1.9M English models against Star's real voice pipeline, particularly first audible chunk, prosody, barge-in stop latency and gaming FPS. Do not install multiple models on a nearly-full machine: https://github.com/kyutai-labs/pocket-tts
- Implement persistent opt-in social memories with deletion, source and age; no automatic intimate relationships, human impersonation, or private viewer biographies. Star can develop a recognizable AI persona and curiosity without a false claim of subjective sentience.

## Autonomous gaming + creation + general knowledge

Use one owner-approved offline practice sandbox with curated goals and host-observed results. Star proposes a mechanic, runs one bounded symbolic action, observes actual changes and logs success/failure with the existing signed game bank. Train only on practice; seal validation/holdout; compare on unfamiliar situations before promotion.

For Roblox creation, the built-in Studio MCP server has supported playtest automation since **March 5, 2026**: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

Roblox's **November 4, 2026** announcement expands permission-selected MCP access to Open Cloud, asset import, analytics, store configuration, and game settings: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 . Star should work in an owner-selected private test place with scoped permissions, `inspect→design→build→Studio playtest→logs→repair→retest`. Asset uploads, monetization, publication and live game actions remain separately gated.

Separate **general world facts** (cited docs/web with source dates), **code skills** (executed tests and versioned API references), **game skills** (host-observed trial receipts), and **personal episodes** (verified spoken/live events). The retrieval system must mark sources stale and seek updates rather than treating previous model output as a fact. Use CPU scheduling outside game deadlines for deep research and self-generated exercises.

## Hardware blockers, safety and acceptance

During this increment, a read-only check on the connected Windows Main showed **C: free 1,720,659,968 bytes (~1.60 GiB), the only listed logical disk**. This is a critical blocker for meaningful OBS recording and new heavyweight model downloads. The earlier `RecordingDiskGuard` is the appropriate admission fence. No files were deleted, no model downloaded, and no recording/broadcast or gameplay was started.

**Acceptance before deployment:** successful independent Windows test of true Pillow HWND capture+resize and source window validation; target game's recognition quality on unseen frames; completed worker stop/zeroization; real benchmark showing lower *whole-loop* latency and unchanged downstream accuracy/FPS; and adequate disk headroom for recorded rehearsal.

**Scope limitations:** the new unit tests use synthetic images. Model speed, human-level VTuber presence, autonomous play, true self-improvement, general reasoning improvements, and OBS/audio host integration are not established by this patch. There is no approval to publish a stream or send game inputs.
