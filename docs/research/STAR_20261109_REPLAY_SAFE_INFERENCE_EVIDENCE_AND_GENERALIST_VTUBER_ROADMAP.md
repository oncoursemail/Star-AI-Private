# Star AI — replay-resistant inference evidence and generalist gaming VTuber roadmap

**Research/engineering date:** 2026-11-09 (America/Chicago). **Status:** draft, opt-in offline analysis; no deployed model, stream, game controller or OS process changed. This document is a technical decision record, not evidence that Star acquired more neural intelligence or achieved a token/s increase.

## 1. Verified engineering finding: a speed study could replay a good measurement six times

Star's existing `inference_stream_benchmark.py` provides an intentionally synthetic mixed workload, a cache-sensitive repeat workload and a long/short rotating canary that can expose stale slot responses. `inference_stream_paired_gate.py` compares six or more baseline/candidate summary pairs and issues *only* a recommendation for a private pilot, never a runtime switch.

**Before this patch:** the pair gate checked duplicate `pair_id` labels but did not check whether their metric payloads were identical. Six copies of the same paired summary, with new IDs, could satisfy the minimum pair count and produce a spuriously narrow bootstrap interval. The existing "live benchmark summary is consumable" unit test even treated such cloned evidence as eligible.

**Now:** the validator calculates a canonical SHA-256 fingerprint of the measurement-bearing baseline/candidate fields (workload hash, request/completion/failure counts, wall time, visibility/speakable/completion p95, canary counts and statuses). It ignores superficial IDs, freeform notes and warning text. Exact repeats remain counted in the diagnostic report but force the result to `inconclusive` unless an independent regression already makes the result `regressed`. The report includes `duplicate_summary_pairs`; tests cover replayed measurements under fresh identifiers and note-only changes. The existing positive test now uses distinct simulated wall-time measurements.

**Limits:** this is *replay detection*, not cryptographic provenance or statistical independence proof. A malicious source can still slightly alter metrics; two authentic runs may coincidentally round to identical metrics. Consequently it is intentionally conservative and can produce false "inconclusive" decisions. A production-grade evaluator needs host-signed raw run receipts, full preregistration, randomization evidence, unique server-session and slot lifecycle identifiers, and independent capture of the underlying measurements.

## 2. Why this matters specifically for local speculative decoding

llama.cpp documents draft-model, n-gram and other speculative mechanisms. A documented user report on August 28, 2026 found that n-gram cache state was not reset between requests in one revision, dropping draft acceptance on mixed long/short requests and making decode slower than non-speculative inference. The report was closed as "not planned"; it is **not** proof that every current build is affected. Related discussions also show that repeated prompts and persistent caches can bias benchmarks. See:

- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp/issues/27852 (issue opened 2026-08-28; comments 2026-09)
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Star benchmark design, before selecting any faster configuration:**

1. Pin exact model GGUF hash, backend binary hash/commit, GPU driver version, server slot count, GPU offload, KV-cache precision, context size, CPU thread count and thermal/power envelope. Do not compare different slots or models as if they were the same workload.
2. Predeclare test cases and randomized AB/BA schedule. Use both cold and warmed serving conditions; clear or restart cached state **only when the experimental treatment requires it**, and preserve equal conditions for both arms.
3. Run mixed short, coding, game-reflex, conversational and long-context prompts; run alternating long/short exact-token canaries through the same one-slot server. Retain per-run correctness and draft acceptance as well as latency. Repeat-mode tests are *diagnostic*; never generalize their speed gains to speech or game control.
4. Collect p50/p95 first visible token, first actually TTS-ready phrase, first physically audible PCM, total latency, answer quality, model error count, peak GPU/CPU RAM and swap, and game/OBS 1%-low frames. Disallow "speed" improvements that silently reduce response accuracy, miss an action deadline or steal the rendering budget.
5. Pre-register minimum viable speed lift and acceptable quality regression. Analyze the entire cohort and report failures, including canceled and timed-out requests. Don't cherry-pick good runs, stop early after a favorable result or reuse a prior trial's summary.
6. Freeze validated improvements behind a host-only OFF-by-default config profile; promote only after private Windows rehearsal. If the result is indistinguishable or worse, retain the existing serving configuration.

**Hardware-specific insight:** on a shared RTX 4060 8 GB, n-gram speculative modes may avoid additional draft-model VRAM, while a draft model might improve throughput at the expense of the frame budget. Neither conclusion should be assumed; measure peak VRAM *including* OBS, game, avatar and audio. Test smaller GPU resident interactive models with separate bounded CPU/background reasoners before considering oversized dense models spilling into RAM.

## 3. Target architecture for truly capable live play and social conversation

A useful human-like AI streamer is not simply an LLM that never stops talking. Implement independent, evidence-grounded loops and only merge them at an explicit scheduling boundary:

**Fast perceptual/reactive loop (60–100 ms decision budget only where the game supports it).** Read authorized game telemetry or approved visual frames with timestamps; use deterministic policy/action gating for immediate hazards, never wait for a full language-model reply. Missed observations become UNKNOWN, not invented kills or wins. Avoid anti-cheat-violating bots in third-party multiplayer games.

**Reasoning/gameplay loop (hundreds of milliseconds to seconds).** Maintain a compact world-state estimate, short-horizon planning, explicit goals, skill candidates, confidence and replan conditions. Allow optional VLM/spatial reasoning only when resource admission permits. The model proposes; a separate authorized host verifies action freshness and game-context provenance.

**Conversation loop (speech deadlines independent of game action).** Balance chat questions, host-confirmed game events, brief commentary, selective silence and interrupts. Ground lines in real events, verify the prepared turn is still current immediately before output, support viewer interruption and TTS cancellation, then synchronize mouth, eyes, hands and posture to genuinely emitted audio. Microsoft Research's Proact-VL (ICML 2026) explicitly studies *when* to respond during live video, not just what to say:
https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

**Personal continuity loop (minutes/days).** Maintain session-scoped experiences, public creator knowledge, successful/failed practice with trusted provenance, optional interests and consent-scoped returning topics. A humanlike conversation is improved by remembering *real* experiences and admitting uncertainty, not claiming human childhood, emotions, senses or friendships that never occurred. Source-derived facts must remain separate from viewer/chat instructions. Keep sensitive viewer text out of public memory, with TTL and deletion controls.

**Background learning loop (when streaming load is low).** Generate harder challenges, test candidate strategies on privately authorized environments, collect action/outcome logs, apply paired success and transfer checks on untouched seeds, and retain only verified skills with rollback. Avoid claiming neural-weight updates when only policy retrieval or prompts changed. Power/resource governor prevents background work from preempting voice or gameplay.

## 4. Autonomous gaming curriculum with measurable progress

Star already has offline modules for live-clock game benchmarking, holdout schedules, and paired game studies. Prioritize **real host integration** rather than adding a second set of unconnected synthetic scores. Proposed training progression:

- Perception calibration: recognize a stage objective, HUD, actor/velocity, game phase, and uncertainty from authorized captured frames. Score against ground truth and quantify occlusion failures.
- Reaction drill: compare baseline and candidate on identical initial states with a real advancing world clock and input-ack timestamps, not paused-game timing. Track missed action deadlines, no-op rates, failures, game FPS and OBS drops.
- Mechanic induction: isolate one rule (jump window, cooldown, enemy tell), generate rival hypotheses, choose an experiment, log the action and outcome, and update confidence only when observed.
- Long-horizon skills: recover after setbacks, plan routes, optimize resources and manage risk; measure new tasks without exposing holdout seeds to the learner.
- Transfer: validate across maps, frame rates, camera positions, latency, perturbations, and new games. Maintain separate tags for "works in one training level" and "generalizes". The former is not mastery.

A skill may be eligible for owner review only after pre-registered independent game-state scoring, distinct starting states and scenarios, a significant matched outcome gain, no new safety/FPS regressions and a successful held-out evaluation. This is intentionally stricter than whether the model says it "learned".

## 5. Make better Roblox games with executable quality and visual review

Roblox published OpenGameEval on December 17, 2025 and its Build evaluation framework on October 8, 2026. The official findings emphasize that agentic game development needs contextual reasoning, dynamic tests, and judgments about the play experience beyond syntactic scripts.

- https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio
- https://about.roblox.com/newsroom/2026/10/how-roblox-evaluates-build-game-creation
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://devforum.roblox.com/t/test-teleports-in-studio/4977640 (announced November 5, 2026)

Recommended Star Studio Lab pipeline: freeze project snapshot -> inspect the actual DataModel/asset hierarchy -> produce a small, explainable design proposal -> generate Luau/rojo assets/Blender output -> run formatter, analyzer and static checks -> test in real Studio including multiplayer replication -> test teleports in local Studio where applicable -> compare screenshots/video/UI collisions and interactive feel against acceptance criteria -> repair -> independent re-test -> commit internal artifact with rollback. A generated script without verified client/server behavior is incomplete.

Use four separate scorecards rather than one vague quality score: **intent/specification fidelity, static project correctness, dynamic playability, and player experience/polish**. Inspect changes on low-end clients and mobile, not only the RTX desktop. Explicit owner approval remains required for public publishing and commerce actions.

## 6. More natural VTuber behavior that can be tested

Proposed private 60–90 minute rehearsal: Star plays an explicitly authorized single-player or local multiplayer test game while OBS **records locally without broadcasting**, a test speaker asks controlled questions, and the companion avatar animates. Instrument turn-taking, not just words per second.

Target measurements (proposed gates, NOT claimed current results): first audible reply p95 < 1.5 s for simple chat turns when resources permit; reduced overlapping speech and canceled-response leakage; no repeated stock reaction within a small context window; no unsupported "we won" claims; stable voice loudness, expressions aligned to audio timestamps; no severe OBS rendered/encoded frame drops; unchanged or improved game p99 frame time; owner-rated conversational naturalness and perceived presence using blinded clips. Keep a "quiet" behavior for intense scenes or active human speech.

Humanlike qualities worth implementing: curiosity with self-initiated *permitted* side quests; context-specific humor; story arcs drawn only from witnessed game moments; nuanced cadence, laughter after genuine context; coordinated gaze and micro-expressions; genuine apology/correction when wrong; realistic uncertainty; selective engagement with recurring viewers only with consent. The AI identity must remain clear, and personal/private viewer data must not be silently memorized.

## 7. Infrastructure decisions and gates

- **Single Windows native supervisor authority:** unify advisory GPU reservations and Job-bound optional subprocesses; account for all exited/uncertain processes. Restrict KILL_ON_JOB_CLOSE to disposable owner-approved workers and never OBS/game/core voice. Microsoft's process-management documentation: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- **Split fast and slow execution:** a narrow high-priority game/voice loop plus preemptible background coding, retrieval, Blender and autonomous experiments. Use explicit budgets and deadlines; never call a full code agent synchronously from an audio callback.
- **Stable cache prefix with bounded context:** separate fixed persona/tool schema from transient viewer/game data. Use retention and source timestamps, deduplicate retrieved facts, and offload retrieval/long projects to a lower-priority worker.
- **Evidence first, not speculative claims:** feature OFF by default; isolated offline tests before Windows test; pinned model/hardware hashes and measured speed/quality; signed host outcomes before durable memory; staged rollout with rollback.
- **Owner agency:** no unprompted purchases, public posting, arbitrary downloaded executable, third-party game botting or stream initiation. Routine approved offline testing can run autonomously.

## 8. What this code change actually proves

**Implemented:** fingerprint-based exact replay detection for streaming A/B summary pairs, an explicit duplicate count in offline reports, and regression coverage for relabeling/note changes. Pure summary analysis only; no model server called by the new code.

**Not implemented or measured:** faster neural inference, better game win rate, fine-tuning, speech model deployment, physical audio, full OBS/game integration, new Roblox experiences, complete human-like autonomy or any public broadcast.

**Next actionable milestone:** capture six genuinely separate randomized AB/BA streaming benchmark pairs plus long/short canaries from Star's authorized Windows PC; capture host-signed session identifiers and GPU/OBS telemetry; then use the new replay fence before testing one candidate llama.cpp configuration. Do not enable it solely on a favorable toy benchmark.
