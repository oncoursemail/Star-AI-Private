# STAR Commerce 2.0 — Going Beyond AutoDS with Evidence-Based Automation

**As of October 18, 2026.** This is development documentation for the existing STAR AI React + Qt desktop app. It is NOT a live dropshipping service or an installed always-on cloud agent. Dependencies: draft PRs #477 → #480 → #482 → #484 → this branch. Do not auto-merge.

## The key strategic decision

AutoDS already publicly offers automated order placement through Fulfilled by AutoDS, a multi-supplier catalog, hourly monitoring claimed on its API marketing page, listing imports, tracking updates, product research and multi-store workflows. Simply duplicating product search would not beat AutoDS. STAR should compete on *decisions across businesses*, with real financial attribution, carefully verified suppliers and support, safe permissioned execution, and measurable experiments.

This is not a promise of superior commercial performance. STAR must demonstrate that performance using matched, consented merchant tests.

## Specific relevance of the provided YouTube video

Dan Martell, "If I Wanted to Build a $10M AI Business (Zero Employees), I'd Do This": https://www.youtube.com/watch?v=w-XPlC3a2oI

An independently indexed chapter summary at https://videohighlight.com/v/w-XPlC3a2oI identifies the actual method:
- 00:42 design systems rather than add workers
- 01:28 identify customers' painful problems
- 03:16 talk with at least ten potential customers
- 03:37 manually validate a paid solution before automating
- 06:57 build a clickable prototype for feedback
- 08:44 focus on a small paid MVP
- 12:25 introduce AI workers as validated demand grows

The video was not directly playable in this research environment; this interpretation relies on an indexed third-party chapter summary, not on first-hand viewing of the full footage. The "$10M" title is a hypothetical ambition, not a verified result or likely revenue.

**STAR interpretation:** research → customer problem validation → legally verified supplier/source → strong product experiment → actual sale/fulfillment/returns data → *then* scaled automation. STAR should avoid spinning up dozens of clones of unvalidated businesses.

## Competitive coverage — vendor-claimed versus built versus planned

| Area | AutoDS vendor claims | STAR currently across PRs | Production requirement |
|---|---|---|---|
| Catalog discovery | Broad approved supplier network, filters and imports | Owner-imported supplier CSV, 1,000 items/business cap | Provider OAuth or documented APIs, source contracts, SKU normalization and region validity |
| Price/stock updates | Hourly monitoring on API page | Opt-in **local rechecks of imported records** and staleness alerts | Legitimate LIVE feed and monitored price/stock mapping |
| Fulfillment | FBA-style automatic purchasing, order and tracking service | No order spending/fulfillment | Authenticated paid orders, exact variant, idempotent supplier purchase, shipping exception handling |
| Supplier risk | Supplier filters | Quality, returns, stock, delivery and margin preflight + audit | Actual sample, QC, insurance/certification and seller-of-record due diligence |
| Product research | "Winning" products, trend evidence | Source-separated Google Trends / Keyword Planner / Merchant reports imports | Permissioned APIs, real market tests, uncertainty and cross-channel reconciliation |
| Multistore | Subscription-dependent | 100 private business records; **not 100 connected stores** | Merchant OAuth and isolation for each real authorized store |
| Customer support | Customer support and cases features advertised | Local policy-grounded drafts, no mailbox | Scoped Gmail/helpdesk OAuth, grounded Shopify order reads, issue escalation |
| Marketing | Price/listing optimization in eligible plans | Research matrix only; no paid ads | Owned Google/Meta/TikTok/Pinterest advertising accounts with daily/lifetime caps |
| Transparency | Independent verification needed | Explicit data origin, missing data, local audit, no imaginary sales | Real reconciliation and operational proof |
| AI shopping | Verify actual integrations | Research only | Shopify Agentic Storefronts, Merchant Center AI commerce reports |

Sources: https://www.autods.com/api/ ; https://www.autods.com/pricing/ ; https://help.autods.com/en/articles/12700443-automate-your-orders-with-fulfilled-by-autods-fba

## Recommended commerce infrastructure

**Merchant source of truth** — Shopify Admin GraphQL API 2026-10 for orders, payment/refund/fulfillment/inventory reports; built-in Shopify Flow for supported internal business triggers. Shopify's rate limits are query-cost weighted; handle throttling with backoff and bulk operations for large reads. The previously connected Shopify app inside ChatGPT DOES NOT automatically grant STAR Desktop those authorizations.

**Supplier strategy** — Shopify Collective first *after* the account meets eligibility: active plan, Shopify Payments with active payouts, compatible supplier country and currency, identity checks when required. Collective already handles supplier price/inventory and certain routing/cost workflows so STAR does not need to reinvent them. Also evaluate Printful, Printify, Syncee, DropCommerce, Spocket, DSers, Zendrop, CJdropshipping, and AutoDS as optional managed fulfillment based on documented availability, eligible geography, actual samples and true delivered costs. Never assume all of these offer arbitrary public APIs. Do not install five overlapping order processors with permission to fulfill the same paid order.

**Product intelligence** — product-market hypothesis, seller policy/legal rights proof, source SKU, variants/GTIN, source timestamps, price + landed shipping, estimated duties/refunds, category risk, sample photo similarity, lead time and in-market availability. Require measurements before any "winning product" claim. Use Google Trends as normalized relative search interest, Keyword Planner as approximate volume, Merchant Center clicks/impressions as the merchant's authorized performance; never call these competitor orders.

**Distribution** — start with official Shopify storefront SEO, accurate schema.org Product/Offer, quality photos, Google Merchant Center free listings, documented maker partnerships and eligible platform shopping surfaces. Then measured Google Ads, Meta Shopping/Conversions API, TikTok and Pinterest when accounts, privacy rules, conversion deduplication and budgets are authorized. Do not send unsolicited messages, run fake reviews, advertise prohibited categories or clone copyrighted competitor creatives.

**Agentic commerce discovery** — Shopify Agentic Storefronts/Shopify Catalog surfaces eligible products in AI-shopping experiences, and the new September 2026 Google Merchant Reports v1alpha includes UCP agentic product performance views. These are opportunities to optimize trustworthy product feeds and test discovery, not guarantees of AI placement or sales. The particular merchant's access varies by platform and rollout.

**Support service** — a dedicated business-owned support mailbox, not a made-up Gmail identity. The Gmail API requires consent and scope minimization; gmail.send is sensitive, gmail.readonly/compose/modify are restricted and may require security assessment for server-held restricted data. Gmail watch notifications expire and must be renewed at least every 7 days. Future workflow: webhook/watch → dedupe → protect from prompt injection → verify customer + order via owned Shopify → retrieve approved FAQ and actual shipping → evaluate answer → approved low-risk FAQ response or escalate. Refunds, payment changes, legal disputes, personal-data requests and unknown identity cannot be silent auto-replies. Track whether the business actually solved the issue, not just whether the AI answered quickly.

**AI/workflow engine** — a single designated queue owner. Shopify Flow for built-in triggers; n8n for vetted simple integrations (with secure credentials and optional Redis/worker queue mode); Temporal for durable, stateful order/refund workflows if scale justifies its infrastructure; LangGraph/STAR specialists for research and structured reasoning with approval interruptions. Do not chain overlapping n8n/Temporal schedulers without unique ownership and idempotency.

**Measurement/evaluation** — Shopify analytics as the orders ledger; GA4/PostHog for legitimate funnel measurement; optional Metabase/DuckDB/ClickHouse/dbt based on volume; Langfuse/OpenTelemetry for model quality, cost and latency with redaction. Compare production metrics to controlled holdouts, not marketing estimates. SQLite is appropriate for STAR's first local planning and safety records; remote multi-tenant workers require transactional coordination and audited authorization.

## Built now: STAR Commerce Pilot control plane

Code: star/commerce/autopilot.py. Qt integration: star/react_shell.py. Private storage: star/commerce/workspace.py. React UI: frontend/src/CommercePilot.tsx, commerce-pilot.css, CommerceDropshipping.tsx. Tests: test_commerce_autopilot.py and commerce-pilot.test.tsx.

The new Pilot provides:
1. Default-OFF per-Shopify-business settings with explicit owner consent: low-stock buffer, minimum modeled pre-ad contribution %, max reported delivery days, evidence TTL and interval minutes.
2. Manual bounded check of up to 1,000 owner-imported supplier offers.
3. A Qt timer that wakes every 15 minutes *while STAR Desktop runs*, reviews only due, enabled, unpaused businesses, and records only private findings. Up to 12 businesses are checked per wake. It has no network, email, publishing, ads, order or supplier-purchase capability.
4. Stable findings for zero/low supplier stock, insufficient hypothetical contribution, long lead times, missing sample, unavailable returns and stale source snapshots (product topics are never screened).
5. Evidence fingerprint deduplication; unchanged scans do not reopen reviewed alerts. Updated evidence can reopen risks. Cleared risks resolve. Max 10,000 rows and bounded audit retention per business.
6. Private source timestamps, review state and operational status in the same STAR Business dashboard. No fictitious revenue or verified supplier badges.

IMPORTANT: An hourly loop over a static imported CSV is **not live supplier monitoring** and cannot genuinely replace AutoDS's automated stock service. No independent remotely hosted 24/7 service is deployed. STAR only works while the local desktop app runs, and source updates still require authorized imports. Every external action is disabled.

## Real production control plane specification

### A. Legal and checkout readiness

Merchant must authorize storefront account, real tax configuration, bank/payment verification, shipping/returns terms, supported goods and supplier samples, and run genuine test orders. Avoid broad generic dropshipping onto Etsy: ready-made mass-market reselling is generally prohibited, whereas original seller-designed production-partner products can be permitted with required disclosures. Amazon requires the seller of record and compliant packaging. FTC Mail/Internet Order Rule requires reasonable shipping promises and delay consent/refunds.

### B. Explicit capabilities, not prompt-only permissions

Each provider capability must be an authenticated structured object: provider, store ID, OAuth scope, access expiry, allowed action, product/SKU selection, dollar cap, authorization ID, idempotency key and approval time. Exact store/budget/price must be revalidated at the write boundary even after earlier approval. One supervisor may approve a contract for low-risk automatic operations, but a model cannot grant itself additional scopes, mark checks passed, increase budgets or change security policies.

### C. Event-driven ingestion with replay defense

Shopify webhook: validate HMAC over raw POST body before parsing; constant-time compare; verify allowed shop/domain/topic; dedupe X-Shopify-Webhook-Id, preserve event's source timestamp and reconcile out-of-order events. Use a durable task queue with retries/backoff, dead-letter alerts and on-demand reconciliation. Timeouts on order placement are ambiguous; query the supplier by idempotency key before retrying. Always reconcile a paid Shopify order to exactly one seller-approved supplier order. No fulfillment or refund without authority.

### D. Honest profit optimization and attribution

For each actual order reconcile:

    booked retail - discounts - supplier invoice - shipping/duties
    - processing/platform fees - refunds/return shipping/chargebacks
    - attributable ad spend - variable customer support and tax/other obligations

Track unknown costs as missing, not zero. Calculate SKU contribution, campaign CPA, ROAS, MER, on-time fulfillment, refunds and confidence intervals. Maximize **reconciled post-ad contribution** with bounded experiment budgets, not gross revenue. Stop bidding immediately on stockouts, unacceptable defects/returns, negative contribution or unknown fulfillment status. User approval must precede campaign creation and a known budget.

The previous STAR sales-learning branch explicitly warns that Shopify session methodology changed in September 2026: segment time windows and do not equate a tracking change to increased conversion.

### E. Safe customer-answer benchmark

Construct an owner-approved, redacted evaluation set across languages and urgent intents. Grade retrieval provenance, exact order-match correctness, claim correctness, escalation recall, toxicity and readability. Require zero wrong promises of tracking/refund/order status. Only well-measured, low-risk FAQ replies may become eligible for an owner-authorized auto-send; all legal/refund/payment disputes escalate.

### F. One-dashboard metrics

Sources and denominators visible beside all metrics:
- Sales: gross sales, net sales, fulfilled paid orders, refunds, cancellations, actual processing fees, supplier invoices, contribution.
- Discovery: approved SKUs, verified demand tests, product feed errors, marketplace disapprovals, impressions, clicks, conversion *with matching sessions*.
- Marketing: organic/paid split, CTR, CPC, CPA, ROAS with attribution windows, net marginal contribution, holdout test status.
- Supplier: in-stock confidence, source-age SLA, variant mapping, shipping lateness, landed cost variance, defects and returns.
- Customer support: queue, first-response time, resolution time, sentiment/CSAT when surveyed, escalations and reopen rate.
- Safety: connector permissions, paused accounts, model hallucination catches, webhook duplicates, run failures, unauthorized write blocks, costs at risk.

## Launch gates and proof required before claims of "better" or "fully automatic"

1. Upgrade/activate Shopify and verify payments/identity; connect one approved supplier using a legitimate app or API; obtain sample proof.
2. Test a small curated catalog and accurate free-listing feed. Run source-specific profitability math and collect genuine checkout measurements.
3. Make supplier sync authoritative with freshness, timeouts and stockout protection; schedule only in a durable always-on environment.
4. Establish authenticated mail support with grounded FAQ and strict escalation, never unauthorized autoreplies.
5. Start approved tiny ad experiments with caps and verified purchase events, measure real contribution and stop losses.
6. Stress-test 1,000 duplicate/out-of-order webhooks, provider failure during supplier purchases, crash/restart recovery, refunds/chargebacks and stale data. Zero double purchase in all replay simulations. Keep full per-business audit and kill switch.
7. Compare end-to-end results against a legally configured AutoDS pilot with *matched* sample SKUs and budget. Do not assert superiority without results.

## Source index (official unless specifically noted)

- AutoDS API and fulfillment https://www.autods.com/api/ and https://help.autods.com/en/articles/12700443-automate-your-orders-with-fulfilled-by-autods-fba
- Shopify 2026 automation overview https://www.shopify.com/blog/automated-dropshipping
- Shopify Flow https://apps.shopify.com/flow
- Shopify Collective eligibility https://help.shopify.com/en/manual/online-sales-channels/shopify-collective/retailers/requirements-and-considerations/
- Shopify Admin GraphQL and rate limits https://shopify.dev/docs/api/admin-graphql/latest and https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits
- Verified Shopify webhooks https://shopify.dev/docs/apps/build/webhooks/verify-deliveries
- Agentic Storefronts https://help.shopify.com/en/manual/online-sales-channels/agentic-storefronts/products
- New Google Merchant UCP alpha reports https://developers.google.com/merchant/api/release-notes/rest/reports
- Merchant product reports https://developers.google.com/merchant/api/guides/reports/overview
- Merchant free listings https://support.google.com/merchants/answer/13889434
- Printful API https://developers.printful.com/docs/
- Gmail OAuth scopes and watches https://developers.google.com/workspace/gmail/api/auth/scopes and https://developers.google.com/workspace/gmail/api/guides/push
- n8n worker queues https://docs.n8n.io/deploy/host-n8n/configure-n8n/scaling/enable-queue-mode
- Durable Temporal activities https://docs.temporal.io/activity-definition
- LangGraph interrupts https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph
- Langfuse evaluations https://langfuse.com/docs/evaluation/overview
- FTC Shipping Rule https://www.ftc.gov/legal-library/browse/rules/mail-internet-or-telephone-order-merchandise-rule
- Etsy reselling policy https://help.etsy.com/hc/en-us/articles/23948763872151-Does-Etsy-Allow-Drop-Shipping-or-Reselling
- Video secondary chapter outline (not full video playback): https://videohighlight.com/v/w-XPlC3a2oI

## Required independent verification before merging

    python -m compileall -q star/commerce star/react_shell.py
    python -m pytest -q tests/test_commerce_autopilot.py tests/test_commerce_dropshipping.py
    npm run typecheck --prefix frontend
    npm test --prefix frontend
    npm run build --prefix frontend

Pass the full repository's Python/React/Windows CI, native desktop QA, accessibility/reduced motion/keyboard tests, security checks and stacked PR reviews. Preserve existing STAR app and public GitHub release channel. Do not publish an installer from this development branch. No secrets or buyer data belong in the public repository.

**Actual status:** STAR's new opt-in LOCAL scheduler, review queue and audit are implemented as development code; real external credentials, live supplier monitoring, 24/7 hosted service, Gmail account/sending, paid ad automation, checkout, supplier ordering, refunds and guaranteed profit are still NOT implemented or connected.
