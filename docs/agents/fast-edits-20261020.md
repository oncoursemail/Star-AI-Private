# fast-edits-20261020 (Claude sub-agent, board #197): breakthrough ideas 4 + 5

Brief: owner via lead, 2026-10-20. Ideas from docs/research/breakthroughs-20261020.md: (4) diff-only answers for edit
tasks, (5) retrieval-based speculative drafts (llama.cpp static n-gram lookup cache). Branch star/fast-edits-20261020
(worktree worktrees/fast-edits-20261020, from origin/star/next e2371e83). Timing only under
`./star.cmd lock run --owner claude --holder fastdraft --server 1 -- ...`; own temp server on brain 1 port 8099
(speed agent used 8094, priority-scheduler agent 8096/8097).

## Result (2026-10-20 19:40Z): both built and measured; NEITHER turned on by default; nothing live changed

### Idea 4, diff-only edits (Settings.edit_diff, opt-in): equal pass rate, -40 % tokens, -17 % wall, not consistent
20 tasks of evals/roblox/edit-tasks-v1.json, same temp server for both arms (live star-fast binary and flags),
greedy, no prompt cache, arms alternated per task, every task inside the quiet lock (holds e1-e9, 15:40-19:11Z).
File: docs/research/fast-edits-20261020/edit-format-ab-20261020.json.

| | full rewrite (today) | diff-only (edit_diff) |
|---|---|---|
| tasks passed (unit tests in the Luau VM + Luau check) | 13/20 | 13/20 (won EDIT-04, EDIT-12; lost EDIT-11, EDIT-18) |
| generated tokens, sum | 16,316 | 9,719 (-40 %; median per task -51 %) |
| wall seconds, sum (requests + checks + fallback) | 1,882 | 1,555 (-17 %) |
| wall seconds, median per task | 88.4 | 70.1 (median per-task ratio 0.86) |
| tasks where diff was faster | | 12/20 |
| blocks applied / fell back to the full answer | | 18 / 2 (a luau_lint false positive on `while true`; a malformed block with two `=======`) |
| generation tok/s (server timings) / prompt tokens per request | 10.35 / 631 | 8.9 / 794 |

Why the time gain is much smaller than the token gain: star-fast's ngram-mod drafts already copy the unchanged code
of a full rewrite at 15-21 tok/s, while a diff is mostly new text (8.9 tok/s), and the edit instruction adds ~160
prompt tokens. Decision: stays opt-in (pass rate not lower, but 8/20 tasks were slower and the live slot was busy in
3 of the 9 holds, so "clearly faster" is not shown).

### Idea 5, static n-gram lookup drafts: lossless (10/10 identical), but 11 % SLOWER stacked on the live setup
Stacking works: llama.cpp-ramforge runs spec types as a cascade (ngram-mod, then ngram-cache, then DSpark; the first
that drafts wins a step). Cache: luau-static.lcs (build_cache.py, 440,006 corpus tokens, 88,267 2-grams, 3.1 MB;
the 10 measured tasks' reference answers excluded). Proxy on those held-out answers: the static cache alone drafts
37 % of tokens, 69 % of them right. Fresh temp server per config, live preset, 10 Luau prompts x 300 tokens, greedy,
single stream (holds sA 19:12Z, sB 19:24Z). File: docs/research/fast-edits-20261020/lookup-cache-spec-20261020.json.

| config | gen tok/s (10 prompts) | draft accept | text vs A |
|---|---|---|---|
| A live: draft-dspark,ngram-mod, n-max 2 | 8.78 | 59.5 % (1612/2707) | - |
| B: A + ngram-cache + --lookup-cache-static | 7.82 (-11 %) | 46.0 % (1464/3184) | 10/10 byte-identical |

B was faster on 2 prompts (LUA-01, LUA-03) and slower on 8. Its 8-token n-gram drafts take steps from the DSpark
head (higher acceptance) and cost bigger verify batches. Decision: not deployed. Using retrieval drafts well would
need the cascade order or a confidence gate changed in llama.cpp (a static draft only where DSpark has none), which is
not a config change.

### What is live: nothing. Temp server :8099 stopped (19:36Z). Brain-1 files stay in /opt/star/bench/fastdraft/
(editab.json, specA/B.json, luau-static.lcs, scripts). PR #534 (star/fast-edits-20261020 -> star/next): https://github.com/oncoursemail/Star-AI-Private/pull/534

## Status log
- 15:00Z start. Claimed #197. Read STATE, wave brief, speed-20261020 (live star-fast = DSpark n-max 2 + ngram-mod),
  priority-scheduler-20261020 (its temp server on :8096 is up).
- Idea 4 built (not yet measured): star/edit_format.py (find_edit / parse_edits / apply_edits / finish), opt-in
  Settings.edit_diff (desktop_core wiring, react_shell allowlist, Settings switch "Write only the changed lines when
  I paste code"). Fallback = the normal full answer, asked once. star/edit_match.py: `whole_lines=True` (never a
  part of a line) and a bug fix: a block whose first line is deeper than its last line (e.g. starts inside a
  function body and ends at `end`) was never matched by the whitespace strategy (the tool path had the same bug).
- Idea 5 facts (llama.cpp-ramforge source on brain 1, the live binary's tree): `--spec-type` accepts `ngram-cache`
  and `-lcs/--lookup-cache-static FILE` is a server option. Several spec types stack as a cascade in fixed order
  ngram-simple, ngram-map-k, ngram-map-k4v, ngram-mod, ngram-cache, then the draft models (DSpark): the first that
  returns a draft for a step wins (common_speculative_draft). ngram-cache drafts up to 8 tokens (hard-coded) from the
  per-request context cache, then the static cache (2-token keys, >= 2 samples, >= 50 % share). The static file is
  what `llama-lookup-create` writes (common_ngram_cache_save: 4 x int32 n-gram, int32 count, (int32 token, int32
  count) pairs); only llama-server is built in bin-ramforge.
- Edit eval: evals/roblox/edit-tasks-v1.json, 20 new Paintball-style Luau edit tasks (EDIT-01..20: bug fixes,
  features, a rename, a signature change; pasted modules of 44-70 lines), unit tests in evals/roblox/tests/EDIT-*.luau,
  reference fix EDIT-*.md (made by applying search/replace pairs with star/edit_format.apply_edits) and the original
  as EDIT-*.bad.md. `python -m star.evals selftest --suite evals/roblox/edit-tasks-v1.json` against brain 1's
  knowledge service + Luau VM: 20/20 references pass, 20/20 originals fail ("selftest: all good"). The existing
  golden suites have only 3 edit-shaped tasks (ENG-01, ENG-06 and UI-12, 12-21 lines), too short to measure.
- Bench tools: benchmarks/edit_format_bench.py (bundle on the PC, gen on brain 1 against the temp server, score on
  the PC with star.eval_checks), server/brain/lookup/build_cache.py (static n-gram cache writer, stdlib, same file
  layout as llama-lookup-create; tests/test_lookup_cache.py), server/brain/lookup/specbench_luau.py (greedy tok/s +
  identical-text compare). On brain 1: /opt/star/bench/fastdraft/ (srv.sh = temp star-fast on 127.0.0.1:8099 with the
  live process's binary, env and flags as of 15:2xZ: -np 3, ctx 98304, batch/ubatch 128, threads 24/24).
- Frontend: tsc -b 0 errors, vitest 66 files / 622 tests passed, vite build OK (node_modules junctioned from
  worktrees/wt-integration/frontend: rmdir the junction before removing this worktree).
- Quiet lock was held by claude-prio, then claude-winvm, from ~15:15Z; my holds wait for it (scratchpad hold.sh polls
  `star lock status`, then `lock run`).
- 15:40-19:11Z edit A/B holds e1-e9 (lock waits of up to 30 min: claude-prio, claude-winvm(-run), claude-gold-gate,
  claude-discord-star-samples). e1 ran with the first instruction (blocks copied whole functions: 388/244 tokens
  for EDIT-01/02) and was discarded; the "Keep blocks short" instruction was used for all 20 scored tasks. During e1,
  e4 and e7 the live star-fast had one busy slot (16-26 cores) although the lock was held: those holds' times are
  noisier (both arms equally, alternating order). e5 overran: `lock run` killed ssh at 10 min but the remote script
  finished EDIT-13 about 2 min after the lock was released (budget lowered to 280-300 s afterwards).
- Scoring fixes made after looking at results (stated so nobody mistakes them for tuning): EDIT-03's unit test
  required the last onSecond value to be 0, which the request never asks; relaxed to "never negative" (affects both
  arms). find_edit missed EDIT-16's wording (no edit verb); bug-report words added and EDIT-16 re-run (both arms).
- 19:12Z / 19:24Z spec holds sA / sB (table above). Full pytest on the PC: 10039 passed, 315 skipped (12 min);
  frontend tsc 0 errors, vitest 622 passed, vite build OK.
