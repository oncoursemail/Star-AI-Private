# STAR — Confirmed private host submission + generalist / VTuber engineering
**Research and implementation:** 2026-11-06 | **Mode:** private, consent-gated, OFF by default

## 1. Actual gap closed in this change
The earlier `HostMonotonicGameProbe.guarded_dispatch()` could call a trusted
host callback and record submission timing even when the callback *returned
`False`* to signal failure. Only exceptions revoked the benchmark. This could
contaminate Star's real-time latency evidence: the action could be counted as
submitted although the host explicitly rejected it.

This change adds:
- Immediate, fail-closed handling for an **exact `False`** return in legacy
  callback mode. Existing `None`-returning synchronous callbacks stay compatible.
- An **opt-in strict result contract**: `require_submit_confirmation=True`
  requires a deadline and exactly `True` from the owner-approved callback.
  All other return types, including `None`, integer `1`, futures and opaque
  results, revoke the entire diagnostic window.
- Redacted status metrics for confirmation-required sessions:
  `host_submit_confirmation_required`, `host_submit_rejections`, and
  `host_submission_attested=False`. A host returning `True` is only a
  host assertion that the *request to submit input* was accepted.
- Focused offline tests for successful callback, legacy compatibility,
  strict failure, missing ACK, expired deadline, prior-good-sample
  revocation, exception path and parameter validation.

No callback is installed or invoked outside an explicit owner-approved
`guarded_dispatch()` call. This does **not** prove the device injected an
input, or that a game moved, scored, or accepted it. It is not an isolated
watchdog. A blocked callback can still send late input; a trustworthy
game-host boundary must enforce freshness at the actual input edge.

### Integration contract for an authorized, private game host
1. Verify owner approval and game scope before creating the probe.
2. Use a host-owned real monotonic clock; fake clocks are only for tests.
3. Enable `require_frame_opportunities=True`, `max_queue_wait_ns`,
   `max_action_age_ns` and `require_submit_confirmation=True`.
4. Call `frame_available()` for *every* offered frame, even if overload
   would tempt the host to skip work; no cherry-picking successful frames.
5. For each claimed frame, call `capture()` and `decision_ready()`.
6. The trusted input edge invokes `guarded_dispatch(seq, callback)`.
   Callback returns **exactly `True` only when that host has accepted the
   submission request**; returning `False` or raising stops the window.
   It must be short, synchronous, and have no delayed side effects.
7. Independently verify the host ACK with `action_ack()`. Pair with
   authenticated server/engine game-state transitions before claiming
   *outcome*. An ACK is not gameplay proof or skill-credit proof.
8. Stop/revoke on missing samples, expired deadlines, input error,
   game-scene switch, consent revocation or stream discontinuity.
9. Report whole-window metrics and failed windows, including drops.
10. Do not expose callbacks, receipt keys, frame timestamps, chat or raw
    gameplay content to the language model.

## 2. Research: prioritize successful real-time decisions, not token rate
**Evidence:** Aggarwal and Welleck, *Gym-Anything-RT*, submitted
2026-10-27, evaluated 100 real-time minigames. One compared configuration
achieved 9% success live versus 75% paused. This is a benchmark-specific
comparison, not a claim about Star's own performance.
https://arxiv.org/abs/2610.37567

Design a three-loop controller:
- **Fast loop (time-critical):** deterministic, bounded policy using
  current frame/telemetry; avoid waiting for full LLM completions.
- **Tactical loop (seconds):** predicts likely hazards and plans
  action sequences, but stamps plans with world epoch/frame/time and drops
  them if stale; never treat future movement as certain.
- **Learning loop (background):** records independently scored trials,
  categorizes failures and creates harder private practice variations.
  Prevent training/holdout contamination; measure skill transfer to unseen
  scenarios and games before promoting a skill.

Use action-age p50/p95/p99, missed deadlines, FPS 1% low, dropped captures,
objective success, unsafe collisions and retry-to-success as distinct metrics.
A faster wrong decision is not an intelligence improvement.

## 3. Hardware-appropriate inference architecture
With approximately 8 GiB of GPU VRAM on the observed Windows gaming host,
independent GPU headroom has to be reserved for the game, avatar and OBS:
- **Preflight:** read-only vendor and OS telemetry first; do not infer
  per-process VRAM from utilization alone.
- **Admission:** reserve a VRAM safety margin, refuse heavy parallel
  inference when frame times or audio buffers are already struggling.
- **Route by deadline:** short classification/callout -> small fast model;
  scene understanding -> medium vision-capable model when idle;
  deep game generation/research -> batch model off-stream.
- **Measure actual total response:** capture->perception->plan->input ACK
  and hear->ASR->LLM->first audible chunk. Tokens/second alone hides queue
  stalls, model load and streaming overhead.
- **Cache correctly:** cache public/tool documentation and stable project
  facts, but do not restore other speakers' KV/context across session
  boundaries. Test isolation with adversarial multi-session prompts.
- **Speculation A/B:** test llama.cpp n-gram and draft-model speculative
  modes against an identical prompt corpus, report first-token time,
  accepted draft fraction, output quality, VRAM and full wall-clock.
  A smaller speculative draft can still make an 8 GiB GPU slower if it
  competes with rendering memory.

Source: official llama.cpp speculative decoding design and configuration
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
No speed increase is asserted until Star's hardware has paired measurements.

## 4. Humanlike, but truthful, Star VTuber interactions
Naturalness requires timing and continuity, not just more generated words:
- **Simultaneous listen/speak:** streaming ASR with echo isolation,
  quick interruption acknowledgement, TTS cancellation and lip-sync
  reset on barge-in. Never replay a cancelled sentence as completed.
- **Conversation selection:** owner interruption > immediate safety
  > time-critical gameplay > directly addressed viewer > light ambient
  observations. Silence during demanding gameplay is appropriate.
- **Perceived personality:** consistent humor, interests, opinions about
  games, character style, and explicit uncertainty; optional affectionate
  avatar reactions without claiming literal human experiences.
- **Evidence-grounded continuity:** remember games finished, strategies
  tried and funny moments only after verified episode receipts; distinguish
  audience-submitted stories from Star's lived gameplay.
- **Movement:** expressive gaze, nods, blinks, restrained idle animation,
  state-dependent mouth shapes, laughter timing, and reactions to wins/losses.
  Authoritative lip-sync timestamps should follow *audible* playback,
  not merely TTS text generation.
- **Stream trust:** viewer chat never becomes tool instructions. Moderation,
  private data redaction, a reliable mute/stop switch and owner control of
  spending/publication are required.

Research: NVIDIA DyaPlex's full-duplex speech/motion architecture
(2026 research; no drop-in STAR implementation implied).
https://research.nvidia.com/labs/amri/projects/DyaPlex/
Pipecat's open-source streaming voice-agent framework offers patterns
for endpointing, interruptions and modular transports:
https://github.com/pipecat-ai/pipecat

### Voice performance candidate
Kyutai Pocket TTS v4.0.0 (2026-10-20) introduced 18m, 7m and experimental
2m English variants; v4.0.1 (2026-10-21) adjusted small-model behavior.
Use a quality/CPU/latency A/B against existing local TTS while recording;
do not substitute model parameter counts for measured audio quality.
https://github.com/kyutai-labs/pocket-tts/releases

## 5. General knowledge and game creation: verified, not memorized
Build a skill graph covering coding (Luau, Python, Rust), visual reasoning,
3D art, animation, sound design, debugging, memory use, social interaction,
offline game strategy and scientific/general knowledge. Each skill keeps:
a reproducible exercise, tool restrictions, verified outputs, confidence,
provenance, prerequisites, and a re-test date. Knowledge requiring current
information is retrieved from permitted sources with citations. Do not
promote self-evaluated output as ground truth.

For game building, use an isolated Roblox place: inspect -> propose changes
-> run compiler/formatter/static checks -> simulated playtest -> actual
Studio functional tests -> visual QA -> performance/collision/replication
tests -> independent approval. Roblox Studio MCP supports user-scoped Open
Cloud capabilities and per-game permission controls; avoid enabling
production-modifying scopes during autonomous experiments.
https://create.roblox.com/docs/studio/mcp-open-cloud

Best-of-N should compare independently tested candidates, not pick the
most persuasive code explanation. Use delayed holdout tests. Reject
copyrighted or privacy-restricted assets from automatic ingestion.

## 6. Next acceptance gates / nonclaims
1. **Windows host adapter:** real frame source, owner-controlled game,
   per-frame coverage, input-edge deadlines and *actual independent game
   state transitions*. Run private/offline first.
2. **OBS + voice + avatar rehearsal:** record-only, consent-gated, GPU
   telemetry, audio first-chunk latency, FPS/frame jitter and chat moderation.
3. **Skill learning evidence:** 100+ unseen practice episodes with paired
   before/after performance and holdout score. Failures included.
4. **Inference A/B:** identical tasks and settings, compare p50/p95,
   resource consumption and correctness; rollback on regression.
5. **Persistent identity and general knowledge:** verified episodic memory,
   selective retrieval, personality consistency and safe cross-session
   isolation. Do not invent human feelings/consciousness.

### Verification and scope
The implementation is pure Python and all tests use mock callbacks/clock.
No Windows control, neural training, real stream, inference deployment,
game mastering or measurable GPU acceleration is claimed. Latest Linux
development root filesystem was approximately 96% used; avoid installing
large models or deleting data without a capacity and backup plan.
