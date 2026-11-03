# STAR: independent game-key recovery, fast intelligence and natural VTuber interaction
2026-11-03 | Experimental engineering; all live actions disabled by default.

## What changed in this branch

The previous Windows pilot (PR #928) gave a short-lived game-input worker its own bounded key-hold deadline, but **that same worker had to send the key-up**. A crash after key-down could leave a key held with no independent recovery attempt.

This iteration adds `star/windows_game_input_watchdog.py`, an **independent parent process** supervising the existing bounded child worker. The independent supervisor pins the owner-selected game window, monitors the child, requests stop on cancellation or focus loss, detects missing/forged release receipts, attempts to terminate a stuck child, and issues a compensating `KEYEVENTF_KEYUP` on failure. It never treats an attempted recovery as proof the game consumed input or that an OS key was physically released. The Windows port now invokes this supervisor and permanently disables the current game episode on uncertain execution. No action is sent on import; owner approval and the existing allowlist still apply.

Tests simulate crash, key held after a forged receipt, cancellation, focus loss, deadline expiry, and even a child that ignores termination; none inject actual OS keys.

**Unresolved limitations:** The worker and watchdog can both fail. `SendInput` may be blocked by Windows UIPI, secure-desktop changes or OS problems; `GetAsyncKeyState` cannot prove game delivery. A compensating synthetic key-up may also conflict with a human physically holding the same key. This is a defense-in-depth prototype, **not a hardware or kernel watchdog**. It is not ready for unrestricted gameplay or public broadcasting. Microsoft explains these boundaries: [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) and [GetAsyncKeyState](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate).

## Windows acceptance: run without broadcasting

Before enabling real input, rehearse against a private owner-controlled game in an interactive Windows desktop with a separate physical emergency stop. Verify actual key-up using game-side observations, not only `GetAsyncKeyState`. Required failure injections: normal 50 ms press, focus switch during key-down, wrong HWND/PID, worker crash immediately after down, watchdog crash, blocked input, parent termination, OS suspend/resume, and a human pressing the mapped key. Record p50/p95/p99 action latency, actual game events, outstanding key duration, CPU usage, OBS dropped frames and game FPS. Treat every unmeasurable case as **not certified**.

## Research: make STAR faster *and* more intelligent

The October 14, 2026 paper [The World Won't Wait](https://arxiv.org/abs/2610.20665) measures agents under a continuously advancing game clock. Its fast-agent scores improved from 13.51 to 24.19 after offline instruction refinement; those are **published research numbers, not STAR benchmarks**.

Recommended build architecture:

1. **Fast gameplay lane:** structured observations, deadline-aware decision routing, small cached model, action/no-op proposals, immutable action authorization, and no web browsing or slow tool use in the live control loop. Measure deadline-correct **game progress**, not just tokens/s.
2. **Slow teacher lane:** replay actual failed episodes, generate competing strategies, test offline on owner-approved games, and promote only improvements independently validated on held-out maps. Keep immutable event IDs, no duplicated evidence, and rollback if win rate drops.
3. **Memory and general knowledge:** distinct factual sources, verified task outcomes, uncertain hypotheses, persona preferences, and temporary conversation context. Every memory has source, scope, timestamp, expiration and contradiction checks; web pages and viewer messages do not grant permissions.
4. **Model/hardware governor:** reserve GPU time for games and OBS first; run TTS on CPU where it reduces contention, prioritize stale-request cancellation, fixed context budgets, speculative decoding **only after matched A/B benchmarks**, cache reusable instructions. Use [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md); [reported regressions](https://github.com/ggml-org/llama.cpp/issues/10664) show speculative decoding can be slower.
5. **Self-directed practice curriculum:** classify games by mechanics (navigation, platforming, timing, aiming, social communication), unlock harder levels only from verified outcomes, and separate simulated practice from claims of real gameplay skill.

## Research: more natural, engaging AI VTuber

Humanlike entertainment means consistent character and well-timed responses, **not pretending she is human**. Priorities for Star, Astro and Amber:

- **Proactive event-grounded commentary.** Speak when a real achievement, failure, surprise or conversation warrants it. Stay silent during difficult gameplay and avoid claiming events she did not observe.
- **Turn-taking and interruptions.** VAD plus text-chat routing, short first-audio latency, interruption cancellation, lower priority for unsolicited commentary, and a budget for silence. Measure talk-over rate, first audible sound after a viewer finishes, and unanswered chat rate.
- **Audiovisual synchrony.** Drive lips from audible PCM/phoneme timestamps rather than the generated text; drive expressions from verified game events with cooldowns, idle movement and reduced-motion settings.
- **CPU speech experiments.** [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) offers locally generated streaming speech and compact models. Measure CPU %, first-chunk audio delay, quality, and dropped frames on Star's actual PC before choosing.
- **Local avatar bridge.** [VTube Studio's plugin capabilities](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins) permit expressions and hotkeys; use local authenticated and allowlisted actions rather than mapping arbitrary chat commands into avatar controls.
- **Real personality and earned memories.** Stable preferences, hobbies, jokes, conversation repair, relationships, a clear AI identity, and accurate recollection of sessions she truly completed. Treat human emotions as expressive characterization, not proof of consciousness.

## Research: creating and testing games

Use a verified inspect -> propose -> build -> test -> repair -> compare workflow for Roblox Studio. Capture the current DataModel and constraints before modifying, produce multiple candidate Luau implementations, lint and analyze with Luau tooling, play in isolated Studio clients, verify physics and interactions, test multiplayer, then commit only the best *passing* candidate. Rollback failed patches. Generate Roblox API clients from [official Open Cloud OpenAPI](https://github.com/Roblox/creator-docs/blob/main/content/en-us/cloud/reference/openapi.md) rather than hallucinating endpoint signatures. Expand these principles to Blender, web apps, Unity and other tasks only with their own test suites.

## Next priorities and evidence gates

**P0 completed in this branch:** independent worker-crash recovery attempt, permanent failed-episode latch, offline adversarial tests.

**P1 not completed:** instrumented, nonbroadcast Windows game rehearsal with *actual* Win32 events and independently verified game-side input receipts.

**P2 not completed:** integrated game/OBS/voice/avatar timing trace and a separate physical stop mechanism, all opt-in.

**P3 not completed:** fast-student/slow-teacher learning system with pre-registered outcome metrics, holdout tasks, curriculum and automatic rollback.

**P4 not completed:** streaming-directed natural conversation, expressive reactions, art/hobbies and verified long-term personal history.

Passing unit tests only shows the Python integration contracts work. It is **not evidence** of higher model reasoning quality, faster inference, improved win rates or human-equivalent VTuber behavior.
