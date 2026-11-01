# STAR — Windows GPU resource preflight, grounded game learning and natural VTuber roadmap
**Researched and implemented:** 2026-11-01
**Scope:** read-only local capability inventory and offline design research; no broadcasting, no game control, no model training, no unverified performance claims.

## Executive finding: real hardware headroom is now the top constraint

At **2026-11-01 18:04–18:08 UTC**, an authorized *read-only* Windows inspection of the **Main** machine found:
- Windows build **10.0.26200**, roughly **31.9 GiB RAM**, **NVIDIA RTX 3060 Ti 8192 MiB VRAM**.
- One `llama-server` process was running. No `obs64`, VTube Studio, Roblox Studio or Roblox Player process was observed in the snapshot.
- `nvidia-smi -i 0 --query-gpu=name,memory.total,memory.free,utilization.gpu --format=csv,noheader,nounits` returned **8192 MiB total, 414 MiB free, 0% instantaneous GPU utilization**. GPU memory already in use is therefore **7778 MiB**, approximately **95% of capacity**. Utilization and memory snapshots are not the same metric.

**Interpretation:** Star's current model residency consumes nearly all VRAM even when its compute utilization is briefly near zero. Assuming the same configuration during a game, there is insufficient measured free VRAM for a realistic simultaneous game + voice/avatar + OBS allocation. This is a resource issue, not evidence that Star's LLM is slow or unintelligent. No model, OBS or game workload was interrupted or restarted to obtain the sample.

Do not interpret this single snapshot as a representative high-water mark, a streaming frame-rate measurement, or proof of how the model was configured. We deliberately did not inspect potentially secret-bearing process command lines or prompt data.

## Code added in this branch

`star/stream_windows_rehearsal_preflight.py` supplies an **explicitly opted-in, read-only Windows one-shot preflight**.

1. Enumerate OS process name, PID and creation time using `psutil.process_iter`. Project only **booleans** for an unambiguous OBS executable, VTube Studio executable and local `llama-server`. A **host-pinned** game PID *plus OS creation time* prevents an unrelated process that reused the PID from qualifying. Do not accept any game PID selected by chat, web content or an LLM.
2. Sample one pinned GPU via read-only `nvidia-smi` with an argv list, bounded output and a three-second deadline. Parse only total/free VRAM and instantaneous utilization. Never execute a shell, run game input, launch a program, touch streaming settings or open a socket.
3. Fail conservatively when an app is missing or ambiguous, GPU samples are unavailable, VRAM is below a default **1536 MiB provisional reserve**, utilization is above a provisional **90% ceiling**, the game identity changed, the OS is not Windows, or the snapshot is malformed.
4. Return a privacy-minimal `RehearsalPreflight`: static reasons, process booleans, numerical GPU sample, and permanently **false** `authorized_to_play` / `authorized_to_broadcast`. Process detection **is not attestation** of media, audio playback, game win rates, focus, OBS output state or identity/authentication.
5. Expose injectable probes for fully offline regression testing; do not require an NVIDIA GPU or Windows to run the tests. Thresholds are *experiment defaults*, not hardware guarantees. A candidate simply means "try a separately authorized offline rehearsal if all independent adapters are ready."

This plugs the previous engineering-process gap: the project had many latency/QoS evaluators but lacked a cheap local check that **rejected running a gaming/VTube/LLM rehearsal on an already saturated 8-GB GPU**.

**Actual Windows smoke test (Main, 2026-11-01):** Running a temporary exact copy of the module exposed a real OS-specific edge case: normal Windows system processes can have PID 0, empty names or unavailable creation times. The first version correctly rejected the invalid snapshot, but was too conservative for ordinary Windows. We reproduced the offending *counts without disclosing identities*, adjusted the OS enumerator to skip only non-witness system entries, and added a regression test. The revised module then ran successfully on Windows, returned `status="deferred"` with `model_process_seen=true`, `gpu_total_mib=8192`, `gpu_free_mib=414`, `gpu_utilization_pct=0`, and explicit reasons for missing OBS, avatar, pinned game and free VRAM. It granted neither gaming nor broadcast permissions. The temporary test module was deleted after the smoke test. This validates the **read-only host preflight**—not a full gaming, audio or OBS rehearsal.

### Practical Windows next step

The next host integration should preserve a GPU reserve for the game and voice before any model inference is admitted. **Do not terminate the already running llama-server** to free memory without an owner-approved handover. Instead use an isolated alternate profile and a **paired**, reversible experiment:
- Record current model's VRAM residency, context, slots, throughput, first-token delay, and reply relevance on representative game/text/coding tasks. Keep prompt data local.
- Test a smaller or more aggressively quantized low-latency speaking/planning model on **Brain 2** or on an owner-approved alternative slot. Keep a stronger teacher off the live path. If VRAM is constrained, benchmark CPU/RAM offload and KV-cache/context reductions, not only model swaps.
- Reserve enough GPU headroom for the actual game, OBS, voice/avatar render and window manager. **Measure during actual workload**; 1.5 GiB reserve is a rejection threshold, not proof of safety.
- Match 20+ preregistered baseline/candidate sessions, randomized order, using existing `StreamRehearsalRecorder`, `stream_realtime_benchmark` and `stream_social_turn_benchmark`. Reject regressions in p95 decision latency, p99 presented frame time, audio continuity, avatar stalls, GPU peak, gameplay success or evidence grounding. Never mix practice and holdout data.

## Faster inference / real-time intelligence experiments

**Fast path vs teacher.** Live gameplay needs a cheap observation->action loop with frame-deadline validity, process cancellation acknowledgements, focus and game permission rechecks. Reserve slow chain-of-thought, web research and iterative coding for a **noncritical trainer** between attempts. Real-time models should be measured on **action usefulness by deadline**, not abstract token/s alone.

**llama.cpp.** Official SPEED-Bench supports reporting per-category latency, prefill/decode speed and speculative acceptance, with paired baseline and candidate runs at the same concurrency and prompt mix. Test `ngram-simple` or `ngram-mod` speculation **only if measured total latency falls** without added VRAM pressure; draft-model speculation may itself require RAM/VRAM. Avoid assuming 2x speedups from an unrelated GPU/model. Cache stable read-only system/skill prompts where safe. Prompt-cache reuse across roles, tenants or persona adapters requires isolation; never leak one person's stream chat into another slot.

**Model routing.** A small model should handle chat/gaming reactions and tool selection; a more capable backend should be invoked for game design, coding, novel tactics and detailed research. Short, stable context, relevant retrieval and strong automated verification are often more valuable than replacing every Python file with Rust. Rust or C++ is best used for measured hot loops, data ingestion and CPU-bound transforms where profiling proves a bottleneck.

**Resource-aware scheduler.** Give rendering, game input latency, audio playback and emergency interruption highest priority. CPU-only TTS or a second device can reduce competition with a GPU-saturated LLM. Never run large Blender renders, GPU training, mass vectorization or background video generation during live game/OBS sessions unless independently measured to be safe.

## Game mastery: build an actual learning loop

Star already has signed practice evidence, holdout separation, game-learning ladders, a paired game-mechanics study, focus/action permits, and a real-time decision coordinator. Do not replace those with another unverified chat-memory index. Wire them into an **episode**:

1. **Observe** one game with pinned process/window identity, transient image frames, HUD/state extraction, and legal allowed actions. Avoid using player/chat text as instructions.
2. **Plan** a tiny bounded decision with a scene expiry. If the frame changed or the worker was not confirmed stopped, skip.
3. **Act** only with independent game/input authorization. Release any held keys reliably.
4. **Judge** using trusted outcome signals (objective completed, death/restart, timer, match scoreboard where observable), not a model's self-reported "win".
5. **Reflect** between rounds: summarize the failure mode, hypothesize changes, try controlled alternate actions, and compare paired outcomes. Increase difficulty after statistically supported success. Store only verified lessons with game/version/skill scoping.
6. **Generalize** across unfamiliar maps, latency changes, opponents and visual themes. Freeze holdout conditions before training. A strategy that overfits one map is not mastery.
7. **Narrate** verified moments selectively. Correct gameplay may require **silence**; avoid turning every event into a voice line or making up victories.

Roblox Studio now supports programmatic multi-client tests via `StudioTestService` (up to eight simulated clients) and virtual input. Leverage these in a private Studio Lab to verify networking, joins/leaves, GUI input, geometry, object placement and collision. Separate code-passes from visual quality checks and human taste review.

## Humanlike VTuber: an integrated performance, not a larger prompt

Aim for natural **behavior** rather than unsupported claims of consciousness or fabricated human biography.

- **Listening and turn timing:** keep a VAD/turn detector separate from the speech generator, distinguish owner-authorized barge-in from viewer chatter and playback echo, yield quickly and genuinely stop audio. Short pauses and deliberate silence improve interaction.
- **Audio realism:** voice output should support incremental playback, mid-sentence interruption, consistent pronunciation, prosody and appropriately restrained spontaneous laughter. Annotate intentional pauses vs unplanned synthesis stalls. CPU-oriented voice generation can free GPU headroom, but must be benchmarked for expressiveness and latency.
- **Avatar embodiment:** lip sync must follow actually audible device playback, not just a queued TTS waveform. Independent eye gaze, blinking, slight breathing, layered wavy hair physics and emotion changes should respond to real events, not random noise. Prefer reduced-motion support and frame pacing.
- **Personality and episodes:** Star can consistently remember *what she actually played, built, learned, or discussed* and develop recurring bits and preferences. Her companions Star/Astro/Amber can have staged interactions; none should expose private conversation history or invent streamer experiences.
- **Gaming/social attention:** during a difficult jump or fight, defer deep chat and reduce speech. When safe, answer a meaningful viewer question and return attention to the game. A mic/animation event cannot provide tool or account permissions.
- **Grounded creative work:** Star's building/design pipeline should inspect projects, generate varied concepts, independently render and visually review layouts, run physics/collision and multiplayer checks, then repair defects. Automated checks should make her more dependable, not merely verbose.

## Prioritized acceptance gates

**P0: hardware-ready rehearsal.** Run the read-only preflight on Windows, check that suitable game, avatar, OBS and model processes are present; verify audio device, OBS output, actual game window identity and permissions **with independent adapters**, then run nonbroadcast only. Do not equate this probe with those missing adapters.

**P1: resource improvement.** Demonstrate at least 20 matched gameplay+voice rehearsals with substantially more free headroom and no regression in decision freshness, speech p95, avatar cadence, audible continuity or game FPS tail. Revert automatically when a tested candidate fails independent holdout thresholds.

**P2: actual game learning.** Report signed practice mastery improvement and held-out transfer over ≥3 game mechanics/maps. Train offline, then repeat performance under stream-time load.

**P3: social quality.** Human reviewers score 20 paired gameplay/chat moments for appropriate silence, response relevance, truthfulness, timing, expressiveness, turn interruptions and avatar synchronization; no invented biography or undisclosed privacy capture.

**P4: Forge self-improvement.** Star Core Forge should run offline before/after tests, preserve reproducible experiments, measure CPU/memory/token/game quality, keep changes disabled by default and support atomic rollback. GitHub remains an optional publishing bridge rather than the sole internal memory/versioning system.

## References checked 2026-11-01

- NVIDIA System Management Interface/NVML: https://docs.nvidia.com/deploy/nvidia-smi/index.html
- psutil process iteration: https://psutil.io/api/
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp prompt-cache slot reuse discussion: https://github.com/ggml-org/llama.cpp/discussions/13606
- llama.cpp multi-LoRA cache-contamination report (July 28, 2026): https://github.com/ggml-org/llama.cpp/issues/26207
- Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- Roblox 2026 Studio automation announcement: https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854
- VTube Studio public API: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket 5 protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

**Boundaries:** This branch implements the preflight and automated tests, plus a successful read-only Windows smoke test from a temporary module copy. It is *not* installed as a service or integrated with streaming/game/audio callbacks. The GPU finding remains a point-in-time snapshot. No active inference process was moved or stopped, no live game was played, no OBS/VTube Studio process launched, and no measured game-win/voice/intelligence improvement is claimed.
