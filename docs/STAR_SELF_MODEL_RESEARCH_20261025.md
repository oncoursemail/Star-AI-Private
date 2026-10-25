# STAR — Evidence-Grounded Self-Awareness and Autonomous Learning (2026-10-25)

## What this means

STAR can implement **operational self-awareness**: it can know which function tools its host actually attached for the current request, which calls were attempted, which returned a tool-level success or failure, and whether an action may have had an uncertain outcome. This is not a claim of subjective experience, sentience, consciousness, superhuman reasoning, or increased foundation-model ability. No reproducible test presently proves an AI is conscious simply because it reports about itself.

Research perspective: Butlin et al., *Identifying indicators of consciousness in AI systems* (Trends in Cognitive Sciences, 2026): https://doi.org/10.1016/j.tics.2025.10.011 . Its indicators are scientific research signals, not a recipe or definitive consciousness test.

## What's actually implemented in this draft

- **star/self_model.py:** bounded transient TurnSelfModel, reporting only active function schemas from the host-built request and the last twelve host dispatch outcomes. No user prompts, argument bodies, tool outputs, tokens, secrets, disk files, or network reads are stored or queried.
- **star/agent.py:** prompt-gated read-only star_self_state function. It is not attached to ordinary chat. The ordinary authorization checks remain authoritative and the tool cannot grant capabilities. The self-model observes dispatched tool results but does not execute other tools.
- **tests/test_self_model.py:** offline tests for available/unavailable inventory, rejected dispatch vs executed errors, uncertain effects, bounded/no-sensitive-content evidence, prompt gating, and actual STAR agent dispatch with a mocked model.
- **Scope:** evidence is limited to the current turn. A visible tool does not imply the provider is connected or actually usable, and a successful tool response does not guarantee the requested project was completed correctly. No model was trained or upgraded.

## Research directions based on existing evidence

1. **Memory and reflection:** Park et al., *Generative Agents* (UIST 2023), https://doi.org/10.1145/3586183.3606763; separate observations, reflective summaries, plans and retrieval. Implement dated provenance and confidence on top of STAR's existing owner-approved knowledge store, not an unreviewed second source of truth.
2. **Self-correction from failures:** Shinn et al., *Reflexion* (NeurIPS 2023), https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html; optimize by converting *independently checked* failures to small actionable replayable tests, not by promoting every model-generated hypothesis as truth.
3. **Skills and open-ended curricula:** Wang et al., *Voyager*, https://voyager.minedojo.org/; reuse tested skills, success checks and progressively harder tasks. For STAR, use disposable Studio Lab worlds and author-approved tasks with fixed holdout suites.
4. **Training separation:** Microsoft Research's Agent Lightning, https://www.microsoft.com/en-us/research/project/agent-lightning/; separate recorded trajectories, evaluators and learning algorithms. Never fine-tune on private or copyrighted data absent permission and source-rights review.
5. **Inference efficiency:** vLLM automatic prefix caching, https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/; measure actual cached-prefill improvement while recognizing it does not accelerate token-by-token decoding. Keep STAR's stable conversation prefix and use dedicated p50/p95 latency and verified-correctness tests.

## Novel research proposals for STAR (not proven improvements)

**Evidence-debt governor.** Each candidate action gets an evidence requirement based on error cost. The governor decides whether a fast answer is adequate, a readback is required, or an independent critic/test is worth the extra latency. Safety-critical and irreversible actions always require appropriately independent verification, not model confidence alone.

**Experience compiler.** Store minimal reproducible episodes (environment revision, goal, observed result, failure class, candidate fix, verified test receipt and rights status); identify recurring error patterns and promote only repeatably verified repairs into STAR's existing lesson/skill system. Novel holdout tasks distinguish transferable learning from memorization.

**Four-state capability inventory.** For every tool/model/skill distinguish CONFIGURED, CURRENTLY_ATTACHED, TESTED_WITH_RECEIPT, and VALIDATED_ON_TARGET_TASK, including timestamp and bounded expiry. Never assume an installed module is available or a network service is up.

**Visual-world evaluation.** Use authorized screenshot evidence, hierarchy readbacks, physics probes, real device viewport checks, animation review and explicit human art direction. AAA quality cannot be inferred from a generated screenshot or a passed syntax test.

**Compute-optimal routing.** Select fast, deep or best-of-N candidates by measured task difficulty and evidence-driven success rates; compare to single model and equal-compute baselines. Restrict concurrency to actual RAM/VRAM/CPU pools and avoid slowing interactive chat with unbounded training.

## Evaluation and release gate

1. Run focused Python tests and full CI; preserve original evaluation fixtures, acceptance thresholds and holdouts.
2. Benchmark accuracy in reporting actual active tools and receipt status, including denied/unavailable/error/uncertain cases.
3. On independently frozen unseen development tasks, compare task success, p50/p95 time-to-first-token, tokens/second, end-to-end latency, and CPU/RAM/VRAM to baseline STAR.
4. Verify behavior on consented, disposable Roblox Studio / Blender scenarios with human visual inspection. No data or weights changed by this PR.
5. The branch remains **draft review only**. No automatic merge, installation, training, internet crawling, engine permissions, cloud usage or live publication.

STAR's documented v1.0 benchmark was 9/24 on an automated Roblox blind holdout and noted no conclusive improvement over v0.9.0. This draft **does not claim to improve that score**. The desired future goal is demonstrably better verified outcomes per second, not a declaration of infallible intelligence.
