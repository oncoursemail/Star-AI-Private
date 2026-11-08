# STAR AI — descriptor-anchored model artifacts, fast game intelligence, natural VTuber streaming
**November 4, 2026 · working-code research**

## What was actually improved

The previous host artifact preflight checked model weights, runtime binaries and voice configuration by SHA-256, then constructed a trusted model catalog. A gap remained: it inspected the parent directory, then reopened a filename by path. A concurrently replaced parent symlink or a Windows junction could silently redirect that path. Worse, identical copied bytes would still satisfy the model digest.

This change adds a **descriptor-anchored POSIX path**. STAR opens and verifies the parent directory itself, then uses directory-relative open operations to descend the hierarchy without following symlinks. Each directory entry must match the opened descriptor's identity, and the final artifact is also checked both before and after hashing. When Python does not support directory file descriptors, notably on Windows, STAR rejects junction/reparse metadata and checks identity using the available filesystem calls. Adversarial tests simulate swapping a real directory or a file for a symlink *between* its metadata inspection and open. Under supported POSIX systems those swaps are rejected.

This change does NOT start OBS, games or models. It does not improve model intelligence, token throughput, voice quality, or actual gaming performance. It does not make Windows pathname traversal race-free: Python's standard directory-descriptor APIs do not work on Windows. That platform still needs restricted owner-managed model directories, and a reviewed native handle-based implementation if stronger cross-platform guarantees are required.

Python documentation: [os module and supports_dir_fd](https://docs.python.org/3.12/library/os.html); [pathlib Path.is_junction (Python 3.12)](https://docs.python.org/3.12/library/pathlib.html).

## Why infrastructure integrity matters for fast streaming

When the model or TTS voice actually loaded differs from the model whose latency was measured, STAR can select the wrong worker for a tight gameplay deadline. Preflight is deliberately a startup-only task: hashing several gigabytes during each LLM response would destroy latency. The embedding host still must load the **same inspected artifacts**, keep deployment files owner-controlled, and invalidate calibration whenever runtime, quantization, voice, adapters, weights or worker configuration changes.

Security boundary by platform:

| Check | POSIX openat-capable runtime | Windows fallback |
| --- | --- | --- |
| Relative path syntax and root ownership | Required | Required |
| Reject symlink/reparse path entries | Yes | Yes |
| Anchor parent directories to open descriptors | Yes | Not through Python standard dir_fd |
| Detect final file mutation during hash | Metadata + digest + descriptor identity | Metadata + digest, weaker race protection |
| Ensure launched worker loaded inspected bytes | Not provided | Not provided |
| Authorize gameplay, speech or broadcast | Never | Never |

All strict host-side controls remain optional until a verified worker-supervisor path exists. SHA-256 is a consistency check, not process attestation or a permission token.

## Roadmap for much better intelligence at the same hardware budget

**Reactive lane (frames):** A bounded skill policy for movement, navigation, combat and UI interaction. It acts only on trusted, fresh game observations and respects input-release and deadline checks. A large model should not sit on the critical path for every jump.

**Tactical lane (seconds):** A planner chooses skills, evaluates short-term goals, and reacts when a game mechanic changes. Timeouts cause a safe pause/replan rather than a late input burst.

**Strategic lane (between episodes):** Offline replay analysis, practice-level generation, documentation lookup, bug finding, parallel candidate strategies, game-rule hypotheses and reproducible training. Store a state/action/outcome trace but never equate STAR's own narration with independent success evidence.

**General-reasoning lane:** Source-grounded retrieval, uncertainty handling, self-verification, multi-model delegation and explicit abstention. Evaluate reasoning on held-out STEM, factual, planning, coding and Roblox tasks. Better quality requires more independently correct outcomes, not longer prose.

**Resource scheduling:** A game, an actual audio speaker and OBS get priority over optional VLM calls, code agents, rendering and self-training. Keep GPU reservations for the renderer. On an 8 GB card, compare CPU TTS and GPU TTS with identical workloads. Offload only when measured overall utility improves; CPU-side inference can still consume memory bandwidth needed by the game.

Use llama.cpp's [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) to compare baseline vs speculative decoding, same dataset, prompt lengths and GPU workload. Record end-to-end latency, tokens/second, acceptance rate, 1%-low game FPS, skipped OBS frames, first audible speech and **task correctness**. Speculative decoding is a hypothesis, not an automatic speedup.

## Learning to play games proficiently

Start with a permitted local or private-testing game and a repeatable curriculum: movement, timing, spatial navigation, object interactions, aiming/tracking, inventory management, cooperative play, then unfamiliar level combinations. Record screenshots/state with timestamps, acknowledged inputs and independently verified progress. Separate training worlds from held-out maps, mechanics, game versions and objective templates; rotating only random seeds is not enough.

For each failure, label whether it was stale vision, an action latency miss, input not released, a misunderstood mechanic, bad navigation, a weak plan, an unverified outcome or a game change. Direct each category to its own repair process. Practice should never optimize by weakening STAR's grading criteria.

The [GameWorld benchmark](https://gameworld-bench.github.io/) shows that partial progress and actual task completion diverge significantly for current game agents. A valid STAR report needs both, plus human novice baselines where feasible. The benchmark scores do not describe STAR's existing ability. Public gaming automation must obey game rules and never bypass anti-cheat or disrupt other players.

## Creating games, testing and debugging visually

Roblox announced its [built-in Studio MCP server on March 5, 2026](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643). On [May 28, 2026](https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854), Roblox added StudioTestService, programmable device simulation and VirtualInput for richer automated tests, including multiplayer sessions with up to eight simulated clients.

STAR should inspect a test place, choose scoped tool actions, generate several candidate Luau/asset/UI implementations, run a static lint/type check, perform a private Studio playtest, inspect screenshots and output logs, verify multiplayer/client-server behavior, and repair one verified failing behavior at a time. Visual polish needs animation/UI screenshots and human review; passing a unit test does not prove artistic quality. Maintain semantic history in local Star Core Forge with rollback, using GitHub PRs only for review/publication.

## A believable, expressive VTuber without impersonating a human

Natural streaming requires grounding, turn timing and selective silence. The persona should express a stable original voice and visual identity, react to *real* wins and mishaps, develop interests through actual projects, remember genuine successful/unsuccessful attempts with uncertainty, and avoid fabricating memories or claims of being human.

**Listening:** When viewers speak, use gentle head/eye movement and brief acknowledgments rather than a long unsolicited speech. Microsoft Research's [RESPOND (March 2026)](https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/) explores controllable backchannels and proactive turn claiming.

**Choosing when to speak:** During tense gameplay, silence can be more entertaining than synthetic chatter. For event-based narration, trigger from fresh game-state evidence and suppress duplicates. Microsoft's [Proact-VL, ICML 2026](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) studies autonomous speech timing for realtime gaming companions.

**Interruptions:** Brief acknowledgments, keyboard noise or music should not necessarily cancel speech. LiveKit's [March 19, 2026 adaptive interruption research](https://livekit.com/blog/adaptive-interruption-handling) provides an approach to distinguishing genuine barge-ins from backchannels. Its current [documentation](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/) describes cloud-assisted deployment conditions, so it should not be treated as an already-integrated, entirely local capability.

**Voice and movement:** [Kyutai Pocket TTS](https://kyutai-labs.github.io/pocket-tts/) is a CPU-oriented streaming TTS candidate; claims made on a reference machine do not establish quality or first-audible latency on STAR's Windows rig. Avatar visemes must follow *physically delivered PCM* rather than precomputed text. On interruptions, clear the audio queue, lip movement and captions together. Keep blinking, gaze, tail and idle motion restrained and accessible.

**Personality quality tests:** Blind-rate expressive speech, natural pausing, grounded humor, game focus, authentic interruptions, griefing resistance, memory consistency and viewer comfort across held-out conversations. Record p95 first-audible response, false interruptions, overtalk, unplanned silence, ungrounded speech and 1%-low game FPS separately. No subjective rating is evidence of human consciousness.

## Required next milestone: private end-to-end Windows rehearsal

Perform one authenticated, owner-approved **private** gaming/recording session with actual game-state feedback, host-controlled input, confirmed key release, OBS local recording, avatar renderer, synthesized speech and real hardware observations. Compare idle, game-only, stream-only and game+stream. Before declaring success, require real frame-time and voice/visual latency traces, independently verified game outcomes, a stable model identity, and no lost input/audio-stop acknowledgments.

The PR's completed unit tests prove the descriptor-path mitigation in an isolated POSIX test environment. They do not show a faster 8 GB GPU, a real gaming win, a live Windows model host, or a finished AI VTuber. Those are separate acceptance criteria, not assumptions.

**Priority after this PR:** implement a supervised Windows worker binding that loads exactly the verified runtime/weights and generates non-spoofable deployment lifecycle evidence, then run the nonbroadcast rehearsal. Avoid one more hypothetical speed claim until the device has actually been benchmarked.
