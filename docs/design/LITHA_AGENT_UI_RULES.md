# Litha agent-interface design and implementation rules

Applies to new Litha user-interface work in `frontend/src`. These rules complement, and do not override, `AGENTS.md`, `docs/STAR_DESIGN_SYSTEM.md`, security/policy enforcement and the existing UI tests.

## Identity and source ownership

- Litha is the successor to STAR Intelligence. Avoid a sweeping rename during a narrow UI change. Preserve legacy data, storage identifiers and host RPC contracts until a separately reviewed migration exists.
- Use the Litha/STAR semantic tokens in `frontend/src/tokens.css`; do **not** paste BoardUI's palette, runtime packages, theme or Pro templates into this Vite/Qt frontend.
- Native-first, readable OLED/dark surfaces; a warm accent belongs to a user action, selection, focused input or true run feedback, not random ornaments.
- Check `Composer.tsx`, `ActivityTimeline.tsx`, `components.tsx`, common `.css` files and installed primitives before adding a new control.
- If a component comes from external source, record its original URL, license, notice obligations and exact files. Public BoardUI free source is MIT; BoardUI Pro is not.

## Truthfulness and capability

- **Backend events are authoritative.** Do not represent search, testing, Luau execution, agent completion, tool success, source opening, model use or approval unless a trusted backend record exists.
- Use `activity.ts` for current run status; do not write a second independent run-state machine for visual effects.
- Visual transitions are *indicators*, not schedulers; they must never cause an agent run or completion.
- Distinguish: queued / running / waiting / blocked / failed / cancelled / done. Keep `failed` visible rather than converting every terminal state to a success icon.
- An LLM explanation about running a tool is **not** an execution receipt; only a host report supports completion or tests passed.
- When introducing source trails, only show real queries/opened sources with verified URLs and provenance; never invent metrics, citations or time-to-completion estimates.

## Human controls and permissions

- Existing composer capabilities are contractual: mode picker, image/attachments, web toggle, screenshots with consent, teams, voice, source access, model state, stop, IME-safe Enter and Shift+Enter.
- Make every new control keyboard reachable with visible focus, a clear accessible label and correct disabled semantics. Restore focus after closing popovers; do not steal focus when loading indicators appear.
- Permission decisions live in `star/policy.py` and the authenticated host. Never implement authorization as a frontend boolean or auto-run an approval on mount.
- New action-capable features remain OFF until the owner's explicit configuration enables them. Decorative state indicators are not grants of new capabilities.
- Approval requests bind to exact action, target, run and expiration. Render past decisions as receipts, not as active buttons on replay.

## Motion and performance

- Honor `MotionPolicy` and OS reduced-motion, plus forced-color behavior. Motion must not be required to understand status.
- Prefer CSS/SVG visual animations that avoid JavaScript timers, per-token reflow, layout shifts and expensive stacked blur layers.
- Observe element size only when geometry truly requires it; guard resize callbacks from causing loops and disconnect on unmount.
- Keep pointer-event-free decorative layers out of the tab order and screen-reader tree. Never cover the send/stop controls.
- Don't create multiple live regions for the same backend progress event or announce elapsed clocks every second.
- Measure actual Qt WebEngine performance on the target hardware before claiming smoothness, CPU headroom or a specific fps.

## Build-review standard

- Make small changes in unique branches; draft PRs only until CI, visual checks, accessibility and Windows smoke tests pass.
- Add tests for terminal outcomes, interrupted run, stale state, reduced motion, focus, cancellation and basic width changes as relevant.
- An agent-generated UI may not alter its own independent grading fixtures or falsely mark tests as passing.
- Do not expose secrets, local file paths, model prompts, unrestricted tool output or chat history in analytics.
- Report separately: implemented, checked by CI, verified in real Qt, and research-only ideas.

## Navigation

- Machine-readable component index: [Litha UI component catalog](LITHA_UI_COMPONENT_CATALOG.json), with implemented versus planned states and source/test links. Reuse the implemented entries; don't claim planned ones have code.
- Deep design analysis: [BoardUI and agent-interface research](../research/LITHA_BOARDUI_AGENT_INTERFACE_20261102.md).
- Existing run event reducer: `frontend/src/activity.ts`.
- Existing run activity UI: `frontend/src/ActivityTimeline.tsx`.
- New original feedback primitive: `frontend/src/RunAura.tsx`.
