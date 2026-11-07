# mistake-memory-20261022 (Claude sub-agent, board #226): S2 mistake memory + self-written fixers

Branch star/mistake-memory-20261022 (worktree worktrees/mistake-memory, rebased on star/next 432096e7 after #548 landed).
Module star/mistake_memory.py, shipped data star/data/mistake_memory/{seed.jsonl,fixers.json}, tests/test_mistake_memory.py.

## Design
- Setting `mistake_memory` = off | retrieve (DEFAULT) | fix. retrieve: a small "KNOWN PITFALLS" section (<= 900 chars, 3 items,
  verified fixes only, matched on API names / task words of the request) in the Roblox turn context (desktop_core.reference_sections).
  fix: also the ladder applies active fixers (no model call). Fixers are OFF unless the owner sets `fix`.
- Memory = S1's mistakes.jsonl (+ new optional fields `by`, `task`) + shipped seed rows.
- Fixer synthesis (`synthesize`): verified rows of one signature -> (before line, after line) pairs -> one changed token span,
  widened by 0-2 context tokens -> anti-unified across cases (varying names become a capture that matches ONLY the names seen).
  Needs >= 3 distinct TASKS (same mistake twice in one task counts once). Rule is stored active only if it (1) reproduces all
  its source cases and (2) changes none of the guard blocks (gold bank 384 answers + eval reference answers). Narrowest
  context that passes wins; otherwise rejected with the reason. Rows made by a fixer (`by: fixer:...`) never train rules.
- Application: `apply()` masks comments/strings, skips names the script binds itself (local/param/function/for), then rewrites.
  verify_ladder.verify_block runs the original, applies fixers, re-runs the ladder, keeps the rewrite only if the rank is no worse,
  then the usual model fix rounds. The answer note says "applied N self-written rewrite rule(s) (no model call)".
- Lint message per fixer: `mistake_memory.lint(code, fixers)`.

## Seed (python -m star.mistake_memory seed --evals work/eval-runs/**/*.json --logs ...mistakes.jsonl --analyzer <luau-analyze> --extra-guard ...)
- Honest limits: S1's real mistake log has 16 rows, none verified, so there were no model-made verified fixes to learn from yet.
  Seed pairs come from stored answers (818 distinct Luau blocks, 505 from failing answers): STAR's lint finds a flagged line, the
  curated lint tables supply the rename (teacher = tables, not a model), and the pair counts as verified only if the finding
  disappears, no new lint finding appears and luau-analyze shows no new error. 60 verified pairs, 0 rejected.
- Signature census over those blocks + logs: 118 distinct signatures (lint rule + compile/api/tests).
- Fixers out: 2, both validated: `(spawn|wait)(` -> `task.\1(` (3 tasks, 15 cases) and `game.<Players|ReplicatedStorage|
  ServerScriptService|ServerStorage|Workspace>` -> `game:GetService("X")` (14 tasks, 45 cases).
  Guard: 618 blocks (gold bank 469 blocks, reference answers 149 blocks): false changes 0. Also 369 stored PASSING eval answers:
  wait/spawn rule changes 0, service rule changes 15 (answers that really use game.Players style; informational, not a blocker).
- Rejected on the way (the guard doing its job): bare `wait` (a reference answer takes `wait` as a parameter), `.X` without `game`.

## Not verified / next
- No paired eval of retrieve or fix on live answers was run (no model on the PC in the daytime). The next real signal is S1's
  mistakes.jsonl filling on the server runs; `python -m star.mistake_memory synthesize` re-learns from it.
- Seed teacher covers only plain renames; compile-error fixes need real verified diffs from the ladder.
