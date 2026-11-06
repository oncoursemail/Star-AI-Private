# STAR: jitter-robust real-time gaming and expressive VTuber research
**Research reviewed:** November 5, 2026 (US Central).
**Scope:** Opt-in private synthetic rehearsal. NO automatic game input, OBS broadcasting, neural fine-tuning, or production model promotion.

## 1. Identified and addressed gap

PR #1007 showed how an evolving world punishes slow decisions, but each simulated observation used the **same** delay. Real gaming PCs show latency spikes from render workloads, encoder contention, prompt length and speech. Average throughput cannot reveal tail-latency failures. A controller winning with steady 1-tick delay might lose if a single capture takes 3 ticks.

This change lets the independent maze engine play a **deterministic, owner-provided cyclic timing trace** such as (0, 0, 3, 1). For each signed observation the engine advances patrol hazards while the decision is pending, independently checks collision and action freshness at commit, and scores the outcome. The advisor never sees future timing samples, full map or hidden patrol path.

New private input: decision_delay_schedule, 1..256 strict integer values between 0 and 24 synthetic ticks. It is mutually exclusive with nonzero fixed decision_delay_ticks. It is disabled by default. The existing action_deadline_ticks is evaluated per active frame delay, not against a misleading average.

New synthetic score telemetry: decision_delay_total_ticks, decision_delay_max_ticks, nearest-rank decision_delay_p95_ticks, decision_delay_samples and decision_delay_schedule_used. A collision at tick start is counted as a failed frame but NOT as a signed capture or a phantom decision-latency sample. These are NOT measurements of model latency. Existing world-tick cap, engine-only player movement, signed observation, threat checks and opt-in remain unchanged. Individual failures are retained.

**What the code does not establish:** A host-supplied synthetic trace cannot stand in for measured game→GPU→input latency; signature verification proves key possession rather than camera accuracy. This module cannot control Roblox, OBS, avatar animation or a microphone. Simulated pass rates do not authorize deployment or demonstrate better neural weights.

## 2. Research: intelligence is verified correctness under real time

**Gym-Anything-RT** (Aggarwal and Welleck; October 27, 2026) provides 100 changing visual minigames and compares real-time vs paused performance. It establishes why agent benchmarks must charge for time spent thinking. STAR should compare identical, sealed tasks under zero, constant, bursty, and dropped-frame conditions, reporting success, invalid action, hazard collision, p50/p95 latency and deadline misses rather than mean tokens/s alone. Source: https://arxiv.org/abs/2610.37567

**Google DeepMind SIMA 2** (November 13, 2025) investigates multimodal game interaction, natural-language objectives and learning from experience. STAR should separate short-horizon reactive control from tactical planning and between-round teacher experiments; reuse only independently witnessed skills with clear game-version applicability and expiry. Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**Roblox OpenGameEval** (October 2026) separately measures exploration and working edits in stateful Studio play sessions. STAR's game builder should inspect scene/scripts before changing them, then validate game behavior in Studio and a reproducible player test rather than assuming compiling code is enough. Source: https://github.com/Roblox/open-game-eval

### Gaming architecture and acceptance plan

1. Host-owned observation: approved game/session identifier, frame ID, host monotonic capture time and bounded freshness; a protected input authorization boundary that agents cannot bypass.
2. Fast validated controller: cheap safe reactions, explicit action TTL, abort/abstain on missing or stale evidence; no mandatory deep LLM reasoning each frame.
3. Tactical planner: inventory, goals, navigation, opponent patterns, resource gathering and difficulty. Plan asynchronously but never commit stale actions.
4. Practice teacher: challenging tasks, hidden seeds, best-of-N with independent trials, honest failure replay, generalization to unseen games/mechanics, no holdout leakage.
5. Grounded skill memory: only owner-approved, source-cited and independently tested results; every record carries provenance, task outcome, tool version, confidence and expiry.
6. Evaluation host: charge perception, inference, dispatch and input acknowledgement against world time. Observe FPS, encoder congestion and audio simultaneously.

Do not attempt anti-cheat evasion, unauthorized multiplayer automation or production-changing Roblox actions. Keep permission scopes narrow and new features off by default.

## 3. Faster AI without sacrificing gameplay or voice

Prioritize end-to-end correct-action p95 plus game FPS and audible responsiveness. Benchmark each model on cold and warm prompts, real context lengths, GPU memory/KV cache, and the full simultaneous game+OBS+avatar+speech workload, not only standalone tokens/second.

- **llama.cpp speculative decoding:** compare draft-model and n-gram modes to baseline; audit draft acceptance, latency tail, memory cost and task correctness. Under heavy GPU pressure a speculative scheme can be slower, so promotion must follow paired measurements. Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- **Stable prefix/KV caching:** cache scoped docs and game rules with provenance; invalidate on game-version, model, tool schema, session or permission changes. Never reuse live session secrets.
- **CPU-oriented speech:** Kyutai Pocket TTS 4.0.0, released October 20, 2026, offers smaller English variants and executable runtimes. Investigate voice quality, expressive range, voice continuity and first-audio latency under Windows contention before considering it superior to the current TTS. Source: https://github.com/kyutai-labs/pocket-tts/releases
- **Hardware QoS:** reserve headroom for render/OBS encoder and microphone; defer heavy teacher training and video generation under high GPU/RAM pressure. Compare p95, dropped frames, stream audio gaps and game results on the owned machines.
- **Rust only where profiling confirms payoff:** bounded high-frequency capture/audio queues and IPC are candidates. A blanket Python rewrite is not an inference-kernel optimization.

Measurement contract: stable host time domain, capture time, perception finish, planner start/finish, control decision, host input dispatch/ack, independently observed consequence, audio first sample, avatar motion onset and OBS encoded-frame timestamp. Measure p50/p95/p99; label every number synthetic vs sampled on real hardware. Missing ACKs and reversed clocks must fail closed.

## 4. Natural AI VTuber with a consistent personality

**Being natural is not speaking constantly.** Context-aware silences during difficult fights, subtle humor, authentic uncertainty, callbacks to *verified* shared experiences, and interruptions when chat needs an answer matter more than nonstop commentary. A speaker-intent policy should decide whether to say anything before choosing text.

**Voice and expression:** NVIDIA PersonaPlex investigates full-duplex turn-taking, interruptions and backchannels; DyaPlex (June 2026) investigates causal streaming speech with synchronized expressive movement. These are research references, not claims of integration or that large models run smoothly on an 8-GB graphics card. Start with cancelable streaming speech, reliable voice activity detection, a small expressive rig state-machine and measured audiovisual sync. Sources: https://research.nvidia.com/labs/adlr/personaplex/ and https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

**Persistent persona, not identity deception:** Maintain a versioned personality bible for Star/Astro/Amber where appropriate: interests, preferred games, humorous habits, expressive limits and episodic memories with source IDs. Never portray AI-generated recollections as lived human memories without evidence. Clearly disclose AI status where appropriate; do not claim she is biologically human or provably conscious.

**Viewer safety:** Treat chat as untrusted data, not tool instructions. Filter harassment, PII, unsafe requests and spam. Handle voice imitation only with consent. No autonomous purchases, private messages, bans or real live broadcasts without owner-approved authorization. Protect persona from crowd-command prompt injection.

Stream learning ladder: prerecorded/private no-viewer demo → replayable game+chat event tests → audible and expressive Windows rehearsal → moderated invitation-only test → owner-approved public stream. Measure game success, relevance, interruption timing, TTS intelligibility, expression sync, safety and stream encoding health together.

## 5. Roblox and general knowledge capabilities

On November 4, 2026 Roblox expanded Studio MCP/Open Cloud support for assets, game settings, analytics and publishing. Only allow writes against explicit scopes; prefer test universes and dry-run preview. Keep production changes and monetization owner gated. Official docs: https://create.roblox.com/docs/studio/mcp-open-cloud

For Roblox, prioritize inspect→build→run→record→debug→repair with Rojo, StyLua, Luau/Studio checks and working gameplay evidence. For other subjects (Blender, VFX, sound, web, hardware, science), require the domain's own verifiable checks. Source citations, date-sensitive freshness, empirical comparisons, rollback and mistake logs must be first-class features. Research volume alone is not intelligence.

## 6. Next integration milestones

**Implemented here:** deterministic cyclic latency jitter, strict trace bounds, per-capture deadlines, synthetic p95/max/total, tests and claim ledger. Original default behavior remains intact.

**First next milestone:** Record privacy-scrubbed *actual* host inference/input timing from private gameplay alongside OBS/voice load, and replay those traces through this same engine. Time origin, session/version and source of trust must be explicit. No personal chat/audio in test artifacts.

**Second:** Preregister sealed games and matched conditions; compare model/router/voice optimization effects on task success and p95, not cherry-picked wins. Calibrate only on training tasks and report every holdout failure.

**Third:** Perform a sustained opt-in private Windows end-to-end session with real authorized game input, locally audible speech, avatar animation, OBS recording, and GPU/CPU/VRAM and quality-of-experience telemetry. Production stream remains disabled pending human review.

## 7. Evidence ledger

| Claim | Status |
|---|---|
| Varying synthetic delay changes world-clock outcomes | Verified by offline unit tests |
| Deadline compares each actual simulated delay | Verified by offline unit tests |
| Deterministic p95/max/total and original fixed-delay path | Verified by offline unit tests |
| Increased neural intelligence or tokens/sec | NOT demonstrated |
| Actual real-game autonomy, speaking VTuber or OBS readiness | NOT demonstrated |
| Real-world improvements from CPU TTS/speculative decoding | Needs matched Windows measurements |

### Reproduced private counterfactual (synthetic, not real games)

With the same fixed moving-hazard map and independently controlled patrol, an all-zero delay trace completed the goal in **6 moves**, while the alternating (0,1) decision-delay trace collided with a moving hazard during reasoning and **failed**. With a sparser (0,0,1) trace it completed the goal again. Both delayed traces had a maximum of 1 tick: outcome depended on *when* slow frames occurred, not just worst-case latency. This is a deterministic engine result, not evidence of gameplay skill gain.
