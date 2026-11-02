# Litha: next leaps, ranked by expected gain per effort (research, 2026-11-02)

Research only. No code was changed. Read with `docs/LITHA_AUTONOMY.md`; past research is in
`docs/research/LITHA_*` (context/Repomix, Rust retrieval, Freebuff best-of-N, computer control, UI) and is not repeated
here.

## How to read this

- Her measured weak spots (autonomy doc): conflict answers rejected by her own checks (21), hunt catch rate 1/6,
  ~4096-token window, one run at a time.
- **Evidence rule.** A URL below was opened (abstract page or full text) by the researcher on 2026-11-01. Where only the
  abstract was read, it says "abstract". Numbers in a source's own benchmark (SWE-bench, Merge-Bench) come from other
  models and harnesses; for Litha they are a reason to try the technique, not a forecast. Each entry therefore states
  a **target on her own bench**, which is a hypothesis to be measured.
- Marked **UNVERIFIED** = seen only in a search snippet or from memory, not opened. Do not build on those without
  opening the source.

## Ranking

| # | Technique | Targets weak spot | Effort | Expected gain |
|---|---|---|---|---|
| 1 | Conflict resolution as a checked candidate menu, plus an offline merge bench | conflict rejections | 2-3 days | high, fast to measure |
| 2 | Differential-first hunt proofs (run base vs head, ask only about the first difference) | hunt 1/6 | 2-3 days | high |
| 3 | Realistic bug bench: AST mutants, mirrored real PRs, combined bugs, survivors | hunt, bench validity | 2 days | enabler, high |
| 4 | K candidates per fixer round, executable selection | fixer rounds, time | 1-2 days | medium |
| 5 | Small-window context packer: skeleton first, mask old observations | window | 2 days | medium |
| 6 | Prompt evolution (GEPA-style) on her own benches, held-out gated | all prompts | 3 days | medium, compounding |
| 7 | Edit-shaped outputs plus prompt-lookup/ngram speculative decoding | serial speed | 1 day + a server check | speed only |
| 8 | Gated self-play adapter training (bug injector + solver, GRPO-style) | everything, slowly | 2+ weeks | uncertain, highest ceiling |

---

## 1. Conflict resolution as a checked candidate menu, plus a merge bench

**What.** Stop asking a 4k-window model to retype a whole merged block as JSON. Build the plausible resolutions with
deterministic code, drop those her existing checks reject, and have the model pick a letter. Only fall back to free
text when no candidate survives. A model that has to emit a one-token choice cannot produce markers, dropped
additions or a mangled escape, which are the causes of her 21 rejections.

**Evidence.**
- Merge-Bench (7,938 real hunks, 1,439 repos, developer's committed resolution as truth; "the best models correctly
  resolve less than 60%"): small dense models are *conservative resolvers* that leave the conflict in place, e.g.
  Qwen3 8B 20.5% unresolved, R1 8B 44.0%, R1 14B 58.4%; the paper trains LLMergeJ (14B, GRPO) which ranks second on Java
  text equality behind Gemini 2.5 Pro. It also notes ConGra's "similarity above 80%" rule can accept wrong code, so a
  parse/equivalence check beats similarity. https://arxiv.org/abs/2605.25890 (abstract + full text read; table text
  was garbled in extraction, so the unresolved percentages above are from a layout-parsed PDF and should be re-read
  before quoting).
- Resolutions repeat: in an empirical study of learned strategies, ~28% of conflicts are 1-2 line changes and a small
  DSL of strategies resolved 11.4% of C++ conflicts (about 41% of the 1-2 line ones) at 93.2% accuracy.
  https://arxiv.org/abs/2103.02004 (abstract).
- MergeBERT recasts resolution as *classification over primitive merge patterns* rather than generation: 63-68%
  accuracy, ~3x semi-structured merge tools. https://arxiv.org/abs/2109.00084 (abstract; the primitive list and their
  coverage are NOT in the abstract, UNVERIFIED).

**Fit.** Her `resolve_text` already has the hard parts (`dropped`, `slips`, `balance`, `broken`, rustfmt/toml/py parse,
`adjacent`, `both_added`). The menu reuses them as a *filter over candidates* instead of feedback to a free-text loop.
It also removes the "too big for her 4096 window" exits because the choice prompt needs only the two sides, not the
retyped output.

**Concrete change** (`litha/pr_fixer.py`):
- New `menu(ours, base, theirs) -> dict[str,str]`: `ours`, `theirs`, `ours+theirs`, `theirs+ours`, a finer 3-way text
  merge (`git merge-file -p --diff3` with `--diff-algorithm=patience`, and a `zdiff3` style retry; the zealous
  variants shrink hunks - UNVERIFIED here, check `git merge-file --help` on her git version), and `adjacent`/`both_added`
  results already computed.
- In `resolve_text`, between the pure-addition shortcut and the 3-try loop: run each candidate through `dropped`,
  `slips`, `balance`, `broken`; if exactly one survives take it; if several, prompt "pick A/B/C" (max_tokens 8,
  `json_mode` off or a one-key JSON); if none, existing loop.
- Optional: split a block into sub-hunks by line-diffing ours vs theirs against base so each sub-question is tiny.
- New `litha/merge_bench.py` (offline, no model needed for the baseline): for every merge commit M in `Star-AI`
  history where `git merge-tree --write-tree P1 P2` reports conflicts, the truth is the file at M. Report per-hunk:
  resolved / kept-conflict / rejected-by-checks / equals-truth (python: `ast.dump` equality; others: whitespace-
  normalised text). Add a `litha/merge_bench.py run --model litha --n 40`.

**Measure.** (a) `python -m litha.merge_bench run --n 40` before/after: share equal to truth, share rejected, mean
prompt tokens. (b) The existing Studio dry run (`python -m litha.pr_fixer --others 8 --dry`; baseline in the doc: 4
resolved, 4 refused). Target (hypothesis): rejections near 0, resolved >= 6/8, zero resolutions that fail the
touched-tests step.

**Cost / risk.** Low compute (fewer, shorter calls). Risk: a menu candidate that passes all syntactic checks but is
semantically wrong (e.g. `ours+theirs` duplicating a statement). Mitigation already in the doc: touched tests must
pass, and the Rust merge runs `cargo test -p`. Keep `.github/` and >5 files with a person.

**Task brief.** In `litha/pr_fixer.py` add `menu()` producing deterministic resolutions of one diff3 conflict block
(ours, theirs, both orders, `git merge-file` finer merge, the existing `adjacent`/`both_added` outputs), filter them with
`dropped`/`slips`/`balance`/`broken`, and change `resolve_text` to take the single survivor or ask her to pick a letter
with an 8-token answer, keeping the old free-text loop as fallback. Add `litha/merge_bench.py` that mines merge commits
from the Star-AI clone using `git merge-tree`, scores any resolver against the committed result, and prints a JSON
summary. Add tests with fabricated diff3 blocks. Record before/after on 40 hunks and on the 8 Studio PRs in
`docs/LITHA_AUTONOMY.md` section 4c.

---

## 2. Differential-first hunt proofs

**What.** Today `bug_proof.prove` asks her to *invent* a pytest test that fails on head and passes on base. That is the
step that fails (one traced miss was a failed proof; another was an invented class). Replace the invention with
execution: generate inputs for the suspect function, run it on base and head, take the first input where the outputs
differ, and ask her one narrow question: "given the PR's stated intent, is this difference intended?" Execution finds
the difference; she only judges intent, a task that fits 4k tokens.

**Evidence.**
- Testora (Pradel; ICSE 2026): LLM-generated tests run on the original and modified code, each behavioural difference
  is classified intended/unintended from the PR title, description and commits; found 19 regressions and 11 PRs that
  fixed a bug by accident on popular Python projects; 13 reported, 11 confirmed, 9 fixed; ~12.3 min and ~$0.003 of LLM
  cost per PR. https://arxiv.org/abs/2503.18597 (abstract; the precision/recall of its classifier is NOT in the
  abstract - a search snippet said 58%/60%, UNVERIFIED).
- Agentic property-based testing (Hypothesis agent over 100 packages): 56% of reports valid, 32% reportable; with a
  scored rubric the top 21 were 86% valid. False positives came from intent ambiguity, implicit preconditions the
  callers enforce, and unclaimed properties; the fix was to require the property to be claimed by docstring, comments or
  callers, and a triage of reproducibility/legitimacy/impact. https://arxiv.org/html/2510.09907v1 (full text read).
  Cost was $5.56 per report with a frontier model, so it does not transfer directly; the *structure* does.
- PBT-Bench (365 injected bugs in 40 libraries, written so default random inputs rarely hit them): a Hypothesis-
  scaffolded prompt lifted mid-capability models by over 20 points (recall range 42.1-83.4% scaffolded vs 31.4-76.7%
  open-ended), the strongest models gained less and two got worse. https://arxiv.org/abs/2605.15229 (abstract).
  That matches her situation (mid-capability model, bugs that need targeted inputs).
- ACH at Meta mutates code toward a specific concern, then generates tests that kill the surviving mutants; an LLM
  equivalent-mutant check had precision 0.79 / recall 0.47, rising to 0.95 / 0.96 with simple preprocessing.
  https://arxiv.org/abs/2501.12862 (seen in a search result only, NOT opened: UNVERIFIED).

**Fit.** This is exactly the "next lever" already written in the autonomy doc section 3b ("run the module's existing
tests on head vs base first and give her the first assert that differs"), extended with generated inputs. She already
has the base/head trees and `python` runner. The PR title/body as "intent" is already passed to `hunt`.

**Concrete change** (`litha/bug_proof.py`, `litha/bug_hunt.py`):
- New `bug_proof.diff_probe(head, base, path, func, python)`: (1) run the module's existing tests on both trees and
  return the first test whose result differs (cheap, no model); (2) otherwise import the function from both trees in a
  subprocess, build inputs from the signature, defaults and the examples in `test_uses` (type-driven Hypothesis
  `@given` strategies for simple types; the model is asked only for 3-5 literal argument tuples as a JSON list), and
  return the first input where return value or raised exception differs.
- `hunt()`: for each function call `diff_probe`; if there is a difference, one prompt: intent + function diff + input
  + both outputs -> `{"intended": bool, "why": str}`. If unintended, the *proof* is the differential itself (frozen
  into `tests/test_litha_found_<n>.py` as an assert on base's output, which the existing fixer hand-off already
  consumes). Keep the current suspect-line path as a fallback.
- Keep the author-intent check: Testora's classifier and the agentic-PBT triage both exist because intended changes
  look like regressions; this is her documented false-hold risk (autonomy doc item 2).

**Measure.** `python -m litha.bug_bench hunt --n 10 --seed 3` (baseline 1/6 caught, 0 wrong-line flags) and the same
with new seeds; false holds with `python -m litha.pr_merger --replay-hunt 20` (baseline 0/7). Report catch, wrong
flags, seconds per function. Target (hypothesis): catch >= 3/6 on the bug-the-tests-catch set, 0 new false holds.
Do item 3 first or together, otherwise the bench keeps measuring bugs CI already blocks.

**Cost / risk.** Mostly CPU (subprocess runs), fewer model tokens than test-writing. Risk: functions with side effects
or heavy imports; run in the throwaway worktrees she already uses, with a timeout, and skip functions that touch the
network or filesystem.

**Task brief.** Implement `diff_probe` in `litha/bug_proof.py` (existing-tests differential first, then argument-tuple
differential), wire it into `bug_hunt.hunt` ahead of the suspect-line path, add an "is this difference intended" prompt
that receives the PR title/body, and freeze a proven difference as a regression test the fixer already picks up.
Unit-test with two fabricated trees (one intended change, one regression). Run `bug_bench hunt --n 10` on seeds 3-5
and `--replay-hunt 20`, then write the three numbers into the autonomy doc section 3b.

---

## 3. A bench that measures the bugs that matter

**What.** Replace line-regex mutants with (a) AST-level procedural mutants, (b) *mirrored real PRs* (revert a merged
PR's source change to get a realistic bug), (c) combined bugs in one file, and (d) *surviving* mutants (tests pass),
which is autonomy-doc items 3 and 9.

**Evidence (SWE-smith).** Four bug sources compared as training data: PR Mirror (invert real PRs) gave the best student,
9.2% resolved; LM Rewrite 8.8%, Procedural 8.6%, LM Modify 5.7% (Qwen2.5-7B-Coder student, 1,000 instances per
strategy). Yield: Procedural 40.2% of attempts valid at $0.00, LM Modify 56.0%, LM Rewrite 35.0% ($3.93 per 1k), PR
Mirror 33.8% ($5.53 per 1k), Combine 96.9% (combining validated bugs of one file/module; 15 failing tests, 11 lines
avg). Procedural mods are 13 AST techniques with criteria filters (e.g. remove a conditional). The full dataset is 50k
instances from 128 repos; the 32B model trained on it reached 40.2% on SWE-bench Verified. https://arxiv.org/abs/2504.21798
(abstract and full text read). LLMorpheus (placeholders in code, LLM proposes three replacements) produced mutants
that resemble real bugs a standard operator set cannot, https://arxiv.org/abs/2404.09952 (abstract; its "~80% of
survivors are non-equivalent" figure was in a search snippet only, UNVERIFIED). Equivalent-mutant filtering: see ACH in
item 2.

**Fit.** `bug_bench.mutate`/`candidates`/`killed` are line regexes (`OPS`), so no multi-line or semantic bugs and no
survivors. Her merged PR history is exactly the PR Mirror source and costs no model calls.

**Concrete change** (`litha/bug_bench.py`):
- `ast_candidates(tree)`: remove a conditional, swallow an exception (`except: pass`), wrong variable (extend
  `wrong_var_edits`), drop an `await`/`return`, swap arguments, off-by-one in slice/range; each a pure AST
  transform with `ast.unparse` limited to the touched function (keep formatting elsewhere).
- `pr_mirror(clone, n)`: for recent merged PRs that touch only `star/*.py`, reverse-apply the source hunks on current
  `star/next` when it applies cleanly; keep it if the touched tests now fail (killed) or pass (survivor).
- New subcommand `bug_bench run --source ast|mirror|line|combine` and `bug_bench hunt --survivors` that reports
  catch rate separately for *killed* and *surviving* mutants, plus a cheap equivalent filter (same AST after
  normalisation, or no covered line changed under coverage) before counting a miss.

**Measure.** The new bench itself: catch/solve per source. Expect lower numbers than 8/8; that is the point. Keep the old
seeds as a regression anchor. Also track "mirror" solve rate over time as the headline number.

**Cost / risk.** No model cost to build. Risk: mirrored PRs that revert feature work (not a bug); keep only those where
tests fail after revert, and tag the rest "feature revert" and exclude.

**Task brief.** Add AST mutants, PR-mirror and combine sources to `litha/bug_bench.py` with a `--source` flag and a
`hunt --survivors` mode that separates killed from surviving mutants and filters trivially equivalent ones. Add unit
tests per mutant kind on small fixtures. Run each source for n=10 and publish baseline numbers (fixer solved, hunt
caught) in the autonomy doc section 3; keep the old line-regex seeds as the anchor.

---

## 4. K candidates per fixer round, selected by execution

**What.** In `repair()` she makes one edit set per round (up to 5 rounds). Sample K (3-4) edit sets in round 1 at
temperature ~0.8 plus one greedy, apply each in a scratch copy, rerun the failing test files, keep the one with fewest
failures (ties: smallest diff). Rounds then continue from the winner.

**Evidence.**
- Agentless on SWE-bench Lite: greedy single location got 29.33% (88) with 40 samples, four separate location sets x 10
  samples 32.00% (96); the "any sample correct" ceiling was 42.0% (126), and performance plateaued around 40
  samples. Selection mattered: majority vote only 25.67%, + regression tests 27.00%, + generated reproduction tests
  32.00%. Cost $0.70 per issue at the time. https://arxiv.org/html/2407.01489v2 (first ~100k characters read).
- Execution alone is a weak selector when many patches pass: R2E-Gym reports test-based verifiers have low
  distinguishability, execution-free verifiers are style-biased, each saturates at ~42-43% on SWE-bench Verified and a
  hybrid reaches 51% (32B model, 34.4% pass@1). https://arxiv.org/abs/2504.07164 (abstract). SWE-Gym (ICML 2025) trained a
  verifier on agent trajectories and reached 32.0% on Verified with inference-time scaling
  (https://arxiv.org/abs/2412.21139, abstract; the 20.6% single-sample baseline was only in a search snippet,
  UNVERIFIED). SWT-Bench: filtering SWE-agent patches with generated tests doubled its precision.
  https://arxiv.org/abs/2406.12952 (abstract).
- Her own measurement is the strongest local evidence: 2 bugs in one PR went from 1/2 to 2/2 with diff + kept progress;
  rounds are already the bottleneck (17-84 s per bug).

**Fit.** The signal she needs is already there: the failing-file rerun is an executable verifier with a clean
count. Her fixer comparison "fewer failures = keep" is a K=1 version. The mesh router sends to GPU nodes first, so K
calls can overlap on more than one node.

**Concrete change** (`litha/pr_fixer.py::repair`): loop `for k in range(K)` over `asker` calls with
different temperature; apply with `apply_edits` in `git stash`-style scratch (worktree copy); run `run_tests`;
score `(failures, diff_lines)`; keep best. Add `--k` and an env override; cap K at 1 when the PR is Rust
(`rust_fix.py` builds are expensive). Use the lint path (`fix_lint`) unchanged. Add a 5th verifier line: run the
touched module's neighbouring passing tests as a regression set (the Agentless "regression tests" step) so a
winner cannot break other tests.

**Measure.** `python -m litha.bug_bench run --n 16 --seed 2 --blind` at K=1 vs K=3: solved, rounds, seconds. Targets
(hypothesis): solved up, mean rounds down; accepted fixes per hour not worse. If it only costs time, keep K=1 (the
doc's "serial runs" weak spot).

**Cost / risk.** K x tokens on round 1. Risk: more time on a single CI runner; do not call it when round 1 already
passes with the greedy sample (stop early after the greedy candidate passes).

**Task brief.** In `repair()` add a `k` parameter: greedy candidate first, return immediately if it clears the failing
files; otherwise sample K-1 more at temperature 0.8, evaluate each in a scratch worktree, pick fewest failures then
smallest diff, and also run neighbouring passing tests as a regression guard. Add `--k` to the CLI. Benchmark K=1 vs K=3
on 16 blind bench items on one fixed seed, and record solved, rounds and wall time in the autonomy doc.

---

## 5. Small-window context packer

**What.** One shared function that fills a ~2,500-token prompt budget in a fixed order: the failing assertion, a
*skeleton* of the relevant files (class/function headers and signatures), the full body only of the few suspect
functions, then masked history for later rounds (old tool/test output replaced by a one-line placeholder).

**Evidence.**
- Agentless: showing the model a file *skeleton* (class and function headers, fields, signatures, comments) instead of the
  whole file kept more ground-truth functions (58.33% vs 53.67%) at lower context (698 vs 778 lines) and cost ($0.02 vs
  $0.15); LLM file choice + embeddings combined contained the right file 81.67% vs 78.67% for prompting alone; repair
  context is a ±10 line window per edit location. https://arxiv.org/html/2407.01489v2.
- JetBrains "Complexity Trap": simple observation masking roughly halves cost vs the raw agent and matches or slightly
  beats LLM summarization on SWE-bench Verified in SWE-agent (five model configurations); a hybrid saves a further 7%
  vs masking and 11% vs summarization. One measurement in the paper (search snippet, UNVERIFIED): observations are
  ~84% of a turn's tokens. https://arxiv.org/abs/2508.21433 (abstract). Study is one agent/one benchmark.

**Fit.** `code_excerpts(budget=9000)` (about 2,500 tokens) and `called_functions` already pack traceback frames and
called definitions; `resolve_text` refuses when `need > WINDOW`. A packer with a skeleton tier and masking lets the same
budget reach more of the right code, and a multi-round repair no longer carries stale logs. Past Litha research
(Freebuff/Repomix) covers *tool* design and caching, not this packing order for 4k.

**Concrete change** (`litha/pr_fixer.py`): `skeleton(source) -> str` using `ast` (headers + docstring first line + body
elided as `...`), new `pack(tiers, budget_tokens)` that takes tiers in priority order and truncates by whole tier;
use it in `repair()` and in `bug_hunt.HUNT` (function + `test_uses` + sibling signatures); in later rounds replace the
previous round's pytest output by "round n: 3 failed -> 1 failed (test_x)". Count tokens with the model's tokenizer if
the router exposes it, otherwise 3.5 chars/token as `WINDOW` does today.

**Measure.** Count of `too big for her ... window` exits in `merge_bench` and in the Studio dry run; blind bench solved
count and rounds at a forced 4096 window; prompt tokens per round (add to `bench.jsonl`).

**Cost / risk.** Low. Risk: a skeleton hides a one-line module constant that matters; keep module-level assignments
referenced by the suspect function.

**Task brief.** Write `skeleton()` and `pack()` in `litha/` (new `litha/context_pack.py`), use them in `repair()` and
the hunt prompt, mask earlier-round pytest output after one round, and log prompt token counts per call into
`bench.jsonl`. Compare solved and rounds on 16 blind items before/after.

---

## 6. Prompt evolution on her own benches (GEPA-style), held-out gated

**What.** Her prompts (`MERGE_PROMPT`, `HUNT`, the repair prompt, the review prompt) are hand-tuned and each carries a
rule that "a measured run needed". Let the system propose prompt edits itself, using the *textual reasons* her checkers
already produce ("dropped what one side added", "the proof imported an invented class") as the reflection signal,
keep a Pareto set of candidates, and promote one only if it beats the incumbent on seeds it never saw.

**Evidence.** GEPA (reflective prompt evolution) reports beating GRPO by about 6% on average (up to 20%) with up to 35x
fewer rollouts and MIPROv2 by over 10% across six tasks; abstract also mentions promising code-optimisation use.
https://arxiv.org/abs/2507.19457 (abstract). Search-snippet detail (UNVERIFIED here): IFBench 38.61% after 678 rollouts vs
GRPO 35.88% after 24,000, GRPO budget fixed at 24k on Qwen3 8B, GEPA not better than GRPO on every task. The larger
framing is AlphaEvolve: an LLM proposes code changes, user-supplied evaluators score them, a diverse program archive is
kept; it needs an automatic evaluator, which her benches are. https://arxiv.org/abs/2506.13131 (abstract; the
reproducibility of its headline claims was not checked).

**Fit.** She has cheap, automatic, trustworthy fitness functions (bench solved count, merge-bench equality, hunt
catch) and no GPU training capacity to spare. Prompt changes are reversible and need no training.

**Concrete change.** Move each prompt to `litha/prompts/<name>.txt` with a version; new `litha/prompt_evolve.py`
nightly step after the bench: take the worst 5 failures of the last run (with checker messages), ask the *best available
model* (mesh) for 3 rewritten prompts, score each on a train seed split, then the survivor on a held-out split, and
write a PR (never an in-place edit) that swaps the prompt only when held-out solved/equality improves by a margin and
nothing regresses on the anchor seeds. The merger's review already protects `litha/`.

**Measure.** Held-out merge-bench equality and bench solved before/after for each promoted prompt; count of promoted
vs rejected candidates per week (overfit check: anchor seeds must not drop).

**Cost / risk.** Each candidate costs a full bench pass (minutes for merge-bench, ~15 min for 10 fixer items), so run
one prompt per night. Risk: overfitting the prompt to the bench; the held-out gate and anchor seeds exist for that.

**Task brief.** Extract the four prompts to files, add `prompt_evolve.py` that produces candidates from the last run's
failures, scores them on separate train and held-out seed sets, and opens a PR only if held-out improves and the anchor
seeds do not regress. Start with `MERGE_PROMPT` on the merge bench from item 1 (fastest loop). Log every candidate to
`~/.star/litha/prompt-evolve.jsonl`.

---

## 7. Edit-shaped outputs and speculative/ngram decoding

**What.** Her answers mostly *copy the input* (a resolved block, a search/replace edit). Two cheap speed levers: ask for
the smallest output that identifies the change (search/replace or a line range instead of re-typing the block), and
turn on prompt-lookup (ngram) speculative decoding in the server that hosts `litha`, which drafts tokens by matching
n-grams already in the prompt.

**Evidence.** Prompt Lookup Decoding: 2x-4x on input-grounded tasks, about 2.4x on summarisation and context QA, no change
in greedy output (Mistral-7B-Instruct, one A100; coding gained most on one chat turn). It is built into HF transformers
as `prompt_lookup_num_tokens=10`; the README does not mention llama.cpp.
https://github.com/apoorvumang/prompt-lookup-decoding (README read). A 2026 code-repair paper (QiMeng-PRepair) uses
"speculative edits" and reports increased throughput and precision gains from edit-aware RL, with no multiplier in the
abstract. https://arxiv.org/abs/2604.05963 (abstract). Agentless chose search/replace edits for fewer tokens and fewer
hallucinations, without a quantified comparison in the paper. https://arxiv.org/html/2407.01489v2.
**Whether the llama.cpp version her mesh nodes run exposes ngram/lookup speculative decoding in `llama-server` is
UNVERIFIED**; a search snippet only showed an `examples/lookup` program and an open server PR.

**Fit.** Serial runs are a stated weak spot. Her fixer edits are already search/replace; the merge and hunt outputs are not.

**Concrete change.** (a) First check the server: on each mesh node run `llama-server --help` and look for lookup/ngram
speculative flags and `-np` parallel slots. (b) In `pr_fixer.resolve_text` return `{"keep": "ours|theirs|both|edit",
"edit": [{"find": "...", "replace": "..."}]}` - this is the output shape item 1 uses. (c) Log `tokens/s` per call
in `bug_bench`.

**Measure.** Wall-clock per bench item and tokens/s before/after, identical outputs under greedy decoding (a free
correctness check).

**Cost / risk.** Near zero for (b); (a) depends on the server build. Gain is speed, not accuracy.

**Task brief.** Inspect the model server flags on each mesh node and report which of ngram/lookup speculative decoding
and parallel slots exist; if available enable them for the `litha` route and record tokens/s and per-item seconds on
the 10-item bench before and after, checking that greedy outputs are byte-identical. Switch the conflict prompt output
to the edit shape in item 1.

---

## 8. Gated self-play adapter training (long-horizon)

**What.** The bench already generates verified (bug, failing tests, fix) triples nightly into `bank-litha-fixes.jsonl`.
Close the loop: train a small LoRA/adapter on the verified pairs, and let it also learn to *inject* harder bugs from
its own failed repairs; deploy only when the bench says it is better.

**Evidence.**
- Self-play SWE-RL (Meta FAIR and collaborators): one model plays bug injector and solver, bugs specified by test
  patches, higher-order bugs from failed repair attempts; +10.4 points on SWE-bench Verified and +7.8 on SWE-Bench Pro
  over its base; injection-only and repair-only variants were significantly worse. https://arxiv.org/abs/2512.18552
  (abstract; model size not in the abstract).
- SWE-smith: 5,105 expert trajectories -> a 32B student 40.2% on Verified; training data from procedural bugs was as
  good as LM-written ones (item 3). https://arxiv.org/abs/2504.21798.
- Merge-Bench: GRPO with a test-free equality reward taught a 14B model to commit to a resolution instead of leaving
  conflict markers (19.2% unresolved vs 58.4% for the base R1-distilled 14B in their table); the paper argues SFT on the committed
  resolution is a poor fit because many valid resolutions differ in syntax (its SFT-vs-GRPO table was unreadable in
  extraction, so the size of the gap is UNVERIFIED). https://arxiv.org/abs/2605.25890 (full text
  read; table values from a layout-parsed PDF, re-check before quoting).
- Small models do respond to in-domain data: an 8B model rose from 8.0 to 38.2 on Verified after SFT
  (Klear-AgentForge, search snippet only, UNVERIFIED).

**Fit and caution.** This is the autonomy doc's item 5 ("gate the nightly adapter on the bench") plus training she does
not yet do on this data. It needs GPU time on a PC that also serves her, and a reward that cannot be hacked: the doc
rule "never edit tests to make them pass" must hold in the reward (hidden tests, tests read-only).

**Concrete change.** Phase A (a day): implement the gate - `bug_bench run --n 10 --seed <held-out>` against the
candidate adapter must not solve fewer than the incumbent, before `auto_deploy`. Phase B: build a verifiable-reward
dataset from bench + merge-bench + mirrored PRs, train with a rejection-sampling SFT first (cheaper, safer) and GRPO
later if there is GPU headroom.

**Measure.** Held-out seeds solved (fixer), catch (hunt), equality (merge bench), and the game-building nightly gate the
adapter already faces.

**Cost / risk.** Highest. GPU time, regression risk on non-code skills, reward hacking. Gate hard; do items 1-6 first.

**Task brief.** Implement the bench gate in the nightly deploy path (serve the candidate adapter, run the held-out bench
and the merge bench, compare to the incumbent's last stored score, refuse deploy on any drop) and write the verified
triples with a `source` and `seed` field so a later training job can split train/held-out without leakage. Training
itself is a separate task after the gate has run a week.

---

## Considered and not ranked

- **Whole-agent frameworks (OpenHands, SWE-agent, Aider as runtimes).** Past Litha research already covers context,
  condensation, repo maps and best-of-N (Freebuff and Repomix documents). Her harness is deliberately non-agentic and
  executable-verified, the same design family as Agentless; swapping frameworks would add tokens a 4k window cannot
  afford.
- **LLM-judge ranking of candidates.** R2E-Gym found execution-free verifiers biased toward stylistic features (item 4);
  use only as a tiebreak after executable checks.
- **Fault localisation with coverage (LLM4FL, 675 Defects4J faults, +18.55% Top-1 over AutoFL).**
  https://arxiv.org/abs/2409.13642 (abstract). Java/Defects4J, and her fixer already gets traceback frames; the
  coverage idea is folded into item 2's "which tests differ" probe.
- **Not researched (state honestly):** SWE-bench Live specifically, mutation tools for Rust, AlphaEvolve-style search
  over *code* rather than prompts, and retrieval embeddings (covered by the Rust retrieval note).

## Sources opened (2026-11-01)

Abstract pages: 2605.25890, 2510.09907, 2605.15229, 2407.01489, 2504.21798, 2503.18597, 2507.19457, 2512.18552,
2504.07164, 2412.21139, 2109.00084, 2409.13642, 2404.09952, 2506.13131, 2604.14820, 2508.21433, 2604.05963,
2406.12952, 2103.02004.
Full text read: Agentless (html v2, first 100k characters), SWE-smith (PDF), Merge-Bench (PDF), agentic PBT (html v1),
Prompt Lookup Decoding README.
Seen only in search snippets (UNVERIFIED): ACH/Meta 2501.12862 numbers, SWE-TRACE 71.2% on Verified, Qwen3-Coder-Next 70.6%, Klear-AgentForge
8.0 -> 38.2, SWE-Fixer 32.8%/24.7%, Testora precision/recall, LLMorpheus 80% non-equivalent survivors, llama.cpp
lookup server support, `git merge-file` zdiff3 behaviour.
