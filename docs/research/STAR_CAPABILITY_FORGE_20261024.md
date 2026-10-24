# STAR Capability Forge — verified tool discovery, routing, and reuse

**Date:** 2026-10-24  
**Status:** candidate implementation on a review branch; no auto-merge or release.

## Goal

Turn the useful idea from InsiderForce's Short, “Get 1000 Free APIs for Claude Code to Build Anything You Want,” into a stronger STAR subsystem:

```text
capability request
    ↓
fast local discovery
    ↓
evidence-aware ranking
    ↓
first-party/spec verification
    ↓
health + latency memory
    ↓
verified inert adapter manifest
    ↓
separate owner-approved execution boundary
```

The key rule is that **discovery is not permission**. A catalog row, MCP Registry entry, OpenAPI document, Arazzo workflow, webpage, or model output can describe a capability but cannot authorize STAR to execute it.

## Current research basis

### Public APIs

`public-apis/public-apis` remains an actively maintained, very large community catalog. Its current 2026 README uses third-level category headings and a table format that differs from older snapshots. STAR's parser now supports the current format and locks it with a regression test.

Public API catalogs are leads, not authoritative statements about current pricing, authentication, privacy, reliability, or commercial terms.

### OpenAPI 3.2.1

The current OpenAPI Specification is **3.2.1 (2026-09-10)**. OpenAPI gives machines a standard description of HTTP API servers, operations, parameters, schemas, and declared security. STAR now summarizes OpenAPI/Swagger metadata and separates read methods from mutating methods.

Source: https://spec.openapis.org/oas/v3.2

### Arazzo 1.1.0

Arazzo **1.1.0 (2026-05-17)** describes multi-step API workflows and dependencies. This is especially useful for agents because a workflow can express the intended sequence rather than forcing the model to infer it from isolated endpoints.

STAR now parses Arazzo descriptions as **untrusted orchestration data**, extracting workflow IDs, source descriptions, operation references, workflow references, step counts, and security warnings. It does not execute an Arazzo step.

Source: https://spec.openapis.org/arazzo/latest.html

### Official MCP Registry

STAR already had discovery-only search over the official MCP Registry. The Capability Forge is designed to use MCP options in the same routing model as REST capabilities, while preserving the existing rule that registry metadata does not install, connect, or authorize a server.

Source: https://registry.modelcontextprotocol.io/docs

### APIs.guru OpenAPI Directory

APIs.guru maintains a public directory of machine-readable API definitions, updates definitions from upstream sources, validates them, and exposes the collection through a REST API. This is a strong second-stage discovery source after a broad catalog match because it can lead STAR directly to OpenAPI metadata.

Source: https://github.com/APIs-guru/openapi-directory  
API: https://api.apis.guru/v2/list.json

### Security model

OWASP's API Security Top 10 explicitly includes unrestricted resource consumption, SSRF, improper inventory management, and unsafe consumption of APIs. Those are directly relevant to an AI that discovers third-party services automatically.

Source: https://owasp.org/API-Security/

## Implemented architecture

### 1. `star/api_intelligence.py`

Pure, deterministic analysis:

- parses current and older Public APIs Markdown table shapes;
- preserves category, auth, HTTPS, CORS, source, and description;
- fingerprints catalog snapshots with SHA-256;
- ranks API candidates;
- summarizes OpenAPI/Swagger operations, servers, auth schemes, and write methods;
- summarizes Arazzo workflow descriptions without executing them;
- generates reviewable integration plans with `executable_by_star=False`.

### 2. `star/capability_forge.py`

Fast shared router for REST, MCP, and future local capabilities:

- bounded in-memory inverted index;
- BM25-style token weighting;
- exact phrase/category boosts;
- multi-token intent-coverage boosts;
- official/verified evidence bonuses;
- unresolved-risk penalties;
- authentication-friction scoring;
- observed success/failure scoring;
- latency EMA scoring;
- three-failure circuit breaker;
- short-lived winner cache;
- automatic cache invalidation when capability/spec fingerprints change;
- fallback ordering;
- inert manifest compiler that strips write operations in read-only mode.

The hot routing path does not need a model call.

### 3. `star/api_catalog.py`

Real Agent/Research discovery tool:

- tool name: `star_api_catalog_search`;
- hard-coded public source only;
- no arbitrary fetch target supplied by the model;
- maximum response size;
- no redirects, credentials, system proxy, or execution;
- SQLite catalog cache under STAR app data;
- 24-hour fresh-cache hot path;
- stale-cache fallback when refresh is unavailable;
- process-hot parsed/indexed cache;
- three searches maximum per model turn;
- outputs are explicitly labelled `discovery_only_unverified`.

### 4. Agent integration

In **Agent + Research** mode:

- STAR instantiates the API catalog discovery source beside MCP Registry discovery;
- the API search tool is attached only for prompts with API/integration intent;
- tool-memory ordering still applies;
- authorization is checked before each call;
- API catalog output is classified as untrusted third-party data;
- reading it blocks full Luau execution for the remainder of the turn under STAR's existing untrusted-source rule.

No discovered API is called.

## Live evidence from the owner's Main PC

These are development measurements, not production guarantees.

### Actual current Public APIs checkout

A live checkout contained about **2.1k parsed entries**.

One measured run:

```text
parse catalog:          23.22 ms
build capability index: 59.42 ms
five searches total:     7.695 ms
```

After fixing the 2026 heading format, `currency exchange` correctly ranked entries from the **Currency Exchange** category instead of generic services containing only the word “Exchange”.

### Real discovery tool path

Against the real raw GitHub catalog:

```text
first call including network + parse/index: ~415.94 ms
second call from fresh local/process cache:   ~8.259 ms
catalog entries on that fetch:                2105
```

The first call changes with network conditions. The important architectural result is that repeat discovery can stay local and model-free.

## Verification

Focused validation on the owner's connected Main PC:

```text
99 passed in 9.51s
Ruff: All checks passed
compileall: passed
```

The focused set includes the new API intelligence, Capability Forge and API catalog suites plus existing MCP Registry, agent tool-catalogue, agent runtime and Tool Workshop/agent-memory tests.

This is not a claim that the complete repository, native Windows package, live external API execution, or release gate has passed.

## Why this makes STAR smarter

STAR can distinguish:

- **found** — catalog metadata matched;
- **verified** — first-party/spec/version evidence exists;
- **healthy** — observed calls succeeded;
- **fast** — observed latency is good;
- **stale** — evidence is old or spec fingerprint changed;
- **temporarily bad** — repeated failures opened the circuit breaker;
- **read-safe candidate** — manifest includes only read methods;
- **write-capable** — mutating operations exist but remain separately gated.

That lets STAR learn which capability is actually useful instead of repeatedly picking whichever result has the most appealing description.

## Why this makes STAR faster

- first-stage search is deterministic and model-free;
- the catalog is fetched once per TTL instead of every request;
- the parsed index is reused in-process;
- a recently proven winner can bypass a full tournament;
- failed providers are temporarily skipped;
- spec/catalog changes invalidate stale choices automatically;
- read/write classification is precompiled into an inert manifest.

## Next implementation layer

The next safe expansion is:

1. ingest APIs.guru REST metadata as a machine-readable OpenAPI discovery source;
2. map official MCP Registry results into the same tournament automatically;
3. fetch first-party/OpenAPI specs through STAR's guarded reader;
4. validate schemas and compile typed adapters;
5. add per-host token buckets, response budgets, idempotent retry rules, and secret references;
6. run recorded-response tests;
7. require an owner-approved live smoke test;
8. only then allow an adapter to move from `executable=False` to a separately configured runtime permission.

For multi-step integrations, Arazzo should be preferred over model-invented orchestration when a trustworthy workflow description exists.
