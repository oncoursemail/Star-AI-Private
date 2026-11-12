# STAR: Cluster Coverage, Honest Acceptance Gates, and the Next Capability Stack

**Research date:** 2026-11-12  
**Implementation branch:** `feat/cluster-coverage-guardrails-20261112-auto11`  
**Parent:** draft PR #1147

## Executive finding

The parent turn-taking evaluator correctly recognizes that pauses from one conversation are correlated and resamples complete sessions. Its own validation plan explicitly requires simulation-based coverage checks before relying on the nominal cluster-bootstrap bounds.

A bounded beta-binomial Monte Carlo study found substantial under-coverage for the percentile cluster-bootstrap upper bound in the tested small/medium-cluster scenarios. The result is not evidence about STAR's real microphone data; it is a warning that a nominal 95% percentile bound must not automatically be treated as a 95% acceptance guarantee.

This change therefore makes the cluster bootstrap diagnostic-only for acceptance and adds a distribution-free, weighted Hoeffding upper bound over independent session-level rates. It also measures the proportion of sessions whose per-session p95 latency exceeds the configured limit. The new bound is deliberately conservative: at 95% confidence and a 5% rate budget, 600 equal-weight independent sessions (or 600 effective sessions after size weighting) are needed when no events are observed.

The runtime remains usable. This stricter rule affects only whether an offline evaluation may report PASS; insufficient evidence returns INCONCLUSIVE rather than silently lowering the confidence standard.

## 1. Statistical model and simulation

### Beta-binomial session model

For each synthetic session:

1. Draw a session-specific event probability (p_i) from a Beta distribution.
2. Draw the session's pause outcomes conditional on (p_i).
3. Vary session sizes independently of (p_i), using either equal sizes or a fixed unequal-size pattern.
4. Resample complete sessions with replacement to calculate the percentile cluster-bootstrap upper bound.
5. Calculate the weighted Hoeffding bound over the same independent session-level rates.

For a beta-binomial model with concentration (kappa=alpha+eta), the within-session intraclass correlation is (1/(kappa+1)). The scenario mean event rate is (alpha/(alpha+eta)).

The simulation compares three separate estimands:

- **Pooled pause error rate:** total errors divided by total pause opportunities.
- **Session incidence:** fraction of sessions with at least one event.
- **Latency violation incidence:** fraction of sessions whose own p95 endpointing latency exceeds the predeclared latency limit.

These are not interchangeable metrics.

### Exploratory Monte Carlo results

A separate local Monte Carlo prototype ran 1,000 synthetic datasets per scenario and 400 whole-session bootstrap draws per dataset. Mean event rate was 5%; the four scenarios varied session count, session-size imbalance and intracluster correlation. The table reports the one-sided 95% upper-bound coverage and a 95% Wilson interval for the Monte Carlo coverage estimate.

| Sessions | Sizes | ICC | Percentile cluster-bootstrap coverage | Weighted Hoeffding coverage |
|---:|---|---:|---:|---:|
| 20 | Equal | 0.20 | 84.6% (82.2–86.7%) | 100.0% (99.6–100%) |
| 20 | Unequal | 0.50 | 67.9% (64.9–70.7%) | 100.0% (99.6–100%) |
| 50 | Equal | 0.20 | 89.3% (87.2–91.1%) | 100.0% (99.6–100%) |
| 50 | Unequal | 0.50 | 76.8% (74.1–79.3%) | 100.0% (99.6–100%) |

The session-incidence Hoeffding guard also covered its known synthetic mean in all four 1,000-run scenarios. The 100% empirical result is not a mathematical proof; the Monte Carlo interval still has finite width.

**Interpretation:** in these synthetic conditions, the percentile cluster bootstrap did not achieve its nominal 95% one-sided coverage. The weighted Hoeffding bound was conservative and covered the target in every simulated replicate. The simulation does not prove that the beta-binomial model matches real conversation data, so the benchmark remains an exploratory diagnostic, not a substitute for licensed real-session validation.

### Reproducible benchmark

The committed standard-library-only benchmark is:

`benchmarks/stream_cluster_coverage.py`

Run it from the repository root:

```bash
python -m benchmarks.stream_cluster_coverage --replicates 1000 --bootstrap-replicates 400 --seed 20261112
```

It prints JSON with scenario manifests, coverage proportions, Monte Carlo intervals and the mean bootstrap upper-bound margin. It caps total resample draws at 50 million per scenario. The committed script has focused deterministic and input-bound tests; the 1,000-by-400 study above was run with an independent local prototype using the same beta-binomial and bound formulas, not against STAR audio.

## 2. Acceptance guardrails added

### Weighted Hoeffding bound

For session (i), let (r_iin[0,1]) be its error rate and (w_i) its share of all opportunities. With independent sessions and fixed observed weights:

[
hat R=sum_i w_i r_i,qquad
K_{eff}=rac{1}{sum_i w_i^2}
]

[
U=minleft(1,hat R+sqrt{rac{ln(1/alpha)}{2}sum_i w_i^2}ight)
]

The bound does not assume independence between pauses within one session. Unequal session sizes reduce the effective session count.

### Session-level incidence and latency

The evaluator also applies Hoeffding's bound to independent 0/1 session outcomes:

- a session had one or more false cutoffs;
- a session had one or more missed final turns;
- a session's p95 endpointing latency exceeded the configured limit.

The last measure avoids treating a bootstrap interval for the *mean of session p95 values* as though it were a confidence interval for the global p95.

### Required evidence

For an equal-weight zero-event sample, the Hoeffding upper bound is:

[
U=sqrt{rac{ln(1/alpha)}{2K}}
]

At 95% confidence:

- 5% maximum rate: 600 independent/effective sessions;
- 10% maximum rate: 150 independent/effective sessions;
- 0% maximum rate: cannot be established from a finite sample.

For unequal pause counts, use (K_{eff}), not the raw session count, for the weighted pause-rate guard.

This is intentionally stricter than the earlier approximate Wilson zero-event threshold of 52 sessions. The Wilson calculation remains available as a diagnostic; it no longer authorizes a cluster-aware PASS.

### Decision semantics

- **PASS:** all predeclared weighted-rate, session-incidence and latency-violation Hoeffding bounds meet their budgets, the effective sample requirements are met, and the observed global p95 remains within its limit.
- **FAIL:** an observed point estimate exceeds a predeclared budget, or sufficient evidence exists and a conservative bound fails.
- **INCONCLUSIVE_HOLDOUT:** the sample/effective-session count is insufficient to establish the required bound.

Cluster-bootstrap intervals remain available for diagnosis and comparison, but they are not used as the acceptance proof until their coverage is calibrated for the relevant session-size and correlation envelope.

## 3. Research applied to STAR's wider capabilities

### Natural multiparty streaming

LiveKit's end-of-turn benchmark evaluates causal pause decisions across multiple languages and makes the false-cutoff/latency tradeoff explicit. STAR should keep end-of-turn, barge-in, backchannel recognition, direct-address detection and multiparty floor control as separate metrics.

Source: https://github.com/livekit/agents/tree/main/livekit-plugins/livekit-plugins-turn-detector

### Game-playing intelligence

GameWorld provides 34 browser games and 170 tasks with deterministic, state-verifiable outcomes. It distinguishes paused reasoning from real-time interaction, which is directly relevant to STAR's reactive-versus-strategic game loops.

Source: https://gameworld-project.github.io/  
Code: https://github.com/gameworld-project/GameWorld  
Paper: https://arxiv.org/abs/2604.07429

For STAR Gamer, use state-based success/progress receipts when the environment exposes them. Keep real-time and paused tracks separate; latency can change gameplay success.

### Continual skill learning

SkillLearnBench evaluates skill quality, execution trajectory and task outcome across 20 tasks and 100 instances. Its findings caution that self-feedback alone can drift and that repeated external feedback matters.

Source: https://cxcscmu.github.io/SkillLearnBench/  
Paper: https://arxiv.org/abs/2604.20087

For STAR's skill library, evaluate all three levels:

1. Is the skill artifact correct, scoped and safe?
2. Did the agent execute the skill's intended steps?
3. Did the environment/task outcome improve on unseen instances?

Skill usage frequency is not evidence of skill utility. Keep versioned skills, preconditions, environment/version scope, failure modes, external execution receipts and held-out transfer tests.

### Game creation

GameDevBench contains 333 Godot tasks spanning 2D graphics/animation, 3D graphics/animation, UI and gameplay. The paper reports that visual feedback improved one evaluated configuration from 41.1% to 52.0%.

Sources:
- https://github.com/waynchi/gamedevbench
- https://proceedings.mlr.press/v306/chi26a.html

For STAR Creator, a successful code edit is not a successful game task. Require engine launch, runtime assertions, screenshots/video comparison and playtest evidence in an isolated project.

### Local inference speed

llama.cpp's optional Prometheus `/metrics` endpoint exposes prompt/decode counters, throughput gauges, processing/deferred requests and speculative-decoding counters. STAR should keep these server metrics separate from client-visible first-content, inter-token and first-audible latency.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

Do not enable metrics or change server flags automatically. The owner-controlled host adapter should read metrics only when the local server is explicitly configured for it.

### Small-cluster alternatives

MacKinnon (2014) studies wild cluster bootstrap confidence intervals and reports that some procedures perform well with small cluster counts. That work concerns cluster-robust regression inference; it is not a drop-in replacement for STAR's binary weighted-rate estimator. A future alternative should be derived for the exact estimand and validated by simulation before replacing the conservative bound.

Source: https://ageconsearch.umn.edu/record/274655

## 4. Next integration steps

The repository already has substantial draft work for trace timing, rehearsal recording, llama.cpp telemetry, cross-session gameplay continuity, general-skill retrieval, creator evaluation and multiparty voice. The next milestone should integrate those systems with trusted Windows host observations rather than create another isolated evaluator.

1. Collect per-stage audio/device timestamps, VAD/ASR/LLM/TTS timing, first audible playback and avatar synchronization.
2. Collect OBS render and output skips separately.
3. Collect game frame-time p50/p95/p99 and control-action freshness.
4. Collect CPU, RAM, GPU and VRAM measurements with source timestamps and staleness checks.
5. Run matched local inference experiments with identical model, prompt, slot count, context and mixed workload.
6. Feed aggregate receipts into the existing rehearsal and model-quality gates.
7. Keep the fast reactive game controller separate from strategic reasoning and skill retrieval.
8. Require environment-state evidence for gameplay and engine evidence for game creation.
9. Keep raw viewer audio/transcripts out of persistent memory by default; store only approved, bounded, aggregate or owner-approved skill evidence.

## 5. Scope and validation boundary

This PR changes offline evaluation only. It does not capture audio, call models, alter model routing, enable telemetry, control OBS/VTube Studio, send game input, modify weights, publish Roblox content or change production defaults.

The synthetic Monte Carlo results are not measurements of STAR's real conversations. The committed benchmark is the reproducible artifact; the independent 1,000-by-400 prototype results are exploratory evidence and should be rerun with the committed script before publication as a formal result.

No measured inference speedup, increased model intelligence, game mastery, naturalness gain or production readiness is claimed. The Windows host adapter and private mixed-workload rehearsal remain outstanding.
