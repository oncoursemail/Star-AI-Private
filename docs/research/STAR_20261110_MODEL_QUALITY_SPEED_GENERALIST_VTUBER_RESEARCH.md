# STAR AI — Quality/Speed Evidence Gate and Generalist Runtime Research

**Research date:** 2026-11-10  
**Implementation status:** An offline, evidence-only model quality/speed gate is implemented in this branch. All other integrations below are recommendations or acceptance work unless explicitly marked implemented.

## Executive decision

STAR should not select a model because it is larger, newer, or faster in one isolated benchmark. A useful model upgrade must satisfy four independent constraints:

1. **Capability:** the candidate performs at least as well on broad, task-relevant quality checks.
2. **Responsiveness:** paired client-observed latency improves, including tail behavior.
3. **Runtime safety:** game, audio, avatar and OBS workloads remain within measured resource budgets.
4. **Evidence quality:** the comparison uses the same host, app build, adapter, backend, generation options and preregistered tasks, with failures retained.

This update implements the first two constraints as an offline review gate. It deliberately does not modify STAR's router. A passing report means *human review is justified*, not that the candidate is approved for production or livestream use.

## 1. New implementation: \`star/model_quality_speed_gate.py\`

### Why it is needed

STAR already has separate tools for:
- randomized paired model latency across short chat, general knowledge, reasoning, Luau, debugging, game strategy, stream commentary and summarization;
- broad general-knowledge scoring with evaluator-only oracles and model artifact identities;
- optional llama.cpp server metrics.

Those reports were previously independent. A faster candidate could look attractive without proving that it preserved knowledge quality. Conversely, an aggregate knowledge score could hide a regression in one domain.

The new gate joins the reports without loading a model, making a network request, reading prompts or completions, or changing the active route.

### Inputs

1. **Paired inference report** from \`star.inference_paired_benchmark\`.
2. **Model-axis general-foundation comparison** from \`star.general_knowledge_benchmark\`.
3. Optional **baseline and candidate llama.cpp server-metrics windows** from \`star.llama_server_metrics\`.

The quality report must identify both models with revision, weights SHA-256, tokenizer SHA-256 and quantization. The app commit, source, request builder, adapter, backend, mode and generation options must match. This prevents an apparent model comparison from also changing the client or sampling configuration.

### Conservative acceptance policy

The current policy is intentionally fixed in code rather than exposed as an easy-to-lower CLI flag:

| Gate | Requirement |
|---|---|
| Paired workload coverage | At least 16 complete pairs |
| Workload breadth | At least 2 pairs in each of 8 categories |
| Request failures | Zero failed or incomplete paired requests |
| First-content median | At least \`max(5 ms, 5% of baseline p50)\` faster |
| First-content p95 delta | No more than \`max(5 ms, 2% of baseline p50)\` worse |
| End-to-end p50 delta | No more than \`max(10 ms, 2% of baseline p50)\` worse |
| Pair direction | Candidate must be faster in more matched pairs than it is slower |
| Knowledge breadth | At least 24 tasks across at least 8 domains |
| Knowledge quality | No overall pass-count loss and no domain pass-count loss |
| Model identity | Explicit model ID, revision and weight/tokenizer digests |
| Runtime route | Never changed by this evaluator |

The current 24-task / 12-domain knowledge corpus is explicitly a **development diagnostic, not a sealed holdout**. Therefore even a passing result cannot authorize deployment. A future release gate must add unseen knowledge, code, game, voice and tool-use tasks.

### Output

The JSON report contains:
- baseline and candidate aliases;
- paired sample count and workload coverage;
- first-content p50/p95 and end-to-end p50 deltas;
- faster/tied/slower matched-pair counts;
- general-knowledge pass counts and rates;
- per-domain regressions;
- optional aggregate server-throughput ratios;
- SHA-256 digests of the two input evidence files;
- stable reason codes.

The report always sets:
- \`automatic_route_change_authorized = false\`;
- \`live_vtuber_rollout_authorized = false\`;
- \`holdout_evaluation_required = true\`;
- \`private_windows_game_obs_audio_avatar_rehearsal_required = true\`.

Malformed, duplicate-key, non-finite, oversized or internally inconsistent JSON is rejected. The parser has byte, depth and node-count bounds. Reports contain aggregate evidence only; no prompts, generated responses, transcripts, audio or viewer identifiers are added.

### Example

After creating the paired and quality comparison artifacts:

\`\`\`powershell
python -m star.model_quality_speed_gate \`
  --paired artifacts/paired-inference.json \`
  --quality artifacts/general-knowledge-comparison.json \`
  --output artifacts/model-quality-speed-gate.json
\`\`\`

To add optional per-model llama.cpp server counter windows:

\`\`\`powershell
python -m star.model_quality_speed_gate \`
  --paired artifacts/paired-inference.json \`
  --quality artifacts/general-knowledge-comparison.json \`
  --baseline-server-metrics artifacts/star-fast-metrics.json \`
  --candidate-server-metrics artifacts/star-deep-metrics.json \`
  --output artifacts/model-quality-speed-gate.json
\`\`\`

The output path is created exclusively; an existing report is never overwritten.

## 2. Inference speed: measure distinct bottlenecks

### Client-observed timing

NVIDIA AIPerf separates request latency, time to first token (TTFT), time to second token, inter-token latency (ITL), output length and throughput. TTFT includes queuing, prompt processing, network delivery and first-token generation. ITL describes the interval after the first token. Percentiles matter because a low median can hide a poor tail.

STAR's existing first nonempty text-chunk measurement is correctly called **first-content latency**, not TTFT. It is not tokenizer-level timing and can include client chunk scheduling. Keep the names distinct.

### Server counters

The llama.cpp server exposes \`/metrics\` only when the operator starts it with \`--metrics\`. In router mode, the \`model\` query parameter is required. The endpoint exposes prompt/generation counters, throughput gauges, processing/deferred request gauges, context high-water marks and speculative-decoding counters.

Use the existing read-only adapter:
- GET \`/metrics\` only;
- no \`/slots\`, which may expose request and prompt-related fields;
- no credentials, proxy, redirects or non-loopback host;
- only an allowlist of numeric series;
- counter resets and missing metrics invalidate derived rates.

These are cumulative endpoint observations, not per-request attribution. Do not infer GPU utilization, VRAM, kernel time or a speedup from them.

### Caching and speculative decoding

vLLM Automatic Prefix Caching reuses KV state when prompts share a prefix. It can reduce prefill work; its documentation explicitly says it does not speed up decode when generation dominates. STAR should stabilize static system/tool prefixes and keep volatile game telemetry out of the prefix, then measure cache-hit behavior separately.

Speculative decoding should be evaluated by accepted draft tokens **and** end-to-end latency. A high acceptance ratio alone does not prove net speedup because drafting and verification have costs.

### Required experiment matrix

On the actual Windows gaming PC, compare the same model file, runtime build, context, quantization and workload under:

1. inference only;
2. game only;
3. game + inference;
4. game + OBS;
5. game + OBS + TTS + avatar;
6. the full stack plus background research.

Record client first-content p50/p95, first audible PCM p50/p95, inter-chunk gaps, end-to-end latency, server prompt/decode counters, CPU/RAM, dedicated/shared VRAM, game frame-time p50/p95/1% lows, OBS render/encode/network drops and audio underruns. Keep private-recording and live-broadcast evidence separate.

## 3. General intelligence and memory

STAR should not be one giant prompt with an ever-growing memory dump. Use a small live working set and retrieve only what the current task needs.

Recommended memory layers:

| Layer | Content | Required evidence |
|---|---|---|
| Working state | Current task, game, active subtasks | Expiry and current-session identity |
| Episodic ledger | What STAR observed, did and what happened | Timestamp, source and outcome |
| Procedural skills | Reusable steps and known failure modes | Reproducible test or human review |
| Semantic knowledge | Facts, APIs, manuals and research | Source, version, date and confidence |
| Project memory | Decisions, files, constraints and milestones | Repository commit or owner decision |
| Hypotheses | Unverified ideas | Explicitly labelled, never presented as fact |

Important rules:
- Append new versions instead of silently overwriting history.
- Mark superseded or expired knowledge.
- Distinguish observed, owner-provided, retrieved, inferred and guessed information.
- Require citations to sources actually opened.
- Allow abstention when evidence is missing or stale.
- Skip memory retrieval for self-contained trivial turns.
- Evaluate multi-session recall, temporal updates, conflicting facts and forgetting of superseded facts.

For general knowledge, retain domain-level reporting. An overall pass rate must not hide a weak area such as science, geography, programming or history. Development suites are for iteration; use a sealed holdout before model promotion.

## 4. Real-time gaming: skill acquisition, not button replay

A useful game agent needs three loops:

- **Reflex:** short-deadline perception and immediate bounded reactions.
- **Tactical:** positioning, pathing, cooldowns, threat selection and short-horizon prediction.
- **Strategic:** mechanics, map knowledge, build choices, practice curriculum and post-match analysis.

The learning protocol should be:

1. Identify the game, allowed controls, objective and failure conditions.
2. Capture a baseline on preregistered scenarios.
3. Practice in a private/training environment.
4. Classify errors: perception, prediction, timing, pathing, execution or strategy.
5. Change one skill at a time.
6. Retest on matched scenarios.
7. Test transfer on an unseen map, level or rules variant.
8. Keep the skill only when outcome quality improves without unacceptable latency or safety regressions.

Score actual objective completion, survival, action validity, reaction deadline, recovery time and transfer performance. A keypress acknowledgement is not proof that the game world changed. A paused-game result is not evidence of real-time mastery.

OpenGameEval is relevant because it evaluates agents inside reproducible, stateful Roblox Studio sessions and checks both edited scenes and simulated play. It separates observation tools from editing tools, so exploration quality can be measured. Gym-Anything-RT is relevant because it compares real-time interactive environments with paused/slowed conditions. These studies motivate real-clock, outcome-based tests rather than text-only reasoning scores.

## 5. Game creation: inspect, build, playtest, repair

STAR Creator should use a closed verification loop:

\`\`\`text
Inspect project hierarchy and references
  -> state requirements and acceptance checks
  -> edit an isolated test place
  -> run static Luau checks
  -> launch a real playtest
  -> inspect screenshots and runtime state
  -> check input, camera, physics, replication and UI
  -> repair one defect
  -> rerun the same test
  -> run a held-out scenario
  -> preserve evidence and rollback point
\`\`\`

A successful compile is not a successful game. Validate actual playability, multiplayer ownership, mobile UI, animation rigs, collision, audio, visual consistency, frame-time and memory budgets. Keep public publishing, purchases, account changes and destructive edits behind owner approval.

## 6. Natural VTuber streaming

The streaming architecture should have a fast live loop and an asynchronous deep loop.

### Live loop
- incremental audio and game-event perception;
- speaker and addressee classification;
- end-of-turn and interruption detection;
- choose speak, acknowledge, defer or silence;
- short, deadline-aware commentary;
- immediate stop of audible output on a verified barge-in;
- synchronized avatar expression and mouth movement.

### Background loop
- research;
- memory retrieval;
- long reasoning;
- game strategy;
- viewer-question preparation;
- creator tasks.

Background results must be checked for age and relevance before they can affect the current live turn. They must never delay urgent speech cancellation.

LiveKit's turn-handling documentation is useful here: interruption handling pauses speech and truncates the conversation history to the portion the user actually heard. STAR should preserve the same semantic invariant even if its audio stack is custom. If TTS is interrupted, memory must not store the unheard remainder as something STAR said.

Human-like streaming quality should mean natural timing and context, not pretending to be a human. Measure:
- false interruption and missed interruption rates;
- interruption-to-silence p50/p95;
- first-audible-PCM p50/p95;
- false-interruption recovery;
- unnecessary response rate;
- addressee accuracy;
- correct silence;
- avatar reaction timing;
- viewer-reviewed conversational coherence.

Natural streams need quiet stretches, varied delivery, relevant humor and brief reactions during danger—not narration of every frame or filler on every pause.

## 7. Hardware and resource policy

The RTX 4060 8 GB target must share resources with the game, OBS, avatar and audio. Do not optimize a model in isolation and then discover that the game stutters.

Recommended priority order:
1. Preserve audio stop/cancel and owner interruption.
2. Preserve game frame-time and OBS output stability.
3. Preserve first-audible response latency.
4. Admit background reasoning/research only from remaining CPU, RAM, VRAM and time budget.
5. Pause or reduce nonessential indexing, training and asset generation during gameplay.

CPU offload, quantization, context size, KV-cache type, flash attention, speculative decoding and GPU layer count are workload-specific experiments. Change one variable at a time, retain a baseline, and revert automatically if paired quality or runtime stability regresses. No universal setting is assumed to be best for an 8 GB card.

## 8. Prioritized implementation roadmap

### P0 — Evidence and quality gates
- Implemented: paired latency + general-knowledge evidence gate.
- Run a real model comparison with the exact local model artifacts.
- Add a sealed knowledge/code/game/voice holdout.
- Connect server counters and client timings to a shared experiment ID and monotonic window.
- Keep route changes manual.

### P1 — Real Windows VTuber acceptance
- Add process-specific TTS audio receipts, not endpoint-wide audio that mixes game and alerts.
- Pin OBS process/socket epoch and use read-only telemetry.
- Pair game frame-time, GPU/VRAM, OBS drops, first audible PCM and interruption-to-silence.
- Run a 30–60 minute private rehearsal with the broadcast destination disabled.
- Compare baseline/candidate with randomized ON/OFF blocks and preserve all failures.

### P1 — Game mastery
- Build a private training curriculum with matched and held-out maps.
- Use game-world outcome receipts, not just input-driver acknowledgements.
- Add transfer tests and regression protection for already learned skills.
- Keep reflex decisions independent of long-form reasoning.

### P2 — Creator and generalist skills
- Integrate inspect-first Roblox Studio tasks and repeatable playtests.
- Add Blender asset validation, rig/animation checks and visual regression.
- Add source-backed science, history, mathematics, geography, computing and language curricula.
- Retain verified procedures, not unreviewed model-generated lessons.

## 9. Verification and limitations

The new gate is a deterministic offline evidence analyzer. Its tests use synthetic reports and validate the gate's behavior; they do **not** show that any model is faster or smarter.

The gate's input identities are operator-declared, not cryptographically authenticated. The 24-task general-knowledge suite is public development data, not a holdout. Paired inference first-content timings are client-observed and do not isolate tokenizer-level TTFT or GPU kernel execution. Optional llama.cpp metrics are aggregate and can include concurrent clients.

Before any candidate is used for live VTubing, require:
- sealed quality holdout;
- real-time game outcome evaluation;
- actual Windows hardware telemetry;
- process-specific audible TTS timing;
- OBS and game stability;
- a private nonbroadcast rehearsal;
- human review and explicit owner approval.

## Primary sources (checked 2026-11-10)

- NVIDIA AIPerf, [metrics reference](https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference) — request, TTFT, TTST, ITL, latency distributions and throughput semantics.
- llama.cpp, [server metrics documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#-metrics-prometheus-compatible-metrics-exporter) — \`/metrics\`, \`--metrics\`, router model scoping and metric types.
- vLLM, [Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) — shared-prefix KV reuse and prefill/decode limits.
- Roblox, [OpenGameEval](https://github.com/Roblox/open-game-eval) and [paper](https://arxiv.org/abs/2610.02563) — stateful Studio evaluation, exploration and simulated play.
- Aggarwal & Welleck, [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), submitted 2026-10-27 — real-time visual-agent evaluation.
- LiveKit, [turn handling and interruptions](https://docs.livekit.io/agents/logic/turns/) — barge-in, interruption and speech-history semantics.
- OBS Project, [obs-websocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md) — read-only host telemetry and session protocol.

## Implemented in this PR

- \`star/model_quality_speed_gate.py\`
- \`tests/test_model_quality_speed_gate.py\`

No production model route, runtime setting, OBS session, game input, microphone, avatar, broadcast or model weights are changed.
