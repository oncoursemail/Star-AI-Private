# Star AI — trustworthy engine telemetry, low-latency intelligence and natural gaming VTuber

**Engineering entry:** November 3, 2026. **Change:** new bounded authenticated game-state ingestion module plus adversarial offline tests. All external model, speech and stream capabilities below remain research or proposed experiments unless marked as implemented.

## 1. New bridge: preserve the source-to-outcome trust boundary

Prior work on branch `feat/star-verified-telemetry-20261103-auto34` could corroborate state transitions and sign journal entries, but `VerifiedGameStateObserver.ingest()` accepted a Python `GameStateSample` from any caller. That **does not authenticate the origin**. It would be unsafe to expose this API directly to a model, screenshot reader, ordinary client-side Roblox script, viewer text, or a publicly accessible endpoint.

This change adds `star/game_telemetry_source_bridge.py`:

1. Accept a strictly bounded (512-byte) UTF-8 JSON frame containing only version, approved source ID, journal session ID, contiguous sequence, world frame, round, phase, checkpoint and HMAC-SHA256. No captions, usernames, arbitrary chat, paths or other metadata can be present.
2. Check duplicate keys, exact field set, integer types (including rejection of booleans posing as integers), strictly monotonic sequence and canonical MAC. The MAC covers **every game-state field**, source ID and fresh journal session.
3. Only after verifying the source authentication, feed `GameStateSample` to the prior `VerifiedGameStateObserver`; a baseline, observed state change, and subsequent corroboration are required before an event is emitted.
4. Forward the witnessed, separately journal-signed `GameMoment` into `StreamEpisodeJournal`, whose session signature and replay fences remain authoritative. A recorded event is an **unspeaking private memory suggestion**, not OBS output, a success metric or direct permission for Star to narrate it.
5. On malformed input, replay, sequence gap, lost server/observer continuity or journal refusal, irrevocably stop the bridge **and clear the connected journal**. Reconnection needs fresh owner approval, journal session, and external source-key material. All functionality is disabled by default.

### Wire contract for an owned-game or Studio test-server signer

The JSON object is `{"v":1,"source":"studio_server_test","session":"<32 lowercase hexadecimal chars>","seq":1,"frame":1,"round":1,"phase":"playing","checkpoint":0,"mac":"<64 lowercase hexadecimal chars>"}`. MAC input is ASCII `json.dumps(("star.game.engine-telemetry.v1", source, session, seq, frame, round, phase, checkpoint), ensure_ascii=True, separators=(",",":"))` and tag is `HMAC-SHA256(SOURCE_KEY, mac_input)` in lowercase hex. Each session starts at sequence 1; no skipped, reordered, repeated or reset sequence is accepted. This is a **protocol**, not permission to install code in another game's server.

**Deployment isolation is essential:** the source signer belongs in an independently trusted owner-controlled game/server-side test host. Keep `SOURCE_KEY` separate from the journal receipt key, memory-isolate both from LLM workers, and authenticate the IPC peer's process/server identity at the operating-system boundary. Roblox Studio plugins and local test clients should never inherit server signing privileges. A compromised source can sign lies; HMAC is *origin authentication*, not proof the underlying gameplay happened. The current code is a pure receiver with **no real game connection, IPC server, process attestation, keyboard injection, OBS, voice, video or broadcast**. It is not ready for an untrusted multiplayer game.

**Offline proof:** `pytest -q tests/test_game_telemetry_source_bridge.py tests/test_game_state_transition_witness.py`; tests include genuine checkpoint/win/loss transitions, maliciously altered phase/score, forged MAC, different signed source, old sessions, duplicates/gaps, unrecoverable stopped observer, malformed JSON with duplicate fields, size caps, and simultaneous packet replay.

## 2. Highest-value next engineering step: genuine nonbroadcast integration

A real rehearsal is a *composition* of independently owned host interfaces, not a model self-report:

```text
Owned offline game/Studio server [engine-owned state] --(separate source HMAC / authenticated IPC)-->
Trusted read-only bridge --(strict parsed world frames + independent clock)-->
VerifiedGameStateObserver --(journal HMAC receipts)--> private memory
  |
Host-only strategy / input controller: bounded game leases + OS focus + watchdog + action ACK
  |
Host-only OBS read-only session: not streaming, not recording, no outbound broadcast
  |
Speech/audio/avatar timing observer: PCM actually played + motion actually rendered
  v
Independent run report: held-out objective progress, deadline success, jitter, FPS, OBS drops,
source freshness, voice latency, synchronized mouth motion, human reviewer preference.
```

Implement the isolated source signer in an owner-approved **deterministic offline test game** first. Authenticate its process identity across restart, use a nonce-bound session handshake instead of writing keys to disk, and enforce loopback-only IPC with process ACLs. Validate the server's declared frame number against the *actual* game-clock advancement. Test a game crash during a key hold, signer restart, OBS reconnect, stale states, invalid key-up acknowledgment, a chat message saying "you won", and network/IPC backpressure. If any gate fails, neutralize input and audio, revoke the experiment, retain a private sanitized failure report, and never start a stream. Windows watchdog recovery is only best effort; it cannot promise hardware-level key-up.

The new bridge is not a complete isolated source connector; do **not** treat its passing synthetic unit tests as a live Windows game win.

## 3. Actually faster Star: measure scheduling before rewriting the model host

**Goal:** maximize *useful, correct, on-time game actions and natural conversational turns*, not tokens/second in isolation.

Separate work into three deadline lanes, rather than running the same large model for all actions:

| Lane | Suggested initial experiment | Admission rule | Measurable metric |
| --- | --- | --- | --- |
| **Reflex / action** | deterministic short movement/evade/stop policies fed by fresh game state and VLM detections | game focus + OBS clean + input watchdog; hard deadline | p95 action latency, missed-deadline rate, actual progress |
| **Tactical** | small quantized local reasoning model, cache stable context, brief structured skill retrieval | free VRAM after game/OBS/desktop reserve; pause if graphics spikes | p50/p95 TTFT, strategy success on held-out seeds |
| **Teacher / creator** | larger model or parallel candidate generation for offline failure analysis, Roblox playtest/build iteration, general research | use idle time off-stream; never starve input/speech | independently verified new tasks, rejection/rollback rate |

This architecture avoids frequent GPU memory churn; the actual reserve must be measured on each 8 GB GPU, not assumed. For each candidate change, run matched hardware+seed workloads with at least five independent replicates and use p95 TTFT, p95 input-to-world-action latency, audible-first-chunk delay, 1% low game FPS, VRAM peak, thermal/power budget and OBS dropped frames. Add a negative control in which model speed improves but gameplay outcomes degrade; the promotion gate must reject that "optimization". Evaluate prompt-cache hit rate and speculative decoding **separately**, since both can regress under short variable game prompts.

**Profiling decision:** Rust/native work is justified for proven hot paths such as frame transport, audio ring buffers and fixed-format IPC; it does not automatically accelerate GPU token generation. Do not trade reproducibility for a premature full Rust rewrite.

## 4. Teaching Star to genuinely learn games

Start with deterministic locally owned benchmarks and build an independent trial table: `(game build hash, seed, state source ID, policy/model ID, allowed actions, deadline, objective, measured outcome, observation hash)`. Give Star a *teacher* that generates harder challenges from her *verified* failure modes, but enforce a sealed held-out set of seeds/levels so self-generated training footage cannot contaminate validation.

Train in a progression: game camera and movement -> platforming/object collection -> temporal planning -> puzzles -> cooperative communication -> dynamic play and transfer. For each skill store (a) triggering conditions, (b) resource/latency budget, (c) evidence IDs for positive and negative trials, (d) side effects, (e) rollback version. The model can propose skills; a different host must test and qualify them. A high "win rate" based on screenshots or model narration is not independently verified progress.

**Roblox game creation** should use Studio's built-in MCP and StudioTestService where supported, with read-before-edit, multi-client scenarios, test assertions, and visual/physics checks. Make 4–8 candidate patches only when bounded by hardware and task time; compare tested outcomes rather than code aesthetics alone. Never equate a successful Luau syntax check with a good playable game.

## 5. More natural and entertaining VTuber behavior, without fabricated humanity

Evidence-based character continuity will be more convincing than perpetual scripted chatter:

- Keep separate **private real-world facts**, **public safe summaries**, and **fictional character lore**. The character can have favorites, evolving hobbies, tiny jokes, Astro/Amber chemistry, and expressive mannerisms; she should never portray fictional in-game achievements as observed experiences.
- Adopt a deliberate `listen -> plan -> speak -> yield / be interrupted -> resume / silence` turn policy. Trigger spontaneous reactions on real game changes, let viewers complete a thought, interrupt only for high-salience events and handle audio cutoffs without repeating whole sentences.
- Sync her mouth to **audio actually played**, and eyes/emotions to observed context. Do not infer speech just because TTS was requested. Sample actual PCM output and rendered avatar timing separately; a model's "I'm talking now" is not evidence.
- A small local CPU TTS (Kyutai Pocket TTS 18.2M / 6.9M / 1.9M) is a *candidate* for preserving VRAM during gaming, not demonstrated to match voice quality. Blind-review sample expressiveness, pronunciation and avatar sync as well as first-chunk latency before switching voices. Keep virtual microphone routing isolated from private system/game audio.
- Give Star a protected "quiet mode" when concentrating, humane recovery and idle routines, a session retrospective with real improvement goals, and a short scripted AI identity disclosure for new viewers. Human-like performance should not rely on misleading viewers that she is biologically human or conscious.

### Research references checked November 3, 2026

1. **Microsoft Proact-VL (ICML 2026)** — real-time video agents for *when* to speak, not only what to say: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ ; code: https://github.com/microsoft/AnthropomorphicIntelligence
2. **Kyutai Pocket TTS** — October 20, 2026 v4.0.0 small CPU models, explicit language IDs and streaming: https://github.com/kyutai-labs/pocket-tts/releases . Reported performance is upstream hardware/data, **not Star measurements**.
3. **Roblox StudioTestService** — official multi-client and plugin automation API: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
4. **Roblox OpenGameEval** — execution-based agent evaluation for Roblox game building: https://github.com/Roblox/open-game-eval
5. **llama.cpp** — configurable inference, prompt caching and decoding; benchmark on actual system: https://github.com/ggml-org/llama.cpp
6. **VTube Studio** — official plugin API for avatar control (requires authorized local connection): https://github.com/DenchiSoft/VTubeStudio/wiki

## 6. Promotion checklist

| Deliverable | Current claim |
| --- | --- |
| Signed source-frame parser and independent origin MAC checks | **New offline-tested code** |
| Disallow source replay, schema pollution, stale observer and misleading memory after failure | **New adversarial tests** |
| Trusted source/engine plugin, isolated IPC and OS process identity pin | **Not implemented** |
| Real authorized Windows game and OBS preview | **Not verified** |
| Speech, mouth shape and gaze synchronized to audible PCM | **Not verified in this change** |
| Measured higher model intelligence, win rate or inference tokens/second | **Not measured** |
| Autonomous public broadcast | **Not authorized or started** |

Keep this change on a draft stacked PR for review. **No main-branch merge, autonomous public streaming, new secret creation or third-party game action is implied.**
