# STAR AI: Measured Gameplay-Load Drift, Faster Intelligence & Natural VTuber Research
**Research and implementation record — November 4, 2026 (UTC) / November 3 (US Central)**

## Outcome and evidence boundary

This iteration introduces `star/game_load_shift_guard.py` plus adversarial tests.
It addresses the **next missing link** after the synthetic multi-load timing lab:
a previously reasonable policy must not silently be treated as reliable after
game/OBS/voice/GPU load changes. The new audit compares *two sequential,
real-host-measured* windows and detects latency spikes, missing input
acknowledgments, game frame stalls, OBS skips, and insufficient VRAM headroom.

**What actually works today:** a dependency-light, deterministic, offline
trace validator, comparator, CLI, and tests. It reads small JSONL metrics
files; it does not start OBS, a game, a local model, or a livestream. It cannot
authenticate a host or verify that a game actually registered input. It does
**not** establish a performance gain or authorize any control. It cannot turn
previous synthetic scores into real skill evidence. The first actual Windows
game+OBS capture is **not yet complete**.

### Reproduce offline

```bash
python -m pytest -q tests/test_game_load_shift_guard.py
python -m star.game_load_shift_guard baseline.jsonl current.jsonl --now-ms 75000
```

The CLI requires an explicit monotonic `--now-ms` timestamp **from the same
host clock** used to timestamp observations. These are local, allowlisted
metrics, not game frames, chat, stream keys, or microphone recordings.
JSONL has one `GameLoadSample` per line and accepts only the dataclass
field names.

- Each window needs >=20 independent observations, the same pinned
  host/session, game scope and predeclared workload class, strictly
  increasing timestamps and reasonable sampling cadence.
- A duplicate episode ID, clock reversal, stale/current-future window,
  a large sampling gap, mixed profiles, or untrusted host assertions
  makes the result **inconclusive** rather than positive.
- One lost input acknowledgment is a failure, never silently omitted from a
  p95. p95 end-to-end latency, game p99 frame time, interval OBS
  render/output skip percentage and minimum free VRAM are checked
  conservatively.
- A stable result is called **`stable_observation`**, deliberately not
  `skill_mastered`, `model_faster` or `approved_for_stream`.
  Its authorization booleans remain false.
- The host must acquire input acknowledgment, frame/OBS metrics and game
  outcome from independently controlled instrumentation. The model,
  chat or synthetic simulator must not author its own measurements.
  The boolean `independently_measured=True` is an unverified assertion
  inside a JSON object; separate signed host evidence is still needed.

## 1. Research: actual game reaction speed rather than token rate

The 2026 GameWorld benchmark distinguishes state-verifiable outcomes from
subjective screenshot scoring and separately evaluates a real-time variant
where gameplay continues during inference. `CaptureToActionTrial` in STAR
already analyzes detailed stage timestamps. The new drift audit adds a
**temporal stability** check across adjacent real workload windows, a
different question from paired A/B latency optimization.

A proposed Windows rehearsal needs timestamped:
`capture_start → frame_ready → preprocess → inference_finish →
input_submit → host_ack → independent game_state`.
Interpret each timestamp correctly. According to Microsoft's `SendInput`
documentation, a successful return means an event was inserted into the OS
input stream; **it does not prove the target game processed it**. Capture a
separate game-state result, release any held controls on failure, and never
call `SendInput` return value "game success".

Recommended measurement strata, preregistered before changing code:

| Workload | Objective | What to protect |
|---|---|---|
| Idle AI only | Decode/prefill and cache latency | Correct answers and task success |
| Game without stream | Screenshot-to-observed game result | Frame p99, input release |
| Game + local OBS recording | Full pipeline under encoder pressure | Render/output skips, audio |
| Game + OBS + VTuber + voice + AI | Real target environment | All of the above simultaneously |
| Same load for 20+ minutes | Drift, thermal / GPU / process changes | Tail latency and liveness |

Don't compare the idle-only synthetic calibration with an unrelated
real-world window as proof of effectiveness. The new module accepts the
**same host, game and workload** in both windows; changed workload yields
inconclusive and demands a new reference window. In future, correlate the
existing game capture benchmark, OBS read-only host, and this drift detector
using a shared episode identifier and independently witnessed provenance.

**Quantitative candidate gates** (engineering defaults, not measured results):
p95 end-to-end latency must not worsen more than 25 ms relative to the
reference window; no newly lost input acknowledgments; game p99 frame
latency must not spike more than 8 ms; OBS skipped-frame percentage must
not rise more than 0.5 percentage points; minimum free VRAM stays above
1536 MiB. Adjust thresholds only by preregistered game requirements,
not after looking at candidate results. A zero-regression observation
still does not prove improved gameplay.

Relevant primary sources:
- [GameWorld state-verifiable and real-time evaluation, 2026](https://gameworld-project.github.io/)
- [Microsoft Win32 SendInput reference](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
- [OBS WebSocket GetStats protocol — render/output frame counters](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)

## 2. Research: intelligence gains under an 8 GiB GPU

Use a **three-timescale agent** instead of trying to call the largest model
for every frame: a reactive primitive skill controller with hard deadlines;
a tactical planner that can reevaluate goals after critical moments; and
an off-stream research/build/test worker that can perform expensive
multi-candidate code generation and verify results. A missed game frame
is not made better by a prettier answer 600 ms later.

Resource scheduling proposal: reserve render and input deadlines for the
game; OBS composition/encoding and local microphone/playback receive
guaranteed time slices; permit deeper language-model or VLM work only
after observed headroom is sufficient. On load regression, decrease frame
sampling or pause nonessential research before compromising game/OBS/voice.

**Benchmark and select instead of assuming model superiority.** Compare a
small local vision/reactive model, a separate high-quality Luau/coding
model, and a fallback hosted model by end-to-end task success and p95
latency, not parameter count. Measure warm/cold prompt prefill, output
tokens/s, first meaningful spoken audio, VRAM, energy, queue wait,
retries, and contextual correctness. A routing policy must allow
abstention and recall of verified tools/docs when local knowledge is
insufficient.

The current llama.cpp SPEED-Bench client measures throughput, latency,
and draft-token acceptance for speculative strategies. It **does not**
measure Roblox game success or streaming QoS. On a GPU shared with a
game, a speculative draft model can reduce capacity; compare it against
no-speculation and n-gram configurations. Validate actual Qwen-family
cache reuse on the pinned llama.cpp version: Sep 2026 reports describe
hybrid/SWA slot-restore re-prefill despite apparent successful restore.
Do not count a successful cache-save API call as demonstrated prefill
savings without instrumenting actual cached token counts.

Primary sources:
- [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md)
- [llama.cpp speculative decoding methods](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [Hybrid/recurrent slot cache restore issue, Sep 1 2026](https://github.com/ggml-org/llama.cpp/issues/28194)

## 3. Research: a more natural, openly AI VTuber

Humanlike performance should come from consistency, timing, and responsive
behavior, not claiming to possess human life experiences. STAR's existing
`stream_persona.py`, signed game-moment journal, session continuity,
voice-interruption, preplay fence, and social-turn evaluator are more
important here than adding decorative model prompts.

Implement/benchmark **three synchrony layers** in an actual private rehearsal:

1. **Conversation:** listen continuously through trusted VAD/ASR; distinguish
   a genuine floor-taking interruption from background noise or an
   acknowledgment; allow silence during demanding gameplay; handle short
   backchannels and stop playback physically when a speaker barges in.
2. **Embodied reaction:** let speech intent drive face, blinks, mouth
   shapes, slight head/ear/hair motion, and laughter timing from actual
   synthesized PCM/viseme clocks. Never claim "I dodged that" before
   the game independently confirms the event.
3. **Personal continuity:** retrieve only recent, authenticated in-game
   experiences and owner-approved preferences; note victories, mistakes,
   running jokes and goals, but separate a model's playful fiction from
   memories of actual gameplay. Avoid persisting player chat, private
   microphone audio, and sensitive viewer data.

Microsoft's May 2026 Proact-VL explores gaming companions that decide
**when** to speak; Microsoft's March 2026 RESPOND examines timely
backchannels and proactive turn-taking. Neither paper alone certifies
STAR's naturalness. Kyutai released small Pocket TTS English models in
October 2026 (18M, 7M, experimental 2M families). These are promising
CPU voice contenders when preserving GPU time for gameplay; evaluate
intonation, first-audible chunk timing, interruption latency and listener
ratings *alongside* CPU usage before switching.

Sources:
- [Proact-VL, Microsoft Research / ICML 2026](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/)
- [RESPOND, Microsoft Research, March 2026](https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/)
- [Kyutai Pocket TTS October 20–21, 2026 releases](https://github.com/kyutai-labs/pocket-tts/releases)
- [SIGGRAPH 2026 EchoAvatar research](https://robinwitch.github.io/EchoAvatar-Page/)

## 4. Research: better game building and general knowledge

Star needs not just more internal coding tokens but a stronger
**inspect → hypothesize → build alternatives → execute → judge → repair**
cycle. Roblox Studio's March 5, 2026 built-in MCP server supplies
project-inspection and playtest interfaces. StudioTestService supports
multi-client scripted tests (up to eight clients in the June 2026 launch
announcement). A finished generated level is not "good" until human-visible
design, collisions, controls, networking, framerate and actual gameplay
outcomes pass independent checks.

Use Roblox built-in tools for sandboxed Studio runs; Rojo/Luau tooling for
linting/unit checks; generate visual comparisons for animation, particles,
UI and lighting. GameDevBench (ICML 2026) shows graphics-heavy tasks are
still materially harder than plain coding tasks, making visual iteration
and video feedback important. Record counterexamples so repeated
failures become reusable private lessons, not unverifiable self-praise.

General-knowledge plan: a source-indexed retrieval lane, date-stamped
claim provenance, uncertainty estimates, deliberate contradiction
resolution, and periodic "closed-book versus retrieved" evals.
Keep web access opt-in; don't blend untrusted webpages into developer
instructions. For strong factual answers, favor citations plus brief
summaries over silently rewriting a model's permanent beliefs.

Sources:
- [Roblox Studio built-in MCP announcement, March 5 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643)
- [Roblox Studio testing APIs — StudioTestService, VirtualInput, devices, June 2026](https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854)
- [GameDevBench paper and benchmark, ICML 2026](https://sethkarten.ai/papers/gamedevbench.html)

## 5. Delivery gates and limitations

**Implemented now:** a pure, offline, explicitly bounded temporal drift
report for host-measured game/OBS workloads; tests for missing inputs,
latency tails, lost GPU headroom, skipped OBS frames, game stalls,
host/episode continuity, clock faults, stale data and malformed records.

**Not implemented in this iteration:** microphone control, voice model
installation, full Windows game input, Roblox scene capture, proof of
real-game skill, automatic game-winning policy selection, live OBS
broadcast, automatic personality learning, and self-modifying model
weights. All experimental features remain opt-in and off by default.

**Next physical validation:** owner-controlled private game, single trusted
Windows timebase, independently pinned game process, read-only authenticated
OBS session, explicit game-clock progress and input-release measurements,
PCM audible-playback timing, avatar visemes, and verified outcomes under
game+OBS+AI load. No public broadcast until this local rehearsal passes.
