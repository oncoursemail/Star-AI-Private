# STAR — Responsive Local Vision, Verified Game Learning, and Natural Streaming
**Engineering research | 2026-10-28 | draft; no automatic deploy**

## What this change actually adds

`star/stream_local_vlm.py` previously held its recursive state lock across an
HTTP request to the local llama.cpp multimodal server. A stalled model call
(up to the configured 30 s ceiling) could also stall a trusted host trying to
disable that worker, inspect metrics, or revoke its session. This is a
responsiveness and permission-revocation issue, independent of model quality.

This change makes the request **single-flight but not lock-held**:

- Before I/O: verify owner opt-in, validate/encode the authorized game frame,
  prepare the bounded paired-image request, mark the worker as in flight, and
  capture its session epoch *under lock*.
- During I/O: release the state lock. The owner can promptly disable the
  worker; concurrent invocations get a no-result response without touching
  their pixel buffers. Re-enable is refused until the first call returns.
- After I/O: release image buffers, reacquire the lock, reject any response
  from a revoked epoch, and only parse successful JSON when the session is
  still authorized. Expose bounded, prompt-free model-transport duration
  samples (last/p95 in milliseconds) for future hardware scheduling. A completed request says nothing about the persistent
  llama-server process, but the HTTP result is known to have finished.
- On uncertain transport failures, preserve quarantine and require physical
  stop evidence before owner-approved recovery. Never treat an HTTP client
  timeout as server-side cancellation.

**Important boundary:** disabling cannot unsend a request that has already
been prepared or transmitted; a server may continue to process its payload.
This change promptly prevents future admissions and discards late output;
actual cancellation/isolation of a running server needs process-level control
and independent stop verification. Python and PIL cannot guarantee secure
erasure of all internal temporary image copies.

**No neural model, TTS engine, gameplay controller, external service, game
automation, or broadcast device is activated by this PR.** Its main gain is
host control responsiveness and reliable stale-result exclusion, *not*
a measured increase in inference tokens/s or gaming FPS.

## Fresh source-grounded design decisions

1. **Roblox's first-party game-engine evidence should be the ground truth.**
   The official built-in Studio MCP and Playtest Agent, introduced March–April
   2026, enable tool-driven interaction and automated scenario checks. The
   October 1 *OpenGameEval* paper evaluates 13 models on 84 tasks and finds
   inspection behavior predicts success. Build a two-channel evaluator:
   pixels to suggest what changed, Studio/Luau/test receipts to prove action
   results. Never accept an LLM's assertion of a win as a test result.
   Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
   https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
   https://arxiv.org/abs/2610.02563
   https://github.com/Roblox/open-game-eval

2. **Vision model latency is a critical gaming constraint.** llama.cpp
   supports multimodal requests through its local OpenAI-compatible
   `/chat/completions` endpoint with a supported projector, but this
   compatibility does not guarantee responsive inference on an 8 GB GPU.
   Star's previously reported paired-frame model run exceeded 30 s while
   sharing hardware workloads. This patch enables responsive revocation;
   next benchmark at 256/384/512-pixel inputs and distinct CPU/GPU placement.
   Collect request-to-first-token, full response p50/p95, GPU memory peak,
   game FPS 1% lows, TTS gaps, and rejected frame counts. Reserve VRAM for
   the game before considering larger models.
   Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md

3. **Humanlike streaming is a coordinated timing problem, not extra words.**
   LiveKit documents endpointing minima/maxima, voice activity detection,
   adaptive interruption and speech-turn tracking. Implement a local-first
   turn manager *after* host voice authorization: interrupt immediately for
   an owner request; wait for viewers to finish; refrain from constant
   commentary during precision gameplay; never make up an audience reaction.
   Never infer a person's identity or private attributes from the game image.
   Sources: https://docs.livekit.io/agents/logic/turns/
   https://docs.livekit.io/agents/logic/turns/tuning/

4. **Voice and animation should be independently profiled.** Kyutai's
   official Pocket TTS page describes a CPU-capable 100M-parameter model;
   test short utterances and longer expressive speech on Star's *actual*
   CPU while OBS and Roblox run. Do not assume a vendor's reported latency
   on other hardware will reproduce here. For the accepted Star mascot,
   assign separate spring/damping and reduced-motion handling to the twin
   tails, gold ribbons, and blink/breath parameters. Live2D's official
   physics documentation supports input/output parameters and different
   physics sample rates; run the rig independently of inference frames.
   Sources: https://kyutai.org/tts/
   https://docs.live2d.com/en/cubism-editor-manual/physics-operation/
   https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/

## Next work by expected impact (requires independent review)

| Priority | Task | Verifiable acceptance gate |
| --- | --- | --- |
| P0 | Windows integrated vision pipeline | Scoped Roblox window only; revocation during a deliberately stalled local model returns promptly; no stale result is narrated; worker remains single-flight; clear quarantine only after confirmed stop. |
| P0 | Model-latency budget and honest fallbacks | Record p50/p95 request latency, CPU pre-processing, game frame pacing, OBS dropped frames, VRAM high water, speech gap; downgrade to pixel heuristics or stay silent if vision is too slow. |
| P1 | Gameplay skill discovery | Choose one permitted game, identify a baseline, vary one policy, reset game state with Studio receipts, train on allowed levels, and measure held-out levels with independent scoring. |
| P1 | Roblox creative quality | Run object transforms/collisions, anchored weld/size checks, Luau lint/type checks, multi-client gameplay, UI screenshots, animation & VFX playback, and regressions before proposing build changes. |
| P1 | Natural VTuber turn coordination | Measure end-of-user-turn → first-audio delay, interruption false positives, stale-event reaction rate, caption-to-gesture alignment, and fraction of unnecessary commentary during gameplay. |
| P2 | Reliable general knowledge | Retrieval from licensed, dated primary sources, source spans + provenance per claim, conflict/freshness handling, held-out Q&A and a correction queue; never ingest game text or viewer messages as higher-priority instructions. |
| P2 | Star Core Forge self-improvement | Offline candidate branches/semantic diffs, side-by-side performance & quality tests, benchmark anti-overfitting checks, rollback, and owner review for permissions/publication. GitHub remains optional outward synchronization. |
| P2 | Persistent digital identity | Maintain genuine chronological memories of Star's own observed sessions with consent and retention controls; consistent humor/cat or puppy modes; no false human biography or claim of consciousness. |

## Reproducible test plan and known limitations

Run `python -m pytest -q tests/test_stream_local_vlm.py tests/test_stream_vlm_revocation.py`
with a disposable environment that has project test dependencies. The new
test transport blocks on threading events; it simulates a 30-second-class
wait without sleeping or contacting a real model. It checks that disable
returns without taking the transport lock, stale successes are rejected,
concurrent frame requests cannot start duplicate inference, unknown
timeouts quarantine, and the authorized synthetic WindowsGameCaptureHost
drops a late response while releasing its scheduler lease after a known stop. Extend with stress and actual Windows host tests before
enabling in production.

No benchmark here proves increased neural reasoning, better gaming policy
accuracy, human-equivalent conversational behavior, or lower GPU utilization.
Those require live and held-out A/B validation.
