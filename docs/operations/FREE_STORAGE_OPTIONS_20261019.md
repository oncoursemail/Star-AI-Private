# Free storage options for Star

Reviewed: **2026-10-19 UTC / 2026-10-18 CDT**. Prices are USD and can change.

**Cleanup has begun; external storage remains a proposal.** Verified maintenance and signed-in browser cleanup removed **125 distinct artifacts / 59,043,372,476 bytes**. Further browser actions are currently blocked by an automatic approval-review capacity failure. See the [cleanup checkpoint](WINDOWS_ARTIFACT_CLEANUP_20261019.md) and [exact receipt](WINDOWS_ARTIFACT_CLEANUP_RECEIPT_20261019.json) for completed work, verification and the remaining selected scope. No external provider signup, billing change, off-site upload or deployment is established by this research. The original inventory was **744,948,406,129 bytes: 744.948 GB decimal, or 693.787 GiB**; it is a historical comparison, not the current inventory or a billing statement. Existing-server capacity remains unverified.

## Recommended architecture

Keep source code, workflows, and private research documentation in the private GitHub repository. Publish approved application installers through GitHub Releases in the public repository. Keep Actions artifacts only long enough for build handoffs and current reviews. Store bulky private working material on existing servers after checking capacity and backup coverage.

For additional off-site capacity, **prefer Backblaze B2 for a small private backup pilot without payment setup**. Choose **Cloudflare R2 when repeated downloads make egress pricing more important**, with deliberate billing controls. Use **Hugging Face for genuine ML models and datasets** when its purpose and permissions fit. These choices are conditional recommendations, not activated integrations.

The first improvement is eliminating obsolete and duplicate outputs. A 10 GB free tier cannot absorb approximately 745 GB of retained builds. Moving every obsolete file elsewhere preserves the underlying retention problem.

## Separate the storage categories

| Category | Appropriate contents | Proposed treatment |
|---|---|---|
| Git repository | Source, configuration, documentation | Keep generated installers out of ordinary Git history. |
| Actions artifacts | Files passed between jobs; review evidence | Short retention; one copy per required purpose. |
| Actions cache | Reusable dependencies and compiler caches | Regenerable acceleration data; not the authoritative release archive. |
| GitHub Releases | Versioned installers, portable packages, checksums | Publish tested software versions and retain useful release history. |
| Private object storage | Backup archives, selected private builds | Enforce access controls, retention, and capacity limits. |
| Static website hosting | HTML, CSS, JavaScript, small site assets | Link large downloads to Releases or object storage. |

Actions artifacts and GitHub Packages share a storage pool. Actions cache has a **separate 10 GB allowance per repository**. GitHub Free includes **500 MB** of artifact storage; Pro includes **1 GB**. Clearing caches therefore does not directly clear the artifact pool. Uploading artifacts to GitHub from a locally hosted runner still uses that storage service. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## Main options

### GitHub Releases: approved software downloads

GitHub permits **up to 1,000 assets per release**, with each file **under 2 GiB**. Its documentation states no total release-size or bandwidth limit. Releases follow repository read permissions. These documented software-distribution limits are not a promise of unlimited general-purpose backup hosting. See [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

For Star, publish the installer, portable ZIP, checksum manifest, and release notes once per version. Record the source commit and successful test run. Public release contents must be intentionally distributable; private logs, credentials, datasets, and development material require a separate destination. Publishing a release does not solve uploads of unnecessary intermediate copies elsewhere in the workflow.

### Backblaze B2: private backup with inexpensive growth

The first **10 GB of storage is free**, and [signup requires no credit card](https://www.backblaze.com/cloud-storage). Current standard storage pricing starts at **$6.95/TB per 30 days**, with no minimum file-size or storage-duration fees. This supersedes older articles quoting $6/TB.

Monthly egress is free up to **three times average monthly stored data**, then **$0.01/GB** for ordinary overage. Selected CDN and compute partners have additional free-egress arrangements; partner charges and integration requirements still need checking. Class A/B/C requests are free for pay-as-you-go customers; Class D has a separate schedule. See [B2 pricing](https://www.backblaze.com/cloud-storage/pricing).

Start with valuable, encrypted backups that fit comfortably below the free allowance. Keep credentials restricted to the required bucket and operations. A backup-oriented allowance can be exhausted quickly by repeatedly distributing a large installer; B2 is not the default public-download recommendation here.

### Cloudflare R2 Standard: frequent downloads and optional mirrors

The monthly free allowance is **10 GB-month of storage**, **1 million Class A requests**, and **10 million Class B requests**. Direct Internet egress is free. Standard overage costs **$0.015/GB-month**, **$4.50/million Class A**, and **$0.36/million Class B**. Billable units are rounded upward. The free allowance does **not** apply to Infrequent Access, which also has retrieval charges and a minimum storage duration. See [R2 pricing](https://developers.cloudflare.com/r2/pricing/).

R2 requires [subscription checkout](https://developers.cloudflare.com/r2/get-started/) and a [billing profile/payment method](https://developers.cloudflare.com/billing/get-started/create-billing-profile/). Free included usage is not a hard spending limit. Cloudflare explicitly says [budget alerts do not pause or cap usage](https://developers.cloudflare.com/billing/manage/budget-alerts/).

Keep private builds in a private bucket. Use expiration rules for disposable previews and check size before uploading. [Lifecycle deletion](https://developers.cloudflare.com/r2/buckets/object-lifecycles/) is asynchronous, typically within 24 hours of expiration, so retain capacity headroom. For public production downloads, use the documented custom-domain path: [r2.dev endpoints are rate-limited and intended for development](https://developers.cloudflare.com/r2/buckets/public-buckets/). Domain registration may be a separate expense.

### Hugging Face: storage for ML work

Free users and organizations currently receive **100 GB private storage**; public storage is **best-effort**, with useful community contributions expected beyond the first few gigabytes. Higher guaranteed limits involve paid plans. See [Hub storage limits](https://huggingface.co/docs/hub/storage-limits).

Suitable Star material includes model adapters, evaluation datasets, and legitimate training examples with appropriate rights and permissions. Its [content policy](https://huggingface.co/content-policy) prohibits excessive or irrelevant repository data. Do not use it to warehouse ordinary Windows CI outputs. Keep private material private; a gated repository still exposes some repository information. This is separate storage, not extra GitHub capacity.

### Existing servers: private working storage

Inspect free disk space, disk health, filesystem ownership, and recoverability before selecting a destination. Existing hardware avoids a new storage-vendor subscription, but electricity, disks, bandwidth, administration, and backup remain real costs.

Use separate directories for disposable build scratch, retained review packages, and valuable research assets. Apply different retention rules to each. A small authenticated SFTP destination may suffice; an S3-compatible service is an option if software requires that API. Keep another recoverable copy of irreplaceable material on a separate device or off-site service. Capacity, service configuration, and restore testing must be recorded before this option is considered ready.

## Illustrative storage costs

These estimates assume decimal GB, a constant retained amount for a full month, one copy, and the first 10 GB free. They exclude tax, excess requests, excess egress, domain registration, and other services. They are not a quote or an estimate of the existing GitHub bill.

| Constant retained data | R2 Standard storage | B2 standard storage |
|---|---:|---:|
| 10 GB | $0 | $0 |
| 100 GB | About $1.35/month | About $0.63/month |
| Inventory snapshot: 744.948 GB | About $11.03/month | About $5.11/month |

Calculations use `max(GB - 10, 0) × 0.015` for R2 and `max(GB - 10, 0) × 0.00695` for B2, using their linked published rates. Provider metering, rounding, and storage changes affect actual charges. GitHub uses binary units for storage billing, so comparisons must begin with bytes.

Deleting GitHub artifacts reduces current usage and future accrual, but does not erase storage already accrued during the billing cycle. GitHub says reporting updates within **6–12 hours**. Verify a real artifact upload after cleanup rather than assuming the billing block immediately cleared. See [storage billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## Website hosting and alternatives screened

**Cloudflare Pages** is a good candidate for a static frontend or documentation site: Free allows **500 builds/month**, one concurrent build, **20,000 files/site**, and **25 MiB per file**. Functions consume Workers-plan usage. The file limit excludes large Windows packages. See [Pages limits](https://developers.cloudflare.com/pages/platform/limits/).

**Netlify Free** permits [commercial projects](https://www.netlify.com/blog/introducing-netlify-free-plan/), but current [pricing](https://www.netlify.com/pricing/) provides **300 credits/month**, with production deploys at **15 credits**, bandwidth at **20 credits/GB**, and web requests at **2 credits/10,000**. Downloads compete with other usage. Do not rely on old 100 GB bandwidth claims for new accounts. **Vercel Hobby** is restricted to [personal, noncommercial use](https://vercel.com/docs/plans/hobby), making it unsuitable for the intended commercial business sites.

**Google Drive** offers [up to 15 GB shared with Gmail and Photos](https://support.google.com/drive/answer/6374270). Its [API quotas and rate limits](https://developers.google.com/workspace/drive/api/guides/limits) require handling. Prefer it for documents and small backups rather than the primary installer-delivery path.

**Oracle Always Free** is a secondary option: **20 GB combined object storage and 50,000 API requests/month** for an account in Always-Free-only state; **200 GB combined boot/block volumes** in the home region is a different resource, requiring VM/storage administration. It is not 200 GB of object storage. Idle VMs may be reclaimed, capacity can be unavailable, and exceeding the object allowance when a trial ends can cause deletion. Review [resource rules](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) and [card verification requirements](https://www.oracle.com/cloud/free/). This complexity makes it a reserve option, not the chosen backup path. Temporary promotional credits are not a durable storage solution.

## Implementation checklist

- [x] Inspect artifact inventory and distinguish protected release inputs and current review builds.
- [x] Record the completed 125-artifact cleanup with exact deleted bytes and verification evidence.
- [ ] Resume the remaining selected cleanup after automatic approval review becomes available; refresh the complete inventory afterward.
- [x] Prepare a draft workflow change to reduce uploads and set explicit retention for future artifacts.
- [ ] Complete native Windows CI, reconcile the overlapping release-channel PR and satisfy independent review before merging the workflow change.
- [ ] Run packaging and download-consumer checks to confirm every required file survives.
- [ ] Verify the intended public release assets, source provenance, and checksums.
- [ ] Inspect existing-server capacity and document the private destination and backup plan.
- [ ] Select B2 or R2 only when a concrete retained dataset and access pattern justify it.
- [ ] Before provider activation, verify current terms, payment exposure, permissions, and usage limits.
- [ ] Add bounded retention, upload-size checks, restricted credentials, and usage reporting.
- [ ] Test one upload/download and one backup restoration before depending on the destination.
- [x] Link verified cleanup results above and keep external setup and remaining validation explicit.
