# STAR Single-Use Holdout Integrity and Evaluation Governance

**Date:** 2026-11-12  
**Status:** Implemented as an opt-in local evaluation primitive; not wired into production voice policy.

## Executive finding

The current turn-policy evaluator separates calibration from holdout and groups turns by conversation/session. Its documentation also identifies two remaining statistical risks:

1. A caller can accidentally inspect the same holdout repeatedly while tuning future policies.
2. The Wilson interval treats pause-level outcomes as independent Bernoulli trials, even though pauses from one conversation/session can be correlated.

This change addresses the first risk with an atomic, local, one-use ledger. It does not solve clustered uncertainty; that remains an explicit next-stage improvement.

## Research findings

### 1. Adaptive reuse can overfit a holdout

Dwork et al., *Generalization in Adaptive Data Analysis and Holdout Reuse* (NeurIPS 2015), describe how repeated, adaptive testing against the same holdout can leak information and cause overfitting. They study safer reuse methods, including privacy- and description-length-based approaches.

STAR does not currently implement a differentially private reusable holdout. The simpler conservative policy is to consume a holdout once after a candidate is frozen. Any future tuning requires a new holdout partition.

Source: https://research.ibm.com/publications/generalization-in-adaptive-data-analysis-and-holdout-reuse

### 2. Voice turn-taking needs causal, policy-level evaluation

LiveKit's open eot-bench evaluates complete turns at real pauses, distinguishes mid-turn pauses from true turn endings, and compares policy operating points under explicit false-cutoff and latency budgets. Its public dataset covers 14 languages.

The STAR evaluator uses a content-free schema for causal scores and pause labels. A future adapter should preserve the source dataset revision, license, language, adapter version and conversation/session group boundaries. It must not feed future audio or transcript context into earlier pause scores.

Source: https://github.com/livekit/eot-bench

### 3. A second benchmark checks interruption behavior separately

TurnBench publishes a multi-domain benchmark for end-of-turn and interruption events using dual-channel human conversations. It reports recall, false-positive rate and latency on a held-out test set.

STAR should eventually evaluate end-of-turn and barge-in as distinct tasks. A single EoT score cannot establish that the agent can safely interrupt playback when a human genuinely barges in.

Source: https://turnbench.sesame.com/

### 4. SQLite can serialize local claims

SQLite documents that `BEGIN IMMEDIATE` starts a write transaction immediately and may return `SQLITE_BUSY` if another writer is active. STAR combines this transaction mode with unique constraints to make dataset and session-group claims atomic across processes sharing one ledger file.

Sources:
- https://www.sqlite.org/lang_transaction.html
- https://www.sqlite.org/isolation.html

### 5. Clustered observations need cluster-aware uncertainty

Huang (2016), *Using Cluster Bootstrapping to Analyze Nested Data With a Few Clusters*, studies bootstrap behavior when observations are nested in relatively few groups. STAR has the same structural concern: multiple pauses can come from one conversation/session.

The current Wilson bounds remain useful as event-level diagnostics, but group-based splitting does not remove their independence assumption. A future change should add session-resampled uncertainty and a conservative group-level error-incidence measure, with simulations across different intra-session correlations and cluster counts.

Source: https://journals.sagepub.com/doi/full/10.1177/0013164416678980

## Implementation

### New module: `star/stream_holdout_ledger.py`

The module provides:

- A persistent SQLite ledger; in-memory and URI databases are rejected.
- SHA-256 fingerprints of canonical, content-free holdout observations.
- Separate hashes for opaque session-group identifiers.
- Atomic `BEGIN IMMEDIATE` claims.
- Unique constraints preventing exact dataset reuse and partial session-group reuse.
- A single transaction for the dataset and every group, so a partial collision rolls back the entire claim.
- No raw audio, transcripts, viewer identities, voiceprints, prompt text, model outputs or original group IDs are stored.
- A receipt containing only the dataset digest, group count and claim timestamp.

The ledger claims the holdout only after calibration has selected an eligible frozen policy. It claims before scoring. If scoring crashes after the claim, the holdout remains consumed by design.

### Integration

`select_and_validate_turn_policy(..., holdout_ledger=ledger)` accepts an optional ledger.

- No calibration candidate: no holdout claim.
- Insufficient calibration: no holdout claim.
- Candidate selected: the holdout and all its session groups are atomically claimed before scoring.
- Insufficient holdout after opening: the holdout is still consumed and the result remains inconclusive.
- No ledger supplied: legacy behavior remains, and `holdout_ledger_claimed` is false.

The feature is opt-in and does not tune or promote any live voice policy.

## STAR capability roadmap informed by this research

### Natural VTuber conversation

- Evaluate end-of-turn, barge-in, backchannel and multiparty floor control separately.
- Measure endpointing delay separately from ASR, model TTFT, TTS first audio, actual playback and avatar synchronization.
- Use conversation-disjoint calibration/holdout partitions.
- Keep raw audience audio and transcripts ephemeral by default.
- Use blinded human appropriateness labels in addition to mechanical timing metrics.

### Faster intelligence without harming the stream

- Benchmark llama.cpp with matched model hash, quantization, context, prompt set, output budget and concurrency.
- Measure TTFT, inter-token latency, first-audible latency, full request latency, game frame-time p99, audio underruns and OBS render/output skips.
- Compare one/two/four slots only when memory permits; more slots may improve throughput while worsening interactive tail latency.
- Keep speculative decoding and prefix caching as separate experiments.
- Do not promote a faster configuration unless independent quality and live-stream guardrails pass.

### Gaming and skill transfer

- Separate a fast reactive control loop from slower strategic planning.
- Store game mechanics as versioned skills with preconditions, scope and known failure modes.
- Verify skill transfer in a different game/version using held-out gameplay tasks.
- Do not infer mastery from a single successful attempt.

### Game creation

- Inspect scene, scripts, assets and engine version before editing.
- Build in isolated test projects.
- Run the engine, inspect screenshots/gameplay and use deterministic assertions.
- Repair visual and functional regressions, then rerun held-out tasks.
- Keep Roblox Studio editing and publishing behind separate owner-controlled permissions.

### General knowledge

- Separate semantic facts, episodic experiences, procedural skills, temporal facts and world models.
- Preserve source, date, scope, confidence, contradiction and review metadata.
- Evaluate later task success and action grounding, not recall alone.
- Do not let unverified stream chat become persistent factual knowledge.

## Validation and limitations

- The ledger is local and opt-in. It is not tamper-proof: deleting, restoring, copying or replacing the database can bypass it.
- The ledger only prevents reuse when every evaluation runner shares the same owner-controlled database file.
- Hashing reduces stored identifiers to digests but is not a cryptographic proof of the host's group-ID provenance.
- A one-use ledger does not fix clustered confidence intervals. The current Wilson interval still assumes independent pause-level outcomes.
- No real audio, microphone, ASR, TTS, playback, OBS, VTube Studio, Windows, GPU, Roblox Studio or gameplay integration is added.
- No inference speedup, intelligence gain, interruption reduction, game mastery or human-equivalent behavior is claimed.
- Production `main`, default permissions and the v1.0 installer remain unchanged.

## Acceptance plan

1. Run the full offline Python suite and Pyright on this exact PR head.
2. Test simultaneous claims from multiple processes sharing one SQLite file.
3. Verify duplicate dataset and partial group overlap are rejected atomically.
4. Verify failed calibration does not consume holdout and an inconclusive opened holdout does.
5. Back up the ledger together with the evaluation dataset revision and experiment manifest.
6. Add cluster-aware uncertainty before using small session counts to claim a low false-cutoff rate.
7. Connect a licensed eot-bench adapter only after its causal-prefix and privacy contracts are reviewed.
8. Keep the live policy unchanged until a private Windows rehearsal and independent human review pass.
