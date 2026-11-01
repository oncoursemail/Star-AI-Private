# select-many-20261025: M5 candidate pool + offline replay (Q3, Q7)

Owner: claude (Opus lane). Branch `star/select-many-20261025` off origin/star/next dd76c595. Research items M5, Q7, Q3 in
docs/research/smarter-faster-20261025.md. Numbers below are from commands run on the PC on 2026-10-25; raw tables are in
`docs/agents/select-many-20261025/` (replay.txt, replay.json, fixes.json). No model, no server and no brain was touched
by the replay.

## What was built

| Piece | Where | State |
|---|---|---|
| Candidate-pool format + recorders | `star/candidate_pool.py` | tested (10 tests) |
| Flag: `python -m star.evals run ... --pool DIR [--pool-tag NAME]` (or env `STAR_CANDIDATE_POOL`, `STAR_CANDIDATE_POOL_TAG`) | `star/evals.py` takes the flags, `star/candidate_pool.take_flags` | tested; NOT run against a live server |
| Ladder hook: raw answer, every block version (first / rewrite / fix) with rungs, rank, seconds, accepted flag, final choice | `star/verify_ladder.py` | tested with fakes; the pool is off by default and the hook is a no-op then |
| Best-of-N hook: every candidate with checks, unit result, chosen flag | `star/best_of_n.py` (`record_best_of_n`) | tested |
| Offline replay: rules, expected pass over all orderings, paired stats with `star.eval_stats`, leave-one-source-out, signal table, Q7 fix-vs-fresh, grading of live pools, chain policies | `star/pool_replay.py` (`python -m star.pool_replay` = `python -m star.evals pool`) | tested (21 tests); replay run on stored data below |
| Opt-in `verify_resample` (default OFF) | `Settings.verify_resample`, `star/verify_ladder.py` (`resample_answer`), `star/doc_grounding.finalize(resample=)`, `star/best_of_n.resample_tool`, wiring in `desktop_core.run_task` | tested with fakes (10 tests); not run live |

The hooks avoid `eval_runner.py`, `eval_checks.py` and `eval_sandbox.py` on purpose: `grader_sha256` hashes those three
files, so touching them would move the sealed-eval fingerprint. Consequence: `--set verify_resample=on` is not accepted by
the eval runner until `"verify_resample"` is added to `eval_runner._SETTABLE`; do that in the same change that re-freezes
the grader fingerprint (see STATE.md, #608/#625), then the farm can A/B it.

### Pool format (schema 1, JSON lines, `DIR/pool-<tag>.jsonl`)
`answer` (raw answer + block spans) / `candidate` (source ladder or best_of_n, block, idx, origin, parent, code, rungs,
rank, ok, accepted, fix_seconds, rung_seconds) / `block_final` (chosen idx, rounds, stopped). Join to an eval task by
`prompt_sha256` (the same 16 characters the result files hold). The true grade of a non-final candidate is added after
the run: `python -m star.pool_replay grade --pool DIR/pool-x.jsonl --suite S.json --out grades.jsonl [server options]`
(rebuilds the answer with the candidate's block, runs the task's own checks; resumable; uses the server's Luau check and
sandbox, so run it on the farm, not during a measured eval). `pool_replay.chain_policies` then scores keep-first,
the ladder's own keep-best, keep-last and the oracle over those graded chains. That live-pool path is built and
unit-tested but has no real data yet: the replay below uses stored result files.

## How the replay is read

Stored result files are the pool: one answer per task per run, star-fast, same tasks (golden-tasks-v2 34, creation-v1 23,
holdout-v1 24 = 81 tasks, 469 raw candidates from 19 run files, 45 mixed tasks; files listed in the last section). Answers
that went through a repair loop (ladder on, retry ladder, slop repair) are excluded: they are not raw samples. A rule sees
only what STAR sees at answer time (compile/type check, anti-slop score, code text, the ladder's API and deprecated
rungs computed offline with the local dump); the hidden tests grade only the choice. Budget N = candidates drawn per
task (all orderings when few, else 2,000 seeded). Baseline = one sample. Paired by task: 95 % bootstrap interval, exact
sign test on changed tasks, Bonferroni over rules x budgets (alpha 0.0018). "CLEAR WIN" needs interval above 0 and the
sign test below that alpha.

Caveat that applies to every number: the pool mixes runs of different STAR settings and days (api_hints on/off, other
commits), so candidates are not iid draws of one generator, and temperature 0 under load gives near-copies (12-15 % of
tasks flip between identical runs). Treat the result as a screen.

## Results

Single sample passes 42.3 %. Pass@N ceiling (oracle): 55.5 % at N=2, 62.9 % at N=3, 69.4 % at N=4.

| Rule (what it does) | N=2 | N=3 | N=4 | extra generations | Verdict |
|---|---|---|---|---|---|
| compile_first: resample only while the first candidate fails the compile/type check | +2.2 (13W/0L) | +2.9 (13/0) | +3.6 (13/0) | ~10 % | CLEAR WIN at N=2,3,4 |
| ladder_first: same on compile + real-API + deprecated rungs | +2.2 (17/3) | +2.8 (17/3) | +3.2 (17/3) | ~15 % | CLEAR WIN at N=2,3,4 |
| verified_first: compile + hard slop | +1.5 | +2.2 | +2.9 | ~10 % | no clear difference |
| verified_rank / ladder_rank: write all N, pick the cleanest | +1.5 / +1.8 | +1.9 / +1.9 | +2.4 / +2.1 | N x | no clear difference |
| consensus (code 3-gram similarity), consensus_clean | 0.0 / +1.5 | +1.3 / +2.9 | +2.2 / +4.5 | N x | no clear difference |
| oracle (ceiling, not a rule) | +13.2 | +20.6 | +25.6 | | |

(points of pass rate vs one sample; W/L = tasks better/worse.) compile_first at N=3: 45.3 % vs 42.3 %, 95 % interval
+1.4 to +4.8, p = 0.0001.

What holds up and what does not:
- compile_first never loses a task, by construction: no candidate that failed the compile check passed the grader
  (0 of 65). It is robust to leaving out any one of the 19 run files (delta +1.9 to +2.4 points, 0 losses every time).
  By suite at N=2: v2 +3.4 (7W/0L), creation +1.7 (3/0), holdout +0.7 (2/0); the holdout alone is not significant.
- The API rung is a poor selector: the 25 candidates it flags passed 52 % (13/25), against 39 % for the rest. So the
  ladder's API rung is not evidence that a resample helps; compile_first is the rule that was wired.
- Parallel best-of-N style selection (write N, pick by what STAR can see) gets +1.5 to +4.5 points for N times the
  generations and is never a clear win. The compile gate gets about the same for ~10 % more generations.
- The visible checks capture about 14 % of the oracle gap at N=3 (2.9 of 20.6 points). The rest needs verifiers that
  separate right from wrong behaviour (execution against tests that mean something), not more candidates. The
  hidden-test pass rate of candidates that compile is 45 %, so "compiles" is the only strong signal STAR has today.
- Consensus on code text does not help at N=2-4 (identical wrong answers, different right ones).

### Q7: fix round or fresh sample (stored ladder-on runs, 21 tasks where a fix call ran)
Fixed answers passed 4 of 21 (19 %, 5 fixes accepted); fresh samples of the same tasks (raw runs, never the same run) pass
24.9 % (one draw) and 30.1 % (two draws, first compile-and-slop-clean kept). Difference -6 and -11 points, interval
-19 to +7 and -26 to +2, 3 tasks better and 7 worse, p(worse) = 0.17. MDE here is 10 tasks, so this is a direction,
not a result: fix rounds recovered little, which agrees with action-wave1's 0 of 11 retry recoveries. Over every task of
the ladder-on runs (77), those runs pass 36.4 % against 40.8 % for one raw sample (-4.4, interval -11 to +2): the
ladder's net effect on these runs is not distinguishable from zero and is confounded by run day (vl creation +9 points,
vl v2 -5, thinking-off runs lower). Do not read it as "the ladder hurts".

## What changed in the product (all default OFF)
`verify_resample = on`: after the model answers, if a Luau block (first two) fails the compile rung, STAR asks the same
request again at temperature 0.7 (then 0.9), at most twice, only while the turn has at least 195 s left, and replaces
the answer with the first one whose blocks compile; the normal rungs and fix rounds then run on the kept answer, and the
check note says the answer was written again. No effect with best-of-N on, tool turns, Studio/Blender/image turns, or
when the ladder is off. Cost: only on compile failures (about 14 % of raw answers in the stored runs), one more full
generation each: at 10 tokens/s that is minutes of latency on those turns, so it fits the PC GPU, background and night
lanes first.

## Not verified (do not claim)
- The live path (`verify_resample` in a real turn, `--pool` in a real eval run, `pool_replay grade` against the server)
  was not run: brain 1 is in the measured eval until about 05:00Z 10-26. All of it is tested with fakes only.
- The replay used temperature-0 samples from different runs. The live resample draws at temperature 0.7/0.9, whose
  per-sample pass rate is not measured; it may be lower than a temperature-0 draw. The research doc's own rule applies:
  screen offline, then confirm the winner on the farm (paired, ladder on, `verify_resample` off vs on, k=2 on the
  sensitive pool). Until then it stays off.
- The offline API/deprecated rungs use the dump shipped in this commit; stored slop scores come from the slop code of
  each run's day.

## Next
1. Add `"verify_resample"` to `eval_runner._SETTABLE` with the fingerprint re-freeze; farm A/B on the sensitive pool.
2. Run one night with `--pool`: N=4 `best_of_n` candidates per task (temperatures 0.5-0.9) so the pool has real
   sampling diversity, then `pool_replay grade` and the chain policies (keep-first vs keep-best vs oracle).
3. Execution-based selection (Q3) needs a verifier that tracks behaviour: per-assertion tests (M4) first; the 14 % capture
   rate above is the number to beat.

## Stored files used (PC, work/eval-runs unless noted)
qab-20261020 golden-tasks-v2-{A,base}, golden-tasks-creation-v1-{A,base}, holdout-v1-{A,base}; vl-20261021
golden-tasks-{v2,creation-v1}-off; v090-{v2,creation,holdout}.json; v100-{v2,creation,holdout-final}.json;
cascade-20261021/night1/golden-tasks-{v2,creation-v1}-fast; work/model-eval/base-v2.json;
work/gold-bank/gate-20261020/golden-tasks-{v2,creation-v1}-none. Q7 adds vl-20261021 golden-tasks-{v2,creation-v1}-on and
thinking-20261023 golden-tasks-{v2,creation-v1}-off (both have the ladder on). Excluded: ladder/retry/repair arms for the
selection pool, the thinking-auto arm (a different generator), work/g1 (2/20 pass: a degraded run), 4B-model gate files,
and the sealed eval-power files (not read).

Reproduce (from the worktree root, Python of worktrees/pr39/.venv-audit):
`python -m star.pool_replay replay --results <files> --budgets 2,3,4,6 --leave-one-out compile_first --out replay.json`
and `python -m star.pool_replay fixes --results <files>`.
