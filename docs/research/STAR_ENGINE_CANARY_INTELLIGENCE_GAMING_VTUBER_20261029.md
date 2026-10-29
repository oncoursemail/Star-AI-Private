# STAR: Real-Engine Canary, Fast Useful Intelligence, Gaming and VTuber Roadmap

Research and implementation date: **2026-10-29**.

This document separates **implemented code**, **offline simulation**, **actual Windows-engine observations**, and **future integration**. It does not claim that a new neural model was trained, that Star learned to play a game autonomously, or that a broadcast was operated.

## Why this change matters

The preceding scene-regression PR compared two local `.rbxl` / `.rbxlx` files through Roblox Studio's official `--task RunScript` interface. The proposed Windows experiment had been blocked when hand-constructed scratch files were not accepted by the engine. More simulation tests would not resolve that problem.

The new [studio engine regression canary](../../star/studio_cli_engine_canary.py) adds a **direct end-to-end diagnostic of the detector** using *two separate, unsaved default Baseplate sessions*. It intentionally creates one tiny, collidable, invisible, unanchored Part **in memory only** in the second session and executes the same fixed read-only counter code. The live engine itself, not a mocked Python object, must produce the changed counts.

The host requires two explicit conditions: an owner-approved local diagnostic and a trusted report that streaming is idle. No user place path, project ID, universe ID, arbitrary Luau body, network command, or save operation is accepted. Each Studio process is told to exit after execution.

Expected independent engine evidence:

| Observation | Expected delta |
| --- | ---: |
| Workspace descendants | +1 |
| BaseParts | +1 |
| Unanchored collidable Parts | +1 |
| Nearly invisible collidable Parts | +1 |
| Tiny Parts | +1 |
| SpawnLocations | 0 |
| Models missing PrimaryPart | 0 |

The canary passes only if **all seven** expected deltas match and the existing scene-regression comparator independently flags precisely the three intentionally injected risks. It rejects a duplicate, mismatched or malformed marker; a baseline from a published game; a missing Studio CLI output; or unexpected scene changes. Timeouts and other launch failures never become passing reports.

**Proof boundary:** A passing canary validates that a specific Studio installation, CLI interface, transcript parser, and comparator can detect this deliberately injected simple defect on a default scratch template. It is not proof of reliable differences between real game versions, no-overlap geometry, good gameplay, visual taste, saved progress, or model intelligence. Production regression testing still needs two independently saved **real** place snapshots.

Official Roblox command-line interface: https://create.roblox.com/docs/studio/cli

Roblox testing modes, including real client/server testing and network simulation: https://create.roblox.com/docs/studio/testing-modes

## Observed real Windows Studio engine result

On **2026-10-29**, the exact locally tested canary source files were copied to an authorized Windows machine, with all three Python module SHA-256 hashes checked to match the Linux source. No OBS process was active in the preflight inspection. Roblox Studio's documented `RunScript` command launched **two separate ephemeral Baseplate sessions** and returned a genuine `passed` result with these seven deltas:

```text
descendants +1, base_parts +1,
unanchored_collidable +1, invisible_collidable +1, tiny_parts +1,
spawn_locations 0, models_without_primary_part 0
```

The measured Python end-to-end process runtime, including both Studio startups and exit, was **38.47 seconds**. That is entirely appropriate for an **idle-only engine acceptance test**, not a per-frame or live gameplay loop. The canary was not connected to a user-made game, player input, save/restore, neural inference, an OBS broadcast, or a VTuber animation host.

## Faster AI means **faster verified outcomes**, not just more tokens

Researching llama.cpp's SPEED-Bench demonstrates why Star should not universally enable draft-model speculative decoding: some pairs or hardware backends are slower than a single model. A September 2026 Windows report also described a severe configuration-specific slowdown in one build/decoding path; the observation is a diagnostic signal, not a universal claim.

Use paired on-device benchmark trials with baseline, quantized, and speculative configurations on the *same prompts and answer requirements*. Retain raw quality labels from independent validators and compare:
- p50/p95 first useful reply (not only first token);
- verified task completion and hallucination rate;
- GPU memory occupancy and 1% low game FPS;
- OBS encoder/dropped-frame continuity;
- p95 first audible TTS chunk and interruptions;
- peak RAM/CPU during scenes and image reasoning.

Give live gameplay a hard rendering/voice budget, route straightforward chat to a small fast model, and move expensive research, self-play, Blender renders, code generation, large multimodal perception and agent tournaments to an idle/dedicated machine. Only start experiments when trusted telemetry indicates sufficient headroom; preserve quality holdouts and rollback.

llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Configuration-specific Windows performance investigation (September 2, 2026):
https://github.com/ggml-org/llama.cpp/issues/28219

## How Star should **actually** learn unfamiliar games

To build general gaming skill rather than memorized moves:

1. Record an unfamiliar map and available action schema in an isolated, authorized test context.
2. Observe a bounded frame history and predict the effect of each potential action **before** taking it.
3. Execute input only through a trusted, focus-checked host. Record the *resulting* state separately from Star's estimate.
4. Grade objective completion using independent game-state evidence; retry failures under a specified hypothesis.
5. Test improvements on a **withheld level or ruleset** to detect overfitting.
6. Store reproducible episodes inside Star Core Forge: exact game build, action sequence, sensor freshness, reason for failure, candidate strategy, test outcome and rollback reference.
7. Practice both solo and multiplayer contexts (disconnects, latency, camera and device changes). A complete playthrough is stronger evidence than a plausible simulation transcript.

Roblox documents distinct server/client simulation, up to eight local simulated players, device and network simulation, and the `VirtualInput` interface. Its RunScript CLI is **not the same thing** as a full playable multiplayer session. Keep these proofs separate and label them clearly.

Sources: https://create.roblox.com/docs/studio/testing-modes

## Making Star a genuinely appealing **AI gaming VTuber**

Treat timing, focus and consistency as one synchronized performance system, not separate arbitrary animation loops.

**Game/attention lane:** During a precision jump, fast combat or teammate speech, focus on the action and suppress low-priority chat. A UI indicator may show that Star is concentrating. She can reflect after a checkpoint rather than constantly narrating.

**Voice lane:** Use turn-taking that distinguishes silence in the middle of an utterance from a completed turn. Make audible speech the source of truth for mouth movement and captions. Explicitly stop stale audio after a turn interruption. Evaluate expressive prosody, natural-sounding laughter and silence with blind human ratings, not a single automated classifier.

**Avatar lane:** Blend expressive amber eyes, natural blinking, subtle head and upper-body movement, gold-tipped twin-tail motion and hand poses with bounded acceleration. Trigger celebrations from real signed gameplay achievements; do not represent arbitrary image-frame guesses as verified wins. For VTube Studio, its official API supports parameter injection and hotkeys. Account for hotkey queueing/cooldown and dropped connections.

**Memory lane:** Build a biography from genuine witnessed experiences: *"I finally beat the bridge after six attempts"* only after the six attempts were verified. Clearly distinguish fictional persona lore from lived digital experiences; keep viewer details private by default and use minimal consented summaries.

**Social lane:** Develop persistent hobbies (drawing, music, building, gaming), self-selected projects and playful cat/dog modes, but keep modes and voice/persona changes owner-tunable. Never invent personal relationships, a human childhood, or claims of literal human consciousness.

Kyutai Pocket TTS's October 2026 small CPU models (18.2M/6.9M/1.9M parameters) provide plausible speed candidates, **not measured Star speed or quality wins**. Evaluate intelligibility, character consistency, laughter and streaming latency on the actual hardware before changing voices.

Sources:
- https://kyutai-labs.github.io/pocket-tts/
- https://github.com/DenchiSoft/VTubeStudio
- https://docs.livekit.io/agents/logic/turns/turn-detector/

## Next acceptance experiments

1. Complete the scratch-only real-engine canary test on the Windows host, reporting observed counts without exposing local file paths, source logs or user data.
2. Run existing scene regression on two *actual* saved, owner-approved Studio project snapshots; verify it catches a removed spawn without misclassifying intentional moving physics objects.
3. Join Studio preflight, pathfinding/navigation integrity, generated input tests, full playthrough verification and post-edit visual review into **one** reproducible job. Reject regressions rather than automatically publishing.
4. Compare local model/TTS configurations under realistic simultaneous OBS + Roblox + avatar workloads; promote only Pareto improvements in useful latency, answer quality and stream stability.
5. Run human-rated VTuber test sessions for conversation timing, audible voice, laughter, avatar expressiveness and factual, experience-grounded memory, followed by a held-out unfamiliar game.

**Security:** The GitHub repository named `Star-AI-Private` is publicly visible as of this date despite its name. Do not place game files, private memories, secrets, stream keys, login tokens, viewer identities or recordings in this branch. GitHub remains an **optional publishing/review channel**; autonomous long-term improvements should be validated and retained locally inside Star Core Forge.
