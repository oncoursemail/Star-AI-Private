# STAR — Nonblocking game-host shutdown, real-time intelligence, and VTuber roadmap
**Research/implementation date:** 2026-11-02 (US Central). **Scope:** private Star-AI-Project, stacked on PR #919. This is an engineering design and offline-tested patch, not proof of live game control, completed streaming, or increased model intelligence.

## Executive finding

The immediate deployability blocker is not another benchmark or another agent personality prompt: the trusted game host must be able to request cancellation and **all keys/buttons up while an authenticated OBS status request is blocked**. A normal WebSocket request can take several seconds. Previously `ObsGuardedGameEpisode.stop()` had to acquire the same episode lock held across that network request. An emergency owner stop could therefore wait for OBS; worse, an in-flight calculation could produce an advisory permit before it noticed the stop.

The new implementation uses a thread-safe stop latch and a once-only host cancel/key-up request independent of the long-lived episode lock. It ensures the in-flight operation rejects its result after shutdown. The slow OBS sampling thread remains responsible for completing witness/loop revocation when it unwinds. This is **not** a verified physical key-release receipt. The actual Windows key dispatcher still needs its own OS-level watchdog and edge-of-actuation checks.

### Reproduction and fix

- Before the patch, a simulated OBS snapshot blocked in one thread while another thread called `stop()`. The stop call did not finish within the bounded 400 ms test interval.
- After the patch, the owner's stop path requests worker cancellation and all-keys-up without waiting for the same OBS mutex. The active/revoked status becomes immediately observable.
- A second adversarial test stops the episode while the **final claim** waits for OBS; no positive claim may leave the episode.
- Once-only cleanup callbacks prevent duplicate host cancel or key-release requests on repeated shutdown.
- Regression gate: `tests/test_obs_guarded_game_episode.py` plus broader `obs/game/stream` tests, Ruff, Python compile, and Git checks.
- This bridge remains opt-in. There is **no** real input injection, game launch, live stream change, credential disclosure, model training, or Windows deployment in this patch.

## Research-to-product architecture: four independent loops

### A. Deadline-accurate fast agent
For each frame: trusted host captures an authorized game frame → abstracts a bounded state → chooses a known-safe fast action before a deadline → checks focus, game ownership, OBS epoch, and stop latch at the physical boundary → acts through a separate host watchdog. On timeout or stale evidence, do nothing or release controls. Do not make the model's confidence a physical input authorization.

**Measure:** first usable action latency (not token/s only), late actions, p50/p95/p99 decision latency, stale claims, FPS, GPU-resident working set, dropped OBS frames, key-held durations, watchdog key-up confirmation. Must test in *live-clock* environments where the game continues while the agent reasons.

RealtimeBench, *The World Won't Wait* (posted 2026-10-14), reports 180 continuously running tasks across six game types and a two-timescale learning design. It reports fast-student mean progress 13.51→24.19 after two learning rounds, **not** a result reproduced by STAR. See https://arxiv.org/abs/2610.20665 and https://github.com/RealtimeAgents/Realtime-Bench . Different benchmark releases and task counts should not be combined into a single score.

### B. Slow teacher and evidence-backed learning
The teacher should run **after** live play, not on the critical action path. Inputs: bounded scenario IDs, anonymized host-verified state/action/outcome receipts, deterministic replay hashes, and difficulty tags. Teacher generates one specific strategy hypothesis at a time. A preregistered A/B study tries it on paired but unfamiliar scenarios, checks safety and latency regressions, and promotes only after independent validation. Keep private holdout seeds inaccessible to planner prompts. Save short, sourced `what worked / under what conditions / evidence confidence` skill cards. Distinguish model-reported emotion or victory from observed outcomes.

Recommended initial teaching tasks: timing a platform jump; choosing cover in a shooter; selecting a kart line; moving through a room using a minimap; constructing a small Roblox obstacle course; recovering after an unexpected game update. A task is learned when transfer works on **unseen maps** under the live clock, not when Star repeats the original route.

### C. Voice/avatar/live personality director
Separate a low-latency director from the full language model. The director decides `speak | listen | react silently | wait` using player speech activity, gameplay events, cooldowns, and whether Star is in a high-stakes maneuver. The language model writes a short utterance only when allowed. Playback timestamps—not just generated text—drive lip-sync, blinks, eye targeting, and expression intensity. Barge-in cancels outgoing audio and marks any partial utterance so it is not falsely remembered as spoken.

Track: perceived response latency, p95 end-of-turn errors, interrupt frequency per viewer, overlapping speech, silent-gap duration, observable smile/blink timing, audio/video drift, and whether commentary refers to *actually observed* game events. Be warm, playful, funny and consistent, but transparent to viewers that Star is an AI character. Do not present generated pseudo-memory, fictional feelings or offscreen activity as physically experienced events. Private messages, donation handling and purchases remain owner-scoped.

Proact-VL (posted March 2026) specifically studies **when to speak**, not only what to say, in live gaming commentary/guidance: https://arxiv.org/abs/2603.03447 . VoiceChat-TTS (August 2026) documents streaming synthesis with mid-utterance interruption controls: https://arxiv.org/abs/2608.13831 .

Pocket TTS publishes tiny CPU-oriented English models from October 2026: `english_18m_2026-10`, `english_7m_2026-10`, `english_2m_2026-10`. Benchmark audio naturalness, voices, first playable PCM, CPU load, and conversational overlap against the incumbent voice pipeline before switching. An approximately 200 ms first-chunk reference is **not** a prediction for the user's machine. https://kyutai-labs.github.io/pocket-tts/

### D. Game creator / Roblox Studio verification
Adopt an inspect→plan→generate N candidates→run lint/analysis→execute inside Studio→play-test→visual inspect→repair→commit recipe, with one passing candidate selected by *executable* evidence. Use independent project snapshots and safe sandbox scenes, and test replication, player joins/leaves, collisions, object hierarchy and UI scaling. No success claims from a code-only check.

Roblox's OpenGameEval (arXiv:2610.02563; repository current 2026-11-02) covers stateful Studio environment exploration and executed scene/play tests. The paper describes 84 curated tasks and 13 evaluated models, emphasizing that looking at relevant game objects before editing correlates with better performance: https://github.com/Roblox/open-game-eval .

## Inference and compute plan on the owner's hardware

A read-only Windows inspection on 2026-11-02 found **Windows 11 Pro, ~31.9 GiB system RAM, RTX 3060 Ti 8 GiB, ~5,235 MiB VRAM free at 28% GPU utilization** (one snapshot, no sustained benchmark). No OBS, VTube Studio, or Roblox process appeared in the sampled process-name list; therefore a combined live demonstration is **not yet measured**. The dedicated RTX 4060 is a separately mentioned target, not evidence of currently available headroom on this host.

1. **Protect the game:** prioritize render/encode, game input and audio deadlines; perform background practice and indexing in lower-priority windows, preferably on a separate machine. Put admission control on free VRAM, encoder queue, GPU utilization, host RAM pressure, OBS frame stall and TTS CPU occupancy.
2. **Run short-model paths:** choose small quantized local models for fast action decisions and a stronger model for offline teacher/research/coding. A stronger model may be **slower** in live games. Verify accuracy and action deadline success together.
3. **Cache carefully:** benchmark slot/prompt prefix reuse with true mixed workloads, not only idle loops. llama.cpp issues opened 2026-10-09 and 2026-10-22 describe potential KV-cache stalls and restore failures; pin a known-good revision or guard cache options with canaries. https://github.com/ggml-org/llama.cpp/issues/30252 and https://github.com/ggml-org/llama.cpp/issues/30961 .
4. **Speculative decoding:** run the official SPEED-Bench against the *already running* server; compare base vs draft alternatives under identical context, concurrency, VRAM reservations and CPU conditions. Draft-acceptance throughput gains can disappear during GPU contention. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .
5. **Knowledge:** keep offline retrieval of verified Roblox APIs, Luau examples, design standards and saved host-evaluated gameplay skill cards. Attach provenance, staleness, and confidence. Do not use browsing or unverifiable memories for action authority.
6. **Autonomy:** scope permission to an approved game/program/project and session. Allow routine self-directed practice and self-scheduling inside that scope; retain approvals for irreversible external actions, purchases, publishing and other people's private data.

## Acceptance experiments (order matters)

| Gate | Environment | Measurable criterion | Status |
|---|---|---|---|
| Emergency key-up request | Offline two-thread fake OBS stall | Stop returns promptly; one cancel/one release; no claim or permit after stop | Implemented; offline regression |
| OBS authenticated witness | Fake and then owner-approved OBS on loopback | Observe OFF→ON→OFF and restarts; reject stale evidence; never start broadcast | Existing offline coverage; Windows socket acceptance outstanding |
| Input watchdog | Owner-approved nonbroadcast local Windows test | Focus loss / emergency stop releases physically held keys; verify OS key-up, not merely callback | Not implemented |
| Whole VTuber loop | Local authorized test game + avatar + OBS in nonbroadcast mode | Game outcome, real audible PCM, lip-sync, end-to-end latency, FPS and dropped frames recorded together | Not completed |
| Gameplay learning | Paired fresh seeds with independent verifier | Skill transfer and timely action success improve without new regressions or holdout leakage | Research/partial offline components only |
| Roblox construction | Sandboxed Studio project | Playable multiplayer build with executable checks and screenshot review, no human bypass | Proposed |
| Long-session persona | Owner-reviewed transcript and timing metrics | Stable preferences, context-appropriate silence, truthful game memories, no excessive interruptions | Proposed |

## Review and security boundaries

- The patch **does not** claim the physical keys are up merely because release was requested.
- Emergency callbacks must be short, nonblocking and thread-safe; if they hang, Python cannot guarantee emergency responsiveness. A separate out-of-process watchdog is required for final physical safety.
- The game-host code must never expose OBS credentials, stream keys, raw window captures, private viewer data or unapproved microphone transcripts through public diagnostics.
- Stacked draft PRs must not be mistaken for merged `main` or released Windows functionality. CI outcome for this PR is independent of the broader stacked PR chain.
- Validate measurements on the user's actual 3060 Ti and future 4060 system before claiming FPS, quality, or intelligence improvement.

## Sources (verified as of 2026-11-02)
- OBS WebSocket official repository and v5 authentication guidance: https://github.com/obsproject/obs-websocket
- RealtimeBench / TORSI: https://arxiv.org/abs/2610.20665
- Proact-VL proactive streaming commentary: https://arxiv.org/abs/2603.03447
- VoiceChat-TTS: https://arxiv.org/abs/2608.13831
- Kyutai Pocket TTS: https://kyutai-labs.github.io/pocket-tts/
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- llama.cpp cache restore and idle-stall reports: https://github.com/ggml-org/llama.cpp/issues/30961 ; https://github.com/ggml-org/llama.cpp/issues/30252 .
