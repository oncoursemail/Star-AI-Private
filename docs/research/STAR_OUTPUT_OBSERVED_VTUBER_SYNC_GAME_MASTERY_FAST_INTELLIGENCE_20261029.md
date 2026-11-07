# STAR: Output-Observed VTuber Sync, Faster Intelligence and Game Mastery

Research and implementation: **2026-10-29**. This note distinguishes new
offline-tested code from field-tested systems, external findings and proposals.
No new neural model was trained. No actual OBS/VTube Studio capture, public
broadcast, Roblox gameplay mastery or inference-speed gain is claimed.

## Implemented in this change

- star/stream_av_sync_audit.py: bounded, deterministic analysis of paired
  **audible output** and **rendered avatar** envelopes captured on one clock.
- tests/test_stream_av_sync_audit.py: adversarial synthetic traces for 0, ±80,
  ±200 ms lag, stuck mouth, missing speech changes, invalid/fabricated timing,
  missing capture attestation, numeric abuse, duplicate/unordered observations.
- Scans possible render-mouth offsets from -240 to +240 ms in 20 ms increments.
  Computes F1, voiced-mouth coverage and silent-mouth false-positive rate.
  Positive estimated lag means mouth movement follows audible speech.
- 180–8,000 synchronized samples, 6–120 seconds, 10–125 Hz sampling and
  multiple speech/quiet transitions. Missing or inadequate evidence never passes.
  A 20 ms search grid and sparse rendering can make estimates differ by a
  full frame; results are diagnostics, not certified A/V timestamps.
- Output is aggregate only: no text, chat, identities, source audio, images,
  credentials, game inputs or automated playback. Opt-in capture attestation
  is mandatory for consideration; an untrusted model cannot attest it.
- A favorable result is **eligible_for_owner_review**, never "humanlike",
  "verified live", auto-merge or permission to broadcast. The host must
  independently establish its actual OBS/mixed-output capture and review it.

Usage (trusted local host; capture actual output rather than commanded values):

    from star.stream_av_sync_audit import OutputAVSample, audit_output_av_sync

    frames = tuple(OutputAVSample(t_ms, audible_rms, rendered_mouth)
                   for t_ms, audible_rms, rendered_mouth in capture_frames)
    report = audit_output_av_sync(frames, output_capture_attested=True)

The capture host MUST sample output PCM and composited/displayed avatar mouth
on the *same monotonic clock*. Star's generated speech, VTube parameter values
or predicted motion frames are **not** output measurements. The host should
discard raw private media after extracting bounded, consented aggregates,
keep viewer and creator data out of commits, and reserve an owner-only
review/replay path before any production change.

## Why this addition matters

The existing project includes StreamStage, verified GameReactionHost,
StreamEpisode, audio playback clock, a Browser Source caption lane, a stream
quality A/B gate, and an offline frame-time/first-audible benchmark. Those
components can be logically correct while the actual OBS composited character
still looks late, silent-but-talking, or mouth-stuck. The missing acceptance
measurement is *what a viewer sees and hears*, not what Star tried to command.

VTube Studio's documented API can inject custom tracking parameters; the
host may drive the rig, but it must independently observe the rendered result.
OBS includes obs-websocket on OBS 28+; the plugin should use authenticated
local sockets and should never expose stream keys or other controls to an LLM.
LiveKit's current turn-taking documentation distinguishes VAD, semantic turn
detection, interruption handling, and preemptive generation. These mechanisms
can improve responsiveness but must be evaluated against speaking over people.

Sources:
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md
- OBS websocket: https://github.com/obsproject/obs-websocket
- LiveKit turn-taking: https://docs.livekit.io/agents/logic/turns/
- LiveKit tuning: https://docs.livekit.io/agents/logic/turns/tuning/

## Highest-value research priorities

### 1. Measured faster useful intelligence, not token-count theater

The October 29 routing incident documented in Star-AI-Private PR #793 is a
practical warning: a slow CPU fallback receiving a flood of requests can make
the service appear dead despite a strong GPU. PR #793 proposes GPU-node
admission control, a single brain fallback slot and bounded wait/503 behavior.
Its reported 20-request live comparison is useful *operational evidence*, not
a general model-intelligence score. **Do not modify that overlapping router
lane from this change**. Review the completed operator measurements, inspect
CPU/GPU queue depths and owner-approved fallbacks, then merge independently.

Prefer a two-speed architecture:
1. Live game loop: cheap perception/action, voice, VAD, playback and rig work.
   Protect game p99 frame time and audio underruns.
2. Deliberative loop: difficult code, asset generation, long web research,
   multimodal scene reconstruction, strategic planning, practice curriculum.
   Admit only when spare CPU/GPU/VRAM or another computer is available.
3. Schedule expensive cross-model best-of-N and Studio rendering when idle.
   Keep useful local tools available even when heavyweight models are delayed.

For every proposed llama.cpp quantization, KV-cache, speculative decoding,
draft model or CPU offload setting: evaluate paired **same model, same
prompt, same hardware and concurrency** task correctness, median/p95
time-to-first-useful-output, tokens/s, peak VRAM/RAM, rollback speed, game
1%-low FPS, OBS dropped frames and audible first-packet delay. Prompt caching
requires keeping static instructions and retrieved skills in stable prefixes,
and measuring cache-hit rate. Avoid inventing speedup from token throughput.

Potential low-resource TTS: Kyutai Pocket TTS provides CPU-oriented English
models, including newer 2026 small variants. Compare voice similarity
(listening study), laughter, pause boundaries, initial audible latency,
CPU thread demand and gaming frame time before selecting a replacement.
A fast but robotic voice loses the actual streaming goal.

Sources:
- llama.cpp server configuration: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts
- Star routing PR #793: https://github.com/oncoursemail/Star-AI-Private/pull/793

### 2. Learning to play *unseen* games, not memorizing familiar footage

GameWorld (2026-04-08) reports 34 games/170 verifiable tasks, and calls out
latency, sparse feedback and irreversible actions as barriers. Roblox's
OpenGameEval (2026-10-01) uses 84 curated tasks, simulated play and separate
observation/edit actions; pre-edit exploration correlates with higher pass
rates. These suggest instrumenting a complete verified loop:

OBSERVE -> estimate uncertainty -> form mechanic hypothesis -> choose one
legal bounded action -> gather actual game-state receipt -> compare prediction
vs observation -> update only the practice memory -> choose next challenge.

Capabilities to add: scene-object persistence, movement timing, projectile/
hitbox estimation, map memory, control remapping, menu and inventory reading,
death/retry planning, multiplayer team coordination, counterfactuals and
calibrated action selection. Fast game actions must not wait on a slow LLM.
Self-generated puzzles should grow in difficulty only when held-out,
independently observed success genuinely improves.

Separate three grades: "played an authorized offline test", "completed a
verified objective", and "skill generalized to held-out games." Games with
anti-cheat, ToS restrictions or other players require an allowed test scope;
do not automate unauthorized matches, evade anti-cheat or surprise other
players. Prefer local test games, explicitly permitted environments and
owner-controlled private Studio sessions.

Sources:
- GameWorld: https://arxiv.org/abs/2604.07429
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval

### 3. Make games that can be finished and enjoyed

Existing scene audit, mutation canary, regression comparison, input and
playthrough gates should be connected to an authorized Studio Lab pipeline.
A successful structural counterexample detects some bad geometry; it does
NOT certify design quality, visual composition, network replication,
animations, reliable controls or gameplay ending. Extend test progression:

spec and art brief -> structured scene plan -> dependency inspection ->
place/prop/material/layout checks -> Studio engine load -> 1–8 client
simulation -> actual player input -> spawn/goal/death/rejoin/save checks ->
video/visual QA -> human blind quality review -> immutable evidence records.

Roblox documents StudioTestService for up to eight simulated clients and
VirtualInput for input processed like real player input. Maintain explicit
ownership, read-only checks by default, and separate approval for publishing.

Sources:
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- https://create.roblox.com/docs/studio/testing-modes

### 4. Stronger cross-domain knowledge with less hallucination

Split memory into: current source-backed facts with freshness/contradiction
flags; validated skills whose tests passed; temporary planning state; and
Star's optional non-sensitive persona continuity. Keep provenance, retrieval
timestamp, license, version, and uncertainty. Put untrusted web/game chat
inside low-trust data records, never system instructions. Expire technology
and version claims on meaningful updates; do not cache outdated source
assertions forever. Use stable retrieval indexes and short targeted context
rather than flooding every prompt with all documents.

Assess breadth with fresh, blinded tasks spanning code, Blender, animation,
UI, physics, networking, game design, speech, visual perception, factual
reasoning and source-use. Measure correctness, citations, refusal calibration,
tool reliability, time/cost and ability to detect an old answer. PR #791
documents actual polyglot compile/type checking; PR #792 adds warm Java
plugin verification. Those are valuable verification lanes but do not prove
all-language comprehension. Avoid overwriting their concurrent work.

### 5. More natural, expressive, *truthful* digital personality

Star should have persistent projects, stable interests, changing opinions
when evidence changes, callback jokes, favorites, appropriate uncertainty,
non-scripted pauses, and spontaneous *real activity*, not invented memories
about being a human. The voice/persona should be identifiable as an AI;
entertainment does not require deceiving viewers.

Audio and expressive motion must use the real audio-playout clock, not time
text was generated. A strong renderer supports expressive eyes, individual
eye blinking, gaze toward game versus chat, physically plausible twin-tail
follow-through, subtle idle breathing, laughter tied to actual audible sound
and mode-specific cat/puppy motions. Avoid repeating emotes during focus.
Let chat interrupt naturally when authorized; a false owner-voice trigger
must not cancel speech. Protect reduced-motion access.

Build *evaluation*, not a vague "more human" switch: viewers (consenting
testers) independently rate naturalness, timing, warmth, repetitiveness and
trust. Combine subjective blinded listening/watching with objective
audio-to-pixel A/V sync (new module), speech-overlap, audio dropouts, GPU
frametime, unsupported game-event claims and caption invalidation. A high
sync F1 is only one necessary property, not proof of a humanlike performer.

## Reproducible acceptance plan

- Unit tests: synthetic ±200 ms lag must be detected; zero-lag, stuck-mouth
  and missing attestation must not be misclassified. Commit no raw media.
- Windows capture experiment: OBS recording with loopback/mixdown PCM and
  rendered avatar aperture measured on a single monotonic timeline. Randomize
  20+ short utterance conditions with different prosody, silences, laughter,
  interrupts and in-game frame load. Repeat candidate and baseline conditions.
- Report actual output-alignment diagnostics with uncertainty; do not
  adjust rigs during the audit. Require owner judgment for visual quality.
- Router experiment: compare first-useful-answer and game FPS under 1, 4 and
  20 competing requests. Explicitly monitor CPU fallback and dropped/503
  requests (a bounded rejection is safer than a 15-minute hang).
- Gaming experiment: sealed level seeds with real engine evaluation, at least
  five independent games, paired controls, hidden observations and learning
  curves. Never train on or narrate validation-only receipts.
- Game creation: score blind human art/UI reviews and engine-completion tests
  independently. Fix regressions before promoting code.

## Exact limitations and security

The new output alignment audit is **offline-tested on synthetic traces**.
No Windows OBS/VTube Studio capture is wired, no hardware latency was measured,
and no live stream was started or changed. The code is intentionally
standalone and does not grant media capture, model or broadcast authority.
A real capture host would be a **separate owner-approved integration** and
should test under valid recording consent and privacy boundaries.

The repository historically named "Star-AI-Private" has been reported publicly
visible; verify actual repository visibility and protect all keys, transcripts,
viewer identities, private memories, credentials and recordings before
adding any material. Star Core Forge remains the long-term canonical local
experiment/review/rollback system; GitHub is an optional publication mirror.
