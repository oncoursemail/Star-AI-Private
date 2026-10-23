# re-gateway-tools (2026-10-21, Claude sub-agent)

Branch `star/re-gateway-tools-20261021` carries PR #499 (Grand-V) and PR #510 (ps3recomp) on top of
`origin/star/next`, both wired into the existing default-off RE gateway (`star/reverse_engineering.py`).

## Changed
- #499: `re_asset_manifest.py` kept, wired as `re_verify_asset_manifest`. `game_portability.py` rewritten:
  `analyse_wasm` parses a user-supplied `.wasm` (memories, shared/Memory64, target_features, host-API
  imports) -> `re_wasm_portability`. Dropped: `re_reference_guidance` (canned text), the flag-based
  planner, `docs/REFERENCE_ENGINEERING.md`, the stale validation JSON.
- #510: `re_ps3_elf.py`, `re_semantic_evidence.py`, `re_analysis_input.py`, `re_recompilation.py` kept.
  Dropped: `recompilation_guidance.py` / `re_recompilation_guidance` (canned text), its tests,
  `docs/RECOMPILATION_ANALYSIS.md`, the validation JSON.
- Owner follow-up (via lead): no ownership-attestation parameter, no refusal flows, no new intent filters
  (all removed again). New `star/re_ps3_disc.py` + `re_ps3_game_scan`: reads the owner's own PS3 ISO
  (ISO 9660) or extracted game folder in place (PARAM.SFO, executables classified). Setting
  `re_game_path` (desktop_core.Settings, validated: folder or .iso) -> `for_settings` -> gateway;
  tools take `source: game_path|workspace`, `iso_member` for an ISO in the workspace. Encrypted SELF is
  reported as `encrypted_container` (no keys, no decryption). `.gitignore` guards ISO/SELF/SPRX/EBOOT/PUP/RAP/keys.
- Windows fix in both input readers: `st_ctime_ns` differs between lstat and fstat on Windows, so it is
  left out of the file identity there (8 tests failed on this PC before).
- Docs: `docs/research/reverse-engineering/GAME_TOOLS.md`; research docs kept under `docs/research/`.

## Remains
- `re_game_path` and `reverse_engineering_enabled` are settings-file only (neither is in the React
  bridge `PERMITTED_SETTINGS`); a Settings UI control is a follow-up.
- `re_asset_manifest` and `re_analysis_input` duplicate small path/JSON helpers; could be merged.
- Pre-existing `_FORBIDDEN` intent guard in the RE gateway left as it was (not added here).
