# Litha: reliable, fast computer control

## Research and implementation review - October 31, 2026

This report studies how Litha can operate a Windows PC with the quality and responsiveness associated with leading computer-use agents. It combines current primary documentation, open-source implementations, benchmark methodology, inspection of Litha's actual repository, a focused driver patch, independent offline checks, and a deterministic timing experiment. Research claims, proposed architecture, and executed results are identified separately. No result establishes that Litha now exceeds ChatGPT, Claude, or human performance.

## Report map

- Executive synthesis: priorities, current Litha components and the implemented change.
- Chapter A: OpenAI and Anthropic integration contracts, coordinates, batching and state.
- Chapter B: Windows UIA, browser control, Roblox Studio, Blender and component selection.
- Chapter C: benchmark versions, open agents, measurement and Forge learning.
- Appendix D: implementation guide and actual offline validation results.
- Appendix E: primary-source register and pinned Litha source references.

The accompanying repository files include executable checks, the complete simulation output, a machine-readable source register, and 30 native acceptance cases marked not run. This report is a review artifact. It does not establish a deployed change or native speed improvement.

## Executive decision

The strongest path is to improve how Litha chooses and verifies operations. Use typed application operations for exact edits, browser structure for web tasks, accessibility controls for conventional Windows interfaces, and visual grounding where those interfaces cannot describe the target. Keep one owner of an interactive desktop's input. Reduce unnecessary model calls, avoid replaying uncertain mutations, and learn reusable procedures only after independent checks.

This is an extension of an existing controller. The inspected project already has cached Windows UI Automation, a bounded latest-frame capture service, local and remote vision grounding, human-paced input, machine enrollment, STOP handling, action logs, skill macros, and separate planning and execution loops. Adding a second general controller would duplicate substantial work. [R01](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py) [R02](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py) [R03](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/screen.py) [R04](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py) [R05](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py) [R06](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/hands.py) [R07](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/winapi.py) [R08](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py) [R09](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/settings.py) [R10](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/agent.py) [R11](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/__init__.py) [R12](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/live_vision.py) [R13](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/identity.py) [R14](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/stopswitch.py)

The focused change fixes concrete recovery defects in the existing driver and adds an optional positive-postcondition wait. The new wait remains disabled by default. Fake-clock experiments establish its scheduling behavior; native Windows acceptance and complete-task latency measurements are still required before enabling it on the user's machine.

### Recommended priorities

| Priority | Work | Why it has value | Required evidence |
|---|---|---|---|
| 1 | Fix replay after uncertain effects | Prevent duplicated text, repeated clicks and unnecessary recovery | Failing baseline reproductions and independent passing checks |
| 2 | Measure full task latency | Distinguish model, capture, application and waiting costs | Stage timings, complete outcomes, retries and resources |
| 3 | Prefer qualified native operations | Collapse many low-level interactions into a precise operation | Same application result and no new side effects |
| 4 | Use outcome-based waits selectively | Stop waiting when a new explicit result is already available | Native false-success rate, observation cost and p95 time |
| 5 | Bind actions to current targets | Avoid stale coordinates, wrong windows and competing input | Native focus, DPI, takeover and session tests |
| 6 | Evolve reusable interfaces through Forge | Convert repeated successful work into transferable skills | Held-out validation, versioning and rollback |

## 1. What exists in Litha today

The repository inspected is `oncoursemail/Star-AI-Project`, development branch `star/next`, commit `a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f`. The default branch was also inspected. Relevant open capture, Studio-practice and debugger PRs were checked for file overlap. This work uses a separate draft branch and does not merge or deploy it.

| Existing component | Observed behavior | Consequence for this work |
|---|---|---|
| `star/computer/uia.py` | Uses `FindAllBuildCache`, cached properties and cached-only elements | UIA caching is already implemented; future work should reduce observation scope or add qualified action patterns |
| `star/computer/eye.py` and `live_vision.py` | Latest-frame capture, age limits, capture ownership and cleanup | Improve evidence identity and consumption; do not add an unbounded screenshot queue |
| `star/computer/ground.py` | UIA, local vision, then optional remote vision | Preserve deterministic grounding before model inference |
| `star/computer/driver.py` | Observe, ground, act, verify, retry; fixed settling delays | The concrete recovery and wait changes belong here |
| `star/computer/agent.py` | Separate model-driven action loop and some visual target checks | A driver change does not automatically modify this whole planner loop |
| `star/computer/hands.py` and `winapi.py` | Human-paced input, STOP checks and native delivery errors | Native delivery and application completion remain separate facts |
| `star/studio.py` | Existing official Studio MCP transport, bounded discovery and explicit instance selection | Extend capability validation in the existing connector rather than replacing it |
| `star/computer/settings.py` | Local configuration, remote vision off by default | Add the new waiting option with a disabled default |

Sources: [R01](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py) [R02](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py) [R03](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/screen.py) [R04](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py) [R05](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py) [R06](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/hands.py) [R07](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/winapi.py) [R08](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py) [R09](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/settings.py) [R10](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/agent.py) [R11](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/__init__.py) [R12](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/live_vision.py) [R13](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/identity.py) [R14](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/stopswitch.py). Prior handoff notes contain historical tests and measurements, but those do not establish the current deployment state. This review did not connect to Brain 1, Brain 2, the owner's desktop, or a native Studio/Blender process.

## 2. The architecture most likely to improve speed and quality

### Select the interface that best expresses the operation

A file rename, a Blender data change, a browser form value and a visual 3D inspection are different tasks. A useful router chooses a qualified interface based on the required effect and available evidence, rather than always asking a model for another pointer coordinate.

| Task family | First route to evaluate | Verification |
|---|---|---|
| Exact file and code work | Scoped filesystem operations, editor interfaces or CLI | Content diff, parse/build result, saved file identity |
| Roblox development | Existing official Studio MCP connector with explicit instance | Data-model state, console, playtest and viewport evidence |
| Blender asset processing | Existing Blender bridge/data operations or a bounded background job | Object/mesh properties, saved artifact, export round-trip and renders |
| Browser workflows | Page-aware driver with semantic locators | Field values, navigation state and application-level result |
| Conventional Windows controls | UIA patterns when the provider supports the required operation | Fresh control state and relevant application result |
| Canvases, games and visual layout | Fresh scoped image plus a qualified grounding model | Target identity, observed result and visual checks |

This is a proposed selection policy. The existence of an API does not establish that it covers a specific task or that a particular implementation is faster. Measure actual results, and retain visual inspection when appearance is part of the user's objective. Vendor documentation supports narrower integrations where suitable. [A01](https://learn.chatgpt.com/docs/computer-use) [A02](https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork) [A04](https://developers.openai.com/api/docs/guides/tools-computer-use) [D01](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview) [D10](https://playwright.dev/docs/locators) [D11](https://playwright.dev/docs/actionability) [D12](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context) [D13](https://create.roblox.com/docs/studio/mcp) [D14](https://create.roblox.com/docs/reference/engine/classes/StudioTestService) [D15](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_operators.rst)

### Give the local controller the time-critical work

For the user's multi-machine architecture, keep input ownership, observation freshness, stop handling and short execution receipts near the interactive desktop. Planning, retrieval, code analysis, rendering jobs and independent verification can run elsewhere when resources permit. Avoid sending a screenshot to a large model for every predictable keystroke.

One interactive Windows session shares foreground focus and pointer state. Multiple agents can prepare plans in parallel, but simultaneous pointer/keyboard streams need separate isolated sessions or a common owner. Multiple Studio instances can be addressed through instance-scoped APIs without assuming they have independent physical keyboards. [A01](https://learn.chatgpt.com/docs/computer-use) [D05](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow) [D08](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput) [D13](https://create.roblox.com/docs/studio/mcp)

A future operation record should contain the task, machine/session, target process/window/document, observation identity, expected effect, dispatch state and verification result. Operation IDs help correlate work, but exactly-once effects require executor/application support or reconciliation. A unique ID by itself does not prevent a duplicated edit.

### Make routine work autonomous within its existing scope

Store task authorization in the controller and apply it to each operation. Repeatedly asking the same permission for an already authorized local task adds delay without clarifying the work. At the same time, text inside a webpage, screenshot or document does not grant a new capability. Keep the existing machine enrollment, STOP, privacy, risk and resource boundaries intact. The patch does not change those policies or install a new remote-control service. [A13](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks) [R01](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py) [R06](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/hands.py) [R07](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/winapi.py) [R08](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py) [R09](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/settings.py) [R11](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/__init__.py) [R13](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/identity.py) [R14](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/stopswitch.py)

## 3. Where the speed is actually lost

The latency path includes observation, model inference, network transport, action dispatch, application work, settling, verification and recovery. Some work can overlap, so instrument the critical path as well as individual spans. Record queue time separately from active work.

The revised OSWorld-Human research identifies planning/reflection/judging calls as major latency contributors in its experiments. This supports testing fewer unnecessary decisions, but it does not establish the same bottleneck or speed multiplier on Litha's hardware. [E05](https://arxiv.org/abs/2506.16042v2) [E06](https://github.com/WukLab/osworld-human)

### Practical experiments

1. **Qualified procedures:** execute a previously validated application operation when its version and preconditions match. Ask a planner again when state diverges.
2. **Short batches:** combine actions whose dependencies are known. Stop and observe after navigation, modal appearance, unexpected focus change or error. Anthropic's current desktop batch contract requires ordered execution and skipped results after failure. [A06](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
3. **Scoped observations:** request the relevant application subtree or image region, while retaining enough surrounding state to detect the wrong window or a blocking dialog.
4. **Selective verification waits:** compare readiness polling with the current fixed wait; count extra observations as a cost.
5. **Resource admission:** keep capture and input responsive while expensive local models, games, voice or rendering compete for CPU, RAM and VRAM. A model fitting by weight size alone does not prove that it can coexist with these workloads.
6. **Prefix and session reuse:** reuse stable instructions and qualified references where the actual inference engine supports it. Separate API cache accounting from local KV reuse.

Human-like motion timing can remain useful for visible drawing or expressive interactions. Exact editor operations can use an application interface where qualified. This is a task-specific design choice, not a proposal to remove input ownership or rate limits.

### Where Rust belongs

Rust is a candidate for a small local host boundary when profiling identifies allocation, serialization, capture conversion, event dispatch or cross-process communication as a bottleneck. Keep application-specific procedures and experimental policies easy to inspect. A language rewrite cannot remove a slow model round trip or an application's own export time. The current patch adds no compiled dependency and does not claim a Rust speed improvement.

## 4. A concrete improvement implemented in this work

### Recovery fixes

The original driver checked for alternative targets before honoring its changed-state guard. In reproduced cases, a click or key action that had already changed the application was dispatched four times even though the intended postcondition remained unsatisfied. Typing could also repeat after partial text had been entered; the screen signature does not include all value changes, so an unchanged signature did not establish that typing had no effect. [R01](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py) [R03](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/screen.py)

The patch moves these decisions ahead of alternative retries. Unverified typing is one-shot. Changed click/double/right/key actions return an uncertain outcome. Ordinary backend exceptions after dispatch also return an explicit uncertain result rather than entering the pre-dispatch retry path. Missing-target and suitable pre-dispatch failures can still retry.

The result and action log expose `outcome_uncertain`. Recovery must inspect current application state before a future attempt. Backend exception receipts retain the exception class without echoing arbitrary request/response bodies. Post-dispatch observation or verification failures receive the same uncertain classification.

STOP checks cover waits and the boundaries after initial observation, after grounding, after verification and after logging before recovery focus. Nonfinite wait configuration is rejected. These checks do not cancel an already blocked native API call.

### Optional positive-postcondition polling

`verification_poll_s` defaults to `0.0`. When explicitly set to a finite value from `0.01` to `1.0`, the driver may observe during the existing settling budget and return when a new positive predicate is satisfied. A suggested experimental interval is `0.05`, subject to native measurement.

Early polling applies only when the declared positive predicate was false before dispatch. Negative predicates, mixed positive/negative predicates, generic visual-change checks and already-satisfied expectations retain the fixed wait. Each wait phase makes at most 32 observations. The existing additional phase for an observed change can still run.

This is a configurable optimization for `Driver.run`. It does not rewrite `Computer.act`, implement UIA event subscriptions, replace the grounding model, or create a native desktop acceptance result. Predicate quality still matters: a matching word is weaker evidence than an authoritative saved-document or data-model check.

## 5. What the executed evidence establishes

The final candidate passed 43 independent unittest methods and targeted compilation. Four selected baseline regression methods produced six expected failures including pointer subcases, with no fixture errors. The validation record contains the actual commands, code hashes, test counts, baseline failures and timing-experiment output. The independent developer suite uses safe fake input, synthetic enrollment and simulated time. The baseline reproduction executes an inspected original module and demonstrates the replay defects; it does not edit protected evaluation fixtures.

The timing experiment compares 33 pairs of cases through the actual driver: 11 readiness/predicate scenarios at hypothetical observation costs of 0, 20 and 100 milliseconds. All paired outcomes and side effects matched. Those observation costs are assumptions, not measurements of Windows UIA or the user's PC.

With zero-cost observations, a result appearing at 70 ms was observed at 100 ms with polling versus the fixed 500 ms wait. A result appearing at 750 ms completed at 750 ms versus 2,500 ms across the fixed extended-wait path. A never-ready case saved no simulated time and required 45 observations instead of three. That tradeoff is why the feature remains disabled pending native profiling.

Native input delivery, Windows packaged acceptance, real app focus, multi-monitor coordinates, Roblox/Blender execution, model quality and target-machine performance were not tested. The full repository test suite was not run from this focused source snapshot; pytest and full application dependencies were unavailable. No claim of deployed speed or frontier-model superiority follows from these offline results.

## 6. How Litha can learn computer work faster

Agent S4 is especially relevant to Litha's self-owned Forge direction: its authors study evolving application interfaces and usage knowledge from task experience, with held-out validation. The useful idea is to improve the tools an agent can call, not only the prompt that asks it to click. The reported benchmark results belong to that experiment. [E16](https://arxiv.org/abs/2610.28601) [E17](https://github.com/simular-ai/Agent-S/blob/main/agent_s4/README.md)

A proposed Litha learning cycle is:

1. Record a development task with observations, actions, failures, final state and elapsed time.
2. Identify repeated work or a fragile interaction.
3. Propose a small typed operation or procedure with explicit preconditions.
4. Test in a disposable fixture, including incorrect-window and partial-success cases.
5. Evaluate on held-out variants the authoring agent cannot edit.
6. Promote only when quality is preserved and the complete-task benefit is measured.
7. Retain the previous version, rollback point and evidence.

Useful lessons include both the intended path and the condition that invalidates it. A browser selector can become stale after navigation; an exporter can change behavior with an application version; a saved-state label can refer to the wrong document. A successful demonstration alone does not establish broad generalization.

Keep benchmark solutions out of training and retrieval. In particular, OSWorld-Human explicitly restricts using its evaluation-solution trajectories for training. Use independent development tasks to construct Litha's procedural memory. [E06](https://github.com/WukLab/osworld-human)

## 7. Native acceptance plan

The separate plan lists 30 proposed cases, each marked not run. Start with local reversible fixtures: edit/save/reopen a scratch document; set and read back a field; open an application and verify the exact window; interrupt a delayed action; switch focus mid-operation; repeat at different display scales; reconnect after an uncertain dispatch.

For Studio, extend the current connector's capability checks and explicitly select an owned test instance. Verify data-model changes, run a representative playtest, inspect console output, and capture relevant viewpoints. For Blender, process a small asset, save it, reopen it and verify an exported round trip. For web tasks, use a dedicated test profile and application state assertions. [D10](https://playwright.dev/docs/locators) [D11](https://playwright.dev/docs/actionability) [D12](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context) [D13](https://create.roblox.com/docs/studio/mcp) [D14](https://create.roblox.com/docs/reference/engine/classes/StudioTestService) [D15](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_operators.rst) [D16](https://docs.blender.org/manual/en/5.4/advanced/command_line/arguments.html) [D17](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_threading.rst) [R08](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py)

Record full success, partial progress, false success, unintended effects, cold/warm median and p95 latency, model/tool calls, observation count, memory pressure and recovery time. Promote improvements only when the result remains correct on the same task distribution. GitHub remains a review/export surface; Litha's internal Forge can own the development loop and rollback history.

## Reading the detailed chapters

Chapter A explains current OpenAI and Anthropic contracts. Chapter B examines Windows, browser and native application routes. Chapter C reviews benchmark validity and evaluation design. The implementation guide specifies the proposed code change, and the source appendix maps every citation identifier to its primary source. Proposed cases and simulated results are kept separate from executed offline checks throughout.

# Chapter A - Current computer-use integration contracts

Research date: October 31, 2026 (America/Chicago). This chapter distinguishes current documented behavior from proposed Litha engineering. It does not establish a measured performance ranking, account entitlement, or successful native-desktop integration. Documentation was opened and inspected; examples were not executed against a user's computer.

## 1. Main decision

Give Litha an application-owned controller that chooses the narrowest adequate interface, executes a short plan, checks the resulting state, and preserves enough evidence to recover. Use direct application APIs for well-defined changes, page-aware browser operations for websites, accessibility interfaces for supported desktop controls, and screenshot-driven pointer actions for genuinely visual or otherwise inaccessible work. The practical optimization target is time to a verified result, including failed attempts and recovery.

This hierarchy is supported by both vendors' current guidance. OpenAI recommends a dedicated plugin or MCP integration for repeatable data operations and visual computer use where visual interaction is needed. Anthropic's product documentation likewise describes connectors, then browser interaction, then direct screen interaction. Neither source establishes a universal speed ratio for Litha's tasks. [A01](https://learn.chatgpt.com/docs/computer-use) [A02](https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork)

## 2. Separate product capability from the integration contract

| Surface | What the documentation establishes | Consequence for Litha |
|---|---|---|
| ChatGPT desktop Computer Use | Local graphical interaction on supported macOS and Windows installations; Windows operates on the active desktop. | A local desktop controller must account for focus and foreground ownership. |
| OpenAI Responses computer use | The application executes structured actions or supplies a code-execution runtime and returns observations. | Litha can retain its own execution, state, verification, and recovery layers. |
| OpenAI Agents API computer use | An OpenAI-hosted browser with a session/event lifecycle. | A hosted browser is a separate environment from Litha's Windows machine. |
| Claude desktop computer use | Current product documentation describes macOS/Windows screen interaction through the desktop app. | Product enablement is distinct from integrating Claude's API into Litha. |
| Claude Messages computer/browser toolsets | Anthropic defines the client-tool contract; the application runs the calls. | Litha still needs drivers, observation handling, input validation, and outcome checks. |

Sources: [A01](https://learn.chatgpt.com/docs/computer-use) [A02](https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork) [A03](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile) [A04](https://developers.openai.com/api/docs/guides/tools-computer-use) [A05](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use) [A06](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool). Availability is evolving. Documentation for Claude Cowork's cloud execution also distinguishes work that can continue remotely from local-file, browser, and computer access that depends on the desktop app remaining available. The existence of a cloud session does not make the local PC remotely available after it disconnects. [A03](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile)

For the owner's Brain 1/Brain 2 setup, a proposed design is to run the controller near the active desktop on Brain 2 and let Brain 1 perform planning, retrieval, and non-UI verification. The control protocol should identify the machine, user session, desktop, process, and target window. This is an architecture recommendation, not a verified property of the current Litha deployment.

## 3. Current contracts contain consequential changes

The inspected OpenAI guidance supports code execution and a structured `computer` action interface. An action call's generated `completed` status is not proof that the runtime executed it. The application executes permitted actions, returns an updated screenshot with the matching call ID, and checks the application result. Conversation continuation and browser/desktop persistence are separate responsibilities. [A04](https://developers.openai.com/api/docs/guides/tools-computer-use)

Anthropic's current computer entry is `computer_toolset_20260801`. Its member calls carry `toolset_name: computer`. The application must process every call in order, stop execution after the first failure, and return a result for each call, including skipped calls. It must not run these batches concurrently merely because their response shape resembles parallel tool use. Old display-dimension parameters from `computer_20251124` are rejected by the new entry. [A06](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)

The corresponding browser toolset offers page text, element references, and tab state as well as coordinates. It can attach an observation to an action result, avoiding a separate observation request when the contract allows it. Tab-management results have a specific `browser_state` shape. [A07](https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-tool)

Litha should isolate these versioned provider adapters from its internal actions. A stable internal `click_target`, `set_field`, or `read_window` operation should not silently change behavior because a vendor renames a field. Adapter conformance checks should cover all supported methods, result shapes, unsupported members, and provider-specific batching rules.

## 4. Why a faster loop needs fewer unnecessary decisions

A useful engineering decomposition is:

`task time = observation + model inference + communication + execution + UI settling + verification + recovery`

Measure those terms separately. If a known export takes eight seconds in the application, shaving a few milliseconds off pointer dispatch will have little effect. If ten short actions each demand a full model round trip, bounded batching may remove substantial orchestration overhead. If most time is spent retrying wrong-window input, better target validation can improve both speed and quality.

OpenAI's latency guidance recommends reducing unnecessary requests, parallelizing independent work, avoiding an LLM when ordinary code suffices, and measuring tradeoffs on actual workloads. Its illustrative percentages should not be applied as a promised Litha speedup. [A08](https://developers.openai.com/api/docs/guides/latency-optimization)

Proposed policy:

1. Execute an already-qualified deterministic recipe when its exact preconditions hold.
2. Use a short model-generated batch when the next few actions have clear dependencies and observable postconditions.
3. Request another observation after navigation, modal appearance, focus changes, errors, or ambiguous state.
4. Escalate to a stronger planner only when uncertainty or failure warrants it.
5. Keep planning and read-only analysis parallel where independent, while giving one writer ownership of an interactive desktop.

The last rule is especially important for multiple Studio instances. Separate processes are not necessarily independent input surfaces: keyboard focus and the pointer can still be shared. Parallel work should target separate sessions or use explicit application APIs; foreground GUI action streams should be serialized per desktop.

## 5. Observations need identity and coordinate provenance

Treat a screenshot as a versioned observation, not just image bytes. A proposed record includes session and window identifiers, capture sequence, monotonic capture time, source rectangle, source display dimensions, returned image dimensions, DPI context, and any coordinate transform. Record the foreground window separately from the window being inspected.

For a screenshot produced by cropping a physical display rectangle and then resizing it, the conceptual mapping is:

`display_x = crop_left + model_x * crop_width / image_width`

`display_y = crop_top + model_y * crop_height / image_height`

Validate the original point before mapping. An out-of-range request should produce a useful error; clamping can turn an invalid request into a click on a different control. Test rounding at edges and reject transforms that no longer match the current display configuration.

OpenAI's driver guidance explicitly distinguishes screenshot/display coordinates and cropped-image offsets from browser CSS pixels. Its computer helper executes actions in order, captures the final screenshot, and does not retry driver actions automatically. [A09](https://developers.openai.com/api/docs/guides/tools-computer-use-sdk-drivers)

Anthropic's zoom contract differs from a generic crop contract: coordinates after a zoom remain in the full screenshot's coordinate space. Its SDK leaves coordinate conversion and image resizing to the driver, and unsupported or invalid inputs need explicit errors. Apply a provider-specific transform once; applying a crop offset to full-frame coordinates would be incorrect. [A10](https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-sdk)

For Litha, observation freshness should be a state question as well as a time question. A screenshot can be recent while the relevant control has already moved. Invalidate a pending action when the target window changes, a display changes scale, the user intervenes, a modal appears, or a prior action changed the layout. Reacquire an element reference after navigation instead of reusing an old reference by name alone.

## 6. Batching must preserve dependency and outcome information

A practical batch is short and local: focus an observed text field, replace its value, and check the value. A long script that assumes many unseen screens will look the same accumulates failure risk.

A proposed internal receipt should distinguish:

| Outcome | Meaning | Recovery |
|---|---|---|
| Completed and observed | Action executed and an explicit postcondition was seen | Continue from the new observation |
| Refused before dispatch | No action was sent | Correct the request or permissions |
| Failed with known no effect | Driver established that the intended effect did not occur | Replan or retry only within its contract |
| Unknown effect | Connection, cancellation, or timeout left execution uncertain | Reconcile authoritative state before retrying |
| Skipped dependency | An earlier prerequisite failed | Obtain a fresh plan |

A timeout is not proof that an action did nothing. Retrying a toggle can reverse the successful first change; retrying an append can duplicate text. Use idempotent operations where the application exposes them, and otherwise read the actual state before deciding what to do.

The OpenAI hosted-browser documentation explicitly instructs clients to recover the existing session after disconnection instead of automatically resending the task. An acknowledgment lost in transit must be treated as uncertain until current session state is retrieved. [A05](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use)

For Litha's local controller, keep an operation ID and a durable record of dispatch, acknowledgment, and verification. An operation ID alone does not create exactly-once semantics; the remote executor and target application must support deduplication or reconciliation. Never infer an application's saved state solely from an input driver's success return.

## 7. Screenshots, context, and caches

Use the smallest observation that still resolves the decision. A structured field value can answer whether a checkbox is enabled; a screenshot is needed for appearance, overlapping controls, or a rendered 3D scene. Preserve a full-frame reference for orientation and request a crop when small text needs inspection.

OpenAI's integration recipes recommend original image detail for computer-use screenshots and describe explicit resizing when model limits require it. They stress mapping coordinates back after scaling. Image limits and costs depend on the chosen model; a single fixed resolution should be evaluated on the target applications rather than assumed best. [A11](https://developers.openai.com/api/docs/guides/tools-computer-use-integration)

Do not append every screenshot forever. Keep recent observations, essential action/result relationships, current goals, unresolved uncertainties, and a compact ledger of verified state. Older images can be retained outside the active model context with references for audit or recovery. Dropping history must not sever the association between a tool call and its result.

For API prompt caching, stable tool definitions and instructions belong before changing state. Anthropic documents that cache breakpoints inside a batch take effect at the batch's end, and that several configuration changes can invalidate cached prefixes. Cache use should be measured, not presumed from repeated wording. [A12](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching)

Local KV reuse is a separate mechanism with its own engine and memory behavior. Litha should report API cache hits, local prefix reuse, screenshot bytes, and image-processing time separately. Their benefits cannot be added as if they were independent guaranteed speed multipliers.

## 8. Permission decisions belong outside screen content

Routine authorized work should execute without repeated prompts. The controller still needs a durable distinction between the user's granted task and text encountered inside an app. A web page saying to ignore previous instructions is evidence about that page, not a new grant to control another application.

Anthropic's prompt-injection guidance recommends preserving third-party material as identifiable tool results, identifying its provenance, and limiting accessible data and actions. Structured wrapping improves delimitation but cannot prove that an instruction is trustworthy. [A13](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks)

For Litha, keep app and operation scopes in an execution policy that page text cannot edit. Preserve existing authorization for routine reversible work; require the established owner approval only where an action is outside that scope or materially consequential. The proposed speed benefit is fewer unnecessary interruptions together with fewer accidental actions, not removal of execution checks.

Keep credentials in a dedicated authentication path instead of natural-language prompts or screenshot logs. Use task-scoped handles when the runtime needs a protected value. Logs should retain enough structure to diagnose an operation while omitting sensitive typed text and raw screen contents where unnecessary.

Also make interruption concrete. A user takeover should cancel queued mutations, release held mouse buttons and modifiers, mark uncertain effects, and require a fresh observation before resuming. Cancellation of the local waiting process does not by itself prove the remote application stopped.

## 9. Proposed acceptance cases

These are proposed cases, not reported passes:

1. A target window moves between observation and dispatch: action is refused or refreshed.
2. A second application steals focus: typing does not enter the wrong window.
3. A resized/cropped screenshot maps center and edge points correctly.
4. Anthropic zoom preserves full-screenshot coordinates.
5. A DPI or monitor change invalidates the old transform.
6. A stale browser reference produces a fresh read and replan.
7. The first batch action fails: later actions are skipped and all calls receive results.
8. An effect occurs but the acknowledgment is lost: reconciliation prevents duplicate execution.
9. A disabled or unsupported action is rejected before dispatch.
10. A user takeover clears queued input and releases held modifiers.
11. An apparent save is checked against the resulting file or document state.
12. A malicious instruction on screen cannot expand the granted application scope.
13. Long runs retain sufficient call/result history while bounding image context.
14. A known recipe is tested on a changed application version before reuse.
15. Two workers contend for one desktop: only the lease holder mutates it.
16. A weak visual signal triggers escalation instead of a confident wrong click.

Compare a baseline and each proposed optimization on held-out tasks: completion rate, false success rate, unauthorized-effect rate, recovery rate, p50/p95 time, model turns, image tokens/bytes, peak memory, and total cost per verified task. Include ordinary text entry, a modal dialog, a file export, a browser form, and native Studio/Blender workflows. Screen dimensions, app versions, model versions, warm/cold state, and network conditions must be recorded.

## 10. Recommended next integration slice

Beyond the focused existing-driver recovery patch in this report, the most reusable integration improvement is a provider-neutral action executor with explicit observation provenance, ordered receipts, stop-on-failure behavior, and reconciliation for unknown outcomes. Extend the existing driver and receipt contracts behind the current feature policy. Exercise changes with offline scripted drivers, then complete native acceptance before promotion. Then capture actual task traces to determine whether observation, inference, application waiting, or recovery dominates the delay.

The evidence supports these architecture choices. It does not establish that Litha already exceeds ChatGPT or Claude, that a particular local model will fit a given workload, or that a fixed speed multiplier is achievable. A stronger claim should follow reproducible performance on the owner's actual tasks.

# Chapter B - Windows, browsers and application control

Research snapshot: October 31, 2026, America/Chicago. This chapter reports primary-source documentation and repository inspection. Architecture and acceptance recommendations are proposals; no live Windows, Roblox Studio, Blender, browser-control, or hardware speed benchmark was run for this chapter.

## 1. Main recommendation: route each operation through its strongest available interface

Litha's existing task controller should route operations through specialized execution adapters. Choose an interface from the task's requirements and the actual capabilities of the target application. Preserve screenshots for visual inspection, unfamiliar interfaces, and operations that truly require pointer interaction. Prefer an application's structured interface when it expresses the intended operation and exposes useful completion evidence.

The inspected base, `a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f`, already contains substantial foundations: `ComtypesUia.snapshot()` calls `FindAllBuildCache` and reads cached properties; `ScreenEye` reuses bounded latest-frame capture; `GroundingChain` starts with UIA and can fall back to configured local or remote vision; `Driver.run()` performs observations, verification and retries. [D21](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py) [D22](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py) [D23](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py) [D24](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py) These mechanisms should be extended and measured, rather than rebuilt as supposedly new capabilities. The driver currently sleeps according to `settle_s` and attempt number before observing; outcome-specific waits are a concrete candidate to evaluate. Existing verification must be preserved when reducing those waits.

| Execution route | Suitable work | Evidence to collect |
|---|---|---|
| Application API, plugin, CLI or MCP | Scene changes, file export, scripts, structured data edits | Object identifiers, returned values, logs, output artifacts and application state |
| Browser DOM with Playwright | Web forms, navigation, tables, web application checks | Resolved locator, field values, URL, download or application response |
| Windows UI Automation | Native accessible controls and standard dialogs | Control identity, supported pattern, state and resulting value |
| Visual grounding plus input | Canvas tools, custom controls, unsupported surfaces | Screenshot identity, coordinate transform, focus and a fresh visual result |

This is a routing policy, not a universal speed ranking. An API that changes hidden state without producing the intended user-visible result still needs verification. An accessibility tree can be incomplete. A browser locator can match several elements. A screenshot target can become stale before the action executes. Each adapter must report its limitations explicitly.

## 2. Windows UI Automation: reduce cross-process work and keep observations fresh

Microsoft UI Automation (UIA) exposes control functionality through patterns such as Invoke and Scroll; a control can support several patterns, and support can change with its state. A client should discover the pattern it needs and invoke that supported behavior. It should not assume that every button-shaped region provides the same interface. [D01](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview)

UIA property access is a significant architectural opportunity: fetching individual properties can require separate cross-process calls. Microsoft's caching mechanism can fetch a selected set of properties and patterns together. Its cache is a snapshot, and refreshing an element's cache does not update old references already retained by the client. A cached-only element reference also cannot invoke control methods. [D02](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients)

Litha already caches its selected properties. The next question is whether the retrieved subtree, observation frequency and payload are appropriately bounded for each task. Keep live execution references inside any future pattern-action adapter; the existing cached-only observation references are appropriate for reading but do not provide an invocation path. Send compact serializable observations to the planner, and measure provider traversal separately from the later output cap. Avoid repeatedly dumping the whole desktop tree.

Scoped UIA event subscriptions can reduce polling, but Microsoft explicitly warns that providers do not raise every possible event. The proposed observation system should combine relevant structure, focus and property events with bounded fallback refreshes. Debounce bursts without hiding a completion event, and force a fresh observation when the next action's preconditions cannot be established from the current snapshot. [D03](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-eventsforclients)

Microsoft recommends a separate COM multithreaded-apartment thread for clients that can interact with their own UI, with no windows owned by that thread. It also warns against multiple threads concurrently adding/removing event handlers. [D04](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading) A dedicated, supervised UIA worker is therefore a better starting design than calling UIA opportunistically from arbitrary frontend or server threads. Adapter requests need deadlines and cancellation; a hung provider must not freeze Litha's main interface.

## 3. Native input: model focus and coordinate systems explicitly

Windows does not guarantee that an arbitrary process can seize foreground focus. `SetForegroundWindow` has restrictions and can fail even when documented conditions appear satisfied. Its return value and the subsequently observed foreground window matter. [D05](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow) Litha should treat an unsuccessful focus request as a distinct outcome, not proceed to type into whichever window currently owns input.

`SendInput` returns how many events were inserted. It is subject to User Interface Privilege Isolation: input can be injected only into applications at the same or a lower integrity level, and the failure diagnostics do not specifically identify UIPI blocking. Existing pressed keys can also alter synthesized input. [D06](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) The controller should distinguish insertion from application completion, record partial insertion, and release its own held keys/buttons on cancellation. An elevated application or secure desktop is a capability boundary, not a reason to weaken Windows protections.

UIA bounds use physical screen coordinates, while DPI virtualization can produce other coordinate spaces in applications and cursor APIs. [D07](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-screenscaling) Windows absolute mouse input uses a normalized coordinate range; `MOUSEEVENTF_VIRTUALDESK` changes the target from the primary display to the whole virtual desktop. [D08](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput) For every screenshot retain its physical capture rectangle, monitor geometry, crop rectangle, resizing scale, rotation, and coordinate convention. Map model output back through that transform exactly once. A cropped image's `(0,0)` is not necessarily the desktop origin.

Proposed regression cases include a monitor left of the primary display, mixed 100%/150% scaling, rotated displays, window movement after capture, resize during an action, and monitor removal. Reject targets outside the observed image or current intended surface. Re-observe after topology or focus changes. A check immediately before input narrows a race window; it does not make all OS focus changes atomic with the input call.

## 4. Screen capture: exploit changes without assuming they prove task completion

Windows Desktop Duplication provides desktop frames in DXGI surfaces together with dirty and move rectangles. Correct reconstruction processes move regions before dirty regions; capture orientation and cursor composition also require care. [D09](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api) These facilities offer a basis for reducing pixel copying and redundant perception, but they do not establish that every model request can consume partial frame updates.

For Litha, keep capture and image encoding outside the planning loop's critical section where possible. Reuse buffers; store a small full-window view and request a higher-resolution crop only when targeting or reading requires it. Preserve original capture metadata and avoid ambiguous, independently resized fragments. Trigger model observation at meaningful state transitions rather than sending a continuous high-frame-rate video stream for ordinary dialog work.

A stable image hash is evidence about pixels only. An export could still be running without visible change; a download can finish while the page looks identical. Prefer file completion, application status, a DOM assertion or a tested UIA property when it represents the intended outcome. Use visual evidence to answer visual questions.

## 5. Browser control: use resilient locators and outcome-specific waits

Playwright recommends locators grounded in user-facing semantics, such as role and accessible name, or explicit test identifiers. Long CSS/XPath chains tied to implementation structure tend to be fragile. Locators resolve elements as actions occur, which is more suitable for changing pages than retaining an old element handle. [D10](https://playwright.dev/docs/locators)

Playwright's actionability checks wait for the conditions relevant to an action. A click, for example, requires a unique target that is visible, stable, enabled and able to receive events. Different actions have different checks; forcibly bypassing them changes the reliability contract. [D11](https://playwright.dev/docs/actionability) These checks establish action readiness, not the success of the user's business operation. After an upload, verify the resulting asset; after a save, verify the persisted value or application acknowledgment.

Keep a browser worker warm to avoid relaunching it for every action. Maintain a page handle and bounded relevant DOM observations, then use explicit outcome waits. Fixed sleeps should not be the normal completion test. In a test environment, preserve traces on failures so Litha can distinguish a wrong locator from a network failure or application bug.

Persistent browser contexts require profile ownership. Playwright states that several browser instances cannot use the same user-data directory, and that automating Chrome's default everyday profile through this launch mechanism is unsupported under recent Chrome policy changes. [D12](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context) Use a separate automation profile where that mechanism is selected, with an explicit session owner. Do not copy or silently repurpose the user's browser profile. Parallel browser tasks can use separate contexts when their data and account state are independent.

## 6. Roblox: the official Studio MCP route is unusually relevant

The current official Studio documentation describes a built-in MCP server using local stdio transport. It exposes script inspection/editing, data-model queries, Luau execution in specified Edit/Client/Server contexts, playtesting, output logs, viewport capture and player input. It supports multiple Studio instances through `list_roblox_studios`; every tool call carries an explicit `studio_id`. The server must be enabled in Studio. [D13](https://create.roblox.com/docs/studio/mcp)

Litha already has an official Studio MCP connector in `star/studio.py`, including bounded discovery and explicit instance selection. Extend and qualify that connector against the actual installed build. [R08](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py) At connection time, discover the actual tool schemas and Studio instances. Bind each task to a verified instance and place identity, and fail clearly if that instance disappears. Keep mutations for one place serialized even when independent scene analysis or code review runs in parallel. A similarly named second Studio window should never inherit the first task's writes.

An efficient proposed workflow is: inspect a narrow hierarchy, read relevant scripts, submit one coherent edit, run a bounded test, inspect output, and capture the relevant viewport. Use GUI control when the operation requires it or the structured route is unavailable. Measure both routes on the same task before declaring one faster. Native calls still need validation: a successful request is not evidence that a scene has correct proportions, a button is readable, or a game is enjoyable.

`StudioTestService` exposes plugin-security methods for Play, Run and multiplayer tests, plus test arguments and completion values. [D14](https://create.roblox.com/docs/reference/engine/classes/StudioTestService) This is useful for reusable lobby, join/leave and interaction exercises. Keep native test lifecycle and returned results distinct from a generic request to click Play. Confirm support on the installed Studio build; the documentation is not evidence that a particular user machine already has the server enabled or this integration working.

## 7. Blender: batch meaningful data operations and verify artifacts

Blender's Python operators rely on context such as the active object, editor or selection; their polling can fail even when a data-level API approach is possible. [D15](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_operators.rst) Prefer direct data operations when they express the task, and use operators with explicit, validated context when needed. Repeating a context-failing operator with longer delays does not solve the underlying issue.

The command-line interface supports background operation and Python scripts. `--python-exit-code` can make an uncaught command-line Python exception produce a nonzero exit code. [D16](https://docs.blender.org/manual/en/5.4/advanced/command_line/arguments.html) A Litha batch job should also produce a structured result manifest and validate the expected `.blend`, image or export output. An empty output or a script that catches and hides its own exception can still defeat a simplistic exit-code-only check. Use arguments supported by the installed version and explicit paths rather than interpolated shell fragments.

Blender documents that its Python integration is not thread safe and that long-lived background Python threads can cause crashes. It recommends independent processes for independent work. [D17](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_threading.rst) For Litha, keep network and model inference outside Blender's mutation context. Use a bounded job queue processed through an appropriate Blender execution path, or separate background Blender processes with resource admission. Do not let several model workers mutate one open scene concurrently.

After saving or exporting, verify data and rendered results separately: object count and identifiers, transforms, material assignments, skeleton structure, expected artifact size, and a representative visual capture. A fast artifact operation still requires enough evidence to catch wrong selection, wrong output path or a missing material.

## 8. Open-source systems to study, without inheriting their claims

Microsoft UFO's inspected main snapshot is `eae3c0a8d168c47cb10df0652e293e092eda1078`, dated October 14, 2026. The repository describes hybrid Windows UIA/Win32/COM and application-API execution, speculative multi-action planning, and device coordination. Its headline of 51% fewer model calls is an author-reported result in its own setting, not a measured Litha latency improvement. [D18](https://github.com/microsoft/UFO/tree/eae3c0a8d168c47cb10df0652e293e092eda1078) [D19](https://github.com/microsoft/UFO/blob/eae3c0a8d168c47cb10df0652e293e092eda1078/documents/docs/ufo2/core_features/hybrid_actions.md)

The transferable idea is to dispatch a short, coherent action sequence locally with checks at meaningful boundaries. For example, populate a known dialog, validate field values, then stop before an unverified transition. Each action retains its target and preconditions; a new modal, changed focus or unexpected result invalidates the remainder. Fewer model calls are beneficial only when retries and missed state changes do not erase the savings.

OmniParser's inspected snapshot is `354021201345a96178360b28733573e27269f2de`, dated July 20, 2026. It converts screenshot content into structured target candidates; it is not, by itself, a complete planner, permission system or result verifier. Its README now distinguishes an MIT-based YOLOv9 `icon_detect_v3`, earlier AGPL Ultralytics detectors, and MIT caption models, while the repository license is CC-BY-4.0. [D20](https://github.com/microsoft/OmniParser/tree/354021201345a96178360b28733573e27269f2de) Qualify the exact code, checkpoint and dependencies selected; avoid a blanket license label.

A visual grounding model is a candidate fallback when DOM/UIA or native APIs cannot identify the target. Evaluate precision on small controls, high-DPI screenshots, custom game editors, icon ambiguity and partially obscured windows. Include its loading time and peak memory while Roblox or Blender is already active. No local model speed or memory figure is established by this chapter.

## 9. Proposed controller contract and concurrency model

Each executable operation should identify a task, request, target surface, observation version, action, required preconditions, deadline, retry class, and expected postcondition. The executor returns a receipt containing the action actually attempted, timestamps, outcome, verification evidence and any uncertainty. Target identity should include the browser context/page, native application/window, or Studio instance as appropriate; a human-readable title is insufficient on its own.

Give each interactive desktop one input owner. A short-lived lease allows one task to move its pointer and type, while other tasks can research, inspect files or prepare plans. The user can take control immediately; that revokes the active input lease and cancels queued actions. Separate desktops or machines can have separate owners. Parallel agents should not compete for the same mouse or the same document's mutable state.

Maintain outcomes such as completed, failed-before-dispatch, partially-applied and uncertain. Repeating an idempotent observation or setting a known field value can be appropriate. Repeating a submission after a timeout can duplicate an external effect. Request identifiers help correlation and deduplication, but do not prove exactly-once execution after a process crash. Inspect the resulting state before retrying an uncertain mutation.

For a local Windows helper, a supervised process with bounded typed messages is a reasonable starting architecture. Existing Python orchestration can remain while a Rust or C# helper owns UIA/capture/input where profiling and packaging justify it. Keep provider-specific model behavior outside the native executor. Off-device Brain 1/Brain 2 operation should carry the same session and action identifiers, authenticate its channel, and reject stale responses after reconnects.

## 10. Acceptance work that would establish improvement

Test a small representative task set before expanding scope: standard dialog edits, a dynamic web form, a download, an editor canvas interaction, a Studio script change and test, and a Blender export. Vary display scaling, app state, network delay, focus changes, duplicate window names and worker restarts. Add an injected modal and an uncertain-completion case rather than measuring only the happy path.

Measure end-to-end accepted-task latency and p95, success rate, recovery steps, model calls, screenshot bytes, UIA calls, peak RAM/VRAM, and time spent in acquisition, planning, execution and verification. Compare the same tasks with native/API routing, semantic UI control and visual fallback, using held-out variations. A faster first click is insufficient if the task needs more repairs or finishes with the wrong artifact.

The first integration priority is the existing Litha controller's routing and observation contract, followed by the official Studio route, a reliable browser worker, and a bounded UIA adapter. Screen parsing and more speculative action sequences should be added only where measured failures show that they help. This preserves local operation and allows concrete improvements without claiming universal PC mastery.

# Chapter C - Evaluation and learning from experience

Research date: October 31, 2026 (America/Chicago). This chapter distinguishes reported external results from proposed Litha experiments. No external benchmark, Windows session, or model deployment described in this chapter was executed. The separate offline driver checks and deterministic scheduling simulation reported in Appendix D were executed.

## Executive finding

The useful objective is fast completion of an independently verified task. A fast click, accurate coordinate prediction, short model response, or high score on one benchmark measures only part of that objective. Litha should record whether the requested state exists, whether unintended changes occurred, how long the complete attempt took, and what resources and interventions it required. The evaluation layer must remain separate from the agent that proposes actions and from the system that learns new workflows.

The strongest design opportunity is to replace repeated low-level work with small, tested application interfaces. A second opportunity is to eliminate avoidable planning, screenshot, and recovery cycles. Both require evidence from representative workflows. Neither a model parameter count nor a public leaderboard establishes that a configuration will be fastest on Litha's computer.

## 1. Benchmark evidence, with the versions kept separate

### OSWorld, OSWorld-Verified, and OSWorld 2.x

The original OSWorld project describes 369 desktop/web tasks; eight Google Drive tasks need additional configuration or may be excluded, producing a 361-task variant. Its site announces OSWorld-Verified in July 2025 and OSWorld 2.0 in June 2026. Consequently, a result labeled only "OSWorld" is underspecified. Record task count, release, excluded cases, and allowed actions. [E01](https://osworld-v1.xlang.ai/)

OSWorld 2.0 introduces 108 longer workflows. Its paper reports a median human duration around 1.6 hours and an average of 318 tool calls for one named Claude configuration. The project reports both full completion and partial progress. These are task-distribution and configuration-specific observations, not estimates for Litha or comparisons against the old suite. Long workflows make missed constraints and unfinished verification particularly consequential. [E02](https://arxiv.org/abs/2606.29537v2)

At inspection, the repository recommends `osworld-v2.1`, announced September 16, 2026. It requires matching code, task files, complete assets, public runtime assets, mocked websites, and provider images. Historical instructions remain in the README, including an older recommendation inside the August release announcement. Follow the active version matrix and immutable manifest rather than selecting isolated installation commands. [E03](https://github.com/xlang-ai/OSWorld-V2)

Its release documentation also distinguishes comparable runs from development runs with weakened integrity checks, and requires resolved concrete versions instead of storing `latest`. Litha should apply the same principle to its own tests: save the fixture, evaluator, application, and controller versions with every result. [E04](https://github.com/xlang-ai/OSWorld-V2/blob/main/benchmark_releases/README.md)

### OSWorld-Human: efficiency needs its own evaluation

OSWorld-Human studies timing and reference action trajectories. The revised paper identifies planning, reflection, and judging model calls as major latency contributors, and reports increasing per-step time in longer trajectories. An instructive discrepancy exists: the repository README reports 1.4–2.7 times excess steps, while the May 2026 paper revision reports 2.7–4.3 times. This chapter does not combine them into one universal multiplier. [E05](https://arxiv.org/abs/2506.16042v2) [E06](https://github.com/WukLab/osworld-human)

The repository explicitly says its solution trajectories should not be used for training. Litha can use the evaluation method, while keeping those solutions outside her training, recipe, and retrieval stores. Learn workflows from separately created demonstrations and synthetic development tasks.

### Windows Agent Arena

Windows Agent Arena is relevant because it exercises real Windows applications. Its normal and hard modes differ in whether some task setup is already performed. The repository's roughly half-hour full-suite timing uses many parallel VMs; this describes evaluation throughput, not the speed of one agent controlling one PC. Its historical cost table likewise is not a current operating-cost forecast. [E07](https://github.com/microsoft/WindowsAgentArena)

For Litha, select a small representative Windows subset and add project-specific Studio/Blender workflows. Record whether the application was already open, which dialog or document was initially selected, and whether setup time is inside the measurement. Do not extrapolate a prepared-task result to an unattended cold start.

### BrowserGym, WebArena, VisualWebArena, and WorkArena

BrowserGym provides a shared environment interface over multiple browser benchmarks. It supports research iteration, but does not by itself verify native desktop control or supply a finished production controller. Use its environment/evaluator separation as a design reference. [E08](https://github.com/ServiceNow/BrowserGym)

WebArena provides self-hostable web tasks. VisualWebArena adds tasks in which visual content matters, providing a useful check against an agent that succeeds only when all needed information is present in text. Keep browser-only results separate from desktop results. [E09](https://github.com/web-arena-x/webarena) [E10](https://github.com/web-arena-x/visualwebarena)

WebArena-Verified re-audits tasks and evaluators, replaces some brittle matching and model judging with structured comparison, and supports evaluation from recorded network traces. Its full set and hard subset have different denominators. Offline rescoring of a recorded run does not mean the original application interaction can happen without a live environment. [E11](https://github.com/ServiceNow/webarena-verified)

WorkArena covers atomic and compositional ServiceNow workflows. Current setup uses approved access to gated instance resources. That dependency should be stated; it is not an immediately available, fully offline fixture collection. The useful transferable pattern is composition: evaluate both a form action and a larger workflow that combines retrieval, a decision, and a mutation. [E12](https://github.com/ServiceNow/WorkArena)

AgentLab documents two easy-to-miss measurement problems: jobs can hang, and tasks sharing mutable WebArena state can interfere. Its parallel runner accounts for some task dependencies. Litha's evaluation runner should use bounded jobs and isolated state; parallelism should never allow one case to change another case's starting conditions. [E13](https://github.com/ServiceNow/AgentLab)

## 2. What the open agents actually contribute

### Agent S3 and S4

Agent S3 separates a reasoning model and a grounding model; its example CLI is explicitly a configuration without the multi-rollout selection method used in the scaling research. The scaling paper reports a 72.6% OSWorld result using multiple rollouts and behavior-based selection. That number cannot be assigned to a single CLI run or interpreted as comparable local latency. [E14](https://github.com/simular-ai/Agent-S/blob/main/gui_agents/s3/README.md) [E15](https://arxiv.org/abs/2510.02250v2)

Agent S4, released in October 2026, evolves application/tool interfaces from task experience. Its authors report 21.3% binary completion on OSWorld V2 using Qwen3.8-27B, versus 3.8 times lower performance for that model's fixed-interface baseline. These are the authors' results under their configuration; they do not establish a speedup, hardware fit, or universal advantage for Litha. [E16](https://arxiv.org/abs/2610.28601)

The implementation describes a separate interface repository, bounded edits, tracked dispatches, budget stops, and reevaluation on validation tasks. It keeps a held-out test split distinct. This is closely aligned with Litha's internal Forge goal: improve a small application interface, verify it independently, and retain or roll back the version. [E17](https://github.com/simular-ai/Agent-S/blob/main/agent_s4/README.md)

A useful Litha experiment would compare a generic sequence of screenshot-driven actions against a typed operation such as setting a known Blender property or validating an exported asset. Evaluate the interface on unseen documents, object names, and layouts. Do not let the interface author inspect held-out expected answers or edit the evaluator.

### OpenCUA, UI-TARS, and OmniParser

OpenCUA combines models, demonstration tooling, and offline action evaluation. Its published tables separate live-task success, grounding accuracy, and comparison to recorded actions. Its current instructions specify model-specific loading requirements and a supported vLLM path; generic model-loading assumptions can be wrong. An example labeled single-GPU does not establish compatibility with an 8 GB card. [E18](https://github.com/xlang-ai/OpenCUA)

UI-TARS reports both end-to-end tasks and grounding benchmarks, with explicit action budgets. A score for locating a target in one screenshot answers a different question from completing a stateful task. Preserve that distinction when choosing a small grounding model. [E19](https://github.com/bytedance/UI-TARS)

OmniParser converts screenshots into structured candidate information for downstream agents. It is a perception component, not proof of correct authorization, action execution, recovery, or task completion. Test its incremental value on Litha's ambiguous custom interfaces rather than invoking it for every application that already exposes reliable semantic controls. [E20](https://github.com/microsoft/OmniParser)

## 3. A measurement protocol for Litha

The following protocol is a proposal, not a completed evaluation.

### Record enough to reproduce a run

Each result should identify the task and fixture revision, initial application state, OS/build, display layout, DPI, application versions, controller commit, model and tokenizer revision, quantization/runtime settings, prompt revision, permitted tools, action/time budgets, seed where supported, and evaluator revision. Record cache state and whether the model/application was already loaded. Redact sensitive observations while preserving hashes and reproducible non-sensitive fixtures.

### Measure the whole critical path

Start the end-to-end clock when a task is admitted and stop when independent verification finishes. Record queue delay separately so a faster internal stage cannot hide a slower user experience. Instrument acquisition, accessibility/DOM retrieval, screenshot encoding, model queue and inference, grounding, transport, action execution, application settling, verification, and recovery. Use monotonic timing within each process; do not subtract unsynchronized wall clocks across machines.

Report p50 and p95 with the number of observations and an uncertainty estimate. A handful of runs can support debugging but provides weak evidence about a tail percentile. Keep cold starts, warm runs, and resumed runs separate. Include timeouts and failed attempts in all-task completion and cost reporting; a successful-only latency chart can reward a system that abandons difficult tasks quickly.

### Score observable outcomes

Use three distinct fields: full task completion, partial progress, and policy/side-effect violations. A correct local file plus an unintended second file is a different outcome from a clean success. A textual claim of success is never the sole evaluator. Prefer application state, file contents, document structure, or known local fixture data. Visual review remains necessary for tasks where appearance matters, with clear criteria and a record of disagreement.

Track false success explicitly: how often the agent says the task is complete while independent checks fail. Also measure duplicate mutations, incorrect-target actions, recovery success, human takeovers, retries, model calls, screenshot bytes, peak RAM/VRAM, and total compute/currency per accepted task. These are more informative than counting mouse clicks alone.

### Compare alternatives fairly

Use the same held-out tasks, initial-state seeds, time budget, permitted tools, and verifier for the old and new controllers. Randomize run order to reduce systematic cache or service-load effects. Show a paired task table, aggregate quality, and wall time before declaring an improvement. If speed improves while correctness worsens, report the tradeoff instead of collapsing both into an opaque score.

Keep three separate experiments: action-grounding accuracy, controller behavior with deterministic fake adapters, and end-to-end native application tasks. A pure controller test can prove that an outdated observation is rejected; it cannot prove that Windows actually delivered the requested mouse event to the intended window.

## 4. Failure cases that deserve explicit acceptance tests

The companion `litha-computer-control-acceptance-plan-20261031.json` contains 30 proposed cases. They include the following behaviors:

| Situation | Required behavior | Independent evidence |
|---|---|---|
| A screenshot or semantic tree becomes stale | Acquire fresh state before a dependent action | Observation identity and revision in the action log |
| Window, document, or monitor mapping changes | Reject the previous target binding | Active window/document identity and transform revision |
| User takes over the keyboard or mouse | Yield input ownership and stop queued dependent actions | Lease state and absence of subsequent input injection |
| A mutation times out after possibly committing | Reconcile state before retrying | Local fixture mutation count and resulting state |
| The same button is repeatedly clicked without progress | Stop/replan within a defined retry budget | Bounded action count and explicit failure reason |
| A task is partly completed | Report remaining requirements | Per-requirement evaluator output |
| A cached workflow matches the wrong application version | Invalidate or revalidate the workflow | Version precondition and validation record |
| A page contains instructions to override the user | Treat page text as task data | No unauthorized tool invocation or changed objective |
| A worker hangs or loses its transport | Bound the wait and retain an uncertain outcome | Timeout record and no blind mutation replay |
| A stronger model is unavailable | Use a qualified fallback or report the blocked subtask | Explicit fallback identity and unchanged acceptance criteria |

Most cases can start with fake adapters and local fixtures. DPI, native focus, accessibility events, privilege boundaries, and packaged Windows behavior also require native acceptance. Preserve that distinction in the test record.

## 5. Speed experiments with the best expected return

First, try semantic application operations before screenshot-based interaction where both are authorized and verifiable. A typed property update or structured file edit may collapse many screen interactions into one operation. Verify the changed state at the same semantic level, then inspect appearance when it is part of the objective.

Second, bound the active observation. Retrieve the relevant window, document, subtree, or crop while retaining enough surrounding state to identify it. Measure both token savings and wrong-target failures. A tiny image crop can be cheap while hiding a dialog or application change that invalidates the action.

Third, batch actions only while their preconditions remain valid. A sequence that selects a stable field, replaces its text, and reads it back may be suitable for a bounded local routine. A click that opens a new page creates a new observation boundary. Fixed sleeps should be compared against event or predicate waits with deadlines; neither should produce an unbounded retry loop.

Fourth, use a fast local path for typed, well-understood actions and reserve a stronger planner for ambiguity, recovery, or new applications. Benchmark the routing decision itself. A smaller model that misclassifies uncertainty can increase total completion time despite faster inference.

Fifth, learn versioned workflows from clean demonstrations and successful development runs. Store preconditions, application identities, selectors, expected effects, timeout rules, and recovery behavior. Promotion should require unseen cases, not replay of the demonstration. Litha's Forge can keep the old implementation and exact rollback point.

Finally, use parallelism for independent jobs or isolated environments. Two workers should not compete for the same desktop focus or mutate the same application state. For a single desktop, one input owner with concurrent read-only analysis is a more useful starting design than multiplying mouse-controlling agents.

## Adoption decision

Begin with the offline controller cases and a small native Windows fixture set, then instrument representative Roblox Studio, Blender, browser, and file workflows. Use OSWorld/Windows Agent Arena/BrowserGym to widen coverage after the local measurement loop is reliable. Study Agent S4's interface evolution as an independently gated Forge experiment. Keep benchmark solutions out of the learning store. Every claimed improvement should include the task distribution, correctness result, measured time, resource cost, and exact implementation revision.

# Appendix D - Implementation and executed evidence

This change extends `star.computer.driver.Driver.run`. It prevents several unsafe internal replays and adds a disabled-by-default option to finish waiting after a new positive postcondition is observed. It does not enable computer use, change policy, or establish native Windows performance.

## Recovery behavior

- A click, double-click, right-click or key action that changes the observed state but fails its expected result returns an uncertain result before trying an alternative target.
- An unverified dispatched `type` operation is never automatically replayed by this driver. Text may already have been partially entered even when the screen signature is unchanged.
- Ordinary backend exceptions after dispatch, and post-dispatch observation/verification failures, return `ok=False`, `verified=False` and `outcome_uncertain=True`.
- Backend exception details expose the exception class, not arbitrary exception payload text.
- Pre-dispatch missing-target, supported grounding-error and rate-limit paths retain their retry behavior.
- Owner STOP propagates as `Stopped`, including after observation, grounding, verification and final logging before recovery focus. Driver waits request sleep slices of at most 50 ms and check STOP between slices. Scheduling overruns and blocking native calls prevent a real-time cancellation guarantee.

`outcome_uncertain` is also recorded in the action log. An upstream caller must inspect the actual application state before deciding whether another operation is appropriate. This flag is not a durable exactly-once protocol and does not prevent another planner from issuing a fresh duplicate request.

The remaining no-visible-change click retry path retains its existing behavior. A missing observed change does not prove that a click had no effect. Stronger application-level reconciliation is a future integration requirement.

## Optional configuration

The default in `computer.json` remains:

```json
{
  "settle_s": 0.5,
  "verification_poll_s": 0.0
}
```

For a controlled native experiment, `verification_poll_s` may be set to a finite number from `0.01` to `1.0` seconds. `0.05` is an experimental starting value, not a measured optimum. The constructor can override the setting; an explicit zero disables a configured nonzero interval. `settle_s` must be a finite nonnegative number. Invalid values fail before any driver operation.

Early polling requires a specific positive postcondition that was false before dispatch. Supported positive fields are `text`, `window`, `window_open`, `toggle` and `focused`. The entire declared positive expectation must pass. Any `gone` or `window_closed` field preserves fixed-wait behavior. Generic pixel/tree change and pre-existing positive predicates also keep fixed waits.

Polling uses the current attempt's settling budget. Each phase has at most 32 observations; the final sample is reserved for the deadline. The existing extended verification phase can follow a changed screen. The deadline bounds scheduled waits and does not cancel a slow UIA or capture call. More observations can increase CPU/capture cost, which is why this option requires native evaluation before activation.

## Reproduce the checks

```sh
python benchmarks/verify_computer_driver_recovery.py -v
python benchmarks/measure_computer_verification_waits.py
python -m compileall -q star/computer/driver.py star/computer/settings.py
```

The independent checker exercises the actual driver with safe in-memory fakes, synthetic enrollment and simulated time. The separate experiment compares fixed and polling waits under explicit hypothetical observation costs and records the implementation hash. Neither script invokes Windows input, models, external services or a live user session. Protected repository tests/evaluations are unchanged; these are developer checks rather than acceptance promotion.

To reproduce the original recovery defects, save the inspected base revision of `star/computer/driver.py` outside the package and pass it to the checker's documented `--driver-source` option. That option executes the provided local Python source and is intended only for a source snapshot the developer has inspected.

## Integration limits

The separate `Computer.act` planning loop is unchanged. The existing `Expect` predicates remain declared observations, not proof of the whole user's task. Substring text, generic changed pixels and window titles have weaker evidentiary value than an authoritative application state check. Native focus, DPI, monitor changes, event delivery, cancellation, typed input and packaged Windows behavior require their own acceptance runs.

Research, the 30-case proposed plan, the independent validation record and deterministic simulation output are stored under `docs/research/` with the `litha-computer-control-20261031` prefix.

## Final recorded results

| Evidence | Recorded result | Interpretation |
|---|---|---|
| Independent offline behavior checks | 43 unittest methods passed | Correctness of the targeted paths under controlled fakes |
| Original-driver regression reproduction | 4 methods; 6 expected failures including pointer subcases; zero fixture errors | The original implementation replayed uncertain effects |
| Targeted compilation | Passed for the 2 changed modules and 2 benchmark scripts | Python syntax/import compilation for these files |
| Timing simulation | 33 paired cases, 66 driver executions | Compared scheduling and effects through the actual driver |
| Paired simulation outcomes | All matched | Success, uncertainty, dispatch payload/count, readiness and focus effects |
| Native Windows acceptance | Not run | No measured Windows speed or input-delivery claim |
| Full application test suite | Not run | pytest and complete application dependencies unavailable |
| Deployment | Not performed | Review branch only |

## Simulation: hypothetical zero-cost observations

The following is a deterministic fake-application experiment. Times are simulated and are not measurements of the owner's hardware. The complete JSON also includes hypothetical observation costs of 20 ms and 100 ms.

| Persistent result becomes ready | Fixed wait | Poll every 50 ms | Total observations: fixed to polling |
|---|---|---|---|
| Immediately | 500 ms | 0 ms | 2 to 2 |
| After 70 ms | 500 ms | 100 ms | 2 to 4 |
| After 230 ms | 500 ms | 250 ms | 2 to 7 |
| After 490 ms | 500 ms | 500 ms | 2 to 12 |
| After 750 ms | 2,500 ms | 750 ms | 3 to 19 |
| After 2,100 ms | 2,500 ms | 2,500 ms | 3 to 45 |
| Never | 2,500 ms | 2,500 ms | 3 to 45 |

The existing extended settling phase explains the 2,500 ms fixed cases. Each polling phase is capped at 32 observations; the total includes initial and extended-phase observations. A never-ready case retains an uncertain outcome and one dispatch in both versions. Preexisting positive, negative, mixed positive/negative and generic-change expectations retain fixed-wait behavior.

The experiment assumes that readiness persists once achieved. It does not establish transient-predicate behavior, real screenshot/UIA cost, model latency, native focus, or application throughput. Blocking native calls can outlast a waiting deadline. This observation overhead is a concrete reason to keep polling disabled until native profiling.

## Reproduction and limits

```bash
python benchmarks/verify_computer_driver_recovery.py -v
python benchmarks/measure_computer_verification_waits.py
python -m compileall -q star/computer/driver.py star/computer/settings.py
```

The independent checker accepts an inspected baseline module through `--driver-source` for regression reproduction. No protected evaluation fixture was edited. Review resolved three concrete issues before final validation: arbitrary backend payloads in receipts, nonfinite waits, and STOP arriving during final logging before recovery focus. The committed validation JSON records the exact checked source hashes.

This patch does not create exactly-once execution. Visually unchanged click retries remain possible. An upstream planner must still respect an uncertain result and reconcile state before repeating a mutation. The separate `Computer.act` loop is outside this patch, and some upstream skill wrappers expose textual detail rather than the new structured uncertainty field.

## Proposed native validation

The accompanying acceptance plan contains 30 cases, all explicitly marked not run. Run a small local reversible fixture set before testing representative Studio, Blender and browser tasks. Record complete-task success, false success, unintended effects, cold/warm p50 and p95 time, model turns, observations, peak memory and recovery time. Use the same tasks and verifier for baseline and candidate. A successful offline check does not substitute for packaged Windows acceptance.

# Appendix E - Source register

This register has 71 entries and 67 distinct URLs. Multiple chapters sometimes cite the same source. These are primary documentation, primary implementation, research-paper and inspected-project references, not independent performance replications.

Mutable documentation reflects the research date. Pinned source URLs identify the inspected revision. Version claims and author-reported results should be rechecked before deployment. The companion JSON preserves source-specific limitations.

### A01 - Computer Use product documentation

[https://learn.chatgpt.com/docs/computer-use](https://learn.chatgpt.com/docs/computer-use)

Supports: Local product supports graphical interaction on macOS and Windows where available.; Windows uses the active desktop foreground.; Prefer dedicated integrations for repeatable operations.

Limits: Product documentation; does not establish this account entitlement or speed on Litha tasks.

### A02 - Let Claude use your computer in Cowork

[https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork](https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork)

Supports: Product describes connectors, browser, then screen interaction.; Desktop computer use documented on macOS and Windows.; Direct screen interaction acts on the applications without a desktop sandbox boundary.

Limits: Product beta and account availability change; no measured Litha comparison.

### A03 - Use Claude Cowork on web, desktop, and mobile

[https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile)

Supports: Cloud task execution differs from local access.; Local files, browser, and computer use require the desktop app to remain available.

Limits: Plan lists varied between indexed snapshots; report avoids exact entitlement promises.

### A04 - Responses computer use

[https://developers.openai.com/api/docs/guides/tools-computer-use](https://developers.openai.com/api/docs/guides/tools-computer-use)

Supports: Code execution and structured computer action paths are documented.; API conversation and execution environment state are separate.; A generated call marked completed still requires application execution.

Limits: Examples were inspected, not live-run; model access and supported tools must be checked per project.

### A05 - Agents API hosted computer use

[https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use)

Supports: Hosted browser has a session/event lifecycle.; Recover the existing session after disconnection before retrying a task.; Unknown acknowledgment requires reconciliation of current session state.

Limits: Hosted browser is distinct from controlling the owner Windows desktop.

### A06 - Computer use tool

[https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)

Supports: Current entry computer_toolset_20260801.; Ordered member calls carry toolset_name computer.; Stop at first failure and return results for every member.; Legacy display dimension arguments are rejected by the new entry.

Limits: Version-specific contract; must not apply older examples mechanically.

### A07 - Browser use tool

[https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-tool)

Supports: Page-aware references and tab state complement screenshots.; An observation may be attached to a permitted action result.; Tab-management result content has a distinct browser_state shape.

Limits: Viewport coordinates and browser element references differ from desktop display pixels.

### A08 - Latency optimization

[https://developers.openai.com/api/docs/guides/latency-optimization](https://developers.openai.com/api/docs/guides/latency-optimization)

Supports: Reduce unnecessary model requests.; Parallelize independent work.; Use ordinary code when model inference is unnecessary.; Evaluate quality and latency tradeoffs on actual workloads.

Limits: Illustrative percentages are not Litha benchmarks or guaranteed improvements.

### A09 - Browser and desktop drivers

[https://developers.openai.com/api/docs/guides/tools-computer-use-sdk-drivers](https://developers.openai.com/api/docs/guides/tools-computer-use-sdk-drivers)

Supports: Computer actions run in order and the helper does not retry driver actions.; Cropped screenshot coordinates require scale and origin mapping.; Browser CSS pixels differ from display pixels.; Uncertain effects need authoritative-state inspection before retry.

Limits: SDK example checks do not prove native Windows driver behavior.

### A10 - Browser and computer use with SDK toolsets

[https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-sdk](https://platform.claude.com/docs/en/agents-and-tools/tool-use/browser-use-sdk)

Supports: Drivers own image resizing and coordinate validation.; Zoom does not change the full screenshot coordinate frame.; Input checks and action limits remain executor responsibilities.

Limits: Do not apply a generic crop offset to full-frame zoom coordinates.

### A11 - Computer use integration recipes

[https://developers.openai.com/api/docs/guides/tools-computer-use-integration](https://developers.openai.com/api/docs/guides/tools-computer-use-integration)

Supports: Original screenshot detail recommended for computer use.; Resize when model limits require it and remap coordinates.; Local driver rehearsals can run without API calls.

Limits: Resolution recommendations are not verified optimal for Roblox Studio or Blender.

### A12 - Tool use with prompt caching

[https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching)

Supports: Toolset cache breakpoints apply after its definition.; A breakpoint within an action batch takes effect at the end of that batch.; Changes to tool/configuration prefixes can invalidate cache.

Limits: API prompt cache is distinct from local KV reuse; measure rather than infer savings.

### A13 - Mitigate jailbreaks and prompt injections

[https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks)

Supports: Keep third-party content in identifiable tool results.; Describe source and provenance.; Limit accessible data and action scope.

Limits: Structured wrapping and model classification do not prove content safe or authorized.

### D01 - UI Automation Control Patterns Overview

[https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview)

Supports: Patterns expose control capabilities; support can change dynamically.

### D02 - Caching UI Automation Properties and Control Patterns

[https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients)

Supports: Bulk fetching reduces per-property cross-process calls; cached-only references cannot invoke; updated cache does not mutate existing references.

### D03 - Subscribing to UI Automation Events

[https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-eventsforclients](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-eventsforclients)

Supports: Scoped events reduce polling; providers do not necessarily raise every event.

### D04 - Understanding Threading Issues

[https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-threading)

Supports: UIA client thread and COM MTA guidance; event registration/removal must not race across threads.

### D05 - SetForegroundWindow

[https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow)

Supports: Foreground activation is restricted and may fail; verify actual focus.

### D06 - SendInput

[https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

Supports: Returns inserted count; UIPI boundary and ambiguous failure causes; current key state matters.

### D07 - Understanding Screen Scaling Issues

[https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-screenscaling](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-screenscaling)

Supports: UIA uses physical coordinates; DPI virtualization requires an explicit mapping.

### D08 - MOUSEINPUT

[https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput)

Supports: Absolute normalized coordinates and virtual desktop flag semantics.

### D09 - Desktop Duplication API

[https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api)

Supports: DXGI frames, dirty/move rectangles, reconstruction order, cursor/rotation handling.

### D10 - Playwright Locators

[https://playwright.dev/docs/locators](https://playwright.dev/docs/locators)

Supports: Semantic locators and test identifiers are preferred to brittle DOM-structure selectors; locators re-resolve.

### D11 - Playwright Auto-waiting

[https://playwright.dev/docs/actionability](https://playwright.dev/docs/actionability)

Supports: Action-specific readiness checks and timeouts; click checks uniqueness, visibility, stability, events and enabled state.

### D12 - Playwright BrowserType persistent contexts

[https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-persistent-context)

Supports: User data directory ownership; multiple simultaneous instances cannot share it; default everyday Chrome profile automation is unsupported for this launch mechanism.

### D13 - Connect to Roblox Studio MCP server

[https://create.roblox.com/docs/studio/mcp](https://create.roblox.com/docs/studio/mcp)

Supports: Built-in local stdio MCP, script/data-model/playtest/capture/input tools, server enablement and explicit studio_id per call.

### D14 - StudioTestService

[https://create.roblox.com/docs/reference/engine/classes/StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService)

Supports: Plugin-security Run, Play, multiplayer test methods and returned test values.

### D15 - Blender Using Operators official source

[https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_operators.rst](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_operators.rst)

Supports: Context-dependent operators and poll failures; direct API approaches can avoid inappropriate operator contexts.

### D16 - Blender command-line arguments, 5.4 documentation

[https://docs.blender.org/manual/en/5.4/advanced/command_line/arguments.html](https://docs.blender.org/manual/en/5.4/advanced/command_line/arguments.html)

Supports: Background/Python invocation and --python-exit-code semantics; installed-version compatibility must be checked.

### D17 - Blender threading official source

[https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_threading.rst](https://github.com/blender/blender/blob/main/doc/python_api/rst/info_gotchas_threading.rst)

Supports: Blender Python integration is not thread-safe; long-lived threads can crash Blender; independent-process alternative.

### D18 - Microsoft UFO repository snapshot

[https://github.com/microsoft/UFO/tree/eae3c0a8d168c47cb10df0652e293e092eda1078](https://github.com/microsoft/UFO/tree/eae3c0a8d168c47cb10df0652e293e092eda1078)

Supports: Hybrid native/UI control and speculative multi-action design; 51% fewer calls is an author claim, not a reproduced Litha measurement.

### D19 - Microsoft UFO hybrid GUI/API actions

[https://github.com/microsoft/UFO/blob/eae3c0a8d168c47cb10df0652e293e092eda1078/documents/docs/ufo2/core_features/hybrid_actions.md](https://github.com/microsoft/UFO/blob/eae3c0a8d168c47cb10df0652e293e092eda1078/documents/docs/ufo2/core_features/hybrid_actions.md)

Supports: Application APIs and UI automation routed through hybrid action infrastructure.

### D20 - Microsoft OmniParser repository snapshot

[https://github.com/microsoft/OmniParser/tree/354021201345a96178360b28733573e27269f2de](https://github.com/microsoft/OmniParser/tree/354021201345a96178360b28733573e27269f2de)

Supports: Screenshot target parsing; latest README distinguishes v3 YOLOv9 MIT-based detector, legacy AGPL detector weights, MIT captions and CC-BY-4.0 repository.

### D21 - Litha existing uia.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py)

Supports: FindAllBuildCache already in use with cached-only property snapshots.

### D22 - Litha existing driver.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py)

Supports: Existing observe/perform/verify/retry loop and attempt-dependent settle_s sleeps.

### D23 - Litha existing eye.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py)

Supports: Existing bounded latest-frame capture wrapper and explicit region handling.

### D24 - Litha existing ground.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py)

Supports: Existing UIA/local/remote grounding chain and local grounding benchmark helper.

### E01 - OSWorld original project and version announcements

[https://osworld-v1.xlang.ai/](https://osworld-v1.xlang.ai/)

Supports: Original 369-task set and possible 361-task variant; Separate Verified and 2.0 announcements

Limits: Different releases and task counts are not directly interchangeable

### E02 - OSWorld 2.0 paper v2

[https://arxiv.org/abs/2606.29537v2](https://arxiv.org/abs/2606.29537v2)

Supports: 108 long-horizon workflows; Binary completion and partial progress differ; Reported human duration and tool-call counts are configuration-specific

Limits: Does not measure Litha or its target hardware

### E03 - OSWorld-V2 repository

[https://github.com/xlang-ai/OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2)

Supports: Pin matching code, tasks, assets, websites, provider images; Historical README instructions remain alongside active recommendations

Limits: Main is mutable; use the named manifest for actual runs

### E04 - OSWorld benchmark release policy

[https://github.com/xlang-ai/OSWorld-V2/blob/main/benchmark_releases/README.md](https://github.com/xlang-ai/OSWorld-V2/blob/main/benchmark_releases/README.md)

Supports: Concrete resolved versions and integrity checks distinguish comparable runs; Active manifests should not be silently changed

Limits: Policy text is not evidence that any particular run obeyed it

### E05 - OSWorld-Human paper v2

[https://arxiv.org/abs/2506.16042v2](https://arxiv.org/abs/2506.16042v2)

Supports: Temporal performance study identifies planning/reflection/judging latency; Revised abstract reports 2.7–4.3x excess steps

Limits: README retains a different 1.4–2.7x range; do not merge ranges; Reported effects are study-specific

### E06 - OSWorld-Human repository

[https://github.com/WukLab/osworld-human](https://github.com/WukLab/osworld-human)

Supports: Human reference action trajectories for efficiency scoring; Explicit instruction not to train on evaluation solutions

Limits: README result range differs from revised paper

### E07 - Windows Agent Arena repository

[https://github.com/microsoft/WindowsAgentArena](https://github.com/microsoft/WindowsAgentArena)

Supports: Real Windows evaluation; normal and hard modes differ; Full-suite duration uses parallel VMs; Historical cost table is not current pricing

Limits: Suite throughput is not one-agent task latency

### E08 - BrowserGym repository

[https://github.com/ServiceNow/BrowserGym](https://github.com/ServiceNow/BrowserGym)

Supports: Shared research environment across web benchmarks

Limits: Browser success does not establish native desktop success

### E09 - WebArena repository

[https://github.com/web-arena-x/webarena](https://github.com/web-arena-x/webarena)

Supports: Self-hostable web task environment

Limits: Dataset and environment revision affect comparisons

### E10 - VisualWebArena repository

[https://github.com/web-arena-x/visualwebarena](https://github.com/web-arena-x/visualwebarena)

Supports: Tasks require multimodal interpretation of web content

Limits: Visual-web coverage does not cover native applications

### E11 - WebArena-Verified repository

[https://github.com/ServiceNow/webarena-verified](https://github.com/ServiceNow/webarena-verified)

Supports: Audited tasks/evaluators and structural comparison; Offline evaluation from recorded network traces; 812 full tasks and 258 hard-subset tasks

Limits: Recorded-run rescoring is distinct from offline interaction

### E12 - WorkArena repository

[https://github.com/ServiceNow/WorkArena](https://github.com/ServiceNow/WorkArena)

Supports: Atomic and compositional ServiceNow tasks; Current setup requires approved instance-resource access

Limits: Not a ready-to-run offline benchmark without setup/access

### E13 - AgentLab repository

[https://github.com/ServiceNow/AgentLab](https://github.com/ServiceNow/AgentLab)

Supports: Explicit handling of job timeouts; Shared-instance task dependencies affect parallel evaluation

Limits: Suggested concurrency depends on memory and workload; not a Litha target

### E14 - Agent S3 usage documentation

[https://github.com/simular-ai/Agent-S/blob/main/gui_agents/s3/README.md](https://github.com/simular-ai/Agent-S/blob/main/gui_agents/s3/README.md)

Supports: Separate generation and grounding configuration; Example CLI is explicitly without multi-rollout selection; Grounding coordinate resolutions must match configuration

Limits: Example run differs from highest published multi-rollout score

### E15 - Scaling Agents for Computer Use

[https://arxiv.org/abs/2510.02250v2](https://arxiv.org/abs/2510.02250v2)

Supports: Behavior-based selection across multiple rollouts; Reported 72.6% OSWorld result uses scaling method

Limits: Not equivalent to single-rollout latency or universal human-level capability

### E16 - Evolving Agent Interfaces

[https://arxiv.org/abs/2610.28601](https://arxiv.org/abs/2610.28601)

Supports: Interface evolution from synthetic task experience with held-out validation; Reported 21.3% binary score with Qwen3.8-27B on OSWorld V2

Limits: Author-reported experimental result; no Litha speed/hardware evidence

### E17 - Agent S4 implementation documentation

[https://github.com/simular-ai/Agent-S/blob/main/agent_s4/README.md](https://github.com/simular-ai/Agent-S/blob/main/agent_s4/README.md)

Supports: Separate interface repository, bounded edit scope and budget; Tracked dispatch and validation reevaluation; Separate train, validation, and held-out test sets

Limits: Documented design is not an independent audit of all code paths

### E18 - OpenCUA repository

[https://github.com/xlang-ai/OpenCUA](https://github.com/xlang-ai/OpenCUA)

Supports: Distinct online task, grounding, and offline action evaluations; Current vLLM guidance and model-specific loading requirements

Limits: Single-GPU example does not establish 8 GB VRAM fit; Old headline claims remain historical

### E19 - UI-TARS repository

[https://github.com/bytedance/UI-TARS](https://github.com/bytedance/UI-TARS)

Supports: Separate task and grounding benchmark tables; Explicit step budgets for reported task results

Limits: Grounding accuracy and task completion are different metrics

### E20 - OmniParser repository

[https://github.com/microsoft/OmniParser](https://github.com/microsoft/OmniParser)

Supports: Screen parsing for downstream GUI agents

Limits: Parsing is not task verification or a complete controller

### R01 - Litha inspected source: star/computer/driver.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/driver.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R02 - Litha inspected source: star/computer/uia.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/uia.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R03 - Litha inspected source: star/computer/screen.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/screen.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/screen.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R04 - Litha inspected source: star/computer/eye.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/eye.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R05 - Litha inspected source: star/computer/ground.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/ground.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R06 - Litha inspected source: star/computer/hands.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/hands.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/hands.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R07 - Litha inspected source: star/computer/winapi.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/winapi.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/winapi.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R08 - Litha inspected source: star/studio.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/studio.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R09 - Litha inspected source: star/computer/settings.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/settings.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/settings.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R10 - Litha inspected source: star/computer/agent.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/agent.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/agent.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R11 - Litha inspected source: star/computer/__init__.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/__init__.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/__init__.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R12 - Litha inspected source: star/computer/live_vision.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/live_vision.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/live_vision.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R13 - Litha inspected source: star/computer/identity.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/identity.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/identity.py)

Limits: Source inspection; does not establish deployed behavior or native performance.

### R14 - Litha inspected source: star/computer/stopswitch.py

[https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/stopswitch.py](https://github.com/oncoursemail/Star-AI-Project/blob/a2f8ea5de8ccfa539795700f9d7e26c74ebd8e4f/star/computer/stopswitch.py)

Limits: Source inspection; does not establish deployed behavior or native performance.
