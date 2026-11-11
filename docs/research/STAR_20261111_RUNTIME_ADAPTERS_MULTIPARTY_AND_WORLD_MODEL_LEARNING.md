# STAR Research: Runtime Adapters, Multiparty Streaming, World-Model Learning & Efficient Inference

**Research date:** 2026-11-11  
**Implementation scope:** explicit Python telemetry adapters and an evidence-led roadmap  
**Status:** research-backed integration seam; no live host wiring or hardware claims

## Executive findings

STAR's recent work added three useful foundations: a bounded W3C-compatible trace ledger, llama.cpp metrics parsing, and existing stream/game/hardware evidence systems. The next step should not be another autonomous agent. It should be a small set of explicit adapters that connect validated outputs from those systems to one trace without moving sensitive content into telemetry.

This update adds that bridge for:
- llama.cpp interval metrics;
- trusted hardware snapshots;
- StreamDirector aggregate counters;
- speech proposal/completion decisions;
- game-skill summary counts;
- long-task checkpoint counts.

It deliberately does not add polling, networking, OpenTelemetry export, automatic runtime hooks, game controls, audio capture, or permission changes.

## 1. Multiparty voice is the hard part of natural streaming

### InteractionBench (November 2, 2026)

InteractionBench evaluates conversational timing, spoken-task accuracy, whisper/volume control, and groundedness across more than 20-turn conversations. Its evaluation emphasizes the client-heard output timing rather than treating model-side generation timestamps as end-to-end latency.

Source:
- https://arxiv.org/abs/2611.02430

**STAR implication:** measure the complete path from input audio to audible output. Track VAD/endpointing, floor decision, model first content, TTS first audio, speaker queue, device playback acknowledgement, and avatar update separately. Do not optimize TTFT while ignoring playback delay.

### MP-Bench (Findings of EMNLP 2026)

MP-Bench evaluates voice agents as active participants in multiparty conversation. The paper reports that evaluated real-time agents remain at or below 22% on multiparty comprehension and near chance on multiparty turn-taking.

Source:
- https://aclanthology.org/2026.findings-emnlp.1437/

**STAR implication:** a one-user voice pipeline is not sufficient for a livestream. Add speaker-grounded memory and explicit addressee inference. The social director should choose among:
1. answer a direct question;
2. acknowledge a short backchannel;
3. continue listening;
4. remain silent because viewers are talking to each other;
5. stop speaking because a human has resolved the question;
6. yield to a genuine interruption.

Do not infer a person's identity from voice alone or store raw voiceprints by default. Use platform-provided, session-scoped speaker IDs when available, and keep them out of diagnostic traces.

### Duplex-MPE (September 25, 2026)

Duplex-MPE contains 2,000 scenarios with three or four human speakers plus an assistant. It separately scores response initiation, answer accuracy, silence preservation, and stopping when a human resolves a request.

Source:
- https://arxiv.org/abs/2609.31948

**STAR implication:** "more talking" is not the objective. Silence and stopping at the right time are measurable capabilities. Include paired explicit-versus-implicit addressing tests, human-resolution tests, and overlapping-speech tests.

### Full-Duplex-Bench v3

The benchmark uses 100 human-recorded requests across 79 scenarios and 12 speakers, including disfluencies and chained tool calls. It scores tool-call accuracy, Pass@1, latency and turn-taking.

Source:
- https://www.full-duplex.ai/benchmarks/fdb-v3

**STAR implication:** evaluate spoken self-corrections, multi-step spoken requests and tool execution—not just transcription quality.

## 2. Inference speed: distinguish applicable methods from research-only ideas

### SpecCache (ACL 2026)

SpecCache uses a speculative model to help identify important KV entries for RAG serving. Its paper reports 2.17–3.95x TTFT reduction and 2.7–5.2x throughput versus full KV recomputation in its evaluated settings.

Source:
- https://aclanthology.org/2026.acl-long.859/

These are paper-specific results, not a promised gain for STAR, llama.cpp, or an 8 GB RTX 4060. Treat this as a design to study only if long-context RAG prefill is measured as a bottleneck.

### Probe-and-Fetch (WWW 2026)

Probe-and-Fetch combines speculative drafting with content-aware KV selection and asynchronous fetching to overlap work that would otherwise serialize.

Source:
- https://doi.org/10.1145/3774904.3792794

**STAR implication:** the useful principle is overlap and prefetch, not copying a large serving framework into the local desktop app. First measure cache hit rate, prefill time, host-to-device transfer, queue wait and VRAM pressure.

### Spexis (September 28, 2026)

Spexis explores speculative parallelism and lookahead scheduling for multi-GPU vLLM serving, reporting up to 34% improvement over its selected parallel baseline.

Source:
- https://arxiv.org/abs/2609.34370

**Applicability:** this is primarily a multi-GPU serving direction. It is not a first choice for STAR's single 8 GB consumer GPU target.

### llama.cpp metrics

llama.cpp exposes a Prometheus-compatible endpoint when metrics are enabled. Router mode requires a model selector. The documented metrics include prompt/generation counters and rates, processing/deferred request gauges, context high-water mark and decode activity.

Source:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**STAR implication:** keep the existing parser read-only. Poll off the latency-sensitive path, tag each server restart with a new instance epoch, and correlate process counters with request-level TTFT/TTST and game/OBS measurements. Never use a process-wide throughput gauge as an individual request's latency.

### Recommended 8 GB GPU order

1. Keep the interactive model resident; avoid reloads during a stream.
2. Bound context by task and summarize/retrieve older history.
3. Keep concurrency low enough to protect audio and game frame times.
4. Measure prompt-prefix reuse before enabling caching features.
5. Compare quantization on task quality and latency, not tokens/s alone.
6. Test speculative decoding with a representative draft model and real prompts.
7. Measure CPU/GPU layer placement under concurrent game and OBS load.
8. Add KV quantization/offload only after proving the current KV cache is the bottleneck.

Use paired baseline/candidate runs and report p50/p95/p99 TTFT, TTST, audible first-response time, generated tokens/s, VRAM peak, game frame-time p95/p99, OBS render lag, audio underruns and task success.

## 3. Game mastery: learn environment dynamics, not just button sequences

### Voyager

Voyager's reusable pattern is an automatic curriculum, an executable skill library, and iterative improvement using environment feedback and self-verification.

Sources:
- https://arxiv.org/abs/2305.16291
- https://github.com/MineDojo/Voyager

**STAR implication:** store skills as versioned, composable procedures with preconditions, expected observations, failure conditions and independent outcome evidence. A remembered sequence is not mastery.

### MechEval / WARC (November 9, 2026)

This recent preprint studies how many exposures a world model needs to learn unfamiliar game mechanics. It introduces 69 recurring mechanics across 20 games and reports test-time adaptation on held-out games.

Source:
- https://arxiv.org/abs/2611.12324

**STAR implication:** build a compact, game-specific dynamics model:
- observe state;
- choose an informative, low-risk action;
- predict the state transition;
- compare prediction with the next observation;
- update the mechanic hypothesis;
- test it on a new state.

Track prediction calibration and held-out transfer. Do not let an LLM's verbal explanation count as proof that a mechanic was learned.

### ARC-AGI-3 caution

Interactive game benchmarks can be vulnerable to trivial action policies or interface loopholes. STAR should record the benchmark version, tool/API version, action budget and independent test set, and should avoid claiming general game intelligence from public examples alone.

Reference:
- https://github.com/arodmor/arc-agi-3

### Roblox creator loop

Roblox describes an agentic Plan → Build → Test workflow, including automated playtesting and analysis of code, DataModel and logs.

Source:
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

**STAR implication:** bind every Studio tool operation to an explicit studio instance and project version. Run playtests in isolated places. Verify output with logs and actual gameplay. Publishing, economy changes, moderation, and live-player operations remain separate owner-approved actions.

## 4. Continual learning and general knowledge

### SkillLearnBench (April 22, 2026)

SkillLearnBench evaluates skill quality, execution trajectory and task outcome across 20 tasks and 15 subdomains. Its analysis finds that no continual-learning method wins across every task/model combination; external feedback and repeated iterations matter, while self-feedback alone can drift.

Sources:
- https://arxiv.org/abs/2604.20087
- https://cxcscmu.github.io/SkillLearnBench/

**STAR implication:** learning should be a controlled lifecycle:
1. acquire evidence from a source or task;
2. store provenance, version and freshness;
3. propose a reusable skill or knowledge item;
4. run external tests;
5. evaluate on held-out instances;
6. compare against the previous version;
7. promote only if quality improves without regressions;
8. retain rollback information.

General knowledge should use source diversity, date awareness, confidence calibration and contradiction handling. A large vector database is not a measure of knowledge quality.

## 5. New implementation: explicit AgentTrace adapters

### Files

- star/agent_trace_adapters.py
- tests/test_agent_trace_adapters.py
- Updated star/agent_trace.py event and attribute allowlists.

### Adapter methods

| Method | Source | Recorded facts |
|---|---|---|
| record_llama_delta | LlamaCppMetricsDelta | interval rates, queue gauges, speculative acceptance, counter anomalies |
| record_hardware_snapshot | HardwareSnapshot | used/free VRAM, free RAM, CPU busy |
| record_stream_director_metrics | StreamDirector.metrics() | accepted/rejected/expired/evicted/completed/abandoned/queued counts |
| record_speech_intent | SpeechIntent | safe speech category, interruption flag, untrusted-context flag |
| record_speech_completion | host completion signal | success/cancelled outcome and interruption flag |
| record_game_learning_summary | GameSkillMemory.summary() | sessions, episodes, state/action counts |
| record_checkpoint_progress | len(StepCheckpoint) | completed step count only |

The adapters:
- require explicit calls from trusted host code;
- use a host monotonic clock;
- accept only exact aggregate schemas;
- reject booleans as integer counters;
- never record prompt/chat/transcript/audio/image payloads, speaker IDs, signal IDs, task scope, checkpoint keys, or checkpoint results;
- do not perform device I/O or network calls;
- do not create or authorize actions.

## 6. Recommended integration sequence

1. **Model host:** record a request span and attach llama.cpp interval samples as separate process observations.
2. **Stream director:** record proposal/completion events after the arbitration decision, not on every raw chat message.
3. **Audio host:** add VAD, endpointing, TTS-first-audio, queue submission and device playback acknowledgements from trusted callbacks.
4. **Avatar host:** record animation update and lip-sync epoch timing; do not store face/voice media in traces.
5. **Game host:** record observation/action/verified-outcome spans with explicit game version and Studio ID.
6. **Task runner:** connect checkpoint counts and task resume events without recording task text.
7. **Trace viewer:** display the critical path and resource state locally, with bounded retention and redacted export.
8. **Optimization loop:** use paired runs and task-quality gates before changing routing, quantization, concurrency or QoS.

## 7. Acceptance tests

### Voice and streaming
- Directly addressed request versus side conversation.
- Explicit versus implicit addressing.
- Acknowledgement while Star is speaking.
- Genuine interruption and false interruption recovery.
- Human answers another viewer's question; Star stays silent.
- Self-correction and multi-step spoken tool request.
- End-to-end first-audible latency and avatar/audio synchronization.

### Gaming
- Learn one unknown mechanic from controlled exposures.
- Predict the next state before observing it.
- Update the model after a failed prediction.
- Transfer the mechanic to a held-out level/seed.
- Keep practice and validation evidence separate.

### Intelligence and knowledge
- Resolve conflicting sources with dates and provenance.
- Detect stale knowledge after an API/game update.
- Demonstrate skill transfer to a new task instance.
- Measure regression after memory or skill promotion.

### Performance
- Idle, game-only, voice-only, game+voice, full OBS stream, and full stream+background research.
- Report p50/p95/p99 latency and frame times.
- Track VRAM, RAM, CPU, audio underruns and OBS render lag.
- Require no quality regression and no interactive-frame/audio regression before adopting a faster model configuration.

## 8. Validation boundary

This PR adds explicit adapters and offline tests only. It does not wire them into Windows audio, VTube Studio, OBS, Roblox Studio, a live model host, or the game controller. It does not demonstrate a speedup, higher intelligence, human-equivalent behavior or game mastery. Those claims require actual host integration, completed CI, paired benchmarks and hardware acceptance tests.
