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


## Phase 2 implementation — unified discovery and schema-driven plans (2026-10-24)

This phase extends the original proof of concept with **runtime integration**, not only
design notes. It stays an opt-in, read-only Agent/Research capability.

### New source: APIs.guru

- `star/api_directory.py` downloads the canonical HTTPS REST listing at
  `https://api.apis.guru/v2/list.json`, maximum 12 MB, no credentials, proxies,
  redirects or model-controlled destinations.
- Only preferred versions with fixed-origin, valid `api.apis.guru/v2/specs/`
  JSON specification URLs are indexed. Missing or unsafe URLs are excluded.
- SHA-checked SQLite cache, 24-hour listing freshness, 7-day spec freshness,
  30-day maximum stale fallback, and only 16 cached spec bodies.
- An APIs.guru listing entry is **third-party metadata**, not vendor
  authorization or evidence that an API is free.
- `star_api_spec_inspect` takes a provider ID from the cached directory,
  never an arbitrary URL. It reads a bounded JSON spec (3 MB maximum),
  summarizes operations/auth and exposes up to four inert typed read contracts.
- No external `$ref` is resolved; no provider endpoint is invoked. Unsafe,
  private, credential-bearing and plaintext server URLs are not displayed
  as endpoint recommendations.

### Unified REST/MCP capability search

`star_api_catalog_search` has a `source` parameter:

| source | Action |
| --- | --- |
| `public` (default) | Existing lightweight Public APIs catalog only |
| `openapi` | Cached APIs.guru machine-readable directory only |
| `mcp` | Existing official MCP Registry metadata adapter |
| `all` | Combine the available sources in one in-memory inverted index |

The unified index reuses `star/capability_forge.py`; dotted, slashed
and hyphenated MCP/REST identifiers can be searched by word components.
MCP Registry listing never means the provider authorized a connection or
the server was installed. If one source is unavailable in `all` mode,
STAR reports a bounded source failure and keeps the other sources usable.

The APIs.guru directory and its SQLite schema are lazily initialized,
preserving the normal Public APIs hot path. Previously cached winners
are invalidated **immediately on failure**, and the next selection can
reconsider healthy fallbacks rather than waiting for the TTL.

### Inert typed operation contracts

`star/api_contracts.py` compiles only GET/HEAD path+query argument shapes.
It handles required path/query parameters, basic string/number/integer/boolean
types, simple enums and numeric/length constraints.

It explicitly does **not** generate runnable requests. It omits credentials,
headers, cookies, POST/PUT/PATCH/DELETE, request bodies, remote references,
arbitrary untrusted regular expressions, complex unsupported schemas and
unbounded parameter sets. Unsupported operations are listed as skipped rather
than silently being generalized into permissive schemas.

`validate_contract_arguments` validates model-proposed parameter values
against the restricted schema without constructing an HTTP URL or sending
a request. Generated contracts are marked `preview_only_no_execution`.

### Actual online measurements

One live APIs.guru listing on the owner's Main PC reported **2,529 providers**
in the upstream JSON body; STAR accepted **2,049 preferred-version definitions**
with fixed-host JSON spec URLs for indexing. This deliberate difference
is filtering, not evidence that the excluded providers disappeared.

The live tool path measured:

```text
APIs.guru initial search:       ~1,502.81 ms
Inspect one real spec:           ~306.23 ms
Typed read contract count:       2
Combined REST/MCP search:        ~1,266.13 ms
Combined indexed capabilities:   4,154
Source fetch failures:           0
```

The specific inspected spec was `1forge.com`; its two GET/HEAD
validation previews were inert and marked `executable=False`. The
combined search returned candidates from APIs.guru and Public APIs.
This is not a benchmark of Star's underlying language model or
real vendor endpoint latency. Network timings depend on connectivity.

### CI correction made during this phase

Earlier PR head `bc6ed32...` had seven Pyright diagnostics and a Windows
prompt-cache regression. The parser/typing diagnostics were corrected by
narrowing `info`, Swagger schemes, `verified_at` and spec URL types.

The warm-up now discards a stale request/tool-list shape when the selected
profile/chat has no persisted history, avoiding cross-profile cache priming
and fixing the focused knowledge-bank/warm-up regression.

Before merge or release, the repository's full Windows/Linux CI and owner
approval remain the authoritative gates. A passing focused test run does
not prove native packaged UX, third-party API execution or model quality gains.

### Reproduction

```powershell
python -m pytest -q tests/test_api_intelligence.py tests/test_api_contracts.py tests/test_api_directory.py tests/test_api_catalog.py tests/test_capability_forge.py
python -m ruff check star/api_intelligence.py star/api_directory.py star/api_catalog.py star/api_contracts.py star/capability_forge.py
python -m compileall -q star
```

### Primary references

- APIs.guru directory: https://github.com/APIs-guru/openapi-directory
- OpenAPI 3.2.1: https://spec.openapis.org/oas/v3.2.1.html
- Arazzo 1.1.0: https://spec.openapis.org/arazzo/v1.1.0.html
- MCP Registry: https://registry.modelcontextprotocol.io/docs
- OWASP API Security Top 10: https://owasp.org/API-Security/
