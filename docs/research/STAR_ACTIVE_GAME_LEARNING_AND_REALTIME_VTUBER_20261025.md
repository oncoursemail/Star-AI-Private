# STAR active game-learning and realtime VTuber infrastructure: research and implementation
**Checkpoint:** 2026-10-25 · **Status:** draft / offline tests / default-OFF · **Stacked on:** PR #617 → #612 → #581.

## Executive conclusion

The most promising route to a more capable, responsive STAR is **measured specialization plus closed-loop verification** rather than pretending a larger prompt or an additional "thinking" agent alone increases intelligence. Asynchronous offline practice can be compute-heavy; live interaction needs low bounded latency and respect for gameplay focus. STAR's game memory must distinguish a strategy *proposed*, *tried*, *successful under familiar conditions*, and *validated under independent conditions*. Her public character can feel natural through timing, silence, continuity, expressive motion, and grounded reactions without falsely presenting a software agent as a biological person.

This changes three specific pieces of source code. It does **not** provide a pretrained agent capable of playing any game, increase foundation-model parameters, deploy streaming, run a game controller, train network weights, or show a measured tokens-per-second gain.

## Implemented in this draft

| File | Change | Boundary |
| --- | --- | --- |
| `star/gameplay_skill_bank.py` | `practice_evidence(...)` returns scoped, fresh **signed practice-only** aggregates; `signed_practice_run(...)` verifies the exact host-assigned practice run | Does not reveal individual play logs, HMAC receipts, or independent validation outcomes |
| `star/active_practice.py` | Owner-approved active-practice planner with coverage-first trials, uncertainty-guided practice, bounded action roster, per-action trial limit, bounded expiring tickets and cooldown | Host must separately authorize capture and control. No network, GPU/model, Roblox or OBS access |
| `star/stream_stage.py` | Optional `StreamTelemetry` influences `StarStage.prepare(...)`; defers optional chatter during measured game-FPS/GPU/voice backlog pressure; preserves danger/owner interruption | Host-supplied telemetry only; old calls without telemetry work as before |
| `tests/test_active_practice.py` | Signed evidence, holdout-blindness, scope isolation, stale data, SQLite tampering, request cooldown, concurrency backpressure, wrong-run suppression | Synthetic fixtures, not real game or hardware results |
| `tests/test_stream_stage_pressure.py` | Speech admission under FPS, VRAM, backlog and owner interruptions | No actual voice synthesis, microphone, rig or game controller |

### Exact offline interface

```python
# Host-side illustration ONLY. Do not put either signing key in a model prompt
# or allow the AI to sign its own results.
from star.active_practice import ActivePracticePlanner
from star.gameplay_skill_bank import GameplaySkillBank
from star.stream_budget import StreamTelemetry

bank = GameplaySkillBank("host-owned-evidence.db",
                         practice_key=HOST_PRACTICE_SIGNER_KEY,
                         validation_key=INDEPENDENT_EVALUATOR_KEY)
planner = ActivePracticePlanner(bank)
planner.enable(owner_approved=True)  # this enables suggestions, NOT game control
capacity = StreamTelemetry(live=False, game_active=True,
                           free_vram_mib=4096, total_vram_mib=8192,
                           game_fps=60, speech_backlog_ms=0)
candidate = planner.reserve("obby", "v1", "finish", "jump_section",
                            ["jump_short", "jump_long", "walk_around"],
                            now_unix_s=TRUSTED_HOST_UNIX_TIME,
                            telemetry=capacity)
# A separate approved host executes a bounded real test in a private place.
# It binds candidate.expected_run_id to the GameTrial.run_id, checks success
# independently of the model, hashes its evidence, and signs the practice trial.
# bank.ingest(signed_trial, trusted_receipt, now_unix_s=trusted_time)
# planner.finish(candidate.ticket, now_unix_s=trusted_time,
#                host_reports_recorded=True)
```

`practice_evidence` is an *aggregate* practice interface, not an API for fine-grained player tracking. The planner's action roster must be selected from a host-curated symbolic action ontology. `expected_run_id` is a host reservation identity; if an unrelated trial, failed tool operation, validation result, older run, or unreviewed AI message arrives, the ticket cannot be counted as verified. The bank's existing independent holdout gate remains unchanged: *practice alone never promotes a real gameplay skill*.

If the trusted host calls `finish(..., host_reports_recorded=True)`, success means **the matching signed practice result was ingested**. It does not mean the in-game strategy actually worked, unless that host genuinely verified the observation. The bank's HMAC keys attest signer identity, not empirical truth.

### Practice selection algorithm

1. Enforce consent, offline telemetry, 1–32 allowlisted symbolic actions, a single in-flight ticket, spacing, expiry and a bounded count per action.
2. Read **only PRACTICE outcome aggregates** scoped to game ID, version, objective and situation. Never use independent validation performance to choose what to practice; doing so would contaminate the holdout.
3. If any action has fewer than three trials, choose the least-practiced one first. This ensures initial coverage instead of an early lucky winner monopolizing exploration.
4. After coverage, compute a lightweight Beta(1,1) posterior uncertainty score based on successes and failures, weighted toward tasks near the challenging 50% success region. More uncertain, plausibly learnable actions are preferred; each candidate is still capped.
5. Produce one candidate and a collision-resistant `expected_run_id`. A separate authorized host can choose whether to execute it. A ticket is NOT permission to press keys, open Roblox, modify a studio place or broadcast.
6. Verify a matching signed run on completion. No unverified success, validation result, old trial or mismatched context can complete the reservation.

The score is a **heuristic** chosen for inexpensive bounded scheduling. Bayesian posterior standard deviation here is not a calibrated model of learning gain, and a 50%-success task is not always the right curriculum. A counterfactual randomized evaluation against uniform scheduling, Thompson sampling and human-selected curricula is required before claiming fewer trials, improved game win rates, faster learning or improved model intelligence.

## Evidence from external research

**Learning new gameplay skills.** Voyager demonstrated an automatic curriculum, cumulative skill library and feedback-driven executable-skill refinement in Minecraft. STAR already has Studio self-play and evidence mechanisms, so adding a practice-only selection layer is a natural gap to close. Voyager's gains do not transfer automatically to STAR or Roblox. [Voyager, NeurIPS 2023](https://arxiv.org/abs/2305.16291).

**Generalizing beyond known games.** Google's SIMA 2 uses reasoning, virtual-world gameplay and self-improvement; its authors explicitly acknowledge short interaction memory, low-level keyboard/mouse precision, long-horizon planning and 3D perception as open problems. The right STAR research question is transfer on **withheld games/maps/control schemes**, not self-reported "mastery." [Google DeepMind SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/).

**Model-based simulation.** DreamerV3 suggests planning through a learned world model as a longer-term option. STAR would first need time-aligned state/action/reward trajectories and isolated, versioned evaluations. A world model is not automatically a drop-in improvement: training costs, accumulated model error and distribution shifts can make a cheap planner better. [DreamerV3](https://arxiv.org/abs/2301.04104).

**Actual Roblox testing.** Roblox announced its built-in Studio MCP server and playtest input automation on March 5, 2026. Its April 9 playtest-agent beta offers a dedicated character for basic in-game validation. Prefer the official, current MCP server and STAR's guarded test-place identity; use input tools only in an owner-approved disposable place. A tool handshake is not evidence that Studio is actually attached or the game passed. [Roblox March 5 announcement](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643) · [April 9 beta](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767) · [official MCP docs](https://create.roblox.com/docs/studio/mcp).

**Streaming expression.** NVIDIA's DyaPlex (June 2026) studies synchronized full-duplex speech and motion. STAR should first implement an economical event-to-cue/speech audio host and verify actual lip synchronization, rather than claiming that DyaPlex is integrated or practical on 8 GB VRAM. [NVIDIA DyaPlex](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/).

**CPU speech alternative.** Kyutai's Pocket TTS includes small October 2026 CPU-focused English models (18.2M / 6.9M / 1.9M parameters) and streaming audio. This may leave more GPU headroom for gameplay. Published throughput is not a measurement on STAR's PC: benchmark first-audible delay, voice naturalness, intonation and simultaneous game FPS with a voice license and consent check. [Pocket TTS](https://github.com/kyutai-labs/pocket-tts).

**Local inference engineering.** vLLM prefix caching can skip repeated prefill but does not accelerate unique decode tokens. llama.cpp speculative decoding can improve generation speed when draft acceptance is high; memory and verification overhead can negate gains, especially on an 8 GB GPU. Test with the exact model, quantization, context and live stream workload rather than assuming advertised multipliers apply. [vLLM caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) · [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).

**Stream plumbing.** Twitch EventSub events are at-least-once, so dedupe `message_id` and handle reconnect/resubscribe correctly; a dropped socket cannot be assumed lossless. OBS WebSocket should be authenticated and restricted to local/private network access. These are future host adapters, not present in this draft. [Twitch EventSub](https://dev.twitch.tv/docs/eventsub/) · [Twitch reconnect](https://dev.twitch.tv/docs/eventsub/handling-websocket-events) · [OBS WebSocket](https://github.com/obsproject/obs-websocket).

## Architecture for a more capable STAR

```text
Owner-approved game / isolated Studio place
  ├─ trusted local game state + occasional screenshots/audio (resource governor)
  ├─ time-aligned observer: objects, position, UI, damage, success, uncertainty
  ├─ task graph: subgoals, deadlines, prerequisites, skill IDs
  └─ guarded controller: only host-allowlisted game inputs/actions, stop on timeout
       ↓
  signed practice trial → practice-only aggregate → ActivePracticePlanner
       ↕                                                 │
  protected game version/seed registry           next candidate reservation
       ↓                                                 │
  independent unseen holdout signer  ← approved offline evaluation harness
       ↓
  GameplaySkillBank.suggest() → owner review → optional skill deployment
       ↓
  verified current-game events → StarStage/StreamDirector → permitted TTS
       ↓
  actually-heard audio → lip / ear / hair / eye / hand motions and timing
       └─ NEVER infer "played completely" from queued TTS
```

### Roadmap to prioritize by expected return, not fantasy benchmarks

| Priority | Proposed next addition | Measurable success gate | Constraints |
| --- | --- | --- | --- |
| P0 | Owner-approved private Studio/game observation and independent test harness | Can reproduce a failure and verify an actual fix on withheld seeds; signed receipts trace to runs | No arbitrary prompts as keyboard automation; abort keys and timeout |
| P0 | Character conversation-turn policy + voice device timestamps | Lower p95 first-audible delay, lower talking-over-game count, real audio-to-mouth alignment | Speech output must actually be heard; skip chat under load |
| P0 | Exact cross-branch baseline A/B harness | Win rate and completion rate against previous STAR on same protected tasks without slowing games | Evaluate unseen levels, not prompts constructed from tests |
| P1 | General game-action ontology and prerequisite graph | Master previously unseen jumps, combat/UI flows with fewer real episodes | No reuse without version/control recalibration |
| P1 | Scene-state tracker with time-aligned audio/visual evidence | Better object permanence across camera changes; calibrated uncertainty on occlusions | Avoid confident false game-state claims |
| P1 | Knowledge provenance router and recall calibration | Better source correctness and citations on held-out general questions without leaking private notes | Verified public sources; no automatic broadcast of private memory |
| P1 | Automatic model profile optimizer: CPU-TTS, quantization, cache, draft decoding | Same-or-better benchmark answer quality with measured game FPS and audible latency | Compare full VRAM, CPU and thermal budgets on real PCs |
| P1 | Cross-game skill composition and transfer tests | Verified skill transfer across 3 unrelated game genres and unfamiliar controls | Negative-transfer regression and protected holdouts |
| P2 | Advanced performance-driven avatar gestures and physics | Perceptual human evaluation for naturalness and rig stability in 30-min session | Hair/tail physics must not clip; reduced-motion mode |
| P2 | World model predictive control and experience distillation | Real improvement over non-world-model baselines on held-out tasks | Expensive training, avoid sim-to-real gaming drift |
| P2 | Knowledge graph/semantic memory consolidation | Fewer repeated mistakes and better long-term factual retention | Explicit retraction, contradiction support, erasure |

## Giving an AI character natural human-like streaming behaviors

Star should be *recognizably Star*, not claim to be an actual human. The experience should arise from coherent attention, expressive delivery, remembered genuine events and honest uncertainty.

- **Attention is more important than chatter.** Pause during difficult jumps, fights, menu searches or a viewer's own speech; give concise reactions after confirmed success. The new `StarStage.prepare(telemetry=...)` is backward-compatible and does this for limited measured pressure. It deliberately permits owner interruption and short danger cues.
- **Conversation timing:** short acknowledgements, occasional silence, varied but purposeful utterance length, polite barge-in handling and no looped filler lines. Use host audio playback start/end timestamps. Measure overlap rate, phrase interruption quality, p95 first-audible latency and completion ratio, not an arbitrary "sounds human" number.
- **Character continuity:** a fictional, clearly marked public backstory can be playful. Keep *real* saved experiences separate from in-universe lore; do not pretend Star has human childhood memories, real feelings, or guaranteed consciousness. Approved public gaming anecdotes require matching observed evidence.
- **Physical performance:** coherent blink, eye focus, breathing, facial expressions, amplitude/phoneme-driven mouth timing, small anticipatory gestures, eye blinks, weighted hair/twin-tail/ribbon/tail physics, ears matching cat/puppy mode. All cues should flow through one timebase and owner-approved rendering app, with a measured frame budget.
- **Viewer trust:** clearly label as AI VTuber, moderate messages before passing them as untrusted data, do not let a viewer prompt move the cursor, modify a game, issue admin commands, operate the PC, or reveal personal/private documents.
- **Graceful failure:** if TTS or inference stalls, let Star wait quietly or use a short owner-authored safe fallback; do not fabricate game achievements or claim speech was heard. Chat events must expire; an interrupted utterance must not be marked completed.

## Benchmarks STAR must pass before public activation

**Game learning:** At least three withheld games and multiple unseen worlds/maps per game; a fixed evaluation trial cap, identical seeds between variants, independent game observer, baseline win rate, time-to-goal, input errors, attempts, exploration diversity and out-of-domain degradation. Count only distinct episodes, not frames or generated text, as evidence. Compare coverage-first/uncertainty scoring with uniform sampling, human curriculum and Thompson sampling. Report confidence intervals, budget and failure cases. Lock validation seeds and signing keys away from agent.

**Realtime VTuber:** Full 30-minute local rehearsal while game + VLM/vision + TTS + avatar renderer operate together. Record p50/p95 first-audible speech latency, overlap/cut-off rate, game FPS 1% lows, VRAM peak, CPU/RAM pressure, silent-response frequency, frame render lag and emotion/word grounding false positives. Test disconnect/reconnect, speech interruption, scene changes, muted source, dropped frames, viewer spam and an emergency owner stop.

**Model intelligence:** Use representative general-knowledge, software, math, visual/game reasoning and Roblox tasks, held out from training/retrieval. Track accuracy and completion, token/second, time-to-first-token, first-audible latency, memory footprint, regression frequency, and source provenance. Quality must not regress when fast-path routing/quantization is enabled. Present per-task distributions and confidence intervals rather than a single ungrounded "IQ" value.

**Repository assurance:** unit tests, mutation/tamper tests, clean diff, ruff/static/type gates, local CI, Windows native installation, studio consent review and observed gameplay proof. Keep default-OFF and draft until independently reviewed. Private-looking repository names are not access controls; confirm GitHub visibility before adding any recordings, keys or personal data.

## Known limits and failure analysis

1. **One thread for SQLite:** this implementation's `GameplaySkillBank` connection uses SQLite's default creating-thread affinity. The active planner serializes ticket state with a lock, but the host must perform bank-backed `reserve` and `finish` from the ledger's owning thread or provide an explicit threaded RPC/queue. The test covers concurrent calls when a ticket is already in flight, not concurrent initial database reads.
2. **Wall-time clock:** the planner requires nondecreasing host Unix seconds for reservations; an NTP rollback requires starting a new session. Future work: monotonic clock for in-process deadlines plus authenticated epoch time for ledger evidence.
3. **No execution authority:** none of these changes capture frames, start Roblox, click game controls, start OBS, select a speech model, download an asset, launch learning jobs or mutate the running character.
4. **Proof-of-practice, not proof-of-success:** signed `outcome='failure'` records still count as practice observations for scheduling but do NOT become learned success. Independent validation still determines whether a skill can even be nominated for owner review.
5. **Conditional heuristics:** VRAM/FPS/speech thresholds are conservative policy starting points, not statistically optimized device limits. Real 3060 Ti/4060 hardware measurements should tune them by workload with fail-safe bounds.
6. **No claims of human consciousness or superintelligence:** richer memory, adaptive scheduling and natural expressions are engineering features, not proof of sentience or surpassing all humans/AI systems.

## Verification recipe

```sh
PYTHONPATH=.:tests python3 -m unittest -q \
  tests.test_active_practice tests.test_gameplay_skill_bank \
  tests.test_stream_stage_pressure tests.test_stream_stage tests.test_stream_budget
python3 -m compileall -q star/active_practice.py star/gameplay_skill_bank.py star/stream_stage.py
ruff check star/active_practice.py star/gameplay_skill_bank.py star/stream_stage.py \
  tests/test_active_practice.py tests/test_stream_stage_pressure.py
git diff --check
```

All test outcomes must be reported from the **exact pushed GitHub revision**. No PR may auto-merge. The public `Star-AI` release repo should remain separate from the full private-source development tree; do not push secrets, training recordings, or unreleased source to the public release repository.
