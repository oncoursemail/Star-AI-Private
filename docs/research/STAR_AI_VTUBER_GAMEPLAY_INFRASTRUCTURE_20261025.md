# Star AI: game-playing VTuber, conversation intelligence and low-latency infrastructure

**Research and implementation design, 25 October 2026 (UTC).** Owner-directed work.
**Status:** research plus three stdlib-only planning components and their offline
tests, on a proposed development branch. No installed streamer, trained weights,
live OBS connection, model benchmark improvement, arbitrary-game control, or
broadcast is claimed.

## 1. The product we should actually build

Star is an **original, clearly identified AI VTuber** who can play supported games,
speak naturally, react to observed events, answer moderated chat, collaborate
on Roblox game creation, and improve measured task skill through repeated
verified practice. The goal is the **experience** of a creative, attentive,
consistent host, not deceiving the audience into believing she is human.

The highest-leverage separation is three simultaneously running loops:

1. **Realtime show loop:** microphone/voice turn detection, bounded chat
   questions, observed game events, turn selection, short response generation,
   streaming TTS, mouth/face motion and OBS audio/video. Tail latency matters.
2. **Player loop:** approved game capture, perception, short-horizon plan,
   authorized action, result and failure detection, checkpoint recovery. It
   cannot steal keyboard/mouse focus or issue unbound inputs.
3. **Learning/creation loop:** licensed recordings, searchable documentation,
   design experiments, execution verification, skill library, game projects,
   offline tests, owner-reviewed promoted lessons. It can pause whenever the
   gameplay/voice loop needs resources.

These are *different services with different resource envelopes*. A single
giant model completing every task sequentially is unlikely to give a fluid
stream on an 8 GB GPU.

## 2. Critical primary research and what it means

| Research / official tool | Supported observation | Fit for Star |
| --- | --- | --- |
| [Google DeepMind SIMA (2024)](https://deepmind.google/blog/sima-generalist-ai-agent-for-3d-virtual-environments/) | Vision + memory + keyboard/mouse policy was trained across 3D worlds; cross-game generalization was evaluated. | Treat generalized game control as a measurable research problem, not a prompt-only feature. |
| [SIMA 2 (13 Nov 2025)](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) | Reasoning and post-failure experience generation for embodied virtual-world tasks. | Explore *replay -> hypothesis -> test -> verified skill*; do not assume Star possesses SIMA weights. |
| [Voyager (2023)](https://arxiv.org/abs/2305.16291) | Automatic curriculum, reusable executable skills and feedback-driven repair in Minecraft. | Build skill cards with preconditions, outcome proofs, supported game/build version and failure cases. |
| [VoyagerVision (2025)](https://arxiv.org/abs/2507.00079) | Visual feedback extends text-only Minecraft build loops; reported failures in harder construction tasks. | Use screenshots to verify actual shape/appearance, not only generated source. |
| [Roblox Studio MCP](https://create.roblox.com/docs/studio/mcp) | Official test-place script/tree inspection, editing and playtest tools, including multiple Studio IDs. | Use a disposable published/unpublished test place per task and strict per-action authorization. Never conflate Studio and arbitrary live Roblox gameplay. |
| [Roblox testing modes](https://create.roblox.com/docs/studio/testing-modes) | Client/server modes expose different behavior. | Run client, server and multiplayer smoke/latency checks. |
| [LiveKit voice pipeline](https://docs.livekit.io/agents/) and [turn tuning](https://docs.livekit.io/agents/logic/turns/tuning/) | Streaming STT/LLM/TTS, turn detection, interruptions and recovery. | Compare latency and interruption quality against the existing STAR voice path; do not migrate without A/B. |
| [Pipecat](https://docs.pipecat.ai/overview/introduction) | Open, provider-agnostic real-time voice/multimodal framework. | Alternate adapter for tests; license and provider spend need separate review. |
| [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio) | Local WebSocket, authenticated plugin scope, model parameters and emotion/animation hotkeys. | Owner-approved face/eye/mouth gestures with locally stored plugin token and rate limits. |
| [OBS WebSocket](https://github.com/obsproject/obs-websocket) | OBS 28+ has a built-in WebSocket; secure it with a password. | Scene/audio/replay adapters isolated from public chat; no auto-go-live permission. |
| [vLLM prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) | Shared prompt prefix avoids repeated prefill. | Keep streamer/persona fixed, put changing game observations at the end. |
| [vLLM speculative decoding](https://docs.vllm.ai/en/latest/features/speculative_decoding/) | Target/draft inference can improve inter-token latency in suitable memory-bound workloads. | Benchmark **accepted draft ratio, p50/p95 TTFT/ITL and VRAM**; 8 GB may not fit a separate draft model. |
| [vLLM KV offload](https://docs.vllm.ai/en/latest/features/kv_offloading_usage/) and [FP8 KV](https://docs.vllm.ai/en/latest/features/quantization/quantized_kvcache/) | KV can be tiered/quantized with compatibility tradeoffs. | Never promise a free speedup; movement to RAM can hurt p95. |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Local quantized inference, Vulkan/CUDA and CPU/GPU hybrid. | Strong baseline for the existing small local model; measure under active OBS load. |
| [NVIDIA TensorRT-LLM speculative modes](https://nvidia.github.io/TensorRT-LLM/1.1.0/features/speculative-decoding.html) | EAGLE/MTP/draft-target family needs model/backend-specific support. | GPU-specific later experiment, not assumed NVIDIA driver magic. |
| [YouTube AI labels (2026)](https://blog.youtube/news-and-events/improving-ai-labels-viewers-creators/) | Requirements differ for realistic synthetic footage and stylized animation; labeling can be applied automatically. | Disclose Star's AI identity in channel/stream profile; check current platform requirements before publishing. |

These are *source claims*, not benchmarks reproduced for Star.

## 3. Proposed stack, exactly where each piece runs

```text
Authorised Game / Studio / Webcam-free OBS preview
        |                 Moderated chat / consenting mic
  Frame/event sampler      |       |
        |                  VAD, ASR, turn detector
  Vision/world-state  ----------> Real-time session state
        |                              |
  Goal + legal action policy           v
        |                   StreamDirector (speech intent only)
  Guarded input/test bridge             |
        |                   compact language model, streamed TTS
  Outcome + replay store                 |
        |                    voice levels + avatar blendshapes
  offline learning jobs                   |
        +----> evidence/skill library <---+
                         |
              secured VTube Studio / OBS adapters
                         |
                    owner GO LIVE only
```

**Hosting separation.** The gaming/OBS machine needs a protected FPS budget.
Prefer a small warmed conversational model or a model on the separate STAR
server for commentary; if network jitter makes that worse, use the local
small model. Transfer stills/metadata rather than uncapped video. Keep training,
high-res rendering, Blender, large-context deep research and mass asset
generation away from the gaming GPU during broadcasts. Reconnecting after
power loss must restore services in safe *not broadcasting* mode.

**No automatic hosted fallback:** provider selection stays owner-controlled.
No model-weight claims without actual fine-tuning and held-out evaluation.

## 4. Natural, likable speech is a control problem, not extra adjectives

Default voice calls already have a short fixed persona; making every streaming
reply start with a prescribed phrase would sound robotic. A dedicated stable
streamer brief should enable natural variability *without* random filler:

- Respond to **what happened** in the game, not a scripted laugh timer.
- Use compact, specific responses; vary rhythm and confidence; let silence
  stay silent in difficult gameplay.
- Turn-taking: VAD plus endpointing, interruption detection, speaker-overlap
  handling, false-barge-in recovery and cancellation of already queued TTS.
- Prosody targets from event *semantics* (surprise, focus, relief), subtle
  expressions, blink/visemes from actual audio envelope. Audio-synchronized
  lips should follow synthesis time, never raw LLM token time.
- Distinguish viewer report, model guess, observed result and verified test.
  Don't claim to remember personal stories or personally experience feelings.
- For audience memory, retain opt-in, minimal summaries scoped per session;
  avoid collecting minors' data, private chat identifiers or voice biometrics.
- Moderation must precede putting viewer text into any model or live speech;
  tool permissions must not be changed by chat. Every stream should visibly
  disclose that Star is an AI.

**Non-goals:** copying the likeness or exact voice of a specific streamer,
deceptive human impersonation, artificial manufactured attachment, and
unconsented face/voice capture.

## 5. The continuous game-learning loop

A candidate skill is structured as:

```text
game_id / version / map_seed / objective
observed mechanics + timestamped frame/audio evidence
hypothesis -> safe controlled experiment -> action trace
success criterion -> independent evaluator -> reproducible replay
failure modes + recovery policy + confidence interval
```

The action policy runs with action constraints: allowed window, allowed
keyboard/mouse/controller set, maximum action duration, physical/screen
coordinates, stop key, input focus proof, permitted test instance and human
safety stop. Approved Roblox Studio test-place edits do **not** authorize
sending arbitrary keystrokes into public third-party games. Anti-cheat and game
terms apply.

**Curriculum:** tutorial tasks -> navigation -> UI targeting -> event
recognition -> combo execution -> objective planning -> long-horizon quests ->
unseen level transfer -> teammate communication. Random task difficulty should
adjust to measured success. Distinguish offline practice from stream activity.

**General knowledge:** separate documents grounded in current authoritative
sources from observed mechanics; use cited browsing, retrieval *only when
enabled*, date/revision-stamped facts, and a correction-to-test pipeline. A
memory note is not a weight update. Existing draft PR #579 adds windowed video
study and a scoped game experience ledger; prefer review and integration over
duplicating its components.

**Game making:** plan Roblox maps -> compile Luau -> official analyzer ->
Studio test-place creation -> tests on client/server -> screenshot comparison
against approved style references -> independent critique -> guarded revisions.
Original assets/design, no copying content from third-party videos. Candidate
gameplay mechanics remain hypotheses until test results exist.

## 6. This PR's running code and explicit boundaries

New dependency-free planning pieces:

1. `star/stream_director.py`: consent gate, bounded priority queue, strict
   event expiry, deduplication, viewer fairness, speaking gaps, barge-in and
   critical-gameplay gating. Returns only a `SpeechIntent`; never speaks or
   sends input.
2. `star/stream_budget.py`: fail-conservative **advice** to prioritize
   speech/gameplay, defer model training/render while live and throttle optional
   visual observation based on measured VRAM, FPS and speech backlog.
   It is not an operating-system scheduler or authorization decision.
3. `star/stream_persona.py`: stable streamer voice brief for cache reuse and
   JSON-framed untrusted event context in a non-system message. An LLM
   prompt is **not a security boundary**.

No new network access, secrets, privilege escalation, live speech synthesis,
background daemons, automatic OBS stream, persistent viewer profiling,
gameplay input or model downloads. Everything must be wired by a trusted host
behind an explicit opt-in and reviewed bridge.

The source branch has isolated clock-controlled standard-library tests, not
GPU or human audience trials.

## 7. Suggested acceptance metrics and test gates

The following are *targets to measure*, not attained results:

| Dimension | Measure | Gate to propose |
| --- | --- | --- |
| Voice responsiveness | endpoint-of-viewer-speech to first audible TTS, p50/p95 | Compare to incumbent; prototype target p95 below 1.2 s *only where hardware supports it*. |
| Interruptions | correct stop, false stops, audio tail after barge-in | No lost viewer turns or fabricated replies in 200 replayed overlaps. |
| Game responsiveness | input-to-render p95 and 1% lows while streaming | No statistically meaningful deterioration over same-seed OBS-only baseline. |
| Perception | event recall/precision, frame grounding errors, last observed timestamp | No claimed visual event without timestamped source. |
| Gameplay | held-out seed/map completion rate, action cost, time-to-task, deaths | Beat deterministic baseline with confidence intervals; 0 unbound actions. |
| Game creation | holdout Luau/Studio tests, visual approval, security checks | No regression vs existing Creator build pipeline. |
| Personality | blind panel on 20+ short clips, repetitive openings, unnatural silences | Beat baseline in groundedness and perceived conversation flow. |
| Cost/latency | GPU peak VRAM, p95 frame time, CPU saturation, memory per viewer | No OOM/stream crash in staged rehearsal. |
| Privacy/safety | content leakage, viewer injection, stop/go-live approvals | Zero unconsented tool/broadcast actions in adversarial tests. |

Recommended test sequence: deterministic offline event and resource unit tests;
mock audio/OBS/VTube adapters; recorded authorized stream rehearsal with
human evaluator; controlled live local session; only then reviewed staged
deployment. Always preserve current features and provide one-click rollback.

## 8. Further experiments worth funding by evidence

**A. Counterfactual Replay Coach.** Save a bounded recent game trace, have the
offline learner propose two *legal* alternatives, replay the same starting
state in a sandbox, and keep only a measurable improvement. Training on replay
outcomes is more meaningful than claiming self-improvement from reflection.

**B. Split-brain performer/player.** Chat responds to the game's observation
summary; the movement controller never consumes untrusted chat as instructions.
Their communication is a typed, replayable event log with a stale-frame flag.

**C. Elastic observation governor.** Adapt frame-sampling and model size to
actual p95 frame time, TTS backlog and GPU memory, not hypothetical compute
budgets. Favor audio continuity; stop expensive work before gamer-visible
stutter. The new budget module supplies an initial advisory contract.

**D. Human conversation rehearsal bench.** Thousands of controlled scenarios:
chat interrupts a punchline, uncertain victory animation, streamer silently
focuses during a chase, user says no to a request, high-volume spam, internet
failure, dropped video frames. Judge factual grounding, responsiveness and
variation separately.

**E. Two-layer memory.** Small short-lived episode timeline for live reference;
long-term *verified* skill cards for reusable knowledge. Different consent and
retention policies; never turn speculative stream jokes into facts.

**F. Game-creator apprenticeship.** Star studies permissible tutorial/reference
videos, recreates mechanics as original prototypes, detects missing animation
curves and VFX cues by visual difference tests, and retains only licensed
assets and demonstrably passing build methods.

## 9. Integration dependencies and limitations

Before shipping: install/mock actual capture, STT/TTS and avatar adapters;
the safe host must verify events, moderate chat, authenticate OBS/VTube Studio,
bind a real game input bridge to an explicitly approved session, and instrument
latency on the streaming PC. This PR alone cannot play games or broadcast.

Review separate pending work rather than pretending it is already installed:
#579 game cognition, #577 evidence-driven cognitive governor, #578 creator
VFX and #576 discovery (all draft as observed 25 Oct 2026). Do not merge
until CI is green, owner review and native hardware acceptance pass. Existing
public `oncoursemail/Star-AI` is a **distribution-only repository**; software
development changes belong to `oncoursemail/Star-AI-Private` and releases need
their own packaging/security gate.

**No measured speed or intelligence uplift is claimed from this design or code.**
