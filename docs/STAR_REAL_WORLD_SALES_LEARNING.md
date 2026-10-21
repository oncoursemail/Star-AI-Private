# STAR Commerce: real-world sales learning and calendar timing

**As of October 18, 2026.** Development branch stacked on Business Mission Control PR #480, which is stacked on Business Workspace PR #477. This is not merged or included in the released STAR installer.

## What actually works

This milestone implements a **local, evidence-first observational learning service** and a STAR-native Business dashboard section for individual, owner-defined businesses. Unlike a machine that continuously changes its model weights, it updates deterministic analysis as the owner imports authorized daily seller totals.

- Paste **customer-free daily aggregates** from a report you have permission to use. The data must be normalized to STAR's eight-column CSV format and must include zero-order dates.
- The backend validates the exact schema, date formats, numeric limits, two-decimal money, permission declaration, one currency/timezone per business and per-day uniqueness.
- Imports are transactional, project-scoped, repeat-safe, bounded to 200 rows/import and 3,000 dates/business. A conflicting existing day cannot be changed unless the owner explicitly selects replacement. A duplicate unchanged day is a no-op.
- Only aggregated daily metrics are stored in the private STAR application data database. The code does not accept customer names, addresses, order IDs, arbitrary columns, or raw purchase histories.
- Show real observations for days 1–10, 11–20 and 21–last day, weekday patterns, and month-of-year summaries. The dashboard displays dates, session reporting, coverage, order counts, and optional contribution estimates only when all relevant cost fields have been supplied.
- Recalculate after every import. For a stronger time-of-month hypothesis, require at least **120 observed days**, **five months**, **90% date coverage**, complete session denominators, **50 orders**, and material session/order evidence in both the training period and the last two withheld months. The modeled rate is **orders per 100 observed sessions**, not distinct-buyer conversion.
- A positive signal becomes a **proposal for a controlled comparison**, never an automatic new listing, price change, marketing spend or message.
- Insufficient evidence, missing denominators and the September 2026 Shopify session-method change suppress action suggestions.

The user's existing STAR model is not retrained in this PR. This is a continually recomputed, auditable rule-based analysis of supplied observations. It can later be connected to an approved real data feed and to experimental learning with owner authorization.

## Exact daily CSV template

Use exactly these fields in this order:

    date,sessions,orders,gross_sales,refunds,platform_fees,fulfillment_costs,ad_spend

One date per row. All money fields are in the specified single seller-account currency, as decimal amounts (e.g. 12.50, not cents); only 0–2 decimal places are allowed. Provide sessions as an integer, or leave it blank if unknown. Orders must be nonnegative integers. Leave unknown money amounts blank rather than entering 0. Include days without orders.

**Gross sales** should be an owner-prepared comparable amount excluding sales tax and shipping, after discounts and before refunds; different marketplaces label gross/net totals differently, so the importer cannot directly ingest unmodified seller exports without a documented normalization step. **Refunds** can occur on days other than the original sale; do not subtract them twice. Other expenses (software subscriptions, taxes, owner labor, processing variations, chargebacks) are not comprehensively modeled.

### Proper data preparation

**Etsy:** Shop Manager → Stats provides visits, orders, conversion and revenue. Shop Manager → Settings → Options → Download Data → Orders CSV provides authorized seller orders. These are different scopes and definitions: only aggregate authorized data into daily totals for the correct shop and reporting timezone, do not paste the raw Orders CSV into STAR, and do not assume a view equals a unique visit.

**Shopify:** Shopify Analytics supports orders, online sessions, sales and date comparisons. Use reports from the merchant's own authorized store. Crucially, the Sep 21–23, 2026 session-measurement rollout can change sessions/conversion without actual demand changing; use comparable periods and annotate this break.

**Google Trends:** normalized, sampled relative popularity (0–100), not orders or absolute sales. It can inform research, but is not a revenue source and must not be used to turn unproven ideas into positive profit forecasts. Merchant Center performance reports can later supply authorized click/impression signals with the required owner permissions.

The source label saved in STAR is an owner assertion only. STAR cannot authenticate a CSV based on the label or checkbox. No seller OAuth, data sync, webhooks, customer messages or production listing access is granted by this feature.

## Statistical and seasonality rules

1. Analyse only one business at a time, with a consistent currency and local date reporting convention. Do not pool shops, countries or marketplaces with different measurement semantics.
2. Last-365-day daily observations are grouped into the **early / middle / late** calendar windows; weekday summaries are descriptive. Month-of-year shows up to three years of observed months but does not by itself assert Christmas, payday or back-to-school demand.
3. Sparse dates, unknown visit/session denominators, changes in tracking definitions, insufficient orders or lack of repeated holdout direction mean **insufficient evidence**. STAR reports the reason, not an imaginary growth number.
4. Even after the conservative gate passes, the result is a candidate to **test**. A log-rate-ratio approximation compares earlier windows with the rest, then checks the direction again in the two most recent months. The model is observational, does not eliminate confounders or control for product price, traffic mix, campaigns, customer geography or launch dates, and does not imply causal confidence.
5. Run a proper owner-approved experiment before scheduling more releases or reallocating ad spending. Hold product, offer and traffic sources as similar as practical; track tests and returns. Time-series validation should always keep later observations out of the earlier training period.

Do not call an owner's manually aggregated dates **verified revenue**. The dashboard keeps this field blank. A reported contribution figure (gross less reported refunds, platform fees, fulfillment and ad spend) is only an estimate from owner-supplied accounting fields, **not profit**.

## Architecture and safety

- Source: star/commerce/sales_learning.py (Python standard library only, no model or network calls).
- Existing STAR commerce connection: star/commerce/workspace.py adds schema and gated commands to the same private SQLite database.
- Qt bridge: star/react_shell.py exposes only commerceLearning and commerceImportDailyMetrics to the native Business UI. Read-only review is separate from owner-confirmed imports; model tools and browser preview cannot silently call marketplaces.
- UI: frontend/src/CommerceSeasonality.tsx, with existing STAR OLED palette and commerce-seasonality.css.
- Tests: tests/test_commerce_sales_learning.py and frontend/src/commerce-seasonality.test.tsx.

All records are isolated by current STAR project **and** exact business ID. The SQLite tables include row digests, a source label and a modification timestamp. Imports never store raw copied CSV text. No credentials or personally identifiable buyer data belong in GitHub or the analytics database.

### Manual checks before merging

    python -m compileall -q star/commerce star/react_shell.py
    python -m pytest -q tests/test_commerce_sales_learning.py tests/test_commerce_mission.py tests/test_lazy_pil.py tests/test_rbx_chat_attachments.py
    npm install --prefix frontend --no-audit --no-fund
    npm run typecheck --prefix frontend
    npm test --prefix frontend
    npm run build --prefix frontend

Use the existing optional Playwright audit for 390/900/1280-pixel preview and real Windows QT UI review. Check import errors, keyboard focus, long report source labels, session-definition warnings, currency formatting, no fake connected badges, and no hidden publication actions.

## Future extensions (not yet implemented)

1. Owner-approved Shopify/Etsy **read-only** analytics adapters using official scopes, credential isolation, token expiry, rate caps and platform report conversion. Etsy's transactions_r endpoint is authorized per seller, not an entitlement to competitors' data.
2. Seller-verified financial ledger with refunds, discounts, taxes, payment/production costs, multi-currency rules and customer-data minimization.
3. Controlled-experiment registry recording actual treatment/control allocation and verified outcomes, drift monitoring, confidence bounds and rollback controls.
4. Per-product and per-category seasonal learning when comparable **product-specific exposure** is available. Don't attribute a shop-wide traffic change to one product.
5. Annual holiday readiness and region-specific calendar planning after sufficient historical evidence, with truthful Google Trends/Google Merchant Center context and source dates.
6. Daily/weekly authorized feed monitoring and owner notifications; no autonomous ad spending, mass posting, buyer impersonation, or unapproved fulfillment.
7. Event-logged performance gates and controlled improvements to STAR's recommendations, rather than rewriting STAR's safety rules or giving the model arbitrary access.

## Research and primary references

- Etsy Stats: https://help.etsy.com/hc/en-us/articles/115015774268-How-to-Use-Etsy-Stats-for-Your-Shop
- Etsy seller CSV: https://help.etsy.com/hc/en-us/articles/360000343328-How-to-Download-a-Spreadsheet-of-Your-Sold-Transactions
- Etsy Open API: https://developers.etsy.com/
- Etsy OAuth and scopes: https://developers.etsy.com/documentation/essentials/oauth2/
- Shopify session-measurement change (Sep 2026): https://help.shopify.com/en/manual/reports-and-analytics/discrepancies/session-measurement-update
- Shopify Analytics: https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/overview-dashboard/
- Shopify revenue definitions: https://help.shopify.com/en/manual/reports-and-analytics/shopify-reports/report-types/default-reports/sales-report
- Google Trends normalization: https://support.google.com/trends/answer/4365533
- Google Merchant API Performance: https://developers.google.com/merchant/api/guides/reports/performance-reports
- Time-series cross-validation and data leakage: https://otexts.com/fpp3/tscv.html
- NIST AI risk measurement/continuous monitoring: https://airc.nist.gov/airmf-resources/airmf/5-sec-core/

**Release gate:** this is a code change proposal, not live marketplace automation, proof of success, trained financial AI or guaranteed earnings. Preserve both stacked parent PRs and review/CI requirements before release.
