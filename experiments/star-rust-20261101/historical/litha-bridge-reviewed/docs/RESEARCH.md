# Technical assessment: Lemonade + AnythingLLM for Litha

**Assessment date:** 2026-10-29  
**Source snapshots:** `lemonade-sdk/lemonade@c306b768e0bc185650e47b3560c6aa6228f7f941` and `Mintplex-Labs/anything-llm@3661da4cfffbd0d65bc1a2fb23787489d249dfd2`. These are repository commit references, not verified release/version compatibility locks.  
**Integration status:** experimental standalone adapter; no Litha repository was accessible for code modification; no real Litha hardware or application was inspected.

## Executive technical conclusion

Lemonade and AnythingLLM are **complements**, but not independent intelligence multipliers. Lemonade is mainly a local inference and model-management abstraction; AnythingLLM is an application layer (document pipelines, retrieval, workspaces, memory, agent tool use and workflows). As of this research, AnythingLLM already integrates Lemonade as a provider and offers an embeddable Lemonade engine. Therefore, stacking both full products inside Litha could duplicate model loading, chat state, UI, vector stores, and agent orchestration. Select the minimum useful surfaces instead.

**Preferred deployment:** use an existing Lemonade service for *local inference*, the AnythingLLM developer API as an **optional external retrieval service**, and keep Litha's own task selection, authorization, conversation identity, tool policy, evaluations, UI and release lifecycle authoritative. If Litha already has a mature RAG system, don't fork it into AnythingLLM; instead borrow ideas and benchmark the new retrieval implementation as a candidate.

## Verified capabilities / caveats

| Area | Lemonade | AnythingLLM | Practical interpretation for Litha |
|---|---|---|---|
| Role | Inference server, downloaded models, hardware backends | User-facing RAG, workspace chat, agents, connectors, scheduled runs | Integrate them at different boundaries |
| Chat API | `/api/v1/chat/completions`, `/api/v1/models`; API accepts `/v1` too | `/api/v1/workspace/:slug/chat`; query/chat/automatic modes | Keep normalized adapter contracts |
| Embeddings/rerank | Documented embeddings and reranking model labels and APIs | Vector search and configurable embeddings + rerank | Avoid assuming an arbitrary chat model also embeds |
| Model selection | Model labels, aliases, active/standby; experimental cloud offload; router policies | Rule-based model router with calculated and model-classified rules | Choose one model-routing policy authority |
| Performance | Local CPU/GPU/NPU backends; hardware-dependent | Relevant-tool selection and short RAG context | Must measure on Litha hardware; no guaranteed speedup |
| Knowledge | Embeddings primitive, not a knowledge governance product | Document parsing, chunking, vector indexing, workspace isolation | Track evidence provenance, revision and permission scope |
| Agents | MCP gateway + local inference | MCP tools, custom skills, visual flows, scheduled jobs | Require trust/approval boundaries; do not enable automatically |
| Shipping | Server or embeddable `lemond` runtime | Desktop or Docker deployment; different roles/capabilities | Do not bundle duplicate servers/models without a packaging plan |
| Licenses | Apache-2.0 source license | MIT source license | Maintain notices if distributing upstream code; model/runtime terms vary |

### 1. Lemonade: architecture and APIs

The repository documents Lemonade Server (connect to externally installed runtime) and Embeddable Lemonade (package a `lemond` executable inside an application). The API has OpenAI-, Anthropic-, Ollama-compatible surfaces and a custom Lemonade API. Supported modalities include LLM chat, embeddings/reranking, transcription, speech and image generation. Each depends on available backend/device/model configuration; seeing an endpoint in a spec **does not** guarantee it works with every hardware profile or downloaded model.

The OpenAI-style API includes `/v1/chat/completions`, `/v1/embeddings`, `/v1/responses`, `/v1/models`, image and audio endpoints. The Lemonade management API includes `/v1/health`, `/v1/stats`, `/v1/load`, `/v1/unload`, `/v1/pull`, backends and download-job management. Actual local server documents can be read from `/v1/docs`, so prefer the installed version's spec to web assumptions. This prototype performs only `GET /models`, `/health`, `/stats`, and `POST /chat/completions`. It **does not** expose pull/load/unload, admin `/internal` APIs, or tool-calling loops.

The model catalog exposes deployment `labels` such as `chat`, `embeddings`, `reranking`, `transcription`, `image` and optional capabilities (`tool-calling`, `vision`). Host-application model discovery should filter on **declared** capability, not model name substrings; test tool-call structure before enabling auto agents. One supported model alias can fail over between local targets, but the configured alias should not bypass a Litha owner-selected resource policy. Model loading can cause high first-request latency and RAM/VRAM spikes. The prototype preflights the installed model list on every call and rejects API entries marked as cloud models and composite `collection.*` recipes (which may route to cloud or invoke server-side tools), so it neither silently triggers a registry download nor chooses an obvious cloud/composite provider. This is a conservative client filter, not proof that a misconfigured upstream service can never contact the internet.

The source docs cover multiple backends (for example llama.cpp CPU/CUDA/Vulkan/ROCm/Metal where supported, FastFlowLM for some NPUs, and modality-specific engines). AMD acceleration must not be assumed available on generic NVIDIA or unsupported NPU hardware, nor should best-case official benchmarks be carried over. The proper comparator is Litha's *current inference stack on the same machine* using identical quantization, context length, batch size and tasks.

Embeddable Lemonade deserves a separate acceptance pass: its `lemond` subprocess accepts a private directory, preconfigured backend versions and model store. An app can use `LEMONADE_API_KEY` to control access, separate model directories, and package pre-downloaded backend binaries. Tradeoffs include installer weight, version pinning, signed binary provenance, per-OS support, child process restart, update semantics, and redistributing bundled backend/model files. Lemonade's own docs explicitly suggest the embedded mode when you need white-labeled, private model deployment.

**Risks:** unguarded model downloads; GPU contention; accidental cloud offload; local API exposed on LAN without a key; passing `/internal` admin credentials to ordinary clients; downloaded models with separate licenses; confusing completion tokens/s with whole-request latency. The default prototype permits only loopback and forbids redirects and HTTP proxy forwarding.

### 2. AnythingLLM: knowledge and agent architecture

AnythingLLM is an integrated multi-user capable application rather than just an SDK. It supports desktop and self-hosted Docker deployments; their user-management and embedded-chat features differ. Workspaces, imported documents, embedded chunks, vector databases, agent skills, MCP servers, and chat sessions are resources in its own application layer. Desktop is simpler for one local user; Docker supports multi-user and role-based access. In Docker multi-user mode, document access is governed by workspace membership, whereas a developer API key may provide broader access; avoid exposing keys or arbitrary workspace selectors to Litha users.

The current repository's developer API implementation documents:

- `POST /api/v1/workspace/:slug/vector-search` with `query`, `topN` and optional `scoreThreshold`. It returns `results` with text, score and document metadata including title, source and URL. This can serve a **retriever** without asking AnythingLLM to generate a second answer.
- `POST /api/v1/workspace/:slug/chat` with `message`, `mode` (`query`, `chat`, `automatic`), optional `sessionId`, and optional attachments. It returns `textResponse`, `sources`, `type`, `error`. `query` mode confines the answer to relevant documents and does not use rolling history; `automatic` may invoke tools when the configured model supports them.
- `/api/docs` on the user's installed instance is the authoritative endpoint reference; API keys are bearer credentials. Never write them in GitHub, frontend builds or diagnostic logs.

Retrieval is not knowledge acquisition by model weights. Uploading documents and indexing their chunks allows later lookup; it does not prove a fact, cure outdated content, or guarantee the right chunk will be retrieved. Distinguish *document uploaded*, *indexed*, *retrieved*, *used in output*, and *fact validated*. For project knowledge, each source should eventually carry a scope, owner, revision/hash, timestamp, access policy, review status, and original-document locator. The prototype transports returned title/reference plus excerpt and score but does not manage ingestion, deletion, revision IDs or access control beyond the configured key.

AnythingLLM's **Intelligent Tool Selection** reranks which skill descriptions enter the context when tool count exceeds a threshold. Its docs claim up to 80% token savings and also report a small per-chat overhead, about 100–500 ms. This is a useful design to *benchmark*, not a verified Litha speedup. Start with deterministic scope/capability filtering, then optionally semantic reranking, and evaluate task success and false tool omission as well as tokens. A tool-selection score is not an authorization grant.

AnythingLLM's **Model Router** uses calculated rules (keywords, context size, attachment, etc.) and LLM-classified rules. Deterministic rules are cheap and inspectable. LLM-classified routing adds classifier latency/risks misrouting. If Litha already routes models, treat this as one set of candidate policies rather than start a second inconsistent router. Place privacy, local-only, permission and model-capability constraints **ahead of** soft latency/cost preferences.

**Memories & Personalization:** recent AnythingLLM docs describe manual and automatic memory extraction using an Observer/Reflector two-stage review: generate candidate facts with confidence, then classify scope, deduplicate and consolidate them. This is a strong pattern to implement in Litha's own memory layer after tests. It should not silently save sensitive personal information or treat the model's guesses as observations. Its documented built-in limit is 20 workspace memories plus 5 global memories per user; those are AnythingLLM limits, not desirable global limits for all of Litha.

**Scheduled Jobs** (introduced by AnythingLLM 1.13) runs agents with a defined prompt, cron schedule and permitted tools, and stores run artifacts/traces. The cited docs say this feature is restricted to single-user mode, so do not assume it is a ready-made multi-tenant scheduler. The general design (job intent + tool allowlist + durable run record + result review) is reusable, but Litha should own its scheduler if it needs broader policy and reliability.

**MCP and custom skills:** AnythingLLM has stdio, SSE and streamable MCP configurations, UI status/logs, and optional `autoStart:false`. Node.js custom skills can invoke OS utilities and should be treated as untrusted executable extensions until reviewed. External tools must be separately authorized by the task user. They should never be auto-enabled simply because a retrieved document instructed the model to use them.

### 3. Critical security lessons

1. Treat vector results, PDFs, web pages, agent memories, and tool output as **untrusted text**. Retrieval can surface prompt injection. Use strict tool isolation, scoped authorization, human review for externally consequential actions, and adversarial regression tests.
2. API keys are powerful. Lemonade's `LEMONADE_API_KEY` protects regular endpoints if configured; `LEMONADE_ADMIN_API_KEY` is stronger and should not be sent to Litha chat clients. AnythingLLM keys must be held server-side; don't use the browser UI to call privileged internal keys directly.
3. Prefer loopback. For multiple machines, use a trusted authenticated tunnel or HTTPS with identity verification and explicit opt-in. Don't rely on an unauthenticated server listening on `0.0.0.0`.
4. Workspaces are data boundaries only to the degree enforced by the upstream instance and its API credentials. Test cross-workspace read/write denial. Deleting a workspace's vectors is not necessarily deleting the original document from the global document library.
5. Keep third-party products updated. AnythingLLM published a critical Desktop advisory for streaming-output XSS leading to code execution in versions <=1.11.1, patched in 1.11.2+. No UI rendering code is imported by this adapter; this nevertheless supports keeping untrusted model responses out of raw HTML in Litha.
6. Never give document-grounded generations autonomous file/terminal/network execution without an independent permission boundary. The prototype intentionally contains **zero** tool-execution API.
7. A claimed citation like `[S1]` generated by an LLM is not independently verified. A separate source list records what was *retrieved*; a human/validator must verify that it *supports the answer*.

### 4. Which capabilities to actually build, in order

**Phase A — keep the current app stable (this package):** opt-in Lemonade provider, installed-model discovery, health and last-request stats; AnythingLLM workspace retrieval and query-mode chat; small bounded evidence-to-inference wrapper; URL and secret safety tests. No backend autoinstall or cloud providers. Note that Litha integration remains unperformed until its repo is available.

**Phase B — knowledge quality:** typed source identity (`workspace, document, version, span`), ingestion ledger, review approval, dedupe, lexical + vector hybrid retrieval, multilingual evaluation, reranking/abstention, citations verified against source spans, stale-document detection, deletion propagation. If AnythingLLM lacks a feature or conflicts with Litha's DB, **implement the pattern locally** rather than forking the entire product.

**Phase C — intelligent routing:** capability-aware model selection, deterministic privacy/resource policy, model warm pool (only when memory allows), cache retention/eviction analysis, retrieval-conditioned prompt compression, and tool shortlist ranking with latency and recall gates. Compare to Lemonade aliases/routing to avoid duplicated authority.

**Phase D — autonomous but accountable workflows:** typed tools/permissions; `plan -> execute -> inspect -> evaluate -> record` job graph; idempotency keys; bounded parallelism; cancellation and rollback; run traces; model and external tool provenance; reviewed promotion of lessons; human approval for destructive or high-impact operations. Scheduled execution must be explicitly enabled by the operator.

**Phase E — multimodal and distribution:** only after A–D, test hardware-backed STT/TTS/vision/image APIs, and decide whether embedding `lemond` reduces operational burden compared with a separately installed service. Bundle only models/backends with vetted licenses and maintain signed manifests and update paths.

### 5. Acceptance benchmark design

No direct speed or quality gains have been measured. An honest implementation gate would use these experiments, with fixed versions and a comparable baseline:

| Measurement | Test | Acceptance criterion |
|---|---|---|
| Local inference quality | Same 30 prompts/seed/context and quantization, baseline vs Lemonade | No meaningful accuracy regression; investigate formatting differences |
| Cold startup + first token | 10 cold and 30 warm runs per hardware class | Report median, P95, and full end-to-end latency separately |
| Throughput/resource | 1/2/4 concurrent chats with system RAM and VRAM logs | No OOM/eviction thrashing, rate-limit when contention appears |
| RAG source retrieval | >=50 held-out document queries; expected spans known | Report recall@4, MRR, freshness, and out-of-scope misses |
| Grounded answers | >=30 answerable + >=20 unanswerable queries | Citation precision and abstention, not just answer fluency |
| Workspace privacy | Cross-project queries; malicious source text | Zero unauthorized cross-workspace access and zero automatic tool actions |
| Tool selection | Baseline all tools vs ranker, same problem set | Task success >= baseline; measure missed essential tools and token savings |
| Model routing | Deterministic rules vs existing Litha router | No privacy-policy violation, record wrong-model and fallback counts |
| Agent run recovery | Kill/restart tasks before, during, after a tool step | No duplicate external effects; trace and compensating actions correct |
| Upgrade/packaging | Windows/Linux supported target with real service versions | Repeatable clean install, uninstall, restart and offline behavior |

**Performance accounting:** Lemonade's `/stats` returns last-request data (e.g., time-to-first-token, tokens/sec, input/output/cache tokens) and must not be mistaken for per-user lifetime totals in shared service operation. Log correlation ID and wall-clock time at Litha's orchestration boundary. Account for `GET /models` preflight overhead, tokenization, retrieval, model switches, network loops and cold starts. Small local models may finish sooner but produce poorer grounded answers, so evaluate **useful correct answers per second**, not raw tokens/sec alone.

### 6. Build-vs-integrate decision

| Candidate | Integrate external service? | Why |
|---|---|---|
| Lemonade LLM API | **Yes, opt-in** | Stable HTTP boundary; minimal duplicate code |
| Lemonade Embeddable runtime | **Later, conditional** | Great distribution option; not needed for initial proof |
| AnythingLLM vector-search | **Yes, opt-in** | Fastest path to inspect real workspace RAG capabilities |
| AnythingLLM full UI | **No** | Would replace or compete with Litha UX |
| AnythingLLM agent executor | **Not by default** | Expands trust/execution perimeter and duplicates orchestration |
| AnythingLLM model router | **Borrow patterns** | Avoid double routing and policy conflicts |
| AnythingLLM Observer/Reflector memory | **Borrow patterns** | Scoped, deduplicated and reviewable candidate memories |
| AnythingLLM scheduled jobs | **Borrow patterns** | May not fit multi-user or local policy requirements |
| Unrestricted MCP auto-install | **No** | Third-party executable trust risk |

### 7. Source index (primary first)

- Lemonade README: https://github.com/lemonade-sdk/lemonade
- Lemonade OpenAI API: https://lemonade-server.ai/docs/api/openai/
- Lemonade-specific API and stats: https://lemonade-server.ai/docs/api/lemonade/
- Lemonade embedded service: https://lemonade-server.ai/docs/embeddable/
- Lemonade embedded runtime auth and process: https://lemonade-server.ai/docs/embeddable/runtime/
- Lemonade configuration and security: https://lemonade-server.ai/docs/guide/configuration/
- AnythingLLM source and MIT license: https://github.com/Mintplex-Labs/anything-llm
- AnythingLLM API: https://docs.anythingllm.com/features/api
- AnythingLLM route contracts: https://github.com/Mintplex-Labs/anything-llm/blob/master/server/endpoints/api/workspace/index.js
- AnythingLLM Lemonade integration: https://github.com/Mintplex-Labs/anything-llm/blob/master/server/utils/AiProviders/lemonade/index.js
- AnythingLLM source-based model router: https://docs.anythingllm.com/model-router/overview
- AnythingLLM intelligent tool selection: https://docs.anythingllm.com/agent/intelligent-tool-selection
- AnythingLLM memory extraction: https://docs.anythingllm.com/features/memories
- AnythingLLM scheduled jobs: https://docs.anythingllm.com/scheduled-jobs/overview
- AnythingLLM MCP: https://docs.anythingllm.com/mcp-compatibility/overview
- AnythingLLM Docker vs Desktop: https://docs.anythingllm.com/installation-docker/overview
- AnythingLLM 1.11.2+ security advisory: https://github.com/Mintplex-Labs/anything-llm/security/advisories/GHSA-rrmw-2j6x-4mf2

## Exact limits of this work

- GitHub connector did not present a Litha repo with push access. No branch, commit, draft PR or deployment for Litha was created.
- Main connected workstation's `~/projects` directory did not contain a folder named Litha; this limited directory check does **not** establish absence elsewhere.
- This package implements a Python *candidate adapter*, not native integration in Litha's unknown programming language.
- The 25 passing tests use simulated HTTP servers, not real Lemonade, AnythingLLM, Litha, AMD NPU, CUDA GPU or model-quality tests.
- The retrieved chunks remain untrusted even when they originate from an ostensibly trusted AnythingLLM workspace.


## Review note — October 30, 2026

The standalone adapter has a reviewed 0.1.1 candidate with 42 offline tests. See the package README for changed behavior and the enclosing STAR audit for measured experiments. The original research remains a dated source snapshot, not evidence of deployment or performance gains.
