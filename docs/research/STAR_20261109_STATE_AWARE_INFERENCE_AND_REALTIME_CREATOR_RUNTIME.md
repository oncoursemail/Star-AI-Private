# STAR — state-aware inference benchmarking and real-time creator runtime

**Research date:** 2026-11-09  
**Implementation:** `star/inference_benchmark.py`, `star/inference_stream_paired_gate.py`, and their regression tests.  
**Scope:** private synthetic inference diagnostics, real-time streaming performance, game-learning evidence, and the Windows VTuber integration boundary.

## Executive summary

This change adds an order-sensitive canary audit for local inference servers. It runs the same synthetic canary set in two sequential orders—long prompts first, then short prompts; and short prompts first, then long prompts—through the same client and configured endpoint. It records exact-token mismatches by synthetic case ID and p50/p95 latency by canary category.

The purpose is to catch a class of stateful benchmark failures that a single mixed workload can miss. In particular, a reported llama.cpp issue described stale per-slot n-gram cache context after a longer request was followed by a shorter request. The audit is a diagnostic, not a claim that every llama.cpp build is affected. Because it does not restart the server, the second pass inherits state warmed by the first; this is a deliberate carry-over stress test, not an independent randomized A/B. A causal order comparison needs separate fresh server process epochs for each order.

The new code does **not** speed up inference, inspect llama.cpp's private cache, restart a model server, verify its process ID or slot count, or authorize a model change. A clean canary run only means that no wrong exact-token response was observed in those synthetic trials.

## 1. New primary-source finding: benchmark order can matter

### llama.cpp issue #27852 (reported 2026-08-28)

The issue reporter described a version-specific `ngram-cache` problem in which a server slot's cached n-gram context and prompt-ingestion watermark could survive between requests. After a longer request, a shorter request on the same slot could skip ingestion of its new prompt and draft from stale context. The report described acceptance falling from 86% to 11% in that setup and noted that repeated-prompt benchmark harnesses could make results order-dependent.

This is a **reported issue and reproduction**, not proof that every current llama.cpp release or every speculative mode is affected. The issue itself was later closed as stale/not planned, but upstream PR #27866 (opened 2026-08-28) remains an open proposal for resetting the per-sequence context cache and adds a regression test. A separate October 11 commit referenced by the issue lives in a fork, not the upstream ggml-org repository. Therefore STAR must not assume the reset is present in an installed build: record the exact llama.cpp commit, build flags, model digest, slot count, and benchmark order, and check whether the upstream PR has merged before deciding the audit is redundant.

Source: https://github.com/ggml-org/llama.cpp/issues/27852
Proposed upstream reset and regression test (still open at research time): https://github.com/ggml-org/llama.cpp/pull/27866

### Distinguish the speculative modes

The upstream llama.cpp speculative-decoding guide describes different state models:

- `ngram-cache` maintains n-gram statistics and has its own cache behavior.
- `ngram-simple` / `ngram-map` use matches in the current token history.
- `ngram-mod` uses a hash pool shared across server slots by design.

Do not treat cross-slot sharing in `ngram-mod` as the same thing as stale per-slot prompt-ingestion state in the reported `ngram-cache` issue. Test each mode independently.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

### What STAR now measures

The new `audit_cache_order()` path:

1. Requires a bounded cohort of 2–12 synthetic canary prompts.
2. Requires sequential execution (`parallel=1`) for each pass.
3. Runs long-context cases first, then short-context cases.
4. Runs the same case set in the reverse length order.
5. Reuses one client object and the same configured endpoint across both passes.
6. checks each response against its own unique expected token.
7. Returns exact synthetic mismatch IDs, order-sensitive mismatch IDs, and category-level p50/p95 latency.

Verdicts:

- `passed`: no wrong canary token observed in either order.
- `order_sensitive`: the set of mismatched canary cases differs by order.
- `canary_failed`: one or more canaries fail in both orders.
- `inconclusive`: transport failures prevent interpretation.

The audit intentionally does not infer internal cache state from latency alone. The p95 deltas are descriptive diagnostics, not statistical proof.

**Operator requirement:** run this against a private, single-slot server (normally `--np 1`) and keep the same server process alive across both passes. The function cannot attest that configuration. Record the server's process/epoch and exact build commit externally; a future trusted host receipt should bind those facts to the result. For an unbiased comparison, run each order in a separately restarted server process and retain both epoch receipts; do not treat this same-process stress sequence as a randomized speed trial.

## 2. SPEED-Bench and the correct definition of “faster”

The upstream llama.cpp SPEED-Bench client evaluates an already-running server and reports per-category throughput, latency, and speculative draft acceptance. It is a useful model for separating workload categories rather than collapsing all requests into one tokens-per-second number.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

For STAR, benchmark these separately:

- time to first visible text;
- time to first speakable chunk;
- time to first audible PCM;
- inter-token latency / decode throughput;
- complete response latency;
- speech real-time factor and interruption latency;
- game frame-time p50/p95/p99;
- OBS dropped frames and render lag;
- CPU/GPU utilization, VRAM headroom, memory pressure, and audio underruns.

A configuration is not a streaming speedup if it improves token throughput but delays first speech, stutters the game, starves OBS, or causes audio glitches.

### Speculative decoding

Speculative decoding can improve token generation when draft acceptance is high enough to offset draft and verification overhead. It can also be slower when acceptance is poor, the draft model consumes scarce VRAM, or cache state is contaminated. On an 8 GB GPU, compare n-gram modes before adding a second GPU-resident draft model, and include a no-speculation baseline.

### Prefix caching

vLLM's Automatic Prefix Caching reuses KV cache for shared prompt prefixes. Its documentation is explicit that this reduces prefill work, not decode time. It helps repeated long context or multi-turn conversations with stable prefixes; it does not fix a slow token-generation phase.

Source: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/

For STAR, keep stable persona/system instructions and fixed tool schemas in a stable prefix. Put changing game state, current viewer messages, and timestamps after that prefix. Measure prefill and decode separately.

### CPU speech as GPU relief

Kyutai's Pocket TTS repository describes streaming CPU speech generation and small English models announced in October 2026 (18.2M, 6.9M, and 1.9M parameters), with upstream-reported real-time factors on its own test hardware. These are promising candidates, not STAR benchmark results. CPU speech can still compete with Roblox, OBS, audio mixing, and vision for CPU time and memory bandwidth.

Source: https://github.com/kyutai-labs/pocket-tts

Benchmark CPU and GPU speech on the actual Windows host with the game, OBS, avatar, and local model running together. Keep the model choice reversible and disabled by default until voice quality and p95 frame-time acceptance pass.

## 3. General intelligence: improve evidence-to-action, not transcript size

STAR already has memory, knowledge, game-practice, and skill-evaluation components. The next improvement should connect them with a common evidence contract rather than adding another untyped conversation store.

Recommended memory classes:

- **World fact:** sourced claim about an API, game mechanic, model version, or external system.
- **Observation:** timestamped host/tool output with freshness, scope, and uncertainty.
- **Experience:** an action STAR actually attempted, with environment, tool, result, and independent completion evidence.
- **Skill/procedure:** reusable behavior that has passed repeatable and held-out tests.
- **Preference/opinion:** subjective and explicitly scoped; never silently promoted to fact.
- **Hypothesis:** unverified explanation that must remain distinct from confirmed knowledge.

Every promoted skill should carry the test environment, software/game version, evidence IDs, known failure conditions, and last validation time. A strategy that works on one map or one FPS setting should not become a universal rule.

Do not fine-tune on every stream transcript. First show that a memory or skill improves held-out actions, avoids cross-project leakage, and remains correct after the source version changes.

## 4. Real-time gaming and game creation

### Two-loop gameplay

Use a small, deadline-aware reflex loop for immediate actions and a slower tactical loop for planning and learning.

**Reflex loop**
- consume fresh, timestamped visual/game telemetry;
- use a small allowlisted action vocabulary;
- reject stale observations and expired action plans;
- acknowledge the input result;
- stop on game/window/scene identity changes.

**Tactical loop**
- infer mechanics and map structure;
- analyze successful and failed episodes;
- design controlled practice tasks;
- adjust difficulty and strategy;
- evaluate on unseen maps and variants;
- promote a reusable skill only after repeatable evidence.

Measure observation age at action time, action acknowledgement p50/p95, missed deadlines, recovery rate, held-out task success, and transfer to new game variants. Do not equate a single lucky win with learned mastery.

### Roblox game creation

Roblox's Studio MCP can call Open Cloud APIs on the owner's behalf. Permissions are saved per game and enforced by Studio. This is powerful, but the correct design is least privilege: inspect/read first, request only the specific write scope needed, and keep publishing, monetization, moderation, secrets, and live player-data actions behind explicit owner approval.

Source: https://create.roblox.com/docs/studio/mcp-open-cloud

The acceptance loop should be:

**Inspect → Plan → Edit → Static checks → Run → Playtest → Visual review → Repair → Held-out regression → Owner-reviewed release**

A successful Luau compile is necessary but not sufficient. Check client/server authority, replication, UI legibility, physics, animation, audio, pathfinding, performance, exploit resistance, and actual playability.

## 5. VTuber streaming: the Windows boundary matters

### WASAPI loopback is not automatically STAR-only audio

Microsoft documents WASAPI loopback as capture of the audio stream being played by a rendering endpoint. That may contain the system mix, including game sound and other applications—not just STAR's voice.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi

For speech pacing and lip-sync evidence, bind the exact STAR PCM stream/epoch to the audio route. Use a process/session-specific signal where available, or a host-owned PCM receipt before mixing. Do not attribute all endpoint loopback audio to STAR. On endpoint invalidation or route change, discard old calibration and require a fresh route-bound session.

### VTube Studio

VTube Studio's API supports plugin authentication and parameter/hotkey control. The first plugin authorization produces an on-screen permission request; users can revoke access later. STAR should request only the permissions required for the current feature and must never attempt to grant its own VTube Studio access.

Source: https://github.com/DenchiSoft/VTubeStudio

The active-listening feature in PR #1096 is only a Python-side, owner-opted cue planner. The native Windows ASR and VTube Studio plugin still need to provide verified, fresh events and render only the approved subtle motion.

### OBS

OBS WebSocket is included with OBS Studio 28+ and its upstream project recommends keeping password authentication enabled. Keep OBS telemetry/read-only observation separate from scene-changing or broadcast-control actions. Do not expose the WebSocket port to the public internet.

Source: https://github.com/obsproject/obs-websocket

### Natural streaming behavior

The response director should be able to choose among:

- a short spoken reaction;
- a full answer after the viewer yields;
- a subtle nonverbal listening cue;
- a delayed response while gameplay is critical;
- silence when commentary would be stale or distracting.

Naturalness comes from timing, context, voice consistency, interruption handling, and grounded continuity—not constant filler or simulated claims of human feelings. STAR should be transparent that she is an AI streamer.

## 6. Prioritized engineering plan

### P0 — inference integrity
- Run the new long-first/short-first canary audit against each pinned llama.cpp build and speculative mode.
- Record server commit, model digest, flags, slot count, hardware profile, and process epoch.
- Compare no speculation, ngram-simple/map, ngram-cache, ngram-mod, and draft-model modes separately.
- Reject any candidate with canary mismatch, order-sensitive correctness, or unacceptable game/OBS regression.

### P0 — Windows streaming witness
- Implement WASAPI route/device notifications and a STAR-owned PCM receipt.
- Bind route ID, stream epoch, first/last audible sample, and monotonic clock.
- Separate STAR output from game/system mix before learning audible speech timing.
- Integrate VTube Studio only after the owner grants the plugin permission.
- Keep OBS authentication enabled and start with read-only telemetry.

### P1 — measured performance and voice quality
- Compare Pocket TTS CPU variants against the current voice path.
- Cap CPU threads and measure frame-time p95/p99, OBS render lag, first-audio latency, RTF, voice quality, and interruption response.
- Test stable-prefix caching only where prompt prefill is a meaningful share of latency.
- Preserve a one-primary-GPU-model default unless a paired private experiment proves a second resident model is better end-to-end.

### P1 — game skill and creator intelligence
- Run practice across multiple held-out maps, difficulty levels, and frame rates.
- Keep per-scenario results and evidence-linked skill cards.
- Add Studio visual/physics/multiplayer checks to the existing inspect-build-playtest-repair workflow.
- Promote skills only after a repeatable success improvement without regressions.

### P2 — long-session VTuber rehearsal
- Run a 30–60 minute private rehearsal with game, OBS, local inference, TTS, and avatar animation together.
- Track first-visible/first-audible latency, interruption-to-silence time, game frame-time p95/p99, dropped frames, audio underruns, CPU/GPU/VRAM, and conversation quality.
- Review the actual recording for awkward timing, repeated gestures, stale commentary, and voice drift.
- Keep public broadcasting, publishing, and irreversible account actions owner-controlled.

## 7. Implementation and verification in this change

### Code added
- Removed stray terminal-diagnostic lines that had been appended to four files in the stacked active-listening change (`stream_listener_backchannel.py`, `stream_stage.py`, its regression test, and its research note). Those lines caused a Python syntax error during broad stream-test collection; the files now end cleanly.
- `Probe.case_category` keeps synthetic workload categories attached to measured requests.
- `summarize_probes()` emits per-category p50/p95 latency and exact synthetic canary mismatch IDs.
- `benchmark_local_model(case_order=...)` supports long-first and short-first canary ordering while retaining the one-slot requirement.
- `audit_cache_order()` runs both orders sequentially through the same client and returns `passed`, `order_sensitive`, `canary_failed`, or `inconclusive`.
- The paired streaming evidence validator accepts and fingerprints the new optional diagnostics so replayed summaries cannot drop them silently.

### Verification
- Focused inference benchmark + paired-gate regression tests: **42 passed**.
- Listener + stage + inference regression tests: **78 passed, 25 subtests passed**.
- Context host + speech pacing + playout clock + fresh barge-in tests: **65 passed, 18 subtests passed**.
- Ruff check: passed for all changed Python files.
- Python compilation and `git diff --check`: passed.
- The broader `tests/test_stream_*.py` collection was started after removing the syntax contamination, but was stopped at 7% because the globbed suite was taking substantially longer than the focused acceptance set. No result is claimed for the full glob.
- Pyright was not run because it is not installed in the connected verification environment.
- Hardware benchmark: **not run** in this change.
- llama.cpp server process/slot identity: **not attested** by the Python audit.
- Windows WASAPI, OBS, VTube Studio, and actual game rehearsal: **not run**.
- No inference speedup, intelligence gain, gameplay win-rate gain, or production readiness is claimed.

## Sources

1. llama.cpp issue #27852, reported 2026-08-28: https://github.com/ggml-org/llama.cpp/issues/27852
2. llama.cpp speculative decoding guide: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
3. llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
4. vLLM Automatic Prefix Caching: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
5. Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts
6. Roblox Studio MCP / Open Cloud: https://create.roblox.com/docs/studio/mcp-open-cloud
7. Microsoft WASAPI loopback: https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
8. Microsoft WASAPI overview: https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi
9. VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
10. OBS WebSocket: https://github.com/obsproject/obs-websocket
