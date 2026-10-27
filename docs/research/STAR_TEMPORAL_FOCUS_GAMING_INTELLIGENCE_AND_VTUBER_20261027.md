# STAR: temporal game vision, autonomous knowledge, and natural VTuber engineering

**Research and implementation date:** 2026-10-27. **Status:** opt-in Python host component + offline tests; no OS capture, OBS broadcast, game controller, inference model, GPU allocation or TTS deployment.

## 1. What this update actually fixes

The foveated HUD feature added up to eight owner-defined game-screen regions. It was intentionally sensitive to brief visual changes. But noisy compression frames, UI flashing, particle animation behind transparent HUD, and transient hit indicators can generate a fresh perceptual signature and force costly model work. Those events should not automatically be treated as new factual knowledge or a verified game achievement.

`TemporalFocusGate` now provides **explicitly opt-in** temporal confirmation in front of the existing `ObservationGovernor`, using already-computed `FrameCue` fingerprints. The default path is unchanged. The gate keeps an independent stable sample and candidate transition for each ROI, requires a configurable two-to-five independent, strictly newer capture frames, resets candidates when a region or streaming session changes, and limits gaps between confirmation samples. It never reads, copies or stores pixels. It also **never delays explicit host cues or full-game/full-HUD changes**: those pass through existing permission, freshness, workload, rate and worker-quarantine checks. Focus hashes remain nonsemantic heuristics.

Integration: `StreamVisionHost(..., stabilize_focus=True, focus_confirmation_frames=2, focus_max_gap_ms=1800.0)`. The 1.8-second maximum inter-capture gap accommodates hosts offering frames near 1 Hz while still requiring sequential captures; at 30 Hz the same setting can confirm in the next frame. This is a latency-versus-noise trade-off: some legitimate one-frame interface events may be suppressed, so never route critical death, safety or moderation signals **only** through this feature. The host must get those events from an independently trusted source.

### Reproducible observations

`PYTHONPATH=. python3 benchmarks/stream_focus_replay.py` replays a **14-frame synthetic** sequence with transient status-color flashes and two persistent transitions at 1.2-second spacing. Under identical (artificial) budgets the existing governor admits **11** observation *requests*. With the opt-in gate it admits **3**, while preserving the two sustained transitions plus the initial baseline. The microbenchmark reports ~20 μs of gate computation per already-fingerprinted synthetic capture on the Linux development machine; numbers depend on runtime and hardware. A smaller number of admitted requests is not itself a model speedup, guarantee of useful vision output, or Windows FPS measurement. Real HUD captures can yield different accuracy trade-offs and rates.

Gate tests cover duplicate/reordered captures, persistent vs flashing transitions, scope changes, competing ROIs, small visual jitter, status resets, strict host opt-in and continued prior authorization/worker safety. This is **not** autonomous gameplay, certified event recognition, or pixel capture.

## 2. Research evidence for the broader STAR architecture

### A. Roblox development quality: inspect, edit, play, verify

Roblox's *OpenGameEval* work (paper dated **October 1, 2026**) evaluates 13 models on 84 curated tasks and finds that inspecting relevant objects in Studio before editing is associated with higher success. It uses executable engine checks rather than code-text similarity. For STAR, the right learning target is completed, independently executable behavior, including placement, parenting, collisions, animation timing, client/server boundaries and GUI scaling—not merely Luau that compiles. [Roblox/OpenGameEval](https://github.com/Roblox/open-game-eval), [paper](https://arxiv.org/abs/2610.02563).

Roblox documented its **built-in Studio MCP server** and automated playtest input on **March 5, 2026**; the **April 15** Studio roadmap explicitly describes plan → build → playtest → fix cycles. Recommended priority: implement authorized Studio Lab execution with pre/post hierarchy inspection, recorded plan, sandboxed edits, measurable player-action replay, and automatic rollback for nonpassing changes. [Roblox developer announcement](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643), [Roblox Studio agentic article](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic).

**Independent quality gate:** `syntax + Luau analyzer + asset validity + geometry/swept-volume + Studio simulation + 2-client network test + human visual review`. Never count pretty screenshots as completion. Keep challenge prompts and holdout maps outside STAR's practice retriever; use signed practice vs withheld evaluation to measure transfer, including objective completion, collision count and camera/HUD interaction.

### B. Three-speed cognition and useful intelligence per second

STAR should run an instrumented **reflex loop** for visually grounded motion/action decisions, a **deliberation loop** for short game strategy, moderated chat and debugging, and a **slow learning loop** for extracting source-cited skills, independent tests, and internal Forge experiments. The reflex loop must not block on web research or large model calls. A context compiler should select only the relevant project docs, active game controls, recent observations, verified skills and explicit permissions, each with a freshness bound. Longer cached prompts can be cheap only if cache hit rate, latency and correct output are measured on mixed requests.

Use small local models for intent routing, simple backchannels, asset classification and low-stakes questions; larger models for genuinely difficult scene planning, novel code design and multistep problems. A model router should maximize **verified success per elapsed second**, not peak tokens/second; high-risk or low-confidence proposals require verification. Compare CPU-only, GPU-only and hybrid assignments under **real game FPS and speech load**, not idle benchmarks. Speculative decoding and KV reuse must be A/B tested against an uncached control, because an apparently faster path can return stale or incorrect context.

**Measurement contract:** for each experiment log task class, hardware, model and quantization identifiers, context length, first-token latency, p50/p95 completion time, resident CPU RAM/VRAM, p95 game frame time, WER if speech recognition is involved, judge agreement against executable checks, and timeout/worker-quarantine failures. Use sanitized metadata only. Hold the task distribution constant, track tail latency and require no regression on security/permission tests. Keep changes OFF until gates pass.

### C. VTuber naturalness is turn-taking plus timing, not constant chatter

LiveKit's current **turn-taking tuning** documentation describes adaptive interruption detection, false-interruption recovery, endpointing and preemptive generation; it also cautions about wasting synthesis on canceled turns. STAR already has a preemptive host; next validate actual microphone speech against interruptions and the 8 GB gaming GPU load. Natural behavior means silence while concentrating, restrained acknowledgments, interruptibility, non-repetitive callbacks to documented stream history and no automatic narration for every movement. [LiveKit turn tuning](https://docs.livekit.io/agents/logic/turns/tuning/).

NVIDIA's **DyaPlex**, described in June 2026 and listed by its authors as a NeurIPS 2026 paper, investigates causal **full-duplex speech plus synchronized motion**. It is a research reference for relative timing of blinking, listening, gaze and gestures, not evidence that the model runs at acceptable latency on STAR's machine. STAR can instead use cheap parameter-level motion synthesis and a separately measured voice worker, with speech-driven lip movement and an idle stage that makes her eyes, twin tails and ears feel responsive without constant random motion. [DyaPlex project](https://research.nvidia.com/labs/amri/projects/DyaPlex/), [Live2D physics guide](https://docs.live2d.com/4.2/en/cubism-editor-manual/physics-operation/).

Kyutai **Pocket TTS** has October 2026 smaller English variants (`english_18m_2026-10`, `english_7m_2026-10`, `english_2m_2026-10`). Their published CPU throughput claims make them reasonable benchmarks for protecting GPU space while gaming, but voice timbre and breath/laughter quality may worsen at smaller sizes. Benchmark auditory preference, time-to-first-audio, p95 under gameplay load, prosody and intelligibility before adopting. Do not clone voices without rights/consent. [Official Pocket TTS README](https://github.com/kyutai-labs/pocket-tts/blob/main/README.md).

### D. Autonomous game playing and transferable skill

Gameplay understanding needs state/action/outcome records, not a stream of screenshots. STAR should infer controls only within supported game rules, practice in authorized environments, and transfer learned skill descriptors (`timed_jumps`, `camera_alignment`, `resource_pacing`, etc.) across privately generated unfamiliar test layouts. Train on feedback with separate evaluation holdouts. Persist mistakes as reproducible evidence: `starting state → action → predicted result → observed result → error classification → corrected strategy`. Re-evaluate after each improvement and on distinct maps/physics settings to detect overfitting. Never claim she has beaten an unfamiliar game based on the existence of an API or a passed unit test.

A practical stepping ladder: private deterministic 2D control tasks → Roblox Studio obstacle courses → multi-mechanic quests and inventory → network client/server private playtests → consented online games without anti-cheat circumvention. The number of independent held-out levels finished, survival rate, action efficiency and recovery from unseen mechanics—not just repeated familiar wins—should decide promotion.

### E. General knowledge and a coherent digital life

STAR's knowledge base should distinguish `observed`, `owner-approved`, `externally sourced`, `model hypothesis`, `obsolete`, and `withheld evaluation`. Every new general fact needs date, source/provenance, confidence and a later refresh policy. Use retrieval first, then answer, then citation/uncertainty validation. For character continuity, store truthful digital experiences from authorized sessions (what game she played, what she actually achieved), and optional **fictional persona lore explicitly labeled as such**. A consistent playful identity is compatible with candid disclosure that STAR is AI; natural delivery should not depend on lying about human memories or consciousness.

STAR's self-directed learning can expand through **bounded curricula** that she proposes: new puzzles, novel game designs, animation exercises, general research questions, source verification and quality-assurance probes. Her local Core Forge should use isolated experiments, semantic diffs, independent hidden tests, rollback and owner review for sensitive external actions. GitHub remains an optional owner publication channel, not a prerequisite for her internal iteration.

## 3. Integration order and hard acceptance gates

| Priority | Concrete integration | Independent pass condition |
| --- | --- | --- |
| P0 | Authorized Windows game frame ring buffer → existing fingerprints + focus gate | No capture without opt-in; drop stale frames; no private material retained; positive/synthetic alert recall & false request reduction |
| P0 | Game FPS + speech backlog + CPU/GPU admission in one session | p95 gaming frame time no worse in A/B; no leaked/infinite GPU leases; speech interruption playback stopped on session change |
| P1 | Studio Lab pre-inspect → edit → 2-client playtest → rollback | Held-out playable benchmark improves without hidden-eval contamination or geometry/GUI regressions |
| P1 | Natural voice+quiet attention+spoken turn timeline | Human evaluation of interruption recovery, nonverbal timing, truthful references; measure speech latency under gameplay |
| P1 | Verified source-backed general knowledge cache | Higher correctness on unseen sourced questions, measurable retrieval freshness, no unapproved context leakage |
| P2 | Cross-game skill bank and self-curriculum | Improved held-out success vs no-learning baseline, with CPU/GPU cost bounded |
| P2 | Live2D twin-tail/ear physics and avatar rig adaptation | Multi-platform param mapping, lip sync, reduced-motion compliance and recorded frame-time overhead |

Design limitations: fingerprints cannot prove game events, a temporal denoiser can miss fast events, and selected validation tests do not establish model intelligence or stream-human indistinguishability. True consciousness and human status are not engineering outcomes that can be certified by a conversational character.

## 4. Reproduction

```sh
PYTHONPATH=. python3 benchmarks/stream_focus_replay.py
python -m pytest -q tests/test_stream_focus_stability.py tests/test_stream_vision_host.py tests/test_stream_foveated_attention.py tests/test_frame_fingerprint.py
python -m ruff check star/stream_focus_stability.py star/stream_vision_host.py tests/test_stream_focus_stability.py benchmarks/stream_focus_replay.py
```

This branch is a draft, opt-in stepping stone in a series of **unmerged** pull requests; it does not enable screen capture, streaming or physical audio. The so-called `Star-AI-Private` GitHub repository currently reports public visibility, and should not be used for private media or secrets.
