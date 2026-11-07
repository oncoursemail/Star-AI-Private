# STAR Business Mission Control — multi-business portfolio

**Status (2026-10-18):** reviewed source branch, stacked on draft Business Workspace PR #477. Not merged into main, not an installed STAR release, and not connected to marketplace seller accounts.

## Implemented in this milestone

- A STAR-native Mission Control panel, integrated into the existing React/Qt Business workspace.
- Up to 100 **local business records** (a record is not a verified real marketplace shop).
- Brand name, customer niche, planned marketplace and initially paused local work.
- Link existing product candidates to a matching-marketplace business, resetting any earlier export approval.
- A durable SQLite checklist work queue, deduplicated by product brief/review fingerprint.
- Explicitly initiated batches of up to 20 deterministic checks, with fair round-robin selection between unpaused businesses.
- Stop/pause a business's local checks or cancel a queued local work item.
- A private, timestamped history of local actions. No fabricated revenue.
- Mobile-responsive UI using Star's existing OLED design tokens, type scale, focus states and reduced-motion policy.

These checklist results are **not proof of copyright ownership, commercial safety or artistic quality**. The owner must inspect the actual work; the queue only checks whether specified evidence and disclosure fields have been supplied.

## Files and integration contract

- star/commerce/workspace.py: existing project-specific candidates, review and permission boundaries.
- star/commerce/mission.py: additive migrations, local portfolio, fairness, idempotency, manual work checks and audit history.
- star/react_shell.py: explicit allowlist for the six additional local Qt actions, with lazy commerce loading.
- frontend/src/CommercePanel.tsx: adds portfolio filter, candidate assignment and QA queueing.
- frontend/src/CommerceMissionControl.tsx: portfolio operations page, bounded work button, history.
- frontend/src/commerce-mission.css: Star-native responsive styling, no second design system.
- tests/test_commerce_mission.py: migration, isolation, fairness, replay, pause and permission coverage.
- frontend/src/commerce-mission.test.tsx: behavioral user-interface tests.

STAR stores everything in the existing private per-user app-data commerce/workspace.sqlite3 database. The migration adds an optional business_id to commerce_ideas, preserving old candidates as unassigned. Nothing is stored in the public GitHub repository except code and tests.

The new bridge actions are commerceCreateBusiness, commercePauseBusiness, commerceAssignBusiness, commerceQueuePreflight, commerceRunPreflight and commerceCancelPreflight. No action performs external network calls, posts listings, sends customer messages, moves money or executes arbitrary AI-generated code. The browser preview does not read the private database.

## Operation lifecycle

1. The owner creates a local business record, initially paused.
2. A candidate is assigned to a matching platform; prior export approval resets on reassignment.
3. A deterministic checklist job is enqueued. A duplicate unchanged request returns the same queue item instead of creating another.
4. The owner explicitly resumes local checks for that business and runs a bounded batch.
5. The checker re-reads the current candidate fingerprint. Stale work is invalidated if evidence or assignment changed.
6. The checker returns needs_evidence or review_ready, never automatically approved, exported or published.
7. The owner inspects original source files, licensing, art and disclosures, and uses the separate explicit review action from PR #477.
8. All recorded activities remain project-scoped and restart-safe in SQLite.

The job queue is NOT a real autonomous background scheduler. Its purpose is to establish a reliable, observable, bounded internal work contract before adding external API credentials or worker infrastructure.

## Why not install every agent framework at once

GSD Core, Superpowers, Anti-Slop and UI UX Pro Max help developers plan, review and design; none is a replacement for transactional idempotency, rate limiting or verified marketplace authorization. Star already ships a design database and Playwright visual audit. A production worker should be added only when necessary, with benchmarks demonstrating need. Heavy frameworks (Temporal, Kafka, a standalone vector database, etc.) require an explicit cost and operational justification instead of being installed indiscriminately.

## UI design principles

- Preserve STAR's existing OLED tokens, system typography, concise warm-gold affordances and semantic statuses.
- Use a human-readable business portfolio and bounded operations stream rather than huge decorative fake analytics cards.
- Show actual local candidates, not imaginary revenue, conversion, orders or connected sellers.
- Distinguish "local checklist ready" from "seller-approved ready to publish".
- Responsive at phone, small desktop and large desktop widths; keyboard navigable with visible focus and accessible labels.
- No unaudited external images or copied interfaces, no stock gradients and no nonfunctional controls.

The STAR GitHub Pages public marketing site must not expose an owner-only business database or claim this unmerged feature is shipped.

## Verification

Execute from the repo checkout after installing reviewed dependencies:

    python -m compileall -q star/commerce star/react_shell.py
    python -m pytest -q tests/test_commerce_mission.py tests/test_commerce_workspace.py tests/test_lazy_pil.py tests/test_rbx_chat_attachments.py
    npm install --prefix frontend --no-audit --no-fund
    npm run typecheck --prefix frontend
    npm run test --prefix frontend
    npm run build --prefix frontend

Optional browser visual audit after reviewing a compatible Playwright installation:

    cd frontend
    node scripts/visual-audit.mjs --tools ../.local/tools --strict

Check 390, 900 and 1280 px layouts, focus indicators, long business names, large text, permission refusals, restart persistence, tests for 100 records and no external marketplace side effects.

## Next PRs — subject to account-specific approval

1. Source-file intake, signed/hash-verified deliverable packages, original rights and design QA.
2. Owner-authorized Shopify and Etsy draft-only API adapters with OAuth, secret isolation, retry/idempotency and shop ownership verification.
3. Real event and order ledger from authorized signed webhooks, reporting actual fees/refunds/net contribution without fictional numbers.
4. Per-business background worker behind owner-enabled feature flags, strict model/API budgets, cancellation, backpressure and security audit.
5. Original, differentiated asset-production engine: seller-approved briefs, licensed image engines, editable SVG/PNG files, provenance, uniqueness warnings and human creative review.
6. Owner-authenticated hosted dashboard only if needed; keep customer data and tokens away from public GitHub Pages.

Fiverr remains a client-specific, meaningful human-delivery platform: no hidden automated Fiverr seller bot. Printify personalized orders and spend require human approval. Etsy creativity/disclosure policy must be checked using official published guidance, not third-party marketing claims.

**Release gate:** this stacked PR is not a live business or guaranteed source of revenue. Preserve PR #477 and existing STAR releases, run independent CI, review code and rollback paths before merger.