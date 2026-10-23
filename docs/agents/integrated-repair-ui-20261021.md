# integrated-repair-ui-20261021

Branch `star/integrated-repair-ui-20261021` from `origin/star/next` 9908e36c. Carries the parts of PR #503 that were
still missing from star/next, with the review conditions applied.

## What of #503 was still missing (content diff, not sha)
- e1dc867a (research + activity receipts, #494) and 22ddc4d7 (reader responsiveness, #497): already in star/next.
  Only `docs/STAR_RESEARCH_PROGRAM_20261019.md` is absent; the lead dropped it on purpose (00d0df36). Not carried.
- e5847996 (incremental repair) = #491 head 1e5d36b7 apart from whitespace: all missing. Carried.
- 8cc1a2ad (Studio UI) = #498 head 9d13a0e3 plus the visual-audit clipping fix and the rail "More" hit-target CSS:
  all missing. Carried.

## Review conditions (quoted) and what was done
#491: "gate the note and the buffering behind a setting that is off by default (or limit the note to actual
unresolved syntax checks), treat only raised/timed-out calls as uncertain, classify the read-only adapters
(reverse_engineering/workshop) as such, and keep the existing tests' expected answers unchanged."
- New setting `incremental_repair` (desktop_core Settings, PERMITTED_SETTINGS, Settings > Roblox code help switch
  "Repair a failed tool step before going on"), off by default. Off: `RepairsOff` (no deferral, no note, no stream
  hold-back), workspace writes return no `validation` key (`Workspace(validate=False)`), and the new exception
  catches re-raise as before.
- Uncertain = raised or timed-out only: dropped the `isError and not workspace` clause, so a clean Studio refusal
  ("Script not found") is an ordinary retryable tool error. Blender's caught exception counts as raised.
- reverse_engineering, workshop and debug_evidence (newer adapter, read-only too) classified as read-only.
- The six existing assertions #491 rewrote (test_edit_match, test_luau_after_untrusted, test_mcp_registry,
  test_security_regressions, test_star, test_studio_loop) are byte-identical to star/next.
- Research notes moved to docs/research/INCREMENTAL_REPAIR_RESEARCH_20261019.md.

#498: "gate the Studio layout and shelf behind a saved preference (or default companions hidden and keep Obsidian
byte-equal to tokens.css), downscale the two 1.1-1.3 MB companion PNGs to display size, move the 3825-line QA JSON
out of the repo"; StarFace timer fix ships ungated.
- Saved preference `star.studio.layout` (Settings > Interface "Studio layout"), off by default. Off: no
  `data-star-studio`, no workspace switch, no Appearance menu or Settings appearance block, no companion shelf, the
  classic welcome; `useAppearance(false)` sets nothing on <html>, so tokens.css applies unchanged.
- ember.png / astra.png: 1122x1402 (1.27/1.07 MB) -> 416x520 (220/185 KB, 2x the 208 px shelf). Provenance JSON
  updated with the new hashes and the originals' hashes.
- QA JSON moved to the workspace folder `work/studio-ui-20261019/` (outside the repo); design doc link updated.
- StarFace timer fix and usePageVisible: ungated. visual-audit.mjs change: carried.

## Checks run
- pytest (APPDATA temp): repair/validation/activity + the six restored files + settings/sanitize users:
  2015 passed, 15 skipped; after the last agent.py edit the focused set: 167 passed, 1 skipped. ruff clean.
- New tests fail without the change (checked by reverting each piece): clean Studio refusal, read-only adapters
  (both), off-by-default streaming; the six restored tests fail with the feature on by default; Studio layout
  off-by-default test fails with the preference defaulting on; star-face-lifecycle fails on star/next's StarFace.
- Frontend: `npm run typecheck` clean, `npm test` 74 files / 686 tests passed, `npm run build` OK.
- Pyright 1.1.414 on changed files: no new errors. desktop_core reportArgumentType is 57 vs baseline 52 here, and
  star/next itself gives 57 in this venv (pre-existing, not from this branch).

## Owner questions
- Companion artwork (Ember, Astra) is AI-generated (`image_gen`), styled after the existing Star mascot; the lead
  noted it may come from fan concepts. It ships only behind the off-by-default Studio layout. Owner to approve or drop.
