# metallic.club: Mac downloads (2026-11-04)

Branch `star/metallic-site-mac-20261104`, from `star/metallic-site-v3-20261103` 80e49cd1 (the site that is live). Worktree
`worktrees/metallic-site-mac`. **Not deployed; the live site is unchanged.** The launcher's Mac work is on
`star/metallic-mac-20261104` (Forge), notes in its `docs/agents/metallic-mac-20261104.md`.

## What it does

- Downloads page: a Mac tile and panel, hidden until `latest.json` has `darwin-aarch64-dmg` or `darwin-x86_64-dmg`. Until
  then a Mac visitor still reads "Metallic does not run on macOS yet" and no Mac link exists.
- With a `.dmg` listed: a Mac visitor gets the Mac panel, marked "This device". Two buttons, Apple silicon and Intel, because a
  browser does not say which chip it runs on. Only the published ones show. `#mac` in the address picks it.
- The panel says plainly: not signed by Apple, the Open Anyway steps, no revival seen running on a Mac, Wine through
  Experimental, no VR, sound needs macOS 15.4.
- Home and header: a Mac visitor's Download button goes to `/downloads/#mac` and reads "Download for Mac". "for Windows" in the
  copy names every system the release has.
- Files: `.dmg` and `.app.tar.gz` allowed in `build.py` and the Caddyfile (cached for good, like every installer). `.dmg` requests
  are logged for the download count, which the launcher branch's `metallic-live` already counts.
- Phones: tiles narrowed so all four fit at 390 px.

## Manifest (one version for all systems; any release moves every OS)

`darwin-aarch64` and `darwin-x86_64` are what the updater uses (`.app.tar.gz`). `darwin-*-dmg` is new, following `linux-x86_64-deb`:
the updater never asks for it, but every copy of the launcher parses it, so it needs both `url` and `signature` (sign the `.dmg`).
Put the version in all four file names, because `/releases/` is cached for a year. HOSTING.md section 4 has the steps.

## Checked

- `tests/test_metallic_site.py`: 25 pass (2 new, 3 assertions changed for the new lines).
- The full Python suite did not finish: stopped by my 9-minute limit at 15%, no failures up to there. This branch touches only the site, so that is not called green.
- Built site in Playwright's WebKit on Windows, with `latest.json` faked, 9 cases, 0 problems and 0 page errors: Mac visitor with no Mac
  files, updater entries only, no manifest, both chips, one chip; Windows with Mac files, `#mac` with and without; iPhone. Screenshots looked at (desktop and 390 px).

## Not checked

- Anything against a real published file or on the real server: no Caddy was run, the sizes and files were faked.
- A real Safari on a Mac.
- That launchers accept the `darwin-*-dmg` keys. The live `latest.json` already carries `linux-x86_64-deb` the same way, so this is expected to work, but no launcher was run against these keys.
- The Open Anyway wording against a real download: the Mac runs started the app directly, so Gatekeeper was never seen. **Try this on a Mac before publishing.**

## Left out on purpose

- Mac self-updates (`.app.tar.gz`) are not logged, so they are not in the `updates` count. Would need the Caddyfile and `live.rs` together.
- An iPhone still gets the Windows installer on the home button; that is how it was.
- The page's title and description still say Windows, Linux and Meta Quest, because they are static: change them in the deploy that publishes Mac files (HOSTING.md).
