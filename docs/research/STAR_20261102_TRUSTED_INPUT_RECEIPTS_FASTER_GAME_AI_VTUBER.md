# Star: Verified game-input release, live-clock intelligence, and natural streaming
**Research/implementation date:** 2026-11-02 (US Central). **Stage:** new opt-in Python integration bridge plus simulated offline tests; not live Windows control or a stream. This change is stacked on draft PR #920.

## Verified engineering gap and implementation

PR #920 made the emergency key-release *request* nonblocking when an authenticated OBS snapshot stalls. That request was not independently confirmed to release a key, however, and `ObsGuardedGameEpisode.claim()` produces only an advisory permit. A host could still call `release(host_confirmed_released=True)` without sampling the actual OS input state. The missing seam is an explicit trusted action and release receipt.

`star/game_actuation_rehearsal.py` now supplies `GameActuationRehearsal`: disabled until owner-approved and bound to an already active, authenticated OBS-guarded game episode. It accepts only an original `ActionPermit`, never arbitrary keycodes from the model. It checks focus/permission before and after the authenticated OBS claim, hands one allowlisted symbolic action to a **host-owned** native-port callback, requests all keys/buttons up, and **only then** acknowledges `episode.release()` if a separate host state probe returns exactly `True` within the monotonic dispatch window. Missing release, stale permit, changed OBS epoch, invalid port response, exceeded deadline and focus loss stop the episode permanently. Owner stop sets an independent cancellation Event without waiting for a blocked input-port or OBS callback; a late action cannot be *reported* successful.

**Boundaries:** Python cannot make an asynchronously scheduled OS input write atomic with stop. The eventual Windows native port **MUST** perform its own stop-generation check atomically at the actual write edge, provide an independent out-of-process maximum-key-hold watchdog, and observe **owned** keys/buttons physically up. A successful callback or `SendInput` return does not prove the game received the action or that a key is released. Never use this simulated bridge as evidence that Windows control is ready.

New offline tests cover cloned/forged permits, owner opt-in, an action with denied physical release, non-boolean fake release evidence, emergency stop during a blocked input callback or OBS claim, focus changes after claim, port failure, exceeded dispatch deadline and single-use tickets. The initial pre-implementation import failed, then focused fake-host tests were added and passed. None pressed real keys.

Microsoft notes that Win32 `SendInput` is restricted by UIPI and does not reset existing keyboard state; physical verification must account for owned keys versus a human's simultaneously held keys:
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput

## Next Windows acceptance gate (P0)

1. Allowlist a single locally approved offline/single-player executable, process identity, game episode, key mapping and max hold. Keep input and live broadcasting disabled by default; don't bypass game anti-cheat or third-party rules.
2. Implement a separate small native input worker with monotonic stop generation at its last OS injection boundary. Implement an **independent watchdog process** that releases only agent-owned keys if the worker crashes, loses focus, misses heartbeat or exceeds its hold deadline. Never trust model/game/chat text with dispatcher capabilities.
3. Bind real physical key-up and mouse-button release checks to the new bridge. Return receipt only after the OS state for every agent-owned button is verified; ambiguous state is a terminal failure. Audit emergency key-up under blocked OBS, lag, process exits, elevated-window mismatch and screen focus changes.
4. Run an owner-approved **nonbroadcast** Windows rehearsal with real game frames, AI reasoning, OBS, synthesized audio and avatar. Require zero stale actions, zero key-hold deadline violations, 100% *independently confirmed* release, and sustained FPS/OBS frame delivery. Passing fake-host tests is not enough.
5. Keep stacked PRs draft until full checks and Windows acceptance; main remains unchanged until approved merge.

## Higher gaming intelligence: separate fast reflexes and slow learning (P1)

The October 14, 2026 research *The World Won't Wait: Evaluating and Teaching Agents Under a Live Clock* describes RealtimeBench: 180 tasks across six continuously running game types. The paper reports a fast agent's mean progress improving from **13.51 to 24.19 out of 100** after two offline learning rounds. These are the researchers' measurements, NOT Star's.
https://arxiv.org/abs/2610.20665

For Star: a latency-bounded **reflex agent** handles hazards and short vetted moves without waiting for internet/teacher calls. A **teacher agent** reviews signed practice failures between sessions, proposes strategies, tests them against unseen levels and only promotes verified better behavior. Use visual change tracking and cheap event detection continuously; invoke heavy vision when game state is novel or uncertain. Keep model selection and context compression keyed to scene and deadline, with explicit refusal to act on stale frames.

Evaluate against fixed and held-out live-clock game episodes: completed correct actions within the real deadline, win/progress rate, transfer across unseen maps, tail latency, 1% low FPS, OBS dropped frames, CPU/RAM/VRAM, number of repeated inference calls, and failure/recovery rate. Higher token/s alone is not a gameplay improvement. With 8GB VRAM hardware, prefer model routing, prompt reuse, asynchronous noncombat learning and CPU speech over simultaneous heavy GPU tasks; benchmark every proposed optimization under OBS+game load.

## More natural, grounded AI VTuber (P1)

LiveKit's reproducible end-of-turn benchmark jointly evaluates false user interruptions and endpointing delay on pauses in 14 languages. The reported English LiveKit Turn Detector v1 **543 ms endpointing delay at a 5% false-cutoff operating point** is a comparison reference, not Star's result; delay here is not model inference time:
https://github.com/livekit/eot-bench

The streaming pipeline must coordinate **listener turn-taking, actual sound-device stop, avatar animation flush and speech admission**. Avoid talking over a mid-sentence viewer, repetitive ambient talk, and fake game-winning claims. Tie excitement and quiet reactions to *signed, genuinely observed* gameplay, and use brief natural pauses. The Star/Astro/Amber character trio can converse, play and emote, but should not monopolize viewers' turns. Build privacy-scoped memories of real games/lessons, not raw chat logs or biometric voiceprints. Explain transparently that Star is an AI character, not literally human.

Kyutai's Pocket TTS now documents October 2026 small English models at **18.2M, 6.9M and 1.9M parameters**, with CPU streaming options. Benchmark sample expressivity, first audible PCM and steady real-time CPU impact before choosing the fastest model:
https://kyutai-labs.github.io/pocket-tts/

Paired naturalness tests should compare interruption rate at matched end-of-turn budget, spontaneous speech relevance, speaker-voice overlap, grounded reaction accuracy, return-question quality, latency to first audible response, lip-sync drift and game FPS in the **same** workload condition. Evaluate on distinct, independent viewer situations; repeated contexts cannot count as independent victories.

## Game creation and breadth of knowledge (P2)

Build a verified Roblox Studio inspect → multiple candidate builds → Luau lint/compile → Play Solo/multiplayer objectives → screenshots and collision/rig inspection → rollback pipeline. Include verification against player journey and visual quality, not just successful code generation. Roblox's Open Cloud place-publishing API has known limitations for types such as EditableMesh, EditableImage and SurfaceAppearance, so an API success is not a full Studio publish:
https://create.roblox.com/docs/cloud/guides/usage-place-publishing

For broader knowledge: curated source-backed retrieval, signed local skill lessons, a versioned internal self-improvement store, backup/rollback, and testable cross-domain curricula (games, animation, VFX, 3D, UI, web). Permit web research on demand but keep online calls out of live reflex decisions. Priority is measured correctness, competence and reliable resource use, not unverified self-awareness claims.

**Change scope:** one new code module, adversarial offline tests and this research artifact; no actual OS input, game win, model retraining, streaming output or measured new intelligence.
