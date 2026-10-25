# STAR: Host-Grounded Gameplay Planning + Realtime Intelligence Roadmap
*Research and isolated implementation: 2026-10-25. Experimental; not deployed.*

## Actual change

`star/game_navigation.py` adds a small, **pure-Python partially observed grid-world planner**. A trusted game host provides `GameFrame` observations: bounded coordinates, visible tile classifications, a player position, stable game/session identity, and monotonically increasing sequence IDs. `NavigationBelief` retains only seen facts and returns a **single advisory movement**. It finds a shortest *verified* route using BFS; when no verified goal route exists, it refuses to guess in play mode. In explicitly approved **practice mode**, it may propose moving along observed safe terrain toward one unseen frontier cell and then requires another host observation. Walls/hazards are never planned through. Dynamic host observations supersede older observations. The planner has no model, screen capture, filesystem, networking, OS input, Studio controls or privilege escalation. `trusted_host=True` is an explicit caller assertion, **not authentication**; enforce producer identity at the transport/process layer.

This is a measurable building block for gameplay **planning and exploration**, not a visual model and not a claim of advanced autonomous play. The toy-grid regression fixture is deterministic and is not evidence of real Roblox/game success.

## Why this matters

A model can describe a movement that seems plausible while having no evidence about geometry. A compact, explicit, updated belief map makes unsupported shortcuts impossible to plan and gives the AI a concrete place to distinguish observed facts from unknown terrain. It also reduces repetitive full-context spatial reasoning: choosing a move is a bounded O(cells) operation rather than a full LLM inference. This is a *potential latency saving* once a host adapter is wired; no inference benchmark was run.

Google DeepMind's SIMA 2 shows a path toward general agents that understand instructions, act and learn in 3D worlds with experimentation, but its research results are not a model STAR can simply claim. Voyager demonstrates iterative environmental feedback plus a reusable skill library; STAR should validate skills against held-out game seeds, not accept model self-ratings.
Sources: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/ ; https://arxiv.org/abs/2305.16291

## Integrate without granting broader permissions

1. Keep the adapter outside the model process. It must identify the explicitly permitted, private test experience; produce frames from actual host instrumentation and verify the game session, model and build; never let model text manufacture observations or safety results.
2. Project screenshots/scene hierarchies into a camera-relative spatial representation **with explicit uncertainty**. Until a tile/edge is verified, it stays unknown. Never treat estimated pixels as authenticated physics outcomes. Record the frame timestamp, coordinate transforms, observation confidence and occlusions. Reject stale frames after teleports or scene resets.
3. Use `NavigationBelief.advise()` for suggestions only. An independently gated actuator can convert the suggestions into playtest controls **after** checking owner authorization, platform rules, focus, game identity, max actions, timeout, emergency stop and whether practice mode is enabled. No autonomous input to other people's games.
4. Host verifies player movement and outcomes and writes evidence to the separate `GameSkillMemory` proposed in draft PR #594; it may add true, observed moments to `StreamMomentMemory` without pretending the AI itself authenticated evidence. Keep failed attempts visible for correction.
5. Write a real offline-to-Studio adapter test matrix: no-knowledge abstention, delayed observation, stale-frame rejection, dynamic obstacles, moving platforms, camera transforms, hazard avoidance, stuck recovery, goal completion, permission revocation, cancellation, and quality comparison against an unchanged baseline. Test on **unpublished owner-owned** Roblox places first. Roblox's built-in Studio MCP and playtesting capabilities provide a supported integration route; never confuse a static fixture with playtest logs. Source: https://create.roblox.com/docs/en-us/studio/mcp and https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

## More intelligent gameplay and game creation: next development investments

- **Hierarchical goals and skills**: separate language goals ("find the key"), symbolic subgoals (reach door, inspect trigger), and verified primitive actions. A reusable skill is a versioned policy with training context, measurable success bounds and revocation, not a prompt claiming expertise.
- **World-state uncertainty**: fuse host instrumentation, video frames and speech with timestamped provenance. Run a predictive scene model only as *hypothesis generation*; controlled host outcomes decide correctness.
- **Active experimentation**: select information-rich, bounded practice trials in sandbox; compare against a deterministic baseline, frozen seeds and untouched holdouts. Track completion, time-to-goal, collision rate, recovery cost, API violations, and repeated failures. Reject changes when regression gates fail.
- **3D building quality**: maintain a scene graph of walls, supports, entrances, functional clearance, mesh scale, pivots and collision groups. Gate placements with spatial overlaps, floating objects, visual texture alignment, missing prop references, budget, and real screenshot inspection at multiple camera poses. Native Roblox UI must remain editable; do not ship flat UI screenshots.
- **General knowledge**: controlled retrieval from owner-approved sources with licenses, source hashes, timestamps, contradiction checks, and topic-coverage analysis. Route hard questions to larger models only when resource policy permits; use the existing `general_knowledge_benchmark` and independent gate, not knowledge claims inferred from increased document count.
- **Learning transfer**: for any reusable action or fact, add provenance, decay/invalidations for changed versions, and evaluation in unseen environments. Prefer retrieval at answer time over weight updates until evaluated examples have licensing, rights, held-out contamination checks and explicit owner consent.

## VTuber: natural, responsive and truthful

Humanlike streaming should mean fluid turn-taking, voice prosody, laughter, facial motion, memory of **real stream events**, quick responses and appropriate silence—not claims of being a human or fabricated childhood. Keep STAR identifiable as AI.

A proposed stream loop:

```
game frame / permitted chat / microphone
        -> time-aligned event bus (source + observed time)
        -> attention selector and owner-interruption lane
        -> choose [play action | short voice cue | listen | silence]
        -> generation-bound TTS + animation commands
        -> OBS/avatars only behind explicit approval and visible kill switch
        -> host feedback: what was audible / visible / actually happened
```

Conversation gets noticeably more natural with **full-duplex listening**, brief backchannels, overlap handling, sentence-boundary audio chunks, and cancel-safe playback receipts. PersonaPlex (Jan 2026) researches configurable full-duplex voice; DyaPlex (2026) researches synchronized speech and motion. Both require license, resource, and quality checks before considering real integration. Existing STAR `voice/call.py`, `voice/metrics.py`, and draft PRs #581/#593/#594 should be reconciled instead of creating another independent director.
Sources: https://research.nvidia.com/labs/adlr/personaplex/ ; https://research.nvidia.com/labs/amri/projects/DyaPlex/

**Avatar and stream behavior:** preserve Star's approved gold-star / dark-haired chibi identity and cat/puppy variants. Calibrate blink, gaze, ear and tail gestures against speech/phonemes, with gentle motion limits and reduced-motion accessibility. Track playback confirmation so a canceled line is not remembered as spoken. Use stream-session-only, expiring callback memory tied to observed wins/failures. Do not make up "real life" experiences; original fictional lore can be explicitly labeled fiction.

## Infrastructure speed: prioritize perceived latency and frame stability

On 8 GB consumer VRAM, keep game rendering / tracking / voice responsiveness ahead of expensive learning. Scheduling background research and training on the CPU/RAM-rich machine when available is safer than assuming large models fit on a streaming GPU. Transfer compressed event summaries, not full video histories, between machines by default.

Use an **A/B measurement table**, not speculative speed claims: time-to-first-audio p50/p95, audio glitches, stream/game FPS p1/p50, per-model first-token latency, decode tokens/s, memory footprint, cache hits, training utilization, interrupted utterances, task accuracy and new-task generalization. Benchmark the same model, prompts, context length, concurrent load, fixed hardware and versions. Disable performance changes that cause quality regressions.

Candidates worth testing, not enabled by this PR:
- llama.cpp **speculative decoding** (draft-model or n-gram), recording draft acceptance and actual latency; some workloads slow down instead of speeding up, so keep baseline comparisons. Docs: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- **KV/prefix reuse and short stable voice prompts**, in-engine where supported, without treating cached outputs as fresh knowledge. Keep confidence/citation freshness checks separate.
- **Adaptive route/effort**: small local model for greetings/event selection and a slower deeper model for complex debugging/coding; measure downstream success on held-out tasks, not only prompt tokens.
- **Cancel/stale-event rejection**: never queue narration for expired moments after the game state changed, and revoke unfinished generated speech/motion on barge-in.

## Evidence, scope and release gates

The included tests exercise only pure Python, one independent toy-world fixture and validation. They do **not** show live Studio play, game input, increased model intelligence, inference throughput, human-perceived voice quality or actual OBS integration. No network services or computer processes start by importing this module.

Keep this work draft against `star/next`; do not merge main, alter evaluation suites, enable video/mic streaming, or send controls to public games without explicit owner approval. Security/process architecture and all overlapping streaming PRs need independent review before deployment.
