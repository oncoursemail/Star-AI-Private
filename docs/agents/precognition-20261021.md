
## G0b follow-up (10-21 21:00Z-, Claude sub-agent "g0b"): the per-turn reference block primed too
Goal: real Roblox code edits under 2 s first token. The gap left above: the reference block after the owner's words
(docs passages, skill packs, lessons, notes; for the edit eval set 1.1-1.7k tokens, not 789) was read after Enter.

Change (commits f03e2678, 4d8c8b41, c1e422f2 on this branch):
- desktop_core: run_task's section assembly moved verbatim into `base_sections` (lessons, reviewed notes, documents)
  and `reference_sections` (docs, skill packs, API hints, error notes, worked/gold examples, project rules + the
  per-turn budget). run_task calls them in the same places with the same arguments: behaviour unchanged.
- prefill_warm.turn_tail: once the draft is primed and no newer draft waits, build the block for the draft with those
  functions (same route, recent_users and tool list as the turn) and prime it in chunks up to the time line; then the
  whole request once with the time line of that moment (Enter in the same minute reads ~4 tokens; a later minute
  falls back to the checkpoint before the time line). Chunks stop when a newer draft waits or another client
  generates. Skipped (draft-only, as before) for web search, attached documents, a Studio connection, diff-only edits,
  or a route/tool mismatch. Only with "Start thinking while I type" on.
- Cut chosen over "move stable parts before the owner's words": the block depends on the question, nothing in it is
  stable across turns.
- Knowledge service retrieval during typing makes the post-Enter retrieval a server cache hit (0.6-1.0 s -> 30-80 ms).
- Tests: tests/test_prefill_warm.py (byte-identical start in fast and tool modes, skip cases, yield, no trace).

### Discord Star: not wired (written down)
- Discord never sends a bot the text being typed; the only signal is TYPING_START, and the bot runs with
  intents.dm_typing = False (star/discord_bot/bot.py). So the draft and its reference block cannot be primed.
- Discord turns do not use run_task (star/discord_bot/brain.py: own system prompt, 12-line history, no id_slot; the
  server picks the slot and its RAM prompt cache brings back the conversation). The per-turn tail is only the clock,
  web results and live-status lines, all computed after the message arrives.
- What could be done (est. ~40 lines + tests, bot restart on brain 2): enable intents.dm_typing; on TYPING_START from
  the owner in his DM (debounced, at most one per 60 s) send a one-token request with the exact
  [system, *history] the next `DiscordBrain.reply` would send, for the model of the last turn, no id_slot, cancelled
  by the real message. It only helps when other clients pushed the conversation out of the RAM cache; unmeasured, so
  not worth wiring before a measurement shows Discord turns re-reading their history.

### Brain 1 measurement (21:46-23:13Z, 8 holds "g0b", side star-fast :8098 = live binary/flags, -np 2, DSpark)
Bench server/brain/kv_banks/tailbench.py: STAR's real run_task / warmup.warm_up / prefill_warm.warm_draft on the PC
(temp APPDATA, default settings, mode auto) against the side server (ssh tunnel) and the real knowledge service.
All 20 prompts of evals/roblox/edit-tasks-v1.json (Roblox code edits with pasted Luau, 1.2-1.8k chars), each in two
fresh chats with the same earlier Roblox turn (12 tools). cold = post-answer warm-up only (setting off today);
enabled = warm-up + type-ahead of the finished text. First token = first visible text of run_task after the call.

| first token after Enter | n | median | worst | best |
|---|---|---|---|---|
| cold, all 20 | 20 | 40.6 s | 105.0 s | 30.6 s |
| enabled, all 20 | 20 | 0.50 s | 106.3 s | 0.45 s |
| enabled, turns whose request matched the primed one | 15 | 0.50 s | 0.58 s | 0.45 s |
| cold, the same 15 | 15 | 37.5 s | 50.4 s | 30.6 s |
- Byte check: for those 15 the real request, rendered by the server's /apply-template, equals the primed whole
  request (starts_with_primed true; the server read ~4 tokens). PC side before the model request 0.09-0.17 s;
  documentation retrieval after Enter 30-80 ms (cached by the prefill).
- 5 misses, ~89-106 s in BOTH arms: EDIT-06/08/17/20 make the turn add 1-3 tools to the chat's 12 (craft audit/
  recipe, calculate, clock, forum search), and Qwen templates put the tool list at the very start, so the whole
  request (~4.4k tokens) is re-read; EDIT-02 also triggers the automatic web search (tail skipped by design). An
  existing problem of the tool list, not of the prefill: follow-up task chip "Keep the Roblox tool list fixed per chat".
- Cost: priming the finished text took 41-67 s of server time (draft 350-480 tokens from the cached start + block
  820-1,680 tokens + the whole request). The full gain needs the owner to pause that long before Enter (pasting code
  and then reading it over); a shorter pause still saves what was read (Enter cancels, the server keeps it).
- Pilot: before the "time line of when it is sent" fix the whole request missed (minute moved on while the block was
  read) and enabled was 2.79-2.81 s (server read the time line + closing tokens, ~50 tokens).
- Side server stopped after the series (srv.sh stop; port 8098 closed). Raw rows: scratchpad g0b/all.json (not in git).

### Enable / undo (unchanged from G0)
- Desktop: Settings > Answers > "Start thinking while I type" (`prefill_while_typing`) on; off = exactly the old path.
- Not verified: the desktop UI end to end (bench calls the same functions the UI calls); live star-fast (side server
  only); the owner's real settings (bench used defaults); minute-boundary fallback on brain 1 (covered only by tests).
- Tests: full pytest 10,405 passed / 343 skipped (23:20Z, after all three commits); tests/test_prefill_warm.py 24.

## Fixed Roblox tool list per chat + minute refresh (10-21 23:30Z - 10-22 02:00Z, Claude)
Goal: the 4 slow edits (EDIT-06, 08, 17, 20; EDIT-02 too) took 89-106 s because the turn added 1-3 tools to the chat's
tool list and Qwen puts the tool list first, so the whole ~4.4k-token prompt was read again.

### Cause (reproduced offline, `run_task` with a model-free client, same seed turn as tailbench)
Chat start "Write a Luau script for my Roblox game ..." = 12 tools. An edit adds: EDIT-02/06 `star_roblox_craft_audit` +
`_recipe` (the word "audit"/"ui"), EDIT-08 `star_calculate`, EDIT-17 `star_clock`, EDIT-20 the three DevForum tools ("bug",
"help", "update"). The triggers are single words in the pasted code or the request. `star_calculate`/`star_clock` were not even
sticky (turn_memory only kept the intelligence sources).

### Design (smallest that works; only with `prefill_while_typing` on, off = byte-identical to before)
- `turn_memory.ROBLOX_FIXED_TOOLS`: one sentence made of the trigger words. `TurnMemory.pin(text)`: from then on every turn
  selects tools for that text too, through each source's own `definitions(text)`, so every setting and permission check
  still applies (a source the owner switches off drops out at once; nothing is hard-coded or widened).
- `desktop_core.run_task`: on a LAN (sticky) tool turn with the setting on and a Roblox message (`is_roblox_task` or
  `is_roblox_dev_prompt`), pin it. `agent.run_agent` lets the pinned text enable the calculator and the clock too (their
  authorisation follows the same list).
- Result: a Roblox chat gets 19 tools from its first Roblox message (12 + calculate, clock, craft audit/recipe, 3 DevForum),
  +1.4k tokens (~4.8k chars of schema) read once; offline check: the tool JSON is byte-identical for all 20 edits (20/20
  IDENTICAL; with the setting off the same 5 tasks still change the list: 15/20 identical).
- Not covered: tools of other topics (design, VFX, map plans, Roblox Cloud, video, hub) still append when asked for; a chat whose
  first message is plain chat (no tools) changes the whole start on its first Roblox message (different system text too).

### Second miss found by the 20-edit run: the time line has minute resolution
After the tool fix 2 of 20 (EDIT-05, EDIT-09) read ~50 tokens after Enter (3.2-3.3 s): the whole request had been primed with
that minute's time line and the minute changed before Enter. The bench pressed Enter ~2 s after priming; a real owner pauses,
so this would be the common case. `warm_draft(keep_fresh=True)` (the app's DraftWarmer passes it): after the whole request is
primed it stays and sends it again with the new time line ~1 s after each minute change (<= 10 refreshes, ~50 tokens each),
stops when Enter cancels it, a newer draft waits, or another client generates.
tailbench `--dwell` reproduces the pause (Enter ~7 s after the next minute change, so the primed time line is stale).

### Timing, 20 Roblox code edits, brain 1 side server (hold "toolfix", 10-21 23:43Z - 10-22 01:57Z, 5 + 6 holds of <= 9 min)
tailbench.py, enabled arm only (cold arm unchanged by this fix: median 40.6 s, worst 105.0 s from the earlier table).
First token after Enter:

| run | n | median | worst | under 2 s |
|---|---|---|---|---|
| before the fix (earlier table, enabled) | 20 | 0.50 s | 106.3 s | 15 |
| fixed tool list, Enter 2 s after priming | 20 | 0.55 s | 24.2 s (EDIT-02) | 17 (EDIT-05, 09: minute change, 3.2-3.3 s) |
| fixed tool list + minute refresh, Enter after a minute change (`--dwell`) | 20 | 0.55 s | 25.0 s (EDIT-02) | 19 |

Per task (dwell run): 0.46-0.76 s for 18 tasks, EDIT-08 1.04 s, EDIT-02 24.96 s. Rows: scratchpad tf/dwell-all.json (not in git).
EDIT-02 stays the exception: the prompt triggers the automatic web search ("latest ..."), whose results are part of the
per-turn block after the owner's words, so the draft is primed but the block (web text, ~800+ tokens) cannot be known
before Enter and is read after it (the web search itself runs on the PC before the model request). 94 s -> 25 s: the old tool-list
re-read is gone, the rest is the web block.

### Quality check: the 20 edit tasks, tools as before vs fixed list (live brain 1, no quiet lock, k=1, greedy)
Same code, same server, `python -m star.evals`-style runs through `eval_runner.build_real` (driver: arms interleaved per
task, tool memory forgotten before each ask), arm `off` = `prefill_while_typing=false` (today's tools, 0-3 per task),
arm `on` = `prefill_while_typing=true` (the fixed 19 tools from the first message; new `--set prefill_while_typing=...`).
Scored by the suite's unit tests in the Luau VM + Luau check. The tool-choice side first:

| | tasks passed | tool calls made (20 tasks) | median seconds (cold, one-shot) |
|---|---|---|---|
| off (tools as before) | 17/20 | 2 (EDIT-10: `star_luau_check` twice, then no code block: fail) | 228 |
| on (19 fixed tools) | 14/20 | 0 | 250 |

- Tool selection did not drop: with 7 more tool schemas on offer the model made no extra or wrong tool call on any task
  (off made 2 calls, both the Luau checker, on one task that then failed for having no code block).
- Pass rate: off-pass/on-fail EDIT-04, 09, 15, 16; off-fail/on-pass EDIT-10; both fail EDIT-05, 20. 4 vs 1 discordant
  pairs: McNemar exact p = 0.375, so INCONCLUSIVE at k=1 (as every earlier k=1 A/B here), direction negative. Failure
  kinds differ (a missed edge case twice, a Luau test aborted on `nil` twice, none a tool call), consistent with a
  different prompt giving a different greedy trajectory rather than a tool effect, but this was not tested beyond k=1.
  Greedy reruns of the same prompt are not independent samples, so a bigger check needs a larger task set (k>=3 A/Bs, see
  the oracle notes), not a repeat.
- Median time of the one-shot task is +22 s with the fixed list: the first request reads ~1.4k more tokens cold. In a
  chat with type-ahead that read happens once per chat (and the start is identical for every Roblox chat, so a saved
  prompt start (G0b bank) now serves all of them).
- Rows: scratchpad tf/evalout/*.json (not in git; evals/results is parsed by the failure ledger).

### Decision / how to turn it on
Off by default (nothing changes unless `prefill_while_typing` is on). Owner: Settings > Answers > "Start thinking while
I type". The fixed tool list comes with it (same switch). If the owner wants the speed without the list change, the
pin is the three lines in `desktop_core.run_task` (`tools_kept.pin(...)`); remove them and the tool-list misses return (4 of 20
edits: ~90-106 s).
