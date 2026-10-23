# Strata + Qwen3.8-Flash-Next in STAR

STAR can use a second local OpenAI-compatible engine for hard work while keeping
its small resident brain for ordinary chat.  The first supported specialist is
Strata running Qwen3.8-Flash-Next.

## What STAR changes

When **Settings → Model → Use Strata for hard local work** is on and the selected
provider is **Local**, STAR keeps simple/Fast chat on the ordinary local brain and
routes these profiles to Strata:

- deeper reasoning and multi-file code work;
- Roblox/Luau engineering;
- source-grounded research;
- Agent mode, including tool loops;
- image inspection when **Let Strata inspect images** is enabled.

The route is deterministic and opt-in.  STAR does not download model weights,
install Strata, start Strata, change drivers, or expose a port.

The default Strata endpoint is:

`http://127.0.0.1:8082/v1`

This is deliberately different from STAR Brain's normal `8080` port so both can
exist at the same time.  The integration accepts loopback only.  A future remote
mode must use an authenticated private endpoint rather than silently exposing a
no-key model server.

## Failure behavior

STAR opens both clients for a Strata-routed task:

1. the Strata client;
2. the resident local brain as a fallback.

A fallback is allowed only when Strata is unavailable before it has produced a
stream chunk: connection failure, timeout, model-not-found, service unavailable,
or an engine/OOM-style failure.  Once a chunk was observed, STAR does not replay
the request on another model.  Once a task falls back, every later model call in
that task stays on the resident brain so a tool loop cannot bounce between
engines.

This preserves STAR's existing rule: do not replay a potentially side-effecting
agent turn after model/tool work has begun.

## Qwen request policy

Qwen3.8 thinking consumes output tokens before the visible answer/tool call.  STAR
therefore gives Strata larger output budgets than its small chat model:

| profile | default reasoning | minimum output budget |
| --- | --- | ---: |
| reasoning | medium | 4096 |
| Roblox | high | 6144 |
| research | medium | 4096 |
| Agent | high | 8192 |

The owner can override reasoning with `none`, `low`, `medium` or `high`.
Automatic mode uses the table above.

Thinking requests use Qwen's recommended sampling starting point
(`temperature=1.0`, `top_p=0.95`, `top_k=20`).  No-thinking requests use
`temperature=0.7`, `top_p=0.8`, `top_k=20`.

STAR's generic agent accepts only the bounded standard sampling overrides
`temperature` and `top_p`; Strata-specific `reasoning_effort` and `top_k`
are supplied by the trusted backend module, not by model output or project files.

## Context and time budgets

The default Strata context is 32K tokens.  STAR converts that to a conservative
character budget for its existing context manager rather than pretending
characters equal tokens.  The setting can be 4K–256K tokens.

The default Strata request timeout is 900 seconds.  Agent tasks may receive up to
twice that task budget because they can contain several model/tool turns.  The
ordinary resident model keeps its existing limits.

## Running Strata

Install and launch Strata separately using its upstream instructions.  To coexist
with STAR Brain, launch the chosen model on port 8082, for example with Strata's
`--port 8082` option, then confirm its OpenAI-compatible models endpoint answers:

```text
http://127.0.0.1:8082/v1/models
```

The model ID exposed by Strata is commonly `strata`; Settings lets the owner
change it to the ID the server actually reports.

Do not enable the STAR switch until Strata is installed and the model has enough
local RAM/VRAM/disk for the chosen quant.  The fallback prevents a hard outage,
but it does not make an undersized Strata configuration fast.

## Measuring whether it is actually better

Token speed is not the promotion criterion.  Use STAR's existing benchmark and
evaluation infrastructure to compare:

- successful task completion;
- repair attempts;
- time to first useful answer/tool call;
- total elapsed task time;
- tool/test outcomes;
- peak RAM/VRAM and desktop responsiveness;
- fallback count.

The new backend emits `strata_selected` and `strata_fallback` events so the
desktop/analytics path can distinguish intended Strata work from resident-brain
fallbacks.

For quality experiments, compare Strata's normal acceleration settings with
route-tail skipping disabled at the Strata process level.  Do not describe cache
adaptation or expert placement as model training: STAR's evidence-backed lesson
loop remains the learning mechanism.

## Source

Implementation:

- `star/strata_backend.py`
- `star/desktop_core.py`
- `star/agent.py`

Regression coverage:

- `tests/test_strata_backend.py`
- `frontend/src/settings-page.test.tsx`

This integration intentionally does **not** bundle or redistribute Qwen weights.
Strata's software license and the Qwen model-weight license are separate; review
the model license for the intended distribution/commercial use before shipping
weights as part of STAR.
