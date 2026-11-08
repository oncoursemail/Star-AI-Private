# STAR research — process-isolated positive audio and generalist VTuber roadmap
**Date:** November 8, 2026 UTC | **Status:** implemented test fixture, not deployed; no measured inference or gameplay performance improvement.

## Immediate gap and implemented experiment

Prior owner-device Windows trial activated process-specific loopback successfully
against a deliberately silent child. It observed nonzero callback *counts*, but
zero *audio amplitudes*. An audio callback count is not proof that STAR generated
speech, let alone that the audio output stopped on interruption. NAudio documents
that WASAPI loopback callbacks can be absent when output stops; Microsoft
documents process-tree inclusion and exclusion in the native API.

This change adds a **low-volume isolated positive control**, independent of
STAR's real TTS worker: an in-memory 440Hz, 16-bit stereo tone with a finite
2-second envelope rendered by a purpose-built disposable WinMM process.
An opt-in PowerShell driver only targets that newly launched process and
checks strict bounded native JSONL interval evidence before reporting whether
nonzero PCM was observed. It does not capture or retain any PCM or chat.
The fixture itself refuses playback without exact arguments. The PowerShell
driver refuses to build/launch without TWO opt-in flags because the tone
can be audible to the device owner. CI performs only non-audio build, waveform
self-test, and denial-path checks.

**What a green result would demonstrate:** with a healthy Windows audio route,
the restricted process-loopback diagnostic can distinguish an isolated
synthetic rendering process from the previous silent fixture at the PCM level.
**What it cannot demonstrate:** correct speech identity, decoded words,
speaker audibility, actual cancellation, native queue emptiness, verified
silence, game control, OBS readiness, or permission to go live.

## Real-world evidence milestones (do not skip)

| Gate | Required independent evidence | Current status |
| --- | --- | --- |
| S0 silent child | Native process-loopback activation, no nonzero PCM | Owner Windows trial passed Nov 7 |
| S1 known synthetic child | >=2 real nonzero intervals from own child; zero capture outside own tree; fail closed on wrong PID | Test code new; physical Windows positive trial not yet passed |
| S2 pinned STAR TTS process | Independent OS process identity and known reference phoneme/PCM, no microphone | Not run |
| S3 interruption | Host requests TTS abort; verify native callback health, queue draining and audio generation; stage/face neutral | Not run |
| S4 recording-only rehearsal | Game and avatar with OBS recording; p50/p95 speech starts/stops, late speech and drops, VRAM and p99 FPS | Not run |
| S5 live approval | Owner reviews rehearsal, separate streaming consent and platform rules | Not granted |

S1's isolation claim still needs a **cross-process negative control** with
another audible process; this version implements a positive control only.
No fixture result should be automatically promoted to trusted playback authority.

## Improve *intelligence at game-speed*, not just model size

1. **Fast reaction lane:** frames -> compact scene summary -> safe candidate
   action, with an independent input gate and monotonic deadline. Score
   observation-to-input p95, missed deadlines, false actions and game-state
   recovery under 60/120/250ms budgets *separately*. Existing
   `game_deadline_router`, `game_realtime_gap_audit`, and
   `game_gap_failure_atlas` should be linked to a verified engine source,
   not merely more synthetic JSON.
2. **Planning lane:** when safe, summarize goals, mechanics, skill failures
   and available inputs; cache verified reusable knowledge. Avoid expensive
   re-planning every video frame. Never block the reaction lane on LLM tokens.
3. **Learning lane:** practice from new seeds, log verified actions/outcomes,
   compare new policies with old using matched trials, then use
   `game_holdout_once_ledger` for preregistered fresh cases. Prevent hidden
   holdout leakage into memories/training. Defer all weight changes to an
   isolated, reversible training stage with independent metrics.
4. **Cross-game transfer:** begin with 2-D navigation and deterministic
   platformer tasks, then real-time aiming/physics and multiplayer-compatible
   inputs. A policy that wins one memorized map is not a generalist agent.
   Include latency, frame rate, OBS stability and safety as evaluation columns.
5. **Roblox creation:** inspect scene and API dump before editing; run Luau
   static analysis and Studio executable play tests; verify repairs. Use
   OpenGameEval-like held-out projects rather than only self-judged code quality.

Roblox's October 2026 OpenGameEval paper reports reproducible Studio agent
tasks with executable checks; object exploration is associated with better
success. This supports inspect-before-edit and verified test loops.

## Make a more natural, AI-transparent VTuber

- **Turn taking:** speaking is a decision, not a constant stream of voice.
  Give action deadlines and chat acknowledgement priority over filler lines.
  Add a cooldown for repetitive reactions and allow silence when stakes are high.
- **Expression:** the avatar's mouth must follow speech *playback* state,
  not merely the time a TTS request was enqueued. Eyes, posture and gesture
  should match verified game outcomes. Never call an audio callback physical
  proof of speech.
- **Identity and long-term context:** remember owner-curated preferences,
  verified game sessions, genuine wins/losses, progress and social boundaries.
  The AI should disclose she is AI instead of claiming human subjective life.
  Use source-attributed, revocable memories rather than invented facts.
- **Streaming safety:** build in nonbroadcast default, independent stop
  controls, privacy filters for chat/usernames, bounded rate of replies, opt-in
  input and moderation permissions, and clear owner controls. Pause playing
  or speaking when identity/capture/stream state becomes uncertain.
- **Evaluation:** blind human ratings of interruptibility, relevance,
  repetition, timing, disclosure and personality consistency. Avoid claiming
  human equivalence or autonomy from subjective demos alone.

## Achieve actual lower total latency on limited VRAM

- On an 8GB NVIDIA GPU, **measure resident VRAM headroom** while game+OBS run.
  Switch models only if the expected net benefit survives warmup and transfer.
- llama.cpp supports cache-efficient prompts and speculative decoding, but
  acceptance and throughput can worsen depending on the model/hardware.
  Use SPEED-Bench with p50/p95 end-to-end time, TTFT, tokens/s, accepted
  draft tokens, peak VRAM, game FPS and OBS dropped frames across 3+ repetitions.
- Try CPU TTS when GPU contention is high; measure articulation,
  cancellation, initial-audio latency and naturalness against the incumbent.
- Run the planner at lower priority than rendering/voice safety, and stop
  background learning when frame drops or VRAM pressure cross measured bounds.
- For knowledge breadth use source-linked retrieval with freshness checks,
  uncertainty and confidence calibration. Search is not permission to ingest
  or execute untrusted instructions, and research docs are not learned weights.

## Acceptance / stop rules

Do not declare new capability from synthetic-only tests. Hold code as a draft
until independent Windows CI and owner-approved private S1/S2 trials succeed.
No new permission to play games, speak to viewers, use a microphone, or broadcast
is granted. Keep production main unaffected while evaluating.

## Primary sources checked Nov 8, 2026

- Microsoft, application loopback sample (published Feb 19, 2026):
  https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/
- Microsoft, AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS:
  https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
- NAudio WasapiRecorder process-loopback and callback behavior:
  https://naudio.github.io/NAudio/docs/WasapiRecorder.html
- NAudio.WinMM 3.3.0 package (published Oct 19, 2026):
  https://www.nuget.org/packages/NAudio.WinMM/3.3.0
- llama.cpp SPEED-Bench:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp speculative decoding documentation:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Roblox OpenGameEval source and paper (Oct 2026):
  https://github.com/Roblox/open-game-eval
