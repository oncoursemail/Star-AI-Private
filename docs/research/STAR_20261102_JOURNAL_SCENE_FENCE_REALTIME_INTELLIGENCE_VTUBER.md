# STAR research update — scene-grounded memory, real-time game intelligence and natural VTuber behavior

**Date:** 2026-11-02
**Status:** A narrow, tested scene-memory correction plus an evidence-based roadmap. The roadmap has **not** been implemented or benchmarked on a live Windows stream.

## 1. Reproduced bug: a conversation could recall the wrong game's moments

StarStage already rejects mismatched signed episode and continuity packets when the director's bound game and the independent host's current-game observation disagree. However, the *ephemeral StreamEpisodeJournal* branch used only `current_game_scope` to select memories and bypassed that shared scope-agreement gate.

Red-state reproduction against the parent of this change:

1. Journal stores a host-attested checkpoint in `obby_v1` and a win in `arena_v1`.
2. The trusted streaming director has transitioned to `arena_v1`, while a second asynchronous host observer still reports `obby_v1`.
3. Public-speaking permission is enabled for a legitimate viewer question.
4. Before the fix, StarStage attached `Earlier in obby_v1, Star reached a checkpoint...` to the answer despite the director being in `arena_v1`.
5. A second failing reproduction bound the director to *no game* yet showed stale `obby_v1` memories.

This is particularly harmful to an expressive VTuber: an apparently heartfelt memory is less convincing when it belongs to the wrong game. It is a *context integrity defect*, not evidence the AI has feelings or experienced an event.

**Fix:** Apply the same `relevant_memory(current_game_scope)` constraint used by signed episode/continuity memory to optional journal retrieval. A bound no-game state, a bound/observer disagreement, or mismatched scope blocks journal recall. A matching game still recalls host-attested moments. There are no new model invocations, data stores, network calls or game inputs.

**Regression:** Tests explicitly prove both bad cases failed before correction, that the viewer's question is still scheduled without an unrelated memory, and that a matching bound game still recalls its own checkpoint. Existing opt-in and moderation gates remain unchanged.

## 2. Next intelligence architecture: two clocks, two budgets, one verified action

### Fast, live clock (reactive gameplay)

`GameDeadlineRouter` + `RealtimeGameLoop` should admit a cheap reactive model only when recent *host-measured* p95 latency plus input-dispatch reserve fits the remaining scene lease. Use a session-specific compact context: goal, observable game state, allowed symbolic actions, fresh frame digest, top one or two relevant verified tactics. Do not interrupt gameplay to ask a giant teacher model.

`finish()` must recheck the scene, confidence, stream pressure and focus and never double-charge the latency of an inference that already completed (addressed in the preceding stacked PR). The trusted host retains sole authority to claim an identity-bound permit and release keys. This repair adds an analogous consistency check for *speech-memory* at its own scheduling boundary.

Measure **capture-to-action p50/p95/p99**, complete misses, false actions, focus and key-release failures, OBS dropped frames, frame age, voice delays and GPU memory, not just generated tokens/sec.

### Slow, offline clock (teacher learning)

After gameplay, replay only owner-approved and locally recorded observations. Have a stronger teacher analyze failures, propose 4–8 strategy variants, and run bounded simulated episodes where available. Adopt a lesson only when an independent held-out evaluation improves *game progress, win rate, safety and latency* relative to the prior verified lesson. Give each lesson a game/version/map signature, evidence digest, expiration policy, and rollback pointer.

The October 14, 2026 **RealtimeBench / TORSI** paper evaluates 180 continuously running game tasks across six types and reports that a fast student's average progress score increased **13.51 to 24.19** after two learning rounds. These are the **authors' experimental results**, not a result achieved by Star. Adapt the hypothesis, do not claim it transfers without measurement.

Source: https://arxiv.org/abs/2610.20665

### General intelligence beyond games

Build a capability router, not a single enormous prompt. Distinguish: live action; code/Roblox creation; verified public knowledge; episodic memories; long research. Each route gets its own context budget, source/citation policy, tool permissions and evaluation task bank. Track unresolved questions, confidence and factual corrections over time.

Define intelligence progress as **higher held-out task success**, **fewer verified factual errors**, **improved cross-project transfer**, **lower cost per solved task** and **faster end-to-end latency**, with per-domain regressions blocking promotions.

## 3. An actually convincing streaming persona

A natural VTuber needs timing and continuity, not nonstop chatter or a fictitious human identity.

* **Listen:** test end-of-turn detection with prerecorded labeled pauses, guest speech, owner interruptions, echo, packet loss and silence; compare false cuts and tail latency, not just average reaction speed.
* **React:** choose a verified game observation plus context-aware short response; reserve gameplay-critical quiet, avoid automatic celebration on unconfirmed wins, and prevent stale scene memory.
* **Speak:** measure from viewer utterance end to **physical audible output**, not to language-model completion. Have queued speech cancellations revoke the corresponding rig motions.
* **Animate:** drive bounded expressions from host-grounded events. VTube Studio plugins support hotkeys and injecting parameters; the host must invalidate old expression batches after scene/voice handoffs.
* **Remember:** factual recollections require per-game provenance and independent public-speaking approval. Phrase them as **Star's logged gameplay events**, never a fake human childhood or fabricated personal history.
* **Socialize:** maintain a consistent original persona, interests and goals, but don't misrepresent human identity, sentience or independently earned achievements. Astro/Amber interactions can be authored with grounded events and audience-safe scripted play.

Sources:
- VTube Studio plugin API: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- OBS websocket API and authentication: https://github.com/obsproject/obs-websocket
- Pocket TTS (October 2026 CPU-oriented 18.2M/6.9M/1.9M English models): https://github.com/kyutai-labs/pocket-tts/blob/main/README.md

**Practical voice A/B test:** compare baseline TTS vs CPU Pocket TTS with identical scripted queries on the actual Windows PC: first audible chunk, complete speech, intelligibility, expressiveness, word errors, speech interruption, game p1 FPS, CPU use and added VRAM. Smaller models are not automatically more human sounding.

## 4. Fast on 8 GB GPUs without harming gameplay

Use llama.cpp server slot telemetry, prompt reuse and continuous batching as candidate optimizations, but don't assume batching always reduces single-user tail latency. Pin identical models/quantizations/context lengths and compare **under an active game + avatar + offline OBS recording**. Route expressive TTS or knowledge indexing to CPU/another permitted machine when GPU pressure demands it. A model fitting in static idle VRAM is not proof it fits under live game rendering and capture.

SPEED-Bench can compare speculative decoding settings for different prompt lengths/concurrency and report draft-token acceptance; verify on Star's hardware before changing defaults.

Sources:
- llama.cpp official server architecture: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Suggested opt-in `live`, `rehearsal`, and `offline-study` profiles:
- Live: hard deadline, cap outstanding work, drop stale advice, prioritize game + audio + encoder.
- Rehearsal: collect time-aligned GPU, OBS, audio, rig and action diagnostics without broadcasting.
- Offline study: broader context, batch/evaluate multiple strategies when rendering isn't competing.

## 5. Game creation and autonomous play, verified rather than decorative

Game creation loop: inspect existing place and intended level design → author small Luau/asset diffs → run syntax/lint/type checks → inspect collision geometry, anchors, attachments and prop dimensions → run a Studio playtest → verify gameplay visually and through game-state assertions → repair **only reproducible failures** → compare against approved reference captures.

Roblox StudioTestService supports scripted multiplayer scenarios, including simulated joins/disconnects. VirtualInput can exercise UI flows in Studio. Use these in permitted test environments rather than botting public competitive games or bypassing anti-cheat. Source: https://create.roblox.com/docs/studio/testing-modes

For gameplay mastery, start with controlled game arenas, validated symbolic input adapters and reproducible seeded challenges. Maintain paired teacher/student curricula, score on **unseen levels** and stop if newly learned strategies increase unsafe or unresponsive inputs.

## 6. Acceptance gates for the next milestone

1. **Memory:** randomized, asynchronous A→B→no-game→A scene changes, all with independently varied observer lag; zero journal or signed-memory passages for the wrong bound scene, and no legitimate viewer question dropped.
2. **Gameplay:** no scene-expired permit dispatched; no invalid key held after stop; compare latency, win rate and misses across at least two independent challenge seed sets.
3. **Streaming:** nonbroadcast Windows capture with actual microphone, game, TTS, avatar and OBS running together. Report real physical audio onset, sync drift, speech-overlap fraction, frame drop counts and resource headroom.
4. **Human-likeness:** blinded A/B listening preference with meaningful silence, non-scripted utterances and context faithfulness; no deceptive biography or imaginary wins; operator retains clear AI disclosure.
5. **Rollout:** leave capabilities OFF unless specifically approved; preserve offline tests and per-feature rollback. No external broadcast, new spending, account actions, self-modifying model updates or unsupervised public-game inputs are enabled by this patch.

**Result of this change:** repaired a specific cross-lane memory-context defect with red/green tests. It does **not** increase model parameter intelligence, inference throughput, game win rates, voice naturalness or livestream readiness by itself.
