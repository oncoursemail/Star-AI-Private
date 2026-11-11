# STAR research: stream failure diagnostics, multiparty floor control, and task continuity

**Research date:** 2026-11-11  
**Target:** STAR local-first desktop runtime, optional STAR Server, live VTuber voice/game/creator workflows  
**Status:** One opt-in benchmark observability improvement is implemented in the stacked development PR. The research integrations below remain proposals unless explicitly marked implemented.

## Executive summary

The next bottleneck is not simply raw tokens per second. STAR must know whether a stream is healthy, whether an interruption invalidated an answer, whether a multi-person conversation has actually yielded the floor, and whether a task remains unfinished after the user changes direction.

This refresh adds a bounded, privacy-preserving failure taxonomy to STAR's local streaming benchmark and connects three newer research findings to concrete runtime requirements:

1. **Joi-Bench-Task (2026-11-09):** full-duplex agents can lose task obligations when a user redirects or interrupts them. STAR needs an explicit task ledger that separates execution state from what has been communicated.
2. **MultiPartyTurnBench (2026-10-14):** multi-speaker floor control is not the same as dyadic end-of-turn detection. STAR needs separate EOT, interruption, backchannel and addressee decisions.
3. **LongMINT (2026-05-18):** memory retrieval and construction remain weak under revisions and interference. STAR needs revision-aware evidence, not a single mutable fact string.

These findings should be combined with AIPerf, TurnBench, Full-Duplex-Bench v3, OpenGameEval, SIMA 2, and STAR's existing QoS, skill, memory and stream-rehearsal work.

## 1. Repository audit and implemented change

The current development PR already adds an opt-in local streaming inference probe. It records first-content latency, second-content chunk timing, request latency, inter-chunk gaps and throughput. It correctly states that arbitrary API chunks are not tokens and must not be labelled token-level ITL.

### Gap found

The probe previously collapsed all failures into a single failed count. An empty stream, timeout, rate limit, server error, connection failure and protocol error were indistinguishable. A partial response followed by a transport failure was also not visible in aggregate output.

This makes performance tuning less actionable: a slow model, an overloaded server and a disconnected endpoint can all appear as the same failed request.

### Implemented on the existing inference PR branch

The file star/inference_benchmark.py now assigns a bounded, content-free category to failed requests:

- empty_stream
- timeout
- rate_limited
- client_error
- server_error
- connection_error
- protocol_error
- request_error

The summary also reports:
- failure_categories: sorted category counts;
- failed_requests_with_partial_content: failed requests that emitted content before failing;
- partial_content_chunks_discarded: content chunks from failed requests, excluded from successful throughput.

Raw exception messages, response text, headers and credentials are never included. A missing category from an older synthetic fixture is reported as unspecified. Existing successful-request throughput continues to exclude failed/partial streams.

The implementation is deliberately conservative. It classifies by exception type and numeric HTTP status only; it does not attempt to parse provider-specific error messages. It does not prove that a server-side stream completed semantically, nor does it infer token-level timing.

### Tests added

The synthetic tests cover:
- empty streams;
- timeout after partial content;
- HTTP 429 rate limiting;
- bounded category validation;
- exclusion of partial output from successful chunk throughput;
- absence of exception text from the returned report.

No model endpoint, GPU, microphone, audio device or livestream is contacted by these tests.

## 2. Joi-Bench-Task: preserve obligations through interruption

**Source:** He et al., *Joi-Bench-Task: Benchmarking Task Coordination in Full-duplex Voice Agents through Interactive Simulation*, arXiv:2611.12118, submitted 2026-11-09.  
https://arxiv.org/abs/2611.12118

The benchmark introduces a controllable user simulator that intervenes during tool execution and spoken result delivery. It evaluates whether the agent tracks:
- what is being executed;
- what has completed;
- what has been communicated;
- what remains to be reported.

The paper reports persistent coordination failures among the evaluated agents. Under request changes, the highest reported task-completion rate is 55%; after interruption, four of five agents have average information-omission rates of at least 23%.

### Application to STAR

STAR should maintain a host-owned task ledger independent of the language model's transcript:

| State | Meaning | Allowed transition |
|---|---|---|
| requested | User/viewer asked for work | accepted, declined |
| accepted | STAR committed to the task | running, cancelled |
| running | Tool/worker is executing | paused, superseded, completed, failed |
| paused | Work is resumable | running, cancelled, superseded |
| superseded | New request changes the target | running only after explicit reconciliation |
| completed | Verifiable work is complete | terminal |
| failed | Work did not complete | running only as a new attempt |
| communicated | Result was actually delivered | terminal communication receipt |

Keep execution completion and communication completion separate. A tool may have completed while speech was interrupted; the user may still need the result. Conversely, saying "done" must never mark an unfinished tool task complete.

On interruption:
1. stop or cancel the current speech turn;
2. invalidate speculative text and stale tool proposals;
3. preserve completed tool receipts;
4. retain unfinished obligations as pending;
5. reconcile the new request against prior tasks;
6. tell the user what changed and what remains, without repeating already delivered details.

A request change must not silently discard earlier work. It may explicitly supersede it, but the ledger should preserve that transition and its reason.

## 3. MultiPartyTurnBench: distinguish floor control from transcription

**Source:** Mathur and Manocha, *MultiPartyTurnBench: Benchmarking Floor Control in Multi-Party Spoken Dialogue*, arXiv:2610.20172, submitted 2026-10-14.  
https://arxiv.org/abs/2610.20172

The benchmark contains 240 synthetically generated, channel-separated conversations with two to five speakers and six interaction types. It separates:
- end-of-turn detection (EOT): a speaker has genuinely yielded the floor;
- interruption detection (INT): another speaker has genuinely taken the floor.

The paper reports that full-duplex agents can perform well on ordinary turn entry while remaining near chance on selective interruption handling. The benchmark also exposes the trade-off between missed takeovers and false activation on backchannels.

### Application to STAR's Social Director

Do not collapse these decisions into one should_speak boolean. Maintain separate short-lived events:

- speaker_active
- utterance_complete
- floor_yielded
- floor_taken
- backchannel
- addressee_hypothesis
- topic_changed
- viewer_addressed_star

Each event should carry a session-local speaker ID, timestamp, confidence, expiry and evidence source. Speaker identity should remain ephemeral unless the user explicitly opts into durable memory.

The Social Director should choose among:
- speak;
- brief backchannel;
- react silently through the avatar;
- wait;
- ask for clarification;
- yield the floor.

Silence is a valid action. Do not optimize for maximum reply count.

### Evaluation plan

Use a staged evaluation:
1. synthetic MultiPartyTurnBench-style fixtures for deterministic edge cases;
2. TurnBench for real dyadic human conversation;
3. MP-Bench for multiparty comprehension and appropriateness;
4. private, consented stream rehearsal with anonymized speaker labels.

Report EOT recall, interruption precision/recall, false activations on backchannels, detection latency, addressee accuracy, response appropriateness and silence preservation separately. Synthetic multi-party audio is useful for controlled tests, not a substitute for natural human recordings.

## 4. LongMINT: memory must survive revisions and interference

**Source:** Lee et al., *LongMINT: Evaluating Memory under Multi-Target Interference in Long-Horizon Agent Systems*, arXiv:2605.18565, submitted 2026-05-18.  
https://arxiv.org/abs/2605.18565

LongMINT contains 15.6k question-answer pairs over evolving long-horizon contexts, averaging 138.8k tokens and extending to 1.8M tokens per instance. The evaluated systems averaged 27.9% accuracy in the paper's reported setting. The authors identify retrieval and memory construction as major limitations, particularly when facts are revised or multiple evidence items must be aggregated.

### Application to STAR

Represent a durable memory claim as an evidence-backed record, not a mutable sentence:

- claim ID and normalized claim;
- entity and scope;
- source ID, source revision and observed-at time;
- valid-from / valid-until interval where applicable;
- confidence and verification state;
- supersedes / conflicts-with links;
- dependency and project-version fingerprint;
- privacy class and retention policy.

When a newer fact conflicts with an older one, preserve both with provenance and mark the old record superseded for the relevant scope. Do not delete the historical record or silently average contradictory facts.

For procedural game skills, also store:
- engine/game version and control-map fingerprint;
- preconditions and observation requirements;
- executable or bounded action recipe;
- expected state transition;
- independent success checks;
- failure modes;
- held-out transfer results;
- last verified timestamp.

A skill should expire or require revalidation when its game version, physics, map, controls or tool schema changes.

Keep the existing governed consolidation and review gates in the promotion path. This research does not justify automatic promotion of model-generated memories.

## 5. AIPerf and local inference: measure the right layer

**Sources:**
- NVIDIA AIPerf metrics reference: https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

AIPerf distinguishes TTFT, TTST, TTFO, ITL and inter-chunk latency. These metrics answer different questions:
- TTFT: how long until the first qualifying output;
- TTST: how long until the second qualifying response;
- TTFO: when user-facing non-reasoning output begins;
- ITL: token-level generation cadence when token accounting supports it;
- ICL: inter-chunk arrival gaps.

STAR's lightweight probe is a local smoke benchmark, not a replacement for token-aware AIPerf. Keep its second-content measurement explicitly labelled as a chunk-level analogue, not TTST.

For llama.cpp, match benchmark concurrency to the configured server slot count for the primary throughput comparison, then run a separately labelled overload test. Record the exact model hash, quantization, backend, build, context, slot count, CPU threads, KV-cache types and speculative settings.

Run the same workload in these conditions:
1. idle inference;
2. game only;
3. game + OBS + avatar;
4. voice + game + OBS + avatar;
5. full stream plus bounded background research.

Report p50/p95/p99 latency, successful output throughput, failures, audio underruns, game frame-time, OBS render lag, OBS encode lag and network drops. Never call an idle-only speedup a live-stream improvement.

## 6. Game mastery and creator intelligence

### SIMA 2

Google DeepMind's SIMA 2 research demonstrates language-guided planning and action in diverse 3D worlds, including held-out environments. It is a research reference, not a drop-in local runtime for STAR.  
https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

Apply the evaluation idea: test goals in unseen worlds, ground actions in current observations, and measure task success rather than plausible narration.

### OpenGameEval

Turkel et al., *OpenGameEval: Benchmarking Agentic Programming and Exploration in a Stateful Game Engine*, arXiv:2610.02563, 2026-10-01.  
https://arxiv.org/abs/2610.02563  
https://github.com/Roblox/open-game-eval

The October 2026 paper reports 84 human-curated Roblox Studio tasks, 13 evaluated models and 16 attempts per task. The best reported pass@1 is 51.7%; best five-of-five consistency is 39.4%. The paper reports that inspecting the objects touched by a task before editing improves pass rate by 13.4 percentage points on scene-only tasks and 9.8 points on script-only tasks.

For STAR Creator, keep observation and mutation tools separate. Require a read-only exploration plan, inspect relevant scene objects/scripts, make a minimal isolated edit, run Luau/static checks, simulate play, verify the resulting state, inspect screenshots/video, and test a held-out scenario. Use a disposable place and explicit publishing permission.

## 7. Unified real-time runtime

The architecture should remain event-driven and bounded. Avoid a swarm of always-on models competing for an 8 GB GPU and CPU time.

| Priority | Work | Runtime rule |
|---|---|---|
| P0 | Audio callback, stop/interrupt, playback clock | No LLM, disk, network or blocking wait |
| P1 | Speech response, immediate game control | Deadline-aware; bounded resource reserve |
| P2 | Current conversation, strategic game reasoning | Cancellable; stale proposals expire |
| P3 | Research, memory retrieval, skill practice | Defer under live pressure |
| P4 | Indexing, consolidation, training experiments | Idle windows only |

Every asynchronous task needs:
- immutable task ID;
- creation time and deadline;
- cancellation token;
- resource estimate;
- input observation/version fingerprint;
- output provenance;
- explicit state transition;
- completion receipt;
- user-communication receipt.

A model may propose actions or memories; the host owns permissions, scheduling, task state, validation and promotion.

## 8. Recommended acceptance campaign

A private, consented 60-minute rehearsal should include:
- a game with unfamiliar mechanics;
- multiple consenting test speakers;
- planned backchannels and interruptions;
- at least one viewer changing a request mid-tool-call;
- one completed task whose spoken report is interrupted;
- one intentionally failed model stream;
- background research pressure;
- OBS and avatar activity.

Required evidence:
- stream failure taxonomy and partial-output counts;
- first-content and second-content distributions;
- token-aware AIPerf metrics where supported;
- EOT/INT and addressee metrics;
- task-ledger reconciliation accuracy;
- game task success and held-out skill transfer;
- audio underruns and actual device-output evidence;
- game frame-time;
- OBS render/encode/network counters;
- memory revision and stale-skill rejection tests.

No lane should pass from missing or under-sampled evidence. A rehearsal result should be eligible for owner review only; it must not silently change model routing, permissions, memories, game controls or broadcast settings.

## 9. Privacy and transparency

- Keep raw audio/video and transcripts out of generic long-term memory by default.
- Use ephemeral speaker labels for session-level turn-taking.
- Obtain explicit consent before retaining viewer-specific memories or using recordings for learning.
- Do not impersonate a human streamer. STAR can have a stable persona, humor, interests and expressive behavior while clearly identifying herself as an AI.
- Never claim a game win, task completion, source verification or spoken delivery without corresponding evidence.

## 10. Source index

- Joi-Bench-Task: https://arxiv.org/abs/2611.12118
- MultiPartyTurnBench: https://arxiv.org/abs/2610.20172
- LongMINT: https://arxiv.org/abs/2605.18565
- AIPerf: https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- TurnBench: https://github.com/SesameAILabs/turnbench
- Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- OpenGameEval: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

**Implementation boundary:** only the streaming benchmark's bounded failure labels and synthetic tests are changed in this update. The task ledger, Social Director changes, memory schema, model routing, game controller, avatar, OBS and broadcast integrations remain research recommendations pending their own reviewed implementations and hardware acceptance tests.
