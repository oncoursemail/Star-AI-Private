# STAR Roblox Intelligence Hub — October 20, 2026

**Status:** implemented **candidate** on private `star/roblox-intelligence-hub-20261020`, targeting `star/next`. Public/creator API wiring and offline tests are proposed; these are not a published STAR release, authenticated Roblox connection, complete Roblox data dump, visual gameplay understanding, or proof of production behavior.

## New chat tools in this branch

| Tool | Kind | Source | What it actually does |
|---|---|---|---|
| `star_roblox_marketplace_search` | Public avatar catalog | https://create.roblox.com/docs/projects/assets/api | Fixed `GET https://catalog.roblox.com/v1/search/items/details` with keyword, documented category and first 10 items; limited sanitized public metadata, no pagination/cookies/purchases |
| `star_roblox_creator_store_search` | Beta creator asset search | https://create.roblox.com/docs/cloud/reference/features/creator-store | Fixed `POST https://apis.roblox.com/toolbox-service/v2/assets:search`, bounded query/type; does not import assets. **Real live schema/access verification pending** because older published OpenAPI shows GET while 2026 feature reference says POST. Failures are visible; no undocumented fallback. |
| `star_roblox_creator_asset` | Public asset details | same official feature reference | Fixed `GET /toolbox-service/v2/assets/{id}`; bounded display metadata, not asset source/mesh/scripts |
| `star_roblox_analytics_metrics` | **Private** creator analytics | https://create.roblox.com/docs/cloud/guides/analytics | Authenticated, allowlisted API key `POST /analytics-query-api/v1/universes/{id}/metrics`; distinct private time-series, not inferred from public visits |
| `star_roblox_analytics_poll` | Authenticated long-query status | same | Exact, validated fixed-universe operation `GET`; never follows an arbitrary response URL |
| `star_roblox_gameplay_telemetry_plan` | Offline methodology | https://create.roblox.com/docs/reference/engine/classes/AnalyticsService | Provides event types and requirements for owner-authored in-game event instrumentation; **does not watch games, instrument Studio, or collect users** |

The existing `star/roblox_research.py` remains the live public-experience data path (title/creator/description/visits/favorites/playing snapshots/thumbnail/votes; trends only across **observed** snapshots). Existing `star/roblox_api_dataset.py`, `star/roblox_api_checker.py`, `star/roblox_docs_live.py`, `star/studio.py`, `star/studio_lab.py`, `star/roblox_cloud.py` remain the technical API and game-building systems. This PR deliberately does **not** replace them with unreviewed parallel implementations.

## Owner-configured creator analytics (strictly opt-in)

1. Use Creator Hub to create a Roblox Open Cloud API key for experiences where you are authorized, scoped narrowly to `universe.analytics:read`. An API key for another experience or lacking the scope will get 401/403; STAR must never attempt cookie/session scraping. The key must already be saved using STAR's existing **Settings → Roblox** credential store, or an established owner-managed environment/key file method. Never paste keys into GitHub, chat logs, PR descriptions, Discord, or the game's source tree.
2. Locally and explicitly set `STAR_ROBLOX_ANALYTICS_UNIVERSES=12345,67890` (replace with actual owner-authorized Universe IDs). No default allowlist: private analytics tools are **not even offered** in STAR Chat without it. Restart STAR to load the list.
3. Enable STAR's existing Roblox research tool access in the UI. Ask `Show Roblox analytics DAU for universe 12345 from 2026-10-01 to 2026-10-15`. The same approved key is used on the specific endpoint; no key value is shown to the model or returned.
4. The backend accepts exactly 10 documented metric IDs (DAU, MAU, visits/sessions, average playtime/session duration, D1/D7/D30 retention, revenue, payer conversion). It enforces metric-appropriate granularity, a fixed 1–90-day window, optional Country/Platform/OperatingSystem groupings, a cap of 12 series × 93 points, and refuses non-numeric/ill-formed responses. Roblox may restrict longer data windows for particular metric categories; these are deliberately excluded.
5. For a slow analytics request, Roblox responds with `done:false`; STAR returns **pending**, with a validated operation ID, never a fabricated graph. Ask STAR to poll that ID later. No unbounded polling loop or blind retry on server errors.
6. Do not treat public experience playing snapshots as DAU, retention or revenue. Do not treat aggregate creator metrics as individual-player profiles.

**Security:** The code accepts only two fixed hosts (`apis.roblox.com` and `catalog.roblox.com`), fixed paths, numeric resource IDs, bounded outputs, no redirects, no cookies, no arbitrary tool-chosen URLs, and never adds secrets to JSON tool responses. The pending operation path is accepted only if it matches the original authorized universe ID. Cloud errors are sanitized. Owner approval grants analytics to explicit IDs, not other experiences.

## Private player statistics: explicitly *not* enabled

Roblox stores player inventory/progression under each developer's own DataStores, with developer-defined schemas. There is **no global public endpoint** to query every user's private XP, inventory or save data. STAR's existing cloud implementation can list **data store names** for the selected authorized private test experience but does not expose raw entry contents. Future optional DataStore entry reading would need per-experience scope, an owner-only UI, privacy/retention, redacted previews, precise entry IDs, no model generalization of one person's record, and protected tests. No production player-data access is granted by this PR.

## Gameplay intelligence: what exists and what requires real native evidence

- STAR may infer *tentative* genre hypotheses from public descriptions (already implemented). Roblox thumbnails are marketing materials, not proof of mechanics. YouTube metadata is not watched footage.
- Native Studio MCP + Studio Lab has approval gates and existing tests. An authorized owner-selected unpublished experience can produce exact script/hierarchy/console/probe/screenshot evidence if the native bridge and Studio are actually active.
- New telemetry **plan** names custom/progression events; the next stage is an actual owner-approved Luau integration using `AnalyticsService:LogCustomEvent` and progression/event APIs, with privacy review and test place runs.
- Do not claim STAR has watched third-party gameplay or obtained inaccessible player statistics.

## Acceptance / test matrix

- [x] New fixed-endpoint client and STAR-chat tool registration implemented in private branch; no hosted cloud key stored in source.
- [x] Offline mock tests added for fixed hosts, public catalog metadata, schema bounds, authorization deny, unknown metric and granularity, 401/403/429/error, async operation path-binding, no fabricated telemetry.
- [ ] Run focused pytest, Ruff, Pyright, whole test suite in owner environment. **Private GitHub Actions may be blocked by billing; do not mark green without evidence.**
- [ ] Test **real** GET public Marketplace and POST Creator Store in a disposable authorized setup; beta body/response format must be corrected if the API disagrees (no guessed success).
- [ ] Test analytics with an actual owner key restricted to a private test experience, including a valid metric, 202 operation polling, 401/403/429/error, no personal data and revocation.
- [ ] Test Windows packaged STAR chat, provider-boundary/privacy behavior, keyboard and tool output rendering, no leaked key or output.
- [ ] Only after test acceptance, prototype a visual **Roblox Intelligence** panel and analytics charts sourced from actual tool receipts (no fake graphs).
- [ ] Later consented player-save inspector and anonymized gameplay event dashboards, strictly for owned experiences and appropriate legal privacy policies.

## Follow-up roadmap, without pretending Roblox publishes unavailable data

1. **Live creator catalog compatibility:** version pin OpenAPI for Toolbox Service, typed category filtering, explicit beta status, bounded pagination/cursors, asset license/permissions verification, Studio import only after owner approval.
2. **Account-scoped analytics:** support richer metric/dimension combinations from https://create.roblox.com/docs/cloud/guides/analytics/metrics with a verified per-metric compatibility matrix; add alerts/error/performance reads only on a separately approved key and precise privacy rules.
3. **Gameplay test lab:** use official Studio MCP, game event telemetry, controlled player simulations and video frame analysis on owned games; store hashed source/rig/build/test/scene evidence and independent gameplay acceptance.
4. **Player progression:** explicit per-experience data store listing and opt-in schema-aware support tools; **no** global player tracking or access to other games' private save data.
5. **Intelligence dashboard:** React view with public vs private tabs, metric units, timestamps, source links, query costs/limits, chart pagination, age-appropriate privacy and screenshot QA.

Primary sources: https://create.roblox.com/docs/cloud/guides/analytics , https://create.roblox.com/docs/cloud/guides/analytics/metrics , https://create.roblox.com/docs/cloud/reference/features/analytics , https://create.roblox.com/docs/cloud/reference/features/creator-store , https://create.roblox.com/docs/projects/assets/api , https://create.roblox.com/docs/reference/engine/classes/AnalyticsService , https://create.roblox.com/docs/cloud/reference/features/storage , https://create.roblox.com/docs/cloud/reference/rate-limits .
