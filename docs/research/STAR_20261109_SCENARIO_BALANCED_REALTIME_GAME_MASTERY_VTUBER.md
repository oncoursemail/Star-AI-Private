# STAR — Scenario-balanced real-time game mastery and generalist VTuber research

**Reviewed:** 2026-11-09. **Status:** implementation plus offline tests in a draft PR; no native Windows gameplay, OBS broadcast, neural model tuning, or production deployment.

## Why this change matters

STAR's prior assess_live_clock compared independently reset baseline/candidate episodes, game-world progress during inference AND OS-input acknowledgement, matched host-observed outcomes, OBS/game QoS, exact paired win significance, and a positive progress interval. But its three-scenario minimum could be satisfied by **22 attempts from one easy stage and one from each of two unfamiliar stages**. The easy stage dominated the global progress estimate and latency p95. A generalist game-playing agent must not be certified on this evidence.

**Implemented:** inverse-Simpson effective-scenario coverage, scenario-specific progress regression, and scenario-specific host-observed action p95 regression diagnostics. Single-sample distinct stages remain valid diversity contributions, so a wide 24-map holdout is not punished merely for having one distinct state per map.

Formula: effective scenarios = N² / sum(n_scenario²). Eligibility now requires at least three named scenarios AND effective diversity >= 2.5, in addition to previous live-clock and outcome gates. A 22/1/1 distribution has effective diversity ~1.19; balanced 8/8/8 has 3.0. **This is a screening heuristic, not proof of independence of seeds, maps or trials.**

A cohort must not sacrifice measured progress in any scenario (mean paired gain < -0.01) or substantially slow action p95 on one level (>10% AND >20 ms), even if the pooled score looks faster. These regressions produce regressed, while insufficient coverage remains inconclusive. Results only expose aggregate counts, not screenshots, chat, accounts or game/player IDs.

## Research verified November 9, 2026

1. **Real-time competence differs from relaxed-time reasoning.** Gym-Anything-RT, submitted October 27, 2026, uses 100 playable real-time mini-games and paused/slowed counterparts. Design deadline-sensitive policies, not just stronger text reasoning. Source: https://arxiv.org/abs/2610.37567
2. **Proactivity is a learned policy.** Microsoft's Proact-VL (ICML 2026, May 2026) evaluates gaming companions that choose WHEN and HOW MUCH to say. Treat silence as a valid action; measure comment relevance, response freshness and natural cadence under load. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
3. **CPU speech has real resource tradeoffs.** Kyutai's Pocket TTS announced 18.2M, 6.9M and 1.9M English models in October 2026. Benchmark pronunciation, first audio, consistency, CPU contention and voice quality on STAR's hardware. Published model throughput is NOT measured performance on STAR. Source: https://github.com/kyutai-labs/pocket-tts
4. **Roblox Studio supports agentic plan-build-playtest-repair.** Roblox's April 15, 2026 roadmap and November 4, 2026 MCP Open Cloud expansion support permission-scoped QA, analytics and asset imports. Publishing, monetization and changing live settings require separate owner authority. Sources: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic and https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
5. **Natural voice requires interruption discipline.** Full-Duplex-Bench-v3 (April 6, 2026) explicitly evaluates disfluencies, chained tasks, latency and interruption avoidance. Record speech-start and physical audio-stop separately. Source: https://arxiv.org/abs/2604.04847

## Actionable architecture, in priority order

**1. Live performance envelope.** Preserve game FPS and OBS dropped-frame targets during concurrent game+model+avatar+TTS load. Connect the existing GPU-worker supervisor to real Windows process ownership and verified stop/exit acknowledgements. Optional workers remain disabled by default.

**2. Game-playing intelligence.** Split perception (fresh timestamped frame and uncertainty), bounded fast reaction (running-world deadlines), tactical planning (when time permits), and offline teacher practice. Validate real OS-input acknowledgements and independently observed game-state success, NOT model self-evaluation. Fix practice mistakes, without looking into hidden evaluation cases.

**3. Verified learning and autonomous creation.** Curate authorized practice mechanics, invent harder practice tasks within host-approved constraints, run Roblox Studio test agents, inspect logs and visual outcomes, repair and rerun. Test transferable skills across new maps AND separate games. Promotion requires separately sealed holdouts and reviewer checks; signed data alone cannot prove scientific independence.

**4. Human-like but grounded VTubing.** Speak reactively about actual witnessed game events with natural silence, contextual jokes and expressive gaze; synchronize mouth/expressions to audibly delivered speech, not queued text. Prioritize viewer questions and owner interruptions. Use limited, explicit public memory approvals; never invent real feelings or a human past.

**5. Speed experimentation.** Compare model routing, quantization, prompt reuse, speculative decoding and CPU TTS with matched workload and real OBS/game pressure. Record p50/p95 first-speakable AND first-audible, response correctness, VRAM headroom, game p99 frame time, OBS dropped frames, native abort latency and voice quality. Reject changes with quality or gameplay regressions regardless of tokens/sec. No speedup is claimed from this PR.

## Reproduction and limitations

Run: python -m pytest -q tests/test_game_live_clock_benchmark.py

Native acceptance requires an owner-approved private nonbroadcast Windows rehearsal, independently observed game-state and audio evidence, randomized matched baseline/candidate order, frozen unseen scenarios and independent analysis. The new coverage metric neither authenticates a host nor deploys a model, plays a game, runs OBS or makes STAR a self-sufficient VTuber.
