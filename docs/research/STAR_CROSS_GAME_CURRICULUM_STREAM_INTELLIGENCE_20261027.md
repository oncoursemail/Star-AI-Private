# STAR: cross-game learning, faster local intelligence and natural gaming VTuber
**Research and implementation note — 27 October 2026**

## Scope and evidence standard

STAR is a local-first experimental AI application, not a newly trained frontier model
and not a conscious human. This patch improves *practice allocation*, not neural
network weights, real-time gameplay skill, or voice quality. An independent Studio
playtest host, observations, signing service, and a full Windows streaming rehearsal
are still prerequisites for on-device autonomy. Treat all speed numbers below as
candidate goals until measured on the owner's hardware.

Existing pieces inspected before design:
- `star/game_learning_ladder.py`: signed practice evidence + bounded single-game DAG.
- `star/active_practice.py`: expiring one-action reservations + exact signed run ID.
- `star/gameplay_skill_bank.py`: split-aware signed practice and held-out records.
- `star/game_mechanic_probe_lab.py`: paired exploratory arm comparisons.
- `star/studio_practice_runner.py`: local, explicitly approved Studio evidence/input
  bridge, with a single action per private episode.
- `star/stream_brain_governor.py`, `star/stream_stage.py`, `star/stream_turntaking.py`,
  `star/stream_motion.py`: GPU, speech, turn-taking and expressive animation controls.
- `star/knowledge_practice_host.py`: reviewed general knowledge practice host.
- `star/stream_realtime_benchmark.py`: paired real-time stream measurement.

### Implemented in this patch

`star/game_portfolio_practice.py` coordinates 2–12 distinct, owner-curated
GameLearningLadders with a private ActivePracticePlanner. It:
1. Requires portfolio AND per-ladder opt-in; all capabilities default OFF.
2. Only recommends offline practice with fresh host telemetry, adequate free VRAM,
   game frame rate, and low audio backlog. Never trains during a live stream.
3. Balances practice *offers* across different games instead of letting the easiest
   or most instrumented game dominate all learning time.
4. Reserves exactly one action tied to an unpredictable, versioned, scoped run ID;
   returns no OS key, Studio token, moderation bypass, or input authority.
5. Only counts a run when the existing ledger confirms the exact independent
   signed PRACTICE evidence. Validation/holdout records are never used for
   curriculum selection or positive progress.
6. Applies per-game cooling-off after unverified or timed-out attempts. Repeated
   missing evidence produces a manual diagnostic block instead of infinite retries.
7. Rejects wrong tickets, stale sessions, fake receipts, backward clocks, and
   replayed completion assertions. Expired reservations release the scheduler.
8. Keeps its runtime counters anonymous. No receipts, names, keys, transcripts,
   screenshots, chat messages, player IDs, or exact run IDs enter telemetry.
9. Leaves all physical input and playtest success evaluation under the trusted host.

**What this unlocks:** a Studio host can ask for an appropriate, *different*
practice game next without sharing a trained model's authority over a game or
sacrificing streaming FPS. It has not yet learned these games.

### Why broader practice is evidence-grounded

- *Voyager* (NeurIPS 2023) combines open-ended curriculum, executable skill
  library, and environment-feedback repair for Minecraft; it is a useful pattern
  for Star's owned local skill bank, but its published results cannot be
  transplanted to Roblox or to the owner's GPU without new experiments.
  Primary paper: https://arxiv.org/abs/2305.16291 .
- Roblox's **OpenGameEval** (submitted 1 October 2026) benchmarks 13 frontier
  models on 84 Studio tasks across scene and script changes. Agents' exploration
  behavior correlates with success; inspect the state before making edits.
  A benchmark pass is not proof of creating an enjoyable finished game.
  Primary paper: https://arxiv.org/abs/2610.02563
  and code: https://github.com/Roblox/open-game-eval .
- **CEGame-Bench** (19 October 2026) evaluates long-horizon complete-game
  creation across Roblox, Unity, Unreal, Godot and Defold. Engine integration
  success can coexist with poor playable completion. For Star, evaluate full
  loops, checkpoints, save/rejoin, and actual human-input playtests separately.
  Paper: https://arxiv.org/abs/2610.26098 .
- Roblox's **Studio MCP/Playtest Agent** is an explicitly Studio-local,
  beta-dependent option, not permission to control public clients.
  Announcements: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
  (5 March 2026) and
  https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
  (9 April 2026).

## Next integration: independently verifiable game learning

**Private game trial contract**

Trusted host, not language model, owns `studio_id`, authenticated local input
port, focus, playtest state, frame capture, watchdog, trusted monotonic clock,
key-up confirmation and outcome signing. The host calls
`GamePortfolioPractice.reserve(..., telemetry=snapshot)`. For a
`practice_candidate`, it checks owner scope and the game already opened for the
requested version, then delegates *one* playtest action to StudioPracticeRunner
or StudioPlaytestHost. The evaluator checks observed state transition, writes
a signed PRACTICE trial with the *exact* `expected_run_id`, and only then calls
`finish(..., host_reports_recorded=True)`. All failure branches report false.

**Important implementation gap:** The per-game StudioPracticeRunner still
accepts one ladder, so the Windows host must coordinate switching private
game environments between portfolio offers. There is no automatic game launch
or Studio multi-instance provisioning added in this PR. Do not wire portfolio
output directly to arbitrary keyboard or public-player controls.

**Suggested target fixture games**, curated and testable on owned content:
- Obby: cross a moving platform, identify last verified checkpoint, recover
  from a deliberate fall and complete a new jump sequence.
- Arena: locate a safe cover position, predict a moving target and survive
  30 seconds in a synthetic bot-only test arena.
- Racer: learn brake/turn timing across unseen map seeds, complete laps without
  resets, transfer control calibration to a different vehicle.
- Builder: inspect a Studio scene, reconstruct scene hierarchy, identify
  colliding or missing props and verify an edited version in play mode.
- Horror: navigate a synthetic objective under limited visibility without
  reading privileged engine state.

**Actual acceptance** must include held-out levels (seed IDs never present in
training), randomly assigned test order, matched hardware budgets and measured
success deltas by game. Track per-game success, median action count, collision
errors, time-to-objective and input faults. Compare the current baseline with
the candidate using bootstrap uncertainty intervals, avoiding pooled metrics
that hide a failing game. An increase in selected practice tasks is **not**
an increase in intelligence.

## Faster inference: measure the whole stream, not just tokens

STAR owns 8 GB GPUs in its planned gaming environments. A larger language model
may increase answer quality but damage FPS or voice latency if it contends for
VRAM. Prefer a workload-sensitive two-tier design.

**Fast lane (tight deadline):** low-cost event classification, owner interrupts,
very short safety/factual acknowledgments, image-change metadata, turn-taking.
Always keep speech/device functions and input watchdog on independent resources.

**Deep lane (interruptible):** longer planning, grounded internet research,
offline tool-driven Roblox Studio inspection, lesson consolidation, simulation,
A/B model evaluation, and autonomous challenge generation. Default not live.

**Proposed performance experiments:**
- Quantized target-model inference, quantization quality parity and per-task
  accuracy, not only tokens/sec.
- llama.cpp speculative decoding (draft model, n-gram, MTP and EAGLE3 where
  compatible). Compare real emitted tokens/sec, draft acceptance, p50/p95 time
  to first token, VRAM consumption, and FPS; never assume a draft helps.
  SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
  (retrieved October 2026).
- Stable system/context prefixes with prompt/KV reuse under privacy scoping:
  segregate caches by owner, project, model ID, context revision and session.
  Evict when knowledge/permissions change. Do not allow one user's private
  cache to become another viewer's context.
- Per-model admission based on live CPU utilization, VRAM headroom and game
  frame pacing. Turn off optional vision while the game stalls.
- On Windows, measure first-*audible* PCM, not just first TTS packet or text
  generated, and require completion rates and comparable answer correctness.
- Alternate CPU TTS against current voice under the same gameplay scene,
  audio buffering and CPU scheduling, including microphone feedback.

Kyutai's **Pocket TTS v4.0.0 (20 October 2026)** added new English models at
18.2M, 6.9M, and 1.9M parameters. **v4.0.1 (21 October 2026)** fixed small-model
pronunciation and updated default model mapping. Its README describes CPU
operation; any vendor speed claim is not a STAR benchmark. Begin with
`english_18m_2026-10` and listen for laughter, accents, word timing, breath
artifacts and unnatural sentence joins before accepting a tiny model.
Sources: https://github.com/kyutai-labs/pocket-tts/releases and
https://github.com/kyutai-labs/pocket-tts .

**Release gate:** significant end-to-end first-audible latency/FPS advantage,
non-inferior speech quality in blinded comparisons, no new stutters,
no leaked prompts, and clean rollback. Never sacrifice game FPS for a tiny
token/s win.

## VTuber: expressive *and* genuinely game-attentive

The goal is a coherent streaming personality, not pretending a machine is a
human person or inventing lived experiences. Star's real known practice and
broadcast-observable game events can inform jokes and callbacks. Fictional
character lore should be distinguishable from factual accomplishments.

**Conversation floor:** A game battle should permit useful silence. A genuine
authenticated owner barge-in wins over generated commentary. A viewer's brief
acknowledgement, background music, cough or keyboard sound should not trigger
premature cancellation. LiveKit's **adaptive interruption handling**
(19 March 2026) uses acoustic features to discriminate these; Star's current
offline VAD gate does not include LiveKit's learned model or its claimed
measurements. Test using consented synthetic interruption/backchannel fixtures.
See https://livekit.com/blog/adaptive-interruption-handling .

**Emotion layer:** Map independently observed wins, surprises, danger and
curiosity to short, calibrated expressions. A natural streamer:
- mostly focuses on difficult game moments rather than talking nonstop;
- delivers a specific little delighted reaction *after* a real success;
- can say 'I don't know' about a new mechanic and test it, rather than bluffing;
- acknowledges a viewer without abandoning the current gameplay task;
- tells small, sourced anecdotes from a verified, consent-approved episode;
- sometimes uses distinctive cat/puppy sounds, but not repetitive canned jokes.

**Avatar:** Preserve Star's accepted soft chibi black-and-gold direction,
amber eyes, indigo-to-gold twin tails, star clip and responsive eyebrows.
Wavy physics should be simulated in the Live2D/renderer pipeline; scripted
cue overlays should not fight those physics. VTube Studio's API supports
custom parameters; expression precedence/hotkeys can override the same
parameters. Stop a stale speech epoch and flush pending expression packets
before resetting a rig. Source:
https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
and https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-(a.k.a.-Stickers-or-Emotes) .

**Broadcast quality tests** (real Windows PC, 30–60 minute local rehearsal):
measure p50/p95 game frame time, FPS 1% lows, VRAM peaks, microphone-to-meaningful
response p95, first-audible delay, lost/replayed speech epochs, interruptions
correctly categorized, output device underruns, laughter timing, mouth sync,
eye focus, tail/hair clipping and user-rated conversational naturalness.
No personal microphone files should be uploaded to a public GitHub repository.

## General intelligence and local self-improvement

- Use owner-approved documents, task-scoped retrieval and provenance tracking;
  periodically revalidate time-sensitive knowledge. An old fact is not an
  evergreen truth. Unknown answers should trigger source review, not guesses.
- Separate passive accumulation from competence. Build independently scored
  general-knowledge, logic, image understanding, 3D construction, audio and
  game-play suites with untouched holdouts. STAR cannot grade its own success.
- Generate slightly harder practice cases from **approved templates**, never
  modify grader code, protected fixtures, deployment policy or safety settings
  autonomously. The local Star Core Forge should perform versioned experiments,
  offline unit tests, semantic diffs and reliable rollback before enabling
  any self-change.
- Keep long-horizon memory tiered: verified task skill, episodic evidence,
  reviewed general facts, fictional persona lore and transient working memory.
  Tag trust, age, source and broadcast permissions on every retrieval.
- Use a multi-agent assembly line only when two workers truly fit CPU/RAM.
  Parallelism that causes swap thrash or oversubscribes the 8 GB GPU is slower.
  Reserve enough RAM and disk for successful recovery after power loss.
- Never let public web research, Twitch chat, retrieved media or model responses
  change device permissions. Do not claim subjective consciousness as an
  engineering result; target persistent and testable self-model *functions*.

## Suggested measurement dashboard (targets, NOT achieved results)

| Metric | Baseline | Candidate acceptance |
| --- | --- | --- |
| Portfolio per-game practice coverage | measure | 3+ distinct curated games represented |
| Signed practice verification rate | measure | no fabricated receipt accepted |
| Unverified repeated failures | measure | bounded cooldown, then manual diagnosis |
| Transfer to unseen map seeds | measure | positive per-game confidence intervals |
| Streaming 1% low FPS | measure | non-inferior to gaming-only baseline |
| First-audible response p95 | measure | faster at comparable completion/quality |
| Supported, useful public chat replies | measure | no regression in evidence support |
| False audio interruptions | measure | fewer without missing real owner speech |
| Full game project shipped and played | measure | reach ending + save/rejoin correctness |
| Unauthorized host actions | zero expected | always zero |

## Verified boundaries of this patch

The new source and tests use no third-party dependencies beyond the existing
project's test environment. They neither start models nor games. The only
measured capability increase here is **new fair, bounded, signed-evidence
multi-game scheduling**. The companion benchmarks, voice experiments, live
play, and broad creative/game-building improvements are subsequent, reviewable
work. GitHub is an optional draft-review publishing mirror of local STAR; local
Core Forge remains the intended improvement system.
