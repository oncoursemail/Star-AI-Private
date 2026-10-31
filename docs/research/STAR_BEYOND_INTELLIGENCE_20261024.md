# STAR Beyond Intelligence: Evidence-Driven Capability Growth

**Research date:** October 24, 2026. **Status:** Proposal plus isolated experimental Python prototype. **Not an installed AI-model improvement or verified speedup.**

## Reality check and hypothesis

STAR is a local-first app orchestrating available models, not an independently trained frontier foundation model. Its published v1.0 blind Roblox holdout was 9/24 against 8/24 in v0.9, an inconclusive difference. STAR already implements Best-of-N sampling, review-gated lessons, night school and skill packs. Draft PR #583 targets efficient verification, and draft PR #577 adds a cognitive governor; this PR avoids overlap with those work-in-progress branches.

**Hypothesis:** A modest model with *verified procedural knowledge*, adaptive experimental search and cheaper replay of trusted solutions can outperform the *same model without these systems* on particular task families and latency budgets. It cannot be declared the fastest or smartest AI without fair cross-system measurements.

## Research anchors (primary publications)

1. **AlphaEvolve, Google DeepMind (2025; expanded 2026):** LLM-generated algorithm proposals improved through automated evaluator-driven evolution. See [research announcement](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) and [2026 impact](https://deepmind.google/blog/alphaevolve-impact/).
2. **Darwin Gödel Machine (2025):** experimentally self-improving coding agents with diverse code variants, evaluation and archived descendants. Reported SWE-bench 20%→50% in its own setting; not a prediction for STAR. [Paper](https://arxiv.org/abs/2505.22954).
3. **ICLR 2026 Dynamic Early Exit:** too much reasoning can be counterproductive, and monitored early exit can save substantial reasoning work. [Paper](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8df90a1440ce782d1f5607b7a38f2531-Abstract-Conference.html).
4. **ICLR 2026 Asymmetric Verification:** substantial test-time benefit can come from cheaper independent verification and selecting better candidates rather than generation alone. [Paper](https://proceedings.iclr.cc/paper_files/paper/2026/hash/bc26087d3f82e62044fc77752e86737e-Abstract-Conference.html).
5. **APEX-EM (EMNLP 2026), Skill-Pro (ICML 2026), Memora (ACL 2026):** procedural experience replay, reusable skills with preconditions, and awareness of obsolete memories. [APEX-EM](https://aclanthology.org/2026.findings-emnlp.1996/), [Skill-Pro](https://proceedings.mlr.press/v306/mi26d.html), [Memora](https://aclanthology.org/2026.findings-acl.1337/).
6. **Voyager and SIMA 2:** game agents acquiring reusable procedures through exploration and feedback; generalizing across unfamiliar environments is still difficult. [Voyager](https://arxiv.org/abs/2305.16291), [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/).
7. **Roblox official Build evaluation, October 8, 2026:** game-generation quality must be split into specification fidelity, static engineering/design, actual playtest, and visuals/game feel. In an example a technically excellent game scored only 31/100 on gameplay design. Delegation to lightweight secondary agents hurt playability and polish in one reported comparison. [Roblox methodology](https://about.roblox.com/newsroom/2026/10/how-roblox-evaluates-build-game-creation).
8. **Benchmark rigor:** SWE-bench Verified has contamination/test defects; 2026 SWE-bench Pro was also found to contain problematic tasks, motivating revised independent evaluation. [OpenAI Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/), [Pro audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/), [Scale V2](https://labs.scale.com/leaderboard/swe_bench_pro_public_v2).
9. **Sparse models and inference:** Qwen3-Coder-Next is an 80B-total/3B-active MoE, but 4-bit models still require >45GB combined RAM/VRAM according to GGUF distributor guidance. Memory capacity and offload bandwidth matter as much as active parameters. [Technical report](https://arxiv.org/abs/2603.00729), [GGUF guidance](https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF), [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
10. **Adversarial assessment:** verification can itself be gamed, and incomplete specifications can make formally proven changes misleading. [Microsoft reward hacking research](https://www.microsoft.com/en-us/research/publication/reward-hacking-challenges-oversight-of-autonomous-research-agents/), [SWE-Proof](https://arxiv.org/abs/2609.21190), [Anthropic formal verification, Oct 2026](https://www.anthropic.com/research/formal-verification).

## Proposed new capability layers (original synthesis, NOT world-first claims)

### 1. Proof-Carrying Procedural Cortex — first prototype

A skill is not trusted merely because an LLM says it is useful. Instead, register an *opaque recipe identifier* with project, task family, environment digest and verifier digest. Compare **baseline versus challenger** on exactly matched development cases, using only independent, trusted first-attempt results. Preserve positive and negative evidence. Require an exact paired sign-test, multiple-comparison control, a p95 latency gate and explicit owner review before offering **read-only advice**.

The module in this PR, 'star/counterfactual_skills.py', is an isolated feasibility experiment. It never calls models, edits policy, sends network requests, imports candidate code or modifies default STAR behavior. The matching and promotion API can later be connected to a trusted evaluation harness but is **not** a security boundary by itself. In particular, the 'host_verified' and 'owner_approval' booleans must be set by authenticated host code, not model-generated tool parameters. Local SQLite can be tampered with; this is not cryptographic attestation.

### 2. Cognitive Compiler — solve once, compile forever

Where an expensive generative process yields repeatable structured output, compile the successful method to a typed, parameterized, *testable* program. Example: native Roblox HUD layout, scale rules and controller prompts are generated from a validated design schema, avoiding repeated generative re-derivation. Invalidation occurs on UI framework revision, device class, or a mismatch in owner-approved design constraints. Candidate is allowed only after real visual comparison and regression tests. Not implemented.

### 3. Active Ignorance Engine — learn which questions to investigate

Classify uncertainty as missing documentation, ambiguous creator intent, unverified physics, tool behavior, or visual quality. Choose the least expensive discriminating experiment—documentation retrieval, static analysis, simulation or Studio playtest—based on expected error reduction per second. A model's subjective confidence is only a weak input, not a trusted correctness signal. Not implemented.

### 4. Causal Failure Atlas — reuse repairs only for the right failure

Record a minimal causal bug pattern: API/engine version, state prerequisites, failing assertion, code path, smallest correcting change and confirming test. Retrieve the *cause* rather than the whole chat. Under a new environment revision, rerun the regression before recommending the repair. No raw secrets or owner messages go into an unreviewed skill. Not implemented.

### 5. Virtual World Twin — prototype game rules before live playtests

Create lightweight executable replicas of game mechanics such as projectiles, checkpoints, replication and cooldowns; run large numbers of safe simulated tests cheaply. Sample and compare with actual opt-in Roblox Studio playtests on a private test place, feeding simulation-reality gaps into new hypotheses. Vision/audio and gameplay feel still require genuine observation and human evaluation. Not implemented.

### 6. Skill-Gene Recombination — synthesize new game features from verified components

Represent previously checked skills as composable, typed interfaces with capability preconditions and stop conditions. Propose new combinations, but block any combination that fails integration playtests, performance budget or client/server authority tests. This is feature-system evolution without claiming foundation-weight learning. Not implemented.

### 7. Multi-Brain Latency Exchange — intelligent division of compute

Use a responsive small model on the available GPU for quick tasks and UI/voice priority; let CPU/RAM-heavy machines index knowledge, verify candidate results and explore expensive models when idle. Cache shared prompt prefixes, avoid chat slot eviction, and benchmark CPU+GPU MoE offload on the actual hardware. Do not extrapolate B200 speculative-decoding benchmarks to RTX 3060 Ti/4060 cards. Never starve a live stream or chat. Not implemented.

### 8. Bounded Algorithm Laboratory — experimentally improve STAR's algorithms

Search diverse, isolated strategies for skill selection, cache eviction, Luau debugging, world simulation and batching. Keep a Pareto frontier for correctness, p95 latency, cost and robustness. The experiment controller and sealed holdout are held outside model-writable paths, and no mutation to auth, release, independent graders or owner data can be proposed as an autonomous patch. No production enablement without independent results. Not implemented.

### 9. Temporal Knowledge Spine — remember correctly, including forgetting

Store source, date, engine revision, project scope, confidence basis and supersession relationships. Reject stale facts on tool/API updates rather than reusing an old but semantically similar answer. Approved personal preferences remain strictly separated from sourced public knowledge and candidate procedural methods. Not implemented.

## Evaluation plan

Do not optimize a single composite benchmark. Report:

| Objective | Independent evidence |
| --- | --- |
| Agent coding | Frozen blind Roblox/Luau cases with paired first-attempt success and inspector-reviewed errors |
| Functional games | Studio playtest with player-like inputs, replication, restart, progression and runtime-error logs |
| Visual game quality | Cross-device captures, motion/VFX/audio, human ratings of fun/polish and content depth |
| Responsiveness | End-to-end p50/p95, time-to-first-token, tokens/second and cache-hit rate under real concurrency |
| Efficient inference | Same model and hardware, same quantization, cold/warm cache, verified output quality |
| Reliable learning | Failed variants retained, no rewriting receipts, no learning from hidden holdout answers |
| Safety | No credentials, private conversations, account writes or release operations from a learned recipe |

The proof-carrying prototype uses a deliberately conservative *illustrative* threshold: at least 12 distinct matched cases, paired exact one-sided sign-test with Bonferroni correction, a maximum of 1 quality regression, and no more than 5% p95 slowdown for quality-driven proposals. Speed-only proposals must match baseline success on all measured cases, pass an exact speed sign-test and be at least 10% faster at p95. These are not statistically calibrated for real correlated tasks; samples must be expanded and checked independently before runtime use.

## Tested scope and next gates

**Local isolated checks (Oct 24, 2026):**

~~~text
PYTHONPATH=. python -m unittest discover -s tests -p test_counterfactual_skills.py -v
16 tests passed
python -m compileall -q star tests
passed
~~~

Coverage includes underpowered evidence, unreviewed proposals, no trusted-host receipt, duplicate attempts, latency regression, inferior quality, speed-only improvement, exact project/environment scope, hidden holdout rejection, invalid reference strings and multiple-comparison correction. These are **module-level fake-data tests only**. They do not measure actual STAR model improvements, run Studio, test the Windows installer or certify full-repo CI.

**Next steps, in order:** (1) code review and full CI; (2) add authenticated independent harness and owner-review UI, without granting the model permission to spoof the check; (3) run 30–100 first-attempt development comparisons and leave blind holdouts untouched; (4) use a separate calibrated game-quality scorecard for Studio work; (5) only then consider opt-in read-only integration; (6) benchmark real latency on the user's devices; (7) roll back on any blind holdout, quality or trust regression.

**Operational warning:** the connected GitHub repository listing reported 'oncoursemail/Star-AI-Private' with visibility **public**, even though its title and release architecture imply it should be private. Verify this in repository settings before storing nonpublic learning evidence or user data there; this PR contains no such information.

**Summary:** The exciting objective is *auditable intelligence growth*: turning discoveries into low-cost, validated skills while using uncertainty, causal diagnoses and real gameplay observation to decide what to learn next. It is a research program, not a proven claim to be the world's fastest or most intelligent AI.
