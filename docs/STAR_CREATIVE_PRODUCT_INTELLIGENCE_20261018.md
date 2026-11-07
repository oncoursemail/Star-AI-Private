# STAR Creative Product Intelligence — 2026-10-18 evidence and build specification

Status: **research + engineering specification only**. No seller-marketplace data has been imported; no designs here are independently QA-approved; no sales or demand forecasts are claimed. This note extends the local commerce prototype without granting it publication or spending permissions.

## Verified primary-source signals (read 2026-10-18)

- Etsy Fall/Winter 2026 seller report (2026-10-14): personalized friend gifts searches +1,400%; pet gifting searches doubled; DIY activities searches +8,500%; hand-painted items +280%. These are Etsy-reported directional US query trends, not addressable market estimates, conversion rates, or proof of profitable products. https://www.etsy.com/seller-handbook/article/1521255894814
- Etsy winter merchandising covers Halloween, Hanukkah, Thanksgiving, Christmas, New Year's, and subsequent Valentine's Day/spring seasonal work. https://www.etsy.com/seller-handbook/article/22817661229
- US Etsy fees: $0.20 listing, 6.5% transaction, Etsy Payments 3% + $0.25 on Etsy's public US seller page; additional advertising/tax/other fees may apply. https://www.etsy.com/sell ; https://help.etsy.com/hc/en-us/articles/115014483627-What-are-the-Fees-and-Taxes-for-Selling-on-Etsy
- OWN3Dtv public Etsy catalog examples: animated overlay packages $32.99, emote packs $19.99-$23, alerts $8, banners $5; competitor ASKING prices, not verified sales. https://www.etsy.com/shop/OWN3Dtv
- Etsy custom overlays marketplace: public examples of $7.50 discounted, $14.26 discounted, $19.99, $45 custom and $80+ custom; a broad competitive range, not a validated median. https://www.etsy.com/market/custom_stream_overlays
- Printify: free plan $0, Premium from $39/month monthly; illustrative T-shirt base cost $12 on Free, $9.60 on Premium; shipping, taxes, storefront fees extra. https://printify.com/pricing/ ; https://help.printify.com/hc/en-us/articles/4483609656721-How-much-will-I-make-per-sale
- Printify US shipments have a $0.40 surcharge from 2026-10-15 through 2027-01-17. https://printify.com/shipping-rates/
- Printify shipping starts at $3.99 Economy and $4.75 Standard depending on product/provider/destination. https://help.printify.com/hc/en-us/articles/4483626155409-What-are-Printify-s-shipping-options

## Portfolio candidates (not a demand-validated ranking)

1. Animated streamer scene systems: OBS-compatible scene templates, starting/intermission/ending, responsive vertical streaming layout, tested stingers, editable source, documented installation. Research-led price experiment $19-$39 for complete noncustom pack; market examples above.
2. Interactive stream widgets: original web-based stream goals, timers, polls and chat overlays. Must have browser tests, resource budget, fallback and platform-specific integration tests; never claim Twitch/YouTube/Kick compatibility without actual tests. Initial test range $8-$25 (hypothesis).
3. Halloween printable party collection: editable invitation, menu, place cards, scavenger hunt, print-at-home decorations, PDF with US Letter/A4 crop/bleed checks. Test $8-$22 (hypothesis).
4. Christmas/holiday craft printable kits: Advent prompts, cut-and-fold decorations, ornament templates, group activity instructions. Test $6-$18 (hypothesis).
5. Personalized pet and friend portrait printables: commissioned original art using customer-supplied assets with consent; protect likeness/data; manual client-specific review. Test $12-$35 digital (hypothesis).
6. Functional planning printables: wedding checklists, budgeting sheets, habit journals and school organizers, with meaningful usability and accessibility. Test $5-$19 (hypothesis).
7. Print-on-demand custom ornaments and wall prints: validate physical sample quality, shipping and margin before publishing. Do not place supplier orders automatically.

## Unit economics examples — illustrative, not live merchant quotes

US Etsy $12 digital item, no ads/refunds: $12 - $0.20 listing - $0.78 transaction - $0.61 processing = **$10.41 contribution before creation labor, AI costs, taxes and overhead**. Listing fee recurs on relist/renewal as applicable.

US Etsy $29 physical item with *hypothetical* $12 production + $4.75 shipping paid by seller, no ad spend: $29 - $0.20 - $1.89 - $1.12 - $12 - $4.75 - $0.40 seasonal US surcharge = **$8.64 contribution before labor, taxes, returns and overhead**. Supplier price is illustrative; verify exact SKU/provider and whether the surcharge applies.

Do not conflate contribution margin with net profit, and do not publish an item until fees and supplier price are freshly checked.

## STAR production pipeline — bounded, observable and quality-first

Discover -> source evidence -> segment customer need -> deduplicate concepts -> score demand/competition/rights/fulfillment economics -> design brief -> build 3 differentiated creative directions -> render/test actual files -> independent visual + technical + rights + accessibility review -> owner veto/approval -> marketplace DRAFT -> approved publication -> order reconciliation -> post-sale defect and return analysis -> proposed improvements.

Research: store source URL, retrieved date, marketplace, query/category, observation type (asking price vs sold), currency, SKU details, sample count, bias, and confidence. Do not use scraped Etsy data contrary to platform terms. At least two independent customer-need signals before investing in large production batches. Never treat a search percentage increase as an absolute sales volume.

Design QA: compare against a real art direction brief, hierarchy, alignment, legibility, negative space, typography license, export size, transparent edges, color profile, originality, trademark rights, mobile preview, print legibility and accurate mockups. For printables, validate A4 and Letter output, bleed, PDF font embedding, margins and readable print at 100%; for stream overlays validate OBS browser source, alpha, frame pacing, transitions, vertical crops, low-end hardware and source editability. A model grading its own output is not independent review. Preserve rejected design feedback as test cases, not auto-approved lessons.

Quality gate: require separate designer/QA approval and user acceptance before publication. The agent must return 'needs review' rather than assert 'perfect'. Hold all questionable IP, offensive/unsafe designs, customer-specific personalized goods and expensive POD orders.

Speed: run research/rights/competitor/economics checks in parallel; bound concurrent render jobs; cache identical evidence by date; use deterministic templates for repeated exports; use the best suitable model for hard visual work and cheap local models for tagging; render contact sheets and do batched screenshot comparisons. Prefer faster rejection of weak ideas over mass generating low-quality inventory.

Automation: SQLite WAL queue for local MVP; idempotent jobs, retry/backoff, dead-letter review, durable event journal, explicit cost budget and kill switch. Daily local discovery of new concepts and weekly portfolio reassessment can be configured, but requires an actual running scheduler. Automatic generation is allowed only for local drafts. External listing/publishing, ad spending, customer messaging, production charges, refunds and payouts require authorized official integrations and explicit bounded approvals.

Feedback: ingest ONLY verified authorized sales/order/refund/conversion records; cohort by channel, SKU, season, fulfillment time, buyer segment and return reason; use Bayesian/small-sample cautious comparisons; propose design and price tests, then require review. Never train on personal buyer data without permission. Avoid optimizing clicks at the expense of complaints/refunds.

## Pilot decision

Start with two product families: a premium animated streaming scene system (evergreen) and a Christmas/holiday printable craft activity kit (seasonal), each with one deeply designed prototype and an independent QA packet. The existing six-SVG starter pack is only a mechanical prototype and should not be relabeled premium. Halloween 2026 is close; prioritize instant-download products over new physical POD items with uncertain delivery deadlines.

## Exit criteria before any live launch

- Original files, visual evidence and license evidence verified by a human
- Three actual competitor comparisons including total deliverables and sale-vs-list pricing
- Validated fulfillment costs, merchant fee assumptions, tax handling and minimum contribution
- Correct buyer-facing description, dimensions, editable file formats and clear limitations
- No unauthorized API, scraping, fake reviews or unconsented mass outreach
- Explicit owner approval for marketplace publication and all real charges
- Genuine checkout test, download test, order/refund tracking, and zero fabricated sales
