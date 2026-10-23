# Integrator round 2026-10-21 (media wave): 9 feature branches, #540 #542 #543 #544, Pillow 13

star/next 6ad9725f -> b40a8176. All landed with `metallic queue run --apply` on the combined tree (below-normal priority, `--jobs 2`).

## Batch A (queue run 1, 4 branches merged cleanly, 11,152 tests)
- anime-dub-research (53841f3d, #495), secondary-motion (388c573a, #533), innovation-gate (a188e67b, #488),
  re-gateway-tools (2f856609, #499 #510).
- live-show, minecraft-tools, accelerator-lab, integrated-repair-ui conflicted in `frontend/src/types.ts` (the one-line
  AppSettings type); music-recognition was red (see below).

## Batch A2 (branch star/integ-media-5-20261021, merge commit 2cf305ee, 11,335 tests green)
Merged on top of star/next one branch at a time in one worktree; every conflict was "keep both":
- AppSettings line in types.ts, Settings key tuples/PERMITTED_SETTINGS (live_show_enabled, minecraft_tools_enabled,
  incremental_repair, music_recognition_enabled, scholarly_research_enabled, blender_motion_qa), agent.py tool groups
  (live_show, minecraft_tools, song_lookup definitions, authorisation and dispatch blocks), SettingsPage switches,
  Desktop.tsx `song` prop.
- Two fixes the combination needed: `MUSIC_ACTIONS=set()` in the commerce bridge test fixture (tests/test_commerce_approvals.py
  execs a slice of react_shell), and the relative links in docs/research/INCREMENTAL_REPAIR_RESEARCH_20261019.md (one level too
  few; test_docs_links).
- Frontend on the merged tree: tsc clean, vitest 80 files / 720 tests, vite build ok (one run reported 1 unhandled error with
  all tests passing; a rerun was clean, not reproduced).
- Closed with a comment naming the merge commit: #492 #495 #533 #487 #504 #479 #488 #499 #510 #481 #483 #491 #498 #503.
  Left open: #502 (debugger evidence tools; no branch covers it), #494/#497 (already in star/next).

## Batch B (branch star/integ-b-20261021, 16ed0ea4, 11,375 tests green)
- #540, #542, #543, #544: no conflicts (GitHub shows all four MERGED). #543 adds two `--add-data` entries to
  windows-desktop.yml (additive, needed to bundle the Player Twins files).
- luau-api check failed on `roblox.Instance.new("DataModel")` in star/data/xray/lune_runner.luau (#544): Lune can create
  one headlessly; marked `-- metallic:allow`.

## Pillow (b40a8176)
- pip-audit lists 8 Pillow 12.3.0 CVEs, all fixed in 13.0.0. requirements.txt now `Pillow>=13.0.0,<14`.
- The 435 test files that mention PIL pass on Pillow 13.0.0 (installed with `pip --target`, 435 passed, 38 skipped). The
  queue's full run used the audit venv's Pillow 12.3, so the full suite on 13 is the push CI. pillow-heif has no 13-specific
  release (1.8.1 latest); only the Discord requirements use it.

## Gates run
- pyright baseline (CI-parity bare 3.12 venv, pyright 1.1.414): 426 known, none new, after A2, B and Pillow. The audit venv
  reports hundreds of openai/stub errors that CI does not see; use the bare venv.
- eval-gate warns (report only) for secondary-motion/quality-ab: no paired verdict was produced.

## Metallic queue notes
- With a running PC the first run needed ~25 min wall for 5 sequential entries; one combined branch is ~6 min.
- `start /belownormal` via a .cmd wrapper works; `Start-Process cmd /c "... > file"` silently runs nothing.

## CI on b40a8176
- Push run https://github.com/oncoursemail/Star-AI-Private/actions/runs/39682010162: Offline Python, React, pyright all green.
- Dependency vulnerability audit (pull_request run 39682017305): green for the first time since 10-20. Discord gateway and Luau specs green.
