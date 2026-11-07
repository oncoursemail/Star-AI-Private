# Litha local AI bridge — experimental integration candidate

**Status: not committed to a Litha repository.** Litha's source repository was not accessible through the connected GitHub account on 2026-10-29. This is an original, standalone Python adapter and test suite, designed to be reviewed and integrated into the correct codebase. No third-party code or model weights are bundled.

## Review update — October 30, 2026 (candidate 0.1.1)

42 offline tests now pass in the assistant's Python 3.13.5 Linux environment (the original 25 plus 17 regression tests). Fixes cover timed queue admission, strict settings and model metadata, aggregate prompt size, exact evidence excerpts and robust citation IDs. The 25-test note below is historical.

The generation interface remains non-streaming, and model-list preflight is still performed per call. Queue timeout is per client, not a global scheduler; the network timeout is not a strict total deadline. Reuse one client per endpoint when appropriate. This remains a standalone **Litha** candidate, not an installed STAR feature. No GitHub CI or live providers were tested in this review.

New environment options: `LITHA_QUEUE_TIMEOUT=5` seconds and `LITHA_MAX_PROMPT_CHARS=50000`. Both providers remain disabled by default.

## What it does

- **Lemonade SDK:** installed-model listing, health, last-request inference stats, and OpenAI-style text chat using the **already installed** model ID. No model downloads or model-manager writes.
- **AnythingLLM:** workspace-scoped `vector-search` and `chat` using the developer API and returned source metadata. Default chat mode is `query`; tool-using `automatic` mode is blocked by this adapter.
- **Grounded bridge:** retrieve up to four bounded excerpts from a specified AnythingLLM workspace, pass excerpts as labelled untrusted JSON to a local Lemonade model, and return independently recorded sources. If nothing is retrieved, do not call the LLM.
- **Safety properties:** both providers off by default, API keys taken from environment variables, localhost-only by default, remote endpoints require explicit opt-in **and HTTPS**, no proxy/redirect forwarding, no unbounded responses, no POST retry, no process/tool execution, and bounded local concurrency. The API key must never be committed.

This does **not** install Lemonade or AnythingLLM, add a document to a workspace, create an agent, improve model weights, or run in the background. It is not a benchmark claim.

## Setup

Requires Python 3.10+ and a running local installation of the external services. There are no Python runtime dependencies.

```sh
python -m pip install -e .
```

Set environment variables in your shell or secrets manager, rather than committing a `.env` file. The `.env.example` file is a reference and is **not automatically loaded**:

```sh
# These commands use Bash; use PowerShell's $env:NAME='value' on Windows.
export LITHA_LEMONADE_ENABLED=true
export LITHA_ANYTHINGLLM_ENABLED=true
export LITHA_ANYTHINGLLM_API_KEY='set-secret-locally'
# Only when Lemonade itself was configured with LEMONADE_API_KEY:
export LITHA_LEMONADE_API_KEY='set-secret-locally'
```

By default, `LITHA_LEMONADE_URL=http://127.0.0.1:13305/api/v1` and `LITHA_ANYTHINGLLM_URL=http://127.0.0.1:3001/api/v1`. Change the AnythingLLM URL for your installed deployment. Both service APIs are intentionally accessed via `/api/v1` (Lemonade also accepts `/v1`). Use per-service API keys; ensure the services themselves are configured to require credentials before permitting LAN access.

Check the local inference connection without modifying a model:

```sh
litha-bridge doctor
```

Obtain a workspace slug from your AnythingLLM instance and an **installed** model ID from `doctor`. Then:

```sh
litha-bridge ask --workspace my-docs --model MY_INSTALLED_MODEL "What is our rollback policy?"
```

Programmatic use:

```python
from litha_bridge import BridgeConfig, LemonadeClient, AnythingLLMClient, GroundedBridge
cfg = BridgeConfig.from_env()
bridge = GroundedBridge(AnythingLLMClient(cfg), LemonadeClient(cfg))
answer = bridge.ask("my-docs", "What is the release process?", model="MY_INSTALLED_MODEL")
print(answer.status, answer.text)
for i, source in enumerate(answer.sources, 1):
    print(f"S{i}: {source.title} [{source.reference}]")
```

The `status` becomes `needs_review` when the generated answer omits `[S1]`-style citations or references nonexistent source identifiers. A valid identifier is **not** proof that the source supports the claim.

**Note on grounding:** a model can still mishandle retrieved text, produce unsupported claims, or invent inline citations. The caller must not treat a citation-looking string as proof. Use the returned `sources` as a separate evidence trail, validate the relevant excerpts, and require explicit permission before taking real-world or code-execution actions.

## Tests

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
# On PowerShell:
# $env:PYTHONPATH='src'; python -m unittest discover -s tests -v
```

`25` offline tests passed on the local Python 3.13 environment on 2026-10-29. They use an isolated localhost HTTP mock, never cloud APIs. A proposed CI workflow tests Python 3.10 and 3.13 on Linux and Windows; that workflow has **not** run on GitHub.

## Host integration / migration checklist

1. Locate the **actual Litha repository**, identify language/entrypoints, and inspect existing local-model, knowledge, auth, and telemetry systems before merging.
2. If Litha is Python-based, add `src/litha_bridge` to the package and wire it behind a settings toggle, not as the default model provider. In a TypeScript/non-Python Litha, port the HTTP contract instead of introducing an unrelated Python runtime.
3. Configure a **specific** workspace slug for each Litha project and prohibit users from supplying arbitrary slugs without an authorization check. An AnythingLLM API key may have access broader than one workspace.
4. Validate installed model labels and context limits on real hardware. Keep automatic cloud offload and automatic model downloading explicitly off.
5. Run acceptance evaluations described in `docs/RESEARCH.md`, including adversarial documents and cross-workspace data leakage, before any wider rollout.
6. Publish via a **draft pull request** to the actual Litha repository and inspect the diff. Don't silently merge or deploy.

## Provenance and compatibility

Research captured 2026-10-29 against Lemonade default-branch reference commit `c306b768e0bc185650e47b3560c6aa6228f7f941` and AnythingLLM `3661da4cfffbd0d65bc1a2fb23787489d249dfd2`. Their APIs may change. Query Lemonade's installed `/v1/docs` and AnythingLLM's installed `/api/docs` for exact version contracts.

- Lemonade: https://github.com/lemonade-sdk/lemonade ; Apache-2.0 source license.
- Lemonade API: https://lemonade-server.ai/docs/api/openai/ and https://lemonade-server.ai/docs/api/lemonade/
- AnythingLLM: https://github.com/Mintplex-Labs/anything-llm ; MIT source license.
- AnythingLLM API docs: https://docs.anythingllm.com/features/api ; deployment's `/api/docs`.

See `docs/RESEARCH.md` for the deeper tradeoffs, limits, and prioritized implementation plan.
