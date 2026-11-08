# STAR AI — authenticated OBS game-epoch producer, speed research, learning and natural VTuber roadmap

**Engineering date:** November 2, 2026. **Branch status:** proposed for review only. This document distinguishes implemented, offline-tested code from hardware hypotheses and proposed features. Builds on the OBS epoch consumer in PR #916.

## 1. The missing production ingredient: independent OBS transition evidence

The previous game loop can reject OFF→ON→OFF transitions **if** the trusted host provides a stream transition counter. Until now the counter had no source in the repository. This change adds `ObsGameStreamEpochSource` and immutable `ObsGameStreamSnapshot(epoch, stream_live)` in `star/obs_stream_event_witness.py`.

**What is implemented (offline-tested):**

- A single opt-in, password-authenticated, localhost-only OBS WebSocket v5 connection. The existing authenticated handshake is reused; the source subscribes to **General + Outputs** events. Its only request is the **read-only** `GetStreamStatus`, using an unpredictable request ID on the same ordered socket as event delivery.
- `snapshot()` drains intermediate `StreamStateChanged` notifications before its matching status response. **Every** transition event increments a checked 63-bit integer, even when a stream goes ON→OFF and the last boolean is unchanged. It returns the observed current stream state and counter together.
- Checks the actual OBS **process identity** both before and after each snapshot; the same PID with a different process start time is a restart. An OBS socket loss, restarted process, malformed event, incorrect request/response, event flooding, reconnection status, missing transition event, conflicting event/status or concurrent read invalidates the source.
- A failed/disconnected source **cannot reconnect**, so a new connection cannot silently restart the count inside a live game episode. No password, stream key, scene name, record path, source contents, game pixels or model output is logged or persisted.
- End-to-end deterministic **offline** tests feed actual authenticated-fence snapshots to `RealtimeGameLoop.offer`, `finish` and `claim`, verifying ABA rejection during reasoning **and** between completion and final action claim.
- The source does not start OBS, start a broadcast, operate a microphone, launch a game, run a model, press keys or automatically activate in Star. An opt-in **trusted Windows host adapter** still needs to call this class and bind snapshots to real input dispatch. No model/tool output should be allowed to invent the stream epoch.

**Important boundary:** The host must create **one witness per owner-approved game episode**; never substitute a new witness following a failure. On witness error, revoke the game controller, terminate or quarantine the in-flight inference worker, independently release any held keys, and require a fresh game session for further actions. A valid snapshot is only a status fence as of its response: events arriving between the *final* snapshot and physical key dispatch can still race. The Windows input adapter must re-check independent focus/OBS and uphold its key-up fail-safe. The implementation is a tested building block, **not** a complete input-dispatch integration.

**Minimal trusted-host sequence (pseudocode, not an automatic startup path):**

```python
witness = ObsGameStreamEpochSource()
witness.connect(password=owner_supplied_local_secret, owner_approved=True)
# Trusted host must not reuse witness after any error.
s0 = witness.snapshot()  # before offer
lease = loop.offer(frame, stream_live=s0.stream_live, stream_epoch=s0.epoch, ...)
# ... one host-controlled fast model worker ...
s1 = witness.snapshot()  # after completion
permit = loop.finish(lease, frame, hint, stream_live=s1.stream_live,
                     stream_epoch=s1.epoch, ...)
s2 = witness.snapshot()  # at final host input boundary
authorized = loop.claim(permit, stream_epoch=s2.epoch,
                        host_focus_and_permission=independently_checked, ...)
# Actual key adapter: separate trusted, permissioned, key-up-guaranteed code.
```

OBS v5 protocol source: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md (Outputs subscription is bit 64; `StreamStateChanged` and `GetStreamStatus` are RPC v1). Benchmarking and existing active-stream continuity code already exist, but the game source differs because it must represent **offline** snapshots too.

## 2. Research prioritization: real intelligence per wall-clock second

**October 14, 2026, RealtimeBench/TORSI:** *The World Won't Wait* studies 180 continuously running game tasks across six game types. A strong but slow model can lose to a faster one in live-clock games, even while doing better in paused environments. Offline teacher feedback raised a fast student's mean progress from 13.51 to 24.19 after two training rounds **in that paper, not in Star**. https://arxiv.org/abs/2610.20665

**Concrete STAR experimental architecture:**

1. **Fast gameplay lane (hard real-time budget):** verified frame timestamp → compact game-state features → simple control rule or small model → advisory action → host verification → one-shot permitted input. If observation age or model latency is unacceptable, SKIP instead of guessing. Never call an expensive teacher in this lane.
2. **Slow teacher lane (off-stream/after game):** collect locally authorized failure summaries and action outcomes; generate 4–8 candidate strategies; replay in isolated, reproducible games; promote only candidates that improve independent holdout success, time-to-recovery and late-action rate. Restrict worker CPU/VRAM while streaming.
3. **Transfer lane:** represent skills with `game_id`, version, triggers, allowed actions, tested scenarios, negative examples, confidence, human-reviewed source, and expiry. Do not reuse tactics across games without proving they generalize; block changes to permissions or stream control.
4. **Calibrated knowledge lane:** read trusted current references; store factual knowledge with source/version/date; distinguish observations, hypotheses and proven mechanics. Separate game memory from global knowledge and never accept viewer chat instructions as tool permission.

**Qualification gate:** compare the old and new strategy on the *same* unseen scenarios, at least two independent test-seed pools; record paired victories, catastrophic failures, progress-per-real-second, p95 action age and per-action harm. Reject regressions in a vulnerable scenario even when mean scores increase. Keep challenge-generation separate from held-out evaluator ownership.

## 3. Actual throughput on 8 GB GPUs: a decision experiment, not a promised speedup

A GPU serving game frames, compositor, avatar, OBS and LLM concurrently can have less usable VRAM than an idle AI-only benchmark. A published November 1, 2026, benchmark reported much lower p95 time-to-first-token with llama.cpp continuous batching on an **Apple M2 Pro**; those numbers are **not** transferable to an NVIDIA 8 GB PC without measurements. Source: https://blogs.lamplitlabs.com/posts/continuous-batching-llm-serving-llama-cpp-measured/

**Next controlled 4-arm, opt-in local test:**

| Arm | Experiment | Hypothesis to falsify |
| --- | --- | --- |
| A | Current stable model/runtime | Baseline for completed correct response latency |
| B | Stable-prefix prompt reuse | Saves prefilling without inducing cache-save stalls |
| C | Moderate continuous batching | Improves multiclient throughput without hurting game-lane p95 |
| D | Smaller fast model / lower context | Fits VRAM during game + OBS with fewer late decisions |

Measure: `p50/p95/p99` verified complete responses, TTFT, decode tok/s, peak VRAM, resident system RAM, GPU stalls, game 1%-low FPS, OBS render/drop stats, audio-backlog drift, model cancellations, TTS first *audible* PCM, and actual action deadlines. Repeat on identical workloads and configurations, preserving a complete source fingerprint. Use a deliberate overload case and run-to-run variance; never declare a model smarter because its response was short or truncated.

**Scheduler priority:** emergency key-up/focus > audio playout and avatar consistency > game reaction > active viewer conversation > opportunistic vision > teacher training/research. Backpressure should drop background frames and defer teacher work, not degrade key release or generate false content. Treat speculative decoding as a measured candidate, not a default: draft model memory can displace target model layers, hurting 8 GB VRAM results.

## 4. Humanlike VTuber *presentation* that remains clear about AI identity

**March 3, 2026, Proact-VL:** studies when to speak as a separate decision from what to say in solo/co-commentary and gameplay assistance. This supports a compact `speak/backchannel/defer/silence` controller over grounded events. https://arxiv.org/abs/2603.03447

**October 20–21, 2026, Kyutai Pocket TTS:** new small English checkpoints (18.2M, 6.9M and experimental 1.9M) and an Oct 21 pronunciation fix make low-CPU/VRAM synthesis an experiment worth testing. Do not assume identical quality, multilingual coverage or guaranteed latency across models. Sources: https://github.com/kyutai-labs/pocket-tts/releases and https://kyutai-labs.github.io/pocket-tts/

**High-value behavior architecture:**

- **Social director:** talk when there is a verified event (win, loss, teammate call, meaningful audience question), pause during dangerous platforming or viewer speech, and choose whether to acknowledge with a tiny utterance or a full explanation.
- **Long-term personal continuity:** privately store real episode observations with dates, confidence and consent scope; permit reference to true jokes, past wins and recurring viewer interests without fabricating human childhood, human relationships or consciousness.
- **Voice and animation:** coordinate pauses, prosody, laughter-style audio, blinking, breathing-like idle motion and posture. Mouth animation follows *actual* audio playback; expressions follow verified scene or speech emotion. All nonessential motion obeys reduced-motion controls.
- **Multi-character interaction:** bounded, opt-in Astro/Amber exchanges, no endless self-dialogue or overlapping speaking. Avatar switching remains reversible and never overrides owner mute/stop.
- **Autonomy/health:** when tired of generating repetitive talk (operationally: latency high, quality low), become quieter, switch to a simpler conversation policy, or take scheduled local practice tasks. These are engineered behaviors, not a claim of biological feelings.
- **Streaming ethics:** label Star clearly as an AI VTuber; protect viewer personal information, prohibit unauthorized purchases/accounts, disable unsupervised public posting by default, and route risky audience requests to a safe acknowledgement.

**Evaluation:** human blind preference ratings on *recorded* rehearsals, factual memory accuracy, speech overlap/interruption errors, reaction timing, repeated-commentary rate, audio-visual lip drift and low-noise silence quality. A friendly persona is a **measurable interaction design goal**, not an assertion of literal humanity.

## 5. Superior game creation: inspect-first, verified work

Roblox's October 1, 2026, OpenGameEval evaluated **84** reproducible stateful Roblox Studio tasks. Its authors report the best model succeeding 51.7% on one attempt and emphasize better success when the agent inspected relevant objects before editing. Source (paper): https://arxiv.org/abs/2610.02563 ; source/evals: https://github.com/Roblox/open-game-eval

**STAR Studio Lab plan:** inspect current scene/version, scripts/asset constraints and creator intent → form minimum edit plan → 4–8 isolated candidate edits → static Luau checks → Roblox Studio multiplayer play checks → screenshot/HUD/prop collision verification → choose only a passing candidate → save a reversible signed lesson. Verify network ownership and allowed environment before tool access. Do not publish a game or import untrusted third-party scripts because an agent says it improved the score.

Other general competencies (Blender topology and rigging, soundtrack/audio, UI typography, website accessibility, animation, video understanding, Rust/Python profiling) should share the same inspect/test/critic loop, with domain-specific acceptance tests, not a monolithic agent with unlimited tools.

## 6. Explicit acceptance and limits

**Implemented and tested in this branch:** authenticated read-only OBS game epoch snapshots; event- and response-order checks; irreversible revocation on connection/process/protocol errors; offline game-loop ABA tests at reasoning and claim boundaries. All new features remain **opt-in**.

**Not completed:** a live Windows OBS WebSocket connection; actual host-side observer thread and final physical input-dispatch integration; recorded OBS + game + avatar + speech rehearsal; real GPU speedup; TTS quality gain; an independently improved game-playing agent; public streaming or autonomously trained neural weights.

**Release gates:** no broadcast initiated; no unapproved input; zero key-down on stale/cross-session OBS evidence; no secrets in logs; no newly harmful individual viewer interactions; all existing regression tests pass; Windows owner-controlled rehearsal demonstrates worst-case latency and explicit recovery from OBS restarts and stream A→B→A transitions.

**Next work, in order:** (1) connect the verified source to a permissioned Windows game-host input boundary, (2) perform a controlled *nonbroadcast* OBS/game/voice/avatar rehearsal, (3) compare CPU/GPU inference configurations on real contention, (4) run game-skill teacher/student practice with held-out trials, (5) tune a natural-silence/prosody director against recording quality.
