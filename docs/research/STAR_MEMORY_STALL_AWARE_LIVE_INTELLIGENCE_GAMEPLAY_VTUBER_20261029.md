# STAR Intelligence — Memory-Stall-Aware Inference, Game Mastery and Believable VTuber Roadmap

Research/implementation: 2026-10-29 (America/Chicago); Linux host checks extended into 2026-10-30 UTC.
Scope: owner-authorized Star AI/Star Core Forge. Experimental and opt-in; no live deployment.

## 0. Concrete upgrade delivered in this branch

The existing `RealtimeTelemetryHost` and `StreamBrainGovernor` already protect
frame rate, audio backlog, VRAM, CPU and task reservations. However, **free RAM
and swap occupancy do not show whether tasks are actively stalling**. STAR's
local inference server is RAM-intensive and must coexist with interactive work.

`star/memory_stall_guard.py` adds an optional Linux kernel PSI +
`/proc/vmstat` read-only observer. `StreamBrainGovernor.admit()` can use the
guard **before** reserving CPU/GPU capacity for `vision`, `research`,
`training`, or `render`. The monitor holds heavy new work during measured
stalls, stale/unavailable observations, or recent swap-churn *with actual
stall pressure*. Voice speech/commentary are not blocked by this monitor;
existing QoS routing, FPS, deadlines and audio rules still apply.

The monitor is **off by default**, never executes jobs, does not kill processes,
does not change llama.cpp parameters, never opens network sockets, and exposes
no chat, video, credentials or viewer data. Existing hosts remain unchanged
unless a trusted embedding host opts into `MemoryStallGuard` and polls on a
background worker. The guard uses one sample as a baseline, then derives
delta stall time and swap-in/out page rates; three distinct healthy intervals
are required to clear a prior stall. A missing/corrupted sample cannot
immediately clear a prior stall. A stale sample blocks *new optional* work,
not active workers or audible speech.

### How a trusted host enables it (illustrative; NOT deployed)

```python
from star.memory_stall_guard import MemoryStallGuard

pressure = MemoryStallGuard()                # no external I/O
pressure.enable(owner_approved=True)
# Trusted host's 1 Hz worker, NOT Studio / sound / render thread:
pressure.poll_linux()                        # reads aggregate /proc counters
# ... next poll after >=200ms; continue about once per second.
# Construct existing StreamBrainGovernor(memory_guard=pressure, ...)
# and keep existing local hardware observers active.
# Never provide kernel paths, host callbacks, or approval arguments as
# model-generated tools. Windows should leave this optional guard unset.
```

Safety: RAM allocated to swap is **not** evidence of ongoing thrashing.
Only a change in swap page counters is activity; even that is not enough
to classify the machine as stalled without PSI evidence. PSI `some` means
some tasks were blocked; `full` means all non-idle tasks were blocked.
Kernel documentation: https://www.kernel.org/doc/html/latest/accounting/psi.html

### Read-only host findings (single observation, not a speed benchmark)

On Star's connected Linux development computer, the snapshot showed roughly
125 GiB RAM, 41 GiB available, 5.4 GiB *allocated* swap, and six llama-server
processes. The kernel reported memory PSI `some avg10=0.00` and
`full avg10=0.00`. A second short check observed **zero new swap-in/out
pages** and the new guard returned `memory_stall_clear` after warming.

This does NOT establish sustained performance, that swapping never occurs,
that the servers are idle or healthy at all times, or that a model got faster.
It does establish why unconditionally blocking work whenever existing
swap usage exceeds a threshold would be a flawed optimization.

Verification: focused offline tests cover parsing, corrupted PSI/counters,
stale host readings, pressure latch/recovery, swap activity, and integration
with the existing Star realtime brain and QoS. No live OBS, Roblox, Windows
gaming or model-speed A/B experiment occurred in this branch.

## 1. Higher *useful* intelligence, not just larger context windows

**Just-in-time grounded memory:** The September 28, 2026 JAM research argues
for preserving detailed episodic histories while retrieving relevant facts
at query time, rather than collapsing every experience into one summary.
For STAR: keep canonical, timestamped, source-attributed records of games,
scripts, design critique and observed fixes in Star Core Forge. Build a small
context pack per question: goal, active scope, known failure cases, 1–3
verified examples, fresh documentation, and missing/uncertain facts.
Source: https://arxiv.org/abs/2609.34385

**Skill lifecycle:** MUSE-Autoskill (May 26, 2026) proposes skill creation,
memory, selection, test feedback and refinement as a persistent loop.
Translate that into independently checked Roblox/Blender/animation/voice
skills, each with testable contracts, negative cases, provenance, version
history and measured generalization. A generated skill is NOT considered
learned until it improves held-out tasks without cheating.
Source: https://arxiv.org/abs/2605.27366

**Fast vs deep reasoning:** Keep local short-action policies under bounded
latency and reserve slower models for novel mechanisms, scene architecture,
hard debugging and research. Route by *completed-task success per second*
and evidence-backed uncertainty, not raw generated-token rate.
Avoid maintaining duplicate context across six servers unless measured
cache savings outweigh memory and swap pressure. llama.cpp supports
server metrics, prompt caching and slot management; test versions and
memory/latency side effects before activating cache/prefix policies.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

Acceptance targets (not achieved): paired baselines at the same compute;
measured p50/p95 end-to-end completion and first audible speech latency;
no degradation in verified coding, visual design, game goals or factual
correctness. Treat faster but less accurate routes as regressions.

## 2. Actual autonomous game skill — private Studio first

STAR's new `StudioPracticeCycle` already connects trusted game observations,
short permitted inputs, signed objective results, forecast calibration and a
practice-only skill bank. The next gain is **real data**, not another
synthetic score.

Use the official built-in Roblox Studio MCP server's playtesting and input
simulation in private, owner-authorized projects; Roblox announced these
capabilities on March 5, 2026:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

Design three repeatable mechanic families: parkour timing, moving-target aim,
and puzzle interaction. Each attempt first fixes the objective, game version,
map seed and control budget. The *independent game state* determines success
or failure, including failed attempts. Run a matched baseline and a new
controller across unfamiliar variants. Keep held-out maps/seeds away from
training and from Star's live persona memory.

GameWorld (April 8, 2026) provides a useful research model: 34 games,
170 state-verifiable tasks, and both low-level controls and semantic actions.
It highlights hard problems in timing, memory and irreversible mistakes:
https://arxiv.org/abs/2604.07429

Never infer game mastery from the action being dispatched or from an AI's
own commentary. No automatically playing public games, buying items,
affecting other players, or publishing a game through this laboratory.

## 3. Better complete game creation — graphics, geometry, animation, play

Build in stages: scene layout and dimensions -> attachment/joint/collision
checks -> navmesh/player reachability -> materials/UV and lighting -> rig and
animation continuity -> responsive UI states -> VFX/audio timing -> real play.
Inspect actual runtime video and multiple camera positions, not merely Lua
or a single screenshot. Check for holes, floating props, missing textures,
clipping, unreachable spawns, camera occlusions and input/UI contradictions.

GameDevBench (ICML 2026) demonstrates that adding image/video feedback can
improve game-development agent outcomes, while graphics-focused tasks
remain difficult. Reproduce results with independent blind comparisons
rather than copying a benchmark's headline score:
https://sethkarten.ai/papers/gamedevbench.html

Combine Star's existing `studio_scene_integrity`,
`studio_multimodal_quality_gate`, `studio_scene_regression`,
`studio_practice_cycle` and GameTransferEval; avoid adding duplicated
quality gates without connecting them to real play and rendering evidence.

## 4. A humanlike, charming Star VTuber — within available compute

The goal is **consistent, authentic virtual character behavior**, not false
claims of human biology or fabricated personal history. Use Star's actual
completed activities, hobbies, successes, mistakes and verified prior
conversations. Maintain different private versus on-air memory scopes.

**Turn-taking:** LiveKit's v1-mini turn detector runs locally on CPU. Test it
with real interruptions, quick acknowledgements, silences and laughter.
Prefer natural pauses to relentless narration; keep game and audience focus
as independently measured resources.
https://docs.livekit.io/agents/logic/turns/turn-detector/

**Animation:** Drive her existing chibi twin tails, gold ribbons, amber eyes,
expressions, shoulders and ears/cat/puppy modes through a shared timed
performance plan. Use real audio amplitude plus phoneme timing if the TTS
backend actually exposes validated alignment; avoid estimating phonemes from
volume alone. Independently compare OBS video and local audible output.

**Hardware realism:** AVTR-1 publishes a 25 fps / five-frame benchmark of
232 ms per chunk on an RTX 4060 (a 200 ms real-time chunk budget), about
0.86x real time before the rest of STAR's gaming/inference workload.
Its reference results on different GPUs do not establish Star's own setup.
Do NOT silently switch an 8 GB 4060 gaming machine to a costly generative
avatar engine. Prioritize lightweight Live2D/skeletal rigs with secondary
hair physics and measured OBS headroom. Revisit generative motion models
only if actual resource and quality tests justify their cost.
https://huggingface.co/avaturn-live/avtr-1

**Believability checks:** audio-to-mouth delay, eyes following game and
chat attention, interruption handling, genuine event relevance, repeated
phrases, game FPS/OBS drops, consistent personality, and calibrated
self-reporting. Use real anonymized recordings only with authorization.

## 5. Near-term implementation order and success criteria

1. **Enabled host polling test:** run this branch's optional guard on a
   dedicated 1 Hz Linux worker for 30–60 minutes while existing inference
   runs normally. Log only counters, pressure state and queue latency.
   Revert safely if unexpected false deferrals occur. This has NOT run.
2. **Paired CPU/server throughput:** compare the same 40+ private tasks under
   equal budgets with and without optional PSI-based background admission.
   Record first-token p95, completed tasks/hour, failures and page-in rate.
   Preserve working production model configurations until evidence justifies
   replacing them.
3. **Live gaming/VTuber integration:** baseline Roblox + OBS + audio + animated
   rig; characterize game FPS, OBS dropped frames, voice backlog, barge-ins,
   lip sync and resource pressure. Keep heavy training off when live.
4. **Real self-learning:** gather 30+ private Studio signed trials on diverse
   mechanics, then score unseen holdouts with independent witnesses. Improve
   skill only when valid outcomes beat the baseline.
5. **Owner-readable Forge report:** explain what changed, what tests passed,
   which metrics improved/regressed, and exactly what is still unproven.
   GitHub is an optional publication path; the local Core Forge maintains
   history, tests and rollbacks independently.

This work adds a tested scheduling guard and a researched integration plan.
It does **not** claim increased neural-model intelligence, increased measured
model throughput, autonomous Roblox mastery, Windows adoption, or a human-quality
live stream. Those claims require separately measured real-world experiments.
