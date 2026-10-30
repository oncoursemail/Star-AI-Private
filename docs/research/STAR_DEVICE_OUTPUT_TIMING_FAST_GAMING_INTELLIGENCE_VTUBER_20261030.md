# STAR — Real device-output timing, gaming intelligence and expressive VTuber roadmap

**Research date:** October 30, 2026  
**Release type:** Opt-in observational improvement, no new streaming permissions or runtime services.  
**Status:** Implementation and offline regression tests added in this branch; real OBS/device acceptance tests still pending.

## 1. Verified gap and implementation

STAR's existing voice "total latency" metric measured **end of user speech to first PCM queued to the speaker**, yet documentation called it time until a person could hear her. Queuing audio does not establish that the sound card, virtual microphone, OBS, or viewers received the signal.

This change instruments the **actual SoundSpeaker PortAudio output callback** with one monotonic timestamp when the first nonzero PCM chunk is offered to that callback. The observation is retained across interruption and reset for each new voice reply. The existing CallSession adds validated fields to its metrics and latency table:

- **first_output_callback_at** — optional same-clock host timestamp, never generated from model text.
- **output_callback_status** — observed, unobserved, unplayed, invalid, or unsupported.
- **queue_to_output_callback** — time the device queue spent before its first nonzero output buffer.
- **output_callback_total** — end of the user's speech to the first nonzero host output callback.
- **OUT_CB** — new latency-table column; existing **TOTAL** remains queue time for backward compatibility.

A missing or unreliable callback is never silently represented as a successful audible response. Invalid types, negative/infinite/out-of-order times, callback exceptions, and no-playback conditions fail closed **for telemetry only**; normal voice playback is not interrupted. No dialogue, voice samples, usernames, or media are persisted by the new measurement.

**Critical interpretation:** An output callback can be scheduled ahead of an actual DAC presentation; the speaker can be muted or routed away from OBS. Thus these measurements are driver-stage signals, **not proof of acoustic audibility or verified livestream delivery**. PortAudio's outputBufferDacTime is in the stream's timebase and must be correlated to the host monotonic clock before use. Source: https://python-sounddevice.readthedocs.io/en/0.3.11/_modules/sounddevice.html

## 2. New external research, checked October 30

**Voice latency tracing:** LiveKit explicitly separates end-of-turn, STT, language-model first token, TTS first byte, and playback start. STAR should not aggregate unequal timing boundaries into one misleading "speech" metric. https://docs.livekit.io/reference/agents/session-traces/

**Speculative read-only tool calls (published October 6, 2026):** An Android cascaded voice-agent study predicted tool needs from partial speech, executed candidate calls while the user was still talking, and checked predictions after corrections. It reported first-audio median dropping from 5.79 s to 4.60 s on its own setup—not a transferable STAR speedup. STAR may experiment with cacheable **read-only** speculation, never speculative spending, game controls, external posts, or account changes. https://arxiv.org/abs/2610.07641

**Listen/Think/Speak (January 26, 2026):** Research on dual foreground speaker and background thinker suggests nonblocking reasoning and natural pauses can coexist. A streamer must also honor interruption, partial ASR corrections, and chat priority. https://arxiv.org/abs/2601.19952

**GameWorld (April 8, 2026):** 34 games, 170 tasks in runner, arcade, platformer, puzzle, and simulation with authoritative game-state success metrics. It provides a model for evaluating whether STAR learns controls, timing, plans, and long-horizon strategies rather than merely producing plausible commentary. https://arxiv.org/abs/2604.07429

**Roblox Studio (March 5 and April 15, 2026):** Built-in Studio MCP and automated playtesting/virtual input can support real inspect/build/test/repair loops. Prefer supported Studio interfaces and controlled game sessions over brittle global desktop input. https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

**EMemBench (2026):** Generates experience-specific memory questions from game trajectories with programmatically derived answers. STAR's memory should retain concrete observed actions, places, objectives and verified results while measuring generalization to unseen episodes. https://github.com/InternLM/EMemBench

**llama.cpp inference (current server documentation):** Prompt caching is supported, cache-reuse has an adjustable threshold and Prometheus metrics are optional. Before deploying any optimization, compare warm/cold prompts, quality, full-task p95, gaming FPS, and resource contention. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**Metric freshness caveat (issue opened October 7, 2026):** Some llama.cpp metrics can lag pending prompt/token accounting. Pair counters with local monotonic spans and successful task outcomes. https://github.com/ggml-org/llama.cpp/issues/30123

**Speculative decoding is workload-specific:** Real issue reports document both gains and regressions across technical, coding and creative outputs. A fast gaming model should not inherit a spec-decoding setting simply because it helped a coding model elsewhere. https://github.com/ggml-org/llama.cpp/issues/23052

## 3. Architecture proposal for STAR's intelligence

### Foreground: responsive player and host

- Use short-lived deterministic game input policies to meet timing constraints; never block each jump or dodge on a lengthy model completion.
- Maintain immutable identities for current game, window, level, and player session. All input commands require the authorized target and a short expiry/deadman timeout.
- Decouple face/mouth rig and voice envelope from background reasoning and rendering.
- Admit urgent speech, interruption, input, and safety actions ahead of optional game asset rendering and research.
- Require independent proof of actual voice playout before remembering an explanation as heard.

### Tactical visual/learning loop

- Sample visual frames only when motion, environment state, objective, or uncertainty materially changes.
- Drop stale vision conclusions. A delayed hazard description must not trigger an input in a game state that no longer exists.
- Before a move, log a predicted outcome; after the move, receive an independent game-state result.
- Classify failures into perception, latency, control, physics, pathing and strategy rather than making a generic memory entry.
- Promote learned mechanics into a reusable skill bank only after repeat trials on holdout levels.

### Strategic knowledge and self-improvement

- Distinguish factual reference knowledge (dated source + version), task skills (worked examples + tests), episodic memories (direct experiences), and persona lore (fictional characterization).
- Retrieve only relevant verified entries for the present question; avoid filling the entire context window with low-quality memories.
- Generate harder independent challenges as performance rises, using unseen level seeds to prevent benchmark contamination.
- Use Star Core Forge as the offline-first code provenance, experimentation, rollback, validation, and skill promotion system. GitHub remains optional for publishing and collaborative review.
- Gate code promotion on holdout task success, correctness, real latency and memory, rollback readiness and regressions.

## 4. Gaming and high-quality game creation

For private Studio Lab, train across movement timing, jumping, tracking targets, multiplayer cooperation, puzzles, exploration, unfamiliar cameras, and recovering from failed actions.

For a generated Roblox game, require a full **launch -> input -> progress -> save -> restart -> restore -> ending** test, verified inside the engine. Add geometry support, anchoring, collision, z-fighting, UI legibility, scale, lighting, animation, VFX, platform accessibility and player usability checks. Screenshots alone cannot verify mechanical correctness; Lua tests alone cannot verify visual polish.

Score at least: unseen-level completion rate, win/death ratio, elapsed time, action validity, repeated failure count, objective correctness, streaming/game FPS, and independent visual review. Compare with a fixed baseline and report negative results rather than cherry-picking successful episodes.

## 5. Humanlike VTuber behavior without deceptive biography

STAR can present a charming, expressive fictional character with recognizable humor and sustained personal continuity while remaining clear that she is an AI. Aim for *believable interaction*, not unsupported claims of biological consciousness.

- **Voice and timing:** short and long sentences mixed naturally, context-appropriate laughter, pauses to focus during precise movement, coherent turn-taking, safe interruptions.
- **Character rig:** expressive eyes and gaze, synchronized speech/mouth cues, spring-driven flowing twin tails with damping, lip closure, body posture, natural head/shoulder motion, reduced-motion mode.
- **Persona:** persistent preferences, hobbies, achievements, mistakes and funny anecdotes from actual verified sessions; fictional backstory labeled as character lore.
- **Gaming:** focus on the game during demanding segments, periodically scan chat, respond to real requests without interrupting a vital move.
- **Social autonomy:** participate in authorized spaces, privacy-safe viewer memory, platform moderation rules, low-risk routine autonomy; do not invent personal relationships or expose private data.
- **Streaming:** OBS private rehearsal, no background app/window capture, emergency mute/stop controls, game allowlists, moderation and consent.

## 6. Controlled speed experiments

| Trial | Baseline | Candidate | Primary outcome | Gate |
| --- | --- | --- | --- | --- |
| Speech queue | PCM enqueue time | first callback and independent loopback | p50/p95 to truly observed output | no false 'heard' claims |
| Fast/slow brain routing | one model | confidence-and-task router | correct finished tasks per minute | difficult queries no worse |
| Prompt caching | cold context | stable cacheable prefix | p95 first speakable phrase | no stale knowledge |
| Vision | synchronous vision pass | timestamped asynchronous worker | game FPS + action freshness | no wrong-window action |
| Gaming practice | fresh unseen levels | outcome-guided learning | held-out wins, deaths, elapsed time | repeatable evaluation |
| Stream persona | scripted reactions | event-grounded expressions | viewer ratings + interruption errors | no false life stories |

Tests must counterbalance game scenes, capture hardware/config snapshots, run enough samples to measure p95, and compare real output instead of extrapolating from a microbenchmark. CPU and RAM improvements should remain valuable on modest hardware.

## 7. Test scope and remaining dependencies

New offline tests cover valid, absent and corrupt callback times, unsupported fake speakers, zero playback, stable first callback, silent input, reset, and interruption-safe timestamp persistence. The core voice flow and saved conversation history remain unchanged.

**Still required for a production claim:** Windows sounddevice/PortAudio callback test, independent loopback or OBS playback witness, captured game frame presentation timestamps, real model TTFT/first speakable time, and interrupted-stream reliability. Test at least 30 full pipeline trials and 20 interruptions; measure p50/p95 and task-quality regressions before enabling any production flags.

**No claim in this PR:** faster neural inference, greater underlying model intelligence, trained gaming mastery, verified viewer audio, consciousness, or a human-quality live broadcast. This PR improves the *quality of performance measurement* so future optimizations can be chosen on evidence.
