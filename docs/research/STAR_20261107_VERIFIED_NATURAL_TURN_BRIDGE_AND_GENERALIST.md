# STAR — Natural streaming turn-taking and generalist intelligence
**Research and engineering: 2026-11-07 (America/Chicago)**

## What was actually implemented

Added opt-in, host-only star/stream_natural_turn_bridge.py with offline tests.
It composes existing StreamDirector (speech event priority and cooldowns) and
TurnTakingGate (echo-cleared owner/guest VAD and continuously verified quiet).
Previously both could return good advice individually without a single
decision point that prioritized real-time game pressure against speaking.

The new bridge has three advisory outputs: HOLD, PREPARE a bounded SpeechIntent,
or STOP_PLAYBACK. It holds new narration on stale VAD, ambiguous voice,
ongoing audio, critical gameplay, unhealthy output, unapproved sessions, and
pending physical audio stop. Only confirmed owner-sourced VAD can request a
barge-in; incidental noise and guest voice cannot impersonate that authority.
An owner/danger event or observed new voice before speech invalidates a pending
speech ticket. STOP_PLAYBACK is latched across session disable/re-enable and
requires a unique stop token plus both trusted host attestations: queued PCM
physically drained and avatar neutralized. Duplicate/stale acknowledgments do
not clear a newer stop. A PREPARE ticket never authorizes sound, streaming,
game input, model launch, account action, or deployment.

The trusted host must authenticate the owner source of VAD, continuously
observe actual PCM device state, moderate event sources, call the bridge on
one monotonic clock, and verify the stop and playout acknowledgments. Audio
and animation are not physically controlled by this code; local standalone
tests cannot prove that Windows audio stops on time. This is a code-level
integration boundary, NOT a deployed natural VTuber.

## Research: why speech timing matters more than verbosity

**Proact-VL**, ICML 2026 (July 6–11), studies three game streaming conditions:
solo commentary, co-commentary, and user guidance. An AI companion must
choose WHEN to respond and HOW MUCH to say, not merely produce clever text:
https://proceedings.mlr.press/v306/yan26c.html

**DyaPlex**, NVIDIA Research, June 2026, studies streaming full-duplex
speech+motion, using time-aligned speech features for synchronized gestures:
https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

Star implementation priorities: source-verified gameplay commentary; never
invent viewers, wins, or emotional experiences; owner and game urgency outrank
optional chatter; preserve comfortable silences; couple expression onset to
measured consumed audio; cut off TTS, PCM AND rig on owner mute; run private
recorded sessions and obtain independent human naturalness reviews. Stable
AI personality, humor, and lore are possible without pretending Star is human.

## Research: speech and inference speed on an 8 GiB VRAM PC

Kyutai Pocket TTS October 20, 2026 v4 introduces 18.2M/6.9M/1.9M-parameter
English CPU alternatives, and a standalone Rust inference runtime:
https://github.com/kyutai-labs/pocket-tts
https://github.com/kyutai-labs/pocket-tts/releases

These are promising as Star plays on a VRAM-limited GPU, but 25x realtime
claims from other systems are NOT benchmarks on Star's own CPU. Compare warm
and cold speech latency, first PCM, actual device-consumed first audible
sample, word intelligibility, emotion/voice quality, memory footprint, and
CPU contention. Preserve explicitly consensual voices and private audio.

llama.cpp documents n-gram, draft-model, and EAGLE-3 speculation:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
SPEED-Bench can compare throughput, draft acceptance, and response latency:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Experiment on Star hardware: matched randomized AB/BA runs of model routing,
prompt caching, n-gram speculation, and CPU Pocket TTS, holding prompt,
context, game load and GPU headroom equal. Measure first speakable model text,
then first device-consumed PCM, then avatar timing and OBS frame-p99. A faster
token count cannot justify worse gameplay, dropped words, ungrounded answers
or even a fraction of a second of audible silence. Existing paired evidence
gate should remain advisory. This PR claims NO measured neural speedup.

## Research: games require a reactive/strategic/learning hierarchy

Gym-Anything-RT, published October 27, 2026:
https://arxiv.org/abs/2610.37567
Realtime-Bench, October 15, 2026:
https://arxiv.org/abs/2610.22155

These benchmarks show that systems that reason well while a game pauses
may fail badly when the world advances during inference. Star should split
a bounded fast action lane, a slower strategic lane, and offline verified
skill practice. Reward independently observed progress *before the game
deadline*, not just longer thoughts. Retain scene/frame identity through
host focus, action acknowledgment, key-up, collision, outcome and OBS
evidence. Never let old screenshots or chat grant game controls.

Run a curriculum on unseen levels/seeds and game revisions. After each
episode, compare explicit mechanical hypotheses against the host-observed
outcome. Keep withheld solutions outside the model's memory and skill bank.
Promote lessons only when held-out pass rate, efficiency and error rate
improve over matched baselines. Causal, signed task evidence matters more
than model self-evaluation or fabricated victories.

## Research: autonomous creation + general knowledge transfer

Roblox's April 15, 2026 agentic Studio initiative emphasizes testing against
the plan with logs and simulated player action:
https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

The **November 4, 2026 Studio MCP Open Cloud** announcement added game-scoped,
permission-controlled API capabilities including asset importing, analytics,
game settings, developer products and passes:
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
https://create.roblox.com/docs/studio/mcp-open-cloud

High-value pilot: disposable Roblox test universe -> inspect source and data
model -> create verified goal -> propose 4–8 candidate patches -> Luau lint
and type/API checks -> test one winner in private Studio Lab -> measure
geometry, rendering, movement and executable acceptance criteria -> preserve
only validated lessons in Star's rollback-capable local store. The same
approach applies to Rust, Python, Blender, UI, animation, physics, research
and documentation. Never test production player-data writes. Live game
publishing, commerce, external messaging and spending require correct owner
permissions, with new capabilities OFF by default.

Build consent-aware autobiographical memory: timestamped, source-linked
experience, explicit confidence and expiration; fictional lore separate
from actual experiences; no unconsented viewer-chat retention. Measure
knowledge calibration on unrelated held-out tasks. Humanlike presentation
does not imply human consciousness or warrant deceptive claims.

## Priority acceptance experiment

Record a private, nonbroadcast, owner-reviewed mock episode that includes a
new minigame, a fast hazard, chat spam, guest incidental noise, genuine owner
barge-in, deliberate GPU stress and abrupt audio/OBS stop. Collect trusted
first-audible PCM timing, failure to stop latency, avatar mouth movement,
OBS drops, frame p99, game-clock action deadlines and game score. Require
zero unconfirmed audio stops; no fabricated game success; robust hold on
ambiguous inputs; stable resource usage. Evaluate against the previous
implementation, including adverse-case regression tests. Keep OBS private
and streaming disabled throughout.

## Boundaries

Only a new advisory bridge, offline tests and research documentation shipped.
No GPU inference, real game, Windows PCM, VTube Studio or OBS was operated by
this code. Windows stop latency, viewer experience and cross-domain model
intelligence remain unmeasured. The GitHub draft must not be merged before
independent CI and an approved private rehearsal. No auto-merge or automatic
live speech can be authorized by this module.
