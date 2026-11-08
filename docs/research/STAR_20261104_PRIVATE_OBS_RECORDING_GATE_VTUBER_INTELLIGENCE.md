# STAR AI — private OBS recording verification, gaming VTuber and intelligence research
**Research / implementation:** 2026-11-04 · branch `feat/star-obs-private-recording-20261104-auto69`

## 1. What changed (implemented, not merely proposed)

Prior to this patch, `stream_obs_local_readonly_probe.py` and the parser below it could verify that OBS was **not live and not recording**. That was useful as a safety preflight but blocked the next acceptance test: an already-running *private recording* with real game and avatar rendering.

Two independently selected read-only modes now exist:

| Mode | Input | Required OBS stream | Required OBS recording | What the result proves |
| --- | --- | --- | --- | --- |
| Default idle/safety preflight | `--observe` | `outputActive=false` | `outputActive=false` | OBS did not report active outputs *at sampled instants*. |
| Explicit private-recording observation | `--observe --verify-private-recording` | `outputActive=false` | `outputActive=true`, `outputPaused=false` | OBS reported an active, unpaused recording and inactive stream *at sampled instants*. |

The OBS WebSocket v5 host uses only `GetStats`, `GetStreamStatus`, and `GetRecordStatus`. A password-protected, local-only read connection and exact per-request response identity are still required. The new mode is opt-in and never calls `StartRecord`, `StartStream`, `StopRecord`, `StopStream`, `SetCurrentProgramScene`, or any other write endpoint.

The `LocalObsProbeReport.recording_verified` field is now populated from validated, explicit private-recording evidence instead of being perpetually false. Evidence parser `report()` also includes `private_recording_verified_only_at_sample_times`. Default mode retains its prior semantics. Unexpected, omitted, boolean-like numeric and paused status fail closed.

This is **not** a complete end-to-end rehearsal, a proof that audio/AV was actually written, or a license to broadcast. Sampling cannot establish what happens between reads; session-level verification also needs final file existence, nonzero media duration, decode validation, PCM/voice witness, avatar motion, real game controls, game FPS, OBS render/encoder drop counters, and recorded playback review.

### How to conduct a *local-only* private check

1. On the Windows gaming host, prepare an OBS scene with a game, avatar and microphone/audio routing. Do **not** go live. Set an OBS WebSocket v5 password in OBS; keep it out of prompts, logs and command histories.
2. The authorized host starts its own **local** recording using OBS UI. The probe intentionally cannot start it.
3. Set `STAR_OBS_WEBSOCKET_PASSWORD` in that host's private environment (not in an agent-visible terminal transcript). Run:
   ```console
   python -m star.stream_obs_local_readonly_probe --observe --verify-private-recording --samples 5 --interval-ms 500
   ```
4. In separate local-only processes, record game presentation frames, actual PCM playback, avatar animation and local inference timings on the same host clock. Review a playable video file **before** accepting the result.
5. End the private recording manually. Run the *default* `--observe` mode as a separate idle-output safety check. Both statuses are observational and grant no authority to publish.

If OBS, the avatar app or real game is absent, mark the rehearsal **incomplete**, not passed. The patch was tested with fake OBS WebSocket responses; no live Windows recording was run.

## 2. Research implications for a faster, more convincing VTuber

### A. End-to-end conversational realism, not synthetic emotion claims

Microsoft Research's **Proact-VL** (ICML 2026) evaluates proactive gaming commentary/co-commentary/guidance. It emphasizes whether to speak at all, what to say and how much to say. For STAR, learn a *speech-opportunity* policy using game events, audio occupancy, viewer turns, OBS pressure and verified game state. Reward useful remarks and correct reactions; penalize hallucinated wins, talking over players, repetitive catchphrases and commentary during high concentration.

Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

IJCAI 2026's parallel game commentary work studies drafting the next utterance while the previous utterance is being played. It reports a reduction of mean inter-utterance silence **from 9.6 s to 0.3 s in its own experiments**; this is not a measurement of STAR. STAR already has `StreamParallelCommentaryPrefetch`; the next step is to tie it to **measured spare compute** from the running private OBS + game + voice load and cancel prefetch immediately when the game scene, worker epoch, speaker or source event changes.

Source: https://ijcai.org/proceedings/2026/972

LiveKit's current turn-handling documentation differentiates true barge-ins from backchannels, supports interruption and speech-history truncation to *heard* speech. A natural STAR must not persist a story about something she said if audio never played; feed back actual playout receipts to memory and avatar expressions, and restore normal response cadence after a false interruption.

Source: https://docs.livekit.io/agents/logic/turns/

**Humanlike streaming** should mean consistent relationships, hobbies and preferences, expressive personality, natural pauses, grounded empathy and actual gameplay memories—not claims that an AI is literally a person or has human consciousness. When an event is unverified, use a question or silence instead of inventing experience. Keep disclosures that STAR is an AI VTuber.

### B. Fast and believable voice, no game-rendering starvation

Kyutai released new small Pocket TTS English models on **2026-10-20** (`english_18m_2026-10`, `english_7m_2026-10`, and experimental `english_2m_2026-10` plus reflection variants). The project explicitly targets CPU-oriented synthesis. Avoid replacing production voice solely on parameter count; run intelligibility, pronunciation, naturalness, first playable sample, 95th percentile response time and CPU contention under **actual** game + OBS + avatar load.

Source: https://github.com/kyutai-labs/pocket-tts/releases

Proposed voice A/B: same 30 short utterances, 10 interruptions and 10 emotionally varied *scripted* lines in each condition, 5 cold/warm runs per item, record first PCM sample at the output device, missed/planned phoneme timing, median and p95 delay, CPU peak and OBS dropped-frame deltas. Preserve mascot personality but let prosody respond to genuine events (not made-up feelings).

VoiceChat-TTS (August 13, 2026) presents continuous, streamable, interruptible TTS driven from LLM text streams; investigate API compatibility/licensing, avoid adopting without real evaluations.

Source: https://arxiv.org/abs/2608.13831

### C. Hardware-aware intelligence throughput

llama.cpp's SPEED-Bench compares full request latency, prefill, decode and draft acceptance, and provides an A/B comparison script. Run identical prompts/models/context sizes/seeds on the 8 GB GPU under three distinct load regimes: idle, game + avatar, and game + avatar + OBS + TTS. A faster isolated decode rate is **not** evidence of a faster gaming VTuber.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Recommended controlled comparisons: (1) no prompt caching vs stable shared-prefix cache, (2) no speculation vs low-overhead n-gram/draft speculation, (3) CPU-voice vs GPU-voice, (4) one model worker vs two workers, (5) alternative context lengths (with question-answer accuracy measured). Track GPU reserved/free VRAM, game frame-time p95/p99, OBS render/encoder drops, time-to-first-PCM, p95 commentary event-to-speech, and correct decisions/s. Reject any change that improves tokens/s but causes worse overall p95 interaction delay or rendered frames.

STAR should use **fast reactive** inference for near-term game events, **tactical planning** asynchronously, and **slow reflective research and memory consolidation** offline. The reactive path needs deadlines; missed deadlines should trigger no-op/handover rather than late actions. No hardware limit can be eliminated by prompt engineering; benchmark under real pressure.

### D. Gameplay learning with an independent observer

STAR already contains `GameplaySkillBank`, `GameLearningLadder`, `PairedMechanicLab`, `GamePredictionLab` and action gates. Avoid creating a second incompatible data system. Instead connect a real, **authorized private game** through a single trusted instrumentation boundary; store versioned game/situation/action IDs, observed inputs, trajectories, timestamped outcomes and witnesses. Do not train on user chat assertions or hidden validation cases.

Training progression:
- Pick one mechanic (move/aim/dodge/timing/puzzle) and use an independently resettable situation.
- Run matched attempts with a declared skill metric and fixed budget.
- Show success rates + Wilson confidence bounds, failures, execution latency and unseen-map performance. Promote skill only after new holdout successes.
- Generate harder *practice* tasks as successes accumulate; do not reveal holdout seeds to the agent.
- Relearn when a game update invalidates prior trajectories; never carry stale control policies across game versions.
- For public multiplayer, respect server terms and anti-cheat rules: use supported APIs, authorized clients and noncompetitive/private test matches.

### E. Better game generation and code quality

Roblox announced Studio's built-in MCP server on **March 5, 2026**, including playtest automation and simulated player input. Its playtest subagent beta was announced **April 9, 2026**. Prefer the official built-in server when available to reduce version skew; run Studio only on the authorized Windows host. Use versioned change sets, project-inspection before editing, Luau parser/linter, deterministic tests, multiplayer scenarios, device simulations, screenshot comparisons and rollback.

Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767/1
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

GameDevBench (ICML 2026) emphasizes the value of **image/video feedback** for agentic game development. Its public task count has changed across versions; pin an exact benchmark revision before comparing results. STAR should evaluate code correctness, visual alignment, motion quality, animation feel, lighting, gameplay balance and crashes rather than awarding success from compile-only outputs.

Source: https://github.com/waynchi/gamedevbench

### F. General knowledge without endless context cost

Use approved retrieved documents and exact source metadata, bounded excerpts, deduplication and memory TTLs. Evaluate answer correctness and source quality on untouched challenge sets; measure total answer latency and retrieval recall, not just context size. Keep fan-out bounded by CPU/VRAM and control admission. Summarize persistent personal history with consent and human-editable explanations; distinguish fact, hypothesis, preference and uncertainty.

## 3. Concrete next acceptance gates

| Gate | Pass evidence | Incomplete or failure |
| --- | --- | --- |
| Local OBS is safe and recording | Authenticated triplets show stream inactive, record active and unpaused at several sample times | Stream active, inactive/paused recording, stale/replayed response, missing password |
| Finished private recording really contains content | Decodable local video/audio file with expected duration, motion and audio synchronization | Active-recording flag alone, missing media file, silent or frozen recording |
| Controls match gameplay | Game-state witness verifies each authorized action's outcome | Model says it won, unexplained input or reused evidence |
| Audio feels conversational | Heard PCM timing, interruptions, commentary relevance, distinct silence/cadence distribution | Generated text-only timing, spurious interruptions |
| GPU remains usable | Measured game 1% low FPS, OBS drops, p95 speech latency under sustained 20–30 minute load | A single idle VRAM snapshot, token throughput alone |
| Learning improves | Held-out unseen task performance beats a frozen baseline with stated uncertainty | Success on repeatedly seen training tasks only |

No automatic publish, public chat, purchase or broadcast action should be inferred from a passing preflight. Private rehearsal and public streaming are separate approvals. Default off remains the right deployment policy.

## 4. Verification scope

New regression cases include default off, explicit recording mode, active and unpaused enforcement, active stream hard rejection, malformed/paused fields, and read-only allowed request list. The pure-parser tests still exercise distinct request correlators and monotonic timestamps. These tests simulate the OBS protocol and are **not** live Windows game/OBS measurements.

### Immediate highest-value follow-on

Install/verify OBS and avatar runtime on the Windows gaming host, establish an authorized private recording with a small stable game and microphone/TTS, and run this new verification flag. Then capture a real playable artifact and measured workload statistics. The agent must not call the rehearsal "passed" unless the game + voice + avatar + OBS are observed together.
