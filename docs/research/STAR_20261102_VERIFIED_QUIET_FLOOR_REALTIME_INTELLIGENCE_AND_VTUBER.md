# Star AI: verified quiet-floor, natural VTuber conversation, and real-time intelligence
**Research/implementation date:** 2026-11-02 UTC
**Status:** offline-capable opt-in control implemented and tested; other proposals below are **not** deployed or measured.

## 1. Finding and reproduction: a gap in turn-taking evidence
`TurnTakingGate` previously returned `speak` after just one echo-cleared, 30 ms, zero-voice-probability VAD sample. It *also* returned `speak` when a guest voiced at monotonic 100 ms and one silent frame arrived at 600 ms, even though 470 ms of the interval was unobserved. That silence is an **assumption**, not captured evidence. At a crucial gameplay moment, this can allow Star to talk over a viewer or owner. The existing 350 ms hangover applied only to a remembered voice timestamp, not a verified continuous quiet window. These two baseline outputs were reproduced on the parent commit.

**Implemented in this change:** a separately approved `require_verified_quiet=True` mode for `TurnTakingGate.enable()`, exposed through `StreamInterruptionHost.enable()`.

* Needs **at least 350 ms of captured, echo-cleared, low-confidence-for-both-speakers quiet frames**, counting frame durations rather than unobserved gaps.
* Resets verified-quiet accumulation after >5 ms of missing capture; resets for uncertain voice probabilities (>0.10 for either speaker) and failed echo clearance.
* The last observed frame must be no older than **75 ms** at speaking advice. Existing 250 ms VAD-stale behavior remains.
* Preserves fast **120 ms confirmed owner barge-in**; speaking hints still do not stop the physical audio device or authenticate the owner. Hardware stop / animation flush / host authorization remain separate.
* Opt-in OFF by default; existing legacy hosts and their current tests keep their behavior. A production host should opt in and record its endpointing tradeoff on actual microphone traces before broadcasting.
* Never stores raw PCM, viewer identity, speech transcript or chat content. Never drives a game or starts a stream.

Tested adversarially: one-frame quiet, audio holes, echo uncertainty, ambiguous speech, ten-millisecond capture loss, late polling, ordinary sustained silence, owner interruption, and a genuine host->gate->stage arm sequence.

## 2. Why this should be measured against real conversations, not just test frames
End-of-turn is **not** identical to silence. LiveKit's maintained `eot-bench` explicitly optimizes the tradeoff between premature cutoffs and the delay after a genuine end of turn; its public English comparison at 5% cutoff reports **543 ms** for its hosted v1, **1,070 ms** for local v1-mini, and **1,600 ms** for a silence-only baseline (these are *benchmark policy results*, not measured Star performance). The models and their evaluation conditions may change; reproduce the comparison with a pinned dataset and versions.

Reference: https://github.com/livekit/eot-bench
Reference: https://docs.livekit.io/agents/logic/turns/turn-detector/

**Deployment experiment, not a feature claim:** Benchmark current heuristics vs. verified quiet vs. locally executable turn detector on consented, anonymized real audio from the target microphone/echo pipeline; evaluate English plus any supported languages. Store only aggregate false-cutoff rate, p50/p95 endpointing delay, false owner-interruption rate, and CPU cost. Set a lower false-cutoff priority for owner/guest conversation, but a shorter response-delay target for urgent, verified gameplay cues. A detector *cannot* establish who the authenticated owner is; that must be a trusted host identity decision.

### Candidate speech timing experiments
1. High-confidence local turn detector with independently measured microphone and playback echo suppression.
2. Streaming TTS with prosody and short interruptible clauses; host reports PCM samples actually played, not merely synthesized.
3. Separate attention channels: viewer chat can be deferred during difficult play, owner interruption can halt output, and game danger cues must be evidence-grounded.
4. A small fatigue-avoidance policy for gaps: once a sentence is interrupted, do not immediately restart the exact same sentence; ask or acknowledge only if the listener is done.
5. Respect *uncertainty* and natural silence: Star should not speak merely to fill every gap.

## 3. Real-time intelligence design: only slow down to get smarter when time allows
A game continues running while an agent thinks. The October 14, 2026 RealtimeBench work (180 continuously changing tasks across six game types) motivates a bounded **fast actor** + offline **slow teacher** with test-gated reusable lessons. Its published improvement (13.51 to 24.19 on a 0–100 task progress scale after two rounds) is a result in that paper, **not a Star game benchmark**.

Reference: https://arxiv.org/abs/2610.20665

**Target stack**, with independent owner toggles:
- **Fast reflex:** image/collision/position/state extraction and deterministic safe moves using a host-signed observation clock; reject input actions that exceed current frame age or come from the wrong game.
- **Tactical fast model:** bounded action horizon, small context, fixed time budget and verified input schema. Can decline an action when uncertainty is high.
- **Slow teacher:** episodic failure review with paused/local sandbox state, generates multiple strategy candidates, and tests on new maps rather than evaluating on its training examples.
- **Verified skill memory:** store provenance, game build, map, policy version, trial split, skill objective, and outcome. Promote only on held-out improvement without a regression in failure or resource use.
- **Cross-game transfer:** separate genre-level affordances (e.g., platformer jump timing) from game-specific mechanics. Never assume a remembered trick works in a different game.
- **Quality measurement:** 3+ distinct seeds/maps, no train/test contamination, win/progress metrics, invalid-action rate, observation-to-input p95, and no degradation during OBS/rendering.

Do **not** let model-generated descriptions authenticate screenshots, claims of wins, lessons, or hardware actions. The host/game runtime must attest observable outcomes. Multiplayer and online play require supported input methods and obey applicable game terms.

## 4. Performance strategy for two computers and an 8 GiB GPU
The strongest actionable speed improvements are workload placement and cache/latency measurement, not speculative unverified model claims.

**Inference:** benchmark ggml-org/llama.cpp's router, quantized small models, prompt-prefix KV reuse (`cache_prompt`), pinned cache keys where supported, and speculative decoding with a draft model. Compare cold and warm sessions and vary short/long prompts. The current llama.cpp server documentation describes common-prefix KV reuse and explicitly warns numerical outputs may differ by batch shape; correctness/regression tests must accompany speed tests.

Reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**Suggested experiments:**
- Protect OBS, game, and avatar VRAM first; move slow teacher, image indexing and batch training to Brain 1 when the live game runs on Brain 2. No GPU oversubscription without a measured safety margin.
- Use CPU speech/turn-detector candidates where their *actual* audio p95 and CPU load are competitive with the current stack. A tiny model is not necessarily a better voice.
- Profile end-to-end **capture → perception → decision → physical keypress**, and **viewer finish → first audible PCM**, plus OBS skipped/rendered frames. Tokens/sec alone does not establish good live behavior.
- Cache **stable** character instructions and game rule documents, not unverified live observations. Invalidate on game transitions, persona version changes, consent changes, and model updates.
- Admission controller prioritizes: hardware stop and owner barge-in > game action deadlines > active TTS/OBS/avatar > deferred explanation/teacher > offline experiments. Recovery probes during broadcasts must remain disabled.
- Use A/B runs on the same hardware/model with reproducible cold/warm samples, p50/p95 and answer quality; choose a candidate only if it improves one objective without violating constraints.

**Acceptance gate for actual speed claims:** one uninterrupted Windows nonbroadcast rehearsal with true game PID, OBS statistics, avatar renderer, AI backend, real audio playback and keypress acknowledgements, with full timestamps and GPU UUID checks. This run did **not** perform that rehearsal.

## 5. Humanlike **presentation**, not fabricated human identity
A believable Star should remember only verified experiences, have stable chosen hobbies and fictional lore *clearly identified as character lore*, react specifically to visible game events, show appropriately timed laughter/excitement, change facial gaze only from host-grounded visual targets, and speak naturally with true interruption support. The goal is high-quality *AI VTuber performance*, not a claim that Star is biologically human, conscious or the legal owner of accounts.

VTube Studio's plugin system supports custom parameters and injected Live2D tracking data, but correct model mappings, authenticated transport, neutral resets, and renderer visual review are still required.

Reference: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

Prioritize the next genuine milestones:
1. **Voice:** opt-in verified quiet floor + local EoT A/B in real recordings, then real PCM stop/flush evidence.
2. **Game playing:** supported local game with deterministic input capture and action deadlines; evaluate on held-out levels and genuine completion.
3. **Game building:** Roblox Studio implementation → Luau static checks → StudioTestService / multiplayer and avatar collision tests → captured visual inspection → repaired and re-tested build.
4. **Creator persona:** persistent but provenance-scoped event memory; explicit distinguishing lore vs observed facts; social continuity without retaining private viewer identities.
5. **Operations:** watchdogs, verified backups/rollback, resources by machine, prevent GPU identity aliases, failure-aware auto recovery only while idle.
6. **General knowledge:** approved-source retrieval first, cite provenance, abstain when absent; test recall across different project scopes and prevent any exposure of private notes during streams.

## 6. Honest limitations
Implemented: **only the new opt-in verified-quiet turn gate plus tests and host wiring**, not pretrained speech endpointing, gameplay mastery, new models, physical device control, improved general knowledge, OBS integration or 3D avatar rig. New unit tests demonstrate correct decisions on synthesized host frames and a simulated stage. They cannot measure real speaker identity, voice quality, game results, actual OBS stream performance, neural inference throughput, or the audible delay caused by a true microphone. Before enabling in public, evaluate calibration and genuine end-of-turn behavior on opt-in recordings, including noisy mic, music and gameplay audio.

Test command: `PYTHONPATH=. pytest -q tests/test_stream_verified_quiet_floor.py tests/test_stream_turntaking.py tests/test_stream_interrupt_host.py tests/test_stream_stage.py tests/test_stream_brain_governor.py`
