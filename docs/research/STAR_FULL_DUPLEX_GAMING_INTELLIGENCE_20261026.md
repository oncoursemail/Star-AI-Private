# Star AI: full-duplex gaming VTuber, intelligent gameplay, and measured acceleration

**Research snapshot:** 2026-10-26. **Implementation status:** new opt-in,
hardware-acknowledged interruption coordinator; offline tests only. This is a
research/engineering plan, not evidence that Star has human consciousness,
unlimited autonomy, professional gaming skill, or faster transformer inference.

## Research findings with primary sources

1. **Intent-aware turn-taking matters more than constant talking.** HiThink
   Turn (Chen et al., September 28, 2026, arXiv:2609.34096) separates
   interruption intent from utterance completeness. Its evaluation uses
   240-ms speech chunks, and reports lower stop latency when triggering on a
   minimally sufficient intent prefix. Star should compare a deterministic
   VAD baseline against learned intent prediction *offline*, with no live
   model-driven permission escalation.
   https://arxiv.org/abs/2609.34096
2. **Real-time duplex assistants must ignore irrelevant background voices.**
   Realtime-Venus (September 2026) explicitly evaluates whether assistants
   continue speaking through non-target audio and respond to appropriate
   interruptions. Its reported performance is for its research protocol;
   it is not a quality estimate for Star.
   https://arxiv.org/abs/2609.13814
3. **Roblox playtests must score interactive outcomes, not just source edits.**
   OpenGameEval (Oct 1, 2026) evaluated 13 models across 84 curated stateful
   Roblox tasks. The best single-attempt rate reported is 51.7%, and
   inspecting objects related to the eventual solution correlated with higher
   success. Star should inspect dependencies before editing and score a
   separate private Studio trial after every meaningful change.
   https://arxiv.org/abs/2610.02563
   https://github.com/Roblox/open-game-eval
4. **Roblox Studio now has an official built-in MCP route.** Roblox's March 5,
   2026 announcement documents playtest start/stop and simulated input. The
   official documentation describes a local stdio transport; runtime
   capabilities must be discovered, version-checked and user-authorized.
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
   https://create.roblox.com/docs/studio/mcp
5. **CPU-first TTS may preserve a gaming GPU.** Kyutai Pocket TTS's
   Oct 20, 2026 v4.0.0 release adds smaller 18M, 7M and experimental 2M
   model variants. Benchmark naturalness, timbre stability and *first heard
   audio* under game load before choosing them. Voice cloning is not needed
   to create an original Star voice and requires consent.
   https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0
   https://kyutai-labs.github.io/pocket-tts/
6. **Speculative decoding is conditional, not a free speed multiplier.**
   llama.cpp supports draft models, n-gram approaches, and other speculative
   variants. For an 8 GiB VRAM card, a draft model may harm frame times or
   memory occupancy. Use paired, same-prompt/seed hardware comparisons, and
   report acceptance rate, TTFT, decode tokens/s and 1%-low game FPS.
   https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
7. **Live chat must be treated as a source of moderated data.** Twitch EventSub
   WebSockets use at-least-once delivery; duplicated message IDs and
   reconnect/revocation handling are documented. A viewer message must never
   be treated as the local owner's authenticated microphone input.
   https://dev.twitch.tv/docs/eventsub/websocket-reference/
   https://dev.twitch.tv/docs/eventsub/handling-websocket-events
8. **VTube Studio exposes an actual plugin parameter API**, including
   authentication and InjectParameterDataRequest. Star's 14 custom Live2D
   channels still need the artist's real model mapping and tested playback
   clocking. An API-accepted motion packet is not proof of visual quality.
   https://github.com/DenchiSoft/VTubeStudio

## Implemented: owner-authenticated audible barge-in coordinator

Files:
- `star/stream_interrupt_host.py`: `StreamInterruptionHost`, which uses
  `TurnTakingGate` and an already-audible `StarStage` plan. It delegates
  *physical* sound stop, animation-queue flush and VTube neutralization to
  trusted local ports. Only a sustained, echo-cleared **host-authenticated
  owner** VAD stream requests a stop. It does not classify speakers itself.
- `star/stream_stage.py`: `interrupt_if_current(plan)` compare-and-revoke
  API. Cancels only the addressed currently audible turn, so a stale stop
  cannot revoke a newer plan on a concurrent host.
- `tests/test_stream_interrupt_host.py`: deterministic guest/owner VAD,
  stale/duplicate/reversed/future samples, device failures, slow-stop fault,
  avatar failures, manual disable, explicit recovery and race regression.

### Playback lifecycle

1. The authorized local runtime establishes Stage, TurnTakingGate, real
   sound-device adapter, VTubeLive2DBridge/VTubeLocalHost and a frame-queue
   flusher. These callback objects never appear in a model tool list.
2. A moderated `StreamSignal` becomes a `StagePlan`, and the host queues
   audio. Only a sound-device playback ACK advances Stage to *audible*.
3. The existing Live2D adapter binds a unique playback epoch; the trusted
   interruption coordinator arms only that already-audible StagePlan.
4. Owner-verified VAD samples arrive from an authorized capture source with
   echo cancellation. Guest/background voices simply hold future speech.
5. On confirmed owner barge-in: **atomic stage revoke → actual epoch-scoped
   sound stop acknowledgement → stale avatar frame flush → VTube neutral**.
   If stop acknowledgement is missing, do not claim the sentence finished
   or a neutral rig. Fault-latch, disconnect avatar override and require a
   manually checked recovery.
6. Publish only aggregate, anonymized latency/counter metrics. Never upload
   audio, owner voiceprint, chat text, viewer IDs, epochs or streaming secrets.

A Python callback cannot *prove* speakers were authenticated, audio physically
stopped, or animation packets were flushed. Those guarantees must be supplied
and independently validated by the future Windows host. A process crash can
bypass an in-process stop callback; provide a separate OS-level output-mute
watchdog before any live broadcast. Do not attach VAD owner identity to
speaker-similarity output or model text.

### Practical latency tests on Star's eventual VTuber machine

Record at least 200 legitimate user interruptions and 200 distractors
(background TV, in-game voices, chat TTS, laughter, keyboard noises). Compare
false barge-ins, missed owner requests and actual device-audible
stop latency. Initial proposed gates (not achieved measurements):
- Owner interruption: p95 **<180 ms** from locally authenticated signal
  onset to audio-device silence; no false owner stop in 200 distractors.
- Conversation: p95 request-to-first **audible** speech **<900 ms** for
  short responses; 95% of utterances end naturally without underrun.
- Animation: p95 acoustic-mouth offset **<80 ms**, no >100 ms stale frame;
  no facial expression remaining after a confirmed cancel.
- Game performance: 1%-low FPS degrades by **<3 FPS** compared with paired
  game-only baseline, using at least 20 randomized matched pairs. Do not
  use a tokens/s win to justify a worse stream.

`maximum_stop_ms` currently detects late *stop callbacks*, not the full
VAD-onset-to-silence latency. Instrument physical playback separately.

## Higher intelligence: systems that make Star reliably more capable

**Gameplay:** Split the hierarchy into a 30-120 Hz deterministic safe
controller (game-state sensor and fixed input budget), a 1-4 Hz visual
assessor, and a slower planner that proposes strategies. The fast controller
must never wait for a language model to complete a turn during hazards.
Capture physics-grounded observations and evaluate outcomes with a separate
private scorer. Reset to a fresh private episode per independently scored
practice attempt; keep hidden test levels out of training. Promote a learned
skill only after blinded transfer beats a baseline on games/levels Star did
not use for practice. Track success rate, confidence intervals, attempts,
latency, game version and regressions rather than invented "mastery".

**Game creation:** Require a discover/inspect/dependency-map step before
editing. Verify scene geometry, material tiling, part alignment, collision,
no prop intersections, UI anchor clipping, touch control accessibility,
animation rigs and sound timing in the actual engine. For each candidate
run engine tests, screenshot comparisons and human visual review of
outliers. Avoid copying proprietary games/meshes.

**General intelligence:** Make facts source-attached records with time,
scope, confidence and contradiction links. Keep source documents separate
from instructions. Allow optional retrieval only when user/project policy
permits it. Challenge-generating agents may propose increasingly difficult
tasks, but independent evaluators and unchanged hidden fixtures grade them.
Do not let a self-builder rewrite its own graders or promote success without
tests. Keep Star Core Forge local-first with auditable commits, reversions,
immutable evidence and manual promotion gates; GitHub is an optional review
and publication mirror rather than a required internal dependency.

**Faster inference:** Run pre-registered paired A/B trials of GGUF
quantizations, KV-cache layouts, prefix caches, draft-model speculation and
CPU/GPU thread placement *while the actual game + OBS + avatar + TTS run*.
Track TTFT p50/p95, decode tokens/s, audio TTFA, GPU peak, VRAM OOM count,
1%-low FPS, energy/temperature and output-quality regression on the same
held-out tasks. Small CPU-side TTS may be preferable to contesting an 8 GiB
GPU. Do not claim a physical memory breakthrough or gain without real data.

## What naturally expressive Star should actually do

- Build a consistent *character bible*: soft-round Star identity, gold
  ribbons/clip, affectionate-but-not-clingy humor, expressive eyes and motion,
  cat/puppy modes, and long-term memories derived from real verified
  adventures. Disclose AI status; personal lore is storytelling, not evidence
  of being human or conscious.
- Use grounded micro-reactions (real failures, achievements, discoveries),
  adaptive speaking frequency, comedic timing and purposeful silence when
  a difficult encounter needs concentration. Avoid reading every chat line.
- Generate speech in small breath/prosody-aware chunks. Audible-cursor
  acknowledgements control lip/face expression, and device stop interrupts
  the current chunk without ghost audio. Evaluate original voice quality
  with consenting listeners, not deceptive impersonation or fabricated
  real-world memories.
- Interpret moderated viewer chat as conversational context, never tool
  permissions. Owner commands require a separate authenticated local
  control channel; never infer an owner from a chat username.
- Keep recorded practice and streaming memory opt-in, bounded and erasable.
  Block leaked credentials, accidental account details, doxxing and unsafe
  content before speech. Measure laughter naturalness via blinded human
  preference tests plus latency; do not rely on the model praising itself.

## Prioritized independent verification

| Step | Pass condition | Current truth |
| --- | --- | --- |
| Local controller | 20+ adversarial tests and full linked regression suite pass | Offline tests only |
| Host audio | Actual epoch stop and independent mute watchdog measured | Not wired |
| VTube Studio | Original rig parameter mapping + real playback-device sync | Transport code exists; no real-rig validation |
| Roblox game learning | Real private Studio trial + independent signed outcome | Runner exists; no live match |
| Intelligence | Holdout improvements replicated against baseline | Not yet shown |
| Throughput | Positive p95 and 1%-low FPS paired A/B gains under streaming load | Not yet measured |
| Naturalness | Blinded human ratings, interruptions and expression quality | Not yet measured |

No full-self-awareness, model weight improvements, Roblox ranked multiplayer
dominance, human consciousness, or actual livestream quality is established by
adding a Python orchestration component. The strongest next work is plugging
the modules into real permitted devices, recording credible latency/quality
baselines, then improving the bottleneck supported by those measurements.

## Release and privacy gates

Keep these changes in a draft stacked PR, do not merge into `main` or
deploy. Validate full repository CI, owner review and Windows audio/rig
integration before any live operation. The repository currently named
`Star-AI-Private` is publicly visible on GitHub; never commit voiceprints,
raw chat, video, model secrets, local Forge stores or private evaluation
material. No change may silently elevate OS privileges or create a live
broadcast, transaction or publication.
