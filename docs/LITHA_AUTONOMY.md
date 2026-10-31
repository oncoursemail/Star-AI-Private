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
  lt-edge, ne-flip, or-and; 17-84 s each, 1-2 rounds). Blind runs: see `~/.star/litha/bench.jsonl`.
- Proofs: false claim rejected by the before-PR comparison; one real planted bug she could not prove with a test
  (unproven claims do not block, so this costs nothing but leaves review weak).

## 4. Not done yet, in order (each is a self-contained next task)

1. **Blind fixing**: bugs NOT in a PR diff (pre-existing, CI-only). Measure with `bug_bench run --blind` and raise
   it: give her `git log -p` of the touched function, run the single failing test with `-l` (locals), let her add a
   print-debug round (temporary prints, rerun, read, remove) before editing.
2. **Review that finds bugs**: per-function hunt + differential proof as the filter (the hunt's false flags die
   when the test passes before AND after). Measure with planted bugs in diffs: catch rate AND false-flag rate on
   clean diffs; ship only when false flags are ~0.
3. **More bug kinds** in `bug_bench.OPS`: wrong variable, missing `await`, dropped `return`, swapped arguments,
   off-by-one slices, exception swallowed, wrong default, removed `.strip()` - plus multi-line bugs.
4. **Other failure types for the fixer**: pyright (parse `error:` lines, file:line), vitest/tsc (frontend), ruff.
5. **Training**: `~/.star/litha/sft/pr-fix.jsonl` holds prompt -> correct edit pairs from the bench (her own
   prompts, the real answers, never another model's text). Feed it to the nightly trainer
   (`server/training/nightly`, harvest step) and gate the adapter on `bug_bench` score: ship only if it rises on a
   held-out seed.
6. **Receipts automatically on STAR's own PC**: run shell + Windows acceptance there for each green `star/next` head
   and write the receipts, so `main` moves with nobody involved (STAR's PC is hers: full admin, no prompts).
7. **Dependency PRs**: let the fixer run the project's lock tool (requirements-home) instead of editing locks.
8. **Codex's stacked drafts**: once marked ready, walk them bottom-up (base first), one per run.

## 5. Rules that stay (do not remove)

Never merge into `main` except through `pr_promote` with all receipts. Never force-push, never push to another
author's branch, never edit tests to make them pass, never print or commit keys or private addresses, one CI rerun per
run, and every decision logged. If a rule blocks real progress, measure it, then change it in code with a test and a
line in this file saying why.
