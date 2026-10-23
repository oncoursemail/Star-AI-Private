# accelerator-lab-20261021 (PR #479 reworked)

Branch `star/accelerator-lab-20261021` from origin/star/next 9908e36c. Replaces PR #479 (star/accelerator-lab-20261018).

## Changed
- Speed gate: `star/performance_gate.py` dropped. `star/brain_benchmark.py` gains `compare_reports` and
  `--compare BASELINE CANDIDATE`: index-paired sign test + bootstrap from `star/eval_stats.py`, any run count
  (below 5 pairs stays INCONCLUSIVE), exit 0/1/2/4 like the eval gate. Documented in docs/PERFORMANCE_PROFILING.md.
- Animation: `star/animation_regression.py` kept without its standalone CLI; reached as Blender MCP tool
  `star_blender_animation_motion_qa` (star/blender_mcp.py), listed only when `blender_enabled` and new setting
  `blender_motion_qa` are on. Toggle in BlenderPanel ("Check animation motion").
- Scholarly research: `star/public_research.py` rewritten: no own httpx client, every request through
  `web_fetch.fetch_page`; `with_scholarly_metadata` wraps the deep-research searcher (team_service.py) when new
  setting `scholarly_research_enabled` is on (first query only, 2 works per provider, no abstracts). Switch in
  Settings > Knowledge & search.
- Research text: docs/research/STAR_ACCELERATOR_LAB_20261018.md (was docs/STAR_ACCELERATOR_VERIFICATION_20261018.md).
- tests/test_blender_brain2.py: expected set `NAMES - {BUILD, ANIMATION_EXPORT}` now also excludes MOTION_QA
  (NAMES grew; offered tools unchanged).

## Ran
- pytest (APPDATA=temp): 28 test files incl. new ones: 669 passed, 5 skipped.
- Mutation: disabling the team_service wiring fails test_team_deep_research_uses_metadata_only_when_the_setting_is_on.
- Frontend: tsc -b ok; vitest 66 files / 624 passed; vite build ok.
- pyright 1.1.414 on changed py files (venv python): no new errors; desktop_core 57/52 reportArgumentType is the same
  on unmodified HEAD with this python (CI uses a bare python).
- Live: one Crossref and one OpenAlex query through fetch_page returned 2 rows each.

## Not verified
- A real `--compare` on two real benchmark runs; the motion tool inside a live chat turn; a full deep-research turn
  with a real model.
