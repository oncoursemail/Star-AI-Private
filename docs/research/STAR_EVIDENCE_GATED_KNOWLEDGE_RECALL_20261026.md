# Star AI — Evidence-Gated General Knowledge Recall, Gaming and Streaming Intelligence
**Research and engineering: October 26, 2026**

## What this pull request implements (not a claimed model upgrade)

This patch adds `star/knowledge_recall.py`, an offline-first, owner-enabled **retrieval-practice coordinator** connected to STAR's existing `KnowledgeStore` and `StreamTelemetry`. Its goal is to make future general-knowledge practice *traceable and difficult to self-score falsely*, while leaving the game/stream and language-model inference paths untouched. It does not change model weights, train a neural network, ingest the internet, install a TTS engine, start OBS, run Roblox, or prove a gain in factual recall or speed.

The coordinator:
1. Accepts up to **96** bounded, opaque, owner-curated question IDs and domains. Every question is pinned to one **reviewed** note, its project scope, and a digest of the note's exact text + source + revision. Changed/revoked/unreviewed notes become ineligible immediately.
2. Queries all current reviewed sources in **one parameterized SQLite SELECT** per decision. No source note bodies, answer keys, URLs, private facts or model prompts enter the result or checkpoint.
3. Recommends **at most one** offline question at a time using balance across domains, time-due reviews and bounded retries. A randomized 128-bit reservation ticket prevents a result for an earlier task being accepted as a new task.
4. Requires independent host-graded feedback with a domain-separated HMAC-SHA256 receipt over the question, ticket, pinned source, grade, grader revision and observation timestamp. Incorrect, abstained and correctly answered questions receive different bounded revisit intervals. Unverified attempts **never** count as learning.
5. Disables background rehearsal during a live broadcast, weak gameplay FPS, audio backlog, missing telemetry or resource pressure. No model/tool/game action is authorized by its suggestion.
6. Can emit a **MAC-sealed**, content-free local progress checkpoint and restore into a fresh disabled scheduler with the exact same source roster. The embedding host, not a model, must save it and supply rollback-resistant monotonic storage. A MAC alone does not prevent restoring an older genuine snapshot.

Questions and reference answers deliberately reside **outside** this scheduler. The trusted runner maps `question_id` to an offline question, obtains a model answer, uses a separately trusted grader (possibly `knowledge_checks.answer_checks` for mechanically scorable prompts or human review for non-mechanical ones), signs the outcome, and calls `finish`. The runner must keep the HMAC key and hidden evaluation corpora away from the model's tool interface. This module receives neither answers nor hidden validation scores; it does not automatically write "reviewed" facts.

## Why this is useful for general intelligence

A model with a large knowledge store is not necessarily more knowledgeable. A stored claim may be fabricated, contradicted, outdated or irrelevant, and rereading it is not equivalent to recalling it without help. Retrieval practice offers a measurable behavior: can the *same frozen model* answer a previously missed question correctly after an offline practice intervention? STAR can eventually compare a model and its new knowledge/memory/rehearsal policy on a sealed independent set. Include a no-retrieval baseline, repeated domain-diverse questions, abstention rates, source accuracy and latency. **Practice scores must never substitute for independent held-out model scores.**

The Free Spaced Repetition Scheduler (FSRS) literature provides a richer probabilistic method for human memory recall, using difficulty, retrievability and stability. This implementation intentionally uses an explicit six-step schedule and short failure retries because it has no measured STAR-model forgetting curve. Do not call it FSRS, claim calibrated retention, or copy its fitted human-memory parameters. When enough offline evidence exists, compare STAR-specific variants under controlled baselines.

Primary references:
- Open Spaced Repetition FSRS implementation and optimization research: https://github.com/open-spaced-repetition/fsrs4anki
- FSRS algorithm overview (July 28, 2026 revision): https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm
- September 2026 systematic review of spaced repetition and retrieval practice in human medical education. **Human-study evidence does not establish LLM improvement**: https://pubmed.ncbi.nlm.nih.gov/42866698/
- STAR's existing offline knowledge response grader: `star/knowledge_checks.py`, `star/general_knowledge_benchmark.py`, and `star/knowledge.py`.

## Practical integration plan: knowledge + actual game learning

**Knowledge lane (offline).** Curate reviewable source notes from permitted factual and project documents. Owner/independent reviewer approves them. Pin source hashes. Schedule short recall probes by domain. Record independently graded answers and abstentions. Keep a separate, previously sealed holdout set and only claim improvement when baseline versus candidate quality is reproduced. Do not put raw personal memories, passwords, chat transcripts or evaluation answer keys into a prompt.

**Game lane (offline then live).** Reuse `StudioPracticeRunner`, `GameMechanicProbeLab`, `GameLearningLadder`, `GameplaySkillBank` and `game_transfer_eval`. An actual Roblox Studio host sees scene state, proposes an *allowlisted* action, runs it, and separately scores outcome. Learn jump timing, obstacle recognition, navigation, inventory menus and game-specific strategies from signed practice results. Validate on unseen levels and different games; many completed practice attempts are not proof of generalization.

Roblox's first-party Studio MCP supports inspecting and editing DataModel instances, executing Luau and testing within open Studio sessions, including multiple Studio instances. Star should use native Studio inspection to locate wall/prop collisions, z-fighting, unattached or mis-sized geometry, UI overlap, broken checkpoints and invisible objects before attempting repairs. The tool is an interface, not automatically a reliable evaluator. Roblox's April 15, 2026 agentic Studio announcement describes planning and playtesting workflows, while Google's SIMA 2 work demonstrates the direction of generalizable visually grounded game action, but neither proves that Star has mastered Roblox gameplay.

Primary references:
- Roblox Studio built-in MCP: https://create.roblox.com/docs/studio/mcp
- Roblox Studio agentic workflows, April 15 2026: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Official Roblox Playtest Agent beta, April 9 2026: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767/1
- Google DeepMind SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

## More human-natural VTuber architecture (while clearly identified as AI)

Star's character identity, cat/puppy moods and humor should remain consistent across streams. A convincing social presence comes from *contingent reaction*, not constant talking or invented human memories. Use distinct fast lanes: real-time game input, prioritized conversational voice, and postponed offline reasoning/learning. Speech should be sparse during critical actions. Reactions should be proportional to actually verified game events, with variable sentence length and pauses. Interactive chat should respect intentional interruption, the viewer's actual words and gameplay, and not pretend to remember fictional events as reality. A persona may have explicitly labeled fictional lore.

For natural voice and animation, keep low-latency microphone/VAD, first **audible** PCM acknowledgements, expressive TTS, synchronized mouth/eye/hair physics, VTube Studio API hotkeys, and stale-epoch cleanup. Measure turn completion and chat usefulness *across all required response opportunities*, not just responses that succeeded. Natural laughter and emotional timbre require human listening tests. VTube Studio hotkey expressions cannot directly override physics-driven outputs; use the rig's physics parameters.

Kyutai's October 2026 Pocket TTS English 18M/7M/2M variants are CPU-friendly **candidates**, not automatically quality upgrades. Compare emotional intelligibility, first audible time, CPU frame pressure and game FPS with the same written and voiced prompts. On an 8 GB gaming GPU, CPU TTS may create CPU contention even if VRAM is saved.

Primary references:
- Pocket TTS repository and October 2026 small models: https://github.com/kyutai-labs/pocket-tts
- VTube Studio official application/API repository: https://github.com/DenchiSoft/VTubeStudio
- VTube Studio expression/physics behavior: https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-%28a.k.a.-Stickers-or-Emotes%29

## Model speed: a gated benchmark, not a marketing number

To increase *useful intelligence per second*, compare a static-prefix cached baseline with n-gram and draft-model speculative decoding on the **same** local model, tokenizer, quantization, prompt mix and 8 GB GPU under active gaming. Capture p50/p95 TTFT, audited answer correctness, actual decode tokens/sec, cache hits, GPU peak, CPU utilization, game p99 frametime and time to first **audible** speech. Reject candidates that win token/sec but lose frame stability or grounding.

Reuse `brain_benchmark.py`, `stream_realtime_benchmark.py`, `stream_latency.py`, `stream_quality.py` and `StreamBrainGovernor`. Keep `stream_persona.STREAMER_SYSTEM_PROMPT` stable to benefit prompt prefix reuse. Schedule research, offline retrieval rehearsal and heavyweight Roblox validation at low priority. Speculative decoding is conditional: additional draft model memory can cost more time/VRAM than it saves; avoid preselecting a winner.

Primary reference:
- Official llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## Acceptance criteria and unresolved work

A verified progress checkpoint is **not** a better model; success receipts authenticate source and grading data, **not truthfulness of the grader**. New reviewed knowledge does not bypass owner's review or privacy controls. Offline trials must use trusted clocks. The current planner intentionally has no write-back into the source store and no live model integration; a host still needs to wire it to `knowledge_checks`, local inference, source review, manual checkpoint storage and a separate sealed benchmark runner. Its fixed review timing and 96-item roster are engineering bounds rather than empirically optimized policy.

Testing should include forged grade receipts, ticket replay, source changes, model-claimed grade without signature, unreviewed facts, project isolation, stale/future feedback, live stream pressure, canceled/expired reservations, cross-thread SQLite reads, restored checkpoints, snapshot mutation and domain coverage. Before any trained-behavior claim, run model-visible practice on a proper offline corpus and independently evaluate transfer and calibration on **unseen** cases. No merged release, broadcast or autonomous game controls are authorized by this PR.

**Important repository visibility:** despite its name, `Star-AI-Private` is publicly visible. This patch contains only generic code, synthetic unit tests and links to public research; no credentials, recordings, identity details or private knowledge notes. Keep all training private corpora and signer keys on the authorized host or internal Star Core Forge. GitHub remains optional for publishing; internal Forge owns Star's long-term development history and rollback.
