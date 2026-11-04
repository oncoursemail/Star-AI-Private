# STAR: measured OS input acknowledgements, reactive intelligence, and a natural VTuber roadmap

**Research date:** November 3, 2026. **Code status:** host-only, optional, offline-tested advisory; no real-game performance claims. **Stacked change:** after PR #951.

## Key performance finding

The existing real-time router profiles inference duration with a fixed 40 ms input-dispatch reserve. This can misjudge whether an input arrives before its game-scene deadline when the OS, GPU, game and OBS are loaded. A fast answer is useless if the world has moved on. The November 1, 2026 GameScaling ViZDoom correction explicitly added attention to screenshot capture, transfer, preprocessing, action processing, and recording time in real-time evaluation: https://gamescaling.github.io/

Implemented in this branch: an optional strict input-acknowledgement profile in the GameDeadlineRouter that measures OS-level acknowledgement separately from model inference, fails closed when recent evidence is missing, partitions live-OBS from idle samples, treats timeouts as 5000 ms, and reserves the maximum of the fixed floor and measured p95 acknowledgment. At model completion, never charge the model-inference time twice but keep the input reserve. Strict mode is OFF by default, preserves existing authorized action controls, and never launches a model or presses a key. RealtimeGameLoop exposes a trusted-host recording wrapper.

Caveat: a host's OS acknowledgement is not proof that the game registered an action, and a host_measured flag is not cryptographic authentication. Genuine game outcomes require an independent engine observer, and physical key release requires actual Windows tests.

## Reactive intelligence architecture

**Reflex tier:** bounded small vision/state model with verified, fresh game observations; deadline-aware admission; cancel stale work; never wait for research or a heavy reasoning model.

**Tactical tier:** asynchronously plan short sequences, retain alternatives, transfer only a scene-bound action recommendation to the fast loop, and use measured uncertainty to decline risky actions. Avoid sending speculative commands directly to the input host.

**Offline teacher tier:** run deliberate training between matches; synthesize increasingly difficult level variations; generate several candidate strategies; score with independent game-engine outcomes; compare against a frozen baseline and unseen holdouts before promoting lessons. Failed, copied, or unverified observations must never count as a win. Keep train/validation/test seeds independent and version the game build.

**Knowledge and game creation tier:** local retrieval over versioned official docs and successful, reproducible examples; freshness-aware citations; inspect an existing game tree before writing code; use StyLua/luau-lsp/lint, Studio execution and visual regression. OpenGameEval (October 2026) measures exploration before edits and reports better results when agents inspect affected objects: https://github.com/Roblox/open-game-eval . Roblox built-in Studio MCP (March 5, 2026) enables project inspection and playtest automation: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 . StudioTestService supports scripted multi-client cases: https://create.roblox.com/docs/reference/engine/classes/StudioTestService .

## Performance plan for an 8 GB gaming GPU

Game rendering and OBS encoding must have priority over optional large-model inference. Compare small CPU-focused speech synthesis versus existing voice on the same gaming PC, measuring audible first chunk, p95 overall response time, OBS frame drops, game p99 frame time, and GPU/CPU use. Kyutai Pocket TTS v4.0.0 (released October 20, 2026) added 18M, 7M, and experimental 2M English models; v4.0.1 (October 21) fixed some sub-20M pronunciation issues: https://github.com/kyutai-labs/pocket-tts/releases . Do not mistake published model size for an on-device speed measurement.

Benchmark actual llama.cpp model candidates with identical prompts, context length, concurrency, and paired seeds. Measure prefill, decoding, time to first token, cache hit fraction, KV memory, speculative decoding acceptance, thermal throttling, and interference with OBS. Compare no-draft versus draft speculation on real prompt categories; a draft model can slow the system. Official SPEED-Bench procedure: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .

Separate Game/Stream tasks from Night School tasks; pause training, downloads and image generation under game/OBS pressure. Cache knowledge by content hash, permission scope and document version, invalidating as soon as a scene changes. Use CPU and RAM optimizations independently of GPU: fewer redundant tool calls, targeted retrieval, structured state snapshots, and bounded memory.

## More natural and social VTuber behavior

Build a conversational *turn policy*: deciding when to speak is as important as choosing words. Use verified gameplay events and audience turns to trigger relevant short reactions, avoid constant commentary, preserve meaningful silence, and defer optional remarks during difficult gameplay. Proact-VL studies when gaming companions should speak and how to control response volume and latency: https://arxiv.org/abs/2603.03447 .

Distinguish speech interruptions from backchannels, mic noise and game audio. LiveKit's turn handling provides a reference for adaptive interruption and recovering from false interrupts: https://docs.livekit.io/agents/logic/turns/ . Star must still enforce her host's independent physical audio-stop and clock-failure safety rules. A natural voice needs distinct rhythm, laugh/sigh/prosody when relevant, and synchronized lip movement driven by actual audio chunks. The avatar should reflect genuine confirmed game events and the chosen expression, not hallucinated experiences.

Keep persistent interests, approved social interactions, long-term goals, occasional unscripted-but-appropriate comments, curiosity-driven experiments, consent-scoped memories, and an episodic diary grounded in *verified experiences*. Always distinguish privately known owner details from public stream-safe stories. Clearly present her as an AI performer, not secretly as a human.

## Real-world acceptance gates before release

Use an owner-controlled/offline test game and a no-network OBS rehearsal. Make 20+ independently reset paired trials in the same scenario. Record timestamps on ONE monotonic host clock: capture start/end, transfer, preprocess, model start/end, OS dispatch/ack, trusted engine event, and independent objective outcome. Measure p50/p95/p99 capture-to-ack latency, deadline-hit percentage, game 1%-low FPS, OBS dropped frames, and TTS time-to-audible. Run baseline fixed-reserve versus strict measured-reserve on matched starts. Require no credible stream/voice/game regression and evidence of better timely gameplay performance. Safety tests include blocked input, lost audio monitoring, stale scene, changed OBS state, foreground focus loss, watchdog crash, physical key release, and an independent stop action.

**What remains unverified:** no Windows physical input, mic, TTS/PCM, avatar/OBS or live gameplay tests are part of this branch. The change is a better *decision boundary*, not evidence of higher neural intelligence, more humanlike voice, improved win rate, or measured faster hardware inference.
