# STAR intelligence, human-natural VTuber, realtime systems and game-building R&D
**Research snapshot:** 2026-10-25. **Status:** offline feature and candidate experiments; no production stream, engine controller, voice model, or model weights are installed by this change.

## Executive engineering decision

STAR's most useful near-term improvement is not more unvalidated context or pretending that a chat model has become sentient. It is a feedback loop with real observation, separate action permissions, independent testing, and measurable improvements in gameplay and production quality. Streaming naturalness must be implemented with *playback* and *turn-taking*, not simply more emotionally intense scripts. On an 8 GB consumer GPU shared with a game, quiet is often a better experience than an additional model call. Preserve Star's original personality and clearly disclose that she is an AI performer.

The new tested slice, `star/stream_turntaking.py`, adds a host-input, opt-in, echo-aware, debounced voice arbitration policy. `StarStage.prepare(turn=...)` can now defer speech while another speaker is active; a confirmed owner voice produces a **suggestion** that the trusted host interrupt its current audio/animation. There is no audio capture, voice recognition, speaker identification, device control, model inference, or broadcast side effect. It composes with the existing `StreamDirector`, `StarStage`, `StreamTelemetry`, `LatencyWindow`, `StreamEpisode`, and signed gameplay practice systems.

## 1. Make her sound conversational without faking humanity

**Evidence.** Kyutai's Moshi implements a full-duplex spoken dialogue architecture with concurrent incoming and outgoing audio streams. Its reported latency is specific to the authors' research setup and cannot be assumed on STAR's GPUs. Kyutai Pocket TTS is a small CPU-oriented speech model; its existence suggests an option for offloading voice generation when GPU contention is high. These are *evaluation candidates* only, not currently integrated STAR features. Sources: https://github.com/kyutai-labs/moshi ; https://kyutai.org/next/tts/

**System design, five independent clocks:**
1. **Capture:** trusted host obtains a consented voice stream, echo-cancellation confidence, audio device clock and source identity. A voice model must not decide who the owner is. No private audio leaves this device unless expressly authorized.
2. **Turn sensing:** VAD produces short local-monotonic frames. Require sustained speech before owner interruption; suppress spurious noise; allow silence after the last voice frame; fail closed on missing/stale frames, mixed speakers and uncleared echo.
3. **Response policy:** host-moderated viewer questions; game events ranked by urgency; prevent chatter during difficult gameplay. A true owner interruption may stop the current utterance; a viewer cannot unlock owner capabilities by saying "I am the owner."
4. **Voice generation:** streaming TTS may output short chunks for low perceived latency. Speech synthesized, queued and started playing are different from speech completed. Never promote queued/partially played words into STAR's autobiographical continuity.
5. **Motion and expression:** lip/jaw/eyes, blink and hair/tail physics are coupled to *audible* chunks and evidence-based emotion. With interrupted speech, reset face, jaw, hair and motion to neutral; reject animation frames from the cancelled sequence.

**Natural, believable behaviors to evaluate:** hesitation when unsure, an understated laugh when context actually warrants it, pauses for action, varied but stable prosody, eye tracking toward a verified game event, waiting for a person to finish, genuine corrections when wrong, occasional topical follow-ups, selective reading of viewer messages, and different cat/puppy expression styling without forced catchphrases. Build a private listening panel that independently grades "talked over person", "unearned joy", "uncanny fake emotion", "latency", and "repetitive lines". Do not create false childhood stories or pass the AI off as human. Frame Star as an original fictional character with an authentic running show history.

**New turn-taking invariant:** the owner source is host-authenticated, echo-cleared, and confirmed over at least 120 ms of fresh activity; only then can `TurnAdvice.should_interrupt` become true. Stale/no VAD data, untrusted echo, guest talk, mixed talk and transient noise force a hold rather than a forced utterance or owner-level interruption. Hold after activity for 350 ms. Thresholds are **initial policies to tune in offline tests**, not empirically proven optimum values. Host must explicitly `StarStage.interrupt()`, silence playback and invalidate old motion. `StarStage.prepare(turn=...)` only holds new commentary; it does not cancel in-flight audio.

## 2. Gameplay intelligence is a measurable loop, not a promise

**Observe:** capture game frames, UI state, collision geometry, damage, objectives, menus, controller state, maps and temporal changes. Label every observation with source, clock age, game version, episode, and uncertainty. Separate what the screenshot truly shows from guesses. For Roblox use the official built-in Studio MCP server, which Roblox announced on March 5, 2026, and only within an authorized test place. Its playtesting and simulated player input can support iterative bug reproduction and verification. Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ; https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

**Act:** bounded, game-specific, owner-authorized symbolic actions, not arbitrary shell code from a video or chat. Use event-triggered controls + a short horizon; let the game receive actual inputs. Keep action budgets and a panic-stop. Start in a sandbox where all progress is throwaway.

**Verify:** obtain outcomes from an independent observer (goal completed, score, damage, objective reached, health, elapsed game ticks), not from STAR's generated explanations. Signed practice outcomes are useful for auditing adapter provenance but cannot independently establish that the observer saw the game correctly. Preserve separate fresh validation seeds/maps that the planner cannot view. Build confidence intervals, not self-praised win rates.

**Learn:** save minimally sufficient procedural lessons, e.g. `obstacle_jump_when_velocity_low`, with applicability conditions, known failures, version, observation quality, and successful/failed trials. Decide whether to practice new actions by uncertainty and real coverage gaps. The existing `ActivePracticePlanner`, `GameplaySkillBank`, and `StreamEpisode` already provide bounded symbolic scaffolding; use them instead of a second unaudited memory store. Reuse a skill in a different map only as a *candidate* until new independent trials confirm transfer. Voyager's curriculum + reusable skill library + iterative feedback is a useful research precedent, not drop-in proof of general intelligence. Source: https://github.com/MineDojo/Voyager

**Proposed tests:** hold out 20% of map layouts and 20% of game versions; record win rate with Wilson lower bounds, deaths, time-to-goal, tool calls, controller errors, visual perception errors and compute per successful task. Collect 3-5 varied seeds per action for early debugging, then larger independent samples before publishing claims. Guard against "learning" by exploiting predictable evaluator seeds or changing the goalposts after reviewing a failed holdout.

## 3. Game creation should have engineering-grade, visual acceptance

STAR needs **three distinct reviewers**: (1) static/source and Luau tests; (2) engine runtime simulation/playtesting; (3) visual-quality assessment using rendered screenshots/video **plus spatial metadata**. Visual-only judging misses invisible collision and broken anchors; source-only tests miss overlapping props, z-fighting, floating shelves and ugly layouts.

**Deterministic spatial invariants:**
- Walls, floors, roofs and railings must be connected within explicit geometric tolerances. Reject unsupported props, open seams and unintended penetrations.
- Each mesh needs a meaningful pivot, bounding box, scale and role. Anchoring, collisions and passability must agree with gameplay. Reject out-of-bounds placement and collision overlaps except labeled intentional intersections.
- Probe camera positions and lighting conditions for texture warping, z-fighting, clipping, missing faces, stretched UVs, absent LODs and shadow errors.
- UI belongs in responsive safe areas; test multiple resolutions, input devices and font scaling. Reject overlapping hit targets, cut-off labels, inconsistent margins and inappropriate circular/over-decorated layouts.
- Animation passes should inspect physically plausible attachment points, blend transitions and cue-to-audio timing; reduced-motion variants remain usable.

**Loop:** generate/build -> programmatic scene checks -> run a controlled playtest -> capture multi-angle screenshots/video -> independent visual reviewer lists exact defects -> propose minimal repair -> rerun all prior tests -> compare against withheld exemplar-style constraints. Preserve before/after image and versioned defect logs. Do not call a model's own one-shot aesthetic score "perfect". Independent evidence is particularly important: GameDevBench's ICML 2026 333-task Godot benchmark highlights that graphical and multimodal tasks are tougher than code-only tasks, and reports improvement from image/video feedback. Source: https://github.com/waynchi/gamedevbench

## 4. Faster actual inference without damaging intelligence

Treat the 2026 STAR Roblox tool-prefix caching work in PR #620 as a **measured, separate performance branch**; avoid duplicating its cache logic or claiming its reported gains here. For every new speed idea, verify on the exact local llama.cpp build, CPU/GPU topology and target workload.

Candidate matrix:
| Candidate | Hypothesized benefit | Failure mode | Required A/B control |
|---|---|---|---|
| Fixed stable tool + rules prefix | Reused prompt/KV prefix | Bigger first request, tool misrouting | cold/warm first-audible, quality, identical task corpus |
| Speculative decoding: `ngram-simple` or compatible draft model | Faster decode on repetitive output | Low acceptance, added model RAM/VRAM, slower total latency | decode tok/s, first-token, RAM/VRAM, acceptance, answer accuracy |
| Smaller fast route for moment-to-moment reactions | Shorter reply startup | Inaccurate gameplay assertions | same grounded opportunities and independent ratings |
| CPU-friendly Pocket TTS (evaluate only) | Reduce gaming GPU contention | lower voice quality, CPU contention, sample drift | audio start p50/p95, intelligibility, PESQ-like proxies, reviewer MOS |
| Batch vision only between action-critical events | Protect FPS | Miss transient mechanics | held-out detection recall, game FPS p1, reaction deadline |
| Offline higher-quality model for planning/build QA | More repair passes | Longer inference and higher energy | fixes per GPU-hour, independent defect rate, cost |
| RAM/KV offload | Fit a larger working set | PCIe/RAM paging, huge first-token latency | tokens/s, warm/cold p95, memory bandwidth, page faults |

llama.cpp's official speculative-decoding docs list multiple implementations and emphasize performance depends on acceptance and draft overhead; user reports also show configurations where it regresses. Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md . Do not silently enable speculative decoding for everyone. Use budgeted paired A/B traces and revert negative changes. VRAM reported free by the host is not proof of extra safe memory (other processes and transient allocations matter). Maintain a reserve; stop training during the stream.

**Quality gate:** equal opportunities, independent review, grounded speech ≥ baseline, unexpected speech ≤ baseline, talk-over ≤ baseline, game stalls ≤ baseline, and p95 first-audible latency improves by a predeclared meaningful threshold. STAR already has `stream_quality.compare_stream_profiles`; run it before recommending a route, and always keep human review before production promotion. Distinguish token throughput, first-token time, first-*audible* time and gameplay FPS. They are separate performance measures.

## 5. General knowledge without filling storage with unreliable internet text

Use a tiered, provenance-based knowledge graph: (a) stable curated references; (b) timestamped web/tool observations; (c) user's explicit project requirements; (d) experimental hypotheses; (e) verified execution/test traces. Do not call web excerpts, Discord posts and creator tutorials equally reliable. Store source URLs/digests and review dates; limit data retention and obey licensing/robots/access controls. Avoid scraping copyrighted video archives into model training and avoid committing chats/voice recordings to public GitHub.

For each question, retrieve only necessary evidence; link facts to the current task context. Assign an expiry to price, laws, game mechanics and APIs. Track source conflicts rather than pretending one answer is universally true. Test multi-hop factual QA, citations, source reliability, up-to-date change detection, "I don't know" calibration and user correction. A large vector database does not itself raise foundation-model intelligence; the evidence and evaluation loop must actually improve the answer.

## 6. Layered architecture with safe checkpoints

```text
owner/stream consent      authorized game/Studio controller       approved knowledge source
        |                               |                                  |
trusted mic/VAD (no PCM here)     observer & timestamped frames     reviewed, scoped snippets
        |                               |                                  |
TurnTakingGate ---> StreamDirector <---- world-state/reasoning planner <------+
        |                   |                    |
        |              StarStage                |-- ActivePracticePlanner -> game sandbox
        |                   |                    |                         |
host stops audio <---- TTS playback ack          +---- signed practice ledger <- host grader
        |                   |                    |
       neutral rig <------ motion             independent withheld eval
```

All trust boundaries matter. An owner-approved planner is not itself permission to control a real game, capture a mic, broadcast, modify an account or promote to main. Stage and turn-taking logic consume host attestations and are not security-grade identity verification. A new input adapter must establish authentic owner source identity, echo cancellation, frame age and moderated messages before passing events inward. Disabled is the default.

## 7. Acceptance and rollout plan

**Phase A — implemented here:** 120-ms owner voice confirmation, 350-ms quiet hangover, 250-ms freshness window, echo-fail closed, no-PCM in-memory gate; optional integration into `StarStage.prepare`; adversarial unit tests including a complete simulated interruption with playback invalidation. No "now human" claim.

**Phase B — real device rehearsal:** on STAR's actual stream-capable computer, host records privacy-preserving local VAD windows, explicit owner/guest label from trusted routing, echo-cancellation status, playback ack and frame rate. Run 30 minutes of *unpublished* clips with at least 30 owner barge-ins, 30 guest interruptions, 30 clipped syllables and 30 playback echoes. Human-review false cancellation, missed interruption, talk-over, perceived naturalness, stalled frames and response p50/p95. Reject the candidate if false owner preemption occurs under echo or guest audio.

**Phase C — play + build:** connect owner-authorized Roblox Studio MCP on the Studio machine, train on sandbox worlds, log deterministic game outcomes and independently grade 2D UI/animation/3D defects. Build from scratch and repair faults without disabling held-out checks. STAR's abilities must be recorded per engine/game/version, not as a blanket "can play any game" promise.

**Phase D — compare intelligence + speed:** reproduce a fixed benchmark bundle across task classes (QA, math/coding, long-horizon planning, Roblox UI/design, game mechanics, controller use, streamer events). Store independent ground truth and measured compute; choose high-quality routes by *paired evidence*. Publish percentage gains only when actual hardware A/B or independently reviewed output supports them.

**Phase E — live after approval:** on-air disclosure that Star is an AI VTuber, explicit mic/chat/privacy permissions, opt-out, emergency stop, observability dashboard and auto rollback. Never merge draft experiments to `main` merely because unit tests pass.

## Exact scope of this commit

* New: `VoiceFrame`, `TurnAdvice`, `TurnTakingGate` in `star/stream_turntaking.py`. Conservative debouncing, stale/echo/mixed-source protection, privacy-minimal counters.
* Integration: optional `turn` argument on `StarStage.prepare`, with host-readable hold recommendations and no I/O side effects.
* New: `tests/test_stream_turntaking.py`, including attempted frame replay/overlap, echo spoof, guest/owner differentiation, talk-over hold and stage interruption lifecycle.
* No new dependencies. No model downloads, no livestream, no data collection, no tool permission change, no observed game action, no hardware speedup assertion.

**Important deployment note:** `Star-AI-Private` was reported as public by GitHub earlier today. Before collecting any voice, chat, game screenshots or keys, verify repo visibility and store all sensitive inputs *outside* source control.
