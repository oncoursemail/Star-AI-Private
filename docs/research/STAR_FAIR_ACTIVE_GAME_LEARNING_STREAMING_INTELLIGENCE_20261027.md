# Star AI: evidence-guided practice, gaming intelligence, realtime VTubing and local speed

**Research and implementation record — 2026-10-27.** Scope: local-first Star Core Forge,
optional GitHub publication; 8 GB VRAM gaming/streaming machine; private/authorized
game environments; strictly independent practice receipts and held-out evaluation.

## 1. The engineering change actually delivered

The existing Star AI modules already had (a) prospective, immutable game-success
forecasts, (b) independently signed game outcomes, (c) per-context overconfidence
diagnostics, (d) owner-curated prerequisite ladders, and (e) a fair portfolio
scheduler across distinct games. They were **not connected at the decision point**.
Thus Star could identify a weak mechanic, but the offline curriculum still chose
the next game solely by exposure count, historical trial count, and difficulty.

This change extends `GamePortfolioPractice` with two **optional** host-only
constructor arguments: `prediction_lab` and `prediction_model_id`.
Without them the scheduler behaves as before. With both present, and only if
the independent prediction lab is enabled, it:

1. Computes currently **eligible** per-game practice actions using the unchanged
   existing authorizations, mastery gates, failure diagnosis, cooldown and
   FPS/audio/VRAM/headroom checks. No streaming/live practice is admitted.
2. Finds games tied for **fewest practice offers**, preserving balanced exposure.
3. Consults no more than ten recent **signed-practice-only** mistake cards
   for each tied, eligible game; matches **game/version/model/objective/
   situation/action** exactly. No viewer text, confidence assertion, hidden
   held-out outcomes, or another game's results are scheduling evidence.
4. Breaks *only those fairness ties* in favor of forecast mistakes (Brier
   error weighted by sample support). Falls back to the existing coverage /
   trial-count / difficulty / stable-ID ordering if there is no match.
5. Fails conservatively if an opted-in evidence store breaks, rather than
   treating empty or corrupted data as a reason to act.
6. Emits only aggregate counts for focus-routed selections and diagnostic
   failures; never emits signer keys, result digests, run IDs or screenshots.

**Important:** This is *resource-safe, evidence-guided practice scheduling*,
not neural weight training, a game-playing controller, an improvement in
foundation-model IQ, or an action permit. The host still must authorize each
private Studio action and independently score and sign the actual result.
A high prediction error alone is not mastery and may reflect poorly calibrated
confidence, a changed mechanic, or a noisy evaluator.

### Invariant worth preserving

`offer_count` remains the primary sorting key. Otherwise a single game with a
persistent prediction error could monopolize attention and make "Star learns
many games" become "Star overfits one game." Likewise, the prerequisite ladder
decides whether a repeated failure requires a **diagnosis**, not more retries.
An uncertified confidence adjustment is never permitted to bypass either rule.

## 2. What current research says, and what it does *not* say

**Voyager (May 2023)** demonstrated the value of an automatically constructed
curriculum, executable reusable skills, environment feedback and self-verification
in Minecraft. The transferable idea for Star is the architecture, not the
specific headline results or a promise that prompt engineering alone will
produce a superhuman player.

- Paper: https://arxiv.org/abs/2305.16291
- Contrast for *building*, not just play: VoyagerVision (June 2025),
  https://arxiv.org/abs/2507.00079. It reports significant limits when
  verifying more complex Minecraft structures. Visual feedback must be coupled
  to structure-aware checks, not treated as a perfect aesthetic judge.
- Game-building tool reality: Roblox introduced Studio built-in MCP and
  automated playtesting in March–April 2026. Third-party agents can inspect
  the DataModel, run authorized playtests and inspect logs; the dedicated
  playtest subagent was announced as a **beta**, not unlimited access.
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
  https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
  https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

**Result for Star:** Train curricula against the *specific* local game version.
Do not pool a race input with a parkour input and conclude skill transfer.
When Star predicts a 90% success rate and independently fails repeatedly,
diagnose the mismatch. When the skill has no trusted observations, practice a
small, curator-approved first step instead of assuming competence.

## 3. Three clocks for a gaming VTuber

A single huge reasoning process should not own the game loop, avatar expression,
chat, world memory and offline practice at the same priority:

| Lane | Goal | Evidence and deadline | When overloaded |
| --- | --- | --- | --- |
| Game controls | Maintain real game responsiveness | Current player state, fresh frame/action permit and host clock | Drop slow vision request; never replay expired input |
| Speech + face | Natural first audible response and accurate lipsync | Audio-device playback cursor, real viewer-turn state, avatar-generation epoch | Silence or short response; never animate text that was not played |
| Learning + creation | Improve future skills, knowledge and Roblox assets | Signed practice results, executable Studio tests, visual/geometry QC | Pause on live stream, FPS loss or GPU/CPU pressure |

For Star's 8 GB GPU, *latency isolation* is as important as model throughput.
Model selection must be measured using actual game frame presents, speech
backlog, GPU memory peaks and first audible output. "Tokens/s increased"
does not imply "the stream feels faster" if frame times or audio worsen.

The official llama.cpp server architecture shares batches across compatible
slots and warns that heavyweight postprocessing on the main slot thread
reduces throughput. The best default is therefore **cache-stable prefixes**,
limited active slots and per-lane compute admissions—not maximal parallel
agents all decoding at once. Details:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md

### Concrete local benchmark

Use Star's existing `stream_realtime_benchmark.py` matched A/B harness.
For each **unchanged** game scene, interleave baseline and candidate runs with
the same prompt family, warmed models and CPU limits. Record minimum 120
presented game frames per run, first **audible** PCM latency, peak GPU MiB,
and whether speech truly finished. Exclude neither interrupted runs nor bad
FPS from final reporting: label failures explicitly.

Measure candidates separately:
- Cached stable system/persona/context prefix vs regenerated prefix.
- One quick local model for short reactions vs full planner on every message.
- One concurrent vision job vs multiple overlapping jobs.
- Speculative decoding configurations vs baseline, with draft-token
  acceptance **and** CPU/GPU co-contention measured.
- CPU voice model vs previous voice path while a game is rendering.

Only recommend a manual pilot if matched trials show genuine first-audible
latency improvement without meaningful 1%-low FPS regression, speech
completion regression, or VRAM over-budget. No theoretical speedup counts.

## 4. Human-natural Star on stream: evidence + timing + expressiveness

A compelling character is not created by continuously talking, pretending to
have had a human childhood, or emitting unsynchronized animation loops.
Star can have a fictional 21-year-old character persona and consistent
playful identity **while remaining disclosed as an AI character**.
Her relationship with chat should be caring and non-manipulative, not a
simulation of real human memories or unearned personal experiences.

LiveKit's 2026 discussion of voice-agent turn handling distinguishes voice
activity from endpointing and meaningful interruption. Model-based turn
detection, echo cancellation and listening during TTS matter more than simply
lowering a fixed silence threshold:
https://livekit.com/blog/turn-detection-and-interruption-handling
https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection

Star's already-existing streaming components should be wired so that:
- Chat question queues accrue fairness without interrupting imminent danger.
- A brief "yeah"/chuckle is not automatically a new instruction to answer.
- A **confirmed spoken** line may trigger a small smile, blink, body lean or
  laughter cue. An unplayed/failed speech line must not generate an "already
  said it" memory or lip motion.
- Surprised, playful, sleepy, cat and puppy modes are alternate expression
  palettes, not generators of invented gaming achievements.
- Real gameplay attention allows 5–15 seconds of purposeful silence rather
  than robotic ongoing narration during demanding moments.
- All gestures have attack/decay and a neutral interrupt reset; reduced
  motion remains owner-configurable.
- Star's twin-tail hair, ribbons, ears and mouth should use **artist-rigged
  Live2D physics** with well-bounded controls instead of synthetic uncontrolled
  offsets. A neutral expression must remain comfortable for long sessions.

VTube Studio's documented custom-parameter injection API can accept an
authenticated host's face/motion values; it does **not** create a professional
rig or synthesize an expressive voice by itself:
https://github.com/DenchiSoft/VTubeStudio

### CPU voice research, not an untested deployment claim

Kyutai Pocket TTS advertises October 2026 English options around 18.2M,
6.9M and 1.9M parameters and supports streamed CPU audio:
https://github.com/kyutai-labs/pocket-tts

These model sizes are *candidates*, not a reason to replace Star's voice:
record blinded normalized-volume voice evaluations for clarity, natural
laughter, playful expressiveness, accent stability, punctuation and
long-form narrative coherence, plus real Windows CPU/GPU contention.
A faster small model that sounds less natural or glitches when interrupted
must fail the quality gate. Prioritize accurate timing and voice identity.

## 5. General knowledge, self-reflection and continuity

Star should maintain separate evidence types:
- **Published reference knowledge:** sourced, dated, license-aware, revocable.
- **Own observed game experience:** signed *practice* episodes or confirmed
  playback, scoped to a version and observation window.
- **Uncertain hypotheses:** predictions, confidence and falsification tests.
- **Owner-approved fictional persona:** consistent interests and preferences,
  explicitly distinct from real past-life experiences.
- **Private owner/project memory:** local and never on-air absent specific
  public permission.

Never treat an AI-generated paraphrase as independent corroboration. Summaries
can be cached for speed, but cache invalidation must account for game version,
source revision, expiry, publication consent and model build.

Host-only **micro-reflection after each verified failure** should store:
forecast, observed outcome, state mismatch, probable reason and next small
hypothesis. Avoid pretending it has emotions or senses it did not observe.
Require at least two genuinely distinct successful challenge examples before
marking a new mechanic as reusable, then test it on new levels.

## 6. Make Roblox builds fail visibly before publishing

A builder with a beautiful concept can still ship a broken or "AI-slop"
experience. Add explicit verification lanes before release:

1. **Structural:** no unanchored architectural walls, intersecting collision
   volumes, missing fixtures, wrong transforms/scale, unreachable doors,
   broken hierarchy or out-of-bounds props.
2. **Functional:** private playtest can start, move, complete an objective,
   purchase/interact, reset and recover from checkpoint. Test *end to end*.
3. **Animation/VFX:** valid skeleton/IK grips, motion curves, material
   assignments, transitions, event timing, particle lifetime and camera cuts.
4. **UI:** native Roblox instances, correct safe area/gamepad/touch navigation,
   responsive font sizing and consistent visual hierarchy; reject accidental
   overlap and unusable buttons.
5. **Visual:** paired reference/render screenshot review by an independent
   visual checker **plus** structural tests; a plausible render does not prove
   physical integrity.
6. **Performance:** compare 1%-low FPS, peak memory, network bandwidth and
   streaming latency in actual game scenes.

Store reversible diffs and verifier evidence inside **Star Core Forge**;
GitHub is optional publication, not the autonomous agent's mandatory runtime.
Any autonomous change with regressed independent tests must roll back.

## 7. Pre-registered evaluation of this particular code change

**Hypothesis:** given multiple equally under-exposed eligible game tracks,
the focus-enabled scheduler spends one slot on an evidence-backed weak mechanic
earlier than the coverage-only baseline, while never reducing the diversity
floor or bypassing cooldowns.

Local simulated unit/integration acceptance criteria:
- A scoped eight-trial overconfidence pattern changes the **tied** selection.
- After that selection, another game has priority until exposure rebalances.
- Wrong action, old evidence, other model ID, disabled lab and independent
  validation outcomes do **not** influence routing.
- Twelve repeated signed failures trigger manual diagnosis, not more retries.
- Live stream, low-FPS, unauthenticated game host and expired reservation
  remain independently protected.
- A closed diagnostics database defers explicitly.
- All emitted offers remain `authorized_to_play=False`.

**External, not yet run:** Compare 20+ matched episodes across at least four
different games and hold back unseen levels/versions. Use independent evaluator
success rate per game, trials to skill threshold, diversity of game coverage,
recovery after game mechanics change, latency/1%-low FPS and genuine playback
latency. Report confidence intervals and adverse cases. No promotion on
practice-only diagnostics or cherry-picked successes.

## 8. Next implementation priorities

**P0: real Windows pilot:** capture frame presents and GPU/CPU budget on
Star's dedicated gaming machine; bind authorized Studio input, actual audio
playback and avatar websocket. Add a physical stop/release watchdog independent
of Python task cancellation. Verify no unplayed speech motion or stale key
dispatch even when workers block.

**P1: reusable skills:** store verified action primitives for jumps, obstacle
timing, camera movement and scene interactions; parameterize by exact game
version; verify on unseen levels before cross-game transfer claims.

**P2: voice naturalness:** run interrupted duplex audio tests and human listening
evaluation while streaming a representative game, measure p95 time to first
audible speech and audible-to-mouth skew.

**P3: real speed:** benchmark prompt-cache stability, small speech models,
speculative decoding and overlapping background workers against an FPS/VRAM
guardrail on the actual computer. Prefer CPU/RAM optimizations that remain
useful if the GPU is replaced.

**P4: broad knowledge + making games:** cite/license public references, add
interactive geometry checks, visual reference comparisons and end-to-end
playtests; require reversible, independently passed changes before promotion.

**P5: Star Core Forge:** signed local experiment manifests, repeatable builds,
quarantined model and hardware workers, semantic code diffs, automatic failure
bisect and fast rollback. Keep experimental features OFF by default.

## 9. Limits and publication cautions

The integration tests use simulated private games and trusted fake signing
keys. No new GPU kernel, model, voice, Roblox map, Live2D rig or live stream
was installed in this change; **no faster tokens/sec, superhuman reasoning,
human consciousness or gameplay mastery is demonstrated**.

GitHub currently reports `Star-AI-Private` as **publicly visible** despite
the name. Avoid publishing private memory, speech/video, user identities,
signer secrets, models, or hidden test answers. Leave the PR draft and stacked
on the exact previously tested base; do not silently merge or deploy.
