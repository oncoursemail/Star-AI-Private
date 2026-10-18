# star-finetune-20261018 (claude): more verified data, apprentice v2, embedding A/B prep

Board item #175. Branch `star/star-finetune-20261018` (worktree `worktrees/star-finetune`, from origin/star/next
798d88e7). Local data (not in git): `work/ft18/` (copies of the night-school data), `work/apprentice/` (pilot + v2).

## 1. Data: verified worked examples (measured 2026-10-18 07:40Z)
Sources: server 1 `data/examples.jsonl` (324 rows), server 2 (49), PC GPU turbo `%LOCALAPPDATA%\STAR-night-turbo\ns\data`
(216 rows on 77 tasks). One example per task after dedupe (count script `work/ft18/count.py`):
- **426 unique verified tasks** (s1 only 300, PC only 77, s2 only 25, s1+s2 24); 572 distinct (task, answer) pairs.
  8 of them are PRIVATE paintball/river tasks (local training only, never in a public file).
- Families: ledger (generated) 196, roblox-* 41, luau 21, economy 18, obby 15, npc/ui/remotes/world/combat/datastores
  13 each, rounds 9, river 8 (private), security 8, others < 7.
- Pool 671 tasks, 245 never solved (practice-tasks-round-lifecycle 0/12, security 4/20, beginner 11/30, debugging 15/37).
- New unique verified tasks per day (all workers): 10-15 45, 10-16 166 (PC turbo's first night), 10-17 56, 10-18
  (to 07:40Z) 16. Baseline ~**56-89/day**.
- Night conductor night of 10-17 (before this change): 5 cycles, created 85, accepted 29 (34 %), cap 40 not reached.
  Rejects: mostly "reference fails its own task" (the model's reference misses its own patterns) and format.
- Bottlenecks seen: (a) one example per pool task, so growth = new tasks + solving the 245 hard ones; (b) server-1
  night school waits "brain busy" since 05:15Z (other clients on the brain + another agent's quiet lock).

## Deployed (server 1, container starai)
- 07:46Z `app/server/night_school/nightschool/conductor.py` (this branch): each cycle also asks for **variants of 4
  recently solved tasks** (2 calls; non-ledger tasks preferred, river/paintball skipped) and gives a reference that
  fails its own checks **one repair call** (at most 4 a cycle; the repaired reference must pass every validator
  again). Calls per cycle 6 -> 8 (+ repairs), accepted per cycle 12 -> 16. Report shows accepted by source and repairs.
- `env`: `STAR_NS_CONDUCTOR_MAX_NEW=80` (was default 40). Timer runs read env + code fresh each start (no restart
  needed); the night-school loop (after-batch hook) still runs the old code until restarted under the quiet lock.
- Undo: `cd /opt/star/learning && cp env.bak-20261018 env && cp app/server/night_school/nightschool/conductor.py.bak-20261018 app/server/night_school/nightschool/conductor.py`
  (then restart star-night-school if it was restarted with the new code).
- Also fixed: `run_cycle` used the wall clock for the first failure cut-off instead of `now` (the existing cycle test
  failed from 2026-10-18 on).

## Status log
- 07:37Z start; data copied read-only; HF weights of Qwen3-4B-Instruct-2507 re-downloading (pilot deleted them).
- 07:46Z conductor deployed (file + env only; loop not restarted: quiet lock held by claude-model-scout18).
