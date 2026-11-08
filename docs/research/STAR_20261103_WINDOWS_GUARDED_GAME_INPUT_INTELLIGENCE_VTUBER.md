# STAR AI — 2026-11-03: Windows game-input pilot and autonomous VTuber research

**Status:** Code implemented and tested with simulated Windows I/O on Linux; live Windows keyboard/gameplay, model speed, and VTuber naturalness **not yet demonstrated**. Stacked on draft PR #927. Does not change `main`.

## What this branch implements

Star's `GameActuationRehearsal` already verifies a single-use OBS-guarded `ActionPermit`, owner/focus authorization, action deadlines, and OS key-release callbacks. It lacked an actual Windows-native backend. New modules introduce a **pinned-foreground-window Win32 `SendInput` pilot**:

- `star/windows_game_input_worker.py`: separate short-lived process performing **one** mapped key down and unconditional key-up attempt; key hold limited to **1–180 ms**, no media/audio/OBS operations, only movement/arrows/space, foreground HWND and PID rechecked. Parent pipe EOF/STOP triggers early release.
- `star/windows_game_input_port.py`: an owner-enabled host port implementing `send_action`, `request_all_up`, `all_keys_up`, and `focus_ok` for existing `GameActuationRehearsal`; bounded worker lifecycle, serial calls, one game per port, no untrusted-key input. Its release callback does not disable subsequent successful actions.
- `tests/test_windows_game_input_guardian.py`: mocked I/O regressions, no keyboard injection. The backend remains **OFF by default**, with no model-facing or viewer-facing controls.

**Trusted Windows host wiring (illustrative only):**

```python
port = WindowsGameInputPort(
    hwnd=owner_selected_foreground_hwnd,
    pid=verified_game_process_pid,
    action_map={"jump": "jump", "walk_w": "move_up"},
)
port.enable(owner_approved=True)
gate = GameActuationRehearsal(
    episode=trusted_obs_guarded_episode,
    send_action=port.send_action,
    request_all_up=port.request_all_up,
    all_keys_up=port.all_keys_up,
    focus_probe=port.focus_ok,
    permission_probe=trusted_game_permission_probe,
)
gate.enable(owner_approved=True)
# Only gate.run(a_host_issued_original_ActionPermit) may request input.
# Stop the gate/worker and construct a fresh port on game or owner transition.
```

**Limits, not to gloss over:** Microsoft's `SendInput` docs state that UIPI can block injection, the API cannot guarantee games consume synthesized events, and it does not reset already held keys. `GetAsyncKeyState` observes desktop key state, not a physical-input receipt or game result; its return may be uninformative on inaccessible desktops. The child worker has a bounded hold **while alive**, but a worker dying while holding a key is **not** covered by its own `finally`. This is not a native independent safety watchdog, not a production autonomous game controller, and not an anti-cheat bypass. A separate supervised OS helper, external kill switch and real Windows validation are required before active gameplay. **This Python worker CLI is not an operating-system security boundary**: another process with arbitrary shell access under the same interactive Windows account could invoke the worker directly, or call `SendInput` itself. Production needs a broker service protected by OS account separation/ACLs; never grant model-controlled shell access to the trusted input account. No real game keys were sent in this development run.

Primary references:
- Microsoft Win32 `SendInput`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
- Microsoft `KEYBDINPUT`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput
- Microsoft `GetAsyncKeyState`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate

## Highest-return intelligence and performance research

1. **Real-time two-timescale reasoning.** Use a small fast controller for decisions made while a game world continues moving; during downtime, use a deeper teacher to analyze failures and propose strategies. Persist only independently verified practice outcomes, then require held-out and cross-game evaluation before graduating a new skill. Star's existing live-clock paired benchmark from PRs #926/#927 is a prerequisite; measure completed objectives and correctly acknowledged inputs, not just tokens/second.
2. **Proactive speech rather than nonstop chatter.** Proact-VL (March 3, 2026) studies real-time gaming commentary and deciding *when* to speak. For Star, combine fresh host-observed events, explicit quiet periods, viewer-turn priority, short utterance budgets, cancellation before playback, and genuine reaction timing. Do not invent wins, feelings or historical game experiences. https://arxiv.org/abs/2603.03447
3. **Humanlike listening and turn-taking.** LiveKit's turn detection and tuning docs offer dynamic endpointing and adaptive interruption controls. Evaluate on laughter, music, overlapping viewer questions, game sound, speech pauses and ambient silence. Audio playback acknowledgements must determine lip animation; queued TTS must not animate her avatar. https://docs.livekit.io/agents/logic/turns/tuning/ and https://docs.livekit.io/agents/logic/turns/turn-detector/
4. **Fast inference under shared GPU pressure.** Benchmark llama.cpp warm/cold prompts, quantization, KV caching, batch sizes, speculative decoding, CPU memory pressure, and GPU usage **while game+OBS+avatar+speech are active**. Speculation can regress performance: an upstream llama.cpp issue documents slower speculation with some draft pairs. Keep improvements only when matched QoS and correct action rates improve. https://github.com/ggml-org/llama.cpp/issues/10664
5. **General-knowledge and creator skills.** Curate source-grounded, provenance-aware memory across Roblox Luau, Studio, Blender, animation, motion, lighting, audio production, UI, software engineering, world knowledge and mechanics learned from games. Reserve GPU memory for interactive work; schedule code search, full-context studies, test generation and game building between broadcasts. Validate authored Roblox builds with actual engine tests, multiplayer checks, playable loops, visual diffs and rollbacks.
6. **Persistent VTuber character, accurately AI.** A stable backstory, evolving interests, long-term creator projects, grounded memories and dialogue with Astro and Amber can make Star feel consistent and expressive. Preserve consent, chat moderation and audience boundaries; never pretend she is a human person or disclose private chat/user data. Silence and uncertainty are preferable to forced jokes or fabricated experiences.

## Engineering acceptance gates

1. Linux offline tests + strict lint + compilation + identical published Git objects.
2. **Read-only Windows** preflight of configured HWND/PID, key registry and safety flags, with **zero** injected key events.
3. Independently monitored **dummy local game** trial (no streaming) with explicit owner approval and test-only keys; record focus loss, parent exit, child crash, synthetic key-up, real game response, and stop deadlines. This requires a separate native supervised watchdog before unsupervised use.
4. Integrated **nonbroadcast** rehearsal with real OBS/VTube Studio/audio, live-clock game-state telemetry, input acknowledgment, and per-step latency/failure reports.
5. A/B skill and model promotions based on held-out achievements, controller p95 latency, game FPS, OBS dropped frames, voice-start latency, and no new input faults. Roll back regressions.

**Release condition:** No claim of better intelligence, winning games, natural speech, or safe physical key control until these measurements are collected on authorized Windows hardware. No merge to `main` without review.
