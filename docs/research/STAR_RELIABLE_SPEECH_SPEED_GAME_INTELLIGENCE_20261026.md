# Star AI — Evidence-backed Speed, Intelligence, Gameplay and VTuber Research
**26 October 2026 | Engineering note and prioritized architecture**

## What this change actually implements

The existing streaming latency recorder measured p50/p95 **only for turns with audible speech**. If difficult turns failed or were interrupted, they disappeared from the latency percentile: misleadingly fast streams could be rewarded. The existing offline paired-quality comparison compared supported responses against a baseline but had no minimum absolute useful-answer rate.

This update changes two existing modules, with regression tests:
- star/stream_latency.py: report all-attempt completion and on-time audible fractions, plus completed-turn p95; do not declare latency "within target" with less than 95% completed-audible coverage. An owner interruption can be intentional: treat low coverage as inconclusive rather than diagnosing the cause.
- star/stream_quality.py: require at least 90% grounded useful responses among human-reviewed "should reply" opportunities for a faster candidate to be considered for independent review. Show any extra failed or cancelled required replies.
- No models, game controllers, OBS streams or TTS backends are started by this patch. No speed or model-intelligence improvement has been measured by it.

## Highest-value architecture for Star

### A. Separate fast action, conversational response and deliberation
Build three execution lanes. A reflex lane samples relevant game state and chooses among host-authorized actions with strict observation-age and deadline checks; it outputs a safe no-op on uncertainty. A conversation lane processes selected chat, VAD and real game events with independent first-audible and completion metrics. A deep-research lane works offline: multi-step reasoning, retrieval, Roblox code/build generation and independent verification. StreamBrainGovernor should reserve resources only from trusted host telemetry and should throttle the last lane first.

This design beats simply using a bigger model for every frame: performance is judged by game FPS, action accuracy, timely audible speech and measured quality, not token count alone.

### B. Turn gameplay into reusable skills — but prohibit self-scored mastery
Combine the present StudioPracticeRunner, GameMechanicProbeLab, GameLearningLadder and GameplaySkillBank. Every training attempt should be scoped by game+version+objective+scene/seed, use a limited symbolic action set, log input-delivery acknowledgements, and require externally signed outcome evidence. Maintain a replayable, owner-reviewed skill library and inject verified skills into new levels.

Transfer claims require sealed holdout levels and multiple games with matched baselines, as in game_transfer_eval; never let the practicing model see held-out outcomes. A promising result in an easy game does not prove unfamiliar-game fluency. Voyager's growing executable skill library and SIMA's visually grounded multigame action research are useful directions, not proof of Star's current abilities.

### C. General knowledge that stays correct as it grows
Create a local provenance-first knowledge ledger: source/license, observed timestamp, summarized assertion, confidence, revision and contradiction edges. Keep private data separate from viewer-approved facts. Retrieval remains opt-in/default-OFF where configured. Use independent abstention and citation checks on fresh, withheld general knowledge tasks across science, history, mathematics, software, media and planning. Weight calibrated "I do not know" over fabricated knowledge. Cache only verified, versioned results and invalidate on source changes.

### D. Roblox creation with deterministic structural tests
First inspect Studio instances and scene relationships, then generate geometry. Use semantic attachment constraints for doors, floors, walls, railings, lights and props. In independent playtests check intersections, floating/supportless parts, mesh scale, UV/material consistency, Z-fighting, camera clipping, light exposure, platform navigation, GUI anchor/safe-area overlap and game-loop correctness. Compare multiple camera viewpoints, not a single hero screenshot. Gate acceptance on playable engine tests plus human quality review, not generated-code elegance.

Roblox announced a built-in Studio MCP server and automated playtest input in March 2026. Those facilities make this practical to integrate, but they do not automatically provide autonomous game mastery.

### E. Human-natural, clearly AI-identified VTuber
- Use actual first-audible PCM and interruption-to-silence metrics, not time to generated text.
- Authenticate owner interruption outside model inference; guest speech is a hold signal, not owner authorization. Hardware must acknowledge stopping old playback and clearing old animation epochs.
- Have the chat director prioritize meaningful viewer questions and real gameplay events, allow quiet concentration, vary speech naturally, remember only verified personal experiences, and never invent a human biography. Star can be playful, funny and expressive while transparently AI.
- Test context-sensitive laughter and voice expressivity with blinded human listener ratings. Avoid repetitive canned laughs or faux emotion claims.
- Use VTube Studio expression/hotkey API for facial motion; physics-driven hair/ears require the rig physics layer. VTube Studio's own docs note that physics output parameters are not directly settable by expressions.
- Treat Twitch EventSub as at-least-once delivery; deduplicate by ID before expensive moderation, reject very old events, and keep bounded chat workloads and reliable reconnect cleanup.

### F. Speed on practical hardware
Quantized models, KV caching, prompt reuse, n-gram or draft-model speculative decoding, CPU/GPU queue admission and background-work deferral are *candidates*, not guaranteed wins. Benchmark a single unchanged model/task, matched prompt lengths and workload, stable thermals and repeated trials. Include memory peaks, game PresentMon frame times, token latency, first-audible latency and chat correctness.

Kyutai's October 2026 Pocket TTS small English 18M/7M/2M CPU models are worth a controlled pilot. They may preserve 8GB-GPU headroom but also differ substantially in timbre and emotional quality. Do not adopt based on manufacturer speed claims alone. llama.cpp supports several forms of speculative decoding; on small hardware, a draft model can cost more resources than it saves.

The connected Linux starai host currently reports 48 logical CPUs, 125 GiB RAM and no nvidia-smi utility. This is not equivalent to profiling the Windows gaming/streaming machine.

## Experiment acceptance criteria

| Dimension | Measurements | Candidate fails when |
| --- | --- | --- |
| Audible speech | P50/P95 time-to-first-audible; all-attempt completion; on-time audible proportion | 95%-completion floor fails or p95 exceeds a declared budget |
| Response quality | Matched context, human-reviewed grounded useful replies, silent/failed/cancelled required opportunities | <90% useful response coverage, more unsupported claims or interruptions |
| Game fluency | Independent paired game success on preregistered sealed cases | Missing runs, leakage, regressions masked by easy cases |
| Game construction | Playtested scripts, collision/traversal/texture defects, multi-view human inspection | Defects, missing assets or unplayable paths |
| General knowledge | Fresh withheld accuracy, grounded citations, abstention calibration | Confident unsupported facts or heldout contamination |
| System speed | Measured token/s, TTFT, CPU/RAM/VRAM peaks, p95 FPS, audio latency | Better benchmark with worse game frame times, correctness or audio |
| Expression | Human reviewer scores for voice/laughter, lip-sync and turn timing | Mechanical laugh/intonation or stale avatar expression |

The comparison modules can *recommend* a candidate for owner review; they cannot authorize game controls, streams, deployment, self-updates or promotion. Preserve offline tests, independent evaluation keys and all existing default-OFF gates. Star Core Forge should run this gate locally even if GitHub is unavailable; GitHub is optional for publishing.

## Next concrete integrations

1. Capture physical Windows audio playback acknowledgements, VAD, real frame timings and host-monotonic stage timestamps into an isolated local benchmark.
2. Pilot Pocket TTS versus existing voice with fixed written/played utterances, normal/cat/puppy character delivery, real device interruptions and listener quality ratings.
3. Exercise the existing private Roblox Studio action pipeline on real bounded episodes; score all attempts independently, then run unseen-level holdouts.
4. Add novel self-proposed skills only after simulator validation, defect inspection and signed test evidence; never let training inspect heldout outcomes.
5. Use a source-backed knowledge ledger, evaluation calibration and versioned conflict resolution for broader facts. Track accuracy alongside speed, not a vague "intelligence" number.

## Primary sources (reviewed October 26, 2026)

- Twitch EventSub transport/dedup/replay: https://dev.twitch.tv/docs/eventsub/ and https://dev.twitch.tv/docs/eventsub/websocket-reference/
- Roblox Studio built-in MCP and playtesting, March 5 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Google DeepMind SIMA, March 13 2024: https://deepmind.google/blog/sima-generalist-ai-agent-for-3d-virtual-environments/
- Voyager open-ended Minecraft agent, 2023: https://arxiv.org/abs/2305.16291
- Kyutai Pocket TTS, October 2026 small models: https://github.com/kyutai-labs/pocket-tts
- VTube Studio API and expression/physics caveats: https://github.com/DenchiSoft/VTubeStudio and https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-%28a.k.a.-Stickers-or-Emotes%29
- llama.cpp speculative decoding reference: https://github.com/ggml-org/llama.cpp/tree/master/docs

**Integrity:** this is a falsifiable development roadmap, not a claim that outside technologies were installed or benchmarked. Neither passing unit tests nor descriptions of a humanlike persona prove higher neural intelligence or human consciousness.
