# STAR: second artifact verification before Windows worker resumes
**Date:** 2026-11-07. **Status:** experimental, owner-opt-in; no live-stream/model-service deployment.

## Implementation in this change

PR #1035 introduced owner-pinned SHA-256 digests of the executable and up to eight small additional launch artifacts. It verifies them immediately before VRAM reservation. A remaining gap is a change to a pinned executable/script *between that check and when the optional worker starts running*.

This increment composes **three existing optional protections**: real host GPU observations, Windows Job Object containment, and digest-pinned launch plans. With both `require_job_tree=True` and `require_artifact_pins=True` the supervisor gives the Windows Job launcher a **host-only, bounded second verifier**. The Win32 launcher first creates the process suspended, assigns it to a KILL_ON_JOB_CLOSE Job Object, then rechecks the *same command and pinned files*. Only after that succeeds does it resume the main thread. A mismatch or failed check terminates the Job and closes its handles; the supervisor faults and retains the VRAM claim conservatively because it cannot independently reconcile a process that never returned a handle.

This is **not** a filesystem TOCTOU elimination, a security sandbox, prevention of malicious DLL load, or proof that model weights are trusted. The Windows loader may map the executable before the second check; scripts can change again after it. Restrict write access to the runtime, use offline deployment verification for multi-GB weights, and do not use this for untrusted executables. The second pass doubles bounded preflight hashing work (up to 128 MiB per pass) and is only suitable off real-time audio/game/OBS callbacks. Strict mode remains disabled by default. The raw Win32 constructor also now rejects actual embedded NUL characters in its argv.

### Verified scope and acceptance criteria

- Portable unit tests: owner-selected strict Job launch passes both checks; a simulated file replacement *after the first pass but before resume* fails; normal non-strict Job mode stays compatible; no ambiguous failure releases a GPU reservation.
- On a real Windows computer, use only a disposable signed/local Python executable to verify a rejected pre-resume callback cannot run the child. No real OBS, game, voice or resident AI model process should be signaled. A subsequent private run with real NVIDIA telemetry is needed before production opt-in.
- Do **not** interpret passing tests as a higher neural tokens/sec rate, better game-play performance, humanlike conversation quality, or a complete production Windows deployment.

## Research: making STAR faster and smarter without worsening gameplay

**Real-time thinking has an opportunity cost.** The October 27, 2026 Gym-Anything-RT benchmark compared 100 minigames under continuously running vs paused conditions. The authors report one frontier agent reaching 9% pass while continuous versus 75% paused. These are *benchmark figures*, not Star scores. The actionable architecture is a three-timescale agent:

1. **Fast reflex:** map fresh, independently verified game observations to a bounded safe action; skip late decisions and ensure input acknowledgement is returned before the scene deadline. Reuse Star's `game_deadline_router.py` and `game_action_freshness.py` rather than adding another uncontrolled LLM.
2. **Tactical planner:** at slower checkpoints, reason about opponent strategy, resource collection, map paths, mechanics and failures. Keep action requests symbolic until the trusted input gate verifies them.
3. **Offline learner/game maker:** invent or select controlled tasks, run an authorized game/Studio lab, compare 4-8 candidate policies when hardware permits, analyze independently verified success, and retain only improvements that transfer to held-out variants and unfamiliar games. Never accept an LLM self-report of victory or expose holdouts in training.

**Inference speed experiment:** llama.cpp's official SPEED-Bench measures throughput, latency and speculative-draft acceptance. Compare normal, n-gram, compatible draft and MTP candidates using the exact same model, prompt corpus, warmed/cold conditions and active OBS/game load. Speculation can be *slower*, especially if the draft consumes scarce 8-GB VRAM or acceptance is low. Promote a configuration only if p95 capture-to-action and first-audible-response improve **without** lower held-out game success, audio quality or OBS stability. Store rollback profiles and per-run GPU free-MiB traces. An unmeasured "54 tok/s" estimate is not a hardware benchmark.

**CPU voice trade-off:** Kyutai's October 2026 small English Pocket TTS models offer CPU-oriented streaming candidates including 18.2M, 6.9M and 1.9M parameters. These can preserve GPU memory in some conditions, but CPU contention, first audible PCM delay, intelligibility and voice expression must be measured on Star's actual machine. It may be better to use a compact CPU voice during demanding gameplay and a richer model during quiet moments only after gated A/B evaluation.

## Research: a convincingly expressive yet clearly AI VTuber

Microsoft's May 2026 Proact-VL work separates deciding **when** to speak from deciding **what** to say. NVIDIA's June 2026 DyaPlex describes streaming full-duplex speech and synchronized movement. Neither paper is an installed Star component. Build on current turn-taking/interrupt and avatar modules with a **grounded performance loop**:

- Observe an actual game result, live VAD/owner speech, validated chat and measured animation/playback. Do not hallucinate a win, loss or social memory to fill dead air.
- Decide whether to comment at all: long silences are appropriate during gameplay focus, co-commentary should yield to others, and owner barge-in stops speech without requiring voice-based identity authentication.
- Generate short event-linked speech, with animation events tied to *actual audio timestamps*: neutral listening pose, subtle blink, emotional emphasis, mouth movement only when sound is emitted. Respect reduced-motion and mute controls.
- Remember approved gameplay achievements, favorite genres, recurring goals and lessons with source/time/evidence; do not store private viewer information without consent. Avoid claiming to be literally human or conscious.
- Rehearse privately with OBS local recording; measure overlap errors, p95 interruption stop time, first-audio latency, lip sync, factual event grounding, viewer privacy, and gameplay FPS/win rate in the same session.

## Roblox game-creator expansion

Roblox's **November 4, 2026** Studio MCP update expands permission-scoped Open Cloud asset import, game-management and analytics access. For Star: design a tiny game loop, construct in a local Studio Lab, typecheck Luau, import versioned Blender assets with scale/material checks, run scripted/private player tests, inspect screenshots and output, automatically repair verified bugs and re-run acceptance. Public publishing, spending and moderation remain behind owner policy. Prefer finishing 3 small playable benchmark games with held-out tests over merely adding dozens of APIs.

## What to build next (distinct from this PR)

1. Wire the opt-in strict Job launcher into a **trusted** Windows optional-worker service. Run a dedicated disposable-process admission/abort/restart drill with *real* GPU observations; private, no broadcast.
2. Implement a reproducible end-to-end performance lab for matched game/task seeds: verify capture -> model -> action ACK -> independently observed state change, along with simultaneous TTS + avatar + OBS.
3. Add paired held-out game-skill promotion with no self-graded wins and quality-preserving latency routing.
4. Implement and blind-test context-aware VTuber silence, interruption, reaction and lip-sync policies before any public session.
5. Connect the verified game-builder loop to the latest Studio MCP permissions and visual QA.

### Primary sources (reviewed November 7, 2026)

- Microsoft, Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- Gym-Anything-RT, 2026-10-27: https://arxiv.org/abs/2610.37567
- Microsoft, Proact-VL (ICML 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA, DyaPlex (June 2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Roblox official Studio MCP 2026-11-04: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
