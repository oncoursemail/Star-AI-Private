# STAR AI — token-to-speech fast path and whole-system intelligence research
Date: 2026-10-30. Status: experimental, off by default for automatic releases; not deployed or livestream-tested.

## Shipped in this candidate

1. The production `SentenceChunker` no longer runs a Python character-by-character sentence-boundary loop for every 1–12-character model token. Its compiled regex scans candidate punctuation, newlines, complete <think> blocks, and fenced code as protected alternatives. Existing eager first-sentence, abbreviations, decimal numbers, clause splitting and non-speech filters remain in place.
2. Plain-text chunks avoid repeated lowercasing when no reasoning tag/code fence marker is present.
3. An unfinished reasoning block or code fence can no longer accumulate a limitless hidden buffer: a 65,536-character pending-text ceiling permanently invalidates that instance of the chunker and blocks later flush/resume. The caller should discard the utterance and construct a new instance; do not replay potentially hidden text.
4. Added unit tests spanning token sizes, code/reasoning non-disclosure, and overflow fail-closed behavior. Added a deterministic, synthetic-only, baseline-vs-candidate benchmark script to repeat the measurement locally.

This only changes local chunk selection CPU overhead and hidden-buffer robustness. It does not accelerate the underlying LLM, GPU, speech synthesis, audio hardware or gameplay. New regex handling is evaluated against thousands of deterministic varied-token cases from the previous implementation. A production rollout requires a real playback/OBS A/B test.

## Performance observations and reproduction

Before code changes, on Star's Linux development machine (Python 3.12, 5 trials x 100 repetitions of each synthetic source) median milliseconds per complete stream were: gameplay/1-character token 7.6242; explanation/1-character 12.7922; protected markup/1-character 7.1302. Early candidate with the regex scanner alone: 4.1799, 5.7024, 4.9195 ms, respectively. The short candidate was also faster at 4- and 12-character tokens. These were **separately timed runs, not a blinded or controlled real-world A/B**. CPU load, cache effects and code refinements can change results.

Use:
`python scripts/bench_voice_chunker_fastpath.py path/to/base/star/voice/chunker.py star/voice/chunker.py --trials 7 --iterations 100`
The benchmark alternates baseline and candidate order with a fixed PRNG seed, checks exactly equal emitted chunks per case, and measures only synthetic text, not user messages or recordings. The important outcome is lower chunker CPU cost under many small token deltas, not neural intelligence.

## Highest-value research priorities — integration rather than feature sprawl

### A. Actual streaming latency waterfall

LiveKit's production voice-agent telemetry separates STT transcription delay, end-of-turn detection, LLM TTFT, TTS time to first byte, and end-to-end **first playback**. STAR already has first-visible and first-speakable metrics; connect actual TTS PCM readiness, device-audible acknowledgment, OBS and frame-present measurements on one monotonic host clock. Record cancelled and silent failures, not just successful turns. Evaluate p50/p95 and concurrent Roblox frame-time p99, not token throughput alone. Separate pipelines on different PCs require clock synchronization or timestamps from one observing host; never naively subtract cross-device timestamps.

Reference: https://docs.livekit.io/reference/agents/session-traces/

### B. Two-speed game intelligence

Provide a 20–60 Hz deterministic local input policy for authorized private playtesting, a slower multimodal observation-and-action policy, and an even slower planner for long objectives. LLM thoughts must not be in the per-frame loop. Each control action needs an epoch, duration, cooldown and independent state outcome. GameWorld supplies 34 games and 170 tasks with state-verifiable outcomes, a better model than trusting an LLM's self-reported win. Use held-out levels to test genuine skill transfer; track success, completion latency, interventions, resets, and illegal/invalid actions.

Reference: https://arxiv.org/abs/2604.07429

### C. Whole-game building, visual inspection, and debugging

Roblox OpenGameEval evaluates 84 actual Studio tasks via executable scene and play-session checks, and finds observing the objects relevant to an edit correlates with better task success. STAR should begin by inspecting the project scene graph; create a scoped change plan; generate alternate candidate repairs; validate script semantics (Luau analyzer, StyLua, Selene); run engine/collision/path checks; independently capture screenshots/video and final progression; reject visually broken and incomplete games. Do not equate compile success with shipped quality.

References: https://arxiv.org/abs/2610.02563 and https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

### D. Experience-grounded knowledge rather than invented memories

Use a typed experience store with {source, timestamp, object/state IDs, witnessed outcome, confidence, permissions, retention}. Memories from gameplay should link to verifiable state or short-lived local observations; facts about external software need current source retrieval, expiration and contradiction checks. EMemBench tests recall, spatial, temporal, induction and adversarial memory from actual game trajectories; this is more meaningful than filling the context window with unverifiable notes. Never put user/player identities, credentials, clips or transcripts in public source repositories.

Reference: https://aclanthology.org/2026.findings-emnlp.905/

### E. General intelligence with evidence-gated self-improvement

Use Star Core Forge, not GitHub, as the essential internal experiment and rollback loop. Each skill upgrade should have preregistered success metrics, hidden evaluation cases, task-level timing, paired baselines, independent result witnesses, and reversible feature flags. A new agent skill is not promoted solely on its own self-review. Track general knowledge correctness, calibration, coding, Blender geometry, UI taste, autonomous game completion and social conversational quality as separate dimensions; allow narrow specialists when they improve the Pareto frontier without regressions. Cache useful verified examples, never untrusted instructions.

### F. Humanlike, transparent gaming VTuber behavior

Plan scene-aware reactions with two attention lanes: gameplay focus and socially relevant viewer messages. Quiet concentration is sometimes more believable than nonstop chatter. Trigger excitement, disappointment, laughter, idle expressions, gaze shifts, blinks, posture and wavy twin-tail hair from **observed** events and acoustic cues, synchronized through a common timeline. Use an interruption-safe speech epoch; never animate old audio after cancellation. Preserve Star's personality and continuity with real experience-based story episodes; do not invent a human childhood or imply the AI is a biological person.

Kyutai Pocket TTS offers a CPU-based 100M model and October 2026 English options as small as 1.9M parameters; these are **candidates**, not automatically better voices. Test timbre, pronunciation, laughter, emotional consistency, first PCM and first audible timing alongside CPU utilization and stream FPS. Start with Star's lightweight avatar rig, not heavy neural avatar animation during gameplay.

References: https://kyutai-labs.github.io/pocket-tts/ and https://github.com/kyutai-labs/pocket-tts

### G. Local model throughput without sacrificing realtime responsiveness

llama.cpp exposes prompt and generation token counters, queue/deferred request gauges and timing in opt-in /metrics. Pair these with Star's measured memory stalls, observed GPU budget, game FPS and audio queue depth to schedule research and render work only when safe. Try cache reuse, model hot-loading and speculative decoding only against verified task-level quality/latency benchmarks; model performance from large datacenter GPUs cannot be assumed for an 8 GB RTX 4060.

Reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

## Acceptance tests before merging or deploying

- Unit tests: original chunk sequences and new security cases pass. Verify thousands of deterministic chunk-partition cases match the old implementation, except intentionally rejected >65,536-character pending streams.
- Local microbench: multiple paired, randomized-order runs, report per-token-size medians, variability and whether chunk content matches.
- Private Windows gameplay: real Studio + OBS + TTS + audio device; measure host-observed first audible p95, game frame-time p99, CPU and GPU memory, dropouts/interruptions, and perceived speech quality.
- Rollout only after independent review and safe rollback. No streaming or game account controls are activated by this change.