# STAR AI — playback-truth intelligence, gaming, performance and natural VTuber research

Date: **2026-10-30**. Status: **candidate code + research**. Local verification only. No voice call, OBS broadcast, game account, live Studio place, model server, hardware setting or deployment was modified. The source repository is **public** even though its name contains `Private`: never publish owner secrets, real chat, recordings, customer data or keys.

## 1. Why this change is different: stop teaching Star things she never said

An audit of the actual production `star/voice/call.py` found a causal continuity error. On an ordinary *non-interrupted* turn, it previously wrote **all generated speech chunks**, or even a fallback of raw model text, into Star's history. That could happen when TTS crashed before producing any PCM, when the device accepted but discarded queued output, or when only part of the utterance was played. Star might subsequently behave as though the human listener had heard a promise, explanation or game victory she had never spoken.

**Candidate implementation:**

- `CallSession._finish_reply()` always uses callback-reported `speaker.played_seconds()` (or the already-snapped pre-interruption playhead) and the existing per-sentence audio spans to reconstruct the **conservatively estimated spoken portion**. Never use generated model text as proof of on-air speech.
- A silent queued utterance is reported as an output error rather than marked as a successful reply. Invalid, nonfinite or unavailable callback telemetry fails closed; source exception messages from devices are not republished as model text.
- Already queued speech is allowed to finish **even if model generation or a subsequent TTS sentence fails**. This prevents the new truth requirement from wrongly forgetting audio that actually played.
- An **opt-in** `CallConfig.playback_stall_seconds` (default `None`) stops a stuck output queue if its pending duration fails to decrease for a configurable 0.05–30 seconds. It is **not** a timeout on the length of a legitimate speech turn. On timeout, stop queued audio and use existing interruption recovery.
- `TurnMetrics.heard_seconds` now records the device-reported played duration on successful turns too, not just cancellations.

**Important measurement limit:** `SoundSpeaker.played_seconds()` counts samples consumed by its sounddevice callback, not verified air-pressure at the viewer's ear, not captured OBS audio and not proof of what an individual comprehended. Likewise, partial-sentence word estimates based on audio duration are conservative **approximations**, not aligned forced-transcription. Exact caption timelines require word/phoneme alignment and independent output capture.

### Regressions to require before approval

| Failure case | Previously possible | New candidate behavior |
|---|---|---|
| Model replies but TTS crashes before PCM | Raw model text may be stored as spoken | No audio-confirmed text enters history; error event remains |
| Speaker discards audio without callbacks | Queued chunks treated as heard | Heard text empty, output error |
| Only first half of one sentence plays | Whole sentence remembered | Conservative prefix only |
| Telemetry is NaN, absurd, unavailable | No trusted non-interrupted playback check | Fail closed; do not invent speech |
| LLM errors *after* one sentence entered playback | Partial audio may still be draining during history update | Drain pending output before recording heard portion |
| Audio callback queue freezes | Worker could wait indefinitely | Optional progress watchdog cancels and silences |

This is a *continuity and recovery* improvement. It does **not** make the LLM smarter, speed up token generation or verify acoustic audibility.

## 2. Next engineering priority: first perceived sound under live load

Earlier STAR branches added first-visible text, TTS-ready-phrase latency and PCM envelope analysis. Measure a **complete** trace on the same monotonic host clock:

`verified game event → selected speech intent → first visible token → first speakable phrase → first TTS PCM → callback-consumed PCM → OBS-mixed audible PCM → synchronized avatar mouth frame`.

An apparently faster model may provide the first word earlier but stall the TTS, overfill its audio queue, reduce Roblox FPS or produce low-quality facts. A better latency metric is the time from a trusted gameplay event or confirmed turn end until an **independently captured audible first phoneme**; explicitly record failures/cancellations. For two separate PCs, correlate using observed request/ack timestamps or a shared capture host; never blindly subtract unrelated monotonic counters.

LiveKit's 2026 turn handling documentation distinguishes client-side and model-native turn detectors and warns that server-side realtime turn detection overrides most client interruption options. Its audio `v1-mini` model can run locally on CPU. Evaluate whether it reduces awkward interruptions and wasted audio *with the existing host turn-taking gate*, rather than stacking incompatible VAD detectors.

Sources:
- https://docs.livekit.io/agents/logic/turns/
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://livekit.com/blog/turn-detection-and-interruption-handling

**Acceptance experiment:** 40 matched, consented, synthetic scripted turns (questions, backchannels, overlapping speech, interruptions, silent output, model/TTS errors), crossed with idle/gameplay loads. Report paired p50/p95 first independently observed PCM, missed/cut-off utterances, false interrupts, CPU, game FPS p1/p5 and avatar-to-sound frame offset. Do not log words or viewer identities in public CI.

## 3. Intelligence architecture: more successful actions, not more modules

STAR already has a large collection of cognition, memory, Studio inspection, learning ladder, game trial, motion, narration and QoS components. The main opportunity is **one witnessed, reproducible task-to-outcome route** and removal of duplicated inference passes.

### Three decision speeds

1. **Reflex layer (20–60 Hz when the game permits):** game-safe deterministic control rules, button release deadlines, collision/pause/emergency interrupts. Avoid an LLM call per frame. In live public multiplayer, obey game policies and avoid unfair control or automation; prefer private authorized games for AI practice.
2. **Tactical layer (1–5 Hz, subject to GPU budget):** scene crops, HUD/object identification, near-term actions, verified state changes and predictions with confidence. Reject stale screenshots before actions; never overwrite new state with late VLM results.
3. **Strategic layer (per objective, not per frame):** long-horizon plans, exploration hypotheses, physics and game-mechanic models, multi-step repair and game-creation decisions. Escalate to expensive models only when the fast route's independently checked output is insufficient.

The tactical and strategic layers write the same bounded episodic record: scope/version, consent and action class, observation digest or permitted private pointer, prediction, **independent verifier result**, error class, and retention policy. A model's own text claiming victory is not verification.

GameWorld (April 8, 2026) benchmarks 34 games/170 tasks with state-derived outcome metrics; its results motivate testing success, control timing, navigation and held-out transfer rather than conversational descriptions of wins.

Source: https://arxiv.org/abs/2604.07429

### Skill growth with real generalization

Use the existing `GameplaySkillBank`, `GameLearningLadder`, `GamePortfolioPractice` and signed trial receipts. Each practice scenario should have a matched *unseen* evaluation on a different seed/map or mechanic variation. Store the improvement from before to after practice **separately** from the self-directed practice outcomes. Fail or revert if a change only improves familiar maps. Measure invalid controls, game over/reset rate, completion time and successful transfer into a second game genre.

**High-value additional skill classes:** UI visual balance and motion judgment, Luau API reasoning, physical prop placement, 3D collision topology, TTS emotional pronunciation, social turn timing, video-event causality, dialogue recall, and safety when choosing tools. Each class needs separate tests; no single “intelligence score” proves mastery.

## 4. Better game creation: Star must finish what she builds

Roblox announced built-in Studio MCP plus programmatic playtest controls and simulated player inputs on **March 5, 2026**. Treat it as a *test-host adapter*, not permission to modify any public game. Before edit, inspect the real Explorer scene graph, scripts and object ownership. After a bounded edit, require executable verification.

1. Run Luau parsing/static analysis and server/client authority checks.
2. Verify mesh bounds, hinges, attachments, collision groups, path continuity, spawn/nav hazards and object references against intended layout.
3. Capture independent screenshots or short clips; use paired visual checks for camera composition, UI readability, animation quality, clipping, z-fighting, materials and lighting.
4. Play an entire route with scripted and AI-driven actors; verify win condition, saves/restores, and reopening the experience.
5. Keep non-regression holdouts separate from practice; attach trace digests and a small falsifiable evidence report to Star Core Forge.

Source: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

**Go/no-go:** performance on 10 private, unseen miniature Roblox objectives must not regress from baseline on completion %, crash %, time-to-win, collision/geometry error count, and human-rated aesthetic quality. A passing script suite alone does not qualify.

## 5. Faster local AI with Brain 1 + Brain 2

The Linux development host has previously been observed running multiple `llama-server` processes; those facts are historical snapshots, not current capacity guarantees. The future RTX 4060 8 GB streaming PC must reserve gaming, OBS, display and avatar resources. Place CPU-friendly tasks (small speech model, deterministic control, indexing, retrieval, telemetry) on CPU/RAM when measured efficient. Run large model planning or image/video rendering on Brain 1 or only in idle budget windows. Avoid starving the UI or game to gain token throughput.

**A/B candidates, in this order:**

- Prefix/prompt cache and stable knowledge/skill prefixes; count actual cache-hit tokens and first-use misses, not only tokens/sec.
- Model routing: small local model for clear low-stakes turns, stronger model for uncertain or high-impact reasoning; inspect verified accuracy and *complete-task* latency on unseen cases.
- llama.cpp speculative decoding with n-gram or compatible draft models. Its SPEED-Bench reports latency and draft acceptance; accept only a paired end-to-end win with the same model weights, context, game load, correctness and energy budget.
- Backpressure using STAR's existing memory PSI and QoS governors; do not throttle merely because swap is allocated. Use actual stalls, queue depth, and frame-time drops.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**Performance acceptance:** lower p95 first-audible latency **and** equal or better correctness, with stable Roblox p1/p5 FPS, OBS frame drop rate, memory pressure and no spontaneous output silencing. A microbenchmark improvement alone is insufficient.

## 6. Personality and natural AI VTuber presentation

A convincing streamer needs a coherent *experience-based personality*, not a fabricated human past. Continue Star's distinctive warmth, dry humor, playful cat/puppy modes, occasional jokes, expressive eyes, black-and-gold mascot design and physically plausible twin-tail hair, while transparently identifying her as an AI.

For each verified event, coordinate **attention → speech choice → emotion intensity → facial motion → body reaction → audio delivery**. A dramatic moment can demand silence; don't interrupt an intense platform jump to answer a routine chat question. Let her laugh only when her dialogue actually has a humorous beat, with breath and expressive timing derived from *current* audio/rig events rather than random effects. Use a bounded moment buffer and measured reaction cooldowns so she can return to chat after gameplay focus without reading every message or replaying stale reactions.

Speech voice candidate: Kyutai's Pocket TTS **v4.0.0 (Oct 20, 2026)** introduced small English 18M/7M/2M families and v4.0.1 **Oct 21** fixed issues including small-model pronunciation. Their publisher describes CPU-oriented streaming, but there is **no Star-hardware quality benchmark** yet. Try representative phrases, Roblox terms, emphasis, laughter/hesitations and pronunciation before replacing a stable voice; never clone a person without permission.

Sources:
- https://github.com/kyutai-labs/pocket-tts/releases
- https://github.com/kyutai-labs/pocket-tts/blob/main/README.md

A humanlike feel is measured via blinded listener ratings of timing, clarity, nonrepetitiveness, humor and reaction accuracy, plus objective first-audible lag and glitch rates. It cannot be established by an AI's self-assessment or claims of consciousness.

## 7. Core Forge: autonomous improvement with proof

STAR's internal Core Forge, rather than GitHub, should eventually own experimentation, branching, test orchestration and rollback. GitHub remains an optional publication and review mirror. Implement **promotion receipts** that say exactly what code changed, which previously unseen tests ran, which build/host produced results, the baseline-vs-candidate confidence interval, regressions, privacy exposure classification and rollback instructions. Reject unauthorized external actions, evidence reuse and unverified claims of learning. Automatic promotion is only appropriate for reversible, pre-authorized low-risk changes with passing independent gates; require owner review for public publishing, financial activity and high-impact external changes.

## 8. Concrete integration sequence

**First:** review this playback-truth patch, run the offline voice suite and a real isolated sounddevice callback/speaker test; inspect error and interruption events. Rehearse “I won the level” with a deliberately muted output device: the next turn must not assume the audience heard it.

**Second:** build a private Windows Studio+OBS rehearsal trace with signed objective events, audible PCM witness, synchronized avatar frames and game-frame telemetry. No live broadcasting required. Connect exactly one narrow event → response → measured output path before adding more modules.

**Third:** run a paired learning study on unseen game maps and a paired model/TTS latency study under equal hardware load. Only promote changes if independent metrics improve without regressions; keep owner-controlled rollback.

## Test evidence and exclusions

The code is evaluated using deterministic synthetic speaker/model/TTS fakes and existing voice regression tests, not a real speaker, Twitch/Discord session, OBS recording or live Roblox Studio game. Results of this run must be filled into the PR only after the final test command completes. No hardware speedup or underlying intelligence gain is claimed.

All new permissions/automation must remain **off unless explicitly enabled**. The playback-stall watchdog defaults to **off**. Changing the audible-history calculation is a correctness fix within existing voice call behavior, not a newly activated microphone or broadcaster.
