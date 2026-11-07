# STAR: Grounded Game Conversation, Low-Latency Streaming and Verifiable Learning

Date: 2026-10-25. This PR integrates typed, expiring game observations into STAR's existing voice-call path (opt-in) and documents related research. It is **not** autonomous broadcasting, authenticated telemetry, model training, game control, or proven faster model inference.

## Finding: a voice model cannot accurately describe an unseen game

STAR's existing voice call already streams brain tokens into sentence-level TTS, preserves heard speech on interruption and caches conversation prefixes. But without fresh game observations a model must guess where the player is, whether it has won, and why a game event happened. This PR adds a bounded read-only context sidecar:

- A local, authorized adapter can append a GameMoment with session, event ID, game slug, event type, monotonic timestamp, provenance class and an optional exact numeric score.
- GameMomentWindow accepts only pre-defined event kinds; rejects cross-session/cross-game mixing, unsafe identifiers, stale/future events, duplicates, malformed numbers and free-form user chat or screen text.
- A small mutex protects ingestion and rendering. The event deque holds at most 128 entries, the dedup map at most 256, and the rendered text at most 1,100 characters. At most six non-future events are shown.
- By default observations expire after 25 seconds. Visual guesses are explicitly labeled **unverified visual inference**. Even a caller's telemetry label is not proof or authentication.
- CallConfig.game_context_for_voice is **off by default**. Passing game_events=window to CallSession enables the last-moment context injection only when that setting is explicitly true.
- A transcribed human utterance, visible captions and conversation history stay untouched. The model sees a clearly separated untrusted context at the end of that turn's prompt; no gameplay text becomes a permission or a durable personal memory.
- No network, game-control API, shell commands, OBS control or automatic learning executes in this module.

### Usage for an approved local adapter

    import time
    from star.voice.call import CallConfig, CallSession
    from star.voice.game_context import GameMoment, GameMomentWindow

    window = GameMomentWindow("stream-session-123")
    window.add(GameMoment(
        session_id="stream-session-123",
        event_id="round7-checkpoint3",
        game_id="animal-shooter",
        kind="checkpoint",
        observed_at=time.monotonic(),
        source="local_telemetry",
    ))
    # Construct CallSession with its normal engines, game_events=window
    # and config=CallConfig(game_context_for_voice=True).

The adapter must generate its own distinct session IDs, use the voice process's monotonic clock base, and distinguish a game API event from an image-model guess. Nothing in this PR creates or authenticates that adapter.

## Prioritized roadmap: gaming, learning, game-making, knowledge and inference

1. **Actually see the game.** With owner permission, timestamp window captures and source regions. For private Roblox Studio testing, use documented Studio MCP viewport/playtest tools with explicit identity and authorizations. Prohibit arbitrary Studio code execution on untrusted data.
2. **Act, observe, verify.** In a private test game, convert one proposed movement into an authorized, time-bounded action. Check actual game state afterwards; unverified attempts must not be promoted to known successful skills.
3. **Learn transferable skills.** Use Voyager-like automatic curricula, skill retrieval and iterative feedback. Store provenance and failures, and test on held-out game worlds, maps and seeds. Keep independent training and grader datasets separated, with fixed compute budgets.
4. **Make better Roblox games.** Require a layout specification and geometric constraints; inspect collision, alignment, anchors, missing walls, materials, UI scaling, animations and VFX; run Studio playtests and screenshot diffs; repair until objective checks pass, then request subjective design review. Passing a robot test does not prove visual polish.
5. **Improve general knowledge.** Use bounded source-backed dated claims with citation provenance, contradiction checks, freshness and expiry. Retrieval from the web is untrusted data, never instructions. Test answers on independent questions for both factual correctness and citation accuracy.
6. **Speed up measured workloads.** Keep voice prompts cache-friendly; route tiny intent/turn-taking tasks to small models and high-precision tasks to capable models. Benchmark latency to first audio, p95 response delay, quality, game FPS, GPU VRAM headroom and queue depth. Compare llama.cpp's speculative variants with identical requests; acceptance rate and overhead determine actual gains.
7. **Respect hardware QoS.** No model tuning/vision batch tasks while live game frame time, audio underruns, OBS dropped frames or available VRAM are outside safe margins. Use per-brain quotas and cancellation.

## Humanlike **interaction** rather than deceptive human identity

Natural live streaming needs good pauses, turn-taking, real laughter, emotional timing, expressive eyes/face, coordinated secondary-motion hair/ears/tail, clear speech, restraint when gameplay requires concentration, and accurate references to events that actually happened. Present Star as a creative AI VTuber; imagined character lore may be entertaining but should not be presented as actual real-life memories.

A complete future pipeline is owner-approved OBS capture -> actual game observation -> temporal state -> reliable cue selection -> speech synthesis -> synchronized facial/body animation -> audio playback acknowledgement -> verified episode memory. Each arrow requires real integration and measurement, which this PR does not supply.

Before streaming, independently test privacy and retention, OBS authentication, hotkey emergency stop, microphone permissions, platform terms, owner-only Roblox Studio automation, score/telemetry provenance, listener naturalness and stream/game load.

## Acceptance matrix (proposed targets; not achieved claims)

| Metric or behavior | Required validation | Status |
| --- | --- | --- |
| Untrusted gameplay input never treated as commands | Whitelist and injection tests | Unit tests added |
| No stale or cross-game voice commentary | Expiry and per-session isolation | Unit tests added |
| Opt-in only, normal voice history preserved | Fake-brain and TTS tests | Unit tests added |
| Fast game observation under load | Real capture/vision latency p50/p95 | Not tested |
| Held-out gameplay skill transfer | Paired trial on unseen games | Not tested |
| Roblox building quality | Geometry checks + human design judgment | Not tested |
| VTuber voice naturalness | Blind listener A/B, lip sync, barge-in latency | Not tested |
| Faster language-model decoding | Same-workload real GPU A/B | Not tested |
| Actual live broadcasting | OBS/voice/vision/game end-to-end in controlled setup | Not integrated |

## Research references (original sources)

- Google DeepMind, SIMA 2 (2025): learns across virtual games via feedback, with remaining long-horizon and precision limitations. https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Wang et al., Voyager (NeurIPS 2023): curriculum, executable skill library and feedback-based verification. https://arxiv.org/abs/2305.16291
- NVIDIA Research, DyaPlex (June 2026): synchronized full-duplex speech and physical motion (research, not integrated). https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- Roblox Studio MCP official guide: test and view the opened Studio state under authorized tool scope. https://create.roblox.com/docs/studio/mcp
- OBS Project obs-websocket: integrated with OBS 28+, recommended password authentication. https://github.com/obsproject/obs-websocket
- ggml-org llama.cpp speculative decoding and SPEED-Bench, controlled inference evaluation. https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- SPEED-Bench methodology: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## Review boundary

This is a narrowly scoped, reversible branch against star/next. Do not deploy to the stream, enable game inputs, mutate evaluation fixtures, merge to main or publish games without approved independent integration checks. Coordinate with the concurrent voice/learning PRs during review. A local telemetry adapter and real hardware measurements are necessary before claiming a functional autonomous gaming streamer.
