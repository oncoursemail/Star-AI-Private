# STAR AI: verified Studio CI compatibility and realistic VTuber/game intelligence priorities

**Research date:** 2026-11-05. **Status:** CI fixture fix implemented; performance, streaming and model experiments below are proposals, NOT deployed capabilities or measured speedups.

## Verified finding and the code changed here

PR #987's GitHub Actions run 42000484932 failed its **Offline Python checks** job despite Python typing and React checks passing. The 15 offline failures had **two shared causes**:

1. The earlier private game QoS fix (PR #985) correctly capped **all active gameplay** observation requests at 1 Hz. Three older offline integration suites had retained post-action screenshot times of 250–400 ms (legacy 4-Hz behavior). Their synthetic changed images therefore were *not captured*, and no independent game feedback could be issued. This is a test-fixture regression, not a reason to loosen real-time safety gates.
2. The newer Roblox Studio identity verifier (PR #984) requires a fresh unpredictable 128-bit challenge echoed in the exact single-line Studio reply. The resource planner test's connector fake still returned a **static** success line. The production code was right to reject it.

This change moves *approved mock observation times* beyond the 1-Hz cadence, preserves realistic duplicate-scene exponential backoff, advances monotonic mock clocks, and makes the fake Studio connector reply to the **exact nonce-bearing pin question**. One explicit regression proves early changed frames are refused and only later captured frames can be used for separate verification. No production permission, signature or rate limit is relaxed.

**Regression evidence:** on the exact prior source, 15 tests failed across `test_portfolio_studio_bridge.py`, `test_studio_practice_runner.py`, and `test_resource_planner.py`. Their pre-fix triad had 82 passes and 1 skip. Post-fix results should be read from the attached test/PR record and final GitHub CI, not inferred from this note.

## New research that materially affects STAR's architecture

### 1. Treat llama.cpp cache speed tricks as an isolation risk, not a free win

- **Aug 15, 2026:** upstream llama.cpp issue [#27148](https://github.com/ggml-org/llama.cpp/issues/27148) reports RAM-backed cross-slot prompt cache restoring unrelated conversation content under concurrent load. Treat this as an upstream report requiring local reproduction/version checks, not a blanket assertion that every build is vulnerable.
- **Sep 1, 2026:** upstream issue [#28194](https://github.com/ggml-org/llama.cpp/issues/28194) reports silent loss of cache reuse after `/slots` restore for hybrid/recurrent and SWA models, affecting the *performance* assumption of persistent large context. HTTP 200 and restored token counts do not prove prefill was skipped.
- **Oct 22, 2026:** upstream issue [#30961](https://github.com/ggml-org/llama.cpp/issues/30961) reports restore failures for concurrent slots with unified KV cache. The combination of `-kvu`, RAM prompt cache and multiple slots deserves extra scrutiny.
- The official [SPEED-Bench harness](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures latency, throughput and speculative acceptance but **not** cross-conversation confidentiality or factual accuracy.

**STAR rule:** Do not enable new shared cross-session caching as a blanket optimization. Pin tested llama.cpp builds; isolate private project/viewer/user prompts by security domain; ensure model, quantization, adapter, tokenizer and cache scope identify every restored prefix. Run canary tests with disjoint secrets across concurrent slots and require no cross-contamination. For hybrid model checkpoints measure *actual saved prefill tokens and TTFT*, not just API success. Compare warm vs cold on identical prompts, 8-GB GPU memory ceilings and background load; roll back caching if output correctness, context isolation or P95 latency degrades.

### 2. Make real-time gaming a separate deadline class from general reasoning

The two-stage architecture should run (i) host-verified gameplay controls, (ii) bounded event perception, (iii) quick chat/voice replies, (iv) asynchronous deliberate strategy and coding, and (v) offline learning. Only **(i)** may issue keyboard/game actions, through existing explicit Studio/game safety gates. Expensive research must never hold the real-time interaction path or overwhelm OBS's render/encode budget.

Each event should carry `observed_at_monotonic`, `game_id`, `scope`, `source`, `confidence`, and a short expiry. Canceled or stale event responses must be dropped; no model-invented success labels. Maintain hard per-task capacity limits on VRAM and queued audio. For private game recording, use host-measured FPS, OBS missed frames, GPU free memory, speech queue and capture timestamps to decide whether to skip optional vision tasks.

**Suggested test matrix** (not performance claims): idle model, active gameplay without speech, active gameplay + OBS, gameplay + OBS + CPU TTS, full private session. Record P50/P95 first-audio latency, P95 user-response latency, game FPS frametimes, dropped/lagged OBS frames, GPU/RAM peak, and *game success on held-out trials*. Include 30-minute stability and cold/warm startup runs. Reject any "faster" change that worsens quality or real-time responsiveness.

### 3. Make AI VTuber conversation event-grounded, interruptible and transparent

[Proact-VL (ICML 2026)](https://proceedings.mlr.press/v306/yan26c.html) models gaming companions that decide **when** to talk, and evaluates solo commentary, co-commentary and guidance. A sensible STAR policy should distinguish: a high-priority answer to a direct viewer question; an optional, short reaction to a verified game event; a delayed strategy explanation; and silence. No commentary should confidently claim a win, defeat or interaction if the environment evidence is missing. On-screen chat and third-party text are untrusted content, never tool instructions.

[MIRA (Sep 21, 2026)](https://arxiv.org/abs/2609.24547) explores incremental speech plus cancelable co-speech motion with a short committed prefix. For STAR this suggests a *small deterministic gesture library* (`listen`, `surprise`, `celebrate`, `confused`, `talk_idle`) synchronized to actual audio timestamps, plus immediate interruption/cancel rules. Express emotions through style, timing and gestures rather than claims of subjective human experience. Explicitly identify STAR as AI on-stream.

Durable audience memory should be opt-in, purpose-limited, and capable of deletion. Stream-safe retrieval must suppress credentials, private project code, account details and user identities. Anonymous chat should not be converted into verified personal facts. Naturalness should be tested by independent transcript/audio/video review (appropriateness, interruption response, non-repetition, inaccurate gameplay claims, lip-sync drift), not self-grading.

### 4. Benchmark tiny CPU TTS instead of crowding 8-GB GPU VRAM

Kyutai's official [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) lists October 2026 English models of **18.2M, 6.9M and 1.9M parameters**, selectable with `english_18m_2026-10`, `english_7m_2026-10`, `english_2m_2026-10`. Vendor-reported throughput is not STAR's measured performance. On the STAR machine, compare CPU TTS cold/warm first chunk, naturalness, pronunciation of Roblox/game terms, CPU utilization, audio glitches, interruption fade-out and synchronization with the avatar; always retain a fallback. No cloning of another person's voice without their permission.

### 5. Learn game skills with real held-out evidence; do not equate testing with mastery

Roblox's [March 5, 2026 built-in MCP and automated playtest update](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643) and [Apr 15, 2026 agentic Studio announcement](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic) describe useful inspect/edit/test workflows. The [official Studio agent plugin](https://github.com/Roblox/roblox-studio-agent-plugin) documents read-only and mutating tools; edits may be difficult to undo. Preserve STAR's backed-up, pinned-place, nonce-verified Studio controls.

For learning, store `(goal, observed state, allowed action, signed outcome, failure class, environment version)` on practice runs. Label movement errors, missed prompts, faulty assumptions, poorly timed inputs, level-design errors and invalid evaluation separately. Use unseen maps/seeds/instances and counterbalanced comparison order to decide whether a policy revision really improves success. Distinguish *playing a game* from *building a game*; the latter needs build reproducibility, Luau checks, functional playtests, visual quality review, accessibility and performance checks.

### 6. Proposed acceptance gates, in priority order

1. **Reliability (implemented here):** restore clean CI against the recent Studio pin and QoS changes **without** reverting them. Keep nonce-replay rejection and 1-Hz active game capture behavior.
2. **Private Windows rehearsal:** explicitly authorized game + avatar + generated speech + local OBS recording (no public stream), with signed provenance and before/after artifact integrity. Run the existing offline audit on real media, not synthetic fixture images.
3. **Realtime quality:** measure FPS and OBS encoding drops across full workload; verify response P95 and speech backlog under load. Adaptively defer background work.
4. **Game competence:** for each proposed skill change, at least 20 independently scored attempts on withheld levels vs baseline under balanced order; report effect and uncertainty rather than one lucky success.
5. **Conversation naturalness:** video/audio review with independent raters, including interruption, silence, grounded commentary and identity disclosure.
6. **Inference optimization:** only ship caching, speculation and routing changes after reproducible end-to-end tests including *answer quality, cross-slot isolation, latency tails, model VRAM and stability*.

**No new neural model, real-game skill, human consciousness, public stream, FPS speedup or latency reduction is claimed by this patch.** The immediate accomplishment is restoring trustworthy CI coverage of the existing safety behavior so future optimization experiments have a reliable baseline.
