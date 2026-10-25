# Star AI — real-time focus, verified improvement, game-playing and natural VTuber behavior

**Research date:** 25 October 2026 (UTC). **Status:** proposed development-only code + primary-source research; **not installed, integrated, trained, deployed, streaming or proven faster on real hardware.**

## What this contribution changes

The existing Star tree is unusually broad. It already has `brain_router`, `cache_banks`, `best_of_n`, `knowledge_bank`, `general_knowledge_benchmark`, `playtest_learning`, `selfplay_curriculum`, `skill_evolution_lab`, `agent_resource_planner`, `live_show`, audio/voice subsystems, Studio Lab, and more. Parallel **draft** branches are building `game_experience`/`video_study` (#579), `cognitive_governor` (#577), and two overlapping streamer directors (#580/#581). Creating another general-purpose brain, skill ledger, model router, streamer director or Studio controller would create incompatible copies rather than intelligence.

This increment instead gives #581 a specific new *interface and evaluation gate*:

1. **`star/stream_observe.py`:** an opt-in, local, bounded *vision admission* planner: novelty-aware perceptual-hash filtering, scene-change cues, periodic refresh, timed reservations, single-flight inference, per-minute token budget, live/offline cadence, monotonic timestamp checks, stale frame rejection, owner/capture opt-in and conservative GPU/FPS/voice-backlog deferral. No frames stored. It uses #581's `stream_budget` decision and adds an offline safety floor. Only a trusted host can turn a returned ticket into a real model call.
2. **`star/stream_quality.py`:** an independent, matched-case evaluator for hypothetical voice/stream configurations. A latency "win" is rejected if it silently drops baseline useful replies, talks over a human more often, increases unsupported statements or stalls the game. Requires same anonymous test cases, pinned context digests, and externally reviewed grounding. Never auto-promotes. This is a statistical *screening gate*, not proof of significance.
3. **`examples/stream_focus_rehearsal.py`:** a completely disconnected demonstration. A **synthetic** six-second/180-frame capture pattern admitted 2 optional vision requests and deferred 178; a synthetic 20-pair speech trace yielded a 31.82% lower p95 first-audible latency. Those numbers are examples of algorithm behavior, **not** real Star performance, resource savings, FPS, voice quality or verified game comprehension.
4. **34 offline unit tests** (this increment only), covering consent, novelty, urgent events, cold start, clocks, per-minute budgets, stale captures, timeouts, headroom, matched-case comparability, hallucination/talk-over/regression checks, and invalid inputs.

**No external-control tool, microphone permission, webcam permission, secret, network client, model weight, gamer input binding or OBS endpoint is included.**

## The big infrastructure redesign: Reflex / Reason / Practice

Star does not need to run the largest multimodal model on every 60 Hz game frame. Separate three lanes with hard resource and permission boundaries:

| Lane | Work | Deadline type | Hardware and recovery strategy | Correctness evidence |
|---|---|---|---|---|
| **Reflex** | Host-observed health, deaths, HUD/event cues, voice barge-ins, verified game/tool safety signals. | Frames/interrupts: urgent. | Lightweight local signal extraction; no general LLM for every observation; never rely on 1 Hz VLM for combat. | Host state, permitted game/test APIs, timestamped event correlation. |
| **Reason** | Select next goal, explain a tested event, form bounded plans, decide when to ask questions, generate short TTS reply. | 0.5–2 s conversation targets; measured, not assumed. | Existing Star model router, warm inference, stable cached prefix, async speech/vision workers, cancellable requests. | Answer grounded in explicitly observed / sourced facts; p95 first-audible measured via #581 `stream_latency`. |
| **Practice** | Video/replay study, Roblox design experiments, learned skills, source retrieval, offline A/B evaluations, 3D asset/animation rendering. | Minutes/hours with stop-and-resume. | Defer or move to non-stream brain; perform on disposable workspaces with caps. | Frozen development/holdout splits, independent tests, visual/physical evaluation, owner promotion. |

A *human-feeling* performer is not constant chatter. It is appropriate silence, quick reactions when clearly observed, no talking over a viewer, natural backchannels, expressive face/hair timing, stable personality, selective chat acknowledgement, explicit uncertainty, transparent AI identity and a reliable stop control. The voice pipeline should manage interruptions and recovery while gameplay runs independently. Star can have **fictional character lore**, clearly differentiated from literal claims about having lived a human life; avoid fabricating viewer relationships or memories.

### Timeline of information, not the same thing as an autonomous policy

- **Perception:** trusted local capture -> lightweight frame fingerprint, audio and in-game event adapters -> novelty/priority filter -> *optional* expensive VLM; attach game/build/session id and capture time. An image hash detects approximate change; it does **not** prove what changed or its causal meaning.
- **Event grounding:** correlate low-level events with multiple observations and, where possible, a game API or owner-approved Studio test. Tag `observed`, `hypothesis`, `refuted`, `verified` separately. A chat comment never upgrades itself to an engine event.
- **Gameplay:** goal -> known allowed action sequence -> short checkpoint -> state delta -> stop/fail/replan. Use a bounded list of supported games with dedicated adapters and permitted training environments. An observation governor is **not** a game-play policy.
- **Knowledge:** source URL/license/date -> extract -> citation -> reversible claim -> contradiction detection -> delayed retrieval/transfer quiz. A memorized fact or rendered frame is not knowledge unless it withstands objective tests. Retrieve a domain by need, not by dumping a giant wiki into every stream turn.
- **Self-improvement:** first-run results, task seed, game version, baseline/candidate config, independent referee, failure taxonomy, reviewer sign-off. Keep leakage-proof sealed holdouts. Do not let model feedback, viewers, or a self-graded "I'm smarter" report overwrite evidence.

## Primary research and engineering implications

**Embodied game learning.** [Google DeepMind's SIMA 2 research preview (13 November 2025)](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) describes language-guided reasoning, varied-game generalization and post-experience learning in controlled virtual environments. It establishes a research direction, **not** that Star has access to SIMA 2 weights or can self-train without a comparable dataset, evaluator and compute. [NitroGen (January 2026)](https://arxiv.org/abs/2601.02427), [open weights and implementation](https://github.com/MineDojo/NitroGen), studies gamepad actions from RGB frames across over 1,000 games and releases a benchmark. Evaluate it on a *permitted* locally reproducible subset before any adoption. Do not assume it fits 8 GB VRAM, works with keyboard/mouse or generalizes to Roblox as-is. Use model/asset/data license reviews and actual memory profiles.

**Long-horizon coding/gaming.** A [15 October 2026 paper by Faldor, Singh and Raileanu](https://arxiv.org/abs/2610.22319) reports four general-purpose Gemini agents beating a randomly generated Minecraft Easy world using Mineflayer, 2,783 self-written programs and 27 hours of play, but also 605 deaths. **Critical limitation:** Mineflayer provides structured game state and programmatic actions, not the ordinary player's screenshot-only experience. The valuable lesson for Star is reusable tools, compact shared notes, explicit task decomposition and recovery — with measurements of retries, failures, token spend and elapsed time rather than a success-story headline. Reproduce only in owner-authorized sandbox environments and separate one lucky run from general reliability.

**Roblox creation.** [Roblox, 5 March 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643) describes the built-in Studio MCP service and playtest automation. [Roblox, 9 April 2026](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767) introduced a Studio playtest-agent beta; [Roblox, 15 April 2026](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic) emphasized plan/build/test loops with project context. For Star: reuse guarded Studio Lab and add regression probes to *current* game maps; verify client/server physics, missing attachments, props, collisions, culling, wall connections, texture/UV appearance, multiplayer and FPS. A playable test place, game-server events and external screenshots are distinct sources of evidence. Live third-party games require separate authorization, platform compliance and anti-cheat boundaries — no silent cross-over from Studio test tooling.

**Speech naturalness.** [LiveKit turn-taking documentation](https://docs.livekit.io/agents/logic/turns/tuning/) makes explicit that end-of-turn, interruption detection, false-barge-in recovery and preemptive generation trade latency for possible wasted work. Test a tuned voice candidate in a private, non-broadcast rehearsal: quick acknowledgements vs full stops, small fillers, interrupted sentences, varied phrasing, laughter alignment, breaths, talking while game input is active. Do not add random human breathing/fabricated emotion to every response. A lively AI performer should never misrepresent being a biological human. VTube Studio and OBS integration remain separate owner-approved plugin/host bridges; credentials belong in local key stores, never in prompts or chat messages.

**Runtime acceleration.** [llama.cpp official server flags](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) document prompt cache and reuse options; [llama.cpp speculative decoding guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) describes multiple draft/verification paths. [OpenVINO GenAI 2026 documentation](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai.html) also discusses speculative decoding and hardware-specific benefits. These are *benchmarks to try*, not universal speedups. A second draft model can make an 8 GB GPU **slower** by consuming VRAM and bandwidth. Measure setup overhead, context hit rate, first audible p50/p95, accepted draft tokens, tokens/s, game FPS 1% lows, hard failures and model-answer accuracy. Cache keys require model id, exact tokenizer, system-prompt revision, LoRA/adapter revision, session privacy boundary and tool permissions. Never share potentially private KV/contexts across users or tasks.

**Source quality vs fluent hallucination.** Research sources can have mistakes, removed licenses, stale API contracts, fabricated claims and contaminated benchmark splits. Require dated citations or real owner-owned test evidence; refuse to invent gameplay facts from sparse 1 Hz snapshots. Test Star on mathematics, code, art mechanics, game physics, tutorials and common knowledge in separate pools. A good *unknown* is superior to a confident, false stream announcement. Project lore may be creative but must be clearly fiction.

## Cross-PC deployment profile (design, not activated)

1. **Streaming/game PC with RTX 4060 8 GB:** game render, lightweight reflex/event inference, avatar animation and OBS; protect video memory and frame pacing. Local speech playback or compact TTS only if measured stable. No heavy model training or high-resolution generative rendering while live.
2. **Brain 1 / server:** larger context reasoning, cached long prompts, retrieval indexes, evaluator and night-school practice when owner-enabled. Benchmark actual LAN round trip, queue time and cold starts; a remote server may be slower for immediate speech even if token throughput is higher.
3. **Brain 2 / Studio:** parallel authorized Studio playtest jobs, scene inspection, Lua testing and visual verification when idle. Do not steal the game's input focus or attach to a third-party game without permission.
4. **Graceful degradation:** in order, reduce optional vision sample rate, stop background learning, shorten spoken replies, drop accessory motion and extra overlays, leave core game FPS and owner interrupt audible. Never "optimize" by discarding required confirmations or bypassing sandbox rules.

## How to use the new code safely

```python
from star.stream_budget import StreamTelemetry
from star.stream_observe import FrameCue, ObservationGovernor

gate = ObservationGovernor(calls_per_minute=24, burst=2)
# A trusted host must separately verify screen permission and owner approval.
gate.enable(owner_approved=True)
telemetry = StreamTelemetry(live=True, game_active=True,
                            free_vram_mib=3500, total_vram_mib=8192,
                            game_fps=60, speech_backlog_ms=70)
# Hash/cue/timestamp must be locally captured by the host, not generated by LLM.
decision = gate.consider(FrameCue(1000, 0xABCD, "new_scene"),
                         telemetry, now_ms=1000,
                         capture_authorized=True)
if decision.admitted:
    # Trusted host invokes a separately authorized, deadline-limited local VLM.
    # Complete after real inference or mark failure. No code executes a model here.
    gate.complete(ticket=decision.ticket, now_ms=1050, succeeded=False)
gate.disable()
```

For measurement, collect matched anonymous opportunities *before* tuning the candidate, blind independent reviewers to route, keep paired context digests, measure p95 on shared audible cases, verify no drop in grounded replies or added interruptions, and call `compare_stream_profiles`. Caller-supplied `reviewed=True` and a digest do not cryptographically authenticate a referee. This module is only one release gate; independent confidence intervals and repeated holdout runs must be added in the existing `frontier_lab`/`eval_gate` path.

Run the new offline tests/demo:

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_stream_*.py' -q
PYTHONPATH=. python3 -m compileall -q star/stream_observe.py star/stream_quality.py \
  tests/test_stream_observe.py tests/test_stream_quality.py examples/stream_focus_rehearsal.py
PYTHONPATH=. python3 -m examples.stream_focus_rehearsal
```

**Important integration note:** #579's `video_study` operates on bounded prerecorded windows; this governor handles only *session-time candidate admission*. Its `FrameCue` does not add permission to crawl/download YouTube or videos. #577's cognitive outcome ledger handles development evaluation receipts; this quality gate handles bounded live-session *experience quality*, not model weight optimization. #580's streamer director overlaps #581's stream director; reconcile before merge rather than running both speech arbiters.

## Acceptance experiments and exact failure criteria

| Trial | Independent test | Minimum evidence for consideration | Hard stop or rollback |
|---|---|---|---|
| **A. Novelty-sampling** | Capture permitted 1080p gameplay frames with recorded event labels. Reuse identical 5-minute clips baseline fixed 1 Hz vs novelty governor. | Perception event recall and detection latency non-inferior; fewer VLM calls at same recall; actual GPU utilization/1% lows measured. | Missed high-impact death/mission/scene events or harmful game latency increase. |
| **B. Voice feel** | Double-blind reviewers rate 20+ matched turns per config; game, questions and mic interruptions prerecorded with consent. | Grounded answers not lower; p95 first audible improved; lower turn-overlap and no increase in fabricated claims; acceptable prosody/expressions. | Silent-fast cheating, overlap, unintended broadcast, model fabricating observations. |
| **C. Game learning** | Supported sandbox game; random seeds, unseen maps and safe controller; record first-attempt pass before retries. | Stable pass@1 improvement across independent seeds, capped GPU cost, reproducible skill transfer after game update. | Offline success but live-game violations, wrong-target actions, insufficient held-out evidence. |
| **D. Roblox builder** | Disposable place, client/server multiplayer tests, mesh/prop geometry audit + screen review with human design rubric. | Independent reviewers cannot reliably distinguish artifacts from agreed manual quality reference on predefined rubric; no unreviewed production writes. | Missing walls, floating props, texture flicker, intersections, failed Studio physics, regressions. |
| **E. General knowledge** | Frozen dated QA and practical transfer sets by discipline. | More correct sourced claims and honest abstentions, measured at matched latency; no train/eval leakage. | Confident unsourced statements or unverifiable claims of consciousness/superhuman intelligence. |

**Targets to measure, not promises:** for the first integrated prototype, record conversational first-audible p50/p95 against the current app, game FPS/1% lows, VLM calls/min, GPU VRAM headroom and missed scene events. No target latency, speedup or "higher intelligence" is claimed reached by adding these modules. Sample count and A/B comparability are mandatory. Start with replay-only, then private OBS rehearsal (no broadcast), then owner-controlled game test; only after CI and review can an integration be considered.

## Work queue, sorted by expected practical value

- **Now / safe:** land bounded observation planner and paired streamer-eval instrumentation as **draft** code; collect a non-sensitive local telemetry/replay fixture with explicit consent; review and settle duplicate #580/#581 voice director ownership.
- **Next / engineering:** thread this single-flight observation ticket through the existing authorized video/vision host; add clock-domain translation *at the host* for Brain 1/Brain 2; integrate native cancellation, voice turn detector, calibrated event confidence, UI kill switch and offline OBS rehearsal. Prevent leaked cross-session work and stale output playback.
- **Then / performance:** benchmark on the actual 8 GB streaming PC and separate server. Compare model variants, cache reuse, speculative decoding, quantization, token/event compacting, STT/TTS and motion pipelines independently. Prefer proven lower p95 over dramatic unmeasured model-size claims.
- **Then / intelligence:** route #579's hypotheses into Studio/microgame experiments, the existing outcome ledger, independently graded replay banks and transfer tests; revise lessons only after verifiers pass. Develop a consented game adapter for exactly one supported title; explicitly deny controls for all other games.
- **Later / experience:** coordinate avatar eye/head/audio expression, story callbacks based on reviewed session events, cat/puppy mode, improv timing, moderated chat fair scheduling, scene automation, optional accessible motion settings. Preserve original Star mascot identity; never clone a real streamer's voice without rights.

## Honest conclusion

A faster and more capable Star will come from **moving less unneeded work onto the critical path, using cheap reflexes for cheap facts, reserving high-quality reasoning for difficult moments, and proving every learning claim against real tasks**. The new code creates two small, auditable engineering boundaries. It is not a conscious system, a proven human-level gamer, a new foundation model or a deployed VTuber. The next step is controlled integration with the existing Star host and actual measured owner-hardware baselines — not another unintegrated AI subsystem.
