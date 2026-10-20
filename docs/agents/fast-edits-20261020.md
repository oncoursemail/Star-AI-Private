# fast-edits-20261020 (Claude sub-agent, board #197): breakthrough ideas 4 + 5

Brief: owner via lead, 2026-10-20. Ideas from docs/research/breakthroughs-20261020.md: (4) diff-only answers for edit
tasks, (5) retrieval-based speculative drafts (llama.cpp static n-gram lookup cache). Branch star/fast-edits-20261020
(worktree worktrees/fast-edits-20261020, from origin/star/next e2371e83). Timing only under
`./star.cmd lock run --owner claude --holder fastdraft --server 1 -- ...`; own temp server on brain 1 port 8099
(speed agent used 8094, priority-scheduler agent 8096/8097).

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
