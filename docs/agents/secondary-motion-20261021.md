# secondary-motion (PR #533 finish), 2026-10-21

Branch `star/secondary-motion-20261021` from origin/star/next. Source: PR #533 head `star/secondary-motion-recovery-20261020` (one commit, cherry-picked): XPBD Luau kernel pack, `scripts/secondary_rig_audit.py`, `scripts/test_secondary_motion.luau`, research doc and manifest.

## Changed
- Pack registered the way other packs are: a `TRIGGERS` entry in `star/skill_packs/__init__.py` (before, the folder was not in `TRIGGERS`, so `available()` never loaded it). NOT in `DEFAULT_ENABLED`: off until `STAR_SKILL_PACKS` names it or the promoter enables it.
- Labelled EXPERIMENTAL in the SKILL.md description and heading; research doc and `verification.json` (SKILL.md hash/size) updated to match.
- `tests/test_skill_packs.py`: pack added to `NAMES`; the grounding test gets a branch for this pack (3 Roblox doc pages + paper + SmartBone, off by default), like the architecture-blender one.
- `tests/test_secondary_motion_luau.py`: runs `scripts/test_secondary_motion.luau` with `shutil.which("luau")` (cwd = scripts/, expects `RESULT passed=<count of test() calls> failed=0`); skips without the CLI. A second test, runnable everywhere, checks the script's two `require`d modules exist.
- `tests/test_secondary_motion_pack.py`: shipped, labelled, off by default, routes only with opt-in and a Roblox prompt naming the topic.

## Ran
- pytest: test_secondary_rig_audit (30), test_skill_packs, test_skill_pack_select_order, test_core_service_skill_packs, test_design_skill_packs, test_engine_skill_packs, test_roblox_gameplay_skill_packs, test_packaged_data_files, test_pyinstaller_data_files, test_windows_package_data, the two new files: all passed, 1 skipped (the real Luau run). ruff clean.

## Not verified
- No `luau` CLI is installed on this PC and none was downloaded, so the 25 Luau tests did NOT run in this session; the wrapper's real-run test is skipped here. The PR's own record says 25 passed on Luau 0.743 on a server. The pinned CI workflow `.github/workflows/luau-specs.yml` does not run the wrapper via pytest unless its job runs pytest with luau on PATH; the lead may want a CI step (workflows are protected, not edited here).
- Not wired into any Roblox runtime; the pack is guidance plus reference code, as the PR states.
