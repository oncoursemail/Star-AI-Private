# thinking-budget-20261023 (Claude, plan D1): adaptive thinking budget

Branch star/thinking-budget-20261023. Module star/thinking_budget.py, tests/test_thinking_budget.py.

- Today: star-fast has `reasoning = off` in server/brain/models.ini, so no turn thinks (only the opt-in `luau_retry_ladder` retry asks with thinking on).
- Server controls (checked on the live build, 2026-10-23): per request `chat_template_kwargs.enable_thinking = true` overrides `reasoning = off`
  and `reasoning_budget_tokens = N` caps the thinking (probe: N=64 -> 70 completion tokens, 9.4 s vs 2.0 s without).
- Setting `thinking_budget` = off (DEFAULT, nothing sent) | auto | always.
  auto: no thinking for chat, short explanations, small edits, quick model, non-code profiles; small/medium/large (256/768/1536 tokens) from
  new-system words, debugging with an error in hand, several scripts, long specs, and families with a low stored pass rate (datastore, performance, economy).
  The check-fix loop's fix call thinks 512/1024/2048/3072 tokens in rounds 1-4 (only through the slot-carrying helper client, so evals keep their background slot).
  The agent adds the thinking tokens to max_tokens so the answer keeps its room.
- Paired eval (work/eval-runs/thinking-20261023, dev split of golden-tasks-v2 + creation-v1, 31 tasks, k=1, arms alternated per task, background slot):
  off 10/31 pass, median 190 s, p90 260 s; auto 10/28 scored (3 CompactionLimitError infra errors), median 316 s, p90 560 s.
  Pass count not better, time much worse -> NOT the default; opt-in. Per-task wins/losses are symmetric (3 each).
- Not measured: `always`, the ladder-only effect (the eval turns that reach a fix round are few), holdout.
