# STAR: speaker-epoch continuity, real-time game intelligence and VTuber engineering
Research and implementation note — 2026-11-02. Host-observation and offline-code scope only.

## This run: reproduced and corrected a real streaming infrastructure defect

The existing `RealtimeTelemetryHost.sample_speaker()` invoked a potentially blocking
local speaker backlog callback outside its session lock. If the stream session,
game context, or output epoch changed while it was in flight, it could:

1. **Drop good new-epoch audio evidence**: an old callback raised an exception
   after the new session already had a valid new speaker reading. The broad
   exception handler unconditionally cleared `_audio`, making a healthy
   stream fail its telemetry admission checks.
2. **Invent new-epoch audio readiness**: an old callback returned normally
   after the context reset and populated `_audio` in the new session. The
   new session appeared to have fresh physical speaker evidence even though
   the reading actually belonged to an obsolete device/epoch.
3. **Leave stale evidence after malformed current speaker readings**: a
   nonnumeric callback return produced False but did not invalidate the
   previous current-epoch sample.

The first two races were reproduced deterministically with
`ThreadPoolExecutor` and paired `Event` barriers. Both tests failed
against the parent code. The implementation now captures the host's
`_generation` before invoking the callback, checks that epoch under
the same lock when committing results, rejects old successful reads, and
only invalidates samples for a failed callback belonging to the *current*
epoch. A malformed current reading now invalidates the old reading rather
than preserving unsupported confidence. Audio remains private; the
telemetry path reads **pending duration only**, never microphone PCM.

**Why this matters:** Lost audio evidence can suppress speech or cause a
temporary avatar/video pipeline freeze. Cross-session evidence can make
Star's resource admission and gaming-stream controller trust data from the
wrong device, game or stream. This change addresses one proven concurrency
hazard; it does not independently prove improved audible voice quality.

## Fresh, relevant literature and technical sources

- **Realtime-Bench** (submitted **2026-10-15**): distinguish wall clock,
  paused clock and token clock. The best reported wall-clock success is 44%
  on its tasks; this is NOT a Star benchmark. Use real action deadlines,
  not just offline reasoning scores. https://arxiv.org/abs/2610.22155
- **On the Clock** (**2026-10-07**): giving agents deadlines in prompts alone
  does not reliably produce controlled timing. Add host-provided time
  budgets and execution hooks; do not imply that merely adding a clock
  increases actual task intelligence.
  https://arxiv.org/abs/2610.10833
- **The Latent Bridge** (**2026-06-23**): compares reactive and deliberative
  agents and a proposed slow-fast communication channel. Treat it as
  research, not proof that a dual-model system is better on this PC.
  https://arxiv.org/abs/2606.24470
- **llama.cpp SPEED-Bench**: reports inference throughput, latency,
  speculative draft acceptance; compare *completed, correct* answers
  under comparable concurrency and VRAM caps.
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- **VTube Studio plugin documentation**: model parameters and hotkeys can
  be controlled through a local API; this is a practical rig integration
  path, NOT permission to broadcast or capture private inputs.
  https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- **Microsoft WASAPI IAudioClock**: device playback cursor positions should
  be interpreted using the reported frequency, not TTS-generated time.
  https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock-getposition

## What Star should become (ordered engineering plan, not deployed claims)

### A. Two-timescale, deadline-aware game intelligence

- **Reactive lane:** perception of game HUD/scene and allowlisted actions,
  with explicit host monotonic deadlines. Use `game_deadline_router`,
  `game_realtime_loop`, `game_action_gate` and their identity-bound leases.
  Reject an expired or cross-frame action *even if the model's advice is good*.
- **Deliberative lane:** in private/offline practice, a stronger teacher can
  review difficult failures, compare alternative strategies and propose
  improvements to a skill recipe. Never run this costly lane in a critical
  live-play frame.
- **Learning contract:** signed practice episodes only; fresh hidden holdouts;
  paired improvement and speed evidence; minimum generalization across
  different games/maps. Do not equate more tokens with learning or game wins.
- **Control:** no fabricated human keyboard authority, no input into
  multiplayer games without the owner's scoped permission and applicable
  game rules, and mandatory key-release watchdogs.

### B. Humanlike gaming VTuber, without misrepresenting Star as human

- **Listen before reacting:** use real output-audio and microphone turn-end
  evidence to decide whether to talk. Model unsolicited speech, interruptions,
  quiet speakers, and owner barging as distinct situations. Prefer silence
  over a generic or badly timed comment.
- **Embodied performance:** sample mouth animation from *consumed* speaker PCM;
  reduce idle head/eye motion during critical gameplay; tie gestures to
  independently observed events. Respect reduced-motion mode.
- **Continuity and character:** maintain bounded, authentic session memories,
  distinct game identities, recurring catchphrases sparingly, and purposeful
  relationships/banter with Astro and Amber only when they are part of the
  approved active episode. Do not invent wins, viewers' feelings or personal
  human experiences.
- **Operational reliability:** speech lane, rig lane and OBS monitoring must
  share a consistent device/session epoch; a reset invalidates outstanding
  speaker/video captions and motion leases. Physical mute/neutralization and
  OBS safety remain responsibilities of the trusted Windows host.
- **Quality measurement:** first audible PCM p50/p95, false interruption rate,
  overlap time, verified game-reaction relevance, visual/audio sync, caption
  lag, frame p95/p99, and long-session crash/reconnect data. Independent human
  ratings complement metrics; no arbitrary "human equivalent" percentage.

### C. More capable at building games and general knowledge

- **Roblox engine:** plan -> generate multiple alternatives -> run Luau
  static checks -> private Studio/Play Solo and client/server tests ->
  scripted input -> screenshot/geometry review -> repair -> independent
  replay. A passing parser alone does not certify a fun, playable game.
- **Knowledge:** maintain separate source citations, review states, retrieval
  scopes and freshness; distinguish a documented fact from a game's current
  runtime state. `stream_knowledge` already requires specific, reviewed,
  explicitly broadcast-approved note IDs.
- **Skills:** add increasingly challenging tasks in UI, VFX, movement,
  camera, animation, audio, physics, multiplayer testing and Blender assets.
  Use quality rubrics and visually verified examples rather than a huge
  unverified pile of web snippets.

### D. Faster and more reliable on the current GPU

On the connected Windows **Main** PC, a read-only **single snapshot**
on 2026-11-02 showed RTX 3060 Ti / 8 GiB, approximately **7,414 MiB used,
611 MiB free, 22% utilization**; a llama-server process was present and
OBS/VTube Studio/Roblox processes were not found in a process-name check.
These numbers are NOT a sustained benchmark. Do not start a second large
model or infer that available bandwidth equals available VRAM.

- Compare quick-reaction model routes on CPU and GPU using **complete,
  graded replies** with p95/p99 wall-clock latency; test under *real* game
  and OBS loads, not a quiet desktop.
- Evaluate llama.cpp prompt-prefix reuse and speculative decoding one
  parameter at a time, fixing concurrency and context length; rollback
  any route that hurts game frame-time or voice turn quality.
- Admit background learning only when live/OBS headroom has been measured;
  keep a dedicated framebuffer/encoder budget. A 2x token-speed gain that
  causes OBS skips is a failure for the VTuber mission.

## Acceptance checklist before promoting or going live

1. Full GitHub offline CI on this draft's exact commit is green, and focused
   hardware-telemetry concurrency regressions pass; source tree hashes match.
2. Run a **nonbroadcast** Windows rehearsal with the actual game, speaker,
   model, avatar and OBS, proving all outputs remain inactive until approved.
3. Collect truthful time-synchronized observations, including repeated
   speaker-output resets while `sample_speaker` is in flight, and verify
   no old-epoch sample can authorize a new-epoch action or speech frame.
4. Run paired minimum-20 baseline/candidate trials of the same game/version
   and voice scenarios; disallow missing audio, game stalls, memory crossover,
   fabricated achievements or invalid model completions.
5. Publish only validated improvements via reviewable draft PRs. No auto-merge,
   model-weight updates, secret access, broadcasts or multiplayer publication.

### What was NOT achieved

No measured increase in neural-model intelligence or token/s speed, no actual
game wins, no new training, no live OBS authentication, no real TTS/rig
rehearsal, and no proof of humanlike consciousness. The committed code change
is specifically an output-telemetry epoch race fix plus offline regression
coverage; the other sections are researched, prioritized future experiments.
