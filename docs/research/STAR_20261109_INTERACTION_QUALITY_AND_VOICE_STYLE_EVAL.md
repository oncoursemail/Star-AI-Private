# STAR voice interaction quality: delivery, task success, and long-context grounding

**Research date:** 2026-11-09
**Implementation:** `star/voice/interaction_eval.py`
**Status:** offline evaluator implemented; live host integration is future work.

## Executive finding

STAR already has a content-free full-duplex evaluator for floor control, interruptions, silence, backchannels, and first-audio/avatar timing in `star/voice/duplex_eval.py`. That is necessary, but it does not answer three separate questions:

1. Does the voice sound appropriate for the moment (including requested whisper/soft/projected delivery)?
2. Does STAR complete a spoken task correctly?
3. Does she remain grounded in what was actually established over a long conversation, including facts never supplied and false premises?

Do not collapse these into a single “human-likeness” score. A system can sound expressive while hallucinating memory, or answer correctly while interrupting people. Each dimension needs its own score and evidence coverage.

## Research findings

### 1. InteractionBench — evaluate several dimensions on the same live interaction

He et al., *InteractionBench: Measuring Timing, Task Accuracy, Whisper and Volume, and Grounding in Real-Time Voice Systems*, submitted 2026-11-02: [arXiv:2611.02430](https://arxiv.org/abs/2611.02430).

The study evaluates 221 items per system across 13 scenarios and 1,519 graded runs. It measures conversational timing, spoken-task accuracy, whisper/volume behavior, and groundedness in conversations longer than 20 turns. Its protocol fixes task scorecards before the model runs, measures whispering acoustically rather than accepting a model's claim that it whispered, and probes whether later answers stay consistent with established, missing, updated, or false-premise facts.

The paper reports a rank correlation of 0.83 between timing and spoken-task accuracy in its evaluated systems. It also reports that hosted systems passed 67–88% of its groundedness probes while the evaluated open full-duplex systems passed 14–35%. These are results from that paper's systems, data, and protocol—not expected STAR scores or universal model rankings.

**STAR design consequence:** preserve separate lanes for style, acoustics, task completion, and grounding; count missing evidence as a failure in the required denominator; use long-context probes with explicit “not provided” and changed-state cases.

### 2. MP-Bench — group conversation is a different problem from one-to-one chat

Shih et al., *MP-Bench: Evaluating Voice Agents as a Multiparty Conversation Participant*, submitted 2026-09-11 and accepted to Findings of EMNLP 2026: [arXiv:2609.13076](https://arxiv.org/abs/2609.13076).

It treats turn-taking awareness, response appropriateness, and comprehension as separate dimensions. In its evaluation of 12 voice agents, real-time agents reached at most 22% multi-party comprehension and remained near chance on multi-party turn-taking.

**STAR design consequence:** a diarization or “who spoke?” label alone is not group understanding. Future holdouts should test who a comment is addressed to, whether a reply is meant for another viewer, references across speakers, and whether Star should join or stay silent. The current evaluator does not process audio or infer speaker identity.

### 3. Full-Duplex-Bench v3 — voice agents must complete chained tools under disfluent speech

Lin et al., *Full-Duplex-Bench-v3: Benchmarking Tool Use for Full-Duplex Voice Agents Under Real-World Disfluency*, submitted 2026-04-06: [arXiv:2604.04847](https://arxiv.org/abs/2604.04847).

The work uses human-recorded requests annotated for disfluencies and tasks requiring chained API calls. Its reported failures include self-corrections and hard multi-step reasoning. The benchmark page describes 100 requests across 79 scenarios, 12 speakers, and four domains.

**STAR design consequence:** the next companion evaluator should score planned-vs-observed tool chains, argument identity, approvals, cancellations, deadlines, and whether the spoken summary is grounded in returned tool results. This PR does not invoke tools or execute external actions.

### 4. Realtime-Venus — keep live interaction separate from deep delegated work

The Realtime-Venus report (September 2026) describes two cooperating loops: one for live perception and speech, another for asynchronous delegated tasks. It snapshots the context at request time, routes work to a suitable model or skill, then returns the result to the same conversation while the live loop continues: [project and technical report](https://realtime-venus.github.io/).

**STAR design consequence:** a slow research or game-planning task must not block immediate listening, interruption, or a short natural response. Delegated results need a conversation/session identity, freshness check, and explicit frontend decision about when they are speakable. This is a proposed runtime architecture, not implemented by this evaluator.

### 5. Roblox creation and Open Cloud

Roblox's Studio MCP/Open Cloud documentation describes per-game permission scopes, approved upload folders, and owner-controlled access; the connected client cannot grant itself additional permissions: [Roblox Studio MCP Open Cloud](https://create.roblox.com/docs/studio/mcp-open-cloud). Roblox's November 4, 2026 announcement adds Open Cloud workflows and asset-import skills: [DevForum announcement](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849).

**STAR design consequence:** route creation work through a private test experience, least-privilege scopes, asset review, and executable playtests. Asset uploads can create permanent owner-owned assets; the host must preserve explicit confirmation and review.

## What this implementation adds

`star/voice/interaction_eval.py` is an offline, content-free JSONL evaluator. It accepts only:

- Opaque scenario, event, and conversation keys plus a turn index.
- Expected and independently annotated delivery-style labels.
- A host-measured audio-present flag, RMS dBFS, true-peak dBFS, and optional whisper HNR/voiced-fraction scalars.
- Whether a spoken task or grounding probe was required and an independent pass/fail/missing receipt.
- A conversation-level coherence score, supplied once per conversation.
- A development/holdout split and context-turn count.

It reports delivery-style accuracy and per-style precision/recall/F1, volume-band compliance, muted-output correctness, near/over-full-scale peaks, acoustic whisper screening, short-vs-long-context grounding, spoken-task evidence coverage, and conversation coherence. It intentionally emits no combined “human-likeness” score.

The default whisper thresholds (HNR < 6 dB and voiced fraction < 0.4) mirror the specific acoustic screen described in InteractionBench. They are **not** a universal definition of whispering; local voice, codec, noise gate, and capture-chain calibration are required. Expected RMS bands are supplied by each authored scenario instead of hard-coding one loudness target for every microphone, voice, and stream mix.

### CLI

```bash
python -m star.voice.interaction_eval receipts.jsonl --split holdout --output interaction-report.json
```

The report is aggregate-only. The evaluator rejects transcripts, audio payloads, viewer identities, prompts, unknown fields, duplicate JSON keys/events/turns, non-finite values, invalid acoustic ranges, inconsistent audio receipts, and missing/extra schema fields.

## Recommended next engineering sequence

1. **Trusted Windows acoustic receipt adapter:** compute RMS, true peak, HNR, and voiced fraction from the actual STAR TTS output path; keep raw PCM ephemeral and never store it in benchmark JSONL.
2. **Client-side timing alignment:** record first audio *arrival* and first audible playout separately. Server generation time alone omits local buffering, audio-device queueing, and network delay.
3. **Long-context probe bank:** 22–30 turn synthetic conversations with changed facts, unknown facts, false premises, interruptions, and task state. Keep answer keys sealed from the model.
4. **Human listening calibration:** compare acoustic labels and style ratings against multiple blinded listeners; do not use an LLM judge as the sole authority for whispering or other non-verbal cues.
5. **Spoken tool-chain evaluator:** require exact planned/observed tool identity, argument digest, permission/approval receipt, idempotency, cancellation and result-grounded spoken completion.
6. **Private nonbroadcast rehearsal:** game + local inference + OBS preview + TTS + avatar for 30–60 minutes. Measure client first-audible p50/p95, interruption-to-silence, game 1% low FPS, GPU/VRAM, CPU, OBS render/encoding drops, audio underruns, volume/style, and long-context groundedness.
7. **Capability transfer:** reuse STAR's existing game-practice and general-knowledge suites, then add held-out unfamiliar games/tasks. Require demonstrated improvement and transfer, not self-reported mastery.

## Non-claims and safety

- This is a measurement tool, not live audio processing, speaker diarization, TTS, avatar animation, OBS control, game control, or streaming integration.
- Host-supplied scalar receipts and human labels are not authenticated by this module. The host must be trusted and the holdout independently controlled.
- No model weights, inference route, settings, permissions, or broadcast behavior change.
- No measured increase in intelligence, speed, gameplay skill, or human-likeness is claimed.
- Keep live integrations opt-in and broadcasting disabled during the first hardware rehearsal.

## Primary sources

- [InteractionBench, arXiv:2611.02430 (2026-11-02)](https://arxiv.org/abs/2611.02430)
- [MP-Bench, arXiv:2609.13076 (2026-09-11)](https://arxiv.org/abs/2609.13076)
- [Full-Duplex-Bench v3, arXiv:2604.04847 (2026-04-06)](https://arxiv.org/abs/2604.04847)
- [Realtime-Venus (2026-09)](https://realtime-venus.github.io/)
- [Roblox Studio MCP/Open Cloud documentation](https://create.roblox.com/docs/studio/mcp-open-cloud)
- [Roblox Studio MCP update (2026-11-04)](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849)

## Additional research: gaming, creation, general knowledge, and inference speed

### 6. Real-time game mastery is not the same as paused reasoning

Aggarwal and Welleck, *Gym-Anything-RT: Scaling Real-Time Environments for Vision-Language Agents*, submitted 2026-10-27: [arXiv:2610.37567](https://arxiv.org/abs/2610.37567).

The benchmark builds 100 real-time minigames and compares the same tasks under live, paused, or slowed conditions. One evaluated GPT-6 Astra configuration scored 9.0% in real time and 75.0% when paused. This is a result for that configuration and benchmark, not a forecast for STAR.

**STAR design consequence:** every game skill needs a real-time track and a deliberate track. Use separate reflex (deadline-bound movement/avoidance), tactical (routes/objectives), and strategic (mechanics/learning) policies. Keep held-out maps, changing hazards, missed-frame accounting, and independently observed game-state transitions. A button press or model explanation is not proof of success.

### 7. Game creation requires inspection and visual feedback, not just code generation

Turkel et al., *OpenGameEval: Benchmarking Agentic Programming and Exploration in a Stateful Game Engine*, submitted 2026-10-01: [arXiv:2610.02563](https://arxiv.org/abs/2610.02563) · [Roblox benchmark repository](https://github.com/Roblox/open-game-eval).

OpenGameEval evaluates 84 human-curated Roblox Studio tasks in reproducible stateful sessions and scores both the edited scene and simulated play. Its abstract reports that inspecting all reference-relevant objects before acting was associated with 13.4 percentage points higher pass rate on scene-only tasks and 9.8 points on script-only tasks, holding task and model fixed. This supports an inspection-first loop rather than blind edits.

Chi et al., *GameDevBench*, ICML 2026: [project and benchmark code](https://github.com/waynchi/gamedevbench).

GameDevBench covers 333 game-development tasks with code and multimodal assets. Its authors report that simple image/video feedback improved one evaluated GPT-5.4 setup from 41.1% to 52.0%. The gain is benchmark- and harness-specific, but it is strong evidence that visual inspection belongs inside the agent loop.

**STAR design consequence:** Roblox, Blender, UI, animation, shaders, VFX, and level building need a loop of inspect → plan → build → run → screenshot/video review → playtest → repair → retest. The evaluator must keep scene correctness, gameplay correctness, and visual quality as separate lanes.

### 8. General knowledge should be grounded, calibrated, and applicable

STAR already contains a general-knowledge benchmark and a knowledge-bank path. The next improvement should be to connect them with source-backed retrieval and a held-out application set:

- Record source, revision/date, and the exact claim supported.
- Distinguish verified facts, owner-provided facts, observed experiences, inferred hypotheses, and unknowns.
- Recheck version-sensitive facts (APIs, libraries, game patches) before use.
- Include "not provided" and contradictory-source probes; reward correct abstention instead of confident guessing.
- Test transfer: ask STAR to apply a learned principle to a new domain or unfamiliar game, not merely repeat the stored lesson.
- Keep the grader and holdout answers inaccessible to the model/skill mutator.

This is a harness and memory-quality priority, not a claim that adding more documents makes a model smarter.

### 9. Inference speed: optimize the bottleneck, not one headline number

- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) reuses KV state for shared prompt prefixes and can reduce repeated prefill. Its documentation explicitly says it does not reduce decode time; it helps most when long prefixes are reused.
- [llama.cpp speculative decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) describes draft-model and n-gram-cache methods. Speed depends on draft acceptance and verification cost; measure rather than assume.
- For STAR's 8 GB GPU target, benchmark the actual model, quantization, context, and concurrency with the game/OBS/TTS workload present. Preserve VRAM headroom for the game and avatar.
- Report client first-audible latency separately from server first-token latency; report p50/p95 inter-token gaps, completion latency, queue wait, GPU/VRAM, CPU, game 1% low FPS, OBS render/encoding drops, and audio underruns.
- Compare a quality gate alongside speed: held-out reasoning, grounded answers, Luau correctness, tool-chain success, and game-task completion. A faster but materially less accurate model is not a valid upgrade.

## Prioritized feature backlog after this PR

| Priority | Capability | Required proof |
|---|---|---|
| P0 | Trusted Windows acoustic receipt adapter | RMS/true-peak/HNR/voiced-fraction parity against reference captures; no raw audio in reports |
| P0 | 22–30-turn grounded conversation holdouts | Correct recall, unknown-fact abstention, changed-state handling, no invented experiences |
| P1 | Spoken tool-chain evaluator | Exact tool/argument digests, approval-before-execution, cancellation, deadline, result-grounded answer |
| P1 | Live/delegated two-loop conductor | Live speech remains responsive while research/game-planning work runs asynchronously |
| P1 | Real-time game mastery track | Held-out live scenarios, state-transition receipts, action-age and dropped-frame accounting |
| P1 | Visual game-creation loop | Executable Studio checks plus image/video review and simulated playtest |
| P2 | General knowledge transfer suite | Source freshness, calibration, abstention, cross-domain application |
| P2 | Quality-aware model router | Paired latency and task-quality evidence under full gaming/streaming load |
