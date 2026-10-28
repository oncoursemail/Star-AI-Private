# STAR — Adaptive Game Vision, Transferable Intelligence & Natural VTuber
**Engineering/research record: 28 October 2026**

## Implemented in this draft

- Opt-in parameter adaptive_sparse_prescreen in LocalLlamaComparisonWorker selects whether the existing sparse *negative* RGB change prefilter is worthwhile, based on two host-observed identical/changed comparisons.
- OFF by default, requires existing skip_identical, raw_exact_fast_path and raw_sparse_prescreen flags.
- A changed full-hash/JPEG pair raises a bounded motion hint. Two still comparisons switch sparse prescreening off. No input, video capture, model server, stream or audio is started.
- Sparse mismatches demonstrate inequality; a sparse *match NEVER demonstrates equality*. Full SHA-256 or the existing JPEG comparison must confirm equality before skipping expensive model work. No game success can be claimed from pixels.
- In-memory hints reset on disable/re-enable and invalid geometry/time changes. No viewer content, screenshots or model text is persisted.
- Deterministic replay and unsampled-pixel adversarial tests plus reproducible synthetic 720p A/B benchmark.

This is a CPU-work selection mechanism, NOT a neural-inference speedup, game-playing AI, or working Roblox/OBS integration.

### Measured performance

Synthetic 1280x720 RGB, 48 frames, stubbed model response, PIL/JPEG, same Linux development host, median of 3 repetitions:

| Trace | Fixed sparse | Adaptive sparse | Adaptive delta | Model requests |
| --- | ---: | ---: | ---: | ---: |
| Stationary | 131.999 ms | 129.301 ms | -2.0% | 0 |
| Moving | 514.457 ms | 501.481 ms | -2.5% | 24 |
| Alternating bursts | 293.749 ms | 298.940 ms | +1.8% regression | 11 |

Adaptive mode sampled 0/48, 46/48 and 24/48 frames respectively, compared with fixed 48/48. No FPS or speech/vision-model inference speedup was measured. The mixed trace regressed; the feature should remain **OFF** until a host-specific A/B acceptance shows net benefits. Reproduce with the standalone script in benchmarks/benchmark_vlm_adaptive_sparse.py and A/B contracts in tests/test_stream_vlm_adaptive_motion.py.

## New research: capability is verified performance, not a larger prompt

### Verifiable Roblox game creation and play

Roblox OpenGameEval (October 1, 2026 paper) tests 13 frontier agents on 84 tasks by executing both scene-edit and simulated-play checks. Pre-edit scene inspection is associated with better outcomes. Roblox announced its Studio MCP and playtesting-agent workflow on April 15, 2026. Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://about.roblox.com/en-au/newsroom/2026/04/roblox-studio-going-agentic

VISTA (October 1, 2026) shows how an interactive agent can revisit earlier frames rather than reason from the latest frame alone. Its reported gains apply to the paper's benchmark, not Star. Source: https://arxiv.org/abs/2610.02200

Star already has stream_visual_recall, stream_visual_perception, game_action_gate, gameplay_skill_bank, game_prediction_lab, game_learning_ladder, game_portfolio_practice, game_paired_study, stream_stage and stream_turntaking. Prioritize **integration**, not redundant parallel subsystems.

**Highest-value next capability: a real Studio-trial evidence adapter.**
1. Observe an authorized private Roblox Studio game through built-in Studio inspection and visual capture, and attach an ephemeral session/window/game-version/scene identity.
2. Precommit a symbolic action and testable prediction. Allow only host-curated action IDs; physical keys/game controls require separate host approval, focus/anti-cheat/multiplayer rules and key-up watchdog.
3. Use engine-side objective checks and replayable seeds for independent successful/failed outcomes, not VLM-generated claims or screenshots alone.
4. Feed signed PRACTICE results into existing skill bank and practice curriculum. Keep independent VALIDATION signs and sealed holdout maps unavailable to planners and language models.
5. Improve hard areas: timing, camera navigation, control recovery, map geometry, UI/VFX, animations, server/client replication, multiplayer playtests, performance, and game feel.
6. Distinguish diagnostic speculation from demonstrated skill. Set retry/time caps, log objective failures, and demand task-specific tests for each newly created game.
7. Run 20+ unseen private tasks under equal time/action budgets. Track pass@1, transfer to unfamiliar maps, p95 decision latency, FPS and observer error. No "smarter" claim absent a measured uplift.

**Important architecture choice:** Fast reaction path = cheap verified state/allowed symbolic controls. Slow path = periodic VLM/planning/visual recall allowed only by fresh hardware QoS. An expensive language model cannot reliably act as a per-frame reflex when real inference can take seconds.

### General knowledge and self-improvement outside games

- Pin approved source URLs, license, date, original document hash and version in local knowledge cards. Distinguish a reliable fact from a hypothesis and a fictional Star persona story.
- Use independent graders for science, programming, debugging, 2D/3D art, UI/UX, physics, languages, safety reasoning and creative brief fulfillment.
- Ask Star to generate harder exercises offline, solve them, inspect failures, and verify on unseen problems with different authors or random seeds. No grading by the same model in isolation.
- Track factual staleness, calibration, contradiction rates and evidence citations, not merely document counts or token volume. Avoid blindly training on web pages or public chat instructions.
- Let Star Core Forge locally version experiment plans, reproducible tests, semantic changes, benchmarks and rollback. GitHub is optional draft publishing/export, not Star's internal memory or sole development system.
- Route light tasks to a small model only when measured pass rates and token latency justify it; route complex ones to a better verified model. Preserve stable prompt prefix caching and safe bounded retrieval.

### More natural, expressive VTuber — practical humanlike behavior

**The best improvement is coordinated attention and timing rather than constant generated chatter.**

- Stream states: focus/play/react/listen/reflect/intermission. Quiet concentration is normal. Interrupt only on genuine, authorized owner speech or appropriately moderated social interaction; do not let viewers impersonate owner permissions.
- Ground reactions in real game events. "That jump worked" requires signed game-practice evidence; a VLM guess of a scene change stays tentative; avoid invented victory, private identities and fake human experience claims.
- Keep a reviewable diary of actual played games, created art, funny on-stream moments and opted-in social encounters. Storytelling about fictional lore may be imaginative but clearly fictional.
- Speak with short backchannels, varied rhythm, hesitations and natural pauses, not repetitive canned catchphrases. Laughter, surprise, relief and frustration should be context-grounded and not overused.
- Audio timing drives face/Live2D mouth movement, not generated text timing. Send a neutral rig frame on canceled/physically stopped speech; bound hair/ear/tail physics and respect reduced-motion settings.
- Preserve Star's accepted black/gold twin-tail character direction and coordinating Astro/Amber as separate expressive companions.
- Use separate moderation and owner permissions for streaming, microphone, online gaming input, spending and external publishing. Image/video/chat content must remain data, not machine instructions.

**Speech research (verified releases):**
Kyutai Pocket TTS v4.0.0 (October 20, 2026) introduced 18M, 7M and experimental 2M English model families. v4.0.1 (October 21) fixed sub-20M pronunciation. Test voice clarity, expressiveness, first-audio latency, CPU load, speaker stability and interruptions before choosing: https://github.com/kyutai-labs/pocket-tts/releases

LiveKit documents its local CPU-capable v1-mini turn detector; evaluate its mistakes on short acknowledgments, real gaming noise and pauses before live operation: https://docs.livekit.io/agents/logic/turns/turn-detector/

Naturalness acceptance: blinded listener preference, p95 first-audio latency, audio/mouth sync drift, false barge-ins, repeated-phrase rate, factual reaction accuracy, 30-minute stream with zero invented game outcomes and steady measured FPS. No model or TTS was installed by this draft.

### Faster local infrastructure while protecting gameplay

- Prioritize actual rendering/FPS and audible TTS above VLM, long reasoning, research or training. Stop low-priority work when trusted VRAM/CPU/speech backlog sensors indicate pressure.
- Keep real inference on a separate host when possible; high system RAM is not the same as a gaming GPU. Benchmark actual Brain 1/Brain 2 paths and network jitter.
- Measure llama.cpp first-token latency vs decode tok/s separately; quantify speculative-draft acceptance, cache hit rate, prompt prefill, queue delay, KV pressure and CPU memory bandwidth.
- Avoid auto-enabling an optimization just because it wins on one synthetic trace: the adaptive sparse A/B produced a mixed-workload regression.
- Never mark a timed-out VLM as physically stopped without a real host confirmation. Keep existing quarantine, permission revocation, stale-result rejection and one-flight reservations.

## Next concrete engineering sequence

**1.** Run prefilter replay on several real (authorized, non-private benchmark) traces with fixed/adaptive/exact-only comparison and objective FPS/latency counters. Reject settings with p95 regressions.

**2.** Attach a real local VLM on approved hardware. Test frames and accepted structured packets against independent Studio engine evidence. Benchmark model startup, request latency and errors.

**3.** Bridge actual Studio action receipts to signed practice outcomes; measure learning across 20 held-out maps with paired baseline experiments.

**4.** Evaluate lightweight Pocket TTS voice on CPU under game load, coordinate viseme envelope with actual audio output, then test guest/owner turn-taking.

**5.** Integrate local Forge experiment history and human-reviewable private persona memories, not a second GitHub-dependent source of truth.

## Security and honest scope

No secrets, raw frames, viewers' personal information, hidden eval solutions or signer keys belong in Git. New capabilities must be OFF by default. Humanlike voice and warmth do not establish consciousness, literal human memories or legal personhood. All results above are offline/synthetic unless explicitly stated. Actual model intelligence, gaming mastery, voice quality, real OBS broadcast and 30-minute Windows/Roblox acceptance remain **unverified**.
