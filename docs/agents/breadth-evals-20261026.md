# Breadth evals: GDScript and instruction following (item F, wave 2026-10-25)

Branch `star/breadth-evals-20261026`, worktree `worktrees/breadth-evals`, board item #250. Research source: item F in
`docs/research/smarter-faster-20261025.md` (section 7, TOP 15 row 14).

**Status: built and validated offline against reference answers. STAR was NOT measured on either suite** (brain 1 was
busy with the sealed eval; the lead said not to send it load). Baselines are the next step, below.

## What exists

| Suite | File | Tasks | Grader |
|---|---|---|---|
| GDScript dev | `evals/gdscript/golden-tasks-v1.json` | 18 | answer runs in headless Godot 4.7.2, harness test per task |
| GDScript holdout (sealed) | `evals/gdscript/holdout-v1.json` + `holdout-v1.sha256` | 9 (a third of 27) | same |
| Instruction following dev | `evals/instruction-following/golden-tasks-v1.json` | 24 | code checkers, no judge |
| Instruction following holdout (sealed) | `evals/instruction-following/holdout-v1.json` + `.sha256` | 12 | same |

- GDScript: original tasks over core language, signals, nodes, resources, math, data, state, input, editor exports,
  tweens and physics steps. Each `tests/<id>.gd` extends SceneTree, loads the model's script as `res://answer.gd`,
  exercises behaviour (return values, signals, node trees, timers, InputMap, property lists) and prints `@@T pass|fail name`
  lines through the shared `evals/gdscript/harness.gd`. 5 to 12 assertions per task. A Godot 3 leak (`yield`, `export(...)`,
  `TYPE_REAL`, `scancode`, `rect_min_size`) fails by itself because the script does not parse in Godot 4.
- Instruction following: 36 original prompts, 1 to 4 constraints each (39 checker types: word/sentence/paragraph/line
  counts, keyword counts, forbidden words, letter frequency, case, no-character, JSON shape, bullets, numbered lists,
  sections, placeholders, postscript, acrostic, table, CSV, language es/fr/de/ru, repeat-then-answer, nth word, wrap in
  quotes, and more). A task passes when every constraint holds (strict); each constraint is also its own check in the
  result, so loose accuracy can be computed. Checker code: `star/breadth_ifbench.py`.
- Holdout convention is the Roblox one (`docs/evals-holdout.md`): `split: holdout`, ids `HO-...`, a `.sha256` freeze file
  (checked by `tests/test_breadth_evals.py`), never used for training data, prompts, packs or tuning, never edited (write
  `holdout-v2` instead). Frozen 2026-10-25.

## Wiring

`python -m star.evals run|selftest|rescore --suite <breadth suite>` is routed by `star/evals.py` to
`star/breadth_evals.py` when every task has `auto.breadth.kind`. The answer path is unchanged: `eval_runner.build_real`
(STAR's `run_task`, isolated APPDATA, quiet-lock probe, planner leases) and `eval_runner.run_suite` (one task at a time,
checkpoint, resume, `--tasks`, `--retry-errors`). Only the scorer differs. `star/eval_runner.py`, `eval_checks.py` and
`eval_sandbox.py` are not touched: `eval_runner.grader_sha256()` is still `5bc54cad...` (no diff against `origin/star/next`
for those three files), so the sealed fingerprint did not move. The breadth graders have their own fingerprint
(`run.breadth.grader_sha256` in the result: `breadth_evals.py` + `breadth_ifbench.py` + `harness.gd`), folded into the run
fingerprint so a result from different grader code is never resumed or compared as the same run. Test files are part of
the suite identity through `auto.unit_test`, as for the Luau suites.

Where Godot runs (never on brain 1, not on the PC unless asked):
```
STAR_EVAL_GODOT_SSH=<user>@<brain-2-address>     # key login, as for the other tools
STAR_EVAL_GODOT_BIN=~/godot/godot                 # default; on a PC with Godot on PATH leave SSH unset
python -m star.evals selftest --suite evals/gdscript/holdout-v1.json             # no model call
python -m star.evals run --suite evals/gdscript/golden-tasks-v1.json --out evals/results/gdscript-dev-<arm>.json --server ... --ssh ...
python -m star.evals run --suite evals/instruction-following/golden-tasks-v1.json --out evals/results/if-dev-<arm>.json ...
```
With neither variable set a GDScript task is `error` (infrastructure), never `fail`. The instruction suites need no Godot.

Godot on brain 2: official `Godot_v4.7.2-stable_linux.x86_64.zip` (77,860,424 bytes) from the godotengine/godot GitHub
release, SHA-512 checked against the release's `SHA512-SUMS.txt`, unpacked to `~/godot/` (user space, no sudo). A run is one
ssh call: throw-away dir and HOME, `unshare -rn` (no network, when the kernel allows it, it does on brain 2), `nice -n 19`,
`ulimit` for memory (6 GB), CPU (15 s), file size, `timeout -s KILL 20`. A test that aborts on a script error is ended by a
10 s watchdog in the harness. Cold start about 0.4 s, a task about 0.5 to 1.3 s (tween and cooldown tasks wait for real time).

Safety of running model code: before anything runs, the script is scanned (comments and strings removed) for file, network,
OS, process and runtime-compile APIs (`OS`, `FileAccess`, `DirAccess`, `HTTP*`, `*Peer`, `ClassDB`, `Expression`,
`GDScript.new`, `source_code`, `get_singleton`, ...); a hit fails the task with `sandbox_policy` and nothing runs. This is a
deny-list plus an unprivileged user and resource limits: defence in depth, not a proof. No task needs those APIs.

## Validation (what I ran, 2026-10-25 night)

- `python -m star.evals selftest` for all four suites: every reference answer passes, every deliberately wrong answer
  fails, every empty answer fails. GDScript: 27 references pass, 27 bad answers fail (each fails real assertions or does not
  parse), 8 alternative correct implementations (`reference/<id>.alt.md`: Timer node vs scene-tree timer, `set =` setters,
  `get_tree().create_tween`, `keycode` vs `physical_keycode`, typed Dictionary, ...) pass. Instruction following: 36 references
  pass, 36 bad answers fail on the intended constraint. Both GDScript suites were run four times in a row on brain 2 while
  night school was running: identical results (the three timer tasks did not flake).
- Live probes of the runner on brain 2: a hostile answer using `OS.execute` is refused without running; an infinite loop
  is killed (about 15 s, `timed out ... in headless Godot`); a memory hog ends without a finish line; an answer with no
  GDScript fence fails `gdscript_block`.
- `tests/test_breadth_evals.py` (55 tests; the two Godot selftests run only when `STAR_EVAL_GODOT_SSH` or
  `STAR_EVAL_GODOT_BIN` is set), plus `tests/test_eval_runner.py`, `test_eval_checks.py`, `test_eval_holdout.py`,
  `test_eval_sandbox.py`, `test_eval_gate.py`, `test_protected_closure.py` stayed green (see the PR for the exact counts).

## Not done / limits

- **No STAR baseline.** Needed: run `golden-tasks-v1` and `holdout-v1` of both domains once for `star-fast` (packs off),
  after the sealed eval on brain 1 finishes (about 11:00Z 10-26) or on the farm. GDScript: 27 tasks, a few minutes of model
  time each; instruction following: 36 short answers.
- The verifier proves behaviour on the tested paths, not that the script is idiomatic or free of leaks (nodes created by a
  test are not all freed; Godot warns at exit, which the grader ignores).
- Language check is a stop-word heuristic for es/fr/de/ru, enough for whole-answer language constraints, not a detector.
- `sentence_count` splits on `. ! ?` followed by space; a title line without punctuation joins the first sentence.
- Prompts say "Godot 4" and "gdscript code block" so STAR's route sees a Godot question; whether STAR's Godot pack or the
  plain route answers is part of what the numbers measure.
- The holdout answers (`reference/HO-*`) are in the repository like the Roblox holdout's; a generator branch cannot edit
  them (`evals/**` is protected), but nothing stops a model from reading the repository: keep them out of training data.
