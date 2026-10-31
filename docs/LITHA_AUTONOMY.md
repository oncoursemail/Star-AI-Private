# Litha autonomy: she fixes, reviews, merges, promotes and learns (handoff for Litha or any AI)

Owner's goal (2026-10-31): Litha merges and finishes PRs herself, finds and fixes her own mistakes, gets better every
day, and takes changes all the way to `main`, with no one else needed. This file is the map: what exists, how each
part decides, how it is measured, what is NOT done yet, and the next steps in order. Read it fully before changing
anything here; every rule below exists because a measured run needed it.

## 1. The pieces (all in `star/`, tests in `tests/`)

| File | Job | Runs |
|---|---|---|
| `pr_fixer.py` | failing PR -> CI log -> her edits -> failing test files pass locally -> her own branch + PR | task "Litha PR merger", every 30 min, 1 PR per run |
| `pr_merger.py` | open PRs into `star/next`: hard gates, her review, proofs, merge | same task, after the fixer |
| `bug_proof.py` | a blocking claim must be shown by a test that fails after the PR and passes before it | called by the merger |
| `bug_hunt.py` | last look before a merge: she reads each changed function alone and names a bug; kept only if `bug_proof` proves it | called by the merger |
| `pr_promote.py` | `star/next` -> `main` (auto-publishes a release) only with all release receipts | same task, last |
| `release_receipt.py` | runs a release check and writes its receipt | by whoever runs acceptance / install |
| `bug_bench.py` | plants real bugs in the real repo, she fixes them, lessons + training pairs + score history | task "Litha bug bench", 03:10 daily |

Scheduled script: `server/pr_merger_run.cmd` (fixer -> merger -> promote) and `server/bug_bench_run.cmd`.
Off switches: `%USERPROFILE%\.star\pr-merger\OFF`, `%USERPROFILE%\.star\litha\OFF`.
Logs: `~/.star/pr-merger/{run.log,decisions.jsonl}`, `~/.star/pr-fixer/{fixes.jsonl,tried.json}`,
`~/.star/litha/{bench.jsonl,bench.log,lessons.json,sft/pr-fix.jsonl}`, receipts `~/.star/release/<sha>/`.
Model: `litha` through the mesh router (`star.asset3d.llm.chat`, GPU nodes first). The model is swapped in ONE place
per module (`ask` / `ask_litha`).

## 2. How each part decides (and why)

**Merger** (`decide()`): merge only if ALL hold.
1. Hard gates (facts, no model): base is `star/next` (never `main` here), not a draft, GitHub `MERGEABLE` + `CLEAN`,
   every check on the exact head completed and passed, at least one succeeded, no forbidden file (locks, keys,
   models, `.env`), no added line with a private address / key / token (version pins like `==10.3.10.19` are not  <!-- star:allow -->
   addresses). Merge uses `--match-head-commit`, so a head that moved is never merged blind.
2. Her review of the diff (chunks of 12k chars): every risk must name a `+` line of the diff, else dropped.
3. Each high risk is checked against the real file: "undefined name" claims are refuted when the name is
   defined/imported; "syntax" claims when the file compiles; "the diff is cut off" claims always; "could / might"
   claims become notes. A remaining claim must be re-proven by her quoting an exact line from the real file.
4. Then `bug_proof.prove()`: she writes one pytest test; it must FAIL on an assert on the PR's code AND PASS on the
   code before the PR (`origin/star/next`). Safety claims (secrets, injection, deletion, leaks) stay blocking without
   a test. Unproven claims do not block.
5. Before a merge the review allowed, `hunt_pr()` runs `bug_hunt.hunt()` on every changed function (max 6) with the
   PR's title and body as the author's intent ("a change the author says they meant is not a bug"). A find that is
   PROVEN (fails on the PR, passes on `star/next`) holds the PR with reason `hunt: ...`.
Why: measured on 6 merged PRs, her raw review held 4 good PRs on invented problems (2/6 agreement); with step 3,
5/6. A self-written test "proved" a false claim until the before-PR comparison was added.

**Fixer** (`fix()` + `repair()`): pytest failures from the failed job log (fetched with
`gh api --allow-escape-sequences`, colour codes and timestamps stripped) -> checkout `pull/<n>/head` on
`litha/fix-<n>-<date>` in `worktrees/litha-fix-<n>` -> up to 5 rounds: prompt = failures + local run + the PR's
source diff (prime suspect) + real code of traceback frames + whole definitions of functions the test calls + her
lessons -> search/replace edits (must match exactly once; `tests/`, `.github/`, locks refused: the tests are the
spec) -> the failing test FILES rerun. Fewer failures = edits kept; otherwise back to the kept state. Success ->
`star commit` (secret checks) -> push HER branch (never the author's, never force) -> PR into `star/next` + comment
on the original. Expired / unreadable logs -> `gh run rerun --failed` (one per run: there is one CI runner).
Blind (no diff): the first failing test is rerun with `--tb=long -l` so she sees the wrong VALUES.
Lint: CI runs `ruff check star` before pytest, so a lint failure shows no pytest output. `fix_lint()` runs ruff's
safe autofixes, then up to 5 rounds of her edits (a round that does not lower the error count is undone).

**Promotion** (`pr_promote.py`): merges the open `star/next -> main` PR only when, for the exact head: every check
passed incl. a Windows build; receipts `acceptance.json` and `install.json` say ok for that sha; `notes.md` exists;
no open proven high-risk hold. These are the ledger's release checks (owner OK 2026-10-13). Receipts come from
`python -m star.release_receipt acceptance -- python scripts/shell_acceptance.py` and
`... install -- cmd /c scripts\windows_acceptance.cmd` (the install test backs up `%APPDATA%\STAR` first).

## 3. Measured (RAN, 2026-10-31)

- Merger replay on 6 merged PRs: 2/6 -> 5/6 agreement after claim checking (the 6th a cautious hold, never a wrong
  merge). Planted-bug catch by review: 0/3 in diff mode; function-by-function prompt 2/3 but 3 false flags on a
  clean file -> review is NOT a bug detector yet; tests/CI + receipts are the safety.
- Fixer, planted bugs: 1 bug round 1 (5 s); 2 bugs in one PR: 1/2 without the diff, 2/2 with diff + kept progress.
- **Bug bench on the real repo, seed 1, with diff: 8/8 solved** (add-not, and-or, drop-not, eq-flip, false-true,
  lt-edge, ne-flip, or-and; 17-84 s each, 1-2 rounds).
- **Blind (failing tests only, no diff), seed 2: 8/8 solved** (add-not, and-or, drop-not, eq-flip, gt-edge,
  in-notin, ne-flip, or-and; 9-78 s, 1-2 rounds). This run was before `deep_failure` was added.
- Hunt (find AND prove a planted bug, no failing test given), seed 3: see section 3b.
- Proofs: false claim rejected by the before-PR comparison; one real planted bug she could not prove with a test
  (unproven claims do not block, so this costs nothing but leaves review weak).

## 4. Not done yet, in order (each is a self-contained next task)

Done 2026-10-31: blind fixing (8/8), the proven bug hunt in the merger, 32 bug kinds, ruff failures in the fixer,
bench pairs written to the nightly bank (`bank-litha-fixes.jsonl`, kind "corrected").

1. **Hunt catch rate**: `python -m star.bug_bench hunt --n 10` (runs nightly too). Raise it: give the hunt the
   function's callers and its tests, ask for 2 candidate lines instead of 1, prove each.
2. **Hunt false flags on real PRs**: the proof cannot flag identical code, but an INTENDED behaviour change looks
   like a regression. Replay the hunt on the last 20 merged PRs (`pr_merger.replay` style) and count holds; if any,
   compare the claim with the PR body before holding.
3. **Multi-line bugs** in the bench (swallowed exception, wrong variable, missing `await`): mutate an AST node,
   not a line regex.
4. **Pyright / vitest / tsc failures for the fixer** (pyright: parse `file:line - error:` lines like ruff).
5. **Gate the nightly adapter on the bench**: the nightly gate (server/training/nightly, PR #847) scores
   game-building answers only. Before `auto_deploy`, serve the candidate adapter and run
   `bug_bench run --n 10 --seed <held-out>` against it; ship only if the solved count does not drop.
6. **Receipts automatically on STAR's own PC**: run shell + Windows acceptance there for each green `star/next` head
   and write the receipts, so `main` moves with nobody involved (STAR's PC is hers: full admin, no prompts).
7. **Dependency PRs**: DONE 2026-10-31. A PR that only changes `requirements*.in/.txt` gets the hashed lock rebuilt
   by `installer/star-home/pin_requirements.py`, then `tests/test_home_installer.py` (#831 -> #850 in 46 s, #833 ->
   #851 in 61 s; #832 onnxruntime-gpu stops: a test pins the GPU build on purpose, owner's call). The merger holds
   a MAJOR bump of a STAR Home package (`major_bumps()`): CI never installs them, so it must run on her PC first.
9. **Hunt benchmark measures the wrong bugs**: it plants bugs the module's tests already catch, i.e. bugs CI
   already blocks. The hunt's real value is bugs the tests miss. Next: plant mutants that SURVIVE the tests and
   count how many she proves (expect some mutants to be harmless: those cannot be proven, which is correct).
8. **Codex's stacked drafts**: once marked ready, walk them bottom-up (base first), one per run.

## 3b. Hunt measured

- Seed 3, first version: 0/6. Cause seen in the log: right line and reason, but the proof imported an invented
  class. Fix: the prover gets the module outline + a real test of the module, and retries when her test also fails
  on the old code. Then 1/6 caught, 0 wrong-line flags (different mutants: 10 kinds were added in between).
- Then the hunt also sees how the tests call the function and names up to 2 suspects (each proven): same 6
  mutants, 1/6 again (a different one caught: run-to-run noise, no measured gain). Not yet checked whether the
  misses are wrong suspects or failed proofs (one traced miss earlier was a failed proof). Next lever: let the proof run the module's existing tests on head vs base first and give her the
  first assert that differs, instead of asking her to invent a new test.
- False holds: `python -m star.pr_merger --replay-hunt 8` on merged PRs #816-#847: 0/7 flagged (one had no Python
  change).

## 5. Rules that stay (do not remove)

Never merge into `main` except through `pr_promote` with all receipts. Never force-push, never push to another
author's branch, never edit tests to make them pass, never print or commit keys or private addresses, one CI rerun per
run, and every decision logged. If a rule blocks real progress, measure it, then change it in code with a test and a
line in this file saying why.
