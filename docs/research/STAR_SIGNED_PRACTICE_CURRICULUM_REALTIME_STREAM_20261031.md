# Star AI — signed-practice curriculum, real-time gaming, and VTuber engineering

Date: **2026-10-31**. Scope: offline-first Star AI / Star Core Forge, game lab, local inference, authored Roblox projects, and owner-approved stream rehearsals. **Research hypotheses are not completed deployments.** This report distinguishes this implementation from untested integrations.

## Shipped: difficulty-gated curriculum planning

`star/game_practice_curriculum.py` consumes only `GameplaySkillBank.practice_evidence()`, the existing practice-only aggregate view backed by independently host-signed trial receipts. It selects one bounded, host-curated exercise; it cannot run a game, edit a project, read held-out validation, or promote a skill.

- **Prevent false progression.** Every listed situation/action at the current difficulty must have at least eight verified practice trials and a Wilson 95% confidence lower bound >= 0.55 (both configurable within bounded ranges). A good run on one map cannot conceal an unpracticed map. More difficult tiers remain locked until every lower-tier entry meets the threshold.
- **Increase practice diversity.** Prefer candidates with fewer trials and weaker conservative confidence, then older practice. Every candidate must match one game/version/objective, avoiding cross-game evidence leakage. The signed bank is read once per situation.
- **Detect ineffective loops.** After 40 trials without reaching the threshold, return `review_required` rather than automatically practicing forever. Inspect capture fidelity, action correctness, game focus, map difficulty, and whether a new strategy is needed.
- **Fail closed.** Off by default. Reject malformed identifiers, unbounded target sets, contradictory difficulties, duplicate or invalid signed aggregates, and future timestamps. Propagate evidence integrity errors. The planner caches no screenshots, player identities, transcripts, signing secrets, or holdout results.
- **Independent evaluation remains mandatory.** The planner reports *practice* progress only. Unseen holdout maps and separately signed validation remain necessary before promoting skills. Confidence bounds describe observed samples; they are not proof of general intelligence.

Local targeted tests during development: `python -m pytest tests/test_game_practice_curriculum.py -q` — **18 passed**. GitHub CI and the actual authorized Windows gaming run require separate verification.

### Example integration

```python
from star.game_practice_curriculum import PracticeTarget, recommend_practice

advice = recommend_practice(
    bank,  # existing GameplaySkillBank, not a model-controlled mock
    targets=(
        PracticeTarget("obby", "v3", "jump_timing", "bridge_easy", "jump", 1),
        PracticeTarget("obby", "v3", "jump_timing", "moving_easy", "jump", 1),
        PracticeTarget("obby", "v3", "jump_timing", "moving_hard", "jump", 2),
    ),
    now_unix_s=trusted_host_unix_time,
    owner_approved=True,
)
# A recommendation is never permission to inject a keypress.
```

A trusted host must approve the game and every scenario, reserve unique practice run IDs, collect real observed outcomes, sign receipts, and call `GameplaySkillBank.ingest()`. Never pass arbitrary model-proposed action IDs into a game controller. A `review_required` status blocks the autonomous retry loop. Keep the existing freshness, independent validation, and resource admission gates.

## Highest-value infrastructure research and next experiments

**1. Two-timescale intelligence.** The October 14, 2026 paper *The World Won't Wait: Evaluating and Teaching Agents Under a Live Clock* introduced RealtimeBench (180 tasks, six continuously running game types). A fast gaming agent handles urgent input while a stronger teacher studies recorded failures between attempts. Its reported 13.51-to-24.19 score change belongs to the researchers, **not Star**. Connect bounded observation→decision→action→outcome traces to reviewed exercises and signed receipts, then promote only tactics that independently pass unseen trials. Do not invoke the expensive teacher during urgent gameplay. Source: https://arxiv.org/abs/2610.20665

**2. End-to-end deadline budgeting.** Measure capture age, LLM prefill, decision completion, input-dispatch age, gameplay FPS, first audible TTS chunk, playback-synced avatar motion, OBS rendering/encoding loss, VRAM headroom, and per-task CPU usage independently. Propose game-specific p95 action deadlines, zero wrong-session input under fault injection, and no OBS/game FPS regression. These are **acceptance targets, not observed measurements**. Expensive rendering/research should run only when the stream resource controller has safe capacity.

**3. Local model benchmark matrix.** Compare CPU-only quick responses, GPU layer offload, prompt-cache modes, and speculative decoding on the 8 GB gaming GPU under matched prompts and fixed seeds. The official llama.cpp SPEED-Bench client measures server latency, throughput, and speculative acceptance. Its presence is not proof of speedup on Star's computers. Track p50/p95 first-token time, total action age, answer correctness, peak memory, and OBS dropped frames before accepting any optimization. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**4. Humanlike but truthful streaming.** Build natural turn endings, reliable owner interruption, short audio chunks, output-audio-clock lipsync, expressive eyes/body/hair, moment-appropriate laughter, and intentional silence. LiveKit's `v1-mini` turn detector is a local CPU candidate. Kyutai Pocket TTS v4.0.0 (October 20, 2026) added 18M/7M/2M English model variants; v4.0.1 (October 21) corrected issues affecting sub-20M models. Compare speech naturalness, timing, CPU contention, and existing voice identity before switching. Neither component was installed here. Sources: https://docs.livekit.io/agents/logic/turns/turn-detector/ and https://github.com/kyutai-labs/pocket-tts/releases

**5. Polished autonomous game building.** Use inspect → design specification → scene build → code checks → executable gameplay → multiplayer test → visual/collision audit → repair. Roblox StudioTestService offers plugin-run tests with up to eight simulated clients, one multi-client session per Studio instance. Probe late join/leave, absent props, wrong pivots, colliding geometry, texture seams, broken animations, UI clipping, and frame rate. Preserve editable scenes instead of substituting attractive renders. Source: https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers

**6. Wider reliable general knowledge.** Maintain source-provenanced verified facts, tool-corroborated observations, reusable task skills, hypotheses, and fictional persona lore as distinct records. Build domain skill packs for Luau/Roblox, Blender/rigging, UI, physics, audio, video understanding, multiplayer design, and general knowledge. Test unseen tasks and calibrated abstention against the old revision before claiming new intelligence.

**7. Natural social continuity.** Store only approved, bounded, revocable recollections of actual gameplay and social interactions. Star can be playful, cute, witty, and spontaneous without claiming an invented childhood, literal human biology, or wins she never earned. Disclose that she is an AI VTuber rather than pretending to be human.

## Reproducible acceptance checks

| Area | Tests before promotion |
| --- | --- |
| Game skill | Multiple unseen maps per tactic; independently signed validation, no scenario regression |
| Curriculum | Cold start, undercovered map, harder-tier lock, 40-failure stop, corrupt evidence |
| Game control | Replayed/stale observations, wrong focus/session, clock rollback; zero unauthorized dispatch |
| Streaming | OBS live/reconnecting/preview state, GPU overload, speaker interruption; no stale speech/animation |
| Voice and avatar | Scripted speech, silence, interruption; human-rated clarity and measured p95 audio latency |
| Builder | Single- and multi-client Studio tests, geometry and visual review, gameplay quality bar |
| Star Core Forge | Matched app revisions, unseen holdouts, rollback on any privacy/speed/quality regression |

### Explicit release status

This revision provides a **deterministic practice-selection policy and isolated tests**, not a live gaming agent or a new neural model. No actual game was played, game skill gain was observed, neural weights were trained, livestream was started, Windows tests were run, or new speech packages were installed in this change. The repository named `Star-AI-Private` currently reports public GitHub visibility; its name does not make it confidential.
