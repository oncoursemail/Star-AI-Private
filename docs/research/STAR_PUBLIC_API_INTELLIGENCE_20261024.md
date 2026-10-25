# STAR Public API Intelligence — research and implementation
**Date:** 2026-10-24  
**Source prompt:** InsiderForce YouTube Short, “Get 1000 Free APIs for Claude Code to Build Anything You Want” (video id `4qIZmI_1Zgs`, published 2026-09-18).

## What the Short is showing
The useful idea is simple: use a large directory such as `public-apis/public-apis` to discover an API, then let an agent read the documentation and integrate it into a project. The clip gives examples such as weather, food/nutrition, crypto prices, news, translation and movie data.

The directory is a discovery source, not a trust boundary. A row saying an API is free, uses HTTPS, or needs no authentication can be stale. “Free” can mean a small free tier; terms, attribution, quotas and commercial-use rules can change. STAR must therefore never convert catalog prose directly into an executable network capability.

## Research conclusions
1. **Keep Public APIs as a broad discovery seed.** It is useful for breadth and human-readable categories.
2. **Prefer machine-readable specifications when available.** APIs.guru maintains a large OpenAPI directory. OpenAPI lets STAR inspect operations, parameter schemas, server URLs and declared auth before generating an adapter.
3. **Prefer an official MCP server when a provider publishes one.** The official MCP Registry is another discovery path for agent-native integrations.
4. **Verify against first-party documentation.** Third-party directories are leads, not authority.
5. **Model API consumption as a security boundary.** OWASP's API Security guidance includes broken authorization/authentication, unrestricted resource consumption, SSRF, security misconfiguration, inventory problems and unsafe consumption of third-party APIs.
6. **Retry semantics matter.** Automated retries are safest for idempotent operations. STAR must not blindly replay POST/PATCH/DELETE calls.
7. **Separate discovery from execution.** Search/ranking can be broad; execution must be a small verified adapter with a host allowlist, schema validation, secret handling, limits and a separate permission for writes.

## Implemented candidate
`star/api_intelligence.py` adds a deterministic, offline analysis layer:

- Parses the common Public APIs Markdown table format without following links.
- Records source/provenance and creates SHA-256 snapshot manifests.
- Ranks candidate APIs by task relevance and operational friction.
- Prefers HTTPS and, when requested, no-auth candidates.
- Surfaces OAuth, unknown auth, plaintext HTTP and CORS uncertainty.
- Reads OpenAPI/Swagger metadata to enumerate operations, servers, auth schemes and mutating methods.
- Produces a reviewable integration plan rather than executing the API.
- Keeps `executable_by_star=False`; catalog contents cannot grant themselves permissions.

## Proposed STAR pipeline
```text
user capability request
        |
        v
API Scout
Public APIs + APIs.guru + official MCP Registry + vendor docs
        |
        v
Evidence verifier
first-party docs / current terms / price / quotas / auth / privacy
        |
        v
Spec reader
OpenAPI / JSON schema / MCP tool schema
        |
        v
Risk critic
HTTPS / SSRF / redirects / secret placement / PII / rate limits /
resource ceilings / idempotency / write classification
        |
        v
Adapter generator
typed inputs + explicit host allowlist + bounded response + redaction
        |
        v
Recorded-response tests
        |
        v
owner-approved live smoke test
        |
        +---- READ permission
        |
        +---- separate WRITE permission
```

## What STAR should add next
- A cached catalog fetcher through the existing guarded web reader, with ETag/Last-Modified support and a content hash.
- APIs.guru ingestion so discovery can jump directly to OpenAPI documents.
- Official MCP Registry lookup before inventing a custom REST adapter.
- A local Integration Manifest containing provider, verified documentation URL, allowed hosts, auth mode, secret name, allowed HTTP methods, rate-limit policy, max response size, timeout, retry policy, data classification and license/terms review date.
- Adapter generation from OpenAPI with schema-constrained parameters.
- Per-host token buckets and global request budgets.
- Secret references only; never paste keys into model context, source URLs or generated frontend code.
- Response provenance: source URL, request timestamp, status, selected fields and bounded content hash.
- A verifier that periodically marks integrations stale when docs/spec fingerprints change rather than silently trusting the old adapter.
- An evaluation set covering stale catalogs, malicious descriptions, redirect-to-private-IP SSRF, huge responses, 429 handling, schema drift, auth failures and accidental write retries.

## Why this is stronger than the clip
The Short optimizes for speed of discovery. STAR should optimize for **verified capability acquisition**: find something quickly, prove what it is allowed to do, generate the smallest adapter, test it, and preserve the evidence. That makes “thousands of APIs” useful without turning thousands of unknown third-party endpoints into thousands of implicit permissions.

## Rollout boundary
This change intentionally does **not** enable arbitrary third-party API calls. It adds the intelligence layer that can select and plan integrations safely. Live networking should reuse STAR's existing guarded web/network boundaries and remain opt-in. Mutating operations require a separate permission and must not be promoted merely because a model or catalog recommends them.

## Primary references
- Public APIs: https://github.com/public-apis/public-apis
- APIs.guru OpenAPI Directory: https://github.com/APIs-guru/openapi-directory
- Official MCP Registry: https://registry.modelcontextprotocol.io/
- OWASP API Security Top 10: https://owasp.org/API-Security/
- HTTP Semantics (RFC 9110): https://www.rfc-editor.org/rfc/rfc9110
