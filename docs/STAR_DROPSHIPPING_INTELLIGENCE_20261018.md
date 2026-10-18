# STAR Business — Dropshipping Intelligence, Distribution and Support

Status: **draft implementation, October 18, 2026**. Depends on PRs #477 (Business workspace), #480 (Mission Control) and #482 (seller aggregate learning). Not shipped in the STAR Windows release, not merged into main, and not an activated dropshipping company. This is the **existing** STAR React + Qt application, not a replacement app.

## 1. Implemented in this branch

The new private Business / Shopify / Dropshipping desk provides:

- Deterministic supplier-catalog CSV validation, 150 rows per transaction, 1,000 offers per business, deduplication and source timestamps. One supplier/SKU belongs to one STAR project and business. The original CSV is not saved; normalized supplier data is stored in the existing private app-data SQLite DB. There is no web fetch, scraper, or supplier access.
- Immediate math-based screening: declared stock, shipping duration, sample review, supplier return eligibility, sensitive-category preflight, target selling price, product and delivery costs, estimated transaction cost, 5% reserve, break-even customer-acquisition cost (CPA) and break-even return on ad spend (ROAS). Passing is **not** certification, a listing, a validated supplier or evidence of demand.
- Three distinct imported demand-signal formats with bounded, date-stamped readings: Google Trends normalized indexes, Google Ads Keyword Planner historical monthly search-volume figures, and Google Merchant Center clicks. Values are self-reported by the importer. They cannot be combined into a unitary competitor sales/revenue estimate.
- One private support policy record per business and on-demand deterministic support-response drafting from customer queries. Never records the input inquiry, promises order tracking or a refund, opens Gmail, or sends any message.
- An OLED STAR-native panel with product economic breakdowns, signal records, truthful zero states and five **disconnected** distribution routes: Merchant Center, Google Ads, Meta, TikTok and Pinterest. No badges claiming live integrations.
- Explicit owner permission on input imports and policy saves; safe/idempotent imports; separate local bridge allowlist; no expenses, publication, email auto-send, marketplace or payment actions.

### Supplier CSV

Header must match exactly:

    supplier,sku,title,category,product_url,unit_cost,shipping_cost,target_price,stock,delivery_days,returns_supported,sample_reviewed

Money values are nonnegative **USD decimal amounts**, max two decimals; unit cost and target price must be greater than zero. Stock is a vendor-reported integer, not an inventory guarantee. Delivery days are estimated days and must be independently verified by destination. Use yes/no flags; samples and return support should be marked yes *only* on actual supporting evidence. Supplier URLs must be HTTPS, are never fetched by STAR, and are informational only.

STAR uses estimated per-order pre-ad contribution:

    P - unit cost - supplier delivery cost - (0.029 * P + 0.30) - (0.05 * P)

All calculations use integer cents for recorded prices, and modeled fractional fee/reserve rounding; never report this as accountant-verified net profit. The 2.9% + $0.30 processing fee and 5% reserve are **illustrative assumptions**, not verified fees, current Shopify rates, an industry-average claim, or measured refund rates. Excludes VAT/sales tax, discounting, software, owner labor, processing variations, duties, chargebacks, returns postage and advertising. Treat contribution as an early **screen**, with a real merchant cost model replacing these assumptions before any go-live.

    hypothetical break-even CPA = max(0, pre-ad contribution)
    hypothetical break-even ROAS = retail price / pre-ad contribution when positive

A 20% contribution threshold is a screening policy, not a profitability guarantee. All candidate prices and costs must be rechecked immediately before publishing or fulfilling.

### Research CSV

    sku,source,metric,value,observed_on

Allowed paired enums: google_trends/trends_index (0–100), google_ads_keyword_planner/monthly_searches, merchant_center/merchant_clicks. The SKU must exist in the selected Shopify-business local catalog; observed_on is a past UTC calendar date.

**These are not direct competitor sales.** Google Trends is sampled/normalized interest; Keyword Planner volumes are historical estimates; Merchant Center clicks refer only to authorized account data. None of these sources establishes that a product is profitable, patented, safe, licensed, or sold in a particular quantity. Keep individual sources, dates and denominators visible; do not train on scraped private account data.

### Support safeguards

The supported inbound text is classified *locally* into general, shipping/tracking, returns/refunds or urgent disputes. Templates rely only on owner-confirmed generic store policies and always mark **review_required=true** and **auto_send_allowed=false**. STAR never verifies a buyer, looks up an order, gives shipment tracking, triggers a refund, responds to email or stores the pasted inbound body. Arbitrary customer text is untrusted content, not an instruction or a new source of truth.

## 2. Blueprint for real near-unattended commerce (future phases)

**Gate 0 — seller readiness.** Merchant must complete identity/payment verification, domain, taxes, shipping/return policy, consumer disclosures, a valid support channel and test order. The connected Shopify account in ChatGPT does **not** grant the STAR desktop app an OAuth token. A trial Shopify store may require a plan upgrade to start sales.

**Gate 1 — authorized catalog discovery.** Use a supplier-approved API or catalog feed for Printify, Printful or another vendor with documented credentials/permissions. Collect UPC/SKU, catalog region, stock/availability, COGS, shipping by destination, lead time, tracking, supplier identity, refund terms, packaging, QA sample results and certificates where needed. Normalize records with source timestamp, currency and supplier ID. For open-web trend research use only permitted public or licensed data, not concealed competitor dashboard data. Every imported offer is a *candidate*, not a storefront listing. Update changed/removed variants and automatically hold listings when inventory or quality evidence expires.

**Gate 2 — product experiment and rights.** Verify product originality/branding rights, product safety and supplier reputation. Order test samples with a user-set procurement budget and approval; inspect physical quality and shipping time. Use a product score built from measurements, not hallucinated popularity. Small stratified experiments with holdout periods should test assumptions. Product photos must represent actual deliverables. Supplier abuse, inaccurate return estimates, brand impersonation and forbidden categories require rejection.

**Gate 3 — storefront and inventory.** Create a Shopify app under the merchant's account with least-privilege official Admin GraphQL scopes. Start with products/inventory/orders **read** scopes. Use official product-write scopes only after documented authorization, review, and dry-run validation. Treat any publish action as a separate gated queue (SKU/source proof, images, product claims, shipping zone, review date). Shopify webhooks or Events synchronize order/payment/fulfillment/refund/inventory changes; verify HMAC over the raw request body, dedupe delivery IDs and recover out-of-order events with timestamps and periodic reconciliation. Do not use a fabricated checkout or mark payment paid before confirmation.

**Gate 4 — automated fulfillment, bounded.** Connect one vetted supplier order API and test order confirmations/tracking/refunds. Map exact variants, calculate payable cost before submitting, obtain destination/legal compatibility, and place purchase orders **only** under explicit account permissions and per-order/daily budgets. Need idempotency keys, order-status state machine, retries/backoff, backorder holds, inventory TTL, address/data minimization, substitution prohibition, delivery exceptions and a stop switch. Fail closed on mismatched totals, missing variants, absent customs information or expired stock. No silent purchases.

**Gate 5 — trusted customer service.** Provision a dedicated company-controlled support mailbox (e.g., support at the merchant's authorized domain) through Google Workspace or another provider; an AI cannot create/verify Gmail identities autonomously. Implement OAuth consent using minimum scopes. Gmail read/modify scopes are *restricted* and app verification and potentially a security assessment apply, especially if restricted data is transmitted/stored on servers. For a native desktop account, use authorized client sync; for a backend webhook worker, Gmail's Pub/Sub watch and incremental history can reduce polling. Gmail watches expire and require renewal (at least every seven days). Keep access tokens in the OS credential store or audited secret vault, never GitHub.

  Support pipeline: new email → deduplicate message/thread → redact credentials/PII → classify language, intent and risk → retrieve exact order from verified merchant API *only when sender identity is validated* → retrieve current published policy and confirmed shipping/fulfillment status → ground a multilingual response with citations/evidence → send safe low-risk FAQ replies only after configured high-quality evaluation gates → log audit/outcome in private storage → suppress duplicate replies. Always escalate disputes, legal threats, chargebacks, refund commitments, personal-data requests, threats, atypical damage, payment edits, harassment, and uncertain facts. Enforce rate limits and prevent marketing spam. No impersonation of the merchant or fabricated promises. Provide clear contact with a human and escalation SLA.

**Gate 6 — real distribution without spam.** Google Merchant Center free listings via Merchant API require accurate product/price/availability data, a verified merchant account and policy-compliant return/shipping descriptions. Add schema.org product pages and SEO. For paid reach, connect Google Ads (Search/Shopping), Meta Ads, TikTok Ads and Pinterest through each platform's **official** authorization and approved APIs; no mass-account bots, unconsented DMs, fake reviews or misleading creatives. Feed only consented, properly disclosed conversion events. Use a gradual cohort-based advertising test plan, frequency caps, exclusions, quality signals and owned creative variants. Reach is limited by policy, budget, audience size and conversion quality, not promised to be unlimited.

**Gate 7 — experiment budget guard.** Advertiser starts with daily and lifetime budget caps, allowed channels/countries, product margin floors, campaign pause button and receipts. Ads remain proposal-only until explicitly enabled. Programmatic bid changes should be limited by max adjustment per 24 hours and by a minimum data threshold. Pause on supplier stock issues, severe ROAS decline, payment processing incidents, complaints or chargeback rise. Optimize *contribution after variable costs* and support costs, not revenue alone. Provide a frozen baseline and holdout; never auto-increase spending because a LLM predicts a bestseller.

**Gate 8 — dashboard and learning.** All metrics must carry source, date coverage, timezone/currency, sampling caveats and quality flags. The source of truth is the seller's own authorized orders, costs and platform-advertising reports. STAR should expose:
- Commerce health: actual orders, revenue, refunds, cancellations, gross margin, estimated and reconciled contribution, stockouts, fulfillment latency, returns, supplier defects and support backlog.
- Acquisition: channel spend, impressions, clickthrough, average CPC, sessions, verified checkout conversion, CAC, ROAS, marketing-efficiency ratio (MER), marginal contribution and campaign confidence interval.
- Customer outcomes: first-response time, verified resolution time, SLA breaches, CSAT from customer opt-in surveys, repeat-order rate, support escalation and refunds.
- Growth: supplier hit-rate, sample failure-rate, approved-to-live ratio, experiment log, novelty/compliance risk and time-to-first-sale. Always separate exploratory statistics from causal evidence.

In time-series analysis, maintain calendar holdouts; never confuse September 2026 Shopify session-methodology changes with genuine conversion improvements. No real orders means show zero orders, not forecasts masquerading as sales.

## 3. Channel policy matrix

| Channel | Appropriate use | Restrictions |
|---|---|---|
| Shopify | Main store for independently compliant dropshipping | Retailer remains responsible for goods, shipment claims, customer returns, product safety and consumer law |
| Printify / Printful | Print-on-demand supplier for **owned/licensed** designs | Verify variant, shipping, quality sample and synchronization; production partner does not give design rights |
| Etsy | Seller-designed originals with disclosed print-production partners; certain permitted craft supplies | General mass-produced ready-made dropshipping/reselling is prohibited; do not auto-post wholesale catalog |
| Amazon | Carefully verified seller-of-record fulfillment (if authorized) | Merchant must be seller of record and packaging/paperwork must not identify other merchants |
| Google Merchant Center | Free approved product discovery; later Shopping Ads | Accurate price, shipping, availability, business identity and functioning refunds |
| Meta / TikTok / Pinterest | Organic creator content; policy-compliant paid marketing after approval | Authorized account/API, clear disclosures, consented conversion tracking and budget caps |

Do not use Etsy as a generic AliExpress resale outlet; do not use Amazon-to-Amazon fulfillment where the shipping customer sees another retailer's branding.

## 4. Reliability and operations architecture

Proposed components inside the existing STAR runtime:

    STAR Business Mission Control (React/Qt)
      ├── local supplier / demand + policy DB (implemented)
      ├── aggregate sales learning by business (existing PR #482)
      ├── permission manager + official OAuth / tokens (NOT implemented)
      ├── connector runners for Shopify, suppliers, Merchant, ads (NOT implemented)
      ├── webhook ingestion + signature/duplicate verification (NOT implemented)
      ├── product creative + compliance gate (future)
      ├── customer service Gmail handler + exact order grounding (future)
      ├── spend/risk authorization ledger + fail-closed state (future)
      ├── bounded scheduler with cancel, retry and dead-letter queue (future)
      └── continuous experiment/evaluation reports + human review (future)

Concrete background tasks must have per-connector minimum intervals, versioned configuration, schema validation, token refresh, priority scheduling and deterministic idempotent handlers. STAR can delegate bounded research/description/creative tasks to local AI models, but the model must not hold permission to spend money, send arbitrary Gmail messages or rewrite the approval policy. All external content can contain prompt injections, so customer/supplier emails and web pages are never trusted control instructions. "Fast" means event-driven ingestion, batched analytics and caching with rate-limit compliance, not unsafe polling or skipping QA.

The best initial paid-ad strategy is **no ad spend until a trustworthy storefront, payment test, sample quality and per-order contribution baseline exist**. Start with organic and eligible free-listing discovery to validate product-market fit; authorize small ad experiments only with a loss budget and verifiable attribution.

## 5. Official references consulted, October 2026

- Shopify dropshipping compliance: https://help.shopify.com/en/manual/compliance/legal/dropshipping
- Shopify Admin API: https://shopify.dev/docs/api/admin-graphql/latest
- Shopify webhook HMAC, duplicates and ordering: https://shopify.dev/docs/apps/build/webhooks
- Printful supplier product/fulfillment API: https://developers.printful.com/docs/
- Etsy seller policy: https://www.etsy.com/legal/sellers
- Etsy dropshipping exception and production partners: https://help.etsy.com/hc/en-us/articles/23948763872151-Does-Etsy-Allow-Drop-Shipping-or-Reselling
- Amazon dropshipping seller-of-record policy: https://sellercentral.amazon.com/gp/help/external/help.html?itemID=201808410&language=en_US
- Merchant API product inputs: https://developers.google.com/merchant/api/guides/products/overview
- Google Merchant Center misrepresentation enforcement: https://support.google.com/merchants/answer/6150127?hl=en
- Google Ads Keyword ideas: https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas
- Google Ads budget services: https://developers.google.com/google-ads/api/docs/campaigns/budgets/create-budgets
- GA4 Data API rate limits: https://developers.google.com/analytics/devguides/reporting/data/v1/quotas
- Gmail API OAuth and restricted scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- Gmail push/watch: https://developers.google.com/workspace/gmail/api/guides/push
- Gmail send API: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
- US FTC online merchandise shipment rule: https://www.ftc.gov/business-guidance/resources/business-guide-ftcs-mail-internet-or-telephone-order-merchandise-rule

## 6. Verification and release

    python -m compileall -q star/commerce star/react_shell.py
    python -m pytest -q tests/test_commerce_dropshipping.py tests/test_commerce_sales_learning.py tests/test_commerce_mission.py
    npm run typecheck --prefix frontend
    npm test --prefix frontend
    npm run build --prefix frontend

CI and Windows-packaged UI smoke tests must run before anything merges. Independently review new native bridge actions and all public source changes. No credential, customer email, order record, payments or store secrets are placed in the public repository.

**Actual limits today:** research imports and policy drafts are local prototypes; no automatic supplier/product feed, real-time Shopify data feed inside STAR, Google Ads campaigns, Gmail account creation, Gmail sending, inventory purchases or refunds. External integrations and guaranteed profits must not be described as completed.
