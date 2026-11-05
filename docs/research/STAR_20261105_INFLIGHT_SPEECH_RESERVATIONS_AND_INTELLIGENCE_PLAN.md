# STAR — In-flight speech reservations, game learning, and real-time intelligence
**Research and implementation note · 2026-11-05**

## Scope and reproducible problem

STAR's prior opt-in `StreamDirector(proactive_limit_per_minute=N)` checked
*completed audible* optional events only during `propose()`. Two asynchronous
proposals could each pass while the counter remained zero. If both were later
spoken, their combined count could exceed the configured limit. A final
`complete()` receipt was not sufficient to prevent actual audio already sent
to the host. Reproduction: offer low-priority optional cue A; propose A; offer
higher-priority optional cue B before any completion; propose again. Before this
patch B was admitted even with `N=1`. This matters for plausible VTuber
behavior: noisy narration is unpleasant, particularly during gameplay.

## Implemented in this PR

- Reserve *capacity* for an issued, unexpired optional `SpeechIntent` before
  offering another distinct optional event. A revised proposal for the same
  underlying event reuses its reservation rather than creating another.
- Reservations are released on host-confirmed failed speech, completion,
  event expiration, scene handoff, or session disable. Only successfully
  confirmed audible completions count in the rolling 60-second quota.
- Real questions, owner interruptions, and observed urgent danger bypass the
  optional budget; they retain the existing speech/fairness checks.
- Add a defensive receipt-side quota check, a privacy-safe
  `proactive_pending` metric, and controlled huge-clock-input validation.
- Pure planning only: **no microphone, synthesized speech, game input, OBS
  control, public broadcasting, or learned model changes**.
- Off by default. An issued plan can temporarily reserve an optional slot
  before speech. Lost/abandoned plans must be explicitly completed as failed
  when possible; otherwise their source event TTL releases the reservation.

## Research, grounded in available sources

1. **Speaking appropriately is a model and scheduler problem.** Microsoft
   Research's *Proact-VL* (ICML 2026, May) studies when to respond during live
   gaming, not just what to say. STAR needs event novelty, viewer intent,
   interruptibility, silence, and scored commentary relevance. A rate cap is
   only a safeguard, not a naturalness evaluator.
   https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
2. **Roblox agents need stateful, playable verification.** The OpenGameEval
   paper (submitted 2026-10-01) evaluates 84 curated core Studio tasks in an
   actual engine with edit- and play-time checks. The public repository offers
   a reusable inspection-before-editing benchmark pattern. STAR should score
   held-out first-try task success, deterministic repair, and scene inspection
   before editing; code compilation alone is insufficient.
   https://github.com/Roblox/open-game-eval
   https://arxiv.org/abs/2610.02563
3. **Voice can be CPU-oriented, but latency is hardware-specific.** Kyutai's
   Pocket TTS README describes October 2026 compact English models at 18.2M,
   6.9M, and 1.9M parameters (including decoder), intended for fast CPU
   generation. Test the actual voice quality, warm/cold start, interruption
   flush, RMS/lip sync, and CPU contention versus gameplay. Do not extrapolate
   vendor speed claims to STAR's Windows PC.
   https://github.com/kyutai-labs/pocket-tts
4. **Speculative decoding must win end-to-end, not just tokens/sec.** The
   llama.cpp documentation supports draft-model and EAGLE-3 approaches.
   These can increase VRAM footprint and contention. Before enabling on an
   8 GiB GPU, benchmark both isolated inference and OBS+game+avatar+TTS
   concurrent operation, p50/p95 first-token latency, acceptance rate, and
   frame drops. Use the same prompts, quantization, temperature and context.
   https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
5. **Model routing and verified practice beat blind self-training.**
   For coding, generate several solutions only when the cost is justified;
   run deterministic Luau/static checks and sandbox playtests; store only
   source-linked lessons with before/after evidence, revision IDs, and expiry.
   Maintain holdout game levels and unseen Studio tasks to detect overfitting.
   Every self-update needs a reversible local snapshot and an offline rollback.

## Prioritized architecture

**P0: private real-time rehearsal (no live broadcast).** On the authorized
Windows gaming machine, record a short private session with a fixed game and
known play route. Produce synchronized observations of game FPS, rendering
latency, token latency, TTS start/end, audible output, speech interruptions,
avatar pose, and OBS recording progression. Log event IDs/timestamps and
hashed evidence only; never store chat secrets. Compare opt-in cadence OFF
and ON with exactly matched replay scenarios. Verify listener judgment on
naturalness and missed genuinely useful comments, not just fewer words.

**P1: hierarchical autonomous gamer.** Separate 10–30 Hz input/observation
loops (lightweight safety and movement) from periodic world-state planning
and an asynchronous practice/review worker. Learn game mechanics from
manuals and approved observation; issue only supported game inputs. Record
action `->` outcome receipts, failures, recovery plans, and success on unseen
level variants. Bound vision rate under GPU pressure and yield to critical
game/OBS tasks.

**P2: game developer with executable evidence.** For each Roblox task:
read scene hierarchy, look up current APIs, make minimal reversible edits,
run Luau analysis + Studio tests, inspect resulting gameplay, perform a
failure diagnosis, then either deliver an independently passing result or
revert. Benchmark with separate functionality, robustness, and aesthetic
rubrics; maintain a never-seen-before challenge set.

**P3: natural VTuber persona grounded in real events.** Persistent preferences,
hobbies, relationship continuity, and expressive emotional *behavior* can
be simulated consistently, without claims of human consciousness or real
feelings. Use permissioned episodic memories with provenance, give viewers
space to finish speaking, suppress repetitive acknowledgements, match
expressions to verified game events, and respond to silence appropriately.
Never impersonate a human or conceal AI identity.

**P4: compute scheduling and intelligence throughput.** Run real-time
gaming/recording/audio at higher priority than speculation, research, and
distillation. Preallocate VRAM headroom, measure eviction/reload costs,
cache safe immutable prompt prefixes per identity and session, and validate
cross-session isolation. Test fast/smart routing on correctness per joule and
wall-clock time, not token throughput alone.

## Required acceptance gates

- Unit: concurrent issued optional plans cannot exceed rolling capacity;
  same-event re-proposals reuse a slot; abandoned, expired, and scene-revoked
  plans release it; urgent verified events bypass it.
- Privacy: metrics expose counts, not names, transcripts, or source text.
  No instruction originates from untrusted Twitch chat.
- End-to-end: private capture proves audible speech (not only queued text),
  real input/outcome success, avatar audio sync, sustained frame pacing, and
  zero unauthorized streaming. Require human review of a recording sample.
- Comparisons: fixed seeds, matched hardware load, repeated randomized
  episodes, baseline vs candidate reports with confidence intervals.
  Revert any increase in missed viewer questions or p95 gameplay latency.

**Limitations:** The implementation here fixes planner admission and overflow
handling, not measured neural intelligence, gameplay skill, FPS, speech
quality, or the independent real-Windows VTuber rehearsal. Feature stays
opt-in and stacked as a draft PR.
