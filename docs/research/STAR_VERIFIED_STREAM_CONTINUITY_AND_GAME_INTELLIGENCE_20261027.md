# STAR — verified cross-stream continuity and next-generation gaming intelligence
**Research and implementation note • 2026-10-27 • proposed/off by default**

## Executive finding

The past ten increments added predictive calibration, context-specific practice,
game-skill transfer verification, frame-time safeguards, audio speculation and
nonverbal avatar attention. They improved *infrastructure*, not pretrained model
weights. The next distinct gap was longitudinal continuity. A streamer with an
animated face and expressive voice can still seem mechanical when it starts each
show with no grounded memory of what happened during a previous show.

This change adds a narrow, tested vertical slice: preserve a tiny, verifiable,
owner-curated account of Star's **own signed practice attempts** between sessions,
and make it available to the existing low-latency, moderated viewer-question path.
It is not a simulation of human childhood or evidence of sentience. No audio,
viewer message, account, model inference, public stream, or game controller is
introduced by the memory layer.

## 1. Research: why continuity matters, and why memory should be audited

1. **Generative Agents (Park et al., UIST 2023)** studies observation,
   reflection, retrieval and planning as parts of believable agent continuity.
   Ablations indicate these mechanisms matter to agent consistency. The paper
   also describes fabricated embellishments as a failure mode. A Star narrative
   should be generated from *specific verified observations*, not unconstrained
   summarization. Source: https://doi.org/10.1145/3586183.3606763
2. **LoCoMo (Maharana et al., 2024)** exposes temporal and causal mistakes in
   long-term conversational memory, even with long context or retrieval. Design
   acceptance: reject fake before/after ordering, cross-session contamination,
   and unsupported inference of game wins or feelings. Source:
   https://arxiv.org/abs/2402.17753
3. **Letta / MemGPT** demonstrates practical stateful agents with persistent
   storage and model-agnostic memory. We should use the architectural principle
   (a small indexed storage tier), not adopt another always-on external service
   or replace STAR's own local Core Forge. Source:
   https://github.com/letta-ai/letta
4. **GameWorld (2026)** standardizes 34 playable games and 170 tasks with
   state-verifiable outcomes. This is a more defensible skill-learning benchmark
   than unverified video-game narration. Source:
   https://gameworld-bench.github.io/
5. **Roblox OpenGameEval (October 2026)** stresses inspect-before-edit and
   executable scene/playtest checks for agent-produced content. Verified
   creation outcomes and verified gameplay experiences must remain separate.
   Source: https://github.com/Roblox/open-game-eval

## 2. Implementation in this change

`star/stream_continuity.py` implements `StreamContinuityVault`, a bounded
local SQLite journal of signed, previously witnessed PRACTICE actions:

- The existing GameplaySkillBank verifies each *exact* recorded event.
  Validation/holdout split, unsigned or altered trials, wrong versions, wrong
  action scopes and stale observations are rejected.
- An owner turns the subsystem on, opens a host-generated episode, records
  approved actions and seals the episode. Only SEALED episodes can be described
  in past tense. Crashed or disabled unsealed episodes are never exported.
- Stored events include only opaque hashed trial/episode IDs, symbolic
  game/action identifiers, success/failure and a Unix ordering stamp; no
  chat, user names, screenshots, key material, evidence receipts or raw game
  frames. Future model-generated stories cannot be input records.
- An independent host-only integrity key authenticates database rows. A
  missing/wrong key or a selected row with modified data causes silence,
  not partial disclosure. The actual gameplay signer remains separate.
- The database indexes episode timestamps and episode-to-event lookups and
  refuses records past its 4,096-entry cap. The visible history uses at most
  two summaries from the last 90 days and a fixed prompt-size ceiling.
- Broadcast-time host approval is required separately from storage approval.
  Broadcast output uses a second explicit curated action allowlist; the public
  packet carries only counts, latest outcome and an evidence-derived
  failure-then-success indicator. It must never imply a completed game,
  acquired mastery, emotion, or fabricated personal experiences.
- The owner can explicitly erase all the retained records and sessions. The
  embedding host must secure the SQLite path and persist the independent HMAC
  key outside the database. Host compromise is not solved by an HMAC.
- `StreamContextHost` retrieves the packet ONLY if the authorized host
  explicitly requests past experience with `include_past_experience=True`
  for a moderated viewer question (the default is False), then forwards
  it through `StreamBrainGovernor` to
  `StarStage`. The stage appends it at **USER/data priority** ONLY to an
  actual `viewer_question`. Game dangers, idle remarks and unrelated chat
  never receive previous-episode context.
- Disabled/new deployments retain the existing behavior: no vault required,
  no new permissions or background workers.

**Why this helps without inventing a person:** Star could truthfully recall
"A couple of attempts at that ledge went badly last session," because
the underlying practice ledger really contains those signed results. It
cannot claim human memories, romantic history, emotional suffering or wins
that are not represented in the source of truth.

## 3. Proposed next intelligence architecture (not implemented in this PR)

### Three clocks rather than one gigantic brain loop
- **Reflex loop: ~15–30 Hz target (measure first).** Read game/cursor state and
  recent button effects; perform low-risk authorized inputs, never reason from
  old screenshots. Strict per-frame action deadlines; drop stale work.
- **Strategic loop: ~0.5–2 Hz target.** Identify mechanic hypotheses,
  navigation subgoals, likely rewards and failure causes. Cache immutable
  world layout and reuse verified local state instead of reprompting whole
  games. If observation is incomplete, mark hypotheses unconfirmed.
- **Learning loop: offline.** Train against fresh procedural seeds, compare
  practice policies, run independent held-out tasks, archive both successful
  and failed experiments in local Core Forge. Prioritize high information gain,
  not repetitive easy achievements.

These are proposed update rates, **not measurements or promised throughput**.
The authorized Studio and game host should control play/pause/input.
Existing signed practice and GameTransferAuditor remain the evaluation gate.

### Skill semantics rather than memorized buttons
Represent a skill as preconditions, action timing, predicted consequence,
contraindications and observed confidence. Transfer across games only when
the relevant mechanic measurements match within error bounds. In particular,
"jump" does not transfer by name if gravity, air control or network latency
differ. Generate controlled A/B tests with identical seeds, then unseen
seeds. Separate practice tuning from independent final evaluation.

### Build quality: games that genuinely finish
A game-production pass should check map topology, anchor/weld integrity,
collision penetration, spawn-to-goal path reachability, Lua diagnostics,
animation transitions, text layout, VFX visibility, memory/frame time and
end-to-end completion. Replay the failed input sequence after each repair.
Roblox's April 9, 2026 Playtest Agent beta can check a subset of objective
conditions; don't claim coverage of complex multiplayer physics. Source:
https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767

### General knowledge, offline-first
Route claims to source-pinned notes with document version/date, freshness,
contradiction flags, confidence and a revocation path. Use independent
recall tests and cite evidence. Store practice/recollection results away
from hidden validation. Current knowledge should be retrieved only when
needed rather than inflated into a large permanently hot prompt.

## 4. VTuber naturalness: speaking, attention, and purposeful memory

**Voice**: LiveKit's March 19, 2026 adaptive interruption analysis emphasizes
why coughs, acknowledgments and genuine barge-ins cannot all be handled by a
single VAD threshold. Star's current turn-taking signals should not be
misrepresented as a deployed acoustic model. Benchmark true interruptions
and false stops with host-confirmed signals. Source:
https://livekit.com/blog/adaptive-interruption-handling

**Voice performance**: Kyutai's October 20, 2026 Pocket TTS release added small
English CPU models (~18M, ~7M and ~2M classes). Candidate for Star's 8 GB GPU:
measure quality, pronunciation, first audio, p95 chunk time and CPU contention
versus the existing TTS, *while the game is running*. Model size alone says
nothing about a convincing laugh or an acceptable stream. Source:
https://github.com/kyutai-labs/pocket-tts/releases

**Avatar**: Integrate the existing QuietAttention planner with Windows avatar
rig inputs after explicit owner approval. Coordinate audible mouth movement,
blink/focus, body lean and twin-tail hair physics. Live2D documents physics
FPS choices (default 60 fps) and warns that physics settings affect the
result; don't mistake tiny planner-cost microbenchmarks for rendered frame
times. Source: https://docs.live2d.com/en/cubism-editor-manual/physics-operation/

**Conversation**: Star should not narrate continuously. A compelling streamer
often stays silent during a difficult encounter, answers a question once,
acknowledges a correction and then returns to the game. External viewers'
assertions remain untrusted, and Star's profile should accurately identify
her as an AI persona. Keep opt-in cat/puppy modes expressive without
claiming biological senses or human history.

**Memory**: Use an explicit "remember previous attempts" affordance, not
hidden unsolicited recollection. The present implementation supports
verified action-history counts; future opt-in milestones can add curated
project releases and drawing/game achievements, but only with independent
completion receipts and on-air permission.

## 5. What should be measured next

| Metric | Proposed test | Why |
| --- | --- | --- |
| Game p99 frametime / 1% low | Same map, input replay, before/after TTS workload | Protect actual gameplay |
| Voice first-audio p50 / p95 | Exact same transcript + hardware load | Believable response pacing |
| Stream interruption precision/recall | Authenticated human-labelled overlap clips | Avoid robotic stop/start |
| Memory consistency | Contradiction/temporal questions across 20 sessions | Catch fabricated stories |
| Privacy leakage | Holdout, private-action, tampered-DB, wrong-key fixtures | Never publish restricted facts |
| Playable objectives | New maps, blind seeds, actual run-to-end proof | Real game-building quality |
| Real-world latency | End-to-end Windows input->observation->speech | Synthetic Python timing is insufficient |

**Local synthetic retrieval microbenchmark (Linux, Oct 27):** after recording
40 synthetic signed practice events in a single SQLite episode, 2,000 cached
in-process `public_packet()` reads measured **0.645 ms median / 0.828 ms
p95 / 1.978 ms maximum** on the connected development machine. This is a
single-process CPU/SQLite measurement, not a comparison against a prior model,
not a Windows/OBS timing result and not evidence of faster neural inference.

Do not promote a candidate merely because one benchmark gets faster:
compare matched tasks, include cold starts, mixed context lengths, game FPS,
VRAM peak, speech quality and independent holdouts. See llama.cpp SPEED-Bench:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## 6. Windows acceptance / rollout instructions

1. Keep this PR draft and opt-in. Confirm the base branch and all stacked
   predecessors have passed review; do not merge automatically.
2. On a local private data volume, create a continuity database and use a
   separate >=32-byte random HMAC key from the authorized host's local
   secret manager. Do **not** put secret bytes, examples of real keys,
   player IDs, private clips, or viewer transcripts into GitHub.
3. Authorize `StreamContinuityVault.enable()`, then issue a unique,
   host-generated episode ID. Record only owner-approved signed practice
   events after the game host's independent verification.
4. Seal the episode only when its actual lifecycle completes.
5. In a second session, instantiate `StreamContextHost` with the optional
   continuity vault and a separate `public_continuity_action_ids` allowlist.
   Supply `include_past_experience=True` only for a specifically requested,
   moderated previous-experience question. Verify facts appear in that viewer
   QUESTION but not in unrelated questions, game danger, comments,
   unmoderated prompts or disabled sessions.
6. Test reset/forget, corrupted DB, process restart, old data, wrong
   game/version, missing playback acknowledgment, full GPU load and headset
   privacy. Owner can withdraw streaming consent without erasing private
   local practice immediately; forgetting requires an explicit purge.
7. Test real Windows OBS/voice/avatar/Roblox capture with synthetic inputs
   before letting a live audience interact. No auto-go-live.
8. Only retain/publish the change after paired evaluation proves at least
   equivalent factual quality, latency, stream FPS and consent behavior.

## Scope and limitations

This PR does **not** retrain the neural model, teach a new game by itself,
capture any Windows audio/video, install model weights, start a broadcast,
guarantee human-quality speech, or prove consciousness. It improves a
particular kind of source-grounded continuity and offers a measurable path
to more convincing AI VTuber interactions. STAR's internal Core Forge should
remain the authoritative local self-improvement system. GitHub is an
optional external review/export route, not its neural memory.
