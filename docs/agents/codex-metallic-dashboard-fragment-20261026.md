# Dashboard links with malformed project fragments

The dashboard decoded its initial `location.hash` directly inside a React state initializer. A copied link ending in `#%` or a truncated UTF-8 escape such as `#%E0%A4%A` threw `URIError` before the loading view could render.

`projectFromHash` now returns the existing default selection (`null`) for malformed escapes. Valid names retain the previous decoding behaviour, including Unicode, encoded `#` and `%`, literal plus signs and empty fragments. The page does not rewrite the link during loading. Project selection and URL updates after choosing a project are unchanged.

The isolated fix changes only the stable `metallic/dashboard` model and its initial selection call. It does not edit Claude's active Metallic Launcher work, accounts, game adapters, updater or artwork.

The new standalone verifier exercises the production helper and the actual React component's first server render for 13 fragment cases. It uses the dashboard's declared Vite/React dependencies for an in-memory build, creates no browser, makes no network requests and writes no owner state. Run from the repository root after installing the dashboard dependencies:

```text
node scripts/verify_metallic_dashboard_fragment.mjs
```

Validation on the isolated source:

- The standalone verifier passed all **13** fragment cases, checking both decoded selection and the actual React first render without rewriting the link.
- The existing dashboard suite passed **3 tests**; its fixtures were not changed.
- `npm run typecheck` and `git diff --check` passed. Dependency installation used the existing lockfile with install scripts disabled; no manifest or lockfile changed.

This fixes malformed-link startup only. It does not establish browser layout, live data freshness or production launcher acceptance.
