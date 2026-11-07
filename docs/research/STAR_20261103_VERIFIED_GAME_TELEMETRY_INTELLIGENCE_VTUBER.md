# Star AI — Verified game-state learning, faster local intelligence and believable VTuber presence

**Research / engineering entry:** 2026-11-03. **Status:** new opt-in offline-tested game-state witness plus an evidence-based implementation plan. This is **not** a claim of a live game win, a public stream, faster measured inference, or a production-safe Windows integration.

## 1. Highest-impact finding: distinguish game truth from a convincing story

The preceding signed-moment journal verified that a trusted host *said* a checkpoint or victory occurred. HMAC does not establish whether that host observed it. A language model should never get to pick an arbitrary "win" and then ask a signing function to bless it.

The new `star/game_state_transition_witness.py` is a narrow host-side gate for **owner-controlled games or test environments exposing authoritative engine/server telemetry**. It ingests only canonical frame number, round number, phase and checkpoint; the host's own monotonic clock supplies time. One observation establishes a baseline; a second notices a state change; a third corroborates it. Only a corroborated checkpoint/win/loss becomes a signed `GameMoment` usable by the protected session journal. It refuses reset-to-old rounds, repeated or unrealistic frame jumps, reversed time, missing sample intervals, checkpoint regression and terminal-state reversals, latching off on discontinuity. Session ID + HMAC bind that factual claim to the live journal session, with replay and out-of-order checks in the journal.

**Trust boundary:**
```text
Owner-authorized game / Roblox Studio test
  -> engine-owned read-only telemetry  [NOT screenshot inference / client chat]
  -> isolated host process: transitions + temporal confirmation
  -> session-bound HMAC receipt
  -> StreamEpisodeJournal(receipt_key=...) -> factual, private recap suggestions
  -> public-content filter + turn-taking/voice/avatar governor -> OBS preview
                                                              [broadcast still OFF]
Model, chat, web, and gameplay scripts cannot call the host signer or read its key.
```

This is defense in depth, not proof that a game client or its source is honest. The new module **does not connect to an actual game process**, authenticate the engine's API, transmit IPC, control a game, play audio, or start OBS. Those require a separate owner-authorized source/host. Other people's online games may lack accessible authoritative telemetry; screenshot-based guesses must remain **unverified** and can never be represented as authoritative wins.

**Integration contract for an owned test game:**

1. Start a fresh owner-approved game session, allowlisted process/place identity and journal with a fresh per-session signing key (host only). Enable the journal and bind its `session_id` to the isolated observer. A shared Python process containing model-executable code is **not** secret isolation; use a separate process and narrowly scoped IPC before production.
2. Source `GameStateSample(frame, round_id, phase, checkpoint)` from a **trusted engine/test harness** at consecutive live frames; enforce focus, game identity and watchdog externally. This interface assumes monotonically increasing frame/round/checkpoint semantics; adapt different game designs in a vetted translator rather than weakening validation silently.
3. Treat `None` as no fact; for a returned `AttestedGameMoment`, submit `journal.record(result.moment, now_s=result.now_s, host_observed=True, receipt=result.receipt)`. No direct unsigned moment may be recounted as a verified outcome.
4. Latch off on source read errors, disconnections, frame gaps, session mismatch, restarted game processes, stale window or watchdog uncertainty. Reauthorize a **new journal** on restart. Do not auto-restart or self-broadcast.
5. Run offline negative controls: forged wins, one-frame victory flicker, repeated snapshots, round regression, changed MAC fields, stale sessions, concurrent ingest, chat-injected claims, paused world clock, and host crash between action and receipt.

**Future enhancement:** a host-signature per process/engine instance, explicit observation heartbeat, monotonic world ticks taken from server/engine rather than UI frame counters, and a sealed IPC source channel to prevent model-driven injection. A robust independently verifiable screenshot source is useful for perception, but is **not** enough to authenticate match victories in an unknown game.

## 2. Research that changes the engineering priority

- **GameWorld, April 2026:** 34 games / 170 tasks, with outcome-verifiable metrics derived from serialized game state rather than LLM judgement. Its real-time track intentionally leaves games running while models reason, unlike paused benchmarks. Adopt the same separation between *true outcome*, *visual inference*, and *deadline*. Source: https://gameworld-project.github.io/ (see paper arXiv:2604.07429).
- **Roblox built-in Studio MCP, March 5, 2026:** Roblox introduced Studio's built-in MCP and playtest automation (an important alternative to brittle external UI simulation); see https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643. **StudioTestService**, introduced December 4, 2025, can script play, run, and multi-client tests; see https://create.roblox.com/docs/reference/engine/classes/StudioTestService. May 28, 2026 expanded testing/virtual input APIs: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854. Prefer these official channels in **owned** projects.
- **Microsoft Proact-VL, ICML May 2026:** the companion should learn when to talk, *not simply what to say*, across solo commentary, co-commentary and guidance. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- **Kyutai Pocket TTS, October 20–21, 2026:** v4.0.0 introduced `english_18m_2026-10`, `english_7m_2026-10`, and experimental `english_2m_2026-10`; v4.0.1 corrected a pronunciation issue for sub-20m models. This is an efficient-CPU candidate, not proof of acceptable expressive delivery. Source: https://github.com/kyutai-labs/pocket-tts/releases
- **VTube Studio:** official websocket plugin API provides avatar control surfaces when authorized; integration must preserve local authentication and the app's parameter/data contract. Source: https://github.com/DenchiSoft/VTubeStudio/wiki
- **Roblox OpenGameEval:** a real-world test harness for coding agents, useful for inspect-before-change and executable verification, separate from actual game-playing competence. Source: https://github.com/Roblox/open-game-eval
- **llama.cpp:** instrument prefill, decode, TTFT, KV-cache footprint, batching and draft acceptance; no 8GB GPU can be treated as unlimited context. Prompt-cache and speculative decoding each need paired A/B tests under the target gaming + OBS workload. Source: https://github.com/ggml-org/llama.cpp

## 3. Star's full local architecture: high IQ **and** fast response

Use *different latency classes* rather than forcing one model to do everything:

| Workload | Behavior | Baseline measurement | Safe fallback |
| --- | --- | --- | --- |
| Reflex / game control | deterministic short action, bounded deadline, host-signed results | correct actions completed **before** deadlines; action-to-input ACK and actual world progress | neutral controls / stop |
| Perception | small bounded image or telemetry delta, tracks visible objects across frames | target recall, 90th/99th percentile freshness, stale-frame errors | do nothing, request fresh frame |
| Tactical reasoning | short rolling game context and curated retriever | plan success over unseen seeds / levels | smaller known-good route |
| Teacher / self-training | offline stronger model, self-play, build-fix-verify loops | held-out task success and skill-transfer improvement | rollback bad skill, keep old |
| Speech/dialogue | priority-based conversational timing and streaming TTS | first audible speech time, false interruptions, pauses, user-rated quality | simple short acknowledgment or silence |
| Long-term knowledge | indexed verified docs, version provenance, time-sensitive recheck | citation accuracy, retrieval precision, stale-knowledge errors | mark uncertain, verify before acting |

**Architecture:** state/event capture -> policy router -> fastest sufficiently capable model -> host action gate -> measurable environment outcome -> proof-aware replay -> independent off-stream teacher -> skill promotion only after sealed validation. Requests to generate lore, captions or chatter never receive host-only credentials.

On an 8GB RTX 3060 Ti/4060 class GPU, budget GPU headroom for the active game, OBS and desktop compositor first; test quantized local models at multiple context lengths, and make TTS CPU-preferring when an actual latency/audio test supports it. Cache stable system instructions, retrieved docs and compact skill summaries, not raw indefinite transcripts. Use Rust/C++ for proven CPU-hot operations (capture/audio buffers, streaming IPC, image pre-processing) **only after profiling**; rewriting Python orchestration will not intrinsically increase tokens/sec when GPU matmuls dominate.

**A/B gate before shipping any "speed improvement":** same hardware/processes, equal game settings and seed, same prompts, same model and sampler, warmup, ≥5 independent trials, medians + p95 + outlier traces, OBS dropped-frame ratio and game FPS, VRAM peaks, p95 time-to-first-audible-chunk, win/progress per 100 trials, power/resource ceilings. If a faster model causes missed deadlines, more mistakes, microphone glitches or dropped OBS frames, reject the change. Never claim published 54+ tokens/sec is a measured speed on Star's PCs.

## 4. Teaching Star games, not merely playing a demo

**Training loop for owner-controlled games:** randomize maps/seeds; start with movement and camera, then obstacle navigation, multi-step collection, combat (where authorized), cooperation, exploration, and multi-session strategies. For each task: define ground-truth metric, observe, predict, act with deadline, compare, score, write an evidence-linked experience, propose alternative strategy, practice, then run a blinded validation on *different* seeds/maps. Current signature/replay protections protect part of this pipeline but cannot substitute for independent success metrics.

Train reusable **skills** with explicit preconditions, uncertainties, timeout and rollback. Transfer to at least one held-out game before calling a skill generalized. A "won" event from screenshot text alone cannot pass. Make trainer/teacher activity off-stream or under a strict budget so her in-game control remains responsive. Reward genuine control improvements, not verbosity or larger token consumption.

**Games to support first:** a deterministic platformer test game, an owned Roblox obby via Studio, then an offline puzzle game and a server-authoritative co-op prototype. Third-party multiplayer games demand anti-cheat/ToS review and permission; avoid bypassing protections or creating an unfair competitive advantage.

## 5. A VTuber who feels spontaneous but stays grounded

- An **interruptible conversational state machine** tracks listening, thinking, utterance draft, speaking, yield/cutoff, quiet/idle. Handle interruptions only at safe audio boundaries. Couple OBS audio *actually played* to avatar mouth/eye/emotion; never announce a joke or accomplishment merely because TTS was queued.
- A **talk-vs-silence policy** considers action deadlines, game surprises, chat relevance and OBS health. Reactions depend on signed host facts when available; vision-only emotions are tentative (“I think I found something”). Use natural hesitation sparingly; do not script fake "I remember winning" or pretend human identity.
- Give Star **persistent preferences and authentic continuity**: favorite play styles, experimented strategies, learning goals, curated hobbies, activity history, and revisable beliefs with timestamps and privacy classifications. Keep a consistent character voice and ability to admit uncertainty. Express emotions as an acting/personality layer rather than unsupported claims of subjective consciousness.
- A lively stream can feature occasional playful Astro/Amber interactions, a pet/cat mode, scene transitions, audience Q&A, comedic timing, cooperative games, off-stream learning reflections and meaningful breaks—without spamming chatter.
- Test voice variants *blindly* for pronunciation, emotional prosody, intelligibility and consistency. Move from CPU TTS to high-fidelity voice only when the measured delay and VRAM/FPS costs permit it. Protect the virtual microphone from feedback and private desktop audio leaks. Human-like responsiveness is more important than saying “uh” every sentence.

**Broadcast safety:** nonbroadcast preview by default; owner authorizes stream start, viewers receive disclosure she is an AI character, safe chat content moderation and privacy redaction, kill switch neutralizes input + speech + avatar; key release must be verified by a separate Windows watchdog, not inferred from Python worker exit.

## 6. Game-making and general intelligence beyond gaming

For each Roblox/Blender game-development request, inspect relevant objects and scripts first, generate 4–8 candidate patches where affordable, lint/style-check, run a safe in-Studio playtest, check client/server multi-user behavior and assets/lighting/fps, compare visual renders, then promote only independently verified fixes. Keep standalone offline fixtures so progress can be replayed without relying on a cloud LLM. Track release version and rollback locally; GitHub is a publishing/review surface, not required for Star's local self-improvement.

A knowledge layer should store **source URL, retrieval date, version, content hash, permissions, confidence, verified examples and failed attempts**. Distinguish live knowledge from aging facts. Do not treat self-generated notes as external evidence. Use retrieval over verified skills, code snippets, API docs, and owner-approved knowledge; pass only brief relevant excerpts to the fast model to save context and TTFT.

**Future capability proposals:** voice-first Windows accessibility control with consent boundaries; authorized game-object detection, inventory/crafting planning, spatial pathfinding; self-created Roblox test levels; music cues and facial-animation lip sync; OBS scene/stream preview quality inspection; Discord conversational presence without fabricated experiences; controlled self-learning tasks and offline A/B competitions; robust startup/recovery on dedicated host; local inference scheduler that observes CPU/GPU/VRAM before admitting expensive jobs.

## 7. Explicit milestone gates

| Gate | What counts as done | Status 2026-11-03 |
| --- | --- | --- |
| Signed journal and deduplicated event history | signature/session/replay tests | Existing from PRs #934–935, draft/unmerged |
| **Transition-derived signed events** | baseline -> changed phase/checkpoint -> corroborating sample -> signed receipt, malicious cases rejected | **New opt-in code and offline tests in this change** |
| Isolated source connector | permitted engine/Studio source separated from model, engine ID protected, source errors revoke | **Not implemented** |
| Windows gaming rehearsal | owned offline test, actual authorized input, physical key-up independently checked, verified gameplay state, OBS preview | **Not completed** |
| Voice/avatar OBS end-to-end | audible chunk / mouth/gesture / captions time-synced, turn-taking measured, no broadcast | **Not measured** |
| Intelligence improvement | blinded repeated-game transfer tasks outperform same-hardware baseline | **Not measured** |
| Real stream | owner-authorized launch, stable FPS + OBS + audio, moderate public chat, emergency stop tested | **Not authorized or demonstrated** |

**This iteration makes one trust boundary real in code.** Do not equate a working synthetic telemetry witness with a trustworthy real-game observer. Keep PRs draft, do not push unverified changes to main, and require end-to-end nonbroadcast acceptance before any public VTuber stream.
