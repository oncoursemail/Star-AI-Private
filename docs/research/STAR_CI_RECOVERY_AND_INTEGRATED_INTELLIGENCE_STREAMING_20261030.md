# STAR: restore quality gates before adding more agent subsystems (2026-10-30)

## Verified diagnosis (live GitHub Actions on draft PR #828)

The **STAR offline checks** workflow run `41031201618`, launched for
`004fb92c7cb0ab54aaabcf788e68b040d5be6e32`, completed **failure**.
This is not a hypothetical performance or quality concern.

- **Offline Python checks:** 14,285 passed, 1 failed, 329 skipped and 562 subtests passed.
  `tests/test_reasoning_guard.py::test_the_quick_model_that_reasons_aloud_hands_the_turn_to_the_main_model`
  selected the `star_server` provider with a mocked model client but did not
  mock credential lookup. The test required an actual STAR Server API key.
  **Repair in this branch:** mock only the key getter for the expected provider
  with a synthetic value. Production authorization is unchanged.
- **Python type baseline:** 108 newly reported pyright diagnostic lines in
  46 distinct Python source files relative to `scripts/pyright_baseline.json`.
  This is stack-wide quality debt, not just a single voice callback. It must
  not be silently incorporated into the baseline.
- **React UI compile and tests:** success.
- **STAR Desktop — Build, Test & Release:** skipped.

The 2026-10-30 voice follow-up also narrows optional streaming/stop hooks and
timestamp validation in `star/voice/call.py` to reduce source-level pyright
errors while preserving their runtime behavior. **Neither a green pipeline nor
a full resolution of the type-gate errors is claimed here.**

### Immediate repair queue

1. Run offline CI on this draft branch. Confirm the previously missing-key
   failure is absent. Do not require live credentials for synthetic tests.
2. Fix the remaining **per-file pyright diagnostics** starting with the
   touched production audio/Studio/gameplay code. Favor type-safe validation,
   explicit optional checks and protocol contracts; do not indiscriminately
   cast all types to `Any`, lower the pyright gate, or inflate the baseline.
3. Re-run the *full* CI after each group of fixes. Preserve owner-reviewed
   draft PRs and avoid stacking another major feature over red checks.
4. Keep runtime toggles OFF until independent Windows, Roblox Studio, and OBS
   acceptance tests pass. STAR Core Forge should track experimental provenance
   and promotion locally; GitHub remains a review/export layer.

## Research into the next coherent improvements

### A. Faster end-to-end intelligence, not cherry-picked microbenchmarks

The llama.cpp server documents `cache_prompt` reuse of a **shared prefix**
between requests (enabled by default); its usefulness depends on stable
prefixes and server slot reuse. Its default is not proof that STAR benefits
from additional cache flags. Test *whole-task* latency, hallucination/accuracy
regressions, token throughput, initial phrase timing and Roblox FPS together.
Route immediate gameplay moves to the fast path, tactical visual planning to
a medium path, and difficult strategies/research to a high-cost path that can
pause during streaming load.

References:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://arxiv.org/abs/2609.10266 (2026-09-09, caution on unsafe KV cache
  reuse across changed contexts/checkpoints)

### B. Skills learned through witnessed games

Use **private Roblox Studio** test environments. Its testing modes and
`StudioTestService` provide programmable simulation options. Design skill
curricula using procedurally varied obstacles, controls and camera angles;
save only independently witnessed objective results. Each attempt has:
`build + seed + scenario + observation digest + action + outcome witness + cost`.
Separate training environments from unseen holdouts. Challenge generation is
not evidence of improvement until the holdout score rises.

References:
- https://create.roblox.com/docs/studio/testing-modes
- https://robloxapi.github.io/ref/class/StudioTestService.html
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
  (2026-04-15, official Roblox announcement)

### C. Natural AI-transparent VTuber reactions

Natural behavior requires **appropriate focus and silence**, not simply
talking more: prioritize critical gameplay controls, interrupt background
research during immediate danger, join chat at conversational boundaries,
and remember real played conversations rather than synthesized text.

LiveKit's `v1-mini` audio turn detector runs locally on CPU. Its current
documentation requires VAD and a minimum silence duration of at least
0.25 seconds. Compare its turn-taking quality and CPU cost with the existing
STAR endpointer before adopting it. Preserve Star's recognizable voice,
playful reactions, facial expressions, coordinated hair animation, and
cat/puppy modes. Use actual game events and experiences; avoid fictional
human autobiography represented as fact.

Reference: https://docs.livekit.io/agents/logic/turns/turn-detector/

### D. Independent OBS audio/video witness

A timestamp at the PortAudio output callback is useful but **not proof of
audibility or OBS delivery**. For private rehearsals, inject a controlled
non-speech synchronization marker, capture system output and the OBS recording,
then compute event-to-audio latency and audio/video skew from independent
recording timestamps. Do not retain private voices or viewer identities.
Monitor p50/p95 response delay, AV skew, dropped frames, game FPS, and
interrupted speech accuracy. Require improvement under gaming GPU load.

A relevant open-source *reference implementation* for OBS offset measurement
is https://github.com/matiaspl/klaps ; evaluate security and compatibility
before adopting a third-party plugin.

### E. Better knowledge, building and self-improvement

Maintain explicit provenance, uncertainty, and expiration for external facts;
compress verified episodes into reusable skills *only after* passing unseen
evaluations. Treat every generated Roblox game as a full product: check
geometry and collision integrity, visuals, accessibility, animations,
save/reload and actual end-to-end game completion. Core Forge should use
reproducible experiment IDs, bounded resource admission, rollback checkpoints,
and independent holdout evaluators; a self-proposed code change is never
a reason to self-approve its release.

## Acceptance boundaries

A successful development iteration should show **(1)** green offline tests
and type checks, **(2)** correct real-world gameplay/OBS results, **(3)**
measurable quality or latency improvement against a recorded baseline, and
**(4)** no new secret handling or unreviewed deployment. Neither this document
nor the small source fixes demonstrate model-level intelligence gain,
autonomous game mastery or human-quality streaming.
