# STAR — witnessed frame coverage, real-time intelligence and streaming quality
Research and implementation note | 2026-11-06 | private / opt-in

## Implementation this change actually adds

Earlier host timing recorded capture -> decision -> action-submitted -> ACK.
The resulting reported latency could still look fast if the host did not call
capture() for a frame it was unable to process. Correcting this *survivorship
bias* is more immediately valuable than guessing another model's throughput.

New **opt-in** HostMonotonicGameProbe mode, require_frame_opportunities=True:

- The approved host invokes frame_available() as soon as each frame is offered
  to Star, *before* choosing whether an agent will process it.
- Each opportunity has one local, monotonically increasing sequence. The
  subsequent capture(opportunity=...) is strictly ordered, single-use, and
  reuses the earlier availability timestamp. Queueing time is thus INCLUDED
  in capture-to-decision and end-to-end latency, not silently discarded.
- Missing, duplicate, out-of-order, and unclaimed opportunities prevent a
  complete timing report; explicit drop_frame(...) increments the drop
  counter and revokes the entire window, including previous fast frames.
- Optional max_queue_wait_ns enforces an explicit 1ms–10s queue admission
  deadline; an over-deadline frame is rejected BEFORE an action is proposed.
- Per-window limits stay 256 offered frames. The legacy probe API remains
  compatible and the new behavior is disabled by default.
- Counts-only status includes offered, unclaimed, dropped, revoked and the
  explicit host_coverage_attested=False flag. No screenshots, video frames,
  speech, identities, raw clock timestamps or input actions are exported.
- No game/OBS/network interactions are made. No authority to send inputs,
  publish a stream, upload assets, or alter a live game is added.

Example private host instrumentation (pseudocode, not a wired host):
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        max_queue_wait_ns=50_000_000)
    token = probe.frame_available()  # call at host frame offering
    seq = probe.capture(opportunity=token)  # may reject a queue timeout
    probe.decision_ready(seq)        # real model returned
    probe.action_submitted(seq)      # approved host submission
    probe.action_ack(seq)            # host ACK, NOT game-state proof
    diagnostic = probe.finalize()    # only if every frame completed

There is NO independent guarantee that an untrusted host calls
frame_available() for every offered game frame, that the clock is untampered,
or that host ACK means that the character moved. These counters must not be
called frame-attested or gameplay-attested. The next trust boundary is a
separate game-state witness / frame-source log (with authenticated frame
IDs, independently counted drops and signed state transitions).

## What recent research changes about the architecture

1. **Real-time intelligence means speed *and* outcome quality**. Realtime-Bench
   (Oct 15, 2026) compares Wall Clock, Paused Clock, and Token Clock and
   reports up to 44% best Wall Clock success. More reasoning can hurt when
   decisions arrive too late. Star needs separate fast reflex control,
   medium-cost tactical planning and asynchronous learning, with
   deadline-sensitive admission rather than uniform model effort.
   Source: https://arxiv.org/abs/2610.22155

2. **A completed objective can conceal a dangerous journey**. RT-SAFE
   (Oct 7, 2026) reports a 12.3x increase in collision incidents in a
   matched real-time vs static comparison, despite similar completion rates.
   The lesson for Star is to record collision, softlock, and deadline
   incidents independently of win rate, and to stop unverified actions.
   This is an embodied simulation result, not a measured Star outcome.
   Source: https://arxiv.org/abs/2610.09294

3. **Real-time gaming is not pausible by default**. Gym-Anything-RT
   (Oct 27, 2026) released 100 real-time minigames and demonstrates
   large paused-vs-running performance gaps. Pair unseen scenario evaluation
   with real measured host latency and report BOTH objective completion
   and milliseconds to safe action, plus action-age percentiles.
   Source: https://arxiv.org/abs/2610.37567

4. **Treat prompt caching as a security boundary**. A public llama.cpp
   issue from Aug 15, 2026 reports cross-conversation restoration of
   unintended cache state under concurrent load. Before enabling
   multi-user streaming chats on a shared llama-server, test session
   isolation and disable cross-slot RAM caching if unverified. Avoid
   blindly assuming cache=more speed without information-leak risk.
   Source: https://github.com/ggml-org/llama.cpp/issues/27148

5. **Voice should not make the game unplayable**. Pocket TTS 4.0.0
   (Oct 20) and 4.0.1 (Oct 21) introduce compact CPU-capable
   English models; candidate sizes include 18m, 7m, and experimental
   2m. Test real local time-to-first-audio and intelligibility in
   the presence of game rendering, OBS recording and AI inference.
   Compare with the existing voice stack; do not switch on hype.
   Source: https://github.com/kyutai-labs/pocket-tts/releases

6. **Naturalness requires timing, not fake humanity**. DyaPlex
   (June 2026) studies streaming, full-duplex synchronized speech
   and motion. For Star, add an interruption arbiter and speech
   queue with explicit silence, viewer turn-taking, overlapping
   game audio limits, emotion/expression trajectories and verified
   episodic memory. She can be a warm, consistent AI personality
   without concealing her AI nature or implying subjective feelings.
   Source: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

7. **Roblox creation must remain permission-scoped**. Roblox's
   Nov 4, 2026 Studio MCP Open Cloud expansion exposes assets,
   game settings, analytics, products and publishing through
   scopes the user sets per game. Start with read-only inspections
   and isolated unpublished test environments; don't autonomously
   enable monetization, bans, paid ads, live publishing or DataStore
   writes. Independent Studio playtests must validate functionality.
   Sources: https://create.roblox.com/docs/studio/mcp-open-cloud
   https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

## Next practical milestones, prioritized

**P0 — Honest measurement:** Wire frame_available() to a specifically
authorized private game host before capture(). Compare host-delivered
frame count against an independent frame-source counter, deliberately
inject skipped frames and queue overruns, and verify that failing windows
cannot become cherry-picked low-latency success reports. Host ACK is
separate from the game-state transition witness. Run record-only first.

**P0 — Hardware admission:** Before gaming+inference+speech+OBS, record
GPU VRAM headroom, GPU utilization, CPU saturation, and OBS dropped
frames. An 8 GB GPU at high occupancy cannot be assumed to fit everything.
Prefer bounded model context, CPU speech path when demonstrated faster
end-to-end, and adaptive step-down under overload. Run reproducible
A/B experiments at the same frame rate and content, with p50/p95/p99
decision age, FPS 1% low, audio gap frequency, lost frames and
actual achievement rate. Never claim a model speedup from code-only tests.

**P1 — Learn gameplay:** Produce an unfamiliar-game skill ladder:
mechanic hypothesis -> safe micro-experiment -> signed observations ->
independent outcome -> short verified skill note -> held-out replay.
Separate tactical mistakes, stale observations and platform latencies.
Evaluate safety incidents as well as win rate.

**P1 — VTuber director:** Separate interruptible speech planning from
the game controller; allow silence and fast nonverbal expressions;
link animation to audio timing; cap chat response queue age; filter
private information and chat content before speaking. Use OBS local
recording, not a public broadcast, for acceptance. Never spoof a real
person or claim to have human biological experiences.

**P1 — Game creator:** Star should inspect Roblox place state, generate
Luau/Blender changes, run lint/compile and isolated Studio playtests,
take screenshots for human-like visual quality review, and repair
the failures it can independently reproduce. Keep production changes
and uploading assets gated.

**P2 — Generalist intelligence:** Add verified skill cards for browsing,
desktop operations, software debugging, game art, video, sound, and
systems administration. Periodically evaluate counterfactuals and
retained knowledge. Self-improvement proposals remain reviewable,
reversible and versioned locally; GitHub is an optional publish target.

## Verification and limitations

Scope: local-only Python probe extension with deterministic / smoke tests
and no internet/game I/O. This update does not yet provide independently
attested real-game telemetry, autonomous gameplay, learned neural weights,
a faster language model, actual TTS-OBS integration, or a live VTuber.
The overall system's first real quality gate is a signed, privacy-scrubbed,
record-only Windows rehearsal with consented input boundaries.

The development Linux host was previously near filesystem capacity.
This update deliberately avoids downloading models or cleaning user
files without an explicit storage plan.
