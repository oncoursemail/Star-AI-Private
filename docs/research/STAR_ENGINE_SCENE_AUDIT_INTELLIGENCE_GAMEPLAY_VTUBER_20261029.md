# STAR: Engine-Observed Scene QA + Intelligence Research
Research and development note: 2026-10-29.

## New verified engine opportunity
Roblox officially documents a command-line RunScript task for Studio, accepting a script path, output-file path, optional local place file, and quit-after-execution. This means Star can inspect real engine state for trusted local places, not just execute Python simulations. It is separate from Studio's multiplayer playtest APIs and Open Cloud Luau execution.

Official source: https://create.roblox.com/docs/studio/command-line-interface
Creator Docs source: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/command-line-interface.md

Implemented in this branch: star/studio_cli_scene_audit.py, with tests/test_studio_cli_scene_audit.py. The owner-approved runner executes fixed, read-only Luau via the official CLI, not model-generated source. It audits at most 50,000 Workspace descendants, checks counts of collidable unanchored objects, invisible collision surfaces, very small parts, spawn locations and Models lacking PrimaryPart. The report is a heuristic: invisible colliders, physics objects and models with no PrimaryPart may be intentional.

This runner never saves or publishes a place. It is OFF until explicitly approved. The caller must provide a trusted fixture inside an approved workspace or deliberately select a new empty Baseplate. Loading an untrusted place can run its existing scripts with side effects; never audit downloaded or hostile games.

## Real Windows observations
On the authorized Windows desktop, RobloxStudioBeta.exe was found installed. A CLI smoke test using a fresh, nonpublished Baseplate exited successfully and created the documented output file. A second invocation using the exact fixed generated Luau scene probe exited successfully and observed six Workspace descendants, three BaseParts and one SpawnLocation on October 29, 2026. No game was edited or published. The CLI output echoes source code lines prefixed with a prompt, so the validator accepts only the standalone printed evidence line; a naive substring search would falsely report duplicate markers.

The full module itself was then transferred byte-for-byte to that Windows host, executed with explicit approval on a fresh default Baseplate and exited 0. It returned status=observed, PlaceId=0, GameId=0, descendants=6, BaseParts=3, SpawnLocations=1 and zero heuristic warnings; verified_playthrough=false and authorized_to_edit=false. The Windows SHA-256 of the executed Python module matched the Linux source: 42f39a4999524ad29a9cdf206569c9b4218046803783facec676c3a438e8909d. No published project, user content, or external service was modified. Local unit tests exercise hostile logs, nonce replay/mismatch, oversized output, impossible counts, path escapes and owner-approval behavior. Neither CLI output nor these unit tests certify gameplay mastery.

## Infrastructure design decisions
The probe permits only fixed whitelisted properties and counters, sends no secrets into Studio, rejects malformed or oversized output, uses a per-run challenge nonce, passes exact subprocess argument vectors without shell execution, uses temporary files, and bounds run time. Output is a structural observation, not proof of code correctness or an authorization to edit. The host must protect its executable path, trust the place fixture, and keep credentials and personal logs out of GitHub.

A challenge nonce is not cryptographic attestation of the Studio executable, place authenticity or all descendant behavior. It is unsuitable as a replacement for Star's separately signed pre-edit inspection receipts.

## New actionable research priorities

### P0: Intelligent game production through execution
Build a graduated verification stack: pre-edit dependency inspection, reproducible object graph construction, geometry and collision checks, static Luau analysis, official Studio engine scene audit, true visual screenshots, actual input-based objectives, multiplayer tests, persistence/rejoin, and human-facing aesthetic review. Automatically repair only issues with verified repro steps. A clean scene audit is not evidence of beautiful UI, enjoyable gameplay or a playable ending.

### P0: Local autonomous intelligence with measured evidence
Use Star Core Forge as the canonical internal source of hypotheses, benchmark tasks, candidate changes, failures, reproducible execution artifacts, code snapshots and rollbacks; GitHub remains optional publication. Generate progressively harder problems in Roblox and unrelated domains. Hold out test tasks before improvement, and evaluate actual transfers rather than model-generated self-praise. Do not promote novel algorithms without independent evidence. Separate factual knowledge from inferences and fictional persona.

### P0: Humanlike VTuber behavior as one synchronized timeline
Coordinate game attention, auditory turn-taking, deliberate silence, genuine laughter, gaze, blink, expressive eyebrows, twin-tail physics, gestures and actual TTS playback timing. Keep episodes grounded in events Star really observed or participated in. Let her develop consistent hobbies, projects, inside jokes and a recognizable social style without fabricating human-life memories or implying she is literally human. If a game demands focus, chat reactions should wait; if a viewer interrupts, stale captions/voice/avatar actions must be cancelled together.

LiveKit turn handling: https://docs.livekit.io/agents/logic/turns/turn-detector/
VTube Studio API: https://github.com/DenchiSoft/VTubeStudio

### P0: Speed optimization without destroying streaming
Schedule a fast perception/action lane, a conversational speech lane and a slower planning/learning lane. On a gaming machine with an 8 GB RTX 4060, Roblox rendering and OBS output quality compete with neural inference for limited resources. Benchmark prompt caching, speculative decoding and CPU TTS versus remote inference, preserving Roblox FPS and 1% lows, OBS dropped/encoded frames, speech responsiveness, VRAM and CPU headroom.

llama.cpp's SPEED-Bench compares latency, token throughput and speculative acceptance under identical workloads. Faster token production alone does not show greater intelligence, and some speculation settings are slower. Before and after experiments need the same prompts and held-out quality measurements.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Kyutai Pocket TTS small October 2026 CPU models are candidates to measure for Star's voice pipeline. Check real-time factor, first-audio latency, intelligibility, emotional expressiveness and preference against her current voice before changing the model.
Source: https://github.com/kyutai-labs/pocket-tts/blob/main/README.md

### P1: Learn to play unfamiliar games by competing hypotheses
For each authorized practice episode capture the initial game state, actual input, resulting state, reward, time and rule compliance. Compare paired strategies under similar initial conditions. Track separate skill metrics for completion rate, time and failure rate. Re-evaluate on unfamiliar held-out maps. Permit self-directed hobbies and practice within approved games and platform rules; do not use online cheating, exploit APIs, or anti-cheat evasion.

### P1: More than Roblox
Maintain source-backed general knowledge indexed by revision and license. Include design/3D assets, Blender animation, procedural graphics, physics, speech science, narration, UI design, accessibility, programming, computer operations and user-approved scientific interests. Prefer primary docs. Detect contradictions and cite current sources in responses. Verify generalization using task suites that Star has not seen during practice.

## Promotion requirements
Record at least three matched workload runs per candidate, include baseline and uncertainty. Streaming improvements require preserved game FPS, stable OBS transport, useful speech latency and independent correctness. Game-creation improvements require real player input and complete objective/persistence checks. Autonomous-learning claims require held-out evaluation and versioned rollback. The new CLI scene observer, by itself, proves none of these.

## Next integration
1. Repeat the successful full module-level Windows smoke check against an owner-approved, trusted local project fixture.
2. Integrate the official CLI audit into an explicitly approved Windows Studio Lab host, with a trusted-fixture allowlist and resource/timeout constraints.
3. Store nonpersonal structural metrics in Star Core Forge's experiment ledger.
4. Connect to visual QA and real gameplay witnesses, then run paired improvements with independent checks.
5. Benchmark speculative decoding and CPU speech while Roblox+OBS are under representative load.

Security: The repository named Star-AI-Private is reportedly PUBLIC on GitHub. Do not place secrets, viewer identities or recordings in it.
