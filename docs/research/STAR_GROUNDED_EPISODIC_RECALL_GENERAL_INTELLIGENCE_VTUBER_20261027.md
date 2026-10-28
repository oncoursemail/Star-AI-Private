# STAR AI — verified episodic recall, stronger general intelligence and natural gaming VTuber

**Research date:** 2026-10-27 (America/Chicago). **Delivery:** opt-in offline signed-practice recall lab, synthetic tests and future integration plan. **Base:** draft PR #723, NOT merged. GitHub is an optional export/review channel; Star Core Forge remains the intended independent local development system.

## Decision: stop equating collected memories with understanding

STAR already has signed gameplay trials, an episode continuity vault, an action-to-visual-change probe, speech turn-taking and avatar motion planners. But none of these, alone, establish that the model can answer questions about what happened earlier. An agent can store perfect logs yet make up a convenient, fluent story. The next capability needs **ground-truth questions from past events, blind answers, single-attempt scoring and independent replay**.

### Research readout (all links to upstream work)

1. **EMemBench — Jan 23, 2026; v2 later in 2026:** trajectory-grounded episodic questions cover single-/multi-hop, temporal, spatial, inductive, logical and adversarial memory. Spatial and inductive reasoning remain weak, particularly for visual games. STAR should test recall *against its own separately verified episodes*, not generic trivia prompts. Paper: https://arxiv.org/abs/2601.16690 ; author page: https://yuhangzang.github.io/papers/arxiv-2601.16690.html .
2. **BetaMem — Oct 19, 2026:** argues for traceable working, spatial, entity, episodic, experiential and procedural memory, with source-supported writes and independent replay gates on fixes. Use that idea cautiously: an implementation for STAR must separate evidence from summaries and must never let a proposed "memory improvement" certify its own results. Paper: https://arxiv.org/abs/2610.26554 .
3. **EmbodiedMemory-Bench — Sep 23, 2026:** emphasizes state tracking, interaction outcomes and later actions grounded in those records, not just fact recall. STAR needs a world-state store with explicit last-observed time, uncertainty and invalidation after a scene change. Paper: https://arxiv.org/abs/2609.28236 .
4. **Roblox OpenGameEval — Oct 1, 2026 paper:** executable scene checks and play-session behavior are better evidence of game creation than generated script text. Agents that inspect relevant scene elements before editing often fare better. Keep independent Studio playtests in the acceptance path. Official project: https://github.com/Roblox/open-game-eval ; paper: https://arxiv.org/abs/2610.02563 .
5. **NVIDIA DyaPlex — June 2026:** research into jointly timed speech and motion, and full-duplex response, suggests coordination rather than a sequence of unrelated canned animations. This is research inspiration, NOT a lightweight model that we claim to run on an 8 GB GPU. https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/ .
6. **LiveKit turn handling — documentation inspected Oct 27, 2026:** separate endpointing, adaptive interruptions, false-interruption resume and preemptive LLM generation. Preemptive TTS is disabled by default in their settings; for STAR, extra speculative voice synthesis must earn its place with cancelled-turn waste and game FPS tests. https://docs.livekit.io/reference/agents/turn-handling-options/ .
7. **Kyutai Pocket TTS — Oct 2026 model additions:** the official repository documents 18.2M, 6.9M and 1.9M English CPU-oriented variants as well as 100M models. These are candidates to benchmark for first-audio latency, intelligibility, expressiveness and CPU contention on STAR's actual Windows PC, not automatic quality wins. https://github.com/kyutai-labs/pocket-tts .
8. **llama.cpp** remains a useful measurable local inference baseline, not a guaranteed fastest engine for every model/hardware combination. Track prefill tokens/sec, decode tokens/sec, time-to-first-token, memory, speculative acceptance, and gameplay FPS *together*. Official project: https://github.com/ggml-org/llama.cpp . Consider alternate runtimes only under the same model, quantization, context, machine and workload.

## What was implemented in this change

`star/game_recall_audit.py` is a new optional **GroundedGameRecallAudit**:

- Requires an owner enable flag, a trusted host's sealed-episode attestation, a private independent challenge key and an existing GameplaySkillBank.
- Checks each supplied GameTrial against an **exact, previously ingested, independently signed PRACTICE ledger entry**. Any missing, edited, held-out, wrong-scope, duplicate or out-of-order item fails closed; only 5–64 action records from a single host-asserted scene scope are accepted.
- Freezes the evidence sequence and generates up to 24 bounded questions. Categories: **frequency**, **temporal/outcome**, **inductive failure streaks**, **cross-action comparisons** and **relative event order**.
- Keeps correct answers hidden inside the trusted lab. Only a bounded symbolic question, 32-character keyed ticket, expiry and skill category are exposed to the model. A question is one-flight, consumed by the first answer; expiry, restart and replay are rejected.
- Scores exact symbolic answers, never lets an LLM "judge" itself, and produces an anonymized per-skill Wilson confidence-lower-bound report (only after enough questions).
- Requires use from the ledger's owner thread, keeps only bounded in-memory data and exposes no viewer details, raw screenshots, prompts, receipts, signing keys, trial IDs, game labels or correct answers through its model-facing API.
- Cannot trigger gameplay, model inference, a broadcast, microphone, streaming speech, neural training, memory rewrites or GameTrial signing.

**Trust caveat:** the bank checks authentic signed receipts **from the trusted observation host**. Neither a signed record nor an episode-sealed flag proves the external game observer was truthful or that the host supplied all records from precisely one actual episode. Real Windows game-state validation and signed episode membership remain required before production use. The offline quiz measures *memory recall*, not game mastery, consciousness or spontaneous natural speech.

### Host-only integration sketch

```python
# Run on the same host worker thread as GameplaySkillBank.
# Bank and its PRACTICE/VALIDATION signing keys are provisioned separately.
audit = GroundedGameRecallAudit(
    bank, challenge_key=host_private_recall_key_32_bytes,
    public_action_ids=frozenset({"jump", "dash"}),
)
audit.enable(owner_approved=True)
assert audit.seal_episode(
    ordered_signed_practice_trials, episode_id="host_session_01",
    now_unix_s=host_unix_seconds, host_episode_sealed=True,
)
question = audit.issue(now_unix_s=host_unix_seconds)
# The trusted host sends ONLY question.prompt to the LLM.
# Never pass audit, its key, ledger internals or correct answers into tools/chat.
result = audit.grade(question.ticket, model_symbolic_answer,
                     now_unix_s=host_unix_seconds)
scores = audit.skill_report(min_attempts=2)  # metadata, not answer key
audit.disable()
```

Do not do this during a broadcast, and never let viewer content call the trusted host API.

## Moving from intelligence *claims* to intelligence *measurements*

Build five separately versioned scorecards so STAR can tell whether a change helped:

| Skill domain | Ground-truth task | Guard against self-deception |
|---|---|---|
| Episodic knowledge | Blind signed-trial questions from previously seen sessions | Future sealed episodes, one answer, no answer in prompt |
| Game mechanics | Action versus control, fresh game seed, repeated practice | Signed simulator state, matched starting conditions, held-out layout |
| Game creation | Scene edit and actual Studio playtest | Engine-level object/physics tests + human visual review |
| General knowledge | Fresh source-backed answers, uncertainty and abstention | Independent dated references, stale-data tests, adversarial contradictions |
| Humanlike broadcasting | Recorded/replayed dialogue, audio, motion, viewer interruptions | Human ratings, turn latency, interruption recovery, mute correctness |

Avoid training on hidden validation. The **owner-only** experiment engine should use all feedback from practice, but independent held-out data stays sealed. Time, room identity, control bindings and environment versions are critical confounders; do not pool unrelated runs.

## Stronger reasoning at lower hardware cost

**Recommended architecture for RTX 4060 8 GB + 32 GB RAM; not newly benchmarked:**

- **Fast game loop:** collect trusted input/HUD cues, maintain bounded local state and choose *pre-authorized* next gameplay action using simple state machines or small learned policies. Do not call a full language model every rendered frame.
- **Deliberate loop:** route genuinely ambiguous mechanics, social conversations and new tasks to a stronger LLM on an event basis. Prefer token budgets, retrieval and cached stable prefixes over persistent full-screen re-interpretation.
- **Background learning:** review signed successes/failures, replay difficult cases, create alternate hypotheses and evaluate harder exercises only when host telemetry permits offline work. First candidate is tested on practice, never on sealed validation.
- **Memory hierarchy:** current scene state (short-lived), signed events (episodic), verified procedures (reusable skills), sourced facts (general knowledge), and owner-approved public streamer memories (tiny sanitized view). Every derived claim carries provenance and a time limit.
- **GPU/CPU broker:** measure reservation pressure, VRAM, TTFT, speech backlog and FPS as a single system; disable background thought if it degrades input responsiveness. Co-locate unrelated loads only if measured wins outweigh context switching.
- **Experiment ledger:** install experiments into local Star Core Forge with semantic diffs, automatic replay, safety checks and rollback; treat GitHub as optional public code review/export rather than the self-improvement substrate.

This gives **more verifiable useful work per second**, not magically greater model intelligence. A 100 ms fast-path win is not useful if it hides a 2 s speech queue or causes frame-time spikes.

## Making STAR a distinctly natural AI VTuber

A convincing streamer needs grounded, continuous behavior rather than constant talking:

- **Natural attention:** quiet while aiming or learning, glances to chat at safe times, eyes leading head, expressive brows and controlled laughter only after meaningful context. Use reduced-motion options and deterministic neutral states on failure.
- **Duplex conversation:** decouple listening from speech; use voice activity + real turn detection, selective acknowledgment, false-interruption recovery and abort any speech/animation on session switch. STAR should yield to players and viewers instead of speaking over them.
- **Voice quality:** record natural first-audio latency and word timings; compare CPU Pocket TTS variants with more expressive baselines on the same machine. Preserve a coherent original voice and do not clone real voices without consent/license.
- **Rig synchronization:** drive jaw, cheeks, eyes, eyebrows, breathing, twin-tail hair and ribbon physics from the *audible* speech timeline and emotion cues; mute/interrupt should neutralize the rig. Cat and puppy modes remain expressive toggles, not unrelated random noises.
- **Real continuity:** only remember things she actually did in signed practice or events the host observed; explicitly distinguish practiced a jump, completed a level and won a match. Don't invent a human childhood or claim literally human sensations.
- **Viewers:** moderated chat, question fairness, private-info minimization, anti-impersonation, anti-spam and a clear AI identity. Never let chat authorize gameplay, spending, account access, code execution or moderation privilege changes.

### Windows / Roblox / OBS acceptance milestones (not yet executed)

1. Trusted game adapter produces timestamped, scoped, authorized controls and independent game-state outcomes. Verify *actual* input release, Studio tool focus, version and game identity.
2. Signed episode host links its archive to exact GameplaySkillBank trial IDs (not merely a Boolean attestation). Feed only sealed PRACTICE sequences to the offline recall evaluator. Add replayable visual/memory questions with image-region ground truth, still avoiding private viewer data.
3. Run at least 20 previously unseen sealed episodes and compare before/after **blind** recall accuracy by category; report Wilson intervals, not unsupported claims of smarter models.
4. Measure 30-minute mixed game + TTS + live avatar runs, logging p50/p95 speech latency, action reaction latency, p1 FPS, VRAM pressure, cancelled speculative work and OBS dropped frames.
5. Blind human review (consenting raters) on naturalness, interruption handling, voice/rig synchrony and factual grounding, alongside automated captions versus audible audio alignment.
6. Review security: this repository currently reports **PUBLIC** visibility despite the name `Star-AI-Private`. Never commit real private keys, viewer identities, recordings, undisclosed game seeds or evaluation answers.

## Review/rollback and claim boundaries

- New module and tests are **off by default** and require a host to integrate them. They neither speed up inference nor autonomously improve weights.
- No Windows game, Live2D renderer, VTube Studio, microphone, OBS or multiplayer session was exercised by this isolated change.
- Quizzes over a fixed synthetic episode prove API behavior only. Gameplay and general-knowledge improvement require external, hidden, independently scored benchmarks.
- The current user request explicitly asks for GitHub publishing, so ship this as a **draft PR** stacked on #723; do not auto-merge or deploy.
