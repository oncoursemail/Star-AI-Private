# Star AI: Verified Autonomous Learning Without Stranded Compute
Date: 2026-10-26 (America/Chicago; implementation completed October 27 UTC)
Status: research + tested offline control-plane patch; NOT a deployed streamer or a demonstrated model-speedup
Branch: feat/knowledge-practice-worker-quarantine-20261026

## Critical integration finding

The offline KnowledgePracticeHost already schedules reviewed, source-pinned
knowledge questions and independently verifies signed grades. Its
asyncio.wait_for limits callback duration, and disable() cancels the active
coroutine, but **neither guarantees termination of an external GPU inference
worker or an independent grading process**. A stale worker can overlap with
the next practice session, consume VRAM, or interfere with a game or stream.
Further, disable() immediately followed by enable() can restore the enabled
flag while an old operation is still awaiting; an unchecked old callback
must not become eligible for a fresh session.

This patch gives learning the same conservative workload lifecycle recently
added to StreamVisionHost:

- Increment a private generation/epoch every time knowledge execution starts
  or is revoked; a result produced for another epoch cannot be graded.
- Refuse a new session while an old asyncio task is running, or while its
  external worker is unconfirmed. Enable cannot erase quarantine.
- Quarantine after timed-out or canceled inference/grading operations. A
  deadline, Python cancellation, or model claim is not physical stop evidence.
- Require a matching host-only stop ticket and
  acknowledge_workers_stopped(stop_ticket=ticket, workers_stopped=True)
  after the embedding application has joined/killed its processes; no
  model-facing tool is given that ability. Acknowledgment is refused if
  the earlier task is still active or the session remains enabled.
- Continue canceling the planner's reserved question in finally; never
  promote unsigned, future-dated, stale-source or late answers.
- Report only anonymous counters and worker state, never prompt/answer text.
- Keep all features disabled by default. No network, model, grader or video
  input is supplied by this patch.

This is a safety/correctness improvement, not evidence of higher base-model
intelligence, a new vision model, improved gaming, or faster tokens/second.

## Evidence and priority-ranked practical experiments

### 1. Think on three time scales

**Reaction loop (16-50 ms budget when available):** cheap host-trusted
movement/UI/game-state predicates and audio/animation control; NEVER block
the game render loop on large-model inference. Keep emergency stop separate.

**Interpretation loop (about 250 ms to several seconds):** rate-limited
visual snapshots through StreamVisionHost and short context-grounded speech.
Use novelty plus fresh CPU/GPU/FPS/audio telemetry; an inference worker that
misses its deadline is quarantined until confirmed dead.

**Offline deliberate loop (seconds to minutes):** source-pinned knowledge
practice, independent grading, game-mechanic A/B trials, best-of-N game
building, screenshot QA, skill transfer, and Star Core Forge experiments.
This loop yields immediately when live, gaming headroom is insufficient, or
audio delay rises. Never run automatic self-updates on a live stream.

The dispatcher should choose among modes by measured deadline headroom,
not model-predicted FPS or an arbitrary large 'intelligence' setting.

### 2. Make actual general-knowledge gains falsifiable

Use Star's reviewed source store and KnowledgePracticeHost with fully separate
offline inference and grader processes. Build a pre-registered curriculum
covering logic/math, verified scientific facts, software engineering, game
mechanics, Blender, animation, writing, geography and everyday reasoning.
Each question pins an editorially approved source revision and timestamp.
Practice cards and grading answer keys must be physically separated from
held-out validation; prevent grade receipts or answer keys from entering the
model-visible prompt.

Track baseline vs candidate *on unseen prompts*: accuracy, exact-match only
where appropriate, calibrated uncertainty, citations and freshness, answer
latency, and refusals. Keep model/version hashes, quantization, sample seed,
temperature, retrieval toggle and test-set IDs stable. A practice scoreboard
can establish progress on that scoreboard; it cannot alone demonstrate that
underlying neural weights became smarter. Persistent memory retrieval and
tool use can make Star more capable without changing neural weights.

When a card is missed, generate a new concept-level practice variant for
independent review, rather than memorizing the held-out answer. Generalize
using transfer tasks after 1 day and 1 week, not only same-session repeats.

### 3. Improve real game learning instead of narrated success

Use trusted host observations at pre-authorized capture rates. Build a game
mechanic record with: game/version, situation, action primitive, observed
outcome, independent evidence hash, hypothesis, alternatives, failure modes,
and confidence. Compare two actions in matched initial situations using
GameMechanicProbeLab, and evaluate progress on previously unseen maps and
new seeds, with negative transfer tracked. Skill-bank success is for a
particular *attempt*, not a claim Star has mastered a game.

Game-control policy should remain sandboxed to approved game sessions and
respect game rules. Do not ship anti-cheat bypass, background spying,
credential interception, account sharing, or hidden multi-account bots.

**Why real Studio playtests:** Roblox announced a built-in Studio MCP server
on March 5, 2026 and a Playtest Agent beta on April 9; on April 15 Roblox
described an agentic plan/build/test loop with code, data-model, log and
avatar-based testing. Star should inspect actual meshes and object relations,
run a character through interactions, compare screenshots to explicit
reference goals, and check structural + visual quality independently.
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

Suggested game-maker acceptance: no missing wall connections; no unintended
overlaps or floating props; tested collision layers, scale consistency,
texturing (UV/stretching), lighting and PBR compliance; UI readability and
responsive scaling; server-client correctness; checkpoint and respawn;
no unexpected errors; consistent gameplay on two FPS profiles.
Output a per-failure reproducible scene coordinate, screenshot reference
and test instruction; do not label an uninspected scene 'polished'.

### 4. Faster local inference without lying about speed

For 8 GiB VRAM, keep game-rendering GPU reservations separate from
model-inference budgets. Start with measured quantization/model-routing
baselines; then A/B test (a) llama.cpp n-gram speculative decoding,
(b) a small draft model when it does not overfill VRAM, (c) prompt prefix
KV reuse limited to safe same-context scopes, (d) shorter context where
evidence retrieval permits, and (e) CPU-scheduled speech.

llama.cpp documents draft-model and n-gram-based speculative decoding and
reports acceptance statistics. Acceptance is workload-dependent; a technique
can be slower if overhead exceeds saved verification steps. Speculative
decoding does not create new intelligence.
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

On October 20, 2026, Kyutai released Pocket TTS v4 with additional English
18M/7M/2M variants (some experimental). Small CPU models can be tested
without automatically taking gaming VRAM; evaluate real voice naturalness,
pronunciation, laughter and cold-start latency, not just generation speed.
Do not copy another streamer's recognizable voice without permission.
https://github.com/kyutai-labs/pocket-tts/releases
https://github.com/kyutai-labs/pocket-tts

**Paired benchmark design:** for each preset, use at least 20 randomized
matched gameplay segments per game/version/scene. Capture actual GPU VRAM,
game frametime p99/1%-low FPS, first-*audible* voice latency p50/p95,
speech completion fraction, ASR interruption latency, model first-token
and sustained tokens/sec, CPU load and knowledge/answer quality. Count
timeouts and failures as failures rather than dropping slow trials.
Publish paired confidence intervals; require independent CI before
suggesting a human-approved rollout. Benchmark on the actual Windows
streaming PC under simultaneous game + avatar + speech, not Linux idle GPU.

### 5. More natural, attentive VTuber conversation

Star should have a coherent fictional persona, expressive chibi face, warm
spoken voice, humor, boredom/curiosity-style behavioral simulation and
persistent authorized preferences, but identify as an AI. Do not invent a
human childhood, relationships or lived experiences as literal facts.

Build a **conversation floor manager**:
- prioritize game-critical attention and actual viewer interruptions;
- backchannel briefly only when it improves the exchange, with silence
  during demanding moves;
- react to host-verified game events rather than hallucinated victories;
- let ordinary questions age fairly instead of being starved by reactions;
- manage humor, laughter, pitch/prosody, breath timing and acknowledgments
  with voice-first interruption recovery and sample-aligned lip sync;
- distinct cat/puppy modes must change animations and playful sounds
  without changing the base identity or privacy rules.

VTube Studio exposes a public WebSocket API for hotkeys, tracking parameters,
items and event notifications. Prototype synchronized eye motion, ears, tails,
hair, blinking, lean, and mouth visemes with actual audio playback clocks,
not model text clocks. Treat speech and avatar leases as revocable together.
https://github.com/DenchiSoft/VTubeStudio

Evaluation: blind human listening ratings on 20 annotated clips, alongside
delayed-question coverage, hallucinated-event rate, interruption success,
overlap/echo failures, frame p99 and fraction of speech genuinely audible.
Be explicit that a score on scripted clips does not prove human-level
conversation or consciousness.

### 6. Star Core Forge autonomy and honest self-model

Build an internal experiment registry with an immutable candidate ID,
code/model/artifact hashes, evaluation dataset pin, metrics, resource budget,
reversible deployment action and owner review. Promote only with a measured
win against a frozen baseline, safety gates, complete CI, and an automatic
rollback path. Do not silently modify a production speech/game worker while
it is live. GitHub is an optional publishing/review mirror: Star's local
version history, test evidence and backups remain authoritative.

Her functional self-model can track capabilities, uncertainty, commitments,
observed experiences, past decisions, emerging interests and long-term
projects. This is useful continuity and behavior, not scientific proof that
the system is conscious or a human legal person.

## Acceptance and nonclaims for this patch

1. Unchanged normal offline question -> independently signed grade accepted.
2. Timed-out inference OR grader -> no accepted grade; worker quarantined.
3. A false stop confirmation, old stop ticket, or premature confirmation -> quarantine retained.
4. Stop acknowledged after host has truly terminated workers -> fresh
   opt-in session possible; previous outputs remain invalid.
5. disable/enable race while callback ignores cancellation -> refused until
   old task actually ends and host confirms stop.
6. No prompts, answer keys, screenshots, microphone audio, private knowledge,
   HMAC secrets or hidden tests are ever published.

This patch neither starts external processes nor validates host honesty:
the embedding Windows/Linux agent must implement physical worker management,
including process-tree termination and join, and call the acknowledgment
only after verified termination. Until that adapter and real device tests
exist, report *control-plane readiness*, not an end-to-end autonomous streamer.
