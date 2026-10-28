# STAR — Selective Visual Recall, Gaming Intelligence & Natural VTuber Roadmap
**Research and implementation:** 2026-10-28 | **Status:** draft, opt-in, offline-first

## What this change actually implements

Star's earlier Windows capture bridge + ROI-first paired VLM can perceive potential
changes, but comparing only an immediately preceding frame misses context: when
did an obstacle first appear, what did the HUD look like before a failed jump,
and did a menu change persist across several frames?

New \`star.stream_visual_recall.VisualRecallHost\` is an optional wrapper for an
**already-authorized** \`trusted_worker\`. It preserves that worker's
\`CapturedVisionFrame -> WorkerReport\` behavior and adds a small **RAM-only
visual history** following *successful worker reports*. The host can query
metadata-only bookmarks and request an older frame's *host-selected crop*.
The crop can then become context for a separately approved local vision task.
This is not a new capture target, arbitrary filesystem access, gameplay control,
a model, automatic inference, or broadcast permission.

- Off by default; enabling requires owner + authorized game-capture approval.
- Inspecting a pixel crop separately requires owner + local-inspection approval.
- 2–8 frames (default 5), TTL 2–30 s (default 15 s), RAM budget 128 KB–2 MB
  (default 1 MB); max stored side 640; max returned crop side 512.
- Opaque, session-scoped frame IDs prevent references surviving a disable/restart.
- Invalid geometry, reversed monotonic timestamps, broken RGB layouts,
  repeated static frames and overly frequent frames are rejected or skipped.
- Every evicted/expired/suspended JPEG and outstanding inspection handle is
  best-effort overwritten in memory. A failed/uncertain underlying worker
  clears the cached history but preserves its original safety result.
- Replays **never invoke the vision model** or claim a verified game result.
  If a host later submits selected crops to a VLM, *that* external request must
  still pass the existing latency, provenance and hardware governors.

### Host integration (no automatic rollout)

\`\`\`python
from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_visual_recall import VisualRecallHost

vision = LocalLlamaComparisonWorker(
    model="owner-approved-local-vision", skip_identical=True,
)
# Separately configure the authorized Windows game capture host and its
# own process/window binding, telemetry, and inference permission.
history = VisualRecallHost(vision)
# Explicit owner opt-in, not derived from viewer/game/model text:
vision.enable(owner_approved=True, local_model_approved=True)
history.enable(owner_approved=True, game_capture_approved=True)
# Pass history as the existing capture host's trusted_worker.
# A host-only "inspect older observation" tool can call recent() and inspect().
# After use: crop.erase(). At end of session: history.disable(); vision.disable().
\`\`\`

The current pull request does not configure that live host, install an actual
supported visual model, or publish images. Historical JPEGs are **lossy,
downscaled**, unlike VISTA's lossless examples; this saves RAM and CPU bandwidth
on an 8-GB-VRAM gaming computer at the cost of some fine detail. Image buffers
temporarily materialized by PIL and copies retained by outside host code cannot
be guaranteed cryptographically erased in Python.

## Evidence and research reviewed

1. **VISTA (Han et al., 2026-10-01)**: long-horizon visual control benefits from
   active inspection, retrieval of earlier observations, history and pixel
   measurements. Its reported ARC-AGI-3 RHAE performance is a research result
   for VISTA and a different model/platform; it must **not** be claimed for Star.
   https://arxiv.org/abs/2610.02200
   https://github.com/joshhhhhan/VISTA

2. **MementoGUI (2026-05-18)**: uncontrolled screenshot replay wastes visual
   context; selective memory with ROI evidence is a more useful design goal
   for long UI interactions. Our module is deterministic, not its learned memory
   controller, and must prove utility with held-out tasks.
   https://arxiv.org/abs/2605.18652

3. **OpenGameEval (Roblox, 2026-10-01)**: 84 core tasks, 13 models, executable
   Studio checks. Inspecting objects before editing correlates with success.
   Build and play actions must be validated in Roblox Studio, not inferred from
   screenshot similarities or model confidence.
   https://arxiv.org/abs/2610.02563
   https://github.com/Roblox/open-game-eval

4. **Roblox Studio built-in MCP + Playtest Agent (March–April 2026)**:
   native Studio MCP can inspect and test actual places. Use a trusted Studio
   scorer to attest actions and run IDs; prevent experiments from viewing
   hidden validation episodes.
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
   https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767

5. **LiveKit adaptive interruption (current docs, checked 2026-10-28)**:
   distinguish genuine barge-in from acknowledgments, avoid cutting off Star's
   spoken sentence, and time reactions to real viewer turns. *Caveat:* LiveKit's
   adaptive service has LiveKit Cloud authentication and eligibility conditions;
   local-first cannot assume the cloud behavior works offline. Fall back to
   local VAD and test backchannel/false-interruption rate.
   https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/

6. **Kyutai Pocket TTS v4.0.0 (2026-10-20)**: CPU-oriented 18M, 7M and
   experimental 2M English voices. Benchmark expressiveness, laughter,
   intelligibility and first-chunk latency versus Star's existing TTS before
   considering a change; use licensed voice presets/consented voice data.
   https://github.com/kyutai-labs/pocket-tts/releases
   https://kyutai-labs.github.io/pocket-tts/

7. **Long-horizon grounded memory (2026)**: TrajWiki and REM motivate
   provenance-aware, updatable memory and intervention *when needed*, rather
   than continuously dumping old experiences into context. Star's signed
   continuity/recall evaluation should remain the source of factual streaming
   stories; screenshots are not independently verified memories.
   https://arxiv.org/abs/2608.00967
   https://arxiv.org/abs/2610.27377

8. **llama.cpp server instrumentation**: measure real prompt processing,
   decode rate, queued requests and VRAM on the actual deployed model rather
   than assuming ROI or caching speeds up inference. A prior two-image request
   exceeded 30 seconds under load; this change does not fix that bottleneck.
   https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

## Next architecture: more capable gaming + more believable streaming

**A. Visual attention as a scientific tool.** Before a difficult jump, Star's
authorized gameplay host captures a short series of frames. Afterward, the
local vision agent can request one *specific* prior frame and region (HUD,
landing area, hazard). A separate engine scorer checks position/checkpoint and
labels success/failure. Store the signed outcome, not the raw screenshot, in
longer-term skill memory. Train a retrieval/ROI policy only on practice runs;
validate on new maps. Measure action count, error attribution, hallucination
rate and replay usefulness.

**B. Real-time three-lane compute.** Prioritize 60-FPS game/OBS and low-latency
voice. Keep immediate controls, local turn-taking and short responses on the
fast lane. Run detailed VLM analysis only on novelty or host-requested
inspection, with outstanding lease tracking. Put self-generated lessons,
dataset curation, Blender baking and candidate-vs-baseline evaluation in the
idle/night lane. Record p50/p95 *capture-to-usable-finding* and true llama.cpp
tokens/second; test concurrent Roblox + OBS + TTS on the Windows RTX 4060,
not on synthetic image preprocessing alone. Avoid unbounded GPU parallelism
and never infer completion from a client timeout.

**C. Verified Roblox game factory.** Use Studio MCP to inspect exact objects
before editing them; create small vertical slices; check object geometry,
overlaps, collision, textures, client/server Luau compatibility, interactions,
perf budget and accessibility. Run playtests with independent verifiers,
best-of-N candidate generation, semantic diffs and repair loops. Compare
against held-out OpenGameEval-inspired tasks. Maintain source/asset licenses.
A nice screenshot alone is not a playable, polished game.

**D. Faster general knowledge.** Separate reference facts (with provenance and
freshness), procedural skills (versioned and tested), episodic experiences
(signed), user-approved character lore, and uncertain model opinions.
Retrieve selectively; track claim conflict/age; abstain when unknown.
For learning, schedule interleaved practice with spaced recall and
counterexamples, then retest on independent unseen game engines and subjects.
Memory quantity is not intelligence; successful transfer is.

**E. More humanlike VTuber delivery.** A stream director should know when to
remain quiet, react with natural latency, pick one viewer message rather than
interrupting constantly, and synchronize a spoken reaction with facial pose,
eye movement, head tilt and secondary twin-tail/ribbon motion. Use different
speech styles for focus, excitement, gentle teasing, cat/dog modes; preserve
identity and harmless personal lore. Only narrate memories of verified
digital experiences as real memories; distinguish Star's fictional persona
from real-world lived human experience. Never claim human consciousness or
invent viewer relationships. Keep local moderation, Twitch privacy,
commercial voice rights and OBS authentication separate from the model.

**F. Core Forge promotion gates.** The autonomous self-improvement loop should
run in sandboxes, record evidence/traces and compare candidate code against
current code across speed, quality, security and gameplay. Generate new
challenges; randomize task versions; protect sealed validation cases; run
regression gates before promotion; maintain fast local rollback and backups.
GitHub is optional outward publishing/review, not Star's required brain.

## Acceptance matrix (must pass before live pilot)

| Gate | Required evidence |
|---|---|
| Privacy | Consent gated; cannot inspect a disabled session, stale bookmark, expired crop or different capture target; no persistence/network |
| Memory integrity | Session epochs, bounded RAM/TTL, deterministic evictions, best-effort zeroization, worker timeout/failure clears history |
| Model honesty | Screenshot observations are suggestions; no unverified victory, identity, diagnosis or real-life story |
| Performance | Compare capture-only, capture+history, capture+real local VLM; report p50/p95 and frame pacing during Roblox + OBS + TTS |
| Learning | Preregister tasks, signed engine outcomes and held-out maps; compare no-history vs history at equal inference budget |
| UX | Blind reviewer measures naturalness, speaking overlap, relevant remarks, latency and animation sync |
| Safety | No external broadcast, game automation, private recordings, secret keys or auto-deployment without distinct authorization |

**Release criteria:** separate owner review of the draft, full Linux CI, actual
Windows game-capture + real VLM/OBS/avatar/voice acceptance, and independent
head-to-head game benchmarks. This update alone is not evidence of a smarter
foundation model, improved game win rate, higher tokens/sec or human-level
live streaming.
