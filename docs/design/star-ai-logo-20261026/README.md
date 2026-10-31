# STAR AI logo options (issue #552, 2026-10-26)

Three directions for the owner to choose from. Nothing in the app has been swapped yet.

- **A, Clip:** the four-point star from Star's hair clip, faceted and lit from the upper left, with light chamfered caps.
- **B, Voice:** a speech bubble carrying the clip star (the assistant who talks back), with round, friendly caps.
- **C, Tile:** a gold app tile with a heavy rounded-square S. It is typographic and the clearest of the three at 16 px and on light or dark taskbars.

Open `preview.html` to see each option in place (add `?light` to the address for Pearl). It covers the sidebar header, the sign-in screen, the title bar, taskbar, tray, browser tab, desktop shortcut and installer. Screenshots: `preview-dark.png`, `preview-light.png`.

## Files (per `option-x/`)
- `emblem.svg` (for dark backgrounds, also the source of the PNGs and the .ico) and `emblem-light.svg` (deeper brass for Pearl).
- `emblem-16.svg` and `emblem-24.svg`, plus `-light` versions: pixel-hinted small sizes, drawn on a 16 or 24 px grid.
- `wordmark.svg` (lockup on dark) and `wordmark-light.svg` (lockup on light). All letters are drawn paths with no font, so they render the same everywhere.
- `emblem-{16,24,32,48,64,128,256,512}.png`. 16 and 24 come from the hinted SVGs; the other sizes come from `emblem.svg`.
- `star-ai.ico` holds 16, 24, 32, 48, 64, 128 and 256 (the 256 is PNG-compressed). Each file was reopened with Pillow to confirm all seven sizes.

`build.py` rebuilds everything. Run it with the Pillow Python (`worktrees/pr39/.venv-audit/Scripts/python.exe build.py --shots`). It renders the PNGs and screenshots with headless Microsoft Edge.

## Swapping in the chosen option later (real files that would change)
- `assets/star.ico`: replace it with `star-ai.ico`. It is used by `installer/STAR.iss` (`SetupIconFile`) and by the exe build in `.github/workflows/windows-desktop.yml` (`--icon assets/star.ico`). `tests/test_brain_release_regression.py` checks that the file exists.
- `frontend/public/star-mark.svg`: the favicon (`frontend/index.html`). `frontend/public/star.svg` is a copy of it. Use `emblem-16.svg`, or `emblem.svg` for large tabs.
- `frontend/src/components.tsx`: `StarMark` and `Brand`, used by the desktop rail header in `Desktop.tsx` (currently "STAR / Intelligence").
- `frontend/src/SiteBrand.tsx`: `StarMark`, `StarWordmark`, `StarLockup` and `StarConstruction` (website, `Landing.tsx`, `SiteMascot.tsx`), plus `site-brand.test.tsx`.
- `site/star-icon.svg`: the public site favicon.
- `star/desktop.py`: the window icon (`app.setWindowIcon(qt_icon('star', ...))`, line ~1110) and the brand pixmaps (lines ~101, ~160) still draw the old glyph through `star/visuals.py`. Point them at the new emblem or `star-ai.ico`.
- `assets/star-preview.png`: the old blue star preview image. Replace it or remove it.
- Tray: no tray icon code was found in this worktree. When one is added, it should use the 16 px frame of `star-ai.ico`.
