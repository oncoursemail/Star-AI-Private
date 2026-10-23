# Studio Atlas (K-now-2 / K1 first slice), 2026-10-22

Retrieval, not training: verified Roblox systems that STAR gets as reference code when a request matches.

## What exists
- `data/studio_atlas/index.json`: 10 systems with capability tags and phrases. Each `systems/<id>/` has a strict-typed Luau module, `README.md` (API, wire it, pitfalls) and `test.luau` (Lune).
- Systems: profile (session-locked DataStore), remotes (secure remote layer), inventory, shop (purchase + idempotent ProcessReceipt), rounds, wallet (currency + leaderstats), combat (hit validation), quests, admin commands, uikit (responsive UI).
- Every module takes its engine services as arguments (DataStore, clock, wait, signals, raycast, Instance.new), so the same code runs on a server and in Lune. `data/studio_atlas/testkit.luau` holds the small fakes (DataStore with UpdateAsync cancel semantics and failure injection, signal, clock). The Player Twins engine doubles were NOT used: they model Instances and services, and these systems need none of that; plain fakes keep each test short.
- `star/studio_atlas.py`: `select(prompt, max_chars)` scores phrases (3) and tags (1), needs 3 points, returns up to 2 systems (second only at 60 % of the top score), README first then as much code as fits (truncated at a line, marked). No model, no network.
- Setting `studio_atlas` (default True) in `star/desktop_core.py`: Roblox route, not quick mode, section `STUDIO ATLAS ...` after the gold bank block, event `studio_atlas_used`. The gold bank stays opt-in and separate.

## Checks run (this PC, 2026-10-22)
- Lune 0.11.0: 10 test files, 62 tests, 0 failed (`cd data/studio_atlas/systems/<id> && lune run test.luau`).
- luau-analyze (`--mode=strict`, the 2026-10 build from work/tools/luau): all 10 modules clean, no lint warnings. Set `STAR_LUAU_ANALYZE` to run it from pytest.
- `tests/test_studio_atlas.py`: each of 10 realistic requests pulls its own system, 5 unrelated requests pull nothing, composite request pulls two, budget and truncation, run_task wiring on/off, setting validation; it also runs the Lune tests and the analyzer when the tools are found (skips otherwise: set `STAR_LUNE`, `STAR_LUAU_ANALYZE`).

## Not done / limits
- Not verified in a live Roblox Studio or on a live brain: only Lune with fakes. The code uses documented APIs (UpdateAsync, BindToClose, ProcessReceipt, ScreenInsets, GuiService:IsTenFootInterface) but wiring snippets in the READMEs were not run in Studio.
- No paired quality gate yet (does the atlas raise task scores?). It is default ON for retrieval only because it adds nothing unless a request matches; run the paired gate before treating it as a win.
- Tag matching is lexical. Paraphrases without the keywords miss; an embedding ranker like the gold bank's can be added later using the same index.
- K2 (skill calls that expand to the module) is not built; the modules already expose small APIs it could target.
- Next systems: gamepass ownership, trading, pets, daily rewards, matchmaking, cutscenes, a UI component library.
