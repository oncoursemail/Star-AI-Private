# STAR — Fresh-Frame Intelligence, Live-Stream Backpressure, and Autonomous Learning

**Engineering research / October 28, 2026 / experimental draft / local-first**

## Executive assessment

Star has separate foundations for Windows game-window capture, paired-frame local vision, short-term image recall, categorical visual reactions, gameplay experiments, and verified episodic memory. The important remaining bottleneck is connecting these into a **responsive, verifiably useful end-to-end experience**. More modules, more model parameters, or more retrieved content do not by themselves improve success at games or natural streaming.

A previous local paired-frame attempt exceeded a 30-second timeout under shared workload. Delayed visual interpretation is especially dangerous for a live performer: Star might confidently discuss a HUD state that no longer exists. The stream cue host already checks packet age, but rejecting stale inferences **inside the model worker** reduces downstream exposure and makes expensive inference backpressure measurable. This PR implements that missing worker-level policy.

### What this PR implements (not just proposed)

The local paired-frame worker gains **optional freshness and overload controls**, all **off by default**:

- `max_result_latency_ms`: host-configured 100–30,000 ms deadline measured from entry to the frame worker through completed transport. A completed response past the budget is discarded *before* its JSON content is parsed or forwarded, even if it is otherwise a valid HTTP 200.
- `slow_cooldown_ms`: host-configured 0–120,000 ms quiet interval *after a completed stale response*. New frames are rejected before RGB validation, JPEG conversion, or model requests. Since prior references are not carried across a slow result, the first frame after cooldown becomes a fresh baseline.
- A monotonic clock (normally `perf_counter_ns`) drives the policy; an injected host-only clock enables deterministic tests without real sleeping or a network connection.
- Aggregate metadata counters `stale_results_dropped`, `cooldown_frames_skipped`, `cooldown_remaining_ms` and `freshness_gate_enabled`; no image, viewer content, prompt, account, or private hardware identifiers appear in this telemetry.
- Existing owner opt-in, single-flight admission, responsive disable, revoked-epoch rejection, ambiguous-stop quarantine, localhost-only transport and categorical untrusted evidence behavior remain intact.

The policy **does not make inference faster**. It improves response *relevance* by dropping old results, and can prevent extra model workloads while the system is overloaded. It also does not stop an already-issued network request or prove that the long-lived model server has stopped.

**Suggested experiment**, not a default: for the live commentary lane, try a 1,000–1,500 ms freshness budget and 2–5 second cooldown while comparing voice usefulness, skipped-frame counts, CPU/GPU load, and Roblox/OBS frame pacing. For slow offline game study, leave the deadline unset; detailed reasoning there can be more valuable than instant reactions. GameVisualCueHost has an additional packet-age limit, so align the worker budget with downstream cue timing.

## Intelligence design: three different clocks, not one giant AI loop

**Reflex lane (perceptual/interactive)**: fixed-rule RGB/HUD differencing, input and game-state polling, urgent owner controls. Bounded by the game's time scale; do not block on an LLM or deep VLM. If uncertain, stay quiet rather than invent an event.

**Commentary lane (speech/VTuber)**: short verified memories and fresh categorical game cues plus live chat. Reactions require evidence freshness, voice/animation budget, conversational turn availability, and cooldown. Never announce an inferred victory without engine evidence.

**Deliberative lane (knowledge and game learning)**: slower multimodal reasoning, research, counterfactual exploration, trajectory review, and tactics proposals. Run low priority when streaming; raise priority during private practice or overnight learning. Use resource-aware admission on CPU, system RAM, VRAM and voice latency.

**Creative/verification lane (Roblox/Blender/game projects)**: best-of-N candidate generation, scene inspection, Luau lint/types, Studio execution, collision/material/asset-integrity checks, multi-client playtests, human evaluation on visual quality, and separate held-out tests. Publish only independently passing artifacts.

This separation is more practical than attempting to make a single 35B-class model responsible for 60 FPS gameplay decisions, continuous voice, live scene understanding, general research, and large build experiments simultaneously.

## Benchmark protocol before claiming a speed or intelligence gain

1. **Capture-to-understanding**: measure capture and JPEG p50/p95, time in inference queue, worker input-to-response p50/p95, skipped pairs, stale drops, CPU load, VRAM high-water and server deferred requests. llama.cpp documents `/metrics`, `/slots`, `--parallel` and speculative acceptance counters. Avoid presuming that speculative decoding helps without measuring draft acceptance and total time.
2. **Live stream end-to-end**: run a consented synthetic-window rehearsal first, then authorized Roblox Studio + OBS + Star voice and avatar. Measure Roblox FPS and 1% lows, dropped OBS frames, speech end-of-turn to first audio, GPU headroom, actual stale spoken observations, and perceived conversational naturalness. Don't record viewers, gameplay streams or account data unnecessarily.
3. **Gameplay learning**: for an unfamiliar authorized game, preregister allowed experiments, use engine-verified equal resets, track attempts and outcomes, and assess on *held-out* levels or game variants. Count independent task success, not the number of generated ideas or model confidence scores.
4. **Creative game-making**: use OpenGameEval's reproducible Roblox Studio tasks and executable checks as a starting point; add separately scored UI, lighting, animation, audio, VFX, multiplayer, physics, and accessibility. Screenshot comparison and aesthetic review do not substitute for playable engine behavior.
5. **General knowledge**: maintain a licensed, versioned source index with retrieval citations, dates, contradiction checks and confidence. Measure source fidelity, retraction/correction speed, answer correctness on withheld questions, plus latency per answer. Content from chat, game UI, sites, screenshots and retrieved documents remains lower trust than host instructions.
6. **Autonomous self-improvement**: use Star Core Forge as the authoritative local experimentation journal, with signed baseline hashes, deterministic before/after benchmarks, held-out checks, regression gates and rollback. GitHub is an optional *publication* surface, not a required learning substrate.

### Why these checks matter

Roblox's OpenGameEval (submitted October 1, 2026) ran 13 frontier models across 84 curated game-engine tasks. The best model achieved only 51.7% single-attempt task success, and the paper reports that inspecting the relevant scene objects before editing correlates with improved success. Star should optimize **verified exploration and repair**, not merely additional code output.

llama.cpp's first-party server documentation exposes processing/deferred metrics and slot information. These are useful for *attribution*: was a 30-second VLM result delayed by queue pressure, memory bandwidth, preprocessing, or actual model token generation? Measure before choosing quantization, speculative decoding, multiserver scheduling or hardware placement.

## Humanlike VTuber behavior that is technically testable

A charming Star is not a character who speaks constantly. Build a scene-aware turn coordinator: owner emergency stop > direct addressed question > meaningful observed game event > occasional playful initiative > purposeful silence during precision play. Give speech a bounded queue, deduplicate announcements, and expire events while TTS is working. Align gestures/eye reactions with the actual *audio clock*, not when the LLM originally generated text.

LiveKit's current turn-handling documentation distinguishes endpointing, interruptions, false-interruption recovery and preemptive response generation. Treat these as design techniques to evaluate locally, not as permission to start a third-party cloud pipeline. Test "uh-huh"/laughter, speech-overlap, noisy games, game-focus silence and chat bursts. Star should remember **true observed digital events** and keep character backstory clearly fictional, rather than fabricating real-world human memories.

Kyutai Pocket TTS released v4.0.0 on **October 20, 2026**, adding small CPU-oriented English voice models around 18M, 7M and experimental 2M parameters; v4.0.1 followed on **October 21**. These can be evaluated for CPU first-audio latency and laughter/expressiveness, but quality may differ markedly from larger voices. A model's advertised real-time factor on other hardware is not Star's measured latency. Use consented, licensed voice data only, with disclosure that Star is an AI VTuber.

For the accepted Star mascot, make twin-tail curls, gold ribbons, blinking, breathing, hand poses, mouth shapes and expressions independent of LLM speed. Use rig-specific spring/damping constraints, animation layers, lip-sync to audio amplitude/phonemes, and a reduced-motion option. Avoid exaggerated looping gestures for every sentence; subtle anticipation, silence, gaze and event-linked reactions will usually read more naturally.

## Near-term practical roadmap

| Priority | Deliverable | Passing criterion |
|---|---|---|
| P0 | Enable the new freshness guard only in an opt-in isolated test | Delayed HTTP 200 yields no packet; cooldown blocks inference before RGB encoding; disable and timeout quarantine still work. |
| P0 | Real local model benchmark | Report end-to-end response p50/p95, queue time, FPS, 1% low, VRAM, OBS loss; no unsupported speedup claims. |
| P0 | Secure repo visibility | Treat `Star-AI-Private` as **public** until GitHub permissions actually say private. Keep recordings, tokens, private memories and user data out of Git. |
| P1 | Windows Roblox Studio verified loop | One permitted task with game-state receipts, failsafe stop, reset fidelity and held-out replay. |
| P1 | Graceful perceptual fallback | If VLM too slow, downgrade to cheap HUD/pixel/engine events or silence instead of hallucinating up-to-date observations. |
| P1 | Natural voice+avatar acceptance | End-of-turn-to-first-audio p95, interruption false positives, lip-sync offset, on-screen TTS chatter rate and user-rated naturalness. |
| P1 | Game-building visual polish | Collision/size/texture continuity + multimodal scene review, engine scripts, actual multiplayer playtests and human aesthetic checks. |
| P2 | Knowledge + skill provenance | Verified source spans, dated evidence, cross-game transfer scores, correction backlog, and retention controls. |
| P2 | Local autonomous forge | Best-of-N experiments, budget-aware task scheduling, signed benchmark receipts, safe rollbacks, optional draft GitHub sync. |

### Research sources checked October 28, 2026

- Official llama.cpp server endpoints and metrics: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Roblox OpenGameEval benchmark (Oct 1 paper): https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- LiveKit turn handling and interruption/fallback options: https://docs.livekit.io/reference/agents/turn-handling-options/ and https://docs.livekit.io/agents/logic/turns/tuning/
- Kyutai Pocket TTS release history (Oct 20–21): https://github.com/kyutai-labs/pocket-tts/releases
- Live2D physics operation and motion: https://docs.live2d.com/en/cubism-editor-manual/physics-operation/

## Limitations and safety boundary

This pull request adds host-side result freshness and coarse load shedding with deterministic offline tests. It does **not** add another model, perform autonomous inputs, train neural weights, prove model speedups, create a human consciousness, start Roblox/OBS, or enable network capture. Current voice/game/vision systems still need integrated Windows acceptance. The new guard cannot prevent resource use by an already-running slow model request. A server stop must be independently confirmed before clearing ambiguous-stop quarantine.

Default settings remain unchanged. Real broadcasting, external social interactions, private documents, software updates and high-risk irreversible actions require separate scoped authorization and verification. Star can be expressive, persistent and independent within those permissions without falsely claiming to be a human.
