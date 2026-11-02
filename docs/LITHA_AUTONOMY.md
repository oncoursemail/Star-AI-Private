# Litha autonomy: she fixes, reviews, merges, promotes and learns (handoff for Litha or any AI)

Owner's goal (2026-10-31): Litha merges and finishes PRs herself, finds and fixes her own mistakes, gets better every
day, and takes changes all the way to `main`, with no one else needed. This file is the map: what exists, how each
part decides, how it is measured, what is NOT done yet, and the next steps in order. Read it fully before changing
anything here; every rule below exists because a measured run needed it.

## 1. The pieces (all in `star/`, tests in `tests/`)

| File | Job | Runs |
|---|---|---|
| `pr_fixer.py` | failing PR -> CI log -> her edits -> failing test files pass locally -> her own branch + PR | task "Litha PR merger", every 10 min, 1 PR per run (3 at once when the owner is away, 4f) |
| `pr_merger.py` | open PRs into `star/next`: hard gates, her review, proofs, merge | same task, after the fixer |
| `bug_proof.py` | a blocking claim must be shown by a test that fails after the PR and passes before it | called by the merger |
| `bug_hunt.py` | last look before a merge: she reads each changed function alone and names a bug; kept only if `bug_proof` proves it | called by the merger |
| `pr_promote.py` | `star/next` -> `main` (auto-publishes a release) only with all release receipts | same task, last |
| `release_receipt.py` | runs a release check and writes its receipt | by whoever runs acceptance / install |
| `bug_bench.py` | plants real bugs in the real repo, she fixes them, lessons + training pairs + score history | task "Litha bug bench", 03:10 daily |

Scheduled script: `litha/pr_merger_run.cmd` (fixer -> merger -> promote) and `litha/bug_bench_run.cmd`.
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
`python -m litha.release_receipt acceptance -- python scripts/shell_acceptance.py` and
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

1. **Hunt catch rate**: `python -m litha.bug_bench hunt --n 10` (runs nightly too). Raise it: give the hunt the
   function's callers and its tests, ask for 2 candidate lines instead of 1, prove each.
2. **Hunt false flags on real PRs**: the proof cannot flag identical code, but an INTENDED behaviour change looks
   like a regression. Replay the hunt on the last 20 merged PRs (`pr_merger.replay` style) and count holds; if any,
   compare the claim with the PR body before holding.
3. **Multi-line bugs** in the bench (swallowed exception, wrong variable, missing `await`): mutate an AST node,
   not a line regex.
4. **Pyright / vitest / tsc failures for the fixer**. Pyright: DONE 2026-11-02 (`fix_types`, see 4d). Left: vitest/tsc.
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
- False holds: `python -m litha.pr_merger --replay-hunt 8` on merged PRs #816-#847: 0/7 flagged (one had no Python
  change).

## 4b. Added 2026-10-31 evening (measured where it says so)

- Runs every 10 min (task "Litha PR merger", overlapping runs are skipped), was 30.
- Flaky / CI-only: a failure that passes locally, or a failed job with no test/lint failure (timeout, lost runner),
  gets ONE rerun per head; when GitHub refuses ("cannot be retried"), close+reopen starts a fresh run (#700).
  Also on her own litha/ PRs (#850 merged after a 0.6 s timing test flaked); never a fix on top of her own fix.
- Conflicts: `resolve()` merges star/next into a copy of the PR on `litha/merge-<n>-<date>`; lock files are taken
  from star/next and rebuilt, code conflicts (max 4 files, 8 blocks each) are resolved block by block by her, must
  compile, no markers, touched tests pass, then her own PR. Live: #756 -> #852 (53 s), #549 -> #853 (33 s).
  Frontend files are only checked by CI (tsc/vitest), not locally.
- Hunt -> fix: a bug her merger hunt PROVES goes to `~/.star/pr-fixer/hunted.json`; next run the fixer adds her
  proof test as `tests/test_litha_found_<n>.py` (she cannot edit it), repairs the code until it passes, and opens
  her fix PR with the test as a regression test. Not yet seen live (no proven find on a real PR so far).
- Merger: honours the reviewed `star:allow` marker like star commit; holds MAJOR bumps of STAR Home packages.

## 4c. Conflicts in every repo (2026-10-31 night, measured)

- `python -m litha.pr_fixer --others N`: for each repos.json entry with `clone` and mode merge (now Metallic-Club/studio)
  she resolves up to N conflicting PRs per run on `litha/merge-<n>-<date>-<hhmm>` and reruns a failed check once per
  head. Her merger then reviews; Studio CI (fmt, nextest, clippy, deny) must be green before she merges.
- Every conflict is shown in diff3 form (with the common ancestor). Checks before anything is written, each answered
  back to her with the reason (3 tries per block, then one more try at the whole file with the checker's message):
  nothing either side ADDED is lost (functions/types/modules, headings, table rows); no line from just outside the
  block repeated (the #853 slip: doubled `data:BootData`, closed); brackets balance as both sides do; escapes are
  not turned into real characters (a Rust `\n` became a line break); the file parses (rustfmt for .rs, toml, json,
  py; naga for .wgsl only where the base copy passes). Pure additions on both sides (empty ancestor) are kept both,
  without asking her. Merged .rs files go through rustfmt when the base copy is rustfmt-clean (Studio CI runs
  cargo fmt --check). `.github/` conflicts and more than 5 files stay with a person.
- Dry run on 8 Studio PRs: 4 resolved (#448, #446, #442 incl. a real logic merge in physics raycast, #438), 4 refused
  (CI files / 7 files / no clean answer). Earlier versions of the same run produced 2 merges with a lost brace, both
  caught by rustfmt. Live: #448 -> Studio #484, #446 -> Studio #485.
- Rust CI repair (`litha/rust_fix.py`, others only, 1 build per repo per run, cargo -j 4, shared sccache, target in
  ~/.star/litha-cargo): rustc errors + the failed job's cargo commands from the log -> her edits on the real code ->
  the same commands locally as compile-only checks (+ the repo's clippy steps CI never reached; `cargo fmt` applied
  without her) for up to 4 rounds. Edits may touch test files but never remove a test or an assertion. Her own
  litha/ PR gets the commit; anyone else's gets `litha/fix-<n>-...`. Live: #485 broke on a hidden conflict (main moved
  `Game.scripts` into `Game.simulation`); she fixed it in 1 round (`self.simulation.scripts.stats()`), 479 s.
- Also found while checking her: star/next's red test `test_solo_p0_pauses_every_background_stream` was a test race
  (the proxy logs a request after answering it), not a slow runner; fixed by waiting for the 3 log rows (3/3 green).
  Her #853 doubled two lines outside the conflict (TS would reject it): closed, check added, #549 will be redone.
- Checked again after CI ran: #485's fix compiled and 2165/2166 tests passed (the 1 is a 40 ms timing budget missed at
  48 ms on the shared Windows runner; she reruns those). #486 (her merge of #442) compiled but broke main's
  `raycast_normal_is_unit_even_from_inside_a_part`: #442 skips a part the ray starts inside, main (#34) hits it at
  distance 0, and both have tests, so no merge keeps both. Closed; now every Rust merge runs `cargo test -p` for the
  crates it touched before pushing, and on a failure she comments on the PR with the failing test and pushes nothing.
- #484's repair gave up in 20 s: CI's own `-j 4` plus hers made cargo refuse every check, so she never saw a compiler
  error. Fixed; she is also shown where each name in the errors is declared (with its `#[cfg]`), the crate's
  `[features]` and the exact checks, plus one rule (gate the test, never the library). Dry run: 1 round, all 5 checks
  green, `#![cfg(feature = "presentation")]` on `camera_api.rs`.

## 4d. Type gate repair (2026-11-02, measured)

- Why: her logs held 4 non-draft STAR PRs on "Python types (pyright basic, baseline gate)" and 27 open PRs had that
  check red; the fixer only reported "new pyright errors" and stopped, so those PRs waited for a person.
- `fix_types()`: runs the pyright CI pins (`npx --yes pyright@1.1.414`) against a package-free venv
  (`~/.star/pr-fixer/bare-python`, made once, like CI's job venv) and applies the rule of
  `scripts/pyright_baseline.py` (per file and rule, only growth counts). She gets each pair above the baseline with the
  code around it; a round must lower the excess, may not add `# type: ignore` / `# pyright: ignore`, and may not edit
  the baseline or `pyrightconfig.json` (`GATES` in `apply_edits`), else it is undone and she is told why. After the
  gate passes, the test files that import a changed module must still pass (a type fix must not change behaviour).
  No npx, or the gate passes locally: reported as before with CI's lines, no rerun.
- Live check on star/next: 339 errors, 0 above the baseline (CI's script agrees). Trial on #878 (draft, local only,
  nothing pushed): 1 round, 83 s, `created is not None and ...` narrowing; `scripts/pyright_baseline.py check` on
  the result: "none new".
- Also fixed: CI lints `star litha`, the fixer linted only `star`, so a ruff error in `litha/` was reported as
  "CI-only" and never fixed.
- PRs recorded in `tried.json` as type failures before this change are retried only when their head moves.

## 4f. Several PRs at once (2026-11-02, simulated, not yet seen live)

- Why: one PR per 10-min run, while a run averages 40 s of work: the 23 logged STAR rows need 22 runs (3.7 h).
- `python -m litha.pr_fixer [--workers N] [--max M]`: a thread pool (`pool()`) over the candidate PRs in the old
  order. N defaults to 3 when the owner is away (`rust_fix.away()`: no input for 10 min) and 1 when the owner is
  at the PC; M defaults to N. A PR starts only while counted + running < M, so a run still counts at most M PRs and a skip
  still does not use one up; with N=1 it is the old serial loop. Each PR is queued once (a hunted PR is not queued
  again), each keeps its own worktree (`litha-fix-<n>`, `litha-merge-<n>`).
- Shared things: `RERUNS` allows ONE `rerun_failed` per run across workers (one CI runner); a second PR that needs a
  rerun gets `RerunSpent`, is left unmarked and is taken next run; a rerun that restarted nothing gives the slot back.
  `mark()` runs under a thread lock plus `tried.lock` and writes atomically; log rows go out under one lock.
  `git -C <clone>` (fetch, worktree add/remove) and `star commit` run one at a time (`SHARED`); every cargo command
  (`rust_fix.run`, `cargo metadata` in `resolve`) holds `rust_fix.BUILD`, so builds stay one at a time.
  `--others N` resolves of one repo also run on N workers; the per-run caps there are unchanged.
- Measured: `python -m litha.pr_pool_sim` replays the 23 STAR and 94 Studio rows of `fixes.jsonl` through the real
  `main()`/`others()` with fake work sleeping each row's logged `seconds` (x0.005; the 2026-11-01 "reran 0" loop on
  #700 left out: fixed since). STAR backlog drained in 22 runs / 3.7 h serial, 10 runs / 1.7 h with 3 workers,
  9 runs / 1.5 h with 4; runs took 40 s mean serial, 61 s with 3 (max 143 -> 145 s); 1 CI rerun per run in every
  configuration. The floor is that cap: 9 of the 23 rows need a rerun, so 4 workers gain little over 3. Studio
  (`--others 2`, away): same 22 runs (the per-run caps did not change) but runs 283 -> 199 s mean, 843 -> 556 s
  max, so fewer runs overrun 10 min: 4.2 -> 3.7 h; with `--others 3` and 3 workers 15 runs / 2.5 h (not switched on).
- Not measured: real contention. The simulation sleeps; live, 3 workers share 12 CPU threads (pytest, pyright),
  her model (`litha` through the mesh router: if one GPU node answers one request at a time, the model-bound part
  of each fix does not overlap) and the GitHub API. Tests: `tests/test_litha_pr_pool.py` (fake fix/resolve: no PR
  twice, one rerun, tried.json and log consistent, workers capped, cargo one at a time).

## 5. Rules that stay (do not remove)

Never merge into `main` except through `pr_promote` with all receipts. Never force-push, never push to another
author's branch, never edit tests to make them pass, never print or commit keys or private addresses, one CI rerun per
run, and every decision logged. If a rule blocks real progress, measure it, then change it in code with a test and a
line in this file saying why.
