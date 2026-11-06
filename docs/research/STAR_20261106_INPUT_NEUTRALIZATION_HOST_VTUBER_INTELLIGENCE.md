# Star AI — guarded host neutralization, real-time gaming, and natural VTuber roadmap
**Research / implementation review:** 2026-11-06
**Change scope:** owner-authorized, offline-first diagnostics. No live game inputs, microphone recording, OBS broadcast, model download, GPU speed claim, or autonomous public posting in this change.

## Why this upgrade, instead of another synthetic latency metric?

The previous host recorder checked frame coverage, action freshness, callback submission acceptance, host ACK deadlines, and abort cancellation. It still allowed a strict-host frame to be scored as complete when **an action submission was accepted but no input-neutralization request was even made**. This is a critical boundary for sustained movement, held movement keys, mouse clicks, and gameplay interruptions. A callback ACK is neither a key-up signal nor a game outcome.

This change adds an **opt-in host neutralization request phase**, not a claim of physical key release:

- `require_input_neutralization=True` requires strict submit confirmation and a configured `max_input_hold_ns` of 1 ms to 10 s.
- The authorized host calls `guarded_dispatch(frame, submit_callback)`, `guarded_neutralize(frame, release_callback)`, then `action_ack(frame)`.
- The release callback MUST return **exactly `True`** to attest only that the host accepted a release/neutralization **request**. A missing, rejected, invalid, exceptional, late, or out-of-order callback invalidates the entire timing window. In strict neutralization mode, ACK before neutralization is refused.
- A **late** release request is **still invoked**; its over-budget timing then revokes the benchmark. Never skip a release request merely because the frame is already stale.
- Concurrent emergency abort remains nonblocking for cancellation of timing evidence even during a blocked release callback.
- Status explicitly says `physical_input_release_attested=False` and `independent_gameplay_proof=False`. It never reports acceptance as proof that the keyboard is physically up or the game moved.

**Limits:** Python callback locking and request receipts do not release keys if a host process crashes, blocks in a native driver, loses focus, or cannot inject across desktop/integrity boundaries. This phase is not a production safety watchdog. It must be paired with a small *independent native process* responsible for physical release and heartbeat expiry before connecting to any Windows game; the native process must monitor held-button state and force neutralization on process death, loss of foreground window, device ownership loss, or lease expiry. A negative/unknown release outcome must not be hidden. If native release is blocked, halt action issuance and notify the owner; never mark the episode as a win.

## Windows native-host research / engineering contract

Microsoft documents that `SendInput` injects keyboard and mouse events but **does not reset current keyboard state** and can fail due to Windows User Interface Privilege Isolation (UIPI), where the error may not identify UIPI as the cause. Therefore `SendInput` success or an API callback `True` is **not** a physical state witness. `GetAsyncKeyState` can inspect the current async virtual-key state, but it too has desktop/visibility qualifications and is not a universal proof about a game's internal input state. Never silently infer "all keys released" from submitting synthetic key-up events.

Minimum Windows private-host contract:

1. **Foreground / desktop eligibility:** owner-authorized target and input scope only, explicit allowlist, no anti-cheat bypass, abort when foreground handle/desktop changes.
2. **Lease issuance:** for each action, native watchdog owns a token scoped to key/button IDs and monotonic expiry; no token, no key-down. Timeouts independent of Python, model inference and game-thread callbacks.
3. **Physical neutralization:** on normal end, expiry, E-stop, suspend, host exit, focus loss, or watchdog re-registration, release all managed inputs, read state independently where technically possible, emit a structured receipt distinguishing `attempted`, `OS-accepted`, `observed-up`, and `unknown`. Never equate them.
4. **Interlocks:** an old episode token cannot submit on a newer session; drop stale frames before native input. Never allow an AI response or game screenshot to mint host proof.
5. **Closed-loop verification:** independent in-game state telemetry must establish whether movement or game objectives occurred; native key state is *not* gameplay success.
6. **Rehearsal gate:** require a test-run that intentionally crashes/stalls the Python controller while a private synthetic input is held and demonstrates timely release in a sacrificial owner-controlled environment. Do not attempt to validate by sending inputs into online games.

Sources: Microsoft `SendInput`: https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput ; `GetAsyncKeyState`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate (reviewed 2026-11-06).

## More intelligence: objective results, not model self-report

**Reflex (10s–100s of milliseconds target, to be benchmarked)**: a small deterministic controller for immediate input/neutralization; hard deadlines, abstention, no large-model dependency. **Tactical planner**: maintain an uncertainty-aware local game model, predict collisions, choose actions against future state and game-specific constraints. **Practice/critic**: offline episodic replay; local feature store of *verified* attempts; adversarial counterexamples; train/evaluate only against held-out scenarios.

Make every trial have a signed-by-authorized-host chain of frame opportunities, actions, neutralization receipts and game-state transitions. This is provenance **within the host** and not cryptographic proof of an arbitrary online game's integrity. Never use a model's confident narration as an outcome label. Keep independent holdout sets, report wall-clock success, collisions, invalid actions, deadlines, recovery, and transfer to unseen maps/mechanics.

*OpenGameEval* (2026-10-01) evaluates Roblox Studio agent execution through reproducible stateful tasks and executable scene/play-session checks, rather than text-only code grading. It includes 84 human-curated core tasks, testing both inspection and editing. The published study reports that systematic object inspection is associated with higher task success. This supports a Star workflow of **inspect → plan → code → Luau static checks → Studio playtest → independently scored outcome → repair or rollback**, with multiple isolated Studio instances only when host capacity and permissions allow.

Source: https://arxiv.org/abs/2610.02563 ; official project https://github.com/Roblox/open-game-eval .

## Faster on the user's 8 GB GPU (benchmark-only recommendations)

Prioritize **end-to-end effect on real game frames**, not standalone tokens/second. Separate budgets for game FPS, OBS render/encoder, avatar, inference prefill, short reactive dialog, and background jobs. When GPU headroom is low, suspend practice/video tasks, route speech to CPU or lightweight voice, and reserve immediate reactions for non-LLM controllers. Avoid duplicating KV caches across viewers and never mix conversation caches across identities.

Benchmark model routing as a **quality/latency Pareto frontier**: identical test cases; cold/warm starts; CPU vs GPU; quantization settings; context lengths; token/sec, first-token time, p50/p95 capture→actuation, timed-game success, and rollback-on-failure rates. speculative decoding/prompt caching qualify only if they improve those values while gaming + OBS is running. Cap concurrency and maximum resident model sizes; maintain measured CPU/RAM pressure too.

**TTS research:** Kyutai Pocket TTS v4.0.0 (2026-10-20) introduced 18m, 7m and experimental 2m English models, with v4.0.1 corrections (2026-10-21). Test time-to-first-*audible* sample, pronunciation, expression, latency while the game runs, CPU contention and the effect on OBS dropped frames, not merely audio throughput. Do not install large models until storage headroom is resolved.

Source: https://github.com/kyutai-labs/pocket-tts/releases .

## Natural Star VTuber: behavior, experience and human-style timing

Make Star **believably expressive while explicitly identified as an AI performer**. Aim for spontaneous-seeming humor based on true context, emotionally appropriate prosody, gaze shifts, micro-gestures, breathing/idle animations, and comfortable quiet time. Do not assert biological feelings, memories she never formed, or human identity.

Design a stateful **stage conductor** with four independently interruptible lanes:

- **Gameplay lane:** has highest priority for urgent action or neutralization. It may suppress speech during high-stakes gameplay but should not suppress safety or stop controls.
- **Conversation lane:** voice activity/end-of-turn estimates, interruptions, short backchannels, delayed answer when Star is busy, and bounded audience fairness. Break long answers into playout-confirmed segments so a new viewer turn can cut in.
- **Expression lane:** actual playback timestamps drive mouth shapes and gesture onset, *not* the time text is generated. Use game events for surprise and short reactions with cooldowns so one error does not trigger repetitive exclamations.
- **Autobiographical lane:** preserve confirmed personal moments and game achievements with provenance, consent and forgetting controls; separate actual Star streaming history from roleplayed fiction. Include her established visual/voice character bible and changing hobby preferences.

NVIDIA DyaPlex (June 2026, NeurIPS 2026) explores full-duplex speech-motion alignment and reciprocal nonverbal backchanneling. Use it as **design research**, not as evidence that Star currently runs that model.

Source: https://research.nvidia.com/labs/amri/projects/DyaPlex/ .

## Instrument OBS, not only the model

OBS obs-websocket 5.x `GetStats` publishes `activeFps`, `averageFrameRenderTime`, `renderSkippedFrames`, `renderTotalFrames`, `outputSkippedFrames`, `outputTotalFrames`, `cpuUsage` and recording disk headroom. Keep render skips and output skips separate; derive window deltas, not lifetime totals. Track live first-audio timing, interruptions, lip-sync offset and speaking-to-action overlap separately. Rehearsal must be explicitly **record-only** with internet streaming prohibited, and recording artifact paths must be checked against available disk space.

Source: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md .

## Roblox permissions and other generalist skills

Roblox's 2026-11-04 Studio MCP Open Cloud announcement expands agent access to game administration, including publishing, commerce settings, analytics and data operations. These are not equivalent to sandbox Studio edits. Keep **read-only** default and separate scopes by game; private unpublished places cannot use some Open Cloud scopes; production write changes and player data require owner-approved deployment policies and rollback. The Studio MCP client need not receive the underlying account token.

Sources: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 and https://create.roblox.com/docs/studio/mcp-open-cloud .

Beyond coding, add evaluated skills in visual reasoning, audio processing, 3D rigging, video understanding, Windows app control, system diagnostics, research citation checking, computer security, social conversation and game strategy. For each, track artifact validity, objective task results, latency, failure recovery and calibration. Autonomous self-learning means *controlled experiments with measurable generalization*, not unsupervised changes to the live runtime.

## Verification and next gates

**Implemented now:** optional strict host-request neutralization phase; exact-True receipt, hold-age deadline, revocation on missing/rejected/late request; nonblocking abort maintained; deterministic simulated tests. Existing legacy paths unchanged when opt-in is disabled.

**Not implemented here:** native Windows watchdog, physical all-keys-up proof, trusted game-state results, real-game autonomous control, real OBS recording, speech generation benchmarking, neural model training, emotional consciousness, or live broadcast.

**Next acceptance milestones:**
1. Integrate a native, separate-process watchdog and a mock-target harness, never a public game. Kill and stall the controller during input holds; prove release behavior independently of Python locks.
2. Validate a real Windows *offline* game episode via native state and host game-state telemetry. A successful frame requires fresh observation, accepted action, neutralization request, key-up witness where technically available, and independently observed state change.
3. Run concurrent game + OBS (local record) + avatar + CPU TTS/inference trials. Report p50/p95 timings, FPS, dropped frames, underruns and memory pressure across multiple repeatable seeds.
4. Run 30+ unfamiliar holdout tasks for both game-playing and Roblox building. Compare with saved baselines and keep failures in the dataset. Only then promote verified improvements.

**Host/storage status at code-review time:** connected Linux root volume ~95% used (12 GB available). No mass cleanup or model weight downloads attempted. This research is an implementation roadmap, not evidence that the remaining stages already work.
