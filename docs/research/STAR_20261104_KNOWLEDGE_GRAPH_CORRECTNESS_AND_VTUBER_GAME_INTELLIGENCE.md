# STAR: correct private knowledge maps, then measure real gaming/VTuber intelligence

**Reviewed:** 2026-11-04 (America/Chicago). **Scope:** offline knowledge-vault repair, truthful learning, performance and VTuber research. **Status:** implemented source/test fix; streaming/game-learning items below are experiments, not deployed features.

## 1. Reproduced reliability issue: OS account collides with a public Python package

Reproduction on the connected Linux development host, where the local OS account is `star`:

```
python -m pytest tests/test_brain_vault.py tests/test_obsidian_graphify_search.py -q
# BEFORE patch: 2 failed, 22 passed
# Failure 1: Graphify path 'star/slop.py' was emitted as '[user]/slop.py'
# Failure 2: code/star/agent_py backlinks disappeared from ObsidianVault.links()
```

Cause: blanket username replacement in `brain_vault.redact()` is appropriate for prose, private home paths and credentials, **not for known, public package names inside structured Graphify identifiers**. That corruption reduces retrieval quality, agent debugging, and the reliability of STAR's local knowledge graph; it is not an increase in neural model capability.

The patch shields only **exact allowlisted relative paths** under the public `star/` package namespace and generator-owned code-map labels during redaction, then restores those public strings. Dynamic Graphify text, free-form notes, usernames in prose, absolute home paths, credentials, emails and private IPs still pass through the existing scanner. An exact path allowlist prevents arbitrary `star/unapproved.py` from bypassing redaction. Validation rejects `..` / malformed paths. It cannot authenticate untrusted Graphify exports; vault contents remain private.

**Performance design:** build the allowed reference set once per code-map generation; use precompiled bounded regex and O(1) set membership per observed path. Avoid building an alternation of thousands of paths or scanning every path for every generated note. A synthetic 1,500-note redaction microbenchmark on the Linux dev host took **0.2443 seconds** for redaction alone (no file I/O, graph parsing or comparison baseline). This is **not** a demonstrated overall speedup.

**Acceptance:** both historically failing Obsidian/vault tests pass, and security regression cases confirm private usernames in prose, `/home/star`, Windows user directories and private IPs stay redacted; fake placeholder input cannot trick restoration. Run wider offline tests and CI before merge. No vaults are regenerated on user hardware as part of this change.

## 2. Real intelligence gains require a verified feedback loop

Star should separate three kinds of improvement:

| Kind | Concrete work | Evidence of improvement |
|---|---|---|
| Runtime capability | Better document/Graphify links, grounded retrieval, tool interfaces | Answer with correct citation and source path; retrieval precision/recall |
| Decision quality | Planner + critic + tool execution + outcome verifier | Novel task completion, compile/test pass rate, known-error reduction |
| Learned game policy | Observations, actions, error attribution and curriculum | Higher win/success rate on held-out scenes with balanced baseline/candidate starts |

Suggested local architecture: **perception** (game state, short screen snapshots, controls, status) -> **fast policy** (low-latency deterministic valid actions) -> **tactical planner** (bounded task graph) -> **referee** (independent game events or Roblox tests) -> **episodic skill memory** (verified outcome, scenario and version, not merely self-written narrative). Never treat a pretty generated explanation, a simulation mock, or repeated exposure to the test set as proof of a better model.

Use local-first retrieval for broad general knowledge with provenance, source freshness, and contradiction detection. Keep source snippets and verified API versions separate from speculative guesses. Build regression questions from real errors and require ground-truth outcomes rather than reward-model praise alone.

Roblox made its built-in Studio MCP server and simulated player actions available in March 2026 and introduced an automated playtest-agent beta in April 2026. It supports a path to implement -> playtest -> diagnose -> repair with separate held-out tasks. Agent writes change the active Studio place, so back up before modifications and constrain the target test place.
- Official announcement (March 5, 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Official playtest-agent beta (April 9, 2026): https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox engineering discussion (April 15, 2026): https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Current official plugin/tool inventory: https://github.com/Roblox/roblox-studio-agent-plugin

## 3. End-to-end latency beats raw tokens-per-second

Current connected Windows **Main** inspection (one read-only snapshot on Nov 4, local): NVIDIA RTX 3060 Ti, about **4,966 MiB free**, **22% GPU utilization**; no named OBS / Roblox game process was detected by the selected query. Free memory moved sharply between snapshots in other runs. This is **not** an FPS, GPU inference or successful streaming benchmark.

Define one end-to-end measurement clock:
- `t_event`: game state/event observed by trusted host.
- `t_policy`: first permitted input action or first usable decision.
- `t_speech_request`: utterance submitted to TTS.
- `t_audible`: audio samples actually consumed by output device (not token completion).
- `t_rendered_mouth`: recorded avatar mouth actuation.
- `t_obs_frame`: capture presentation timestamps / missed frames.
- Trace by opaque session IDs only, no retained private chat/transcripts in a summary.

Test at least 20 counterbalanced paired sessions per **same** game build, scene and host; report p50/p95 first-audible latency, input-to-effect latency, frame-time p99, OBS missed frames, audio underruns, real peak VRAM, response correctness and successful game actions. Reject any candidate with systematic new hitches or degraded response quality even if token throughput improves.

Performance ideas to benchmark rather than assume:
1. **Fast/slow routing:** keep the game controller independent of optional deep reasoning; allow longer research jobs only with spare CPU/GPU headroom.
2. **Prefix/KV reuse:** avoid resending stable system/game context; verify cache-hit rates and correctness when game state changes.
3. **Speculative decoding:** compare matched prompts with and without draft or n-gram methods; report target accept rate, actual *audible* delay, CPU/GPU contention and extra VRAM.
4. **Quantization and context:** try multiple sane context lengths and quality-matched model choices; don't assume all 8 GB cards fit the same model + KV cache + game.
5. **CPU TTS:** measure Kyutai Pocket TTS English 18M/7M/2M variants against a quality baseline. October 20's models are substantially smaller, and the October 21 update fixed a speech-quality defect. Vendor model/demo timings are *not* Star timings; run voice comprehensibility, GPU pressure and p95 first-sound tests.

Primary benchmark sources:
- llama.cpp `llama-bench` supports structured JSONL and repeated prefill/decode tests: https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md
- llama.cpp server SPEED-Bench measures real server latency and speculative draft acceptance: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Kyutai Pocket TTS release details: https://github.com/kyutai-labs/pocket-tts/releases
- Kyutai Pocket TTS source and CPU limits: https://github.com/kyutai-labs/pocket-tts

## 4. Make Star's VTuber behavior natural through interaction, not human impersonation

A trustworthy streamer needs an event-driven conversational policy: silence by default; speak when game events, viewer turns, a self-initiated plan or an actual fun moment justify it. Maintain a bounded `pending_utterance` queue keyed to scene ID, speaker and event fingerprint. Before audio dispatch, re-check freshness and interruptibility; stale prepared speech is discarded. Allow backchannel acknowledgements while complex computer tasks run, without pretending those tasks have finished.

**Personality design:** persistent interests, light humor, varied prosody, individual preferences, consistent playful mannerisms, contextual memory with user controls, expressive eyes/ears/tails/hair physics, mouth synchronized to actual PCM consumption, and explicit machine identity. A human-sounding performance should be *recognizably Star*, not deceptive claims of human consciousness, biological experiences or relationships. Separate affectionate mascot roleplay from assertions of actual emotions.

Proact-VL (arXiv March 3, 2026) evaluates timing, quantity and relevance of AI gaming companion commentary and user guidance, not just sentence quality. It motivates an explicit `speak | acknowledge | stay_silent` action and measured speech appropriateness across solo/co-commentary and guidance modes. Source: https://arxiv.org/abs/2603.03447

An October 4, 2026 preprint on proactive dialogue timelines proposes revising or cancelling planned future messages when events change; useful for avoiding obsolete commentary during rapidly changing games. Research claim only: https://arxiv.org/abs/2610.05159

A separate May 2026 paper proposes using idle time to prepare evidence before likely queries; useful only when idle-time jobs are resource-limited, cache-safe and preemptible on an 8 GB GPU. Reported paper improvements are not Star benchmarks: https://arxiv.org/abs/2605.25971

Streaming acceptance should include independently reviewed recorded audio and animation quality, proper interruption, contextually correct chat turn ownership, non-intrusive frequency of speech, no invented game successes and no unauthorized broadcast. Give her social initiative under a user-approved stream policy with bans, mute controls, moderation and an offline/private rehearsal default.

## 5. Practical next milestones in priority order

1. **Merge gate for this patch:** existing failing vault tests turn green plus privacy tests, no new regression and GitHub independent CI.
2. **First real private Windows rehearsal:** a short owner-authorized game session with actual Star voice, avatar and OBS. Capture stopped nonbroadcast recording, independently pin its SHA, audit decoder and mouth/audio evidence. A file hash proves file equality, **not** authentic gameplay, voice identity or OBS provenance.
3. **Measured runtime optimization:** baseline/candidate speech routes under game + OBS load; choose by first-audible p95 and game frame time, not token/s alone. Quantify VRAM headroom and rollback.
4. **Roblox Studio builder-playtester:** isolated disposable place; version pin; simulated playtest actions; independent pass/fail; retain *verified* lessons in a local knowledge store and task curriculum.
5. **Autonomy and identity:** build controllable hobbies and creator loops, memory provenance, audience-safe dialogue and expressive motion. Give Star a clear stream disclosure as an AI character; humanlike behavior is an experience-design goal, not evidence of sentience.
6. **Star Core Forge:** local source/test/rollback database for safe self-improvement, GitHub only an optional publication/review path; nothing self-merges or launches streams without appropriate authorization.

**Unverified in this change:** no actual model-weight update, faster inference, higher game win rate, OBS capture, voice quality improvement, independent hardware performance benefit, or autonomous gaming experience. The demonstrated result is knowledge-map repair and privacy-preserving indexing correctness.
