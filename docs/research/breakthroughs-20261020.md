# Breakthroughs: ten new ways to make STAR better, faster and smarter (research, 2026-10-20)

Status: research plus one built first step (idea 1, `star/api_hints.py`, opt-in, offline tests). Written by a Claude
sub-agent for the owner; hosts are "brain 1" (EPYC, 48 threads, 125 GB, the 35B MoE star-fast on CPU), "brain 2"
(i7, 8 cores, Studio machine), "the PC" (RTX 3060 Ti, 8 GB; the 4B apprentice and the night turbo). Nothing here
repeats `docs/research/acceleration-20261018.md` (49 solutions) or `docs/research/multi-model-20261014.md` (15 ideas);
where an idea touches one of theirs the difference is named. Labels: **[measured]** = a number from this repo's own
files or runs, **[estimate]** = my arithmetic, **[source]** = an external paper or page.

## What the anti-slop measurement says (the evidence these ideas start from)

`python -m star.slop` over 416 stored eval answers with pass/fail, 138 verified worked examples and 276 apprentice
answers [measured, docs/agents/anti-slop-20261020.md]:
- 6 % of eval answers are slop by a hard rule; a slop answer fails the task 72 % of the time against 53 % for a clean
  one (apprentice arms: 89 % vs 63 %). Slop is a cheap predictor of failure, available before any test runs.
- The most common slop is an **invented Roblox member** (24 answers; `UIGridLayout.ColumnCount`, `Atmosphere.SunInfluence`,
  `RunService:Create`, `game:GetPlayers()`), and four of those answers PASSED: the lenient compile gate cannot see
  members. 3.6 % of the *verified* worked examples contain a stub, a comment-only function or a "tested, production-ready"
  claim. So the verifier, not the writer, is where quality leaks, and the cheapest fixes are static.
- 49 % of the invented members are on a class the prompt itself names [measured]: the model had the class in front of it
  and still guessed the member. That is a missing-reference problem, not a reasoning problem.

## The ten ideas, ranked by (expected gain x confidence) / cost

| # | Idea | Gain [estimate] | Cost | First step |
|---|---|---|---|---|
| 1 | API-dump member hints in the prompt, then in the repair | -50 % invented members on named classes; +2-4 golden tasks | built (opt-in) | A/B on golden v2 with the paired gate |
| 2 | Lessons compiled into checks (lesson -> forbid/require rule) | lessons that cost 0 prompt tokens and never go "flat" | 1 day | classify the lesson store; compile the "never use X" form |
| 3 | Cheap pass predictor (slop + lint features) to rank best-of-N and order retries | best-of-4 at the cost of ~2 answers | half a day | logistic fit on the 416 + 276 labelled answers, report AUC |
| 4 | Diff-only answers for edit tasks | 2-4x less generation on edits (CPU 10 tok/s is the bottleneck) | 1-2 days | diff grader + applier in eval_checks, measured on ENG-* tasks |
| 5 | Retrieval-based speculative drafts from the exemplar bank (REST / static n-gram cache) | +20-40 % gen speed on code, lossless | 1 day | build the cache from 429 verified examples; `llama-lookup` acceptance rate |
| 6 | Mutant adequacy score for every task's tests | removes "verified" that mean nothing; raises training-data quality | 1 day | 3 mutants per reference answer in the Luau VM, kill rate per task |
| 7 | Grammar-constrained code fences (GBNF) on llama.cpp | kills the "no code block" / unclosed fence failures (~13 % of apprentice fails) | half a day | one grammar, A/B on the apprentice 117 slice |
| 8 | Concise-vs-slop preference pairs from `trim_filler` (DPO, length-controlled) | shorter answers at equal pass rate | 1 PC night | build pairs from stored answers; count |
| 9 | Prompt-prefix bucketing in night school (shared KV prefix per category) | -30 % wall time per attempt on brain 1 | 2 h | sort the pool by prefix hash; measure prompt tokens cached |
| 10 | Expert pruning of star-fast for brain 2 (REAP-style) | a 15-20B Luau brain on the i7 | 1 week + GPU time | expert activation histogram on 200 Luau prompts |

### 1. API-dump member hints: give the model the real names before it guesses (built)
- **Mechanism.** `star/api_hints.py`: the classes a request names (exact spelling, in order, max 6) are looked up in
  the validated local dump (940 classes); their own members (then the superclass chain, stopping at Instance; internal
  and deprecated names dropped; max 40 names, 1,600 chars) become a per-turn reference section after the documentation
  block. Opt-in setting `api_hints_enabled`. Step 2 (not built): when `slop.py` flags an unknown member after the
  answer, the existing repair call gets the same list for *that* class, which covers the other 51 % (classes the model
  chose itself).
- **Why it should work.** Code models hallucinate API members when the API is rare in pre-training; putting the
  documentation of the referenced library in context removes most such errors [source: DocPrompting, Zhou et al.
  2022, arXiv 2207.05987; "API-aware" retrieval in CodeRAG-Bench, Wang et al. 2024]. Here the "documentation" is a
  name list, cheap and exact. 49 % of the invented members were on classes the prompt named [measured].
- **Expected gain.** Invented-member findings on named classes -> near 0; 4 of 416 passes were on invented members
  and would have become real passes; golden v2 +2-4 tasks [estimate].
- **Measure with the gate.** `python -m star.evals run --suite golden-tasks-v2` with the setting on and off, k = 2,
  `star.eval_gate compare_paired`; secondary: C08 count in the result files' new `slop` field (zero cost to read).
- **Smallest first step.** Done: module, tests, opt-in wiring; offline reach measured (hint present for 79 % of the
  416 prompts, median 928 chars). Next: one night on brain 1, both arms.

### 2. Lessons compiled into checks
- **Mechanism.** Night school's lessons are 240-char sentences ("never use wait(); use task.wait()"). Many have the
  shape *never use X* / *always use Y when Z* / *prefer A over B*. A compiler turns those into `forbid`/`require`
  regex checks of the kind `eval_checks.pattern_checks` already runs, attached to the task categories the lesson was
  learned on. The lesson then costs no prompt tokens and is enforced, not suggested; the sentence stays as the
  explanation in the repair prompt when the check fails.
- **Why.** Lessons-in-prompt were flat (24/48 vs 22/48) [measured, acceleration doc B12]; the same knowledge as a
  check is deterministic and composes with the repair loop (execution feedback beats instruction text for small
  models [source: RLEF / "execution feedback" results in AutoIF, arXiv 2406.13542]). The multi-model doc's hint
  distillation moves lessons into weights; this moves them into the verifier, which is cheaper and auditable.
- **Expected gain.** Each compiled lesson adds a hard check for the class of mistake it names; the gate stops passing
  answers that violate it; training rows get cleaner [estimate: a few points on the categories with lessons].
- **Measure.** For each compiled lesson: the paired gate with the check on/off is meaningless (it only removes
  passes), so measure precision: how many stored passing answers it would reject, hand-checked (the anti-slop sample
  method), and the repair pass rate with the explanation in the repair prompt.
- **First step.** Classify the lesson store (`lessons.db` on the servers; `star/lessons.py` has the directive parser
  `_FILLER`/`always|never` forms already) into compilable / not; compile the "never use X" form only.

### 3. A cheap pass predictor to rank candidates and order retries
- **Mechanism.** Features that cost nothing: slop score and rule flags, luau_lint finding counts, block count, prose
  words, code chars, unknown-member count, whether the answer restates the prompt. Fit a logistic model on the 692
  labelled answers (416 eval + 276 apprentice). Use it (a) in best-of-N (`star/best_of_n.py`, #270) to rank candidates
  before the expensive sandbox run and to stop early when the first candidate scores high; (b) in night school to retry
  first the tasks whose failed answer had the lowest predicted pass.
- **Why.** Outcome reward models trained on pass/fail labels pick better samples than majority vote [source: Cobbe et
  al. 2021, "Training verifiers", arXiv 2110.14168; CodeRanker, Inala et al., NeurIPS 2022]. Here the features are symbolic and
  the data already exists; no GPU needed. Slop alone separates 72 % vs 53 % fail [measured].
- **Expected gain.** Best-of-4 quality at the cost of ~2 verified candidates when the predictor's AUC >= 0.7
  [estimate]; retries spent on the tasks most likely to flip.
- **Measure.** AUC on a held-out 30 % of the labelled answers (offline); then best-of-N time and pass rate with and
  without ranking on golden v2 through the paired gate.
- **First step.** A 60-line script over the result files; report AUC and the top features.

### 4. Diff-only answers for edit tasks
- **Mechanism.** For "fix this script" tasks (ENG-*, PERF-*, most Paintball cards) the answer format becomes a unified
  diff or search/replace blocks against the given code; the app applies it and runs the same checks. The grader
  (`eval_checks`) accepts either format; the prompt asks for the diff only when the task supplies the source.
- **Why.** Brain 1 generates at ~10 tok/s; a 120-line fixed script is 1,200+ tokens (two minutes) when the change is
  8 lines. Aider's edit-format benchmarks show diff formats cut output tokens 3-5x with equal or better correctness
  on capable models [source: aider.chat/docs/benchmarks, "edit formats"; SWE-agent uses the same]. The acceleration
  doc speeds edits by n-gram speculation (copying the unchanged text faster); this stops generating it at all.
- **Expected gain.** Edit tasks 2-4x faster on brain 1 and the PC; shorter answers are also less slop [estimate].
  Risk: small models mis-apply diffs (wrong context lines); the search/replace form is more forgiving.
- **Measure.** Seconds per task and pass rate on the ENG/PERF subset of golden v2, both formats, paired gate with a
  pre-registered time bound.
- **First step.** `eval_checks.apply_edit(answer, source)` + tests; score the stored ENG answers' diffs offline.

### 5. Retrieval-based speculative drafts from STAR's own verified examples
- **Mechanism.** llama.cpp's lookup decoding accepts a static n-gram cache (`llama-lookup-create` over a corpus,
  then `--lookup-cache-static`): drafts come from a datastore instead of a draft model. Build the cache from the 429
  verified worked examples + reference answers + the Luau corpus; drafting is a hash lookup on the CPU, verification
  is the batch forward pass the model already does.
- **Why.** REST (retrieval-based speculative decoding) reports 1.6-2.4x on code with a code datastore and no draft
  model [source: He et al. 2023, arXiv 2311.08252]; prompt-lookup decoding gives 2-4x on input-grounded tasks [source:
  Saxena 2023, github.com/apoorvumang/prompt-lookup-decoding]. The model scout measured +29 % with DSpark + ngram-mod
  [measured, model-scout-20261018.md]; the multi-model doc's idea 2 uses only the prompt's n-grams. STAR's answers are
  highly repetitive (`local Players = game:GetService("Players")` ...), exactly what a datastore drafts well.
- **Expected gain.** +20-40 % generation speed on code answers on brain 1, lossless under greedy decoding
  [estimate]; stacks with the DSpark draft head if llama.cpp allows a combined mode.
- **Measure.** RAMForge `specbench.py` (identical text, tokens/s) on 20 golden prompts, cache on/off; then the gate
  (it must be a no-op on quality).
- **First step.** Build the cache file from the exemplar bank offline; report the n-gram overlap between stored
  answers and the cache (the proxy for acceptance) before touching the server.

### 6. Mutant adequacy for every task's tests
- **Mechanism.** For each task with unit tests, generate 3-5 mutants of the reference answer (flip a comparison, swap
  `+`/`-`, drop a branch, return a constant) and run the task's tests in the Luau VM. Kill rate = adequacy. Tasks whose
  tests kill < 60 % get a `weak_tests` mark: their passes are "compiled", not "verified", until the tests are improved
  (the conductor can write the extra tests; it already writes tasks).
- **Why.** 49 of 74 wrong apprentice answers passed a compile-only gate [measured, acceleration doc]; mutation
  score is the standard measure of test strength [source: Jia & Harman 2011, IEEE TSE 37(5)]. The acceleration doc
  (B2) uses mutants to accept *generated* tasks; this audits the existing 541 and ranks the training data by verifier
  strength.
- **Expected gain.** Fewer false "verified" rows in the fine-tune set; the blind set gets a reliability number per task.
- **Measure.** Kill-rate distribution over the pool; re-score the apprentice's 74 wrong answers: how many now fail.
- **First step.** A mutant generator for Luau (token-level, 5 operators) + the VM runner, offline on the 324 verified
  tasks' tests.

### 7. Grammar-constrained code fences
- **Mechanism.** llama.cpp accepts a GBNF grammar per request. A small grammar for "optional prose, then exactly one
  ```luau fence that closes, then optional prose" makes an unclosed or missing code block impossible, at the sampler
  level (no retry). Apply only on routes that require code; never in chat.
- **Why.** 10 of 74 apprentice failures were "no code block"/format [measured]; grammar-constrained decoding
  guarantees syntactic validity at negligible cost [source: Geng et al. 2023, "Grammar-constrained decoding for
  structured NLP tasks", arXiv 2305.13971; llama.cpp grammars/README]. The eval runner's "ask again when the answer
  stops inside a code block" becomes unnecessary.
- **Expected gain.** Format failures -> 0 on the apprentice; a few tasks on star-fast; no extra tokens [estimate].
- **Measure.** Paired gate on the apprentice 117-task slice, grammar on/off; count format failures.
- **First step.** The grammar file + a test that llama.cpp's `gbnf-validator` accepts the stored passing answers.

### 8. Concise-vs-slop preference pairs from the trimmer
- **Mechanism.** `slop.trim_filler` produces, for every stored answer with filler, a shorter twin with identical code.
  (original, trimmed) pairs with the trimmed one preferred are free DPO data; add pairs (slop answer, clean answer) for
  the same task from different attempts. Train the 4B apprentice with length-controlled DPO on the PC.
- **Why.** DPO drifts to longer answers unless length is controlled [source: Park et al. 2024, "Disentangling length
  from quality in DPO", arXiv 2403.19159]; here the preference is explicitly shorter-at-equal-content, which is the
  anti-slop objective. The acceleration doc's KTO/DPO use pass/fail labels, not length.
- **Expected gain.** Shorter answers (fewer tokens = faster on every host) at equal pass rate [estimate].
- **Measure.** Mean answer tokens and pass rate on the blind set, before/after; slop score in the eval report.
- **First step.** Build the pair file from the stored answers; count usable pairs (filler present in 18 + 3 + 2 of the
  measured sets today: small, so add night-school attempts first).

### 9. Prompt-prefix bucketing in night school
- **Mechanism.** Night school tasks in one category share the system prompt, the same skill pack and the same active
  lessons; only the task text differs. Order the batch by the hash of that shared prefix and pin a slot per bucket so
  llama.cpp's prompt cache keeps the prefix; the prompt phase (70 tok/s on brain 1 [measured, acceleration doc B14])
  then costs ~1 s instead of ~20 s per attempt.
- **Why.** Prefix caching is the standard trick for shared-system-prompt batches [source: SGLang RadixAttention,
  Zheng et al. 2023, arXiv 2312.07104]. The multi-model doc's idea 9 caches the *chat's* prefix across resumes; this
  applies the same mechanic to the night batch, where the prefix is identical across dozens of tasks.
- **Expected gain.** A 60-80 s attempt loses 15-20 s of prompt time -> +25-30 % attempts per night on brain 1 [estimate].
- **Measure.** `prompt_tokens` cached vs processed in llama-server's slot stats, attempts/hour before/after.
- **First step.** Sort the pool by (category, pack set) in `pool.py`; log cache hits for one night.

### 10. Expert pruning of star-fast for brain 2
- **Mechanism.** star-fast is a 35B MoE with ~3B active. Measure which experts fire on 200 Luau prompts; prune the
  experts that never fire (REAP keeps the model usable at 25-50 % expert removal [source: Lasby et al. 2025, "REAP the
  experts", arXiv 2510.13999]); the pruned model fits brain 2's RAM and runs the night school there at full speed.
- **Why.** Brain 2 is idle except as a Studio box and a verifier farm; a Luau-specialised pruned brain doubles the
  night's answer capacity without new hardware. Different from the acceleration doc's "use brain 2 for verification":
  this gives brain 2 a model worth running.
- **Expected gain.** +60-100 % night-school answers/hour across the two brains [estimate]; quality loss unknown until
  measured.
- **Measure.** Golden v2 paired gate: pruned vs full on brain 1 first (same machine), then speed on brain 2.
- **First step.** Expert-activation histogram with llama.cpp's `--verbose` expert logging on 200 prompts (brain 1,
  under the quiet lock, 10 min).

## Explicitly not proposed
Anything that needs the Studio runner, new hardware, hosted-model distillation or touching the Team Create place;
and the ideas the two earlier documents already own (best-of-N, cascades, KTO/RFT, evidence pyramid, cloud Luau).

## Sources
- DocPrompting (Zhou et al. 2022): https://arxiv.org/abs/2207.05987 ; CodeRAG-Bench (Wang et al. 2024): https://arxiv.org/abs/2406.14497
- AutoIF, self-play with execution feedback: https://arxiv.org/abs/2406.13542
- Training verifiers (Cobbe et al. 2021): https://arxiv.org/abs/2110.14168 ; CodeRanker, "Fault-Aware Neural Code Rankers" (Inala et al., NeurIPS 2022): https://proceedings.neurips.cc/paper_files/paper/2022/hash/5762c579d09811b7639be2389b3d07be-Abstract.html
- Aider edit formats and benchmarks: https://aider.chat/docs/benchmarks.html
- REST: retrieval-based speculative decoding (He et al. 2023): https://arxiv.org/abs/2311.08252 ; prompt lookup decoding: https://github.com/apoorvumang/prompt-lookup-decoding ; llama.cpp lookup example: https://github.com/ggml-org/llama.cpp/tree/master/examples/lookup
- Mutation testing survey (Jia & Harman 2011): https://doi.org/10.1109/TSE.2010.62
- Grammar-constrained decoding (Geng et al. 2023): https://arxiv.org/abs/2305.13971 ; llama.cpp GBNF: https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
- Disentangling length from quality in DPO (Park et al. 2024): https://arxiv.org/abs/2403.19159
- SGLang / RadixAttention (Zheng et al. 2023): https://arxiv.org/abs/2312.07104
- REAP the experts (Lasby et al. 2025): https://arxiv.org/abs/2510.13999
- Project files: docs/agents/anti-slop-20261020.md (numbers), docs/research/acceleration-20261018.md,
  docs/research/multi-model-20261014.md, docs/agents/model-scout-20261018.md, docs/agents/apprentice-model.md.
