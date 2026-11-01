# Star AI — Retention-aware gaming intelligence, faster execution and natural VTuber systems

**Research/implementation:** November 1, 2026. **Status:** owner-opt-in, offline Python advisory; no Windows gameplay, livestream, trained model, measured inference acceleration or production deployment is claimed.

## The actual gap: passing practice is not retained ability

The current repository already includes a signed `GameplaySkillBank`, a Wilson-lower-bound practice curriculum, separate held-out evaluation, a deadline-aware gaming router, a stream-load governor, speech quality gates, and an action-freshness/input gate. Those are important foundations, but the curriculum had no scheduled retrieval of a *verified mastered* skill until its evidence aged completely out of the lookback. A high aggregate of old wins could also obscure a very recent genuine failure. This is consequential for an autonomous game-playing Star: rapid skill acquisition and stable ability are different goals. A single convincing success cannot certify generalization.

**Implemented:** `recommend_practice` now accepts optional `spaced_review_after_s` (default `None`, behavior unchanged). The interval must be a bounded integer >=60 seconds and <= the signed evidence lookback. A still-mastered lower-tier situation that has passed its review interval receives a `spaced_review` recommendation before advancing to a harder level. The oldest eligible verified experience is reviewed first. Unmastered current-tier situations take precedence over repetition at that tier. Stale evidence still demands a `review_required` assessment, and inadequate lower-tier results still block escalation. All suggestions are just symbols, not permissions to play or train.

**Implemented:** `GameplaySkillBank.practice_evidence` now reports an optional `most_recent_success` PRACTICE-only bit, computed after verifying every signed ledger row. Equal latest one-second timestamps with conflicting outcomes are resolved pessimistically: any failure is the latest effective outcome. The curriculum prevents a skill from being considered mastered immediately after its most recent signed failure even if aggregate lower confidence bound remains high. Older four-field `PracticeEvidence` adapters continue to work with the optional field absent; malformed optional flags are rejected. Validation/holdout results do not affect this practice field.

Host-only example:

```python
advice = recommend_practice(
    bank,
    targets=trusted_host_allowlisted_targets,
    now_unix_s=trusted_host_unix_seconds,
    owner_approved=True,
    min_trials=8,
    max_evidence_age_s=7 * 86400,
    spaced_review_after_s=24 * 3600,
)
# advice.status == "spaced_review" is NOT game-input authorization.
```

The parameter is an adjustable experiment, **not** a known optimal training interval. Star Core Forge should benchmark whether it improves actual retained gameplay ability versus a fixed-practice baseline before enabling the feature for any real game.

## Dated research: how to learn and verify real game ability

Czyż et al., *Scientific Reports* (2024), meta-analysis on contextual interference in motor learning (54 studies), reports positive overall laboratory retention effects, but an almost negligible benefit in applied settings. This supports studying varied/delayed practice but **not** claiming that spacing is a universal gaming breakthrough. DOI: https://doi.org/10.1038/s41598-024-65753-3

Roblox **OpenGameEval** (published October 1, 2026) evaluates agents in 84 real stateful Studio tasks, including executing checks on edited scenes and simulated play. It finds that inspecting objects before editing correlates with better outcomes even after accounting for task and model; correlation is not a causal proof. The test assets are open: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

Roblox's official **StudioTestService** can run plugin-driven multiplayer tests using `ExecuteMultiplayerTestAsync`, up to 8 simulated clients. Apply it to lobby replication, joining/leaving, interactions and adversarial network conditions rather than just checking that Luau compiles: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

### Bounded learning experiment for Star

Pre-register a private allowed game, frozen versions, at least two unseen maps/scenarios and enough independent trials. Split practice, retention probes and held-out validation by map/seed and signer, with an honest audit. Compare the current curriculum against the new interval using matched resources, equal practice time and identical scripted controls. Evaluate success rate, normalized objective progress, action timing, peak memory, failure recovery, and a delayed no-hints retention check. Reject any promotion when previously solved scenarios fail, trusted host evidence is absent, held-out seeds leak to learning, or runtime conditions differ. The stream teacher should never run during broadcast, even if the game is paused. Star may generate hypotheses and harder exercises but independent host/evaluator must certify them.

## Intelligence and inference speed on an 8 GB GPU

Existing repo components already measure deadline routing, first visible/speakable text, real audible speech and frame timings. The missing step is **a full Windows workload acceptance test**. Do not rewrite the entire Python application in Rust or launch additional GPU jobs merely to increase benchmark throughput.

1. Benchmark llama.cpp baseline against its documented n-gram or draft-model speculative decoding using fixed model and prompt hashes, context length, cache state, slot count and CPU/GPU allocation. Use SPEED-Bench for draft acceptance, per-category latency and throughput; then compare end-to-end spoken responses, game frame p95/p99 and OBS render/encode/network drops. Official sources: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md and https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
2. Keep low-latency reactive decisions on a proven small route, deterministic fallback for urgent reflexes, and larger teacher reasoning *offline only*. An inferred action after the frame deadline is worse than a safe skip. Match all timing to one trusted host monotonic clock and independently check action freshness immediately before dispatch.
3. Preserve GPU VRAM for the live game, OBS and avatar, with background research, rendering and model learning suspended under pressure. Do not treat tokens per second as intelligence. Require independent gains on held-out gaming, general knowledge, coding and Roblox creation while monitoring first audible p95, actual speaker stop, frame-time tails and GPU memory.
4. Only consider Rust for profiled hot paths (audio PCM conversion, frame transforms, spatial geometry, retrieval indexes, scheduler bookkeeping); compare speed/heap use with boundary overhead, errors and cancellation semantics. Retain maintainable Python orchestration where measured Rust benefit is absent.
5. Treat prompt-cache KV reuse as a security and correctness boundary: isolate user/session histories and rerun canary conversations to detect cross-session leaks. Store no secrets or private recording in the public repository.

## Humanlike VTuber behavior without false human identity

Natural streaming requires coordinated *behavior*, not a larger personality prompt. Star's stable AI streamer brief should be warm and expressive while clear about being AI and truthful about what she observes and remembers. Speech should be short during difficult game moments, interruptions must physically stop outgoing audio and immediately invalidate old avatar motion epochs, and lip motion should follow real audible PCM rather than queued TTS text. Eye focus, subdued breathing/head movement, laughter after actual unexpected events, blinking, and hair/ear/tail physics can turn silence into attentive presence without fake stories.

LiveKit documents a locally runnable CPU **v1-mini** turn detector for self-hosted agents; their adaptive interruption handling is **cloud-only**, not something Star should assume comes with offline deployment. Test local VAD and interruption handling with actual viewer pauses, background noise and gameplay sounds. Official docs: https://docs.livekit.io/agents/logic/turns/turn-detector/ and https://livekit.com/blog/turn-detection-and-interruption-handling

Use the existing `stream_social_turn_benchmark` to compare matched real moments: first audible latency for viewer questions; overlap; incidental-noise false interruption; authenticated owner barge-in to actual speaker stop; unwanted dialogue during critical gameplay; and groundedness of claimed wins. Candidate improvements must pass both aggregate and individual-case regressions. Do not infer human feelings/consciousness from animation scores or invent biographical events. Recollections should come from actual signed gameplay episodes and separately approved public notes.

## Roadmap and acceptance conditions

**Next integration:** expose anonymous counters for due-review recommendations and latest-failure mastery vetoes, and wire the advisory into owner-approved local game-lab practice only. After each independently witnessed game result, train only from practice split and allow a separate held-out benchmark to decide promotion. Every new change should be versioned and reversible within Star Core Forge; GitHub is an optional external publishing destination, not a dependency of Star's self-improvement system.

**After that:** combine verified screen/game-state observations, quick action policy, a deadline router, input watchdog, audio turn detector, VTube Studio/Live2D rig playback, signed episodes, Roblox Studio automation, and host OBS telemetry. Evaluate synthetic/multiplayer Roblox tests plus visual geometry/texture placement using fresh screenshot inspection, not generated acceptance prose.

**Rehearsal requirements:** operator-approved Windows streaming workstation, actual OBS recording and game, end-to-end time stamps, fixed baseline/candidate versions, an independent quality reviewer and credible held-out scenarios. Reject scene defects, missed physical audio stops, stale observations or non-consensual automation. Do not promote merely because isolated Python tests pass.

## Verification and limitations

The changes add bounded synthetic regression cases for opt-in defaults, exact review time, oldest verified retention candidate, low-tier prerequisite ordering, signed recent failures after many victories, same-second opposing results, excluded validation failures, invalid configuration and corrupted flags. **No gameplay or speech systems were operated, and no intelligence/speed benefit has been measured.** Dedicated unit tests, repository CI, and the Windows rehearsal are separate verification stages. No credentials, player names, raw chat, audio or screenshots were added.

This GitHub repository is **public**, so do not commit sensitive local files or video. The existing PR remains draft and unmerged pending complete review and hardware evidence.
