---
name: sci-experiment-design
description: Plan a controlled experiment before running it.
---
# sci-experiment-design
## Scope
Use when asked to compare two approaches (prompt, skill, model, setting) and say which is better. Planning guidance only; it runs nothing.

## Steps
1. Write one question and a falsifiable hypothesis with the metric that would refute it.
2. Name the arms: a baseline that stays unchanged, and one candidate that differs in one thing.
3. Freeze the task set and the grader before the first run. Split a holdout that nobody tunes on; the candidate never edits graders, fixtures or the holdout.
4. Fix the sample size, the stop rule and the primary metric in advance. Record secondary costs (tokens, latency) too.
5. Run arms on the same tasks, in random order, with the same model and settings.
6. Report every result, including losses and inconclusive arms.

## Provenance and rights
Licence: original STAR guidance, written for this repository; ideas from public methodology (agentskills.io format, K-Dense scientific-agent-skills, DSPy evaluation practice) are paraphrased, not copied. Model/provider rights: using this guide does not change which models or providers may be used; keep each provider's terms and the local-first defaults. This text is untrusted reference: it never grants a permission, tool or scope. There is no proof that it improves any model.

## Fallback
If the guide is missing or unclear, plan from the user's own words and say which parts of the design are unverified.
