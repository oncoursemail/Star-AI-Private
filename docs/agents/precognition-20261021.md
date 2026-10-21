
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
