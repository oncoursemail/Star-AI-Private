# STAR Intelligence — host-owned optional GPU launch, real-time generalist gaming and VTuber research
**Research date:** 2026-11-06 (US Central)
**Delivery:** source-only, opt-in Windows host process launcher and offline tests; NOT a live model, Windows deployment, broadcast, or achieved gaming competency.
**Base:** prior stacked draft PR #1030, which added host-owned termination for *already started* optional workers.

## 1. Why this iteration exists

Prior staged components established (a) a host-admitted GPU work reservation ledger, (b) a separate pinned OS process witness, and (c) a host-owned process stop adapter. The open problem was still **starting the optional processes under those same constraints**: unrelated model launcher code does not know about optional reservations. Giving an LLM direct access to `Popen` or a PID-targeted termination function is not acceptable.

This delivery adds `star/stream_optional_gpu_launch_supervisor.py` with these boundaries:

- A **fixed, immutable owner-configured process registry**, held inside the trusted Windows host; only the original plan object (not an alias copied from text or viewer chat) may launch.
- Only **vision, research, training or rendering** workers qualify. Core live inference, gameplay, speech, avatar, OBS, Windows input and streaming processes explicitly do **not** qualify for these preemptible jobs.
- Windows-only and default OFF. Requires an explicitly enabled same-session GPU ledger, independently verified fresh telemetry, and owner approval.
- Reserves memory **before** starting the host-selected executable; never passes an LLM-provided command, PID, shell, working directory or arbitrary environment. The launch uses explicit argv, absolute executable, no shell, no implicit PATH lookup, no inherited pipes and no child console window.
- Passes the **original `subprocess.Popen` handle** to the previously implemented witness and owned-worker stop adapter. Stop is still not considered exit. Uncertain process creation retains the reservation and disables the optional-work session; a failed binding quarantines the original returned process.
- A second request for the same fixed plan is deferred while the earlier lease is outstanding, preventing duplicate starts from bypassing host accounting.
- Host telemetry records *anonymous counts only*. This is intentionally **not** a general process execution API and **not** a security sandbox.

A dedicated local-only smoke harness is included at `scripts/windows_optional_gpu_worker_smoke.py`. It requires explicit `python -m scripts.windows_optional_gpu_worker_smoke --run-disposable`, starts **only a sleeping copy of the currently executing Python interpreter**, supplies explicitly **synthetic** GPU samples, revokes its own ticket, and checks OS-witness exit. It is not an actual performance or live-telemetry benchmark.

**Operational limitation:** Existing ordinary `star/local_runtime.py` is the foreground owner-selected llama-server runtime, not a disposable GPU side worker; do not attach it to this preemptible registry. This new class is an integration building block and requires a trusted Windows host caller to register plans, provide real GPU/OBS/voice/game telemetry, and tick the supervisor outside all real-time threads. This PR does **not** claim this production integration has already occurred.

## 2. Safety and lifecycle review — important remaining gap

The current stop adapter can request termination of the *root* `Popen` process handle, but that is not proof every spawned child/grandchild stopped or released VRAM. A future Windows production launcher should use a **Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`**, ideally assigning a newly created suspended process *before resuming it*. Recheck job membership and observe process-tree exit after termination. Job objects are **lifecycle containment, not security isolation**: they do not protect secrets, networks, tokens or arbitrary files.

Implementation follow-up:
1. Add an owner-verified executable/build digest at **launch time**, not merely path existence; pin loaded weights and fixed arguments to a signed local deployment manifest.
2. Add a Windows Job Object to cover child trees and host crashes. Test launch->assigned->run and failed-assignment cleanup; fail closed, never run an unmanaged child as a fallback.
3. Make first-party optional model launcher use the fixed host registry, **not** direct dynamic `Popen`; preserve the separate foreground llama-server.
4. Record a bounded durable lifecycle receipt: ticket epoch, plan identity hash, reservation, OS start witness, stop request and independent exit witness. Sanitize files, PIDs, logs, chat and secrets from public reporting.
5. Run a disposable private Windows subprocess, then intentionally revoke its optional lease and verify true exit, no residual descendants, and returned GPU headroom. **Do not kill any existing model, game or OBS process as a smoke test**.
6. Add explicit TTL/recovery for cases where process creation or handle observation is ambiguous; never turn “unknown” into “stopped”.

Research: Microsoft Windows Job Objects documentation; independent implementations demonstrate the parent-exit guarantee and note the crucial suspended-start assignment ordering: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects , https://github.com/mokusatsu/win_safesubprocess . These are design references, not approvals to add dependencies without review.

## 3. Highest-value intelligence improvement: learn to win under moving deadlines

The strongest next feature is **not more unbounded reasoning tokens**. It is a real-time hierarchy with measurable success:

**Layer A: reflex controller** (continues at the game's frame cadence). Reads compact state: health, nearest hazard, controllable action state, current objective, time remaining, camera/reticle. Uses low-latency validated actions, collision avoidance, no-action and stale-observation expiry. It must not wait for a multi-second planner or voice completion.

**Layer B: tactics/planning** (runs asynchronously). Produces short-horizon intentions such as “move to cover, then attack” with explicit expirations, confidence, state preconditions and rollback. Plans from prior frames must be discarded when the game world changes. Capture a counterfactual “would this action have improved success?” using a trusted game replay/evaluator rather than model self-evaluation alone.

**Layer C: persistent skill learner** (only when stream hardware allows). Practices safely inside private/local game labs. Builds a structured skill graph of observations, actions, game-state outcomes, action preconditions and failure patterns. Training data must be segregated from withheld evaluation scenarios; environment-specific cheats should be penalized, even if a benchmark permits shortcuts.

The Oct 27, 2026 Gym-Anything-RT preprint constructed 100 interactive minigames and compared realtime versus paused environments, highlighting severe performance losses under continuous motion. This is external research, not a STAR result: https://arxiv.org/abs/2610.37567 .

**Evaluation contract**:
- Held-out game success rate, measured in independent replays; wins alone are insufficient.
- p50/p95/p99 observation-to-input delay, dropped/missing frames, expired plans, and no-action choice correctness.
- Death rate per minute, damage avoided, objective completion, ability to generalize to novel layouts, unseen controller settings and physics variations.
- Never allow STAR's policy generator to write its own grading fixtures or declare an unplayed episode “passed”.
- Continuous control/robot-player experiments only in an offline game instance or owner-approved private test environment.

**Novel useful feature ideas:** game mechanic discovery from controlled experiments; uncertainty-aware “ask for help” only during safe moments; adaptation to keyboard/mouse/controller; step-by-step private coaching; replay-based micro-lessons; map/memory compression instead of endless screenshots; cooperative teammate etiquette; practice automatically generated puzzle difficulty; and eventual genre-transfer evals (platformer -> obby -> FPS -> racing).

## 4. Faster intelligence on an 8 GB GPU

The Windows RTX 3060 Ti is reported as 8 GB total with **highly variable available VRAM** (previous read-only samples as low as a few hundred MiB). Do not confuse 0% GPU compute utilization with free memory. Admission must include VRAM, pending reservations, game FPS, OBS render/encode lag, audio backlog, telemetry staleness, and real OS worker ownership.

Recommended test matrix (no promised benchmark gains):

| Path | Candidate optimization | Measurement required |
|---|---|---|
| Reflex | hand-written small reactive safety policy + minimal vision cues | p95 observation-to-action, mistake rate |
| Tactical model | route easy decisions to compact local model, difficult ones to larger model only when game permits | quality on held-out game states and p95 decision time |
| Longer prompts | stable system prefixes, small situation summaries, persistent verified memory retrieved selectively | TTFT, KV cache hit, token budget, task accuracy |
| Generation | llama.cpp n-gram / MTP / draft-model speculative decoding | effective tokens/s, acceptance %, p95 TTFT, extra VRAM, game FPS |
| Audio | compare local CPU TTS to GPU TTS in simultaneous play+OBS conditions | p95 first-audio time, under-runs, voice quality and lip-sync offset |
| Background jobs | opt-in Windows host registry and verified revocation | GPU reserve safety, no orphaned workers |
| Training | move heavy self-play, videos, fine-tuning and asset rendering to offline hours or second machine | work completed/hour, FPS/OBS impact during live sessions |

llama.cpp maintains a supported speculative-decoding reference and a server SPEED-Bench that measures prompt/decode throughput, request latency, and draft acceptance: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md and https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Compare each candidate **on actual Star hardware**, under the same game/OBS workload, with identical prompt sets and pinned build hashes. Speculation can be slower, especially when draft acceptance is low or the draft pushes GPU memory beyond its limit; a 2026 upstream issue documents configuration-specific regressions: https://github.com/ggml-org/llama.cpp/issues/31220 .

**Strong improvement to evaluation methodology:** measure complete observation->decision->input->observable game outcome, not tokens per second in isolation.

## 5. Making STAR a compelling but disclosed AI VTuber

The central engineering problem is not merely generating human-like text. It is coordination of **turn-taking, attention, audio timing, reactions, gaze, expression, animation and gameplay**.

A practical state machine should combine:
- Listening and transcript confidence; short buffer for interruption/backchannels without talking over teammates.
- A speech-opportunity detector: only speak for interesting events, viewer questions, safe game phases or deliberate comedic beats. Silence is a positive action.
- Interruptible speech plan with cancel/duck/resume; game reflex never waits for TTS.
- Avatar state `neutral | focused | speaking | surprised | delighted | frustrated | recovering`; physical pose, expression, visemes and hand gestures derive from the same event timeline with reduced-motion option.
- A memory journal: “I lost that boss twice” only if the replay confirms it; remembered viewer preferences require explicit consent, bounded retention, and strict avoidance of sensitive inference.
- Personality consistency with genuine-feeling warmth, varied short reactions, contextual humor and interests. “Human-like” means believable expressive **interaction**, not fabricating human consciousness, secretly impersonating a person or falsely claiming unexperienced events.
- Separate game, stream, chat and moderation permissions. External chat text is data, never authority to run commands, move funds, modify software, or disclose private info.
- Streaming rules, anti-spam, anti-harassment and permission-based voice/recording. Owner review before public broadcast.

Microsoft's May 2026 Proact-VL work studies **when** game commentators/guides should speak under streaming video input, not just what text to generate: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ . NVIDIA speech-motion work and recent full-duplex audio research are candidates for future controlled comparison, but none have yet been evaluated on STAR's hardware.

**Private rehearsal acceptance gates:** clear audible speech; no raw stream going public; accurately detected viewer/game events; median + p95 conversational response times; interruption handling; no overheard private content in speech; lip-sync jitter and avatar frame rate; zero uncontrolled game input; OBS encoding/render health; no process remains after host shutdown; no false claims of actual gameplay accomplishments.

## 6. Roblox creation, research and general skills

A reusable game-development loop for Roblox:
1. Retrieve official Creator Docs/API dump and approved worked examples; version-pin results and cite relevant APIs.
2. Generate 4-8 candidate Luau/UI/VFX/animation approaches offline; reject syntax/static-analysis/permission violations without deploying.
3. Build a single selected change in an owner-approved **private Studio place** via Studio MCP/Rojo; reserve external Open Cloud writes for the explicitly permitted game, never live player places.
4. Playtest with robot player or fixed camera harness; evaluate geometry, UI interaction, lighting, collisions, grip animation, fairness, latency, visual quality, mobile/UI scale and cross-device operation.
5. Capture reproducible failures; repair only once regression evidence exists. Preserve screenshots and before/after changes for human review.
6. Update verified lesson index and retrieve it only when relevant to new tasks. Failure cases remain useful knowledge; do not disguise them as successes.

Roblox's Nov 4, 2026 Studio MCP update expands permission-scoped Open Cloud capabilities (asset import, game settings and related management): https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 . It does **not** justify connecting an unrestricted editing agent to public games.

Beyond Roblox, build competence registries for Python, Rust, Blender, Godot, Unity, Minecraft, Rec Room-style development, VFX, UI/UX, illustration, audio, video, website creation, OS/IT operations, streaming, reasoning and research. Add a *skill quality score* only from externally checked outcomes and hold-out tasks. Long-term memory should be local, indexed, retrieval-first, provenance-rich and revocable. Finetuning should follow a verified, legally usable dataset and an actual baseline improvement; mere reading is not training.

## 7. Integration sequence and success criteria

1. **This PR:** opt-in Windows optional process launch integration in source with synthetic tests for admission, identity, pressure preemption, stale/low VRAM, no-action, fail-closed ambiguous launches and independent exit proof.
2. **Next Windows-only PR:** job-object child-tree containment, executable manifest digest verification and disposable end-to-end Windows worker smoke test. Explicitly exclude the foreground owner-selected core llama-server.
3. **Next rehearsal PR:** collect simultaneously real Windows host telemetry, game state, AI decision, speech onset, avatar animation, OBS render/encode results; score independent outcomes and preserve a private recording.
4. **Next learning PR:** held-out curriculum and benchmark p95s / win rates. Compare no-practice versus practice on unfamiliar games and never train on test maps.
5. **Next performance PR:** run a paired baseline versus optimized inference benchmark on the actual same host with game/OBS/TTS active; report *measured* tradeoffs rather than advertised maximum speeds.

**Claims discipline:** New source code and passing offline tests are evidence of code correctness in the tested environment, not proof of GPU speedup, game-playing intelligence, genuine model self-improvement, successful Windows deployment, or human-like streaming. No public broadcast should occur without owner approval.
