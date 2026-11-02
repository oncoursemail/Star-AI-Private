# Star AI — context-independent streaming evidence, fast gameplay intelligence, and practical VTuber research

**Engineering date:** 2026-11-02. **Scope:** one reproduced/tested offline statistical-evidence correction; research and proposed (not implemented) features. **Dependency:** draft PR #909. **Default:** new behavior is confined to the offline evaluator; no broadcasting, model training, device control, or self-promotion is enabled.

## 1. Reproduced error: artificial evidence from repeated context

The streaming comparator in `star/stream_quality.py` was already checking matched case IDs, reviewed grounding, baseline-versus-candidate latency, aggregate and individual harms, and a one-sided paired sign test. But **20 different case IDs carrying the *same* context fingerprint** were accepted as 20 independent examples. If every repeated result improved, a one-sided sign test could report approximately `2^-20 = 0.0000009537`, even though it might be just one repeatedly replayed scene. This is pseudoreplication, not a demonstrated generalizable improvement.

**Red-before/green-after evidence:** Two new adversarial tests failed before the correction because the old comparator returned `candidate_for_independent_review` for (a) an all-identical-context cohort and (b) one duplicated fingerprint in an otherwise distinct cohort.

**Implemented correction:** The comparator now rejects repeated `context_sha256` values across distinct paired case IDs with `insufficient_or_unpaired_evidence`. It reports only `paired_cases` and `distinct_contexts`, not transcript hashes or viewer identities. Positive reports expose `distinct_contexts` as an audit field. Synthetic fixtures now generate a deterministic distinct fingerprint per synthetic case; baseline and candidate for each case retain the same fingerprint. Existing latency and harm checks remain intact.

**Important limitation:** Unique hashes are necessary, not sufficient, for independent observations. Twenty nearby conversational turns in one stream, twenty differently worded restatements, or twenty identical games with different seeds can remain strongly correlated. The hash is provided by the host, not a cryptographic witness of actual media. The updated result is only a **candidate for independent review**, never deployment authority.

**Host normalization contract for any future real-data pipeline:**
- Fingerprint the same normalized and privacy-minimized **complete** context in both arms, including relevant game/version, observable state, speech turn, capture/source protocol and configured time window. Do not fingerprint only an arbitrary case ID or run timestamp.
- Never use viewer personal identifiers, raw public chat, microphone bytes, or unpublished streams as reusable model memory. Keep a host-only link to any confidential audit material.
- Pre-register independent *episodes or sessions*, holdout categories, and the comparison plan. Evaluate both within-episode and across-episode uncertainty, including a leave-one-episode-out check. Future episode-cluster inference should not silently replace this conservative duplicate rejection.
- Rate-limit repeated tests and guard against post-hoc case selection; positive significance computed from a cherry-picked set is not a qualification.
- If context hashing is unavailable or cannot meet its contract, do not claim statistical independence. The offline system should withhold qualification instead of inventing confidence.

### Reproduction and review gates

```bash
/home/star/.cache/star-verification-venv/bin/python -m pytest -q tests/test_stream_quality.py tests/test_stream_quality_paired_evidence.py
/home/star/.cache/star-verification-venv/bin/ruff check star/stream_quality.py tests/test_stream_quality.py tests/test_stream_quality_paired_evidence.py
python3 -m compileall -q star
git diff --check
```

These are local checks, not Windows gaming/OBS performance evidence. Preserve project-wide regression and GitHub Actions before merge.

## 2. Research synthesis: fastest useful intelligence rather than fastest incomplete output

**RealtimeBench/TORSI, 2026-10-14.** The authors evaluated 180 tasks across six continuously running games and found that actions can become useless while slow agents reason. Their offline teacher / fast live student improved the paper's fast agent from 13.51 to 24.19 average progress after two learning rounds. Those are **paper results, not STAR measurements**. Source: https://arxiv.org/abs/2610.20665

**A concrete STAR experiment:** Keep `game_realtime_loop`, `game_action_gate`, `game_deadline_router`, `gameplay_skill_bank`, `game_paired_study`, and `game_transfer_eval` as separate, accountable systems. On each permitted, private game frame: capture timestamp -> structured observation -> short-horizon action policy -> host deadline/scene lease -> action or abstain. After each private attempt, allow an offline coach to study verified outcomes, propose **skill cards** (not immediately rewrite the live model), and schedule harder practice. Only signed unseen-case comparisons can recommend cards for review. No model-generated "I won" claims count as evidence.

**Intelligence that transfers:** Prefer staged curricula for aiming, pathing, timing, object manipulation, menus, parkour, racing, and tactics, with explicit mechanics and failure causes. Include intentionally altered maps, unseen seeds, misleading visual cues, and changed control bindings. Score real progress, success, deadline misses, recovery from mistakes, and qualitative skill-card grounding. Never train on hidden validation traces.

**Faster local inference (experiments, not speed claims).** The current upstream `llama.cpp` server documents prompt caching, cache-reuse, slot persistence, inference metrics, and model router options. Host-RAM prompt caching can save repeated prefill, but changing multimodal context or cache invalidation can negate its value. Test stable prefix caches vs disabled caches, with actual response correctness, completion reason, first audible phrase, p95 time-to-act, RAM pressure, and p95 gameplay frame time. Measure CPU-GPU placement and n-gram/draft speculative decoding on the actual 8 GB GPU; neither is automatically faster. Official reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md and speculative documentation https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**Suggested experiments in order:**
1. Baseline *mixed* 15-minute workload: game active + live-like STT/voice queue + offline model requests, recording p50/p95 end-to-end action latency, verified completeness/correctness, GPU allocation, frame-time tails, dropped OBS frames, and idle vs loaded behavior.
2. Compare warm prompt cache vs cold, unchanged input vs modified game state, short vs long context, and cross-scene invalidation. An apparently fast wrong/reused answer is a failure.
3. Compare small gameplay policy with a larger offline coach, under the same frames and unseen scene controls. Candidate must improve success/progress without increasing deadline misses or stream harms.
4. Admit background experiments only with measured spare CPU/GPU/VRAM. Pause or shed speculative learning first; protect actual player and voice quality. Return to baseline automatically on regressions.

## 3. Game building and self-debugging

**OpenGameEval (published 2026-10-01)** evaluates Roblox agents with a stateful Studio environment, 84 curated tasks, and executable scene/play checks. Its authors found that inspecting relevant objects before changes correlates with better outcomes. Source: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

STAR's proposed engineering loop: inventory the place, map dependencies/instances, plan a minimal semantic edit, generate several candidate solutions, run Luau syntax/type/lint checks, perform Studio multiplayer/UI input tests, verify collision/anchors/physics, capture screenshots, compare against requirements, repair on measured failures, and retain an owner-reviewable diff. Official Studio documentation describes `StudioTestService` multi-client simulation and `UserInputService:CreateVirtualInput()` simulated inputs, restricted to the experience's own UI. Source: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md

A useful quality metric combines **working behavior** and **visual correctness**: finished UI layout at multiple aspect ratios, animation timing, rig/hand grasp, collision material, lighting, VFX occlusion, deterministic client/server outcomes, replication, and FPS under load. A pretty screenshot without a playable test is not a success. For Blender, add topology/rig deformation/render sampling and material seam checks. Maintain rollback checkpoints in Star's internal forge; GitHub is an optional publication channel.

## 4. Natural and expressive VTuber: credible behavior in real time

**Humanlike should mean responsive, consistent, emotionally expressive and socially considerate—not pretending to be biologically human.** Keep STAR's AI identity clear. Allow a coherent persona, humor, thoughtful pauses, self-initiated topics, interests, expressive face/voice, and session-grounded preferences. Build verified long-term autobiographical notes separately from fictional character lore; label uncertainty instead of making up events.

**Turn taking:** LiveKit's open `eot-bench` evaluates 14-language real conversations and explicitly optimizes the **tradeoff between false interruptions and conversational delay** rather than accuracy alone. Compare context-independent episodes, near-silence, echo, overlapping viewers, code-switching, game sound effects, and owner interruptions. Source: https://github.com/livekit/eot-bench

**Voice:** Kyutai Pocket TTS's October 2026 English CPU models include 18.2M, 6.9M and experimental 1.9M variants. The published README says small variants can reach high real-time factors on reference CPU configurations; Star must measure her own CPU load, intelligibility, prosody, first **actual** audio playback, lip synchronization and game FPS before adoption. Source: https://github.com/kyutai-labs/pocket-tts. Avoid cloning real people's voices without appropriate permission.

**Avatar:** VTube Studio offers authenticated WebSocket plugins and custom parameters, letting a host-controlled adapter inject expressions, face/body movement and other animation inputs. Require human-approved mappings, rate limits, playback-clock-aligned mouth movement, neutral expressions on missing audio, reduced-motion support and graceful fallback when the plugin disconnects. Source: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

**On stream:** Permit spontaneous commentary **only from verified observations**: a missed jump, a genuinely completed objective, a newly discovered enemy mechanic, a real viewer question, or an approved memory. During difficult gameplay, brief acknowledgments or silence are more natural than continuous speech. Give Star/Astro/Amber independent speaker identity, priority queues and scene-bound memories so stage chatter cannot interrupt gameplay or misattribute experiences.

**Privacy and trust:** Never treat audience chat as tool authorization; guard against prompt injection, spam and impersonation. Preserve explicit owner approval for broadcasting, account creation, real-money actions, online third-party game automation and irreversible changes. Test privately; do not evade game anti-cheat or site rules.

## 5. Acceptance matrix and next actions

| Area | Measured acceptance | Status as of this document |
| --- | --- | --- |
| Duplicate-context pseudo-independent evidence | Repeated complete context digest in distinct case IDs cannot qualify; unique synthetic cases continue to pass | **Implemented and locally unit-tested** |
| Offline learning transfer | Higher signed win/progress on sealed, independent game seeds with no increased latency misses | Proposal; not measured |
| Inference and resource scheduling | p95 capture-to-action and first-audible response improve on the actual mixed Windows workload, without worse game/OBS frame tails | Proposal; not measured |
| Natural voice | Lower or equal false-cutoff rates at matched latency; better judged prosody; measured PCM/face sync | Proposal; not measured |
| Roblox/Blender game quality | Executable multiplayer tests, collision/UI/render checks, repeatable repair | Proposal; not measured |
| General knowledge | Correct and source-grounded answer rate, dated retrieval, memory provenance, public-permission gates | Proposal; not measured |
| Windows integration | OBS verified **not broadcasting**, actual game+microphone+TTS+avatar process telemetry, no leaked inputs or keys | Not performed here |

**Boundary:** this work repairs a statistical evaluation flaw; it does not install new models, train a smarter neural net, demonstrate more wins, lower measured inference latency, confirm broadcast-ready behavior, or operate games or OBS. Every new capability stays off until a trusted host validates and enables it.
