# STAR AI — Verified local inference, real-time game intelligence and humanlike VTuber engineering
**Research and implementation note | November 2, 2026 | Draft PR (no deployment)**

## Why this particular correction matters
Raw tokens/second cannot measure intelligence, and an incomplete response cannot be a successful low-latency inference. STAR's existing offline synthetic benchmark accepted locally fabricated negative latency, negative token counts, invalid success types, missing canary verification, and length-truncated responses as nominally successful. Its streaming benchmark could accept contradictory visible-output / canary-status reports. The test harness therefore risked claiming faster AI, safer model cache reuse, or quicker speech startup without adequate evidence.

### Reproduced and corrected
- Before patch, four adversarial invalid-measurement cases failed (they were accepted), and a separate red test showed a completion with `finish_reason="length"` counted as a successful, fast response.
- Add strict bounds and types for `Probe` records; reject invalid opaque case IDs, contradictory `ok/canary_ok`, invalid wall time, and an unverified successful canary.
- Require explicit `finish_reason="stop"` before a response contributes to local completion throughput. A shortened, tool-diverted or unverified completion must count as failed, not as a “performance win.” This is especially important when choosing a model for in-game comments or time-critical reactions.
- Check `StartupProbe` reports: success requires visible text; a canary match must correspond to success, a mismatch to a mismatch status, and a canary workload cannot report success without positive verification.
- No model is launched, no keys sent, no OBS stream started, no learned model promoted, and no additional owner permissions granted by these changes.

**Scope:** These are accuracy/integrity fixes for *measurement and selection*, not an observed speedup or stronger pretrained model. A separate true-quality evaluation remains mandatory. The static canary merely identifies one class of response reuse, not overall correctness.

## Architecture: the fastest usable local intelligence, not misleading raw speed

1. **Real-time reactive branch:** Reuse the existing `game_deadline_router.py`, `game_realtime_loop.py` and `game_action_gate.py`. Run an owner-approved validated small policy on a fresh trusted game frame. The response must fit remaining scene lifetime including host input release reserve. Expire and discard after scene changes. Keep worker termination proof, per-game scope, focus, action allowlists and physical key-up as independent host gates.
2. **Tactical branch:** Use retrieval of verified game mechanics, visible goals, current HUD/state and short-horizon predictions. Avoid invoking a slow general model on every frame. A safe "no action" is preferable to an out-of-date hallucinated input.
3. **Offline teacher:** Only between episodes and with authorized compute headroom. Create alternative strategies (Best-of-N), execute against a private simulator/test map, compare matched held-out seeds, track confidence and regressions, and retain only verified summaries. The `game_learning_ladder.py`, `gameplay_skill_bank.py` and `game_skill_gate.py` already cover separate pieces; integrate without bypassing human approval/holdouts.
4. **General knowledge:** Keep factual retrieval separate from persona and gameplay reports. Use source/date/provenance/visibility checks and uncertainty. Recent viewer claims and screen text must remain untrusted data and cannot authorize browsing, purchases, code execution or account operations.
5. **Resource-aware local serving:** Benchmark fixed model/GGUF/quantization/KV-cache build and prompt distribution. On an 8 GiB GPU, avoid assuming that a nominal Q4 checkpoint fits at *actual concurrent* game, avatar and OBS demand; measure peak VRAM headroom, prefill latency, p95 first usable output, p95 complete, tokens/s and failure rate. Compare CPU TTS to GPU TTS under identical concurrent gameplay. Do not replace model options based on idle synthetic numbers.
6. **Speculation and prefix reuse:** Use llama.cpp's actual server-side SPEED-Bench to measure draft acceptance and per-category throughput, and vary cold/warm prompts, prefix reuse, context lengths and concurrency to reveal cache effects. Require zero wrong unique canary outputs across long↔short slot cycles; investigate mismatches rather than optimizing around them. A high draft acceptance rate is not a guarantee of correctness.

## VTuber: believable expressive interaction while transparently AI

STAR should build an emotionally coherent *character presentation* through stable interests, preferences, cadence, self-reflection notes, and genuine shared gaming experiences, without asserting unverifiable subjective consciousness or fictional human-life memories as facts. Her streaming persona should stay warm, playful and sometimes quiet. She should apologize for mistakes without circular repetitive phrasing; acknowledge actual game-state events and celebrate only independently attested wins.

- **Turn-taking:** Simultaneously optimize listener interruptions, false end-of-turn cutoffs, and actual first audible PCM, not first token alone. In LiveKit's English EOT evaluation the reported 5%-false-cutoff operating-point delay was 543 ms for v1 vs 1070 ms for v1-mini. These are external benchmark results, *not* STAR measurements. Evaluate CPU cost on STAR's machine and acoustic conditions (laughing, quiet speech, game audio).
- **Voice:** STAR already has an opt-in `voice/pocket.py` streaming adapter. Kyutai's October 2026 Pocket TTS variants have 18.2M/6.9M/1.9M parameters and CPU orientation; published CPU speed is not proof of better end-user prosody. Compare speech intelligibility, expressive variation, pause placement, word-level pronunciation, CPU contention, generation-to-playback lag, p95 first audio, and user listening preferences.
- **Avatar stage:** Use actual device playout clock, not generated PCM duration, to drive mouth and eye expressions in VTube Studio. Behavior should be event-conditioned (surprise at real danger, relief after a proven success, concentrated silence during difficult movement), with cooldowns to prevent repetitive gestures; accommodate reduced-motion preferences.
- **Streaming social life:** Make reactions specific to the current game; keep viewer attention fair rather than rewarding spam, remember only properly scoped host-confirmed memories, and avoid mirroring viewer private chat into public output. Build Astro/Amber interactions as scripted/opt-in character moments without disguising them as independent humans.
- **End-to-end rehearsal:** First do a **nonbroadcast** Windows run with game + inference + physical speaker + avatar + OBS monitoring. Record anonymous latency histograms, audio underruns, encoder skipped frames, game FPS and false conversational cutoffs. Never claim on-air streaming from simulation.

## Roblox game creation: verify the outcome, not just generated code
1. Inspect project hierarchy, game state and relevant scripts before editing. Roblox OpenGameEval's 2026 benchmark reports that exploration of touched objects before modification correlates with success, and evaluates edits *and play mode* with executable checks.
2. Generate limited candidate variants in isolated scenes; validate Luau syntax/strict analysis, asset references, collision bounds, required connections and safe object sizes, plus UI readability and keyboard/controller use.
3. Run official Studio test automation: multiple private clients, state replication, ragdoll/physics and network-latency simulation, death/respawn, race conditions, gameplay exploits, checkpoints, accessible UI and perceived animation quality.
4. Apply semantic minimal diffs, store independently verified artifacts/replay evidence, rollback on regressions, and assess generalization on games/maps not seen during strategy development.
5. Explain exactly what was generated, inspected, run, and *not* verified. Testing a stub simulator does not establish that Roblox Studio or an actual player session succeeded.

## Concrete benchmark matrix and acceptance criteria
- **A/B design:** Identical pinned model file hashes, endpoint settings, quantization, context size, stream concurrency, random seed where available, and *fresh* vs cached prompts. Use at least short chat, long-context, code, game reactions and reasoning workloads; report per-category not only pooled average. If the A/B protocol is changed mid-experiment, label it exploratory.
- **Transport integrity:** Zero silent truncation; every counted completion requires explicit `finish_reason="stop"`. Canary mode must observe exact distinct tokens, zero mismatches and zero unverified successful rows; all incomplete or canceled streams count as unsuccessful rather than fast.
- **Latency:** Report request arrival to first visible token, first speakable phrase, first *audible* device sample, completed response, and p50/p95/tail. Preserve failed and timed-out requests in the denominator.
- **Game value:** Compare scenario-matched action success, win/progress, p95 dispatch latency, deadline misses, and held-out unseen maps, with independence assumptions and repeated testing documented. No statistical gate can authorize an unreviewed autonomous model update.
- **Streaming quality:** At matched gameplay load observe OBS skipped/lagged frames, VRAM peak, game FPS, turn-taking overlap/false interruptions, audio gaps and avatar lip sync. Favor reliable 60 FPS play plus naturally paced voice over a faster benchmark that destabilizes OBS.
- **Publish gates:** Owner-authorized devices and private games only; no broadcast, account spends, external game chat or autonomous code promotion without explicit separate host controls. New features default OFF; verified code review/CI before merge.

## Technical sources and dates (verified November 2, 2026)
- ggml-org, **llama.cpp SPEED-Bench server benchmark**, OpenAI-compatible llama-server, speculative decoding, draft acceptance and concurrency: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- ggml-org llama-bench and inference benchmark utilities: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench
- LiveKit, **eot-bench** model EOT false-cutoff/latency Pareto evaluation: https://github.com/livekit/eot-bench
- Kyutai, **Pocket TTS**, October 2026 smaller model options: https://kyutai-labs.github.io/pocket-tts/ and https://github.com/kyutai-labs/pocket-tts
- Roblox, **OpenGameEval** 2026, stateful Studio automated evaluations: https://github.com/Roblox/open-game-eval
- Roblox, developer test/simulation documentation: https://create.roblox.com/docs/studio/testing-modes
- VTube Studio official API/plugin guide: https://github.com/DenchiSoft/VTubeStudio/wiki
- STAR's existing components: `star/inference_benchmark.py`, `star/inference_stream_benchmark.py`, `star/game_realtime_loop.py`, `star/game_learning_ladder.py`, `star/game_skill_gate.py`, `star/stream_director.py`, `star/stream_episode_journal.py`, `star/voice/pocket.py`.

**Next milestone:** connect verified completed-inference and first-audible counters to an actual Windows nonbroadcast session, without relaxing game-action or stream authorization. This document is a design/evidence roadmap; new integrations beyond the measurement fix remain *not implemented*.
