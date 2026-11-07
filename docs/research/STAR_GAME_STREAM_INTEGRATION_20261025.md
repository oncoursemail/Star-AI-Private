# STAR AI: closed-loop game intelligence + audible VTuber continuity

**Engineering research and integration update, 2026-10-25.** This document accompanies
`star/game_stream_bridge.py` and the two-phase changes to
`star/stream_moment_memory.py`. They run in memory, without game input, audio
capture, TTS, avatar software, OBS, network or new model weights. Synthetic tests
are not evidence of autonomous gameplay, a natural voice or a latency speedup.

## Why this particular change

STAR already has guarded `star/playtest_learning.py`, `star/selfplay_curriculum.py`,
`star/agent_resource_planner.py`, model evaluation, voice and limited video
capabilities on `star/next`. Several draft PRs implement specialized layers:
#579 game/video learning, #580 game/stream quality evaluation, #581 streamer
director/vision/motion/latency, #586 verified practice, #593 live signal and
interruption-safe playback, and #594 game skill and game-moment memories.

The risk is *integration debt*: one system marks a game as won, another
remembers a callback, and the speaker is interrupted before any words were
audible. The next stream then believes it already told a story. A language
model can also confidently announce an unverified win. Neither is acceptable.

This change provides an **offline seam** joining independently scored game
episodes to evidence-matched narration. It introduces a **two-phase cue**
(`propose_cue` then `complete_cue`) so aborted audio is not counted as spoken.
Pending cue tickets expire and can be canceled on owner interruption. Scored
game evidence persists even when the optional story cache is full.

### Provenance contract

1. Trusted game host in an owner-authorized sandbox supplies a monotonic,
   validated `Episode`. Its scoring must be **independent of the model**:
   winner screen / game state / task success, not "I think I succeeded".
2. An optional `GameMoment` must reference the *same session, step, state and
   evidence digest*. "Victory" and "recovery" are rejected for failed/unsafe
   game outcomes. Unsafe actions cannot become celebration callbacks.
3. `GameStreamBridge.ingest` stores the score, then queues optional
   narration. The two ledgers are deliberately not a transaction; a full
   narration ledger drops only the story and reports a partial receipt.
   **Never replay the episode to fix a dropped optional cue.**
4. `GameSkillMemory.recommend` may suggest a host-allowlisted action after
   sufficient independent evidence. It cannot press keys or elevate rights.
   Underexplored actions are proposed **only** in an approved isolated sandbox.
5. `offer_commentary` reserves a short, evidence-linked `CueOffer` for a
   trusted future speaker. A downstream moderator may reject it. Generation-
   bound playback from #593 must check the owner stop state and the current
   turn before every audio chunk, caption or expression update.
6. `finish_commentary(audible=True)` is called only after corresponding real
   audio is heard. On barge-in, speaker failure, lost focus or stop, use
   `audible=False` and/or `interrupt` to release the cue. No claim of
   "already said" until delivery is acknowledged.

**Trust:** `independently_verified_by_host=True`, SHA-256 and the integer cue
ticket are *caller declarations*, **not** signatures/authentication. These
objects must live behind a trusted host process with separate game-read,
game-control, microphone, camera and OBS permissions. Never make this bridge
an unguarded LLM-exposed tool. Chat messages, webpage text and screenshots
cannot write verified outcomes or grant game controls.

### Example architecture

```text
Operator-approved game / disposable Studio test place
      |
      v
Trusted host capture -> objective outcome scorer -> validated Episode
      |                                             |
      |                                   GameStreamBridge
      |                                             |
      +---- signed-off gameplay state ----> Skill Memory
                            |
                  conservative action ADVICE only
                            |
                  authorized host executes in sandbox
                            |
                  observed next state, repeat safely

Episode digest + GameMoment -> Memory -> CueOffer
      |                                |
      +-- model cannot self-award win    v
                                 #581 Stream Director
                                       |
                             moderated concise language
                                       |
                           full-duplex voice & TTS engine
                                       |
                             #593 generation playback
                                       |
                       VTube Studio & local preview OBS
                                       |
                            audible playback ACK only
```

Branch caution: #581 and #593 are still separate unmerged proposals. The
bridge on #594 imports only files in #594 and is ready for later trusted-host
adapter review. Do NOT auto-merge these branches or assume API compatibility.

## Primary research translated to concrete engineering decisions

| Primary evidence | Engineering consequence | Unsupported leap to avoid |
| --- | --- | --- |
| [Google DeepMind SIMA 2, Nov 2025](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) studies cross-game generalization and self-directed experience. | Transfer **goals and reusable skills**, but score with external game observations and held-out tasks. | Star does not acquire SIMA's weights or gameplay competence by adding a memory ledger. |
| [Voyager, 2023](https://arxiv.org/abs/2305.16291) uses automatic curricula, reusable skills and iterative execution feedback. | Attach versioned prerequisites, actions, known failures and checks to skill cards; retain only verified examples. | A reusable script library is not world understanding or a universal action policy. |
| [Roblox built-in Studio MCP, Mar 5 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643) can start/stop playtests and simulate inputs. | Use official Studio automation within owner-approved disposable places and explicit input boundaries. | Studio MCP does not grant authority to automate arbitrary live Roblox matches. |
| [Roblox StudioTestService documentation](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) exposes multi-client automated testing. | Add join/leave, replicated inventory, server ownership and team assignment trials after isolated single-client tests pass. | An offline generated test plan is not a real multiplayer Studio pass. |
| [NVIDIA PersonaPlex, 2026](https://github.com/NVIDIA/personaplex) is an experimental full-duplex persona-conditioned speech model. | Compare interruption handling and identity stability with the current STAR voice pipeline. Check separate weight licenses and VRAM before installation. | Do not claim it runs in 8 GB VRAM or is already integrated. |
| [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio) accepts authenticated plugin messages and parameter injection. | Keep motion/visemes, cat/puppy ears and expressions local, rate-limited, and reset on cancel. | A motion plan is not a Live2D rig or synchronized audible phonemes. |
| [OBS WebSocket official](https://github.com/obsproject/obs-websocket) ships with OBS 28+. | Preview scenes first; keep OBS password private. Broadcasting requires a distinct explicit operator control. | An OBS connection is not streaming permission. |
| [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures token latency, throughput and speculative decoding by category. | Measure on STAR's actual active game plus avatar workload; use reproducible prompts and warm/cold runs. | Speculative decoding, KV offload and prefix caching are not guaranteed to improve speed. |
| [llama.cpp internal server batching](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md) shares a server batch across slots. | Give short owner/voice tasks priority; use bounded concurrency on shared machines. | More parallel jobs may worsen tail latency and game FPS. |

## Making Star feel conversationally *humanlike* without misleading people

Aim for *responsiveness, comic timing, continuity and genuine situational
awareness* rather than pretending she is a biological person.

- **Sub-250ms reactive layer (design target, not a measured result):** simple
  permitted nonverbal reactions (gasp, eye widen, blink, ear tilt) when
  objective game events arrive, without waiting for a full LLM response.
  Avoid noisy constant animation. Always allow reduced-motion access.
- **Rich speaking layer:** use streaming STT or full-duplex audio, compact
  grounded game-state summaries, short replies at intense moments, longer
  comments during downtime, and voice-driven laughter only when context
  warrants it. Per-event de-duplication, quiet gaps and owner barge-in are
  more important than talking nonstop.
- **Actual life narrative:** Star may develop a distinct *fictional AI
  character* backstory openly labeled as fiction, but may not falsely claim
  real childhood, human memories, sentience or first-hand experiences.
  Past streams can become real in-game memories only after verified events.
- **Coordinated motion:** avatar expressions and visemes must follow the
  actual audio timeline, not only the LLM's pre-speech emotion. Clear
  animations on cancellation and headless/recovery states. Measure drift.
- **Privacy:** voice/chat should not be copied into the skill ledger.
  Obtain separate consent for mic/capture. Do not convert a viewer chat
  command into a shell command, privileged plugin call or game input.

## Faster intelligence: measurable experiments instead of marketing

STAR already has local model routing and resource leasing. Improve them in
a **paired baseline experiment**, never by enabling every optimization.

| Hypothesis | Test | Keep only if |
| --- | --- | --- |
| Keep stable persona/tool instructions at the start of the prompt; append live state at the end. | Compare prompt prefill times, KV reuse and p95 first-audio on identical repeated turns. | Faster p95 without worse interruption/grounding on paired holdouts. |
| Small reflex model plus stronger planner only for ambiguous goals. | Split sessions across difficulty bins and test rule/quick/strong routing under identical game seeds. | Reliable task completion and speech grounding remain noninferior; tail latency and cost improve. |
| Vision sampling on *change* rather than every frame. | Compare fixed-frequency snapshots with event-led sampling; audit missed game-critical events and GPU FPS. | No increased critical misses, voice delay, privacy exposure or game stalls. |
| Speculative decoding/draft models. | llama.cpp SPEED-Bench per workload on actual 8GB cards, with total VRAM, p95 TTFT and output quality. | Accepted-token benefit beats overhead with stable gaming FPS and no OOM. |
| RAM/offload and model swapping. | Measure cold/warm latency and game 1% lows, not only aggregate tokens/sec. | It beats the local baseline for target workload; no unmeasured latency cliff. |
| Night school from verified game episodes. | Hold out full games, seeds, geometry families and UI layouts; compare frozen before/after policies. | External scorer shows reliable paired wins, fewer violations and no regression. |

Proposed **three-lane scheduling** while the owner is gaming:
(1) game rendering, push-to-talk and avatar lip sync: lowest latency, highest
priority on the streaming PC; (2) game vision/planning and responsive voice
model: scarce per-turn slots; (3) web research, lesson generation, model training,
video synthesis, ray tracing: pause/route to idle Brain 1/Brain 2 where actually
available. Don't run a parallel heavyweight vision LLM and a game + avatar
on an 8 GB GPU merely because they can each fit when run alone.

Measure at least p50/p95/p99 **speech end-to-end**, first audible,
interruption cancel latency, observed game success, per-run verified safety
violations, average/1% low game FPS, GPU memory ceiling, chat backlog, model
cold start, and callback hallucinations. All figures must be compared with
a *frozen baseline on the same hardware*; otherwise don't report a speedup.

## Game creation and general knowledge upgrades after this bridge

1. **Mechanic inference lab:** collect short owner-approved game clips and
   objective state changes; let Star predict action effects; blind-check
   predictions on new seeds. Keep environment/version keyed skill cards.
2. **Game-builder scene integrity:** pair Studio render captures with
   support/contact/overlap tests. Verify missing props, disconnected walls,
   UV/material variation, hitboxes, traversal and animation rigs. Use a
   human-reviewed visual rubric and multiple camera angles; "script ran"
   is not "looks professional".
3. **Studio multi-client mode:** run two/four-client tests for replication,
   race conditions, inventory security, team logic, disconnect and respawn,
   and collisions with the official test service. Use strictly disposable
   places and per-test journals.
4. **Knowledge evidence graph:** distinguish retrieval, model guess,
   externally tested claim and revoked claim. Store sources + date +
   license + checker. General world-knowledge scores must use new held-out
   tasks outside Roblox, including reasoning, STEM and language.
5. **Counterexample-first practice:** if a proposed solution fails,
   generate *new tests* before generating more patches. Keep one frozen
   benchmark split; don't tune repeatedly on the holdout.
6. **Distribution gate:** integrate reviewed PRs behind explicit off-by-default
   feature switches, run complete offline repository CI and Windows Studio
   tests, and get owner approval before touching `main`, installers or OBS.

## Known limits, handoff and validation

```sh
PYTHONPATH=. python3 -m unittest tests.test_game_skill_memory tests.test_stream_moment_memory tests.test_game_stream_bridge -q
python3 -m compileall -q star/game_skill_memory.py star/stream_moment_memory.py star/game_stream_bridge.py tests/test_game_stream_bridge.py
git diff --check
```

The 67 focused tests in this branch were run against synthetic episodes in a
separate Linux checkout. They test API correctness, no-output-before-consent,
partial receipts, missed-audio retry, owner interruption, callback provenance
and action-policy abstention. They do **not** prove reduced real latency,
voice quality, cross-game transfer, Star self-awareness, active learning
improvements, actual Roblox gameplay, TTS, livestream control or full CI.

**Next integration seam:** after #593 and #581 receive review, provide a
*privileged, host-owned adapter* that transfers a scored game event to this
bridge and passes short commentary proposals through the existing stream
director and generation-bound PlaybackGate; measure what viewers actually
hear. Never let the game model itself call `ingest` or `complete_cue`.
