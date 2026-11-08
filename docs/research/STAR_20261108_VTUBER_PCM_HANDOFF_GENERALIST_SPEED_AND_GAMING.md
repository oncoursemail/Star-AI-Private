# STAR — November 8, 2026: real-time VTuber PCM handoff, intelligence, gaming and speed

**Status:** Research plus narrowly scoped **implemented owner-host integration**, not a deployed VTuber, training result, inference benchmark, Roblox playtest, or claim of actual listener audibility. Production `main` is untouched. This PR stacks on the opt-in preplay restart-fence work (#1064).

## Verified repo observation and why this change matters

The codebase already has `StreamPreplayGate` (fresh VAD/game/OBS advice and restart quarantine) and `LocalEpochPCMSink` (single-use, owner-local epoch-scoped PCM16 queue and stop/quiet accounting). Until this PR they could make independently valid decisions without **one bridge** requiring (a) exact reviewed-intent identity, (b) actual fresh host clock, (c) bound native PCM epoch, (d) STOP before host quiet acknowledgement, and (e) no new output until physical stop is witnessed. In isolation, the preplay gate's drain acknowledgement trusts booleans and a matching `SpeechIntent`; the PCM sink separately trusts its host's native-output-flushed observation. Neither one magically measures speakers, Windows mixer tails or viewer ears.

`StreamPreplayPCMBridge` joins these existing boundaries, disabled by default. It provides:

1. Admission only with exact, current `PreplayDecision(status='reviewed')`, monotonic host clock and independently quiet native PCM epoch. Admission does not authorize broadcasting.
2. Bounded PCM submission only for the exact admitted `(intent, epoch)`; normal sink epoch, format and backpressure checks still apply. Accepted queue writes are **not** evidence audio was heard.
3. A serialized disable path that revokes the dialogue planner **before** native stop, then keeps the previous reviewed intent quarantined across restart.
4. A native-quiet acknowledgement requiring the same intent and epoch, `LocalEpochPCMSink.observe_quiet()` success **and** `StreamPreplayGate.acknowledge_host_drain()` success. Missing, wrong, recycled or partial receipts do not unlock.
5. Fail-closed manual recovery after a failed native stop or mismatched planner receipt; no automatic rearm or forced stream start.

The gate's new read-only `reviewed_for_host(..., now_s=...)` also closes a previously possible stale-review admission: an old reviewed intent must still be within the 250 ms review lease and its deadline *when the native host binds the first epoch*. Ongoing PCM chunks are scoped to the exact already-bound intent/epoch; a trusted output host must continue monitoring VAD/game/OBS interruptions during the whole utterance. **The bridge intentionally implements STOP+FLUSH, not full natural utterance completion or actual audio detection**. Those require independent native host instrumentation; only the trusted device owner may assert quiet.

Offline fake-speaker tests deliberately do **not** invoke PortAudio/OBS/network/Roblox. A real Windows acceptance test must verify the native process and PCM output path, not just test booleans or application buffer counts. Do not ship this as a fully integrated streaming feature before that test.

## Highest-leverage next work (ordered by measurable outcome)

### A. One actual Windows owner-only end-to-end rehearsal, before more abstractions

Run private, nonbroadcast only. Use one dedicated audio process and owner-approved speaker, target process-specific WASAPI loopback, 1–2 short synthetic TTS utterances, avatar rig pose updates, OBS recording **without starting a live stream**, plus a local game test scene. Test: first chunk within specified latency, no stale PCM after owner barge-in/disable, no voice overlap after restart, app + native buffer/loopback evidence agree, no source cross-contamination, and no output without authorization. Record physical process IDs, timestamps and epoch identities in **private diagnostic logs** but exclude them from publicly shared sample datasets. If output-probe quality is unknown, hold restarting rather than infer silence from missing callbacks.

This closes the gap between passing host simulations and actual audio. Write acceptance fixtures to separate 'PCM submitted', 'native output observed', 'external acoustic audibility' and 'OBS recorded'; they are not interchangeable facts.

### B. Faster intelligence under an 8 GB VRAM gaming budget

Test actual **end-to-end latency and task success**; do not rank configurations by tokens/second alone. Run A/B on the same model weights, prompts, seed set and game workload, with warm and cold cache strata, context sizes (2k/8k/16k/32k if supported), one concurrency setting, FPS and OBS logging. Compare:

- A small local reflex classifier/finite-state policy for 16–33 ms action ticks (not a full generative LLM per frame); strategic planner asynchronously revises a **time-bounded** action plan. The physical input host must still validate game focus, permission, signed observed state and key-up watchdog.
- Prompt/KV caching with stable system and task-prefix layout; warm-cache and cold-cache latency separately. Cache hit rate, TTFT and peak VRAM matter more than any assumed theoretical gain.
- Baseline decoding, n-gram speculation and a genuinely compatible small draft model; compare with llama.cpp SPEED-Bench throughput, end-to-end latency and draft acceptance. Speculation can cost more VRAM/overhead than it saves, especially while a 3D game and OBS run.
- A CPU TTS profile using Kyutai Pocket TTS small English models versus the current voice stack; preserve voice/persona quality and first-audio latency, rather than automatically accepting a smaller model. Reserve GPU headroom for game frame-time and OBS encoder stability. CPU thread contention is possible.

**Pass gates** (project targets, not results): no regression in game frame-time p95 or OBS dropped frames; improved p95 owner-interruption-to-native-quiet; no measurable drop in previously unseen game-task success; lower end-to-end comment delay at equal utterance quality. Publish baseline, n, hardware, runtime versions, distributions and failures, not invented TPS values.

### C. Learn games through verified perception → act → outcome, not simulated confidence

Gym-Anything-RT (October 27, 2026) shows the large gap between paused and real-time perception/action. STAR already has a signed `GameplaySkillBank`, single-use holdout ledger, practice curriculum and paused/live gap atlas. The missing payoff is **actual trustworthy game traces** on the dedicated Windows gaming PC:

1. Scope each game/version/build and prevent identical visual frames or repeated challenge IDs from being counted as independent heldout evidence.
2. Collect timestamped screenshots and authorized game-state telemetry, chosen action IDs, actual key-down/key-up or controller events, observed result and deadline; exclude unverified model descriptions from scoring.
3. First learn in safe, local/private training mode using short staged objectives (navigation, camera control, dodge timing, objective understanding, tool use). Iterate with deterministic reset and speed-up/slow-down modes.
4. Use matched-pair comparisons of strategies with a fixed sample budget, then independent unseen levels for promotion. Stage difficulty with confidence bounds and spaced recall; expire obsolete game-version skills.
5. Keep streaming and game-control loops separate. Slow generation must never block key release or a fast reflex. Practice on protected/private instances; respect anti-cheat and game rules in public multiplayer titles.

For making Roblox games, use official Studio MCP inspection and Script Sync, static Luau checks, Rojo/StyLua/selene where appropriate, then Studio playtest assertions and screenshot comparison. *OpenGameEval* offers genuine executable scene/playtest evaluation; its research reports inspection before mutation is correlated with success. Verify bugs using **debug evals** and record real green/red tests rather than showing only polished generated assets.

### D. Natural, *truthful* human-like VTuber presence

- Build **listener state**, not a fixed speech timer: end-of-turn, backchannel, owner barge-in, off-topic viewer chat and game-critical moments have different interrupt policies. RESPOND (Microsoft, March 2026) describes controllable backchannel and turn-claim rates; Proact-VL (2026) is useful for proactive *when-to-speak* decisions from ongoing video rather than continuous chatter.
- Attach facial, eye, blink, ear, hand and hair-rig animations to measured spoken prosody and observed gameplay outcomes. Avoid random exaggerated emotion every sentence; use a small consistent expression vocabulary and natural silence.
- Keep an episodic memory of **verified** things STAR played, built, learned and was told consensually. Distinguish 'observed', 'viewer-reported', 'imagined/persona lore' and 'unknown'. Never invent stories about relationships or claim real human biological feelings as facts. Give a stable recognizable character voice and interests, but disclose AI identity on stream.
- Train presentation skills with private A/B playbacks: turn-overlap rate, median/p95 response delay, interruption completion, facial-lip mismatch, repetitive phrase rate, joke appropriateness, and whether comments refer to actual events. Human review and live viewers can opt out of being remembered.
- Multi-agent collaboration can generate code, maps, dialogue, voice, VFX and QA in parallel **off stream**. A safety- and resource-aware conductor must cap parallel GPU loads and stop nonessential model jobs when the game/OBS/TTS exceed headroom.

## Source review (links verified November 8, 2026)

- Roblox Studio MCP official update, **Nov 4, 2026** (Nov 5 known issue for unsaved places): https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 . New permission-controlled Open Cloud/asset workflows; never give unbounded publish/admin rights to an autonomous experiment.
- Roblox OpenGameEval repository and 2026 evaluation paper: https://github.com/Roblox/open-game-eval ; its release log documents 30 debug evals introduced Mar 3, 2026: https://github.com/Roblox/open-game-eval/blob/main/EVAL_RELEASE_LOG.md .
- Gym-Anything-RT, published **Oct 27, 2026**: https://arxiv.org/abs/2610.37567 . 100 real-time minigames with paused/slowed counterparts; important evidence for deadlines and fast-reflex separation.
- llama.cpp SPEED-Bench documentation: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Match prompts/settings and compare baseline vs speculative decoding; it reports prefill, decode, latency and acceptance.
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts . October 2026 models down to 1.9M parameters are candidates for CPU-voice experiments; published performance on other CPUs is **not** a benchmark on STAR's PC.
- Proact-VL project: https://proact-vl.github.io/ . Continuous video perception and proactive *when-to-speak* policies.
- Microsoft RESPOND, **March 2026**: https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/ . Natural turn taking requires backchannels and listener-sensitive interruption policies, not simply a faster TTS model.
- Realtime-Venus: https://realtime-venus.github.io/ . Asynchronous full-duplex voice/vision direction worth exploring; no plug-and-play fitness claim.

## Operational risks, privacy and release discipline

- On this machine `/` was ~93–94% used with ~15 GiB free. New model downloads, duplicate clone trees and temporary captures can cause hard failures. Use tiny synthetic fixtures, record disk-headroom checks before capture/model installation, and do not delete existing workspaces without an ownership/retention audit.
- The STAR repository contains many partially stacked, draft feature branches. Require independent CI, native host tests and integration/release review **before** merging a chain into production `main`.
- New code/experimental features remain opt-in. No livestream, account creation, external game purchase, moderator action, OS process manipulation or remote publication from an untrusted model prompt. Preserve rollback and audit trails.
- Never interpret app PCM queued, loopback samples, model speech text, avatar movement or an OBS test rendering as proof of human hearing. Require separate measured evidence for each.

## Reproduce this PR's offline boundary check

```bash
python3 -m unittest -q tests.test_stream_preplay_pcm_bridge tests.test_stream_preplay_gate tests.test_stream_director tests.test_stream_turntaking tests.test_stream_load_governor
python3 -m py_compile star/stream_preplay_pcm_bridge.py star/stream_preplay_gate.py tests/test_stream_preplay_pcm_bridge.py
git diff --check
```

These tests only exercise fake PCM and deterministic host leases; they do **not** prove the Windows host callbacks are independently trustworthy.
