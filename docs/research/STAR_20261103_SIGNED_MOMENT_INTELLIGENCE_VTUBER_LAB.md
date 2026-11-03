# STAR — signed game-state memory receipts, intelligent gaming, and natural VTuber acceptance
Date: 2026-11-03 · Proposal: opt-in offline-first, owner-controlled, **no broadcast**
Status: receipt implementation and offline unit tests present on this branch; GPU, TTS, gameplay and OBS improvements below are **research proposals**, not measured capabilities.

## 1. The immediate provenance hole and what this patch actually changes

The stream journal previously relied on a caller-controlled `host_observed=True` flag. PR #934 closed per-game event-ID recycling after FIFO eviction, but it did not authenticate the source of a win, loss or checkpoint. Any component allowed to call that API with the flag could submit a structured victory without the game-state witness.

An **optional protected journal** now takes a 32+ byte host-owned secret and requires an HMAC-SHA256 `SignedGameMoment` for each new fact. The MAC covers:
* unpredictable 128-bit journal session ID, host monotonically increasing per-game event sequence;
* game/level scope and moment ID, outcome kind, exact binary64 event timestamp, and stage ID;
* a protocol domain/version constant to prevent reusing a token for a different purpose.

Validation happens **before** a rejected source can advance the journal clock or evict a legitimate memory. Valid but replayed/out-of-order sequence numbers fail for that game independently. Disable/enable rotates the session ID and clears the rolling memories and receipt high-water marks. Legacy unsigned mode remains compatible, is explicitly signaled in metrics, and must not be described as authenticated. Neither mode is proof that a game actually happened: if the host signer is compromised or signs a fabricated observation, HMAC will authenticate the false claim.

### Host-only integration example (do NOT expose key/signing function to an LLM)

```python
import secrets
from star.stream_episode_journal import GameMoment, StreamEpisodeJournal
from star.stream_moment_receipts import sign_game_moment

# Held in a trusted local game-observer process: never model-visible.
key = secrets.token_bytes(32)
journal = StreamEpisodeJournal(receipt_key=key)
journal.enable(owner_approved=True)
# The authoritative game-state callback must produce the structured fact.
fact = GameMoment("evt_0042", "private_test_game", "checkpoint", 100.0, "room_2")
proof = sign_game_moment(fact, session_id=journal.session_id, sequence=42, key=key)
accepted = journal.record(fact, now_s=100.1, host_observed=True, receipt=proof)
assert accepted
```

`sequence` must come from a trusted per-game observer counter, **not** from chat messages or model text. Do not embed the signer in prompt tools. Keep the secret only in the authorized host; rotate/recreate on process restart. HMAC attests source and integrity, not physical truth, process isolation, OBS state, or permission to speak. Use a Windows sandbox/private self-owned test game first. Subsequent host hardening: protect the signing key from child workers; bind receipts to pinned process identity and game capture epoch; add independently sourced win/state signals and audit delivery gaps. Never allow a signing callback directly callable by the model.

## 2. Architecture: make Star better, not just faster at generating text

**Fast lane (target 5–15 Hz game decisions, tuned by real deadlines):**
changed-region screen capture -> lightweight scene/danger detector -> state cache/short horizon -> game-rule and input permission gate -> bounded action -> independently observed game-state result. Do not run a full long-reasoning model for every frame. Abort stale model responses after a changed scene, elapsed action deadline or focus revocation.

**Teacher lane (off stream, owner-authorized):**
replay independently verified failures -> create 4–8 action/strategy candidates -> run candidate policies in a deterministic test game/Roblox Studio lab -> compare with matched baselines using actual task completion, resource consumption, and game-side action receipts -> promote only statistically supported improvements. Avoid training on the exact holdout level used for validation. Bad or duplicate episode data must never masquerade as learning.

**Experience/memory lane:**
short-term context for exact current game, verified factual journal for the session, and user-approved long-term skills/knowledge with citations and provenance. A stream persona can express enthusiasm or frustration as a character without falsely claiming a human body, emotional consciousness or real-world personal experiences. Model-generated dialogue is not a trusted game observation.

Why this split: Voyager's skill library/automated curriculum motivates composable tested macros, while OpenGameEval directly demonstrates the benefit of inspecting relevant Roblox scene objects before editing them. Proact-VL motivates *deciding whether to speak at all* based on live gameplay evidence rather than continuously narrating.

## 3. CPU/GPU and latency experiments for 8 GB gaming cards

Do not assert a 50+ tok/s result for Star without a local matched test. A quantized model may fit for one context and spill at another; GPU VRAM, draft model overhead and concurrent OBS/game workloads change the result.

Run a paired, reproducible matrix with the *same* fixed game, prompts, context lengths, chat replay, FPS cap and OBS scene:
1. Small fast real-time model vs slower teacher; test p50/p95 **correct action deadline** and actual success, not only tokens/sec.
2. Plain decoding vs llama.cpp prompt caching / speculative decoding using SPEED-Bench; report prefill time, time-to-first-token, tokens/sec, acceptance, VRAM peak and regressions. Speculative decoding can be slower for high-entropy outputs.
3. 4k, 8k, 16k and 32k effective context with retrieved project facts; isolate cache-hit and offload behavior.
4. Single GPU game+model+OBS vs GPU game+model with Pocket TTS on CPU; audio first-chunk and first-*audible* packet, FPS 1% low, encoder lag, dropped frames, microphone/virtual-audio loopback latency, power/CPU saturation. Pocket TTS v4.0.0 introduced small 18M/7M/2M English model variants on 2026-10-20. Their vendor-level speed claim must not be mistaken for measured Star speed.
5. Bench 3060 Ti and 4060 separately if physically available; pin process/GPU ID so evidence cannot silently switch devices. For each run include baseline, changed version, confidence interval, rollback and explicit hardware snapshot.

Design principle: the only useful speed increase is one that improves **completed correct decisions before the game's deadline** without degrading game FPS, stream health or voice conversation.

## 4. Making Star a believable and enjoyable AI VTuber

**Timing and dialogue.** Combine speech activity detection with end-of-turn detection. Let viewer or co-host turns take priority, use meaningful silence, and explicitly separate tiny backchannels ("mm-hmm") from actual interruptions. LiveKit's docs note adaptive interruption is cloud-dependent; for local-first prototypes use VAD plus an offline turn-taking evaluator instead of assuming unavailable cloud behavior.

**Proactive yet grounded.** Maintain a small set of host-observed game events. For each candidate, decide `speak / respond / ask / stay silent`; measure too-frequent comments, redundant victories, unsupported claims, interrupted viewer questions, and stale comments. Track game/outcome confidence *before* TTS. Prevent fictional long-term memories.

**Expressive production.** Drive speech, avatar lip sync, blinking, gestures and camera movements from actual utterance playback timestamps, not merely TTS text generation completion. Idle playfulness, twin-tail hair physics, and natural reaction animations can be creative persona choices, but must not steal GPU/CPU from the running game. Keep Star/Astro/Amber interactions grounded in explicit current scene state; don't invent actions they never performed.

**Identity and trust.** Stream clearly labeled as AI. Be conversational and personable, but do not impersonate a real human, claim private relationships, leak viewer data, or fabricate achievements. Keep content moderation and emergency mute/stop outside Star's LLM.

## 5. Roblox creator and general-knowledge capabilities

Implement an inspect-first Studio executor: inspect touched objects, code, networking and runtime before modifying; propose multiple candidate changes; validate Luau with offline linters plus Studio play tests; include multiplayer server/client tests, physics/collision checks, screenshots and input traces. Keep authoring and evaluation fixtures separately controlled. OpenGameEval publishes executable stateful Studio evaluations and highlights materially better outcomes for inspect-before-edit behavior.

For general knowledge, use versioned source retrieval with small cited chunks, explicit timestamps, separate owner-verified facts from model hypotheses, and avoid adding web content to executable permissions. Learn from *verified* tests, not from self-scoring or synthetic praise.

## 6. Acceptance and sequencing

**Already verified in this branch:** the optional receipt protocol and protected journal reject altered field, wrong key, wrong session, same-sequence replay, out-of-order receipt, mismatched scope, and unauthenticated time poisoning. All checks are offline simulation; no real game source was contacted.

**Next P0 (not done):** a nonbroadcast Windows test-game rehearsal with an independent observer/signing process, game-side input acknowledgement and process-watchdog key release. Give each completed game action a host-produced receipt, then connect game event -> signed journal fact -> proposed commentary -> synthesized PCM -> actual audio playback witness -> avatar animation receipt -> OBS read-only health. No gameplay or live stream should be triggered by test setup.

**Targets, not results:** zero unsupported on-air wins in adversarial fixtures; zero unsigned accepted facts in protected mode; no safety/control failures; p95 short reactive turn under 1s audible where feasible; no newly dropped OBS frames vs baseline; game FPS 1% low not degraded beyond agreed margin. Run A/B across at least three varied game types and multiple seed levels. Do not declare "human-like" based on text chat alone: assess audio timing, interruption handling, appropriateness, avatar sync and long-term factual consistency.

Keep this change as a **draft stacked PR based on #934**. Main must not be modified or automatically merged.

## Primary references checked 2026-11-03

- Roblox OpenGameEval project and executable scene/play tests: https://github.com/Roblox/open-game-eval
- October 1, 2026 OpenGameEval paper: https://arxiv.org/abs/2610.02563
- Microsoft Research Proact-VL (ICML 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- Voyager — open-ended curriculum and skill library: https://voyager.minedojo.org/
- LiveKit turns and interruption handling: https://docs.livekit.io/agents/logic/turns/
- LiveKit June/July 2026 interruption guidance: https://livekit.com/blog/turn-detection-and-interruption-handling
- llama.cpp SPEED-Bench README: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp issue documenting speculative decoding being slower on some text categories: https://github.com/ggml-org/llama.cpp/issues/23052
- Kyutai Pocket TTS v4.0.0 release (October 20, 2026): https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0
