# Litha agent-interface research: BoardUI and beyond

**Research date:** 2026-11-02  
**Applies to:** Litha (successor to STAR Intelligence), local-first Windows/Qt desktop with a React 19 / TypeScript / Vite frontend and Python backend.  
**Status:** Architectural research + narrowly scoped frontend implementation in a review branch. Longer-term items below are **not** implemented by this document.

## Executive decision

Use BoardUI as an interaction/design-systems reference, **not** as a replacement frontend, Next.js migration, design clone, or runtime dependency. Keep Litha's existing composer and its functionality. Implement a small original run-state aura that reflects the current host-reported `ActivityRun`; pursue durable event replay, tool receipts, source provenance, and conductor inspection only when supported by actual backend records.

A trustworthy Litha interface must be:

1. **Truthful:** no progress, evidence, approvals, finished tests, or agent execution fabricated by animation timers.
2. **Fast and local-first:** no new remote UI dependency, no activation-time network call, no expensive JavaScript render loop around the composer.
3. **Distinctive:** existing semantic dark/metallic-gold tokens rather than BoardUI's iridescent demo palette.
4. **Accessible:** real labels and live regions, accessible focus and controls, reduced motion in both OS and application settings.
5. **Compositional:** UI is a read-only projection of backend events; permissions and side effects remain in the host, never in CSS/React.
6. **Reviewable:** a small feature-focused branch and tests, with unfinished items stated as research rather than shipped capabilities.

## Research and provenance

Upstream sources checked (official sources, 2026-11-02):

- BoardUI catalogue: https://www.boardui.com/components — source-owned React/Tailwind system, 106 catalogue entries shown on inspection; some entries are Pro. This catalogue is not a list of 106 free components.
- BoardUI Composer Loader: https://www.boardui.com/components/composer-loader — SVG stroke-path, thin leading line, glow and bloom, adjustable phase/arc/speed; adapts to the composer geometry. **The actual upstream source** was inspected at https://github.com/BoardUI/boardui/blob/main/components/application/composer-loader/composer-loader.tsx .
- BoardUI Agent Thinking: https://www.boardui.com/components/agent-thinking — wave, spin, stars and infinity, elapsed time and reduced-motion fallback.
- BoardUI Agent Progress: https://www.boardui.com/components/agent-progress — a Pro component; its demo can advance by duration. Do **not** equate an animated duration with a completed backend task.
- BoardUI Web Search: https://www.boardui.com/components/web-search — query and visited-source trail. Litha must use host-provided source receipts and real URLs if it builds this.
- BoardUI MCP: https://www.boardui.com/mcp — agent-aware component discovery, usage examples, installation. Litha should consider a native registry; do not add the BoardUI CLI or MCP to the production app.
- BoardUI license: https://www.boardui.com/license — **free GitHub sources are MIT; Pro has separate terms.** A Pro component cannot be treated as MIT merely because its demo is visible. Original implementations and high-level interaction concepts are acceptable; do not copy/re-distribute Pro source.
- BoardUI free GitHub: https://github.com/BoardUI/boardui — source-owned component approach, React Aria foundations, semantic tokens, RTL rules.
- assistant-ui tool UX: https://www.assistant-ui.com/docs/tools/tool-ui — explicit lifecycle states, human input/approval, tool receipts.
- assistant-ui multi-agent: https://www.assistant-ui.com/docs/tools/multi-agent — nested task inspection and read-only sub-agent transcripts.
- assistant-ui resumable streams: https://www.assistant-ui.com/docs/guides/resumable-streams — replay from persisted producer data after reconnect.
- Vercel AI Elements: https://elements.ai-sdk.dev/components/tool and https://elements.ai-sdk.dev/components/reasoning — tool-status presentation, explicit distinction between reasoning content and structured events. Its message docs report a forthcoming move to shadcn/ui/deprecation, another reason not to depend on an imported framework.
- React Aria: https://react-spectrum.adobe.com/react-aria/ — accessible primitives for complex controls.
- ResizeObserver: https://developer.mozilla.org/en-US/docs/Web/API/Resize_Observer_API — resize-driven measurement without a JS polling loop.
- Reduced motion: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/%40media/prefers-reduced-motion — OS accessibility preference; also respect Litha's own setting.

This research is a **design study**, not a claim that BoardUI Pro packages were installed or that all referenced features have been implemented.

## Baseline audit: what is already in the project

Inspect before replacing anything:

| Area | Existing evidence | Decision |
| --- | --- | --- |
| Chat composer | `frontend/src/Composer.tsx` | Preserve modes, attachments, screenshot consent, voice, web, teams, image mode, source access, stop, keyboard support, tool availability notes |
| Existing visual tokens | `frontend/src/tokens.css` | Continue semantic variables for background, focus, border, text, accent and statuses; avoid transplanting a foreign theme |
| UI motion policy | `frontend/src/MotionPolicy.tsx` | Continue OS + app reduced-motion enforcement |
| Run model | `frontend/src/activity.ts` | Source of truth for real states; already knows route, model, tools, Luau checks, team plan, streamed text, success/failure/cancel |
| Run timeline | `frontend/src/ActivityTimeline.tsx` | Preserve explicit activity, actual time, tool/agent state and stop; never collapse all meaningful failures into success |
| Host event handling | `frontend/src/Desktop.tsx` | `BackendEvent` is keyed to a request, transformed by `applyProgress`, and then rendered |
| Desktop transport | `frontend/src/bridge.ts`, `frontend/src/types.ts` | Real host connection, but no durable replay protocol is evidenced by the current UI contract |
| Visual / accessibility tests | `frontend/src/composer.test.tsx`, `frontend/src/a11y-motion.test.ts` etc. | Reuse their patterns, extend coverage, and run Windows Qt/CPU performance checks before releasing |

The current backend event contract exposes progress/result/error and maps them into `ActivityRun`. That is **not the same thing** as an append-only replayable event journal; durable resumption is a future change.

## Concrete component mapping and priorities

### P0 — Implemented in this branch

**Litha Run Aura** (`frontend/src/RunAura.tsx`, `frontend/src/run-aura.css`):

- Wraps the *existing* composer; does not repaint its input, change model choice, intercept clicks or alter focus.
- Uses two original SVG strokes (soft glow + thin trace), one path, CSS-driven dash animation; no timer and no per-token imperative animation.
- Resizes when the composer changes shape via `ResizeObserver`; falls back if unavailable.
- Reads a `RunAuraPhase` projection from `ActivityRun`: idle, working, researching, verifying, stopping.
- Only declares researching when the latest running event is an actual search step. Verification styling requires a reported Luau-check event/tool; generic tools are **not** verification.
- Is visually inert after completion, failure or cancellation. No fabricated percent, fake source URLs, or checkmarks.
- Is marked `aria-hidden` and delegates actual text/status reporting to the existing timeline.
- Falls back to a static accent with reduced-motion; hides the effect in forced-color mode.
- Uses existing local dark/gold variables. **No BoardUI source or Pro component copied.**

Tests in `frontend/src/run-aura.test.tsx` cover event projection, terminal outcomes, generic tools, accessibility invisibility and rendering.

### P1 — Next: coherent tool receipts, not arbitrary generated UI

Introduce one **typed tool-event identity** emitted by the host:

- A stable `toolCallId`, `runId`, `toolKind`, display summary, status, start/end timestamps, and sanitized safe result metadata.
- Status is one of queued, running, awaiting approval, completed, failed, blocked, cancelled.
- Every completed/failed tool displays a receipt derived from a backend record, never from a model claim in text.
- Approval controls must round-trip through the current host policy gate, bind to exact action/id/version, expire appropriately, and become a locked receipt when resolved. A text response alone must never authorize a privileged action.
- Records should not expose secrets, raw file paths, provider headers, stored prompts or private outputs in logs/analytics.
- GitHub UI: PR title, **draft** state, changed-file count, test results only when actual CI/test evidence exists; never print a synthetic passing check.
- Luau UI: differentiate static analysis, offline sandbox, Studio test and production publication (separate evidence and authorization levels).
- Browser research UI: show each query/source only when the backend provided it; retain provenance and distinguish fetched content from a synthesized answer.

Suggested renderer registry: `toolKind -> (Running / Complete / Error / Approval / Receipt)`, with an unknown-tool fallback. Don't ship a large dependency solely to reproduce a simple state card.

### P2 — Conductor Inspector

Use the existing `activity.ts` plan and agent steps as the core model, but extend the host payload carefully:

- Agent ids, parent agent ids, role, provider/model, actual dependencies, budget, started/end timestamps and an actual status.
- Sibling agents may run in parallel; show a tree or DAG with confirmed state, not a linear decorative list.
- An agent claiming to have tested something is **not proof** of a test. Verification must link to a test run artifact/report generated by a trusted runner.
- Summary-first interaction: collapsed by default when the answer finishes, expandable on demand. Avoid multiple timers rerendering the entire chat.
- Read-only nested agent traces until a specific authenticated approval request permits input.
- Inspector tabs: Files/Diffs, Tool receipts, Test evidence, Browser sources, Roblox Studio, Blender, Media. Render only tabs with real data and supported host capabilities.

### P3 — Durable, resumable runs (architectural proposal only)

Proposed **host-owned** versioned event envelope:

```ts
type LithaEventV1 = {
  schemaVersion: 1
  runId: string
  threadId: string
  sequence: number          // monotonic per run; not a timestamp
  observedAt: string        // ISO 8601 host UTC time
  kind: 'plan' | 'agent' | 'tool' | 'source' | 'output-delta'
      | 'artifact' | 'approval' | 'usage' | 'terminal'
  payload: unknown          // schema-validated and redacted by host
}
```

Transport/recovery:

1. Python host persists allowed event envelopes in an append-only, bounded local journal with an explicit retention/clear policy. Storage must never be remotely accessible by default.
2. On reconnect, UI requests `snapshot + events after lastSequence` for **the current authenticated owner/thread**, never a global event feed.
3. Reject duplicate, stale, out-of-order or wrong-thread envelopes. A gap triggers a fresh snapshot and explicit `reconnecting` state, not fabricated completion.
4. The host is authoritative on run life cycle and on cancellation. UI restart cannot start an accidental duplicate run.
5. Deliberately separate `producer complete`, `saved to chat` and `UI caught up`.
6. Expired/abandoned runs receive a host-generated interruption status; no forever-spinning cursor.
7. Stable tool approvals bind to current run and action and must never reappear as active after resolution/replay.
8. Multi-agent events have stable parent and child ids, causal references, and their own bounded payloads.

**Do not claim resumability merely because the frontend can rebuild an `ActivityRun` in memory.**

### P4 — Native Litha UI registry for self-building

Create a first-party component specification catalog, tied to **Litha's** visual language:

- Components: composer, message, run aura, run timeline, tool status, tool receipt, approval card, source trail, agent tree, artifact inspector, diff, file tile, command palette, accessibility form primitives.
- Every entry documents stable name/id, props, intended semantic tokens, keyboard/focus behavior, example screenshots/fixtures, editable source path, platform restrictions and reduced-motion behavior.
- All code generators must prefer installed components over inventing new variants. UI render checks can detect raw hex colors, inaccessible unlabeled controls, duplicate component patterns, over-animation and unsupported data claims.
- Provide an optional read-only query interface to the registry for coding agents. Do not automatically grant file write permissions or expose arbitrary filesystem paths.
- Update tokens/registry only with human-reviewed snapshots and tests; no model-generated change may edit its own independent acceptance tests.
- Keep Figma as a design source if one is established; Figma integration is not necessary to render the app.

## Detailed UX rules for Litha

**Composer:** preserve Enter/Shift+Enter and IME safety; keep mode, model, voice, files, screenshots, team and image controls. Never substitute a blank BoardUI Pro composer. No animated input background under text.

**Status:** display a single accurate phase sentence in the existing status/timeline. No separate repeated live regions announcing a changing timer; elapsed seconds should be visually present but not repeatedly announced.

**Sources:** query -> opened URL -> retrieved evidence -> cited answer. Links must reflect the fetch record and remain available in the receipt. A search API call does not prove the model actually read a page.

**Tasks:** parent/child status is derived from exact agent lifecycle events, with queued distinct from blocked and cancelled. Completion % is allowed only if the host knows a finite list of tasks; progress from a timed animation is a demo only.

**UI quality:** calm background, restrained borders, consistent radius and typography; a single focused accent on the primary action. Excess shimmer, giant glowing cards, floating decorative shapes and repetitive `Thinking...` toasts lower perceived quality.

**Permissions:** new tools/network browsing/agents remain OFF unless the owner has explicitly enabled them. Visual UI never bypasses host enforcement.

**Localization:** use semantic direction-aware layout and accessible names; code snippets/paths/URLs remain LTR; do not introduce BoardUI's RTL provider unless replacing current focus behavior is demonstrably safe.

## Research-informed trade-offs

| Option | Benefit | Cost / reason not to adopt wholesale |
| --- | --- | --- |
| BoardUI free source | Great examples of source-owned UI, tokens, loaders and think states | Next.js/Tailwind conventions mismatch existing Vite/Qt/CSS app; import only if a specific component pays its complexity |
| BoardUI Pro | Rich component inspirations and templates | Separate licensing; no Pro code distributed in this public repo without appropriate rights and policy review |
| assistant-ui | Excellent typed tool lifecycle and nested task UI, resumable stream documentation | Would be a chat-runtime rewrite; take protocols and interaction patterns, not a dependency for this feature |
| AI Elements | Useful accessible patterns for tool/reasoning/results | Tied to different SDK/stack, plus announced end-November-2026 packaging transition |
| React Aria | Robust keyboard/focus primitives for advanced future widgets | Gradual replacement only; current composer has tests and established behavior |
| Bespoke Litha components | Native visual identity and exact host integration | Requires stronger tests, registry and maintenance discipline |

## Acceptance tests and performance gates

These are **targets / tests to run**, not measured results:

- Phase truth table: idle, sending, source search, official docs lookup, real Luau-check, generic tool, stopping, terminal done/failed/cancelled; verify only actually reported states render.
- Aural noise: no duplicated live regions or 100ms announcements; stop and type remain keyboard operable; focus remains on the input as the busy state changes.
- Geometry: 320px narrow view, normal desktop width, 200px textarea growth, attachment rows, zoom at 100/125/150%, Windows Qt WebEngine on real hardware.
- Reduced-motion: Windows preference **and** app setting; no moving band in either case, static readable border if active.
- Performance: no extra JS animation timer, no width polling, no effect-driven resizing loop; run browser profiling and avoid layout shifts when starting/stopping the aura.
- Smoke: submit message, view real search/step, cancel, fail, complete, switch chats mid-run, reopen app; no ghost glow or stale response.
- Build: `cd frontend && npm ci && npm run typecheck && npm test -- --run && npm run build` with available supported Node/OS, plus project's actual package scripts/CI. This branch has not independently validated a Windows packaged EXE.
- Release gate: no regression to screenshot consent, attachments, team mode, voice, file access, editable prompt, existing single-source-of-truth run model.

## Scope boundary / completion ledger

| Item | Status in this change |
| --- | --- |
| BoardUI catalogue, Composer Loader, Agent Thinking, Agent Progress, Web Search, MCP and license review | Research recorded here |
| assistant-ui / AI Elements / React Aria / Web API comparison | Research recorded here |
| Original phase-driven composer aura | Implemented in source |
| Truthful phase mapping + component tests | Implemented in source |
| Keep existing composer and activity reducer | Preserved |
| Production tool receipts / approval cards | Design proposal; not implemented |
| Full multi-agent conductor tree | Design proposal; not implemented |
| Durable host-side replay journal | Design proposal; not implemented |
| Independent component MCP server / design registry | Design proposal; not implemented |
| Runtime and Windows EXE validation | Not claimed without actual CI/machine results |

**Principle:** implement one coherent vertical slice, validate it, and only then build the next surface. The strongest UX is one that accurately communicates what Litha can prove.
