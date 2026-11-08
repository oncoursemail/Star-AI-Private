# STAR — real-time GPU lease accounting, intelligent gaming and natural VTuber roadmap
**Research date:** 2026-11-06. **Scope:** offline-first Windows gaming PC + Linux development host. **Change status:** implemented *host-only advisory* scheduler and synthetic regressions; not deployed into the Windows game/OBS executor.

## 1. Concrete failure observed before changing code

On the owner's connected Windows **Main** machine, a read-only `nvidia-smi` sample on 2026-11-06 showed **RTX 3060 Ti, 8,192 MiB total VRAM, 7,545 MiB used, 480 MiB free, 1% GPU compute utilization, 46°C**. A `llama-server` process was observed separately, but these measurements do not attribute VRAM consumption to that process. Neither OBS nor a Roblox player/Studio process appeared in the sampled process-name filter. A one-time snapshot does not define a stable budget.

This is exactly why low GPU compute utilization is NOT evidence of spare VRAM. A speculative draft model, extra VLM or simultaneous TTS job can fail to load or destabilize the game/OBS render path even while GPU utilization is near idle.

## 2. New implementation (this branch)

**Files:** `star/stream_realtime_gpu_leases.py`, `tests/test_stream_realtime_gpu_leases.py`.

Unlike the existing `StreamAdmissionGate`, which advises each workload independently, `RealtimeGPUWorkLeases` maintains **one bounded ledger for all optional GPU jobs sharing the same device**. It composes the existing gate rather than replacing it.

- Default OFF; only a trusted local host may opt in, accept verified telemetry, and reserve optional work.
- Before admitting any research, training, rendering or vision claim, subtract **all outstanding claims** and preserve a configurable critical VRAM reserve for game rendering, Star's speech/avatar and OBS.
- Only 1–4 optional concurrent jobs, with default maximum 2; monitor stale metrics, clock reversals, game FPS, speech backlog, OBS render/encoder lag, worker heartbeats, and private-rehearsal transition.
- **Immediate revocation advice** upon resource pressure. A revoked lease remains charged until the host independently confirms that its worker really stopped. Stalled or absent acknowledgements never silently restore GPU headroom.
- Strong session/identity binding, restart fencing, explicit start and stop acknowledgements, bounded read-only metrics, no stored raw frames/audio/chat/PIDs, and no authorization for tool use, real input, public broadcast or model execution.
- Synthetic, deterministic concurrency/regression tests cover simultaneous overbooking, live/private transitions, stale and malformed measurements, worker timeouts, revoked-ticket replay and recovery.

**Conservative caveat:** current accounting subtracts outstanding claims even where sampled free VRAM already reflects allocations by active workers. This can reduce throughput. It is preferable to optimistic double allocation under unreliable host sampling. Production integration should eventually record the CUDA allocation boundary so pending versus resident reservations can be reconciled safely.

**Host integration contract:** never expose `host_verified` or `host_confirms_worker_stopped` as model-callable flags. The authorized local host authenticates telemetry, reserves capacity before starting an optional worker, explicitly observes its start, polls revocation, terminates or suspends optional workers through independently permissioned OS code, and calls `release` **only after confirmed cessation**. Underlying game/speech/OBS jobs are never managed by this optional-job ledger.

## 3. Intelligence: two clocks, one verifiable learning loop

The October 27, 2026 **Gym-Anything-RT** research introduces 100 changing-environment minigames. The key finding is that a strong reasoning system can fail dramatically if the world progresses during thought. Treat *real-time play* and *offline strategy research* as different processes:
1. **Fast reactor** (live): observe recent frames, track uncertainty and scene age, decide whether an action is still meaningful, or deliberately take no action. Prioritize game input and verified release; no leisurely chain-of-thought in the critical frame path.
2. **Strategist** (between play segments): review recent verified states and independent outcomes, develop tactics and compare plans. Do not use live chat as permission to run actions.
3. **Teacher/self-play** (off-stream only): use game simulators, Roblox Studio Lab, counterbalanced A/B policy trials, hidden holdouts and code/visual tests. Feed back only improvements with independent success evidence, keeping training data separate from evaluation.

Reuse the repository's existing `GameDeadlineRouter`, `game_latency_skill_lab`, `game_holdout_schedule`, `game_transfer_eval`, and gameplay skill bank. **Do not** claim a higher-intelligence model just because a scheduler or larger context improves apparent performance.

Recommended independent metrics: success on unseen scenarios; time-to-action and p95 action acknowledgement; action validity under observation age; failures and near misses, including abandoned and no-action cases; before/after game outcome skill gain; CPU/GPU cost per verified success.

Source: https://arxiv.org/abs/2610.37567 (Aggarwal & Welleck, October 27, 2026).

## 4. Performance: what to test instead of claiming impossible tokens/sec

1. **Measure before reconfiguration:** cold/warm first-token latency, sustained decoding tokens/s, p50/p95/p99 end-to-end frame-to-action and audible speech, peak resident VRAM, KV-cache memory, concurrent task load, OBS rendered/encoded loss, game FPS and jitter.
2. **Router:** fast local model for latency-sensitive gameplay or spoken backchannels; larger reasoner only off-stream or for verified hard tasks. Treat workload-specific heldout quality as a required gate; slower can be correct, faster can be wrong.
3. **KV/cache engineering:** isolate user/game/session contexts; cache stable skill/doc prefixes and expire invalidated scene states. Long context costs memory and prefill time; retrieval plus a compact evidence ledger is usually a better default than blindly increasing context.
4. **Speculative decoding:** benchmark llama.cpp server draft-model and n-gram speculative modes individually *under actual stream contention*; extra draft-model VRAM can hurt an 8GB card. Measure acceptance rate, first-token latency and successful tokens/s, not only peak speed.
5. **CPU voice:** evaluate Kyutai Pocket TTS as an off-GPU option with consented voices. Its reported CPU speeds are on its published reference hardware, **not** a performance measurement on Star's PC. Monitor CPU contention with game capture and audio playback.
6. **Roblox build throughput:** apply best-of-N Luau candidates then lint/static analysis, Studio test, visual inspection and outcome verification. Cache imported, approved source/documentation and reusable assets, not unreviewed generated answers.

Sources:
- llama.cpp inference and supported CPU/GPU hybrid path: https://github.com/ggml-org/llama.cpp
- llama.cpp speculative implementations and metrics: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Pocket TTS CPU/streaming technical reference: https://kyutai-labs.github.io/pocket-tts/

## 5. More humanlike (not falsely human) on-air interaction

Microsoft Research's **Proact-VL** (ICML 2026) emphasizes not just *what* to say but **when** to say it. For Star, naturalness should be measured by:
- Suppress commentary during tense real-time input windows, while a guest is speaking, when audio output is interrupted, or when a claim lacks evidence. Treat intentional quiet as a positive choice, not an error.
- Short specific reactions on independently witnessed wins, failures and discoveries; longer reflection between matches. Ground memories in actual witnessed moments, not invented personal stories.
- Full-duplex turn taking: voice activity/echo suppression, owner-authenticated barge-in, partial utterance cancellation, mouth animation synchronized to *actually played* PCM (not just generated text), expressive neutral idle states and emotion-conditioned gestures.
- A consistent fictional adult persona with humor, interests and relationships, but **clear disclosure that Star is an AI VTuber**, not a real human person. Never fabricate private-life experiences to simulate authenticity.
- Personalized general knowledge: retrieved primary sources with dates, explicit uncertainty, self-correction, local preference/memory storage with retention and source controls; no viewer-granted permissions.
- Before public streaming, independently review private OBS clips for audible reply p95, interruption latency, mouth alignment, excessive overlap, false interruptions, game/stream FPS stability, factual grounding and prompt-injection defense.

Sources:
- Proact-VL: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- OBS websocket security and recording interface: https://github.com/obsproject/obs-websocket
- BayLing-Duplex (June 2026; research, not ready-to-integrate STAR capability): https://arxiv.org/abs/2606.14528

## 6. Roblox + generalist developer autonomy

Roblox's **November 4, 2026** Studio MCP expansion exposed Open Cloud operations through per-game permissions and asset-import workflows. Use a dedicated private Studio sandbox and minimal permissions; default any publishing, monetization, moderation or production state changes to owner review. Teach Star to inspect project structure, retrieve correct Luau/Roblox API references, implement with Rojo/StyLua/Selene/luau-analyze when applicable, playtest with engine evidence, and automatically repair only verified faults.

Source: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849.

## 7. Next concrete acceptance milestones

**A. Integrate leases with actual Windows host (not done).** Connect trusted NVIDIA/OBS metrics to the lease ledger and a separate authorized process manager. Verify exact GPU start/stop confirmations and use bounded worker heartbeat. Accept only after telemetry-stale, OBS-lag and process-hang fault injections stop OPTIONAL work without blocking game input or speech.

**B. Private end-to-end Windows game + OBS rehearsal (not done).** Collect real game frames, native input receipts, independently observed state changes, Star audible PCM, mouth/avatar frames, OBS recording and OBS interval counters in the same signed session. Use `stream_private_rehearsal_scorecard` and existing independent host probes. No live broadcast or public chat input.

**C. Held-out game improvement (not done).** Precommit unfamiliar minigames and Roblox Studio tasks, evaluate baseline and candidate with identical load and counterbalanced order, and require a significant positive gain with no critical-case regression.

**D. Speech naturalness gate (not done).** Record owner-approved private, isolated audio/avatar clips, measure p95 audible latency and barge-in playback stop, false interruption rate, grounded speech, and independent human preference for timing/expressiveness. Explicitly keep the AI disclosure.

**E. Actual inference speed gate (not done).** Compare baseline and tuned configurations under simultaneous game/OBS/TTS load. Only promote a faster route when latency *and* independently measured quality improve or remain within predeclared noninferiority limits.

## Important limits

New lease accounting is **real tested Python infrastructure**, not an actual CUDA allocation hook, Windows driver integration, faster model, a trained gameplay policy, verified humanlike performance, or a streaming deployment. No heavy model was installed. This work was deliberately offline and safe with roughly 11 GiB free on the connected Linux root filesystem and limited live Windows GPU headroom.
