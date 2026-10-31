# STAR Intelligence: verified-compute efficiency and quality gate (2026-10-24)

**Status:** experimental source change on a task branch; not merged, shipped, enabled as a default, or benchmarked on the owner's live models.

## Executive decision

STAR already has a working verification-driven Best-of-N implementation (`star/best_of_n.py`), cache banks, prompt layout stabilization, model routing and offline evaluation gates. Adding more sample calls without evidence would waste its CPU/8 GB VRAM budget. This change makes **existing** verification work more economical and prevents apparently successful repairs that silently lost earlier checks. It does not claim to improve model weights or guarantee higher benchmark scores.

The research-backed direction is **more useful checked work per second**, not maximum token volume. Selection quality must be proven on independent frozen tasks under a fixed budget; speed must be measured, not inferred from source changes.

## Research, checked 2026-10-24

| Finding | Relevant evidence | Implication for STAR |
| --- | --- | --- |
| Candidate search can improve reasoning when verification is dependable. | Zhao, Awasthi & Gollapudi, *Sample, Scrutinize and Scale*, ICML 2025, https://proceedings.mlr.press/v267/zhao25a.html | Reuse STAR's candidate/checker pipeline; don't replace hard checks with a generic model's confidence score. |
| A verifier that finds discriminating counterexamples can improve code selection. | Ma et al., *Scaling Agentic Verifier for Competitive Coding*, ICML 2026, https://proceedings.mlr.press/v306/ma26av.html | Research an owner-reviewed differential-case generator later. Their reported benchmark gains **are not STAR measurements**. |
| Long coding-agent rollouts benefit from compact summaries and comparison, not simply keeping every token. | Kim et al., *Scaling Test-Time Compute for Agentic Coding*, arXiv 2604.16529 (2026), https://arxiv.org/abs/2604.16529 | Future candidate summaries should retain hypotheses, real tests, failure modes, and provenance, not free-form self-praise. |
| Unconditional LLM self-verification is unreliable and varies with problem difficulty. | Zhou et al., *Variation in Verification*, ICLR 2026, https://proceedings.iclr.cc/paper_files/paper/2026/hash/ea21628f0fc0de542373be4c88343478-Abstract-Conference.html | A model judge can only break ties **after** deterministic checks; do not call it proof of correctness. |
| More expensive verification can be useful if grounded in execution evidence. | Jin et al., *ReVeal: Self-Evolving Code Agents via Reliable Self-Verification*, ICLR 2026, https://www.microsoft.com/en-us/research/publication/reveal-self-evolving-code-agents-via-reliable-self-verification/ | Use targeted repair feedback with freshly rerun checks. This PR strengthens the gate; it does not perform RL training. |
| Shared prompt prefixes can save prefill compute but cannot speed token-by-token decoding on their own. | vLLM, *Automatic Prefix Caching*, https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/ | STAR's llama.cpp cache and stable context layout should be profiled on actual supported models before any engine change. |
| llama.cpp exposes prompt cache and slot controls; request/slot concurrency is a real capacity constraint. | Official llama.cpp server manual, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md | Do not spawn more model samples than available slots; leave the pre-existing capacity planner in charge. |
| Tool latency and dependency tracking affect multi-task-agent results. | Shi et al., *AsyncTool*, Findings of EMNLP 2026, https://aclanthology.org/2026.findings-emnlp.982/ | Profile response-time distribution and cancellation before enabling more background agent work. |

## What is implemented here

### 1. Within-turn verification reuse

`BestOfN.evaluate` groups candidates in RAM, **only during that turn**:

- Static verifier key = exact `(extracted_source, full_answer)`. Some checkers inspect Markdown completeness, so two answers with matching source but different surrounding text must **not** share static verdicts.
- Sandbox key = exact extracted source with the same shared generated-test string for the turn. A single sandbox result is copied into all matching candidates. Different source text is never deduplicated. Mutable dicts and check lists are copied so ranking cannot corrupt another candidate's evidence.
- The existing concurrency cap of three verification jobs remains; cancellation is still owned by the Best-of-N turn. No persistent disk cache, global prompt cache, cross-user cache or new permissions are introduced.
- A checker exception produces a **failed** static-verification result, not a successful empty result. A sandbox exception becomes **not run** with only its error class logged (no raw endpoint, exception message or source content).
- When the blank module/stub reference run is unavailable, **none** of the model-authored assertions count as independent evidence. This protects against vacuous assertions.

The work record contains counts, not source: `candidates`, `static_runs`, `static_reused`, `sandbox_runs`, `sandbox_reused`. It is emitted as a structured event and archived in the existing Best-of-N turn record.

### 2. Evidence-preserving repairs

A regenerated answer is accepted only when it reduces verified hard failures **and**:
1. All originally executed static checks can still run; no check disappears.
2. Every originally passing static check still passes.
3. If the original answer had counted unit-test evidence, the repaired code successfully reruns the same tests, retains every previously passing assertion and does not conceal an unavailable sandbox.
4. The winning candidate's stored unit results, failures and checks are updated together; there is no stale success report.

This is intentionally conservative: some useful edits may require a manual second round instead of being silently promoted. A warning or refusal to upgrade is better than a fabricated pass.

### 3. Explicit limits

- Generated tests are **not** the same as independent owner-authored acceptance criteria, Roblox Studio playtesting, real network tests, or hidden holdout tasks.
- Identical source run once in the sandbox does **not** create several independent pieces of evidence.
- The within-turn reuse is bounded by N <= 8 and dies with the turn; it cannot contaminate a different project or conversation.
- Real-time latency may not improve when candidate generation dominates or all candidates differ; an exception-failed checker does not mean the source is definitely broken.
- Do not run proposed Luau inside the Windows chat application. The existing separate configured sandbox remains the only test execution path.
- This change touches neither policy/auth/authz nor release pipelines; it has no ability to install models, send unapproved tool calls, edit protected eval fixtures or merge itself.

## Measurements and acceptance plan

**Offline deterministic tests:** `tests/test_verified_compute_efficiency.py`, plus the existing Best-of-N and desktop integration tests. They assert exact checker and sandbox invocation counts, candidate selection invariance on duplicate inputs, failure isolation, and repair rejection when past passing tests regress.

**Example of work-accounting, not an actual speed benchmark:** if four candidates contain three distinct full answers and only two distinct source bodies, the same checks previously needed four static calls plus four source sandbox calls and a stub run. The new design uses three static calls plus two source sandbox calls and the same stub run. This is fewer *calls*, **not** a claim that overall chat latency falls by 25% or 50%.

**Before enabling a default behavior change:** use STAR's existing independent evaluated Roblox development/creation cases, then a sealed holdout. Preserve immutable evals and graders. Run paired baselines with the same tasks, model file/digest, context window, cache configuration, seeds (if supported), concurrency, tool permissions, timeouts and actual hardware. Collect:

1. First-token, complete-answer and end-to-end verification wall time: p50, p95 and worst-case.
2. Prompt tokens processed, generated tokens, model slots occupied, peak RAM/VRAM, sandbox executions and error rates.
3. End-to-end task pass, common regressions, repair acceptance rate, false-pass/false-fail audit.
4. Duplicate source share, static-reuse share, sandbox-reuse share and correlation with latency.
5. Native Studio smoke/play tests **separately**; static Luau and isolated-VM checks do not establish Studio behavior.

Require a paired quality gate and independent holdout before changing a default or promising any numerical gain. If candidates differ almost always, work reuse will be close to zero; keep it only if the complexity remains justified.

## Prioritized future experiments (not implemented by this PR)

**P1 — budget-calibrated candidate generation:** use measured task difficulty + verifier hit rates + available free slots to decide whether N=1, 2 or 4 is worth it. Do not let heuristics escalate indefinitely. Compare against fixed-N and existing heuristics with the same total inference budget.

**P2 — counterexample-guided repair:** ask a verifier to create *candidate-distinguishing* edge cases using operator-approved specifications, run them in an isolated sandbox, and only promote after independent check coverage. Do not trust a model's claim to have executed a test.

**P3 — prefix/cache profiling:** benchmark current llama.cpp `cache_prompt` and STAR's opt-in KV-bank checkpoint on each exact model revision. Consider native speculative decoding or an alternative engine only after measuring tokens/s, memory, cold and warm prefill, and decode quality on this CPU/8GB-GPU setup. vLLM's APC feature is not a drop-in switch for a llama.cpp server.

**P4 — compact rollout knowledge:** store evidence-bound summaries of errors/fixes per project with owner approval, fingerprints, TTL, privacy boundaries and provenance. Retrieval should abstain for unknown or stale facts; never learn policy grants from generated text.

**P5 — multi-brain workload governor:** independent work may run on idle brains; throttle when the owner is streaming or interacting, never claim unexecuted actions, and prefer UI responsiveness over speculative training. Measure actual model and Studio latency before concurrency increases.

## Local reproduction

```sh
python -m compileall -q star/best_of_n.py tests/test_verified_compute_efficiency.py
python -m pytest -q tests/test_best_of_n.py tests/test_best_of_n_desktop.py tests/test_verified_compute_efficiency.py
git diff --check
```

Do **not** merge or publish until normal CI and project review. Model comparisons, Windows installer tests and live Roblox Studio runs require separate evidence.
