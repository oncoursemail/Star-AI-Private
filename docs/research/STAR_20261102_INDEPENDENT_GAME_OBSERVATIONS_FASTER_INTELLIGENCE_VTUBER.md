# STAR AI — Independent Gameplay Evidence, Real-Time Intelligence and VTuber Roadmap
**Research date:** 2026-11-02 (America/Chicago). **Scope:** Star AI / Litha successor codebase; owner-only autonomous game practice, verified capability improvement, streaming presence and hardware-aware inference.

## Executive finding: intelligence improvements need independent evidence

STAR can be made *apparently* smarter without becoming better if its practice and validation counters accept repeated copies of one observation. The signed gameplay ledger had this defect: separate trial IDs, run IDs, HMACs and timestamps were treated as independent even when every trial pointed at exactly the same `evidence_sha256`. An agent could obtain an apparently strong statistical estimate by replaying a reviewed screenshot/observation. Duplicate receipts are not independent Bernoulli samples.

**Pre-change reproduced failures in offline unit tests**:
1. Five signed repetitions of one practice capture produced `rehearsal_only` despite only one distinct observation.
2. Five independent practice captures plus eight repetitions of one signed validation capture produced `ready_for_host_review`.
3. Twenty-five repeated signed holdout captures produced `bounded_transfer_evidence_for_owner_review`.
4. A capture signed in source training and re-signed under an otherwise good target holdout could still qualify as independent transfer.

**Implemented**: validate every scoped signed record, collapse same-digest repeats to one earliest observation, reject same-observation conflicting action/split/outcome, and refuse purported cross-game validation that reuses a source-training observation. Model-facing practice views remain validation-blind; receipt keys remain host-only; the bank still cannot control games or broadcast. Tests now generate genuinely distinct observations for distinct synthetic attempts. The dedup is deliberately conservative: identical bytes can sometimes occur in two real static attempts, so future capture providers need a signed independent event envelope with episode/game/version/process, monotonic capture sequence, experiment allocation, and trusted result witness. **HMAC authenticates a signer; it does not prove that the signer saw a real game outcome.**

**Boundary**: This change improves how learning claims are *evaluated*, not LLM weights, raw tokens/sec, gaming win rate or observed humanlike behavior. Repeated synthetic tests are not hardware rehearsal. Existing databases remain on the same SQLite format; no secret migration is needed. Future schema migration should consider separate immutable `observation_id` and signed `experiment_id` independent of image bytes.

## Research 1 — Live-clock gaming intelligence

**October 14, 2026**, Pan et al., *The World Won't Wait / RealtimeBench* (arXiv:2610.20665), test agents on 180 continuously running game tasks across six game types. A slower but more capable agent can lose to a faster student when the environment is *not paused*. A two-timescale offline teacher reviews failures and tests modifications away from the live match; a quick student runs without teacher calls during active play. Researchers report improvement from **13.51 to 24.19** average progress after two iterations; these are **not STAR metrics**. Source: https://arxiv.org/abs/2610.20665

**Practical Star architecture**:
- **Observe**: window-scoped authenticated game frame, exact process identity, monotonic capture time, scene/version, focus check, confidence and evidence hash. Sample HUD, minimap, hazards and action affordances at different rates; never process entire desktop by default.
- **Fast loop**: curated small model plus deterministic emergency reflexes; bounded candidate symbolic actions, explicit release deadlines, stale-frame rejection, OBS transition epoch checking and independent OS key-up watchdog.
- **Slow teacher**: only offline/paused attempts; failure diagnosis, mechanics testing, plan hypotheses, replay tasks, tool-assisted research, independent evaluations and persisted signed lessons. Never freeze a live game to ask the teacher unless the host/game allows it.
- **Promotion**: preregister experiment, train on practice, evaluate on unseen maps/versions/opponents, require genuinely distinct evidence and compare elapsed-time success with matched GPU/OBS conditions. Evaluate worst-case latency, timeouts and cancellations, not only mean tokens/sec.
- **Curriculum**: start with single-player/local sandbox steering/jumping, then timing/combat/pathing, games with unfamiliar controls, and finally generalization to held-out levels. Use separate policy/legal approval before online multiplayer, no anti-cheat circumvention.

**Measured outputs**: task success before deadline; 95th/99th percentile end-to-end decision latency; stale-action percentage; game FPS p1/p50/p95; practice-to-holdout generalization, deduplicated observed outcome count and confidence intervals; failed release receipt count (must remain zero before live input).

## Research 2 — Low-latency on 8-GB Nvidia gaming GPUs

Existing Windows read-only inventory in this run detected RTX 3060 Ti. A simultaneous OBS + game + avatar + LLM deployment must be benchmarked under *actual* peak VRAM load, not an idle inference benchmark. Treat 8 GB as a physical memory boundary; do not claim model fit or token rates without testing token context, KV size, offload and game memory use.

**Experimental matrix** (offline, opt-in):
- Local llama.cpp configurations: CPU fallback vs safe partial GPU offload; quantization, KV cache options and context length matched to actual prompt length. Compare only completed responses with correct answers. Protect game FPS by explicit GPU budgets and reserved memory for renderer.
- Cache evaluation: stable system prefix and retrieved verified skill pack; compare cold/warm prompt processing, cache hit rate, wasted memory and interruptions. Do not let a stale skill re-enter a new game session through cache identity errors.
- Speculative decoding: llama.cpp SPEED-Bench reports draft-token acceptance, throughput and latency. Benchmark no draft vs n-gram vs an adequately small draft *on the same* machine; avoid assuming speculative decoding improves gaming latency. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Teacher only between attempts: CPU/RAM-heavy tasks while the GPU is occupied by rendering; night practice can use otherwise idle GPU within thermal/CPU limits. Prefer scheduling and bounded RAM/prefix caching over RAM dumping or unmeasured 80-GB KV ambitions.
- Prioritized, preemptible jobs: game input > emergency stop > live conversation/audio > capture/perception > offline teacher/training > asset generation; prove that cancellation physically drains the previous worker before reusing its compute slot.

**Gate**: no admission to active GPU inference on unsupported or stale host telemetry; comparison must include streamer frame drops, OBS skipped/dropped frames and audible voice latency. Baseline must run same game/scene and caption load. Reject purported speedups with worse decision accuracy or sound.

## Research 3 — Humanlike *interaction*, not deceptive identity

**May–June 2026**, Yan et al., *Proact-VL*, ICML 2026: proactive video-language companion research evaluates gaming commentary, co-commentary and guidance, emphasizing when *not* to speak and balancing latency/quality/quantity. Sources: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ and https://proceedings.mlr.press/v306/yan26c.html

Star VTuber behavior architecture:
- **Priority**: owner interruption > genuinely urgent gameplay cues > addressed viewer question > co-stream collaboration > infrequent ambient dialogue. Permit meaningful silence when concentrating or listening.
- **Turn taking**: VAD/STT followed by endpointing with measured transcript revisions; start speculative **text-only** generation if compute allows; commit only against the matching final moderated transcript and exact full prompt digest. Cancel provisional speech on a changed transcript or gameplay deadline. LiveKit's current turn-tuning guide distinguishes endpointing, interruptions, false interruptions and preemptive TTS costs. Source: https://docs.livekit.io/agents/logic/turns/tuning/
- **Speech**: benchmark CPU-only Kyutai Pocket TTS 4.0 Oct 20 2026 English 18.2M/6.9M/1.9M variants against a local baseline; 1.9M is experimental, and smaller does not guarantee good voice. For any custom Star voice, use approved/owned voice samples. Compare time to *audible* first word, intelligibility, prosody, game frame loss and interruptions, not just raw generation time. Sources: https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0 and https://github.com/kyutai-labs/pocket-tts
- **Avatar**: lips from actual audible PCM envelope, eye/gaze/blink movements during silence, expression strength proportional to verified events, moderate physics and reduced-motion support; explicit rig/audio epoch resets on interruption. Distinguish queued utterance from physically heard one. Avoid fixed periodic catchphrase spam.
- **Persona and memory**: persistent user-approved persona, private day journal of *verified* actions/results, uncertain first-person language ("I think", "I saw") for tentative game observations; Astro/Amber as character interactions that are clearly synthetic. Maintain personality consistency without claiming human consciousness, inventing achievements or falsely representing a human operator.
- **Social controls**: host-moderated chat ingestion, no viewer tool-authority escalation, configurable viewer consent, no personal identity extraction, safe recording policies. No autonomous livestream until owner explicitly approves broadcaster credential use and rehearsal passes.

**Humanlike quality measurements**: false interruption rate; viewer question response accuracy/freshness; average and p95 first *audible* word; percent speech referencing a real verified event; silence ratio for non-relevant gameplay; avatar lip-audio sync drift (median and p95), moderator incidents, reported conversational naturalness from a blinded preference test.

## Research 4 — End-to-end Roblox/game building

**October 2026**, Roblox's official *OpenGameEval* project evaluates agents inside reproducible, stateful Roblox Studio environments with executable scene and simulated-play checks. It finds that observing affected objects before editing correlates with successful solutions. Source: https://github.com/Roblox/open-game-eval ; https://arxiv.org/abs/2610.02563

**Pipeline**: read project and assets -> map dependencies/API versions -> generate multiple candidate Luau scripts/scene edits -> apply in isolated Studio Lab clones -> run StyLua, Selene, Luau analyzer/typechecks and independent simulator tests -> verify placement/collisions/network replication and multiplayer semantics -> take actual annotated screenshots/video for visual review -> score reproducible playtest end-to-end -> merge only a verified candidate and retain rollback. Prioritize **fully playable tasks** over polished screenshots or compiling code without a session.

**Cross-domain knowledge expansion**: verified topic packs (Luau/Roblox API, mechanics, design/animation, Blender, Rust, Linux/Windows, game-specific lore where licensed) with citations/last-checked dates and retrieval-scoped freshness. Generate tougher novel tasks from observed failure gaps; separate training practice material from heldout tests; measure transfer to game versions Star has not seen. Autonomous experimentation and promotions should remain auditable inside the local self-owned Forge; GitHub optional publish bridge.

## Engineering acceptance / prioritized integration

**P0 — Completed here**: independent observation dedup and signed cross-scope replay guard; adversarial tests. Run targeted + full relevant regressions, Ruff, byte compilation, published GitHub-file hash verification. Keep draft stacked PR, main unchanged.

**P1 — Actual Windows nonbroadcast rehearsal**: launch/attach authorized OBS (recording only), VTube Studio, local inference worker, owner-approved single-player/local sandbox game. Pin process + HWND identity; connect the already developed OBS event witness, game controller, host dispatch API and independent OS key-up watchdog. Record sanitized actual audio/P95 latency, FPS and OBS statistics; verify physical key release on emergency stop. Never infer readiness solely from mocked ports or installed executables.

**P2 — Fast/slow split and compute experiments**: finish paired live-clock game suite and SPEED-Bench variants across stream states; student policy candidate promoted only on genuine independent validation, including new game levels.

**P3 — Natural streaming without false experiences**: measured speech endpointing/cancellation, CPU TTS A/B, on-air event grounding, original rig avatars, story continuity, audience moderation, honest AI identity and careful consent.

**P4 — Autonomous game creation/general learning**: Studio Lab isolated tasks, builder/playtester/evaluator roles, visual and behavior checks, return real game artifacts and verified skills, not self-graded code success.

## Explicit unknowns

- No completed real-game session, winning run, Twitch/YouTube live broadcast, synchronized audible audio or Windows physical-input watchdog is proven by this Linux-only patch.
- Deduplicating one `evidence_sha256` within a game scope is a conservative heuristic, **not** proof that distinct digests are independent observations; future capture signing should include a trusted event-run ledger and OS/game process identity, and forbid one frame being reused under many experiment allocations.
- Quality and speed claims are withheld pending system-level benchmarks. Earlier offline test totals are test coverage numbers, not model ability metrics.
