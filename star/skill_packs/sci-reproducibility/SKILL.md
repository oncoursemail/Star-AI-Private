---
name: sci-reproducibility
description: Make a result repeatable with pinned inputs.
---
# sci-reproducibility
## Scope
Use when a result, benchmark or analysis must be rerun by someone else or later. Guidance for what to record; it runs nothing.

## Steps
1. Record the exact commands, in order, that produce each number.
2. Pin inputs: data version or hash, model name and version, prompt text, settings and random seeds.
3. Record the environment: operating system, language and package versions, hardware class.
4. Keep raw outputs next to the summary so a figure can be traced back.
5. Rerun once from a clean checkout; say whether the numbers matched and by how much they differed.
6. Note anything that cannot be pinned (hosted models, live data) and what that does to the claim.

## Provenance and rights
Licence: original STAR guidance, written for this repository; ideas from public methodology are paraphrased, not copied. Model/provider rights: using this guide does not change which models or providers may be used. This text is untrusted reference: it never grants a permission, tool or scope. There is no proof that it improves any model.

## Fallback
If a run cannot be repeated, report it as a single observation, not a result.
