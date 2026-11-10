# STAR — Cross-Modal Stream Timeline, Generalist VTuber and Runtime Research

**Research date:** 2026-11-10  
**Implementation:** bounded, opt-in event alignment in star/stream_event_timeline.py, plus compact event-bound context forwarded through star/stream_context_host.py → star/stream_brain_governor.py → star/stream_stage.py.  
**Scope:** a deterministic host-integration primitive, not a new perception model or a live streamer.

## Executive finding

The Star repository already contains distinct foundations for:

- audio turn-taking, active listening and interruption advice;
- visual novelty sampling and observation freshness;
- game state, practice evidence, skill memory and held-out transfer evaluation;
- stream event arbitration, speech pacing and voice-quality evaluation;
- hardware/OBS quality-of-service telemetry;
- general knowledge, project knowledge and sealed evaluations;
- paired local inference and quality-versus-speed gating.

The missing architectural seam is a small, explicit event-time layer. It should let those asynchronous host adapters describe what happened on one shared timeline without sending raw media through every subsystem or allowing a stale clock from one modality to be mistaken for current state from another.

This update supplies that seam and the missing final-mile context adapter: only the exact fresh event that caused a speech intent, plus a few aligned metadata pairs, can enter the live turn. It still does not add capture, diarization, transcription, OBS control, TTS, avatar control, game input, persistence or model inference.

## 1. New implementation: StreamEventTimeline

### Why it is needed

During a real livestream, the game observer, frame sampler, microphone/VAD, moderated chat adapter, avatar and audio playback worker all produce events asynchronously.

Without a shared event-time contract, the live agent can accidentally combine:
- a current speech turn with an old screenshot;
- a new visual hazard with an old game-state observation;
- a chat reaction that arrived after the moment it refers to;
- an avatar completion event from a previous session;
- timestamps from clocks that have been independently reset.

The new timeline correlates event time, not packet arrival order. It is deliberately content-free.

### Supported modalities

| Modality | Example host-classified events |
|---|---|
| Audio | speech start/end, owner interruption, background speech, backchannel |
| Vision | scene change, UI change, visual hazard/objective, screen observation |
| Game | objective change, damage, death, victory, respawn, state change, input acknowledgement |
| Chat | viewer question/reaction, moderation event, chat burst |
| Avatar | speech started/stopped, expression started/completed |
| Host | load pressure, session marker |

The host must classify events. An LLM's own statement that a hazard, interruption or successful action occurred is not trusted event evidence.

### Default bounds

| Bound | Default | Reason |
|---|---:|---|
| Ring buffer | 128 events | Fixed memory ceiling |
| Source watermarks | 16 | Bounds per-source replay state |
| Freshness TTL | 2,500 ms | Prevents old observations entering current context |
| Future tolerance | 25 ms | Small clock-jitter allowance |
| Alignment window | 250 ms | Finds nearby cross-modal events |
| Returned pairs | 32 | Bounds context and CPU cost |
| Event key | 20 hex characters | Opaque session-scoped reference |

These are engineering starting values, not calibrated performance claims. Measure the Windows host's adapter latency and clock skew before changing them.

### Reliability contract

- Owner approval is required to start a session.
- Each session receives fresh session and clock-epoch labels.
- Old-session and mismatched-clock events are rejected.
- Every modality/source pair has a strictly increasing sequence watermark.
- Replayed, out-of-order, stale and excessively future-dated events are rejected.
- A regressing or invalid host monotonic clock faults the session and clears buffered context.
- A source timestamp regression is rejected without advancing its watermark.
- Event count, source count, pair count and model-facing context bytes are bounded.
- Snapshots are ordered by capture time, not receive time.
- Pair proximity is not causality. Timestamp uncertainty is carried into each pair; if skew does not exceed the sum of both uncertainty bounds, relative order is marked uncertain.
- Stale events are pruned, while sequence watermarks remain so evicted events cannot be replayed.
- Disabling clears the session, buffer and watermarks.

### Privacy and trust boundaries

The timeline stores no audio bytes, video frames, transcripts, chat text, viewer names, account IDs, prompts, model outputs or credentials.

The returned event summaries and model-facing JSON contain only opaque event references, modality, event kind, age, confidence, uncertainty and alignment metadata. They omit raw source IDs, session tokens and evidence digests.

Hosts must use ephemeral sensor IDs, never viewer identities, as source IDs. A SHA-256 digest associates an event with evidence retained elsewhere; it does not authenticate the host, prove the evidence is genuine or prove the classification is correct.

The shared monotonic clock is also a host responsibility. This module does not convert Windows performance-counter values, audio sample clocks, video presentation timestamps or game-engine clocks. The adapter layer must translate them into one clock domain and provide a realistic uncertainty bound.

### Selective event-bound context: connecting the timeline to the live brain

The first timeline implementation could align events but did not yet forward them into the existing governed speech path. The follow-up adds star/stream_timeline_context.py and passes its packet through StreamContextHost, StreamBrainGovernor and StarStage.

The context builder:
- accepts only a TimelineSnapshot and the exact event key returned by the trusted host's IngestResult;
- selects one matching event and at most four fresh cross-modal pairs;
- emits at most 2,048 UTF-8 bytes;
- rejects a faulted clock, missing event, inconsistent age, stale event or malformed alignment;
- copies no raw source ID, session ID, clock epoch, evidence digest, transcript, media, viewer name or chat text; the packet constructor rejects extra JSON fields, duplicate keys and non-canonical payloads.

The stage attaches the packet only when all of these match:
1. the packet event key equals the selected StreamSignal.signal_id;
2. the event modality/kind is compatible with the selected speech intent (for example, a game_success requires a host-classified game victory event);
3. the snapshot is no more than 250 ms old at the moment of use;
4. the event remains within a 1,000 ms age budget;
5. a game-success signal is independently classified as observed.

A mismatched or stale packet is counted and omitted; it does not block an otherwise valid speech turn. The event key remains host-side correlation data and is not placed in the model-facing JSON.

**Why this matters:** it prevents a nearby but unrelated event, an old screenshot, or a delayed packet from contaminating the current reply. The packet is deliberately tiny so the live path does not pay for the full 16 KiB timeline snapshot on every turn. This is a context-size bound, not a measured token-latency improvement.

The host must still use the same monotonic clock for the timeline and stage. This bridge does not prove sensor truth, event causality or actual audible playback.

## 2. Research: what current voice-agent work teaches Star

### VAD is not end-of-turn detection

LiveKit's current turn-detector documentation explains that voice activity detection answers whether speech is present, while semantic end-of-turn detection predicts whether the speaker has finished. A thinking pause can be silent without being a completed turn. Its audio detector combines semantic and acoustic cues over VAD and supports dynamic endpointing. [LiveKit Turn Detector](https://docs.livekit.io/agents/logic/turns/turn-detector/)

**Star implication:** keep separate event types for speech start/stop, end-of-turn, addressee, backchannel and interruption. Do not reduce them to one is-speaking boolean.

### Evaluate the latency/false-cutoff tradeoff

LiveKit's open EoT benchmark evaluates pauses in real human-to-agent conversations. Its dataset spans 14 languages and labels every pause of at least 100 ms, distinguishing mid-turn hesitation from the final pause. The benchmark sweeps endpointing policies and reports a latency versus false-cutoff tradeoff rather than hiding it behind one accuracy number. [eot-bench](https://github.com/livekit/eot-bench) · [dataset and methodology](https://github.com/dlange-aai/livekit-eot-bench)

**Star implication:** evaluate each language and conversational situation separately. Report false cutoffs, missed interruptions, time-to-first-audible PCM, interruption-to-silence and recovery latency. Do not optimize delay by making Star interrupt people.

### Full-duplex conversation plus asynchronous delegation

Realtime-Venus (technical report dated September 12, 2026) describes two cooperating loops: one for live perception/speech and one for delegated background tasks. It preserves the request's originating context, lets background work proceed while conversation continues, and tracks whether a prepared reply was actually delivered. Its video-memory design retrieves selected frames by relevance and novelty instead of repeatedly processing every frame. [Realtime-Venus](https://realtime-venus.github.io/)

**Star implication:** urgent audio stop, owner interruption and short live reactions belong on a short path. Deep research, long reasoning, knowledge retrieval and game-strategy work should run asynchronously. A background result must be checked for age, session and project/game version before it can influence a current turn. Actual playback receipts—not generated text—must determine what Star said.

### Natural interaction includes appropriate silence

The Realtime-Venus evaluation separately measures continuing through backchannels, speech directed at other people, background speech and responding to actual interruptions. This supports Star's existing decision vocabulary: speak, acknowledge, hold, yield or remain silent.

**Star implication:** do not narrate every frame or respond to every chat line. Measure unnecessary responses and correct silence alongside response quality.

## 3. Research: real-time gaming and game creation

### Live-clock evaluation matters

Gym-Anything-RT (October 27, 2026) introduces 100 real-time minigames and controlled paused/slowed counterparts. Its abstract reports a large capability gap between acting while the world evolves and acting when the environment is paused. It also warns that code-writing agents can bypass the intended perception/action loop if the benchmark does not constrain the interaction channel. [Gym-Anything-RT](https://arxiv.org/abs/2610.37567)

**Star implication:** use the real game clock for gameplay acceptance. Score objective completion, valid actions, reaction deadlines, survival, recovery and transfer to unseen scenarios. A paused-game score or keypress acknowledgement is not proof of real-time game mastery.

### Generalist game agents learn through diverse environments

Google DeepMind's SIMA 2 research describes an agent that combines high-level reasoning with in-game action, conversation, self-directed practice and evaluation on held-out environments. It uses human demonstrations and model-generated labels, then explores self-directed play to improve in new worlds. [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/)

**Star implication:** retain the existing reflex/tactical/strategic split and test cross-game transfer. Build practice curricula from mistakes, but keep practice evidence separate from sealed evaluation. Never let a game agent inspect a hidden grader or validation roster.

### Roblox now exposes permission-scoped agent workflows

Roblox's April 15, 2026 roadmap describes a plan/build/test loop, structured plans, parallel task execution and playtesting against the original plan. Its November 4, 2026 Studio MCP/Open Cloud documentation adds the open_cloud_invoke tool, per-game and per-person permissions, access levels (Safe, Balanced, Full access, Custom), and approved upload folders. Full access includes scopes that can affect live players, publish to a live game, change monetization or access data. DataStore/MemoryStore access through execute_luau can reach live data, and HTTP requests require the Network capability plus an explicit domain allowlist. [Agentic Studio roadmap](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic) · [Studio MCP/Open Cloud permissions](https://create.roblox.com/docs/studio/mcp-open-cloud)

**Star implication:** Creator should use inspect → plan → isolated build → static checks → real playtest → visual/runtime inspection → repair → rerun → held-out test. Start with Safe or a narrowly customized scope set; do not request Full access for ordinary code/scene work. Keep approved asset folders separate. Use a private test experience for data-store work because Studio may access the same live data stores. Publishing, purchases, live settings, bans, secrets, player-data writes and cross-server messaging remain separate owner-approved operations.

## 4. Recommended Star architecture

**Host adapters**
- Audio/VAD/EoT adapter
- Vision/frame-novelty adapter
- Game-state/action observer
- Moderated chat-event adapter
- Avatar and actual PCM-playout observer
- Host QoS and shared-clock adapter

**Live path**
1. Receive host-classified events on a shared monotonic clock.
2. Reject stale, replayed, wrong-session or clock-mismatched events.
3. Build a small current timeline snapshot.
4. Combine event semantics with current turn state to choose speak, acknowledge, hold, yield or silence.
5. Keep urgent interruption and audio-stop handling outside the slow model path.
6. Record speech as delivered only after the host observes actual audible playout.
7. Animate speech-linked mouth movement only while matching audio is audible.

**Background path**
1. Capture a minimal immutable task context and originating session ID.
2. Route to a specialist: research, coding, knowledge, game strategy or creator.
3. Admit work based on real CPU/GPU/VRAM and stream QoS telemetry.
4. Cancel or deprioritize work when its session expires or game/OBS/audio headroom falls.
5. Return a bounded result with provenance and timestamp.
6. Revalidate age, session, project/game version and permissions before it can influence the live path.

The new timeline implements only the event-alignment primitive. Host adapters, queues, cancellation, TTS, avatar and OBS connections remain future integration work.

## 5. Faster inference without damaging gameplay

Star already has local paired inference benchmarks, llama.cpp server metrics, model quality/speed gates, resource planning, visual novelty sampling and streaming QoS. Do not add another generic tokens-per-second counter.

Use a fixed workload matrix on the actual target PC:

1. model only;
2. game only;
3. game plus model;
4. game plus OBS;
5. game plus OBS, TTS and avatar;
6. full workload plus vision and background research.

Record for each configuration:

- client first-content p50/p95;
- first-audible PCM p50/p95;
- inter-chunk gap p95;
- end-to-end response latency;
- prompt processing and decode throughput from server counters;
- CPU, RAM, dedicated/shared VRAM;
- game frame-time p50/p95 and 1% lows;
- OBS render/encode/network drops;
- audio underruns and interrupt-to-silence;
- task quality and held-out success.

Prioritize: (1) audio stop/owner interrupt, (2) game frame-time and OBS stability, (3) first audible response, (4) vision refresh, (5) background reasoning and indexing. Pause nonessential background work under pressure.

Keep client first-content latency, model TTFT, first-audible latency and first-avatar-reaction latency as separate measurements. They describe different stages.

NVIDIA AIPerf's metric reference is useful because it explicitly separates request latency, time-to-first-token (TTFT), inter-token latency (ITL), inter-chunk latency (ICL), and aggregate throughput. TTFT includes queueing, network transport, prompt processing and first-token delivery; it is not pure decode time. ITL excludes TTFT. Star should therefore preserve raw client timings and report p50/p95/p99 distributions instead of relabeling one end-to-end stopwatch as model speed. [AIPerf metrics](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference)

The llama.cpp server exposes prompt/decode counters, active/deferred requests, context high-water marks and speculative-draft acceptance through its Prometheus-compatible endpoint when metrics are enabled. In router mode the endpoint needs a model identifier. This is a useful server-side diagnostic complement to client timing, not a replacement for first-audible and game/OBS measurements. [llama.cpp server metrics](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

llama.cpp also supports speculative decoding with a smaller draft model and several n-gram methods. The official documentation exposes generated/accepted draft-token counts and acceptance rates. A high acceptance ratio is not itself proof of faster end-to-end speech: compare matched prompts, output quality, TTFT, ITL, first audible PCM and mixed game/OBS load. Keep a no-speculation baseline and disable a configuration that adds overhead or harms quality. [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)

## 6. General intelligence, memory and self-improvement

The existing repository already has knowledge stores, game-skill memory, practice ladders, mistake memory, transfer evaluation and sealed evaluation infrastructure. The next intelligence gains should come from making their evidence portable and trustworthy, not by stuffing every past interaction into the prompt.

M3-Agent (ICLR 2026) is a useful multimodal-memory reference: it builds episodic and semantic memory from ongoing visual/audio input and evaluates long-video understanding with M3-Bench (100 robot-perspective videos and 920 web videos). The practical lesson for Star is to keep event-level episodic records linked to source evidence and retrieve only relevant memories for the current task—not to retain every raw stream frame. [M3-Agent / M3-Bench](https://mlanthology.org/iclr/2026/long2026iclr-seeing/)

LongMemEval (ICLR 2025) provides 500 questions across information extraction, multi-session reasoning, temporal reasoning, knowledge updates, preferences and abstention, with long histories around 115K tokens per question in its S split. Star should use it to measure retrieval and temporal consistency, while keeping its own user data private and never placing the benchmark's hidden answers in prompts. [LongMemEval paper](https://xiaowu0162.github.io/publications/13_longmemeval/) · [official repository](https://github.com/xiaowu0162/LongMemEval)

| Memory class | Retain | Promotion evidence |
|---|---|---|
| Working | Current task/session state | Expires at task/session end |
| Episodic | Observed event, action and outcome | Host-observed receipt; owner review where public |
| Procedural | Reusable skill and failure-recovery steps | Reproducible practice plus independent holdout |
| Semantic | Facts, API behavior, manuals and research | Source URL, version/date, excerpt digest and confidence |
| Project | Owner decisions, constraints, commits and test results | Exact repository/commit or owner decision |
| Hypothesis | Candidate explanations and experiments | Remains unverified until tested |

Use append-only revisions, supersession links, source/version metadata, temporal validity and explicit abstention. An LLM's self-report is not evidence that a game action succeeded, a file changed or speech was audible.

A practical improvement loop is:
1. detect uncertainty or repeated failure;
2. formulate a falsifiable practice task;
3. retrieve current authoritative sources;
4. run a bounded experiment in a private environment;
5. measure actual outcomes;
6. compare with a frozen baseline;
7. test on unseen variants;
8. promote only the verified procedure;
9. retain the failure and rollback path.

## 7. Natural VTuber behavior: measurable acceptance criteria

Do not optimize for a vague human score. Use separate, reviewable measures:

- correct addressee and turn-taking decisions;
- false-cutoff and missed-interruption rates;
- unnecessary-response rate and correct-silence rate;
- first-audible and interruption-to-silence p50/p95;
- speech pacing, pause distribution and non-repetitive phrasing;
- game-event grounding and stale-observation rate;
- avatar reaction alignment with audible output;
- long-session memory consistency and correction handling;
- human reviewer ratings for relevance, warmth, humor and conversational flow;
- transparency: Star is presented as AI and does not claim human life, senses or experiences she does not have.

Naturalness should come from context-sensitive timing, varied delivery, evidence-based reactions and quiet stretches—not scripted filler, fake experiences or pretending to be human.

## 8. Integration and release plan

### Stage A — host adapter
- Add adapters for audio turn receipts, vision observations, game events, moderated chat events and audible/avatar output receipts.
- Map all source timestamps into one Windows host monotonic clock.
- Use ephemeral source IDs and per-session sequences.
- Calibrate timestamp uncertainty from measured adapter latency.
- Never include raw media or viewer identity in timeline metadata.

### Stage B — offline replay
- Replay a private, consented recording with known event annotations.
- Inject clock drift, delayed packets, duplicates, missing events, source restart and session rollover.
- Compare aligned pairs with human-annotated event windows.
- Measure stale-event leakage, false alignment, missing alignment and uncertainty coverage.
- Keep benchmark audio/video and transcripts in the private evaluation store, not Git.

### Stage C — private Windows rehearsal
Run the game, local model, OBS recording (not broadcast), TTS, avatar and background work simultaneously for 30–60 minutes. Verify actual CPU/RAM/GPU/VRAM, game frame-time, OBS render/encode drops, audio underruns, first-audible latency and physical stop behavior.

### Stage D — owner-approved live pilot
Only after offline replay and private rehearsal pass. Keep publishing, monetization, external messaging, player consequences, live game changes and broadcast controls separately owner-approved. A timeline event is never an authorization token.

### Release blockers
- No shared monotonic clock or known clock uncertainty.
- Any stale event can reach live context.
- Duplicate or old-session events can trigger a reaction.
- Model-generated event claims can be mistaken for host observations.
- Background tasks can block interruption or audio stop.
- Missing telemetry is treated as zero load or zero latency.
- An offline benchmark is treated as live deployment approval.

## 9. Verification and limitations for this change

The new packet builder was exercised in a clean scratch package with a minimal timeline-type stub:

- 6 focused scratch smoke checks passed after packet-schema hardening (fresh alignment, privacy omissions, stale/faulted snapshots, missing event, invalid event key and forged-field rejection).
- The new repository test file adds builder and stage-integration regressions, and tests/test_stream_context_host.py now covers the full context-host → governor → stage forwarding path.
- The repository integration tests have not been executed in this run; GitHub Actions is the independent verification step.
- Ruff was not installed in the scratch runtime.
- The connected starai Remote Desktop Commander device was online, but its monthly execution quota was exhausted. Repository-wide tests and native Windows rehearsal could not be run.

No inference speedup, game skill gain, improved model intelligence or live-stream acceptance is claimed. The 2 KiB context ceiling and freshness windows are policy bounds; their quality/latency tradeoff still needs replay and Windows measurements.

## Sources

1. LiveKit, [Turn Detector documentation](https://docs.livekit.io/agents/logic/turns/turn-detector/) — VAD versus semantic end-of-turn, endpointing and language support.
2. LiveKit, [eot-bench](https://github.com/livekit/eot-bench) and [dataset methodology](https://github.com/dlange-aai/livekit-eot-bench) — pause-level evaluation, multilingual coverage and latency/false-cutoff tradeoff.
3. Venus Team / Ant Group / Tsinghua University, [Realtime-Venus](https://realtime-venus.github.io/) — full-duplex interaction, asynchronous delegation and selected-frame long-video memory; report dated September 12, 2026.
4. Aggarwal and Welleck, [Gym-Anything-RT](https://arxiv.org/abs/2610.37567) — real-time versus paused visual game-agent evaluation; dated October 27, 2026.
5. Google DeepMind, [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) — multiworld game interaction, reasoning, practice and self-improvement; dated November 13, 2025.
6. Roblox, [Agentic Studio workflows](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic) — plan/build/test and playtesting; dated April 15, 2026.
7. Roblox Creator Hub, [Studio MCP and Open Cloud permissions](https://create.roblox.com/docs/studio/mcp-open-cloud) — per-game scopes, approved upload folders and high-risk operations; verified November 10, 2026.
8. NVIDIA, [AIPerf Metrics Reference](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference) — TTFT, ITL, ICL, request latency and throughput definitions.
9. ggml-org, [llama.cpp server metrics](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) — prompt/decode counters, queue gauges and speculative decoding metrics.
10. ggml-org, [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) — draft-model and n-gram methods plus accepted/rejected draft statistics.
11. Lin et al., [M3-Agent / M3-Bench](https://mlanthology.org/iclr/2026/long2026iclr-seeing/) — multimodal episodic/semantic memory and long-video QA benchmark; ICLR 2026.
12. Wu et al., [LongMemEval](https://xiaowu0162.github.io/publications/13_longmemeval/) and [official repository](https://github.com/xiaowu0162/LongMemEval) — 500-question long-term conversational memory benchmark; ICLR 2025.
