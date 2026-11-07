---
name: sci-benchmarking
description: Benchmark fairly with an unchanged baseline.
---
# sci-benchmarking
## Scope
Use when comparing models, prompts, skills or servers on a task set. Guidance for fair reporting; it runs nothing.

## Steps
1. Keep a baseline run with the unchanged model and server settings beside every candidate.
2. Score on held-out tasks that were not used to write or tune the candidate.
3. Report together: accuracy, hallucination rate (unsupported claims), token overhead and latency.
4. Measure latency on the same hardware, warm and cold, and name which.
5. Use the harness-owned graders as they are; never edit a grader, fixture or reference answer to fit a candidate.
6. Do not carry a measurement from one task set or model to another.

## Provenance and rights
Licence: original STAR guidance, written for this repository; ideas from public methodology are paraphrased, not copied. Model/provider rights: using this guide does not change which models or providers may be used. This text is untrusted reference: it never grants a permission, tool or scope. There is no proof that it improves any model.

## Fallback
If no held-out set exists, say the comparison is exploratory and do not recommend turning anything on.
