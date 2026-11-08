# Star AI — preplay lease recovery and measurable real-time intelligence
**Research and implementation date:** 2026-11-08. **Status:** offline-safe code and tests; not integrated with physical audio or public broadcasting.

## Engineering finding: a speech-plan deadlock disguised as polite silence

The existing `StreamPreplayGate` reserves one `SpeechIntent` during `preflight()`, then expects a host to revalidate and eventually settle that intent. A dropped VAD callback, interrupted generation, delayed scheduler, stale OBS sample, or cancelled TTS draft can prevent a plan from being reviewed or settled. Before this change an expired, never-reviewed candidate remained in `_pending`, making subsequent calls return `awaiting_previous_playout_receipt` indefinitely. This can make Star seem inattentive during a long stream even if her perception and inference work correctly.

### Implemented, with bounded failure modes

- Recover a candidate that **never passed final revalidation** once its short lease or the source-event deadline expires. Call the existing director's `complete(..., spoken=False)` so the event is abandoned rather than falsely recorded as spoken.
- Run recovery before the fresh VAD / GPU / OBS admission check, so stale telemetry cannot leave a zombie reservation. Never infer that a missing VAD/audio callback means silence.
- Never automatically recover a **reviewed** candidate: the trusted physical output host may already have PCM queued or playing. Require host acknowledgement to settle that stage, otherwise overlapping speech could occur. The watchdog cannot grant playback or broadcast authority.
- Provide three bounded, non-sensitive lifecycle counters: expired unreviewed drafts, current unreviewed candidate, and reviewed plan awaiting physical host receipt. They contain no chat or audio.
- Remain default-disabled, independent of OBS, game inputs, microphone, TTS, external chat, viewer identity and streaming permissions.

**Known limitation:** `settle(..., audible_confirmed=...)` still relies on a trusted caller; this module does not cryptographically authenticate physical PCM receipts. An external, separately permissioned output host must verify play/abort/flush and attest the exact epoch. A reviewed orphan is intentionally blocked instead of being guessed safe. Do not treat a planning receipt as proof of sound heard by viewers.

## Measurable intelligence, not just larger prompts

1. **Fast perception/action loop** (host-controlled, hard deadlines): capture game state at a bounded rate; publish object positions, objective, collision/death cues, telemetry timestamps and uncertainty. A verified action policy selects from permitted game inputs. Never let a slow LLM inference frame block this loop.
2. **Tactical model** (asynchronously, interruptible): analyze difficult situations, propose a plan with a game-state version and expiration, and never act on a stale scene. Store successful tactics as evidence-bound recipes.
3. **Learning loop** (offline/low-priority): propose practice goals, run paired real-time vs slowed/paused challenges, diagnose mechanics, evaluate against single-use withheld scenarios, and promote only independently verified results. Preserve failed attempts as diagnostic data; don't tune on holdouts.
4. **General-knowledge loop** (source-aware): retrieve versioned Roblox API docs, Luau diagnostics, creator assets, voice/OBS specifications and trustworthy general references. Distinguish cited facts from guesses and show uncertainty. Pin exact retrieval corpus/build with each skill change. Keep user memories scoped, erasable and grounded in observed events.

[Gym-Anything-RT, published October 27, 2026](https://arxiv.org/abs/2610.37567) evaluates 100 real-time minigames and their paused/slowed counterparts and finds a large execution-time capability gap. This directly supports testing **action deadline success**, not only reasoning accuracy. The published 9% vs 75% result is for a specific evaluated frontier configuration, **not a forecast** for Star's local hardware.

[OpenGameEval, published October 1, 2026](https://arxiv.org/abs/2610.02563), evaluates Roblox agents over 84 curated stateful Studio tasks and shows that inspecting relevant objects before editing correlates with higher success. Pair every Star code-writing action with read/inspect, Luau static checks, executable Studio checks, and independent repair verification. Verify the benchmark *version* and task split; the original 2025 release used 47 tasks, later expansions differ.

## Inference engineering for competing 8 GB VRAM workloads

A gaming/OBS host with an 8 GB NVIDIA GPU has limited headroom for a large resident language model, video understanding, avatar rendering and TTS. Capacity has to be measured, not inferred from quantization size alone. The user's game + OBS frame budget must win resource contention over optional narration.

- Establish simultaneous-game baseline at the actual resolution and OBS encoder setting, recording p50/p95 perception-to-action delay, rendered-frame p99, OBS render/encode/network losses, free VRAM and TTS first-audio p95.
- Benchmark a deterministic small reaction model (or validated tool/policy) before choosing a larger language model for tactical steps; route only tasks which measurably benefit.
- Compare persistent prompt prefixes/KV caching, draft/speculative decoding and `--np`/batch/concurrency settings with matched model, sequence length, prompts, game load and GPU headroom. Keep a control group with no optimization.
- `llama.cpp` [SPEED-Bench documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures prompt/decode throughput, end-to-end latency and speculative draft acceptance; benchmark under load as well as idle. Its [server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) explains shared-prefix cache reuse. Faster token generation **does not imply** faster actions or better gameplay.
- Treat lower p95 action latency **at equal-or-higher holdout win rate and equal-or-lower OBS frame loss** as a genuine improvement. Do not claim one until there are on-device paired measurements.

## Human-*like* streaming through better timing, not deception

Use Star's consistent fictional persona, interests, expressive eyes/gestures and verified episode memory, but explicitly identify her as an AI VTuber. A believable stream benefits more from speaking at the correct time than talking nonstop.

- Revalidate speech immediately before output. Honor verified owner interruptions and guest turn-taking; never derive owner authority from similarity or untrusted chat.
- Prefer short, relevant game-specific reactions. Avoid repeating success lines or talking over jump timing and multiplayer comms. Use silence naturally.
- Bind each reaction to a visible gameplay event, game/round identity and maximum age. Synchronize mouth/avatar frames to real PCM receipts; never animate a claimed voice response without corresponding audio.
- Let her make and play small games, comment on what she actually tried, learn from outcomes, schedule her hobbies and evolve her style. Keep any outgoing public interactions under moderation, rate limits and channel-specific permissions.
- [Microsoft Proact-VL](https://github.com/microsoft/AnthropomorphicIntelligence/blob/main/Proact-VL/README.md) is a 2026 research direction for deciding *when* to proactively comment during a continuous video stream; it is not proof that the current Star host can already do this.
- [OBS websocket](https://github.com/obsproject/obs-websocket) includes an authenticated API; use read-only local stats in private rehearsal, never infer authorization to broadcast merely from a successful OBS connection.

## Acceptance ladder for actual deployment

**Offline regression (this PR):** a never-reviewed candidate that times out must be abandoned exactly once and stop blocking later questions; stale VAD must remain a hold; a reviewed candidate must stay reserved until a trusted host receipt; parallel preflights must not double consume a lease; any fake timestamp must fail closed. Tests may use deterministic synthetic input; they do not prove physical audio behavior.

**Private, owner-approved Windows experiment (future):** against a dedicated signed audio-output process, prove verified positive-tone/negative-control process isolation, correct audio epoch, physical abort/queue flush, unique receipt and playout latency. Keep raw voice/audio local and disposable.

**Recording-only integrated rehearsal (future):** actual game + vision + local inference + TTS + avatar + OBS. Collect p95/p99 action response, TTS onset, owner interruption stop delay, game-frame p99, VRAM headroom, render/encoder misses, percent grounded commentary, double-talk incidents and holdout game success. An unexpected broadcast, stale scene action, fabricated speech receipt, or severe OBS overload fails the rehearsal.

**Deployment gate:** require independent Windows CI, manual owner-reviewed hardware measurements and confirmation of actual runtime wiring before promoting the draft. No evidence currently demonstrates a live-stream-ready Star, a faster LLM, or higher game win rate.

## Design constraints

Protect user chat, voice and game account data. Make all autonomy opt-in, bounded and reversible; keep tool permissions separate from speech advice. Preserve Star's offline-first internal development system and export to GitHub only through reviewed branches. Avoid large model downloads on the Linux host until disk headroom (previously about 14 GB free) is verified.
