# STAR Business workspace — initial integration

**Code stage:** reviewable development branch; NOT a production marketplace connector.  
**Data residency:** private per-user STAR app-data SQLite database.  
**Revenue:** not connected or verified. Never infer sales from draft counts.

This work builds on the existing `star/commerce/planning.py`, `star/commerce/art_quality.py`,
`star/delivery_package.py`, React 19 desktop and existing STAR design tokens.
It does not create a second UI, alter the main AI model, or grant an autonomous agent the
ability to publish, charge, message customers, or access private browser accounts.

## What works now

1. **Business** is a section of STAR's desktop sidebar. Browser `?preview=1&tab=business`
   shows a clear read-only zero state; it does not connect to a private database.
2. The installed desktop can create real **local candidate records** by marketplace,
   with an original brief and project isolation. Data goes to
   `<STAR_APP_DATA>/commerce/workspace.sqlite3`, never the Git repository.
3. The review desk validates evidence using the existing Etsy/Fiverr review standards.
   An owner can record originality, licensing, visual QA, buyer preferences, AI
   disclosures, mockup checks and print production sampling where relevant.
4. An explicit **Approve for export** click sets local status only after all required
   evidence fields are present. Changing the evidence resets previous approval.
   Evidence text is **seller assertion**, not independently verified copyright or art quality.
5. Duplicate titles within one project/channel, malformed identifiers, cross-project
   modifications and oversized inputs are rejected. No account login, network call,
   model request or publisher runs as a consequence of these actions.
6. The existing optional Playwright visual-audit script includes Business at desktop,
   small-desktop and phone viewports, checking control layout and browser a11y.

The backend action names are restricted to `commerceBoard`, `commerceCreate`,
`commerceEvidence` and `commerceReview`. No `commercePublish`,
`commerceSpend` or Fiverr messaging action is present. Unlike the AI chat tools,
these actions live inside the desktop's allowlisted Qt bridge.

## What is *not* built yet

| Capability | Verified development status | Next release gate |
|---|---|---|
| Etsy shop draft upload | Existing local research and assessment only | Seller-created app, OAuth PKCE, listings_w scope, sandbox verification, explicit owner permission |
| Shopify product drafts | Three live merchant-store drafts were created separately via authenticated ChatGPT tooling | Install merchant-approved Digital Products app, attach complete ZIP files, set price, verify checkout/payout and test downloads |
| Fiverr service workflows | Human-review draft planning only | Seller operates account; AI may prepare a customized proof and delivery packet, not a hidden inbox/gig bot |
| Payhip / Gumroad | Local concept pipeline only | Verify platform-specific approved integration surface before coding writes |
| Printify | Research and local physical-art gate only | Account + supplier economics + sampling + review of personalization before paid production |
| Continuous novel asset creation | Separate three-pack graphics prototype (not bundled with STAR) | User-approved original creative brief, licensed generation engine, distinctness testing, quota/cost ceiling, automated packaging, independent art review |
| Schedule and optimize | Not enabled | A production worker with rate limits, idempotency, real sales reconciliation, pause/stop, spending cap and alerts |
| Automatic revenue | Not possible to guarantee | Real demand, conversion, refunds, fees and business owner review |

**Shopify account connection in ChatGPT does not install any app or grant the STAR desktop
Shopify credentials.** The merchant must authorize each integration separately.
Existing Shopify drafts remain **drafts**, not live products. If Shopify Digital
Products is installed, buyers can get download links automatically only after files
are attached and the store is configured to sell.

## Engineering direction: one coordinator and one quality gate

- **GSD Core**: primary phase planning/workflow if the owner later installs it into
  their coding runtime. Do not run `npx` installers on an owner machine without
  examining their scripts, licenses and version pin.
- **Superpowers**: TDD, structured problem decomposition and review *practices* per task,
  rather than a second competing autonomous project manager.
- **Frontend Design + UI UX Pro Max**: design direction and an evaluated reference
  database; existing STAR data already includes UI UX Pro Max reference tables.
- **Anti-Slop**: evidence-based critique for generic labels, artificial metrics,
  missing states and accessibility. It is not a substitute for a `DESIGN.md`
  with project-specific visual direction.
- **Playwright**: inspect STAR's own preview and checkout *test environments*.
  Do not use it to stealth-automate Fiverr or circumvent Etsy auth.

The Business UI uses the existing OLED-neutral STAR tokens, system fonts,
semantic statuses, functional text hierarchy and reduced-motion support.
No ornamental fake earnings or animated payout numbers.

## Developer verification

From repository root:

```bash
python -m pytest -q tests/test_commerce_workspace.py tests/test_commerce_planning.py tests/test_commerce_art_quality.py
python -m compileall -q star/commerce star/react_shell.py
cd frontend
npm install --no-audit --no-fund
npm run typecheck
npm test -- --run src/commerce-panel.test.tsx
npm run build
```

For optional real-browser QA on a machine with Microsoft Edge and a reviewed
`playwright-core` install in `.local/tools`:

```bash
cd frontend
node scripts/visual-audit.mjs --tools ../.local/tools --strict
```

This test captures `?preview=1&tab=business` at 1280, 900 and 390 widths;
the test cannot demonstrate real Shopify checkout or installed Qt WebEngine.
Report visual findings rather than treating any one automated score as proof of taste.

## Next implementation milestones

1. Product **ProofPacket** intake from local authorized files, design provenance,
   design QA, uniqueness report, and explicit rights review.
2. Etsy **draft-only** authorized API adapter (OAuth PKCE, no raw token exposure
   to React), attach digital files and listing images only after seller verifies
   account, permissions and shop ID.
3. Shopify integration using least-privilege merchant authorization; preserve
   user-verified pricing and listings as drafts until merchant review.
4. A bounded production scheduler for *new* creative briefs, not palette-swapped
   copies; require novelty/provenance evidence and cost ceilings. Pause if a
   QA or licensing check fails, authorization expires or sales data are missing.
5. Revenue reconciliation from authorized receipts, handling fees, refunds,
   taxes and support obligations; no estimated sales disguised as real income.
6. Independent review and release through GitHub PR + CI. Live marketplace
   publishing/spend approvals must stay outside auto-merge and AI tool permissions.

## Official documentation

- [Etsy draft digital listings](https://developers.etsy.com/documentation/tutorials/listings/)
- [Etsy OAuth authentication](https://developers.etsy.com/documentation/essentials/oauth2/)
- [Fiverr responsible AI](https://help.fiverr.com/hc/en-us/articles/37554976380177-Using-AI-on-Fiverr-Guidelines-for-freelancers-and-clients)
- [Playwright browsers](https://playwright.dev/docs/browsers)
- [GSD Core](https://github.com/open-gsd/gsd-core)
- [Superpowers](https://github.com/obra/superpowers)
- [Anti-Slop](https://github.com/zansxart/anti-slop)
- [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)

## Opt-in, tools and owner approvals (integration, 2026-10-21)

- Setting `commerce_enabled` (Settings > Tools, off by default) switches on the Business tab, the Qt actions, the Commerce Pilot
  scheduler tick, the model tools below and the draft console (`python -m star.business.console`).
- Model tools (only when the prompt is about shops, listings, suppliers and so on): `star_commerce_overview` (read),
  `star_commerce_draft_candidate` (local draft), `star_commerce_propose_action` (a draft of a real-world action).
- Real-world actions (list or price a product, place or change an order, spend money, post publicly, message a customer, change
  a third-party account) exist only as proposals in `star/commerce/approvals.py`. The owner approves with the Approve button in
  the Business tab or `python -m star.commerce approvals approve ID --yes`, and an approved action runs once through a connector.
  Models cannot approve or run. No connector ships in STAR: the owner adds one with their own credentials, so until then an
  approved action stays approved and nothing leaves the PC.
- Approval is a confirmation, not a filter: no topic, wording or content checks. Evidence "blockers" are advice only.
- `star/business` (draft asset workforce, PRs #485/#505) and `star/commerce` (workspace, PRs #477-#486) are two halves of one
  feature: the workforce makes draft asset packs on a loopback page; the workspace holds candidates, monitoring and approvals.
  The console page ships in `star/data/business/` (already bundled by both Windows builds; replaces PR #508's build-file edit).
