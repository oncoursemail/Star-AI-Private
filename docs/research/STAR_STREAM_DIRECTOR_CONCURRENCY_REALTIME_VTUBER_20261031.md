# STAR: Thread-safe live stream director and research-backed next experiments (2026-10-31)

**Scope:** engineering note. No live OBS/Twitch broadcast, autonomous game input, inference speedup, or voice-model installation is claimed. The implementation in this change is a narrowly scoped concurrency correction; later work requires independent host integration and Windows acceptance tests.

## Concrete finding and code change

`star/stream_director.py` was a mutable, session-local narration planner with no internal synchronization, although Twitch chat intake, game observations, owner-interruption inputs, TTS generation, and playback callbacks can originate from different threads. Each operation read/wrote the shared events queue, issued intent map, session epoch, speaking cooldowns, deduplication caches, and counters.

That creates possible interleavings: `offer()` checks queue capacity while another `offer()` appends, `complete()` checks an intent while `disable()` clears the session, or `metrics()` observes a partly updated queue. None of these races can be addressed through prettier text generation or bigger models.

A reentrant lock now makes `enable`, `disable`, `offer`, `propose`, `complete`, and `metrics` atomic relative to one another. The private `_expire` operation stays inside its caller's transaction. Calls remain bounded and perform no external I/O while holding the lock. This is a *correctness* improvement for concurrent hosts, not a demonstrated token-per-second or gameplay-intelligence improvement. Production adapters still have to check owner permissions, genuine audio playback receipts, and game observation freshness.

## Follow-up experiment 1: Twitch connection health as a separate host signal

Twitch EventSub WebSockets use Welcome, Keepalive, Reconnect and Revocation messages. The official documentation says a host should treat a connection as lost when its keepalive window is exceeded; during a documented handoff, keep the old socket until the replacement Welcome arrives. STAR currently has approved session-ID binding and reconnect/deduplication rules in its offline adapter, but a reliable *network host* still needs keepalive monitoring and revocation handling. Do not assume chat ingress alone proves Twitch is still connected.

**Proposed acceptance:** synthetic missing-heartbeat, reconnect-overlap, disconnection/revocation, duplicate EventSub deliveries and session-ID mismatch cases. On loss, cease new chat narration, preserve privacy, and make a new authenticated host session the only way to resume.

Source: https://dev.twitch.tv/docs/eventsub/handling-websocket-events/

## Follow-up experiment 2: Natural conversational barge-in

LiveKit's March 19, 2026 adaptive interruption work distinguishes genuine interruptions from acknowledgments, sighs and coughing. The documentation also distinguishes voice activity, end-of-turn confidence and false-interruption recovery. STAR should benchmark an adaptive detector against its current deterministic `TurnTakingGate`; do **not** let a speech model assign owner identity or issue game/OS permissions.

Measure false barge-ins/hour, owner interruption response latency (median/p95), speech restoration after a false alarm, interruption at word boundaries, and laughter/phoneme-to-avatar alignment. Use human-rated conversational naturalness, not just ASR accuracy.

Sources:
- https://livekit.com/blog/adaptive-interruption-handling
- https://docs.livekit.io/agents/logic/turns/tuning/

## Follow-up experiment 3: Fast reflex + deep teacher, measured on an 8 GB GPU

Keep reactive gameplay action selection separate from the between-round teacher. The teacher should never block an imminent game input. Gate actions on fresh observations and a measured decision deadline; reserve GPU headroom for the game, OBS encoder, avatar and audio before allocating inference work. For the user's RTX 4060 8 GB environment, verify the actual host's available VRAM and memory rather than assuming a particular working set.

llama.cpp SPEED-Bench supports controlled baseline-versus-speculative comparisons with request latency, throughput and accepted draft-token metrics. Use identical prompts, model/quantization, output length, concurrency and game load, and reject apparent speedups when gameplay p95 latency, frame pacing, OBS skips or speech interruptions get worse. Switch expensive Python sections to Rust only after profiling proves worthwhile.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## Follow-up experiment 4: Game-creation quality in Roblox Studio

Roblox StudioTestService can automate multiplayer/server-client tests. The strongest game-building loop is inspect scene -> propose minimally scoped changes -> run Luau analysis -> execute tests -> capture visual/collision evidence -> repair -> independently verify. Do not approve merely because scripts compile; evaluate missing walls, prop intersections, scene scale, UI legibility, animations, multiplayer replication and playability.

Source: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

## Follow-up experiment 5: A humanlike but truthful VTuber

Build a durable, queryable *real-activity journal* that separates (a) host-verified gameplay and creative work, (b) user-supplied preferences, (c) uncertain model inferences, and (d) fictional persona lore. She can make callbacks to games she actually played, react to witnessed defeats and wins, express consistent interests, and have warm spontaneous humor without presenting made-up personal events as real.

A separate performance-adaptive stream director should decide when **not** to speak: difficult combat, owner voice, unstable stream output, and unverified scene observations. Coordinate voiced audio timestamps with mouth shapes, eyes, body gestures and hair secondary motion. Evaluate with consented A/B recordings and blind human ratings. AI disclosure, moderation, viewer privacy and bounded operating permissions remain essential.

## Acceptance and deployment gates

1. Deterministic concurrent offer/disable/propose/complete regression testing, including queue cap, per-viewer fairness and epoch invalidation.
2. Offline Python checks and Pyright; no external keys, streams or model downloads in CI.
3. Host-level Windows stress test with gameplay + OBS + voice + avatar, comparing before/after at matched workloads.
4. Keep the draft PR unmerged until reviewed and CI green. The `Star-AI-Project` repository is PUBLIC; never commit private viewers' content, recordings, tokens or credentials.
5. No new runtime feature implicitly enabled; the host must still obtain owner authorization for external actions.
