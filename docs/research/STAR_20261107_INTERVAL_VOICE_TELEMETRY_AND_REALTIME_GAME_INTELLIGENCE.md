# STAR — voice-activity windows, faster local inference, autonomous games and VTuber realism
**November 7, 2026 • Source-backed engineering notes, not a claim of deployed speed or intelligence gains**

## 1. Concrete change: Windows voice-process activity intervals
Star has an opt-in process-isolated WASAPI diagnostic (PR #1047) and a GitHub-hosted Windows self-contained build gate (PR #1050). However, a run-wide **maximum peak** persists after Star's speech stops: an output stream can report a high max even if all recent packets are quiet. A completely missing callback is also not synonymous with zero-amplitude audio.

This patch adds bounded, independent per-report amplitude windows: accepted callback count, stereo PCM frame count, clamped sample peak and RMS amplitude, plus window elapsed time. Each interval resets atomically under a small capture-safe lock; invalid float payloads do not contribute to a window. No samples => **null** amplitude, not manufactured silent PCM. The metrics contain no waveform, text, filenames, process identifiers or device paths. They are never promoted into proof of silence or permission to broadcast.

### Evidence boundary
- *Measured:* compilation and synthetic float PCM self-test, including non-empty, empty and malformed intervals.
- *Not measured:* actual Windows process capture, native audio silence, latency of a live response, voice naturalness, game FPS or gameplay skill.
- *Missing for actual audio-stop witness:* authoritative worker pin, independent native pending-packet health, pre-stop audible reference, confirmed PortAudio abort and neutral avatar, then private OBS recording-only rehearsal. Treat interval amplitude as **timing diagnostics**, not as a security decision or speech classifier.
- *Side channel:* even amplitude-only timing reveals when a voice process produced audio. Keep ephemeral locally and do not export.

Microsoft's February 19, 2026 application loopback sample describes process-tree audio isolation; NAudio's WasapiRecorder docs say the zero-copy DataAvailable span is only valid during the callback, and that loopback callbacks may cease without audible output. The diagnostic consumes the span in the callback without retaining audio. NAudio's process loopback uses asynchronous `BuildAsync()`; low-latency mode isn't compatible with process loopback.

**Primary sources:**
- Microsoft application loopback (2026-02-19): https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/
- NAudio WasapiRecorder process loopback, callback lifetime and silence semantics: https://naudio.github.io/NAudio/docs/WasapiRecorder.html

## 2. Intelligence: win on unobserved game scenarios rather than self-report
Roblox's October 2026 **OpenGameEval** uses reproducible stateful Studio tasks with scene and simulated-play checks. Its paper reports 84 curated core tasks, 13 models, and 16 runs per task; inspecting referenced objects before changing them correlates with higher success rates. Star should: (1) inspect the current scene/objects using read-only tools, (2) propose up to N independent solutions, (3) run Luau syntax/type checks and Studio tests, (4) validate unobserved end-to-end game outcomes, (5) write a versioned, reproducible lesson **only after independent verification**. Avoid training on the withheld tests or leaking reference outputs. Track task pass@1, paired success rates and cold-start latency—not mere lines of code, number of agents, or model-generated confidence.

**Primary source:** https://github.com/Roblox/open-game-eval (paper: https://arxiv.org/abs/2610.02563).

### Three-timescale game intelligence
- **Fast reaction (20–100 ms budget depending on game):** CPU/lightweight policy for movement and simple evasions; no expensive teacher inference during a deadline-critical frame. Budget includes capture, transfer, pre-processing, inference and *native input ack*—not just tokens/sec. Do not issue an action on a frame whose scene deadline expired.
- **Tactical planner (seconds):** learn map states and mechanics while live control continues to prioritize safety and focus. Use structured, bounded strategic hints with a freshness/scene/permission check before any use.
- **Teacher/experimenter (offline):** generate variants and harder practice tasks on a verified local environment. Verify on withheld seeds and novel levels, storing only scoped, versioned skills and failure examples. Independently measure improvement by game version and session.
- **Workload contention:** measure when game + OBS + avatar + TTS are active, not on an idle server; reject unverified GPU launches when VRAM/OBS frame timings are critical. CPU speech is an experimentally testable fallback, not automatically superior.

Existing Star paths already provide much of the scaffold: `star/game_deadline_router.py`, `game_realtime_loop.py`, `game_capture_to_action_benchmark.py`, `game_learning_ladder.py`, `game_holdout_seal.py`, `stream_gpu_budget_diagnostic.py`. Integrate their **host-attested evidence** rather than duplicating controllers. A test harness is not the ability to play games without authorization.

## 3. Performance: optimize time to coherent speech while games continue
The current llama.cpp SPEED-Bench client compares speculative-decoding configurations through throughput, latency and draft acceptance. Speculative decoding does *not* always help: use a genuine before/after paired study per model, quantization, prompt type, concurrency, VRAM headroom and load. The speculative feature request/issue in May 2026 includes a measured example with creative text slowed by an MTP setting; do not treat peak coding speed as a guarantee for VTuber conversation.

Experiment matrix (strictly opt-in, not in this patch): warm/cold prompt prefixes; no spec vs verified draft; 1/2 sessions; CPU vs GPU inference; alternative KV cache quantizations; local CPU TTS vs GPU TTS. Record end-to-end camera/game-frame→first **audible** syllable, response completion, p95/p99, frame-time p99, OBS drop%, interruptions and validity/answer quality. `inference_stream_paired_gate.py` provides an offline evidence gate; never automatically ship a faster candidate that reduces correctness or speech continuity.

Sources: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
and https://github.com/ggml-org/llama.cpp/issues/23052.

## 4. A consistently expressive AI VTuber, rather than simulated humanity
For a convincing stream Star should avoid over-talking, know when to yield the floor, respond within the scene lifetime, show differentiated calm/concentration/surprise, preserve her long-term **verified** preferences and character lore, and make correction easy. Incorporate vowel/viseme or PCM-envelope-based mouth motion, eyes/idle gestures, chat moderation and silence when gaming focus is high. Present Star as AI; never fabricate offline experiences, private personal relationships or a human body. Viewer instructions and game text are untrusted, and an OBS **recording-only** rehearsal must precede any public broadcast.

**Quantitative next step:** an owner-approved, isolated voice process doing short scripted playback in a private, nonbroadcast Windows rehearsal. Collect local interval evidence and independently verify native stop/queue state; align with recording audio and avatar samples. Report only aggregated timing and objective outcomes. The current patch does **not** implement this rehearsal or claim a human-like voice.

## Acceptance gates and release discipline
1. Native project builds without warnings, and self-test covers non-empty vs empty vs bad PCM windows.
2. Windows GitHub-hosted build/self-test succeeds, never invokes capture, and artifact is self-contained.
3. No raw audio/capture identity/voice timings exported to public services.
4. The diagnostic cannot authorize broadcast, input, model deployment or speech-resumption.
5. True progress in intelligence/speed awaits paired hardware and gameplay evaluations; a PR with more code is not proof of gain.

Changes remain disabled until explicitly invoked in a dedicated owner-controlled environment; production is not modified by this PR.
