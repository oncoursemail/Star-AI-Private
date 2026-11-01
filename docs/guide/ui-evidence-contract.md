# UI evidence contracts

**Status: Opt-in (experimental, off by default).** This extends the existing read-only
`workspace_starry_eye_audit` tool. It checks whether supplied evidence covers an
explicit set of required UI cases. It does not launch a browser or Roblox Studio,
take screenshots, authenticate a capture, certify accessibility, or approve a design.

Use this when a UI must be reviewed across different screens, states, viewport
sizes, input methods or motion preferences. A good desktop screenshot should not
hide a missing phone, error-state or keyboard test.

## Enable and call

Set `STAR_UI_EVIDENCE=on` in the process running Litha. For a development session in
PowerShell, set `$env:STAR_UI_EVIDENCE = "on"` before launching the application from
that shell. Unset it to turn this experiment off. This does not enable workspace
writes, engine execution or any external service.

Select the workspace containing the evidence files, then call:

```json
{
  "path": "quality.json",
  "ui_contract_path": "ui-contract.json"
}
```

The tool name is `workspace_starry_eye_audit`. Python callers can use
`star.starry_eye_quality.audit(workspace, "quality.json", ui_contract_path="ui-contract.json")`.
Supplying a contract while the experiment is off returns an error. Omitting
`ui_contract_path` keeps the existing audit path and does not evaluate UI coverage,
even if the manifest happens to contain `ui_observations`.

## 1. Write requirements before collecting evidence

A contract contains version `1`, target `web` or `roblox`, and one to twelve cases.
Each case explicitly identifies its conditions. Choose representative risks; do
not automatically multiply every possible dimension into a huge matrix.

```json
{
  "version": 1,
  "target": "web",
  "cases": [
    {
      "id": "menu-phone",
      "screen": "menu",
      "state": "default",
      "viewport": {"width": 390, "height": 844, "unit": "css_px"},
      "input": "touch",
      "motion": "default",
      "elements": ["Play", "Settings"]
    },
    {
      "id": "menu-keyboard-reduced",
      "screen": "menu",
      "state": "settings-open",
      "viewport": {"width": 1280, "height": 800, "unit": "css_px"},
      "input": "keyboard",
      "motion": "reduced",
      "elements": ["SettingsDialog", "Close"],
      "events": ["dialog-open", "focus-enter", "escape-close", "focus-return"]
    }
  ]
}
```

| Field | Meaning and bounds |
| --- | --- |
| `id`, `screen`, `state` | Stable IDs beginning with a letter, followed by letters, digits, `_`, `-` or `.`, at most 64 characters. |
| `viewport` | Exact integer width and height: web 100–8192 `css_px`; Roblox 200–8192 `rendered_px`. Captures still require 200–8192 PNG pixels per dimension and at most 16 million pixels overall. |
| `input` | `pointer`, `keyboard`, `touch` or `gamepad`. |
| `motion` | `default` or `reduced`. This is a requested condition, not a behavioral assertion. |
| `elements` | One to 32 unique IDs that must have supplied layout records for the capture. This does not recognize controls in pixels. |
| `events` | Optional ordered sequence of one to 16 event names. Repeated names require repeated events. Additional intervening events are allowed. |

Case IDs and complete condition combinations must be distinct. Unknown fields,
unsupported versions, booleans masquerading as numbers, nonfinite numbers and
duplicate JSON object keys are rejected. There is no `passed`, `skip` or
`owner_approved` override.

The twelve-case limit matches the existing screenshot collector. Divide larger
products into explicit artifact audits and retain the results of every required
audit; one complete batch does not establish that the whole product is covered.

## 2. Capture and describe the actual state

Keep the existing quality manifest fields:

```json
{
  "project": "ExampleGame",
  "artifact": "menu",
  "source": "src/Menu.tsx",
  "sources": ["src/Menu.tsx", "src/menu.css"],
  "views": {
    "phone": {"file": "captures/phone.png", "width": 780, "height": 1688},
    "keyboard": {"file": "captures/keyboard.png", "width": 1280, "height": 800}
  },
  "layout": {
    "phone": [
      {"id": "Play", "rect": [48, 200, 684, 104], "interactive": true},
      {"id": "Settings", "rect": [48, 328, 684, 104], "interactive": true}
    ],
    "keyboard": [
      {"id": "SettingsDialog", "rect": [400, 200, 480, 400]},
      {"id": "Close", "rect": [808, 224, 48, 48], "interactive": true}
    ]
  }
}
```

This example describes intended file names and geometry; it is not a runtime
capture or measured layout. Replace the rectangles with measurements from the
actual browser or engine. Include all relevant source files in `sources`.
The verifier cannot discover that an important stylesheet or dependency was omitted.

Each view still has exactly `file`, `width` and `height`. The existing collector
checks that the file is a real decodable PNG with those dimensions, at most
8192 pixels per dimension and 16 million pixels overall. Its minimum dimension
is 200 pixels. Source, image and JSON size limits also apply.

Add a `ui_observations` list to this manifest. Every observation must provide:

- `case`: the required case ID, and `view`: its captured view name.
- `screen`, `state`, `viewport`, `input`, `motion`: the actual recorded conditions,
  using the same field shapes as the contract.
- `pixel_ratio`: captured PNG pixels per viewport unit, between 1 and 4. For
  Roblox it must be 1. For a 390 CSS-pixel-wide viewport captured as 780 PNG pixels,
  use 2. A browser configured to save CSS-scale screenshots uses 1 even on a Retina
  display. This value is not automatically the browser's `devicePixelRatio`.
  Expected PNG dimensions are viewport dimensions times this scale, rounded to
  the nearest integer with halves rounded up.
- `sources_sha256`: a mapping from every manifest source path to its SHA-256.
- `capture_sha256`: SHA-256 of the exact PNG file bytes.
- `trace_sha256`: required for a case with `events` to be complete; SHA-256 of the
  exact trace file bytes.

Source and capture hashes are ordinary lowercase 64-character hexadecimal
digests. A collector should compute them from the files it actually used and
retain the observed context with them. Calculating a hash after the fact cannot
prove that an image was produced by that source revision. These bindings detect
inconsistency; they are not signatures or authenticated execution receipts.

Each case can have one observation and each observation must reference a distinct
view. Two separately recorded views may have identical image bytes: a static
screen can legitimately look the same under two different input settings.
Renaming a view alone does not prove those settings were exercised.

**Coordinate spaces matter.** Existing `layout.rect` values are in captured PNG
pixels, including on web targets. The new contract checks viewport-to-image scale
and required element presence. It does not convert the existing target-size checks
to CSS pixels or apply all WCAG target-size exceptions.

## 3. Bind interaction evidence to the case

For cases with required events, add `trace_file` to the manifest. The trace needs
the existing `engine`, `run_finished`, `events` and optional `metrics`, plus a
`sources_sha256` map matching the complete declared source set.

Each UI event relevant to a case carries its case ID and capture digest:

```json
{
  "name": "focus-enter",
  "t_ms": 120,
  "case_id": "menu-keyboard-reduced",
  "capture_sha256": "REPLACE_WITH_ACTUAL_LOWERCASE_SHA256"
}
```

The placeholder above is deliberately not a valid digest. A real collector must
record the actual digest. Existing non-UI engine events can remain in the trace;
events without the required case binding cannot satisfy that UI case. Timestamps
must be ordered, finite, nonnegative and no later than one hour. At most 500
events are accepted. The trace engine must match the contract target.

The inspector looks for the required event sequence within the events bound to
that case. It does not execute those actions or interpret the event names as
proof of correct browser semantics. An event called `focus-return` is still a
supplied record. A later live collector should verify focus state itself and
record its assertion outcome.

Missing or unfinished trace evidence remains unverified. A completed, correctly
bound trace that contains the case but lacks its required sequence fails. Stale
trace bytes, mismatched source hashes or a different capture binding fail.

## Read the result

| Overall result | What it means |
| --- | --- |
| `automated_checks_failed` | At least one checked condition contradicts the requirements: for example low contrast, a stale digest, wrong viewport, conflicting label or missing ordered event in a bound completed trace. |
| `insufficient_evidence` | A required case, capture, element record or trace binding is missing, or no checks could be made. |
| `automated_checks_passed` | The supplied data passed the checks that were performed. This remains distinct from runtime execution, accessibility conformance and visual approval. |

`ui_coverage.status` is `declared_coverage_complete` only when the explicit case
requirements are satisfied by the supplied declarations and bindings. Its result
always reports that capture authenticity, accessibility conformance, motion
preference behavior and owner approval have not been proven.

The report includes compact per-case status and actionable `findings`. Counts
include findings omitted by the existing 100-record display limit;
`findings_omitted` makes that truncation explicit. A long report cannot turn a
failed audit into a pass.

`evidence_key` retains the existing source/image identity.
`ui_contract_sha256` fingerprints the exact contract bytes, and `ui_audit_key`
also binds the manifest, contract and trace to that evidence identity. Editing
requirements or changing observation labels changes this audit key even when
the pictures stay identical. Neither key grants approval or execution authority.

## Design and verification still require judgment

Use the existing design database for bounded reference retrieval, preserve the
project's authored `DESIGN.md`, and choose native components for the target.
Inspect real renderings, interact with controls and review the hierarchy, copy,
spacing and motion purpose. For web, combine DOM/axe checks with keyboard and
human review. For Roblox, use the existing Studio device lab and inspect editable
instances and actual engine bounds.

See [the research and adoption decisions](../research/LITHA_UI_RESEARCH_20261101.md)
for the complete source review, objective checks, design heuristics and next
implementation priorities.
