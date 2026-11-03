# Star AI: authoritative game-engine telemetry + real VTuber intelligence roadmap
**Research and implementation date: November 3, 2026.** This is a **development design**, not a completed live-game, OBS, Windows or voice demonstration.

## 1. What changed in this PR and why
PR #940 added a verifier that accepts a HMAC-authenticated engine frame and requires a corroborated state transition before a private streaming memory can be formed. PR #941 added capture-to-action deadline evaluation. A **real source-side packet generator** was missing: its tests built signed packets by hand. This change adds `star/authoritative_game_telemetry_source.py`, using the bridge's actual canonical MAC format, source/session pinning, strictly increasing frame numbers, and a live engine-reader callback.

`AuthoritativeGameTelemetrySource.poll()` emits one **512-byte maximum** v1 JSON packet. Only an independently trusted engine-owned callback (returning `GameStateSample`) can supply state. An invalid or stalled sample revokes that source instance, rather than emitting a guessed win. The source can sign up to 4,096 observations in a session; no wraparound or implicit restart. No automatic network listener, model tool, Windows input, OBS control, file storage, or secret printing is added.

**Integration path (engine host and receiver are distinct processes):**

```text
owner-controlled game/test engine ─ authoritative reader callback (private)
        │
        ▼
 AuthoritativeGameTelemetrySource (private SOURCE_KEY, never model-visible)
        │ canonical v1 bytes, distinct process; OS-local authenticated IPC needed
        ▼
 AuthenticatedGameTelemetryBridge (source MAC, session/seq, fail closed)
        │
        ▼
 VerifiedGameStateObserver (initial + transition + corroboration)
        │ privately signed moment, distinct MOMENT_KEY
        ▼
 StreamEpisodeJournal (no on-air speech authorization)
        ├── verified self-play learning / skill bank (separately evaluated)
        └── grounded on-air reaction director (separate broadcast permission)
```

**Contract:** the engine is trusted, not simply an AI generated screenshot/description. The two signing keys MUST be independent and secret; supply them through a deployment secret manager, not files in Git. Keep both host processes isolated from inference workers, viewer chat, mod/plugin executors and Roblox clients. Never expose a callable signing operation to a model. A forged downstream packet fails MAC validation; a *compromised game engine itself* can still sign false facts. Neither this implementation nor HMAC proves reality without an independently trusted engine. The receiver only attests what the source claims.

**Minimal host-side sketch** (must be deployed in a private game-owner process, not a model tool):

```python
# CODE EXAMPLE ONLY; requires an owner-controlled engine's real read_game_state()
producer = AuthoritativeGameTelemetrySource(
    source_id="studio_server_test",
    session_id=journal_session_id,  # from owner-approved receiver handoff
    source_key=private_engine_key,
    trusted_reader=read_game_state,  # -> GameStateSample from game engine
)
producer.enable(owner_approved=True)
frame = producer.poll()  # host must transfer over pinned local IPC
# In receiver process: bridge.accept(frame)  # returns private signed event or None
```

A production coordinator MUST stop both sessions if **either** side fails delivery, consumer receipt, read timeout, game focus or authorization. Blocking callbacks require an independent process-level deadline: Python cannot kill a hung game engine callback. Treat packet creation as consuming a sequence number even when transport fails; **never retry the same session as though an omitted packet never happened**. The source/bridge cannot run in the AI inference process and is not a public OBS automation tool.

## 2. Real-time gaming intelligence: what to build after this

### A. The minimum playable loop (a controlled game)
1. Run a small owner-created test game exposing authoritative `frame`, `round`, `phase`, `checkpoint` from **server-side** engine state. In Roblox, use server-side plugins/TestService or a private game server. Never use an untrusted Roblox client as the source of truth.
2. Put the signing host and bridge/witness in different restricted OS processes. Authenticate the OS-local pipe peer and prevent the inference model from choosing file paths, source keys or source ID. Packet MAC **does not** authenticate the transport peer.
3. Connect the existing approved Windows game capture + guarded action permit + independent input watchdog to the same game/round and host-monotonic clock. Require an independently confirmed key-up. Only authorize **nonbroadcast** trials.
4. Record capture, transfer, preprocessing, inference, dispatch, game-world frame progression, OBS dropped frames, game p99 frame time and audible audio first-chunk time in the same trial. The November 1, 2026 GameScaling correction explicitly shows why inference-only timing is misleading.
5. Evaluate matched baseline/candidate episodes with randomized ordering, varied seeds and **unseen** holdout games. Compare wins/progress/valid actions, deadlines and QoS. Do not select improvements on a public leaderboard alone.
6. Add a physical, operator-run Windows acceptance checklist. No model may claim its own test succeeded; no stream starts from a passing offline report.

**Current throughput limit:** 4,096 packets/session. At 20 fps that is ~205 s, so it is *not a long-duration livestream connector*. Extend with an authenticated, independently acknowledged epoch rotation protocol (fresh IDs/keys, clear observer/session boundaries, no replay of old wins) before long streams. Never silently reset seq to 1 or reuse a journal key.

### B. Faster AI on an 8 GB card without compromising the game
- **Real-time reflex lane**: cheap key/scene policy or compact vision-action model; do not wait for long text completions on dodge/turn decisions.
- **Tactical lane**: short bounded reasoning when action deadlines allow; reject stale frames. Dynamic frame sampling based on motion and danger, not rigid screenshot spam.
- **Offline teacher lane**: after an attempt, run heavier reasoning, replay criticism, multi-candidate fixes and private evaluation; distill only verified improvement into a small action policy. This does not mean the model weights improve automatically.
- **GPU budgeting**: protect game rendering and OBS first, leave free VRAM headroom for encoder/vision buffers, use CPU speech if a voice-quality test passes, and run heavy learning/video generation off-stream. Compare actual GPU residency and p95 end-to-end action time rather than asserting a quantization will fit at all contexts.
- **llama.cpp tests**: compare baseline decoding against prompt-prefix reuse, low-overhead speculative n-gram candidates, and separate small draft models on the exact chosen binary, prompts, context lengths and GPU. More speculative tokens can be slower.
- **Important upstream caution:** reports in August and October 2026 describe cross-slot prompt-cache reuse and multi-second idle-slot saves under some llama.cpp configurations. They are issue reports, not proven universal regressions. Until evaluated and isolated, do not share an untrusted viewer context's cached state with a private memory or model tool session. Use separate processes or per-trust-context caches for sensitive work and test cache correctness under concurrency.

### C. Star learns games instead of merely memorizing them
`GameScaling` studied 80-game continued pretraining and showed that diversity of game experience matters for related unseen games; far-shifted 2D/2.5D transfer remains challenging. Prioritize **observable skill progression**: create reproducible training/validation/test seeds, collect trustworthy engine outcomes, generate harder tasks automatically, attempt them, validate independently, and only then add a lesson. A game-specific trick is not general intelligence. For Roblox use Studio's built-in MCP server, project-tree inspection, automated playtests, `StudioTestService` multiplayer tests and screenshot/physics checks to validate games Star creates.

The learning library should store:
- Game version, scenario and exact action-policy build identifiers; **no** unstated cross-game generalization.
- Independently observed outcome and confidence; failures and counterexamples are first-class lessons.
- A compact "why this worked" skill recipe, replayable tests, expiration/retest schedule, source provenance and rollback.
- Private training splits separate from blind holdouts; avoid training on evaluation answers.
- Safety and permissions: only automate games where permitted; no unauthorized online matchmaking, anti-cheat bypass or public player harassment.

## 3. A natural, expressive, but genuine VTuber
Naturalness comes from response timing and consistency as well as voice. Star should be clearly disclosed as an AI rather than pretending to be a human. She can maintain a stable character identity, preferences, hobbies and remembered **verified** experiences, without claims of literal human consciousness.

**On-air scheduler (next integration):** game danger and real owner interruptions preempt commentary; viewer questions win over routine low-stakes narration; suppress stale or repetitive events; silence is a valid action. Keep an explicit speech queue with cancel/physical-audio-stop acknowledgments. Use measured first audible PCM timing and voice activity rather than token emission to measure response speed. Drive mouth and face from actual audio envelopes/phoneme time where available, not only scripted emotions. Add blink, gaze and idle movement with moderation of repetitive loops; respect reduced-motion and moderation policies.

**Model candidates:** Microsoft's `Proact-VL` investigates continuous video understanding and proactive speaking decisions, useful as **research inspiration** but not a drop-in Windows controller. Kyutai `pocket-tts` v4.0.0 (Oct 20, 2026) offers new 18M/7M/2M-scale English options; v4.0.1 (Oct 21) includes small-model bug fixes. Benchmark voice naturalness against latency on **Star's own CPU**, copyright/licensing and consent for any voice; avoid installing a multi-GB CUDA wheel just for CPU synthesis. Keep live audio and mic off until operator-owned rehearsal verifies interruption safety.

**Suggested success gates (targets, not achieved measurements):** 0 unverified on-air victory claims; no action after deadline; no key held beyond the watchdog limit; no broadcast start in tests; lower capture-to-ack p95 than a matched baseline without worse objective success/game frame p99/OBS drops; grounded conversational response with reviewed natural interruptions, pauses and no invented personal stories.

## 4. Additional high-value features after the proof-of-play milestone
1. **Private sandbox gaming gym:** game bots for practice, novelty-conditioned curriculum, accurate score/episode resets, playable 2D platformer + FPS + Roblox Studio minigame fixtures.
2. **Game developer apprenticeship:** projects under Rojo/Wally/Luau Analyzer/StyLua, test generation, multi-instance Studio test gate, Blender asset export with geometrical validation and screenshots.
3. **General knowledge with provenance:** retrieval from curated docs, package/API version checks, permissions for web research, citation-backed answers, untrusted-source prompt-injection isolation, aging/contradiction tracking.
4. **Social streaming:** owner-approved community channels, viewer-question deduplication and rate limits, moderation, verified callback provenance, consent-preserving memories, evolving hobbies, social interaction boundaries.
5. **Distributed multi-PC orchestration:** keep Brain 1's research and slow teacher tasks separate from Brain 2 Windows capture/streaming, with a process supervisor and signed job/callback identity, restart and backups.
6. **Self-improvement governance:** reproducible offline acceptance, paired A/B skill tests, safety gates, staged promotions, semantic diffs and rollback in Star Core Forge; GitHub as outward review/publishing channel.
7. **Rust where profiling warrants it:** narrow memory-safe native boundaries for frame copy and audio scheduling are candidates; rewriting the entire Python orchestration blindly will not improve neural network arithmetic.

## 5. Sources reviewed (dates and confidence)
- GameScaling, *Scaling in Games* research site, **November 1, 2026** ViZDoom real-time correction (https://gamescaling.github.io/). Important external measurement caveat; not a reproduced Star gaming win.
- Roblox, *Studio is Going Agentic*, **April 15, 2026** (https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic); Roblox official `StudioTestService` docs (https://create.roblox.com/docs/reference/engine/classes/StudioTestService). Vendor capabilities; do not assume any local bridge is enabled.
- Microsoft Research collaborators, `Proact-VL` code and project (https://proact-vl.github.io/; https://github.com/microsoft/AnthropomorphicIntelligence/tree/main/Proact-VL). Published benchmark, not evidence Star has humanlike speech.
- Kyutai `pocket-tts` releases, **October 20 and October 21, 2026** (https://github.com/kyutai-labs/pocket-tts/releases); project documentation (https://github.com/kyutai-labs/pocket-tts). Developer-reported performance is not a measurement on Star's system.
- llama.cpp slot caching discussions and bug reports: `#13606` (https://github.com/ggml-org/llama.cpp/discussions/13606), `#27148` (https://github.com/ggml-org/llama.cpp/issues/27148), `#30252` (https://github.com/ggml-org/llama.cpp/issues/30252). **Issue reports**, not established universal defects. Test current pinned versions independently.

## 6. Verified in this PR vs not yet done
**Implemented:** source-side engine callback signing compatible with existing authenticated receiver, strict transport size/session budget, monotonic live-state checks and terminal revocation, offline end-to-end tests including actual private journal integration and forged packets.

**NOT implemented:** actual owner game instrumentation, isolated IPC with OS peer credentials, real Windows input execution, complete OBS + voice + avatar rehearsal, measured inference performance improvement, model weight training, or production long-session telemetry key rotation. Leave private tools and broadcasting OFF until these are independently tested.
