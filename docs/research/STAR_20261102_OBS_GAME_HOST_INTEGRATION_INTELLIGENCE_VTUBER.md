# STAR — verified OBS-to-game episode bridge and 2026 intelligence / VTuber research

**Engineering date:** 2026-11-02. **Status:** proposed, disabled by default. **Depends on:** PR #918's authenticated `ObsGameStreamEpochSource` and the existing `RealtimeGameLoop`. No live gameplay, streaming, model training or Windows physical input was run as part of this change.

## 1. Implemented this run: practical missing host boundary

`star/obs_guarded_game_episode.py` introduces `ObsGuardedGameEpisode`. It is a reusable, opt-in **trusted host integration** for one owner-approved game episode, not a game bot. The host creates it with an authenticated OBS event witness, one realtime controller, independently implemented focus/permission probes, a cancel-inference request callback and an all-keys-up request callback.

The bridge connects OBS only with explicit owner approval, samples the authenticated single-connection epoch when it starts, and **rechecks OBS at offer, inference completion, and immediately before final action claim**. It supplies `stream_live` and `stream_epoch` itself; these fields cannot be passed by the model through the bridge methods. It uses one injected *trusted host monotonic clock* for all deadlines and latency samples. Final claim independently invokes host focus and permission callbacks. Unexpected errors revoke the episode permanently, stop new game leases, request in-flight worker cancellation, request key release and disconnect OBS. Cleanup is best-effort, with no false claim that a worker has actually terminated or a physical key-up completed.

**Tests:** deterministic offline fake OBS protocol, one-use lifecycle, independent focus/permission checks, valid one-shot claim, OFF→ON→OFF transitions during model thinking and between response and claim, OBS restart, dropped socket, invalid telemetry, invalid password and an exception from a safety callback. All without opening real OBS or injecting a key.

**A critical distinction:** a successful `claim()` is *only* an advisory result. Its boolean does not authorize physical input by itself. The Windows host still needs to check that the approved game is the foreground process at the physical dispatch edge, enforce per-title policies and anti-cheat/ToS restrictions, ensure key release with a separate OS-level watchdog, and suppress auto-broadcast. Because even the last OBS status fence can precede an external stream transition, an independent host monitor must react to such changes during actual input. Likewise, a callback that requested key release cannot prove release unless separately attested. Keep this opt-in, never make it model-callable.

### Host-only minimal integration sketch (illustrative; not a launch command)

```python
# Trusted Windows host, never model-supplied callbacks:
episode = ObsGuardedGameEpisode(
    witness=ObsGameStreamEpochSource(),
    loop=RealtimeGameLoop(),
    focus_probe=windows_check_foreground_game,
    permission_probe=windows_check_episode_authorization,
    release_keys=windows_request_all_keys_up,
    cancel_inference=host_request_worker_termination,
    clock_ms=lambda: time.monotonic() * 1000,
)
episode.start(scope, symbolic_allowlist, password=local_obs_password,
              owner_approved=True)
# Only after trusted host measurements and an actual frame observation:
lease = episode.offer(frame, telemetry=trusted_sample, host_verified=True)
# host executes a bounded, permissioned *fast inference* worker if lease.route allows;
# worker's proposal alone cannot call game input or invent OBS evidence.
permit = episode.finish(lease, frame, hint, telemetry=latest_trusted_sample,
                        host_verified=True)
if permit.offered and episode.claim(permit):
    # STILL requires independent physical-dispatch focus / OBS / key-up watchdog.
    pass
# Host requests physical key release and independently confirms it before:
episode.release(permit, host_confirmed_released=real_keyup_confirmation)
episode.stop()
```

## 2. Intelligence: optimize **verified progress per elapsed second**

**2026-10-14 — RealtimeBench / TORSI:** https://arxiv.org/abs/2610.20665. A 180-task, six-game benchmark demonstrates that slow deliberation can be harmful while the simulated world continues. Its two-timescale teacher/student method improved a fast student's average progress from 13.51 to 24.19 after two rounds *in the paper*, not in STAR.

**Proposal:** architect the real-time lane as screenshot/event capture → compact game state → calibrated rapid policy → bounded advisory action → independently checked dispatch. **No retrieval, browser research, training or deep reasoning in the frame deadline**. The slow lane replays authorized failed attempts, develops new policies, validates them on held-out maps or seeds, and promotes only robust passing improvements. Recording a video or a self-reported reward is NOT proof a strategy improved.

**Acceptance metrics:** deadline-adjusted solved-task score, win rate across held-out levels/episodes, invalid actions per 1,000 frames, p50/p95 time from frame to verified suggestion, frames skipped because late, and overall game FPS during OBS+voice. Compare matched hardware, same seeds, and randomize policy order to avoid warm-cache contamination. Keep practice/validation sets separated, reproducible and locally stored.

## 3. Game creation: verify a *playable game*, not just passing code

**2026-10-01/06 — Roblox OpenGameEval:** https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval. The benchmark has 84 stateful Studio tasks, executable scene checks, and play-session checks. Full exploration before modifying relevant objects correlates with more reliable results. Its pass rates are not STAR's.

**2026-10-19 — CEGame-Bench:** https://arxiv.org/abs/2610.26098. This long-horizon, cross-engine benchmark emphasizes a striking gap between integration/build success and actual game completion; its paper reports only 16% of agent-produced games reach the ending in the evaluated settings. This is an independent research result.

**Proposal for STAR Studio Lab:** retrieve game requirements, pre-explore affected Instances, sandbox edits in a copy, statically check Luau, simulate one/two-player interaction, inspect collision paths/UI state and camera failures, test start→play→save→restart→finish, then compare to untouched control. Export a verified semantic diff and rollback receipt. The first deliverable should be a stable end-to-end golden game, not merely more generated assets.

## 4. Speed: 8-GB VRAM is a measured budget, not a promise

**llama.cpp source:** https://github.com/ggml-org/llama.cpp/tree/master/tools/server. Server slots, prompt reuse, caching and speculative decoding are useful knobs but can hurt on cache misses or GPU contention. Run a comparative matrix against real game+OBS+avatar load: quick model only; quick model + LLM cached prefix; quick model + speculative draft; and CPU speech + GPU quick model. Measure *correct completed responses*, p95 latency, prompt-prefill time, tokens/sec, VRAM headroom, dropped OBS frames, game 1% lows, STT/TTS delay, power usage and memory pressure. Under resource strain **shed background research, high-frequency vision and high-resolution animation first**.

**Candidate:** Kyutai Pocket TTS https://kyutai-labs.github.io/pocket-tts/ is an available CPU-oriented streaming speech engine. CPU viability does not establish better voice quality or speed for this PC. Benchmark it against STAR's current TTS using a fixed, consented sentence corpus, on the streaming hardware. Only approve if audible quality and turn latency improve without harming game FPS.

## 5. Humanlike, without pretending to be human

**2026-03 — Proact-VL:** https://arxiv.org/abs/2603.03447 examines proactive multimodal companions and the vital decision of *when* to comment; its gaming scenarios include solo commentary, co-commentary and guidance. **LiveKit turn-taking:** https://docs.livekit.io/agents/logic/turns/turn-detector/ documents model-based end-of-turn detection and ways to measure premature interruptions.

**Architecture:** an event-salience queue observes *verified* game milestones, chat questions and teammate speech; a turn manager reserves silence when another person speaks; a short text planner commits a truthful line; streaming TTS produces aligned phonemes and playback timestamps; the avatar adds expression, blink, gesture, subtle hair physics and gaze. Personality and autobiographical memory should recall only events Star actually played/observed, distinguish guesses, include confidence, and never fake personal off-stream experiences or human legal status. Astro and Amber can be separate opt-in stage characters with collision-free speaking turns, not three voices fighting for the microphone.

**Evaluation:** blind human preference across matched highlights; unwanted speech per 10 minutes; interruption rate; question-to-audible-response p95; audio-motion skew p95; correct/false game commentary rate; memory error rate; playback artifacts; rate of user-muted sessions. Scripts that manufacture impressions of feelings are less useful than genuine continuity, humor and responsive timing. Clearly disclose that STAR is an AI VTuber.

## 6. Priorities and hard gates

| Priority | Deliverable | Required verification |
| --- | --- | --- |
| P0 | Windows nonbroadcast OBS + Game bridge | One witness per episode, focus recheck at input edge, auto keys-up watchdog, terminal stop on socket failure, no unauthorized stream |
| P0 | Integrated rehearsal | 15+ minute game+OBS+TTS+avatar trace; p95 turn latency, 1% low FPS, drop rates and VRAM evidence |
| P1 | Controlled game learning | Baseline/teacher practice/held-out head-to-head across fixed task suite; statistically sound win/progress delta |
| P1 | Speech/naturalness system | Silence budget, interruption evaluator and lip-sync against *playback*, not predicted samples |
| P1 | Studio Lab golden game | Automated launch, playthrough, multiplayer action, crash recovery, restart/save and finish test |
| P2 | Local knowledge + distilled skills | Retrieval with source dates, confidence, failure cases, deterministic rollback before any self-promotion |
| P2 | Multi-machine resource governor | Brain 1/Brain 2 latency-aware placement, no GPU-sharing assumptions, offline degraded mode |

**Deployment limitation:** this change runs no physical game input, does not connect to owner's running Windows Studio or OBS instance, and cannot prove new game wins, neural-network intelligence, streaming naturalness or lower latency. It is an independently tested integration building block that helps make the eventual hardware rehearsal reliable. Keep the PR draft until Windows acceptance and full CI verify.
