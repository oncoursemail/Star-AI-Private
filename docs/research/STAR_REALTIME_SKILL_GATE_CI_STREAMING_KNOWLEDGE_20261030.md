# Star AI: verified real-time game skill, voice, knowledge and infrastructure upgrade

Research and engineering audit — **October 30, 2026**. This document records a limited code update to draft PR #845 and a deeper inspection of existing Star modules. It does **not** claim live gaming, deployment, a faster neural model or human consciousness. Research is current to the cited sources and must be reproduced on Star's own Windows/Brain 2 hardware.

## 1. Concrete code and CI findings

**Existing repository inspection:**
- `star/stream_brain_governor.py` already gates model admissions using trusted game FPS, device memory, voice backlog and local workload measurements; it does not run models.
- `star/stream_context_host.py` already connects approved public knowledge, signed practice summaries and stream context to governed `StarStage` plans.
- `star/stream_audio_avatar_session.py` already binds consumed PCM samples to avatar motion with epoch validation; it does not prove that OBS recorded output.
- `star/gameplay_skill_bank.py`, `game_paired_study.py`, `game_learning_ladder.py`, `game_transfer_eval.py` and `studio_multimodal_quality_gate.py` already handle signed learning evidence, a curriculum, independent holdouts and verified visual reviews. A separate generic "learning loop" would duplicate these.
- `star/stream_episode_journal.py` provides new session-local, opt-in, structured game memories. Its event IDs were previously deduplicated *globally*, although identical local IDs can be reused independently by different games. Updated keys are now `(game_scope, moment_id)`; expiration and capacity eviction update the same key. Added a cross-game regression test.

**Failed CI investigated:** Oct 31 02:13 UTC, PR #845 head `246b3ca1...`, offline run `41157754004`: 14,424 passed, 1 failed, 329 skipped, 562 subtests passed; React and Pyright succeeded. The sole failure was `tests/test_warmup.py::test_startup_check_is_cheap_and_truthful_then_primes_one_slot`: `server_status(settings)['ok']` returned `False` instead of the expected fresh-process `None`. Other tests can update a process-global `_LAST_SERVER_CHECK` for the same mock LAN target in an xdist worker. The test now starts from an isolated, monkeypatched empty status cache without modifying the production status mechanism. This fixes a test-order assumption; latest whole-suite CI must confirm it.

**New, supplementary benchmark:** `star/game_skill_gate.py` evaluates paired *host-attested* performance trials on the same held-out maps/seeds, requiring ≥20 pairs across ≥2 scenarios by default. It explicitly segregates paused and real-time games; checks newly lost wins, normalized progress regression, p95 and extreme per-case action-delay regression; rejects missing, repeated and contaminated practice/holdout cases; and provides only an advisory, anonymous verdict. It does not access game controls, speech, the network or training. Its `host_verified` Boolean is NOT a signature. **It MUST NEVER replace `GameplaySkillBank`/preregistered signed `game_transfer_eval` or be treated as auto-promotion authorization.** This fills a narrow timing/progress-diagnostics gap without weakening the existing stricter transfer gate. All tests use synthetic trials and are not evidence of new gameplay mastery.

## 2. Highest-value infrastructure architecture

| Tier | Duty | Source of authority | Failure behavior |
| --- | --- | --- | --- |
| Game control (fast) | deterministic, game-specific action policy, permitted interaction | actual game state + independent authorized host | stale observations -> neutral/stop |
| Attention and tactical reasoning | observe events, select next objective, decide when to speak | host video/game state, resource telemetry | late inference -> discard result |
| Broadcast pipeline | capture audio/device playout, animated rig, OBS witness | local trusted device/OBS host | stop old playback epoch on interrupt; don't invent audible success |
| Learning and memory | practice, replay, independent evaluation, source-backed retrieval | signed records, held-out eval, reviewed public facts | quarantine ambiguous evidence |
| Star Core Forge | local experiments, versioned builds, rollback, canary | independent tests and owner-approved deployment gates | revert on regression |

Keep game graphics, input, speaker playback and OBS on a protected realtime budget. Run research, evaluation and model experiments in a background budget, preferably on a separate machine when available. Prevent multiple Studio instances or a large vision model from silently exhausting the RTX 4060 8 GB VRAM. Measure *actual* RAM/VRAM headroom instead of reserving an invented fixed amount.

**Experiment matrix:** baseline LLM; cache-stable prompts; speculative decoding only when draft-model headroom exists; mixed CPU/GPU offload; CPU TTS. Keep identical model weights, prompt sets and 20+ repeated warm/held-out tests per workload. Report general knowledge, Roblox Luau, design, game strategy and social-conversation correctness separately. Record p50/p95 first audio playback, model decode, game 1%-low FPS, OBS dropped frames, RAM/VRAM peak, energy and time-to-recovery after interruptions. Reject speedups that cause newly wrong paired answers.

Source: llama.cpp official server SPEED-Bench, with per-category throughput/latency/speculative-acceptance reporting: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## 3. Game-playing improvement plan (actual outcomes)

**Offline phase:** evaluate a platformer, dynamic dodger, puzzle and a Roblox Studio game using owner-authorized controls. Save host-owned resets, version, seed, game mode and objective *before* running candidates. Gameplay success and progress must come from the engine's serialized state, not a language model's narration. GameWorld evaluates 34 games and 170 tasks, and its GameWorld-RT variant keeps the game running during inference; compare paused and real-time scores independently. An August 2026 fine-control branch supports higher-frequency action evaluation. Sources: https://github.com/gameworld-project/gameworld and https://gameworld-project.github.io/

**Practice phase:** use `GameLearningLadder` and `PairedGameStudy` to select isolated practice objectives; track predictions made *before* attempts, input latency and success. Block self-reported victories and unobserved practice improvements from the knowledge/stream journal.

**Validation phase:** use `game_transfer_eval`'s preregistered roster and signed independent host results for held-out transfer. Feed only aggregate progress/latency diagnostics from the new `game_skill_gate`; never send hidden individual validation cases to the model. Across-game improvements require multiple game families rather than hundreds of almost identical seeds. Also track known-skills regression and difficulty increases. Never equate "a model talked about the game" with "a game was played".

Relevant newer continual-learning research (date checked Oct 30, 2026):
- AGENTCL (June 2026): naive experience accumulation can degrade held-out performance, and controlled reuse streams distinguish learning more reliably. https://arxiv.org/abs/2606.02461
- EmbodiedCLBench (October 9, 2026): compositional transfer matters more than collecting unlimited repetitive experience. https://arxiv.org/abs/2610.13021
- SkillLearnBench (April 2026): external feedback and task outcomes are more reliable than recursive self-feedback alone. https://arxiv.org/abs/2604.20087

## 4. More natural (but honest) VTuber streaming

Star's persona should have continuity, interests, playfulness, modes (normal, cat, puppy), expressive eye/gaze movements, naturally timed laughter, head movement and coherent twin-tail hair motion. These are **functional performance goals**, not a claim that AI has human biology or felt emotions. She should transparently identify as an AI entertainer and refer to verified episodes rather than invented memories.

**Voice**: compare the existing stack against Kyutai Pocket TTS v4.0.1 (released October 21, 2026). The October 20 v4.0.0 release introduced 18.2M/6.9M/1.9M English models; v4.0.1 fixes smaller-model issues. Small CPU models may protect game VRAM but are not guaranteed to sound natural. Test on Star's Windows CPU under game load, and pin model/release, voice and CPU thread count. Source: https://github.com/kyutai-labs/pocket-tts/releases

**Turn-taking**: independent test clips must distinguish a true owner barge-in, viewer acknowledgment, streamer excitement, silence when concentrating, speech onset, laughter and loud game audio. LiveKit documents local `v1-mini` turn detection in self-hosted production, while full `v1` and adaptive interruptions can involve LiveKit Cloud credentials/inference. Do not claim they are deployed locally unless tested. Sources: https://docs.livekit.io/agents/logic/turns/turn-detector/ and https://livekit.com/blog/turn-detection-and-interruption-handling

**Perception to behavior**: react to observed wins without premature statements; direct eye gaze towards chat overlay when reading questions, screen target during dangerous maneuvers and camera for viewer address; tie mouth blendshapes to *consumed* audio samples. Limit how frequently Star makes ambient remarks. Allow a genuine sense of focus and calm instead of continuous filler speech.

**Audio / motion acceptance**: device playback acknowledgments are not OBS broadcast proof. For a Windows rehearsal use `StreamBrainGovernor` -> `StarStage` -> `AudibleAvatarSession` -> recording witness with explicit playback epochs. Verify actual OBS audio waveform aligns with spoken captions and mouth movement; note when speech was cut off. Record a review clip with owner permission; never place private raw media in a public repository.

## 5. Building original Roblox games, not "AI slop"

Roblox `OpenGameEval` now describes 84 curated core Studio tasks, with executable scene and play-session scoring and a measurable association between inspection-before-editing and success. It is not sufficient to create syntactically valid Luau. Source: https://github.com/Roblox/open-game-eval

For each generated project, Star should produce a scene/interaction inventory, deterministic tests, runtime screenshot and an owner-reviewable visual change summary. Include:
- Geometry: flush walls and joined assets, no unintended intersections/gaps, correct pivots/scales/grips/attachments and no z-fighting.
- UX: visible affordances, no overlapping UI labels, responsive mobile controls, keyboard/controller access and readable font sizes.
- Functional play: inventory, tools, matchmaking, join/leave, animation replication, physics and correct lobby flows.
- Visual quality: compare reviewed screenshots in `studio_multimodal_quality_gate.py`, not just a model's aesthetic score.
- Performance: baseline frame-time distributions on low/medium/high graphics, mobile device simulation and real network lag.

Roblox's May 28, 2026 Studio testing update documents `StudioTestService`, `StudioDeviceSimulatorService` and `VirtualInput`. `ExecuteMultiplayerTestAsync` supports up to **8** simulated clients per test session; use it for scripted multi-client actions, not for unsupported claims of mass player scale. Sources: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854 and https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers

## 6. General-knowledge intelligence and continuous self-improvement

Build a versioned evidence graph: `(source, retrieval_time, license, fact, confidence, contradiction_keys, evaluation_family)`. Keep claims separate from action authorization. Retrieval routes should first use curated project/docs, then optional verified online sources; freshness TTL for current facts; compact evidence cards; no dumping an unbounded vector cache into the prompt. A source digest only identifies a document; it does NOT prove the document's claims.

Treat a new prompt recipe, agent skill, retrieval policy or model configuration as a candidate experiment in local Star Core Forge. For each, require:
1. An immutable code/config snapshot, independent regression suite and provenance of model/tool versions.
2. Paired correct-to-incorrect analysis on previously unseen general knowledge, Luau, animation, UI, gaming and streaming cases.
3. Latency + energy + VRAM + FPS baselines under realistic concurrent workload.
4. Reversible canary, recovery drill and owner-level decision for external publication or high-impact operations.

To improve "humanlike" behavior, prioritize **consistent autobiographical *game experiences*, conversational timing and appropriate expressive reactions**, not manufactured stories or claims of consciousness. Make it genuinely useful and engaging while accurate about its artificial nature.

## 7. Next required physical experiments

1. Re-run complete GitHub CI on the new PR head; do not describe synthetic tests as passed until they run. The repaired startup test should remain robust when other xdist tests have probed the same mock LAN.
2. Connect genuine host observations to the session journal with explicit owner opt-in and a fresh game-session epoch; replay old chat events must not create memories.
3. Run the **same 20+ real-time held-out game scenarios** under baseline and candidate, and run the existing signed validation separately. Interpret new timing gate as supplementary owner report only.
4. Record a private 10-minute Windows game+OBS+avatar+voice rehearsal and report p50/p95 first audible response, 1%-low FPS, OBS dropped frames, interruptions, game scores and human-listener naturalness ratings.
5. Tune one change at a time, with rollback. The biggest potential gain comes from connecting already-built systems and measuring real outcomes rather than introducing a disconnected new framework.

**Security**: `oncoursemail/Star-AI-Private` currently reports visibility `public`. Do not commit host signing keys, evaluation seeds, player identities, viewer transcripts or raw voice/video. GitHub is a review/publishing mirror; local Star Core Forge should remain capable of offline code review, tests, backups and rollback.
