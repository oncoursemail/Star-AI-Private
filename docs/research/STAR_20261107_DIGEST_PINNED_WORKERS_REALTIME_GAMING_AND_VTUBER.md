# STAR: digest-pinned optional workers, faster real-time intelligence, and natural gaming VTuber research

**Prepared:** 2026-11-07 (America/Chicago). **Scope:** additive experimental branch; no automatic rollout to a real stream, game, model server or machine service.

## What this increment actually implements

The optional Windows worker path already contains a host-only GPU lease ledger, a real NVIDIA-memory observer, a host-owned process bridge, and opt-in Windows Job Object containment. Those parts help Star avoid oversubscribing her gaming/OBS GPU and prevent a terminated parent from leaving its child processes running.

This increment adds **optional launch-time SHA-256 pinning** for the owner-selected executable and up to eight additional local input files (for example, a Python launch script, small inference configuration, or trusted worker plugin). The trusted host can set `require_artifact_pins=True` on `HostOptionalGPUWorkerLaunchSupervisor`. In that mode a worker whose executable lacks an expected digest cannot start. Every specified pin is revalidated before requesting a GPU lease or creating a subprocess.

The digest check reads bytes from an opened regular file and confirms the file identity/size/mtime did not change during the read. The launch path enforces a **128 MiB cumulative hashing budget**, refusing larger files instead of synchronously hashing multi-GB model weights during supervision. This catches common accidental or malicious changes *before* optional execution. All failures defer the launch while preserving pre-existing GPU reservations; there is no fallback to a user or model-supplied command.

**Limits:** A SHA-256 pin is only as trustworthy as the locally owner-reviewed pinned manifest. This is not a code-signing system, DLL isolation, security sandbox, model-weight provenance check, or a defense against replacing an executable between verification and CreateProcess. Restrict write access to the launcher directory, scripts, model weights, and manifest. There is no live production connection yet; the module is disabled by default. Hashing large GGUF weights synchronously is inappropriate on a real-time supervisor thread. Validate large weight digests at controlled offline deployment/preflight time and measure the total startup cost; never treat the binary hash as proof that model weights were checked.

### Why it helps Star

Untrusted content on a livestream must never decide which process Star starts. Digest-pinned fixed commands, Job Object containment, and reversible resource leases together reduce the blast radius of accidental launch-path changes when Star eventually runs a live streaming computer. Reliable infrastructure is necessary, but does **not** on its own increase model reasoning accuracy, neural tokens/second, game win rate or avatar realism.

### Implementation contracts and deployment sequence

1. Owner provisions a fixed absolute executable and computes a trusted SHA-256 from independently reviewed bytes. Optionally include the launch script/config pins; keep secrets outside public manifests.
2. A trusted Windows host registers `HostOptionalWorkerPlan(..., executable_pin=HostArtifactPin(path, digest), additional_pins=(...))` and constructs `HostOptionalGPUWorkerLaunchSupervisor(..., require_job_tree=True, require_artifact_pins=True)`. These flags are independently opt-in. Never pass a plan or pin from chat or model output.
3. The host enables its real GPU lease source and verifies a fresh OS-originated game/OBS/voice measurement. The start command runs on an off-hot-path supervisor worker. Failure to verify the path/digest defers *before* reserving VRAM.
4. Only an owner-approved, registered plan may be launched; the Windows Job Object retains custody of descendants. Probe failure, QoS pressure or shutdown revokes optional jobs, and the accounting lease is freed only after the root has exited **and** kernel Job Object active-process count is zero.
5. Before production connection: test a disposable Windows worker under genuine GPU telemetry, restart recovery, binary substitution, script changes, child-process lingering, operator disable, power loss and private game+OBS+voice load. Preserve disabled-by-default until verified.

## Research: measurable gains in Star's intelligence and gaming

**Highest-return architecture:** an asymmetric three-speed agent, not a single huge model on every frame:

- **Fast reflex path**: small deterministic state machine / low-cost model for movement timing and hazard avoidance; enforce action deadlines and never let an LLM's slow deliberation stall frame-critical input. Unknown observations default to no-action or safe pause where the game allows it.
- **Mid-speed planner**: checkpoint goals, tactical decisions, inventory/resource choices, combat strategy and failure diagnosis on a lower update frequency; consume structured observations and use verified tool interfaces.
- **Slow learning loop**: generate a hypothesis about a mechanic, conduct controlled practice runs, compare against a prior policy on matched seeds, store only independently measured outcomes, and re-test on unseen game levels. Prefer causal interventions to memorizing frame sequences.

**Evaluation design:** Held-out levels and unseen games; fixed opponent/seed sets for paired trials; count actual verified completion/win rate, illegal inputs, missed deadlines, death rate, retries and action latency. Separate interactive *real-time* evaluations from pause-and-think conditions and record both. A skill may only be promoted when it beats its baseline on new tasks without extra action errors or memory/privacy regressions. Protect hidden test cases from Star's training loop.

The October 27, 2026 Gym-Anything-RT research emphasizes exactly this problem: environments change during inference, so a model may score far worse in real-time interaction than when paused. GameWorld supplies 34 games / 170 verifiable tasks, and its August fine-control branch adds 400-step higher-frequency episodes. These are evaluation references, not evidence that Star already has the scores.

**Self-play game developer:** Tie Roblox Studio construction to Luau typechecking, Selene/StyLua validation, a private Studio Lab, scripted test players, visible GUI/art inspection and repeated end-to-end playable acceptance. Progressively generate new control tasks: unfamiliar UI state, new map geometry, unknown ability cooldown, moving hazard, bot opponent, then an entire game loop. Reject unverifiable "I finished it" claims; use Studio logs/game-state receipts and frame-level evidence. Roblox's November 4 Studio MCP expansion gives permission-scoped Open Cloud asset/game operations; use explicit operation allowlists, never public publishing by default.

## Research: faster neural inference on consumer 8-GB NVIDIA cards

For an 8-GB RTX 3060 Ti/4060 environment, **VRAM pressure plus OBS rendering** can dominate user-perceived speed. The right metric is end-to-end capture-to-action or viewer-question-to-first-audible-speech, not a standalone token/s number.

A/B experiment matrix:

| Experiment | Primary metric | Important control |
| --- | --- | --- |
| Small fast model / larger planner routing | p50/p95 capture-to-action and held-out game success | Same tasks, seeds and inference quality rubric |
| llama.cpp ordinary vs speculative draft vs n-gram | output tok/s, TTFT, draft acceptance, p95 response latency | Same prompts, context, batch/slots and GPU headroom |
| Prompt-prefix cache and retrieval | prompt eval ms, relevant-fact accuracy, GPU memory | Prevent stale history and holdout leakage |
| CPU Pocket TTS vs current voice engine | first audible PCM, real-time factor, listener quality | Concurrent OBS and game, same voice texts |
| Static vs VRAM-aware optional-job admission | stream dropped/rendered frames, missed actions, stall/restart incidence | Real telemetry, no synthetic best-case claims |

Collect a representative workload with an active game + avatar + OBS private recording. Capture total GPU memory, *free* VRAM, GPU use, FPS p1/p50/p99, audio glitches, first audible response, invalid game inputs and stop requests. Test each candidate on stable warmed-up runs. Warmup and cold start results must not be mixed. Promotion requires improvements in **quality and latency** without degradation of realtime stability.

llama.cpp's SPEED-Bench compares different speculative decoding strategies and reports category-level latency/throughput and draft acceptance. Optimize measured results on Star's actual system, not generic vendor token/sec charts. Kyutai's Pocket TTS is a locally deployable CPU-oriented streaming speech engine; evaluate how freeing VRAM trades against CPU contention and voice expressiveness.

## Research: a natural and responsible VTuber personality

Humanlike interaction depends far more on timing and context than on claiming to be human. Star should be clearly an **AI VTuber character**, with a stable persona and consent boundaries, without inventing conscious feelings or pretending to be a real person.

An implementable on-air behavior system uses:

- **Perception:** host-authorized gameplay observations, vetted chat, VAD input, actual audible speech events and measured avatar playback; uncertain data stays uncertain.
- **Turn-taking:** yield for an authenticated owner's barge-in, hold for confirmed guest speech, ignore incidental noise, and prioritize quiet during critical gameplay. Never accept voice similarity as owner authentication. Emergency mute and OBS stop remain host-level controls.
- **Style:** spoken phrases short enough to finish before the game state changes; expressive phrasing appropriate to observable success/failure; sometimes silence; tiny nods, gaze and blinks when listening, not constant mouth motion. Respect reduced-motion and mute switches.
- **Memory:** approved, source-tagged game achievements and lesson summaries instead of unfiltered chat transcripts. Ask permission before remembering identifiable viewer details; expire routine session context. Retract a false game claim instead of repeating it for personality consistency.
- **Growth:** discover new games/genres, plan their own practice sessions, reflect on *verified* mistakes, learn authored 3-D asset workflows, Luau/Rust, music and visual design. Personal projects have explicit execution budgets and owner-configured public interaction rules.

Microsoft's May 2026 Proact-VL work specifically studies low-latency video understanding, **when to speak**, and how much to speak in live game settings. NVIDIA's June 2026 DyaPlex describes synchronized full-duplex listening, speech and motion, a useful research direction rather than a component already integrated. Star already has pieces such as `stream_turntaking.py`, `stream_interrupt_host.py`, `stream_idle_attention.py`, `stream_director.py`, `stream_social_turn_benchmark.py` and `stream_episode_journal.py`; connecting them to a trustworthy live host matters more than duplicating their planning code.

Use blinded A/B rehearsals on distinct gameplay and viewer scenarios with independent listeners. Measure first audible PCM latency, overlap, barge-in stopping, speech appropriateness, avatar synchronization, factual grounding, perceived warmth/consistency, unplanned silence and game performance. Do not tune to the blinded set.

## Practical priorities after this PR

1. **Prove full Windows service wiring**, including digest-verified Job Object startup/shutdown on disposable workers, and reconcile OS handles on service failure. Preserve owner approval and off-by-default config.
2. **Run a private, non-broadcast integrated rehearsal**: authorized game + model inference + CPU/GPU speech comparison + speaking/listening avatar + OBS local recording. Produce a reproducible scorecard with actual measured p50/p95 and verifiable game outcomes.
3. **Start paired held-out generalist practice**: 4–8 candidate tactics if compute allows, select only via independent in-game evaluation, track regressions across unseen games and tasks.
4. **Add observable personality quality tests**: guest interjections, owner interruption, avoiding fabricated events, contextual silence, audio/animation alignment, viewer privacy, safe chat handling.
5. **Integrate Roblox Studio Lab and game creator loop** with local verification, resource-aware scheduling, recovery, and human review before public uploads.

### Primary references (as available 2026-11-07)

- Microsoft Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Gym-Anything-RT (2026-10-27): https://arxiv.org/abs/2610.37567
- GameWorld: https://gameworld-project.github.io/ and https://github.com/gameworld-project/GameWorld
- Proact-VL (ICML 2026): https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- DyaPlex (2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- Pocket TTS (official): https://github.com/kyutai-labs/pocket-tts
- Roblox Studio MCP expansion (2026-11-04): https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

**Evidence boundary:** This PR implements artifact digest checks and offline regression tests. It does not claim actual better gaming win rates, faster neural inference, human-equivalent emotions, deployed Windows model control, or public stream readiness.
