# STAR — Suspended Windows Worker Launch and Capability Roadmap

**Research snapshot:** 2026-11-10  
**Implementation branch:** `feat/windows-suspended-job-launch-20261110-auto11`  
**Stacks on:** PR #1118 (cross-platform worker process-tree supervision)  
**Scope:** Windows worker admission correctness, latency isolation, long-horizon memory, multiparty VTubing, real-time game mastery, game creation, and local inference.

## Executive summary

PR #1118 added POSIX process groups and Windows Job Objects, but its Windows path attached the Job Object after the child process had already started. A very short interval therefore existed in which a worker could spawn a descendant before containment was established.

This increment changes the Windows launch order:

1. Create the worker with `CREATE_SUSPENDED`.
2. Create/configure a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
3. Assign the still-suspended process to that Job Object.
4. Resume its initial thread only after assignment succeeds.
5. If assignment fails, either explicitly resume in documented `root_only` fallback mode or terminate the worker when tree containment is required.
6. If resume fails after assignment, close/terminate the Job Object and fail the launch; never silently run an uncontained worker.

The process's user code cannot create children before the assignment/resume sequence. This closes the child-spawn-before-assignment race during normal operation. It does **not** provide the stronger crash-atomic guarantee of assigning the job inside `CreateProcessW`; that remains a future native-launcher option using `STARTUPINFOEX` and `PROC_THREAD_ATTRIBUTE_JOB_LIST`.

No CPU, RAM, GPU, affinity, priority or memory caps are enabled. No neural speedup or gameplay improvement is claimed.

---

## 1. Windows process lifecycle research

### Job Objects

Microsoft describes Job Objects as a way to manage process groups as a unit, including descendant processes, termination, limits and aggregate accounting. By default, child processes created through `CreateProcess` join the job unless breakaway behavior is configured.

- Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- AssignProcessToJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
- QueryInformationJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject

### Why create suspended

The documented `CREATE_SUSPENDED` process-creation flag creates the primary thread in a suspended state. Microsoft documents that the initial thread does not begin executing until `ResumeThread` reduces its suspend count to zero.

- Process creation flags: https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags
- Suspending thread execution: https://learn.microsoft.com/en-us/windows/win32/procthread/suspending-thread-execution
- ResumeThread: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread

STAR now uses Tool Help thread enumeration to locate the suspended worker's initial thread, opens it with `THREAD_SUSPEND_RESUME`, and requires the previous suspend count to be exactly one. An unexpected count or API failure causes the contained launch to fail rather than guessing that the process is safe to resume.

The initial thread is the only worker thread expected before user code executes. The implementation does not use undocumented `NtResumeProcess`.

### Remaining stronger option

Microsoft documents `PROC_THREAD_ATTRIBUTE_JOB_LIST` for assigning one or more jobs during process creation on Windows 10 and newer / Windows Server 2016 and newer.

- UpdateProcThreadAttribute: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute

A future native launcher can create the process with `STARTUPINFOEX` and this attribute, so the job is assigned as part of creation. That is preferable where STAR needs to close the small creator-crash window between process creation and post-creation assignment. The current suspended-launch implementation prevents the child from executing during that window, but a parent crash could still leave a suspended process until an external cleanup mechanism reaps it.

### Failure semantics

| Condition | Required behavior |
|---|---|
| Job assignment succeeds; resume succeeds | `windows_job` |
| Job assignment fails; tree not required | Resume explicitly as `root_only`, preserving the diagnostic |
| Job assignment fails; tree required | Kill the still-suspended root and raise |
| Job assignment succeeds; resume fails | Close/terminate the job, kill the root, raise |
| Job API cannot be initialized while suspended | Kill the root; never leave it suspended indefinitely |
| POSIX launch | Keep existing new-session/process-group behavior |

The root-only fallback is a declared capability downgrade, not a claim of tree containment. Callers that execute untrusted or potentially spawning tools should request `require_tree=True`.

---

## 2. Protecting the live VTuber path

Star's live stream is a deadline-sensitive workload. Background work should be admitted only when it will not jeopardize audio, game control, avatar animation or OBS.

Recommended priority classes:

| Class | Work | Scheduling policy |
|---|---|---|
| P0 | Audio capture/playback, emergency stop, game input, OBS health | Reserved capacity; minimal queue delay |
| P1 | Direct viewer address, turn-taking, short response, avatar reaction | Bounded latency; preempt background work |
| P2 | Gameplay planning, scene commentary, current-stream reasoning | Preemptible at safe checkpoints |
| P3 | Deep research, coding, Blender renders, asset generation, memory consolidation | Background; pause/cancel under P0/P1 pressure |

Worker supervision is a prerequisite for this policy: cancellation must actually release the process tree. The new Windows suspended launch closes a race in that prerequisite; it does not itself implement a scheduler or impose hard resource caps.

Measure the full workload, not just model tokens/second:

- ASR partial/final latency and end-of-turn delay.
- First TTS audio chunk and first audible response.
- Audio underruns, queue depth and playback jitter.
- Game input-to-action latency and frame-time p50/p95/p99.
- OBS render/encode lag and dropped frames.
- CPU, RAM, VRAM, GPU utilization, disk I/O and worker count.
- Background cancellation latency and time until resource release.
- Task quality, factual support and conversational appropriateness.

A model/configuration is a win only when the target workload improves without unacceptable quality regression or live-path degradation.

---

## 3. Multiparty streaming: social intelligence, not just speech recognition

MP-Bench (Findings of EMNLP 2026) evaluates voice agents as active participants in multi-party conversations. In its reported study of 12 agents, real-time agents scored at or below 22% on multiparty comprehension and near chance on turn-taking. This indicates that single-user voice demos are insufficient evidence for a capable livestream participant.

- Paper: https://aclanthology.org/2026.findings-emnlp.1437/

STAR should separate four tasks:

1. **Speaker tracking:** who is speaking, with confidence and overlap handling.
2. **Addressee inference:** whether speech is directed to Star, another viewer, or the whole group.
3. **Turn-state estimation:** continuing, yielding, interrupted, unresolved overlap, or complete.
4. **Response policy:** speak, briefly acknowledge, wait, ask for clarification, or remain silent.

A deliberate silence action is essential. If two viewers are talking to one another, Star should not treat every sentence as a prompt.

Evaluate on real multi-speaker audio with:
- explicit and implicit addressing;
- overlapping speech;
- acknowledgments and backchannels;
- self-corrections and long thinking pauses;
- a human already answering a question;
- game audio and noisy microphones;
- multilingual and different speaking-rate samples.

Track turn-taking accuracy, response appropriateness, comprehension, false interruption rate, missed direct addresses, latency and silence-preservation separately. Preserve a stateful interruption-recovery record so Star does not repeat the same sentence after a viewer cuts in.

---

## 4. Long-horizon memory and general intelligence

### MemGym

MemGym evaluates memory in long-horizon agent environments spanning tool-use dialogue, deep research, coding and computer use. Its design isolates memory from the backbone, runner, prompt and tool policy, which is important for a fair STAR memory-on/off comparison.

- Paper: https://arxiv.org/abs/2605.20833

### LongMINT

LongMINT contains 15,600 question-answer pairs over long, evolving contexts averaging 138.8K tokens and extending up to 1.8M tokens. The paper reports 27.9% average accuracy across seven evaluated systems, with particular difficulty on multi-target aggregation and facts revised by later information.

- Paper: https://arxiv.org/abs/2605.18565

### ProMemAgent

ProMemAgent studies prospective memory: retaining an intention from an earlier sensory context and recognizing when a later situation makes it relevant. Its CPMBench contains 1,000 instances across eight everyday categories.

- Paper: https://arxiv.org/abs/2610.27400

### Application to STAR

Use versioned, provenance-bearing memory records rather than unstructured summaries:

- **Semantic:** facts, concepts and source provenance.
- **Episodic:** time-bounded experiences and events.
- **Procedural:** reusable skills with preconditions and tests.
- **Causal:** action → observed consequence links.
- **Prospective:** future intentions with trigger, expiry and completion state.
- **Project:** repository, architecture, dependency and decision history.
- **Working:** short-lived active-task context.

Every fact should distinguish observation, user report, hypothesis and independently verified outcome. When a source or repository changes, preserve history but mark the old claim as historically valid and currently stale where appropriate.

Use hybrid retrieval only after a deterministic baseline: exact entity/project lookup, lexical search, semantic search, temporal search, causal-neighbour expansion, then reranking. A contextual bandit may select among retrieval policies only in shadow mode first, with a fixed exploration budget, sealed holdout, source-freshness checks and rollback. Do not allow a retrieval optimizer to grant itself new permissions.

---

## 5. Game mastery and game creation

### GameDevBench

The GameDevBench project describes 333 Godot game-development tasks across 2D graphics/animation, 3D graphics/animation, UI and gameplay logic. Its authors report that image/video feedback increased GPT-5.4 performance from 41.1% to 52.0% in the studied setup. The result supports visual feedback, but it does not predict STAR's score or Roblox performance.

- Benchmark: https://github.com/waynchi/gamedevbench

### Star Gamer

Use a closed loop where the game keeps running while STAR observes, reasons and acts:

1. Read controls and objective.
2. Establish a safe, low-risk practice task.
3. Observe state and action consequences.
4. Practice with bounded action batches.
5. Diagnose failure using state/logs and visual evidence.
6. Change one strategy at a time.
7. Retest on a new seed/map.
8. Transfer the mechanic to an unfamiliar scenario.
9. Save a procedural skill only after held-out validation.

Measure objective completion, survival, input-to-action delay, missed action windows, resource use, damage/deaths, scenario diversity and transfer—not only win rate.

### Star Creator

For Roblox, Godot and Unity, require the agent to launch the actual project, capture screenshots or short video, inspect engine logs and compare observed output with expected output. A successful compile is only one gate. Include asset correctness, rig/animation checks, collision/physics checks, UI readability, performance and regression playtests.

---

## 6. Local inference speed: benchmark the actual 8 GB deployment

The upstream llama.cpp SPEED-Bench client benchmarks a running server and reports prompt throughput, decode throughput, request latency and speculative-draft acceptance. Compare identical prompt traces, model artifacts, context/output budgets, concurrency and server slots.

- SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- llama.cpp MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

Recommended experiment order:

1. Baseline TTFT, prompt tokens/s, decode tokens/s, p95 completion latency and answer quality.
2. Stable prompt-prefix reuse and KV-cache policy.
3. Context compaction and retrieval budgets.
4. Speculative decoding with identical prompts and output budgets.
5. MoE expert-cache size / CPU share only for MoE models.
6. CPU TTS versus current TTS on the actual voice corpus.
7. Repeat with game, OBS, avatar, ASR and TTS active.
8. Retain only settings that improve the mixed workload without a quality regression.

A public Strata benchmark reports substantial speed differences against tuned llama.cpp on its own 3060/P100/5070 setups, while also showing that speculative decoding can lose when the draft head pushes experts out of limited VRAM. Those are useful hypotheses, not transferable promises for STAR's RTX 4060 8 GB.

- Strata benchmark snapshot: https://github.com/Niko1221/Strata/blob/main/bench/results/2026-10-06-llamacpp-0.6.0/README.md

Do not optimize raw tokens/s while ignoring audio underruns, game frame-time or OBS encode lag.

---

## 7. Acceptance plan

### Offline tests
- Job assignment occurs before the suspended worker's initial thread is resumed.
- Root-only fallback resumes only after assignment failure and reports the downgrade.
- `require_tree=True` kills the still-suspended process on assignment failure.
- Resume failure after successful assignment closes/terminates the job and fails closed.
- Invalid Windows API results and missing initial thread do not leave a worker running.
- Existing POSIX sync/async descendant cleanup remains green.

### Windows acceptance
Run the native Windows CI on the authorized self-hosted runner. Verify a child spawned by the worker is counted in the Job Object and disappears after termination. Also verify assignment failure and resume failure through controlled test doubles.

### Mixed-workload rehearsal
Run a private 60-minute rehearsal with game, OBS, VTube Studio, ASR, TTS, avatar animation and bounded background research. Record synchronized host telemetry. Do not broadcast publicly as part of this test.

### Promotion
A passing offline test is not a Windows acceptance result. A passing Windows process test is not a mixed-workload performance result. Keep the change in a draft PR until independent CI and the authorized Windows acceptance test pass. Production `main` remains unchanged.

## Explicit limitations

- Suspended creation prevents worker code from spawning descendants before assignment, but it does not eliminate the creator-crash window. `PROC_THREAD_ATTRIBUTE_JOB_LIST` is the stronger follow-up.
- Job Object containment does not prevent a deliberately privileged worker from using other process-launch mechanisms or external services.
- The change does not implement CPU/GPU admission control or telemetry collection.
- Benchmarks are research inputs, not STAR measurements.
- No model training, automatic memory promotion, live game control, OBS broadcast or external publication is enabled.
- No claim of human identity, consciousness, or human-equivalent behavior is made; the goal is socially fluent, expressive and transparent AI streaming.


---

## 8. VTuber ecosystem scan: useful patterns to evaluate, not copy blindly

### AITuber OnAir

AITuber OnAir is a modular TypeScript toolkit whose public repository describes separate packages for chat, voice, transcription, comment intelligence, conversation-pattern diversification, agent policies, WebSocket chat and viewer relationships. Its comment-intelligence package is especially relevant: it filters unsafe/noisy live comments, selects one comment to answer, and summarizes ignored comments instead of flooding the model with every message. Its `manneri` package detects repetitive conversation patterns, while `kizuna` offers viewer points/achievements.

- Repository: https://github.com/shinshin86/aituber-onair

STAR should evaluate these patterns against its existing stream director and multi-party floor controller before adding another parallel comment queue:

- Keep a bounded, rate-limited viewer-event buffer.
- Select one high-value comment or question per response opportunity.
- Preserve aggregate context about ignored messages without retaining unnecessary raw viewer data.
- Detect repeated topics and rotate to relevant alternatives without injecting random or fabricated facts.
- Offer opt-in, transparent viewer achievements; avoid manipulative parasocial scoring or claims of exclusive emotional bonds.
- Keep moderation/risk checks outside the language model's authority to bypass.

The repository is MIT-licensed according to its README, but bundled avatar assets and third-party media have separate terms. Review package dependencies, asset terms and license notices before reuse. A reference architecture does not imply that STAR should import the whole monorepo.

### Open-LLM-VTuber

The Open-LLM-VTuber project demonstrates a modular local-first stack with swappable LLM, ASR and TTS providers, voice interruption, visual perception, Live2D expression mapping, proactive speech and persistent conversation history. Its release notes describe an asynchronous backend, concurrent TTS segment generation with ordered playback, first-fragment prioritization, and interruption logic that stops further token generation.

- Organization: https://github.com/Open-LLM-VTuber
- Project repository: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- Releases: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/releases

Useful STAR experiments:

1. Measure first-sentence TTS separately from full-response completion; prioritize the first audible fragment only when the sentence is semantically safe to stream.
2. On interruption, cancel generation, stop queued audio, preserve the unspoken response state, and avoid replaying already-audible text.
3. Keep provider lifecycle explicit so idle models can release VRAM without reinitializing on every turn.
4. Keep ASR, VAD, endpointing, LLM, TTS and avatar animation asynchronous but coordinated by one turn/session epoch.
5. Run a no-headphones echo test: STAR must not treat her own TTS or speaker output as a new viewer utterance.

These are design references, not evidence that the same latency or quality will transfer to STAR's hardware.

### Broadcast and avatar control boundaries

VTube Studio exposes a local WebSocket API and requires the user to allow plugin API access. OBS WebSocket is included with OBS Studio 28+ and recommends password protection.

- VTube Studio API project: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket: https://github.com/obsproject/obs-websocket

STAR's host should expose a small allowlist of typed actions (expression, hotkey, scene preset, mute, stop) rather than a generic arbitrary WebSocket command. Bind control to localhost by default, authenticate OBS, keep secrets outside model context, and never allow viewer text to choose arbitrary files, processes, URLs, scenes or plugin calls.

### Integration decision

Do not add another full VTuber framework to STAR. Keep STAR's existing Python/React architecture and evaluate small, isolated ideas against its existing modules. First candidates are comment selection/summarization, conversation-diversity detection, cancellable first-chunk TTS, explicit provider lifecycle and typed avatar/OBS actions. Each candidate should be A/B tested against the existing stream director and turn-taking evaluations before promotion.
