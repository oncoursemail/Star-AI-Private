# STAR — pre-submit action freshness, intelligence, and VTuber QoS
Implementation & research record · November 6, 2026 · private/offline only

## What is implemented in this branch

The existing private host probe witnesses offered frames and measures the latency
between capture, completed reasoning, submission and host acknowledgment.
It previously enforced optional queue age but did NOT reject a decision that
became stale *during inference or while preparing the input*. This can make a
correct recommendation dangerous in a real-time moving game.

This branch adds **opt-in action freshness** to
`star.host_monotonic_game_probe.HostMonotonicGameProbe`:

- `max_action_age_ns` (strict int, 1,000,000..10,000,000,000 ns). Disabled
  by default; existing unguarded callbacks are backward compatible.
- An approved host records `decision_ready(sequence)` and MUST then call
  `pre_submit_check(sequence)` synchronously on the **actual action path,
  immediately before issuing input**. The check uses the same local monotonic
  clock as capture; the total age includes frame queue time and inference.
- A stale check rejects the decision and revokes the whole measurement window.
  No previous fast frames remain eligible for a success-only report.
- The subsequent `action_submitted(sequence)` requires one prior freshness
  check and independently checks the deadline **again**. This identifies time
  spent between pre-submit validation and the host's submission event.
- Duplicate/reordered/bool frame identities and clock regressions revoke the
  window. Counts-only status exposes `action_deadline_violations`, guard active,
  and `action_freshness_attested=False`; no raw timestamps or sensitive
  gameplay/media/chat content is reported.
- All logic is local. There is NO automatic game control, authorization to
  send an action, authenticated hardware clock, signed frame source, independent
  gameplay proof, OBS broadcast, or external network call.

Integration sequence (example pseudocode, NOT a wired game host):

    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        max_queue_wait_ns=30_000_000,
        max_action_age_ns=80_000_000,
    )
    offered = probe.frame_available()     # at the actual frame-offer boundary
    sequence = probe.capture(opportunity=offered)
    # run an approved model/controller against the authenticated game state
    probe.decision_ready(sequence)
    probe.pre_submit_check(sequence)       # MUST precede the real host input
    # approved_host.send_input(action)      # intentionally NOT called here
    probe.action_submitted(sequence)       # records host submission; checks age again
    probe.action_ack(sequence)             # ACK is not proof of in-game movement
    diagnostic = probe.finalize()

Important TOCTOU limitation: because the check and a host's input operation
are separate, Star cannot prevent a malicious or incorrectly integrated host
from sending the action anyway. The second check detects a late host
submission but cannot undo an already-sent input. Before any real-game use,
integrate an atomic, owner-approved host action gate and an independently
validated game-state transition; do NOT label this as real gameplay safety.

Tests cover the compatibility path, strict input validation, stale inference,
stale queue time, missing/duplicate checks, late submission, revoked
history, deadline equality, count redaction, deterministic latency replay,
and synthetic-game outcomes. They do not benchmark actual model speed.

## Research: priority changes versus incremental features

### 1. Real-time game intelligence must account for action age

A strong language model that reasons for 500 ms may be worse at a game than a
simpler controller acting in 20 ms. Keep three separate loops: (a) direct
reaction/control from last trusted frame with a hard deadline, (b) tactical
planning over seconds, (c) offline curriculum and verified skill acquisition.
Measure completed objectives, unsafe actions, p50/p95 age at submission, lost
frames and recovery quality. This new deadline gate is a small piece of (a).

Recent work:
- Realtime-Bench (2026): https://arxiv.org/abs/2610.22155
- Gym-Anything-RT (Oct 27, 2026): https://arxiv.org/abs/2610.37567
- RT-SAFE (2026): https://arxiv.org/abs/2610.09294

### 2. Model speed: benchmark scheduling and privacy, not just advertised tok/s

On 8 GB GPUs, leave a measured VRAM margin for the game, compositor/avatar,
OBS and KV cache. Try CPU speech as a *separate* tested option rather than
loading one more GPU model unconditionally. Track TTFT, generation latency,
full perceive→action delay, GPU 1% low FPS, OBS lost frames, audio underruns,
and correct task completion **at a fixed workload**. Compare same quantized
model/context, warm/cold cache, and repeat across multiple trials.

- Official llama.cpp speculative decoding:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Official llama.cpp server flags and metrics:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Open Aug 2026 report of cross-conversation cache contamination:
  https://github.com/ggml-org/llama.cpp/issues/27148

The cache-contamination report requires evaluating slot/session isolation
before enabling RAM-backed cache sharing for stream chat. A performance
optimization must never cause one viewer's private prompt to leak into another
interaction. Prefer explicit per-session cache partitioning or opt-out where
isolation cannot be verified.

### 3. VTuber voice: choose the smallest *intelligible* model under load

Kyutai Pocket TTS v4.0.0 (Oct 20, 2026) offers 18M, 7M, and experimental 2M
English model options. Run blinded listening tests for clarity and emotional
range as well as first-audio latency on Star's own CPU *while playing*.
Pre-render safe stock reactions; limit speech concurrency; suppress commentary
during high-risk gameplay; preserve interruption and silence. Full duplex
speech models such as NVIDIA PersonaPlex are useful research references but
not a guarantee of VRAM fit on an 8 GB gaming GPU.

- https://github.com/kyutai-labs/pocket-tts/releases
- https://github.com/NVIDIA/personaplex
- https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

Humanlike streaming is best evaluated through conversational turn-taking,
grounded commentary, audio/video alignment, consistent but evolving
preferences, recovery from misunderstandings and transparent AI identity.
Store verified game anecdotes, not fabricated first-person human memories.

### 4. Roblox game creation: exploration before modification

Roblox's OpenGameEval (Oct 2026) evaluates reproducible Studio agent tasks
through executable scene and play-session checks. Its report notes that
agents which inspect affected objects before editing tend to succeed more.
Establish inspect→plan→modify in a test place→playtest→repair→regress.
Isolate asset imports and any sensitive Open Cloud write scopes. On
Nov 4, 2026, Roblox extended Studio MCP with Open Cloud invocation and
per-game permissions; live DataStore access can touch real player data.

- https://github.com/Roblox/open-game-eval
- https://create.roblox.com/docs/studio/mcp-open-cloud
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

## Acceptance gates before enabling real host operation

1. Host integration must have explicit owner opt-in, authenticated frame
   origin/session and independent frame-count comparison; test missing frames.
2. Integrate a single atomic submit path: invalid/expired action NEVER reaches
   game input. Inject long inference and pre-submit stalls while verifying
   real host refusal, not merely telemetry rejection.
3. Preserve frame→action→ack→new game-state evidence chain; distinguish ACK
   from actual movement, win/loss and hazard collisions.
4. Run private Windows recording with game, OBS, avatar and speech together.
   Compare 3+ repeated trials per condition, including GPU saturation.
5. Only promote a new controller/model/voice if it improves a defined
   quality-latency frontier without privacy or safety regressions.

**Current proof level:** local deterministic guard and synthetic replay
tests only. No new neural model training, model speed benchmark, real
gameplay control, speech generation or actual VTuber stream is claimed.