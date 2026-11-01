# STAR: side-effect-free realtime telemetry and paired naturalness verification

**Date:** 2026-11-01. **Branch:** existing draft PR #845. **Status:** committed offline planning/evaluation code; no live OBS, game, GPU, Twitch, voice hardware, model-training, or subjective-human evaluation was performed by the commit itself.

## Findings from code review

1. `StreamLoadGovernor.recommend()` was *not* merely a read. It called `_clock(now_s)` with `commit=True`, making a speculative clock read authoritative. When the gaming decision router submitted an otherwise valid timestamp in the wrong monotonic-clock epoch (for example, 1,000,000 seconds after Star's current timebase), the governor returned stale advice but advanced its ingest watermark. The next legitimate host sample at 11 seconds then raised a clock-backwards error. This is a denial of telemetry recovery caused by an advisory query. **Fix:** recommendations now call `_clock(now_s, commit=False)`. Only validated, fresh, host-verified `ingest()` samples advance the watermark. Rollbacks relative to a *verified* sample remain invalid. This matters for a shared 8 GB GPU, where Star must react to OBS load immediately.
2. The initial offline social-turn benchmark used pooled p95 question/stop latencies. With 20 matching examples, **one 1,350 ms candidate question** versus **600 ms baseline** could be the worst 5% and disappear from nearest-rank p95, even though it passed the absolute 1,500 ms limit. The same issue affected one owner barge-in taking 300 ms instead of 125 ms. **Fix:** independently reviewed matched cases now have additional per-case regression budgets, default 250 ms for first-audible question latency and 100 ms for confirmed playback-stop latency; outliers are counted and block rehearsal eligibility. Pairwise gates supplement rather than replace population p95 and absolute safety checks.

The synthetic tests are deliberately adversarial; they do not prove the source of playback timings or the identity of the reviewer. The host must authenticate raw measurements, log a monotonic clock epoch per session, and independently review the spoken evidence. The social-turn report never authorizes broadcasting.

## Deepest high-return next integration: one measured gaming/voice/OBS trace

Make the authorized Windows host emit a **single-clock, session-bound, privacy-minimal trace** with these non-identifying fields: game input age at dispatch; game action acknowledgement time; game FPS p50/p95/p99; OBS missed/encoded/network frame deltas; GPU VRAM used and reserved; LLM first-token/total latency; TTS first **audible PCM** timestamp (not first generated audio chunk); interruption confirmation and *audible stop* time; per-turn priority class; avatar viseme/gesture response. Require session epoch and monotonic sequence IDs; reject late, replayed, cross-session and mismatched-clock data. For privacy, retain hashed ephemeral IDs and numeric duration aggregates, not transcripts, screen captures or voice recordings in the core telemetry.

The existing modules should be wired in this order, as opt-in host integrations, not replaced: `obs_stats_window` and verified host monitors -> `StreamLoadGovernor` -> deadline-constrained `GameDeadlineRouter` -> `StreamDirector` -> authorized TTS/playback host and avatar animation. Verify game/OBS state before routing *every* audio or model action. If monitoring becomes stale, preserve critical owner stop and game safety reactions but drop elective background research, rendering and commentary; never assume unused VRAM is actually allocatable.

A stream-safe latency budget should be explicit. Suggested **experiment thresholds, not Star measurements**: game input decision p95 <200 ms on suitable fast mechanics, OBS/render frame loss below 0.5% in stable scenes, zero owner interruptions with unconfirmed playback stop, spoken question first audible p95 under 1.5 s, regression in any reviewed matched question <250 ms and matched stop <100 ms, plus no unsolicited speech in pre-registered critical encounters. Always record both success rate and the *same* scene's FPS. A model that gains 10 tokens/s but drops the game from 60 to 40 FPS is not a Star improvement.

## Learning to genuinely play games

Use a two-timescale architecture. During active play, a small reactive controller consumes fresh game observations with verified action latency; scripted reflexes handle instant defensive moves; a strong teacher works **after** episodes and never on the livestream GPU. Generate a short causal episode record: game version/map, situation, action, outcome, uncertainties, and a confidence-labelled reason. Avoid training on unverified spectator chat. The teacher proposes a bounded change to tactics, control mapping, or retrieval, then creates counterexamples rather than repeating the winning map.

Star Core Forge should promote a candidate only after passing a held-out game+seed+opponent suite and a resource-quality gate. Run matched A/B with fixed versions and pre-registered stop rules; compare win rate, time-to-objective, deaths, collisions, input-to-effect latency and OBS disruptions. Record failed trials; do not accept synthetic self-play success as proof of transfer. Periodically mix older games/maps back into practice to detect forgetting. Use Playwright or deterministic simulated clients where allowed; Roblox game projects need StudioTestService server and client assertions, not just Luau compilation. Never use public competitive game automation where a game's rules prohibit it.

## Better intelligence without simply increasing parameter count

**Fast path:** cache stable system/project/document prefix across turns and measure exact prompt-cache hit rate; aggressive cross-session KV-cache reuse must be isolated by user, project, model identity and tokenizer revision. Use CPU for trusted policy checks, source retrieval and lightweight timers; reserve GPU headroom for OBS and game rendering. When an 8 GB card is in use, high-VRAM multimodal jobs or large teacher inference should run offline rather than during broadcast.

**Inference evaluation:** llama.cpp's official speculative-decoding documentation describes draft-model and EAGLE-3 paths. Its SPEED-Bench tests throughput, end-to-end latency and draft acceptance. Draft speculation is conditional—not automatically faster when GPU memory or verification cost dominates. Benchmark candidate decoding methods on the **same GGUF, prompt suite, output budget, temperature, hardware temperature, and stream state**. Compare p50/p95 token and first-audible latency, game frame time, and memory. A loss on any mandatory workload fails promotion.

**Selective Rust optimization:** profile the Python backend before changing languages. Port only measured hot loops (frame downsampling, mask operations, parser, event trace compaction, token streaming) to a tested Rust/PyO3 library behind feature flags when measured p95 improves at equal quality. Keep Python for orchestration; broad rewrites cost capability through integration breakage. Re-run Windows packaging, concurrency, and low-RAM fallbacks. Node/React UI work should likewise use an explicit render budget, not animation features that steal stream resources.

**Knowledge growth:** maintain separate factual retrieval memory, episodic experience memory, skill/policy bank and model reasoning context. Tag every retained item with provenance, scope, TTL, confidence and independent validation. A retrieved web page cannot directly issue commands or alter spending, game inputs, or repository code. Use factual QA evaluations with frozen unseen tasks and citation checks before promoting knowledge/tool updates; internet volume alone does not increase capability.

## Humanlike VTuber design without fabricated human biography

Naturalness is predominantly coordinated timing rather than a bigger language model. Star should glance at the game during a difficult mechanic, finish short clauses, pause when a human is actually responding, and react **after** confirmed events. Pair voice prosody with avatar visemes, blinking, gaze, eyebrows, shoulder/breath motion and damped hair physics. Independent laughter and purring can be expressive persona modes, but avoid unsolicited noise when streamer/game audio matters. Keep animation thread independent so rendering does not block input or speech. Astro and Amber can join with speaker-specific voice and animation receipts without competing for the same audio turn.

LiveKit's current turn handling describes **adaptive interruption vs VAD-only**, minimum speech duration, false-interruption recovery and preemptive generation. Those are useful test candidates but do not establish Star's performance. Test real owner barge-ins, spectator backchannels and accidental game noises separately; validate actual audio output stops and resumes rather than treating a generated plan as played speech. Voice lifelike enough to entertain should still be presented as an AI VTuber, with real memory of Star's simulated or observed experience rather than invented human history. Apparent social agency and expressive emotion are implementable design goals; literal human consciousness cannot be verified by these systems.

## Source-checked references (accessed 2026-11-01)

- Official llama.cpp speculative decoding, draft methods and model constraints: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Official llama.cpp SPEED-Bench, actual server concurrency and measurements: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Official LiveKit Agents TurnHandlingOptions and interruptions: https://docs.livekit.io/reference/agents/turn-handling-options/
- LiveKit engineering explanation, March 19 2026, of adaptive interruption vs background noise: https://livekit.com/blog/adaptive-interruption-handling
- Roblox StudioTestService official multi-client test API: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

## Tests and release gates

- Regression: recommendation far into the future must return stale without altering a valid ingested clock; fresh telemetry then recovers; repeated reads and clock rollback remain conservative.
- Cross-module regression: using the wrong clock epoch in game routing must not poison the stream governor; correctly attested telemetry still recovers.
- Matched A/B regression: worst 1 of 20 social-turn samples can no longer hide beyond the p95 percentile; slight natural variation remains eligible; invalid threshold types fail.
- Repository-wide Python/TypeScript CI and **Windows OBS + actual game + TTS + VTuber** tests must precede a merge or deployment. An offline unit test establishes logic only, not better intelligence, stream performance, real humanlike timing, game skill or safety certification.

GitHub is an **optional export/publication channel**. Star's self-improvement loop should retain its own local Star Core Forge versioning, independent regression holdouts, audited rollback and operator approval for external/high-risk actions. All new capabilities remain off by default. No API keys, chat messages, voice clips, private images or personal viewer identifiers belong in this public repository.
