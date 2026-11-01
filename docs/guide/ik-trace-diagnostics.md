# IK trace diagnostics: schema and verification notes
**Status:** Opt-in (off by default; a developer tool).

The new `star.ik_trace_quality` module is an opt-in offline diagnostic tool. It summarizes observations supplied by the caller. It does not capture Roblox/Blender frames, solve IK, prove animation quality, pass the repository's evaluation gate, promote a candidate, or change runtime settings.

## Invocation

```sh
python -m star.ik_trace_quality trace.json
```

The pure API is `report_ik_trace(payload)` and raises `ValueError` on malformed input. The CLI prints a JSON report and exits 0 for a valid trace; that exit code means validation and reporting succeeded, not that the animation passed a quality threshold. Invalid input exits 2 and produces no report on stdout.

## Complete version-1 schema

| Level | Field | Meaning |
|---|---|---|
| Trace | `schema_version` | Integer 1, not boolean or floating-point 1.0 |
| Trace | `rig_scale` | Finite positive normalization length in the same units as coordinates, within 1e-6..1e6 |
| Trace | `chains` | 1..64 objects with distinct names |
| Chain | `name` | Printable string of 1..128 characters |
| Chain | `samples` | 1..10000 samples, with at most 20000 across the trace |
| Sample | `t` | Seconds in 0..86400, strictly increasing within a chain, with at least 1e-6 seconds between samples; one timestamp ULP is allowed at that boundary |
| Sample | `effector`, `target` | Required xyz arrays, measured in the same consistent coordinate frame |
| Sample | `effector_q`, `target_q` | Optional pair of xyzw quaternions, unit length within 0.001; accepted quaternions are normalized for angular calculations |
| Sample | `contact` | Optional strict boolean; missing means unobserved |
| Sample | `contact_frame` | Optional stable support-local coordinate-frame identifier, string 1..128 printable characters |
| Sample | `contact_position`, `contact_anchor` | Optional xyz observations in that SAME support-local coordinate frame |

The three contact observation fields must either all be present or all absent. They may be present only with `contact: true`. True contact without coordinates is allowed and remains unmeasured for contact geometry. The anchor must remain fixed across adjacent measured samples of a continuous contact on the same support frame. A missing observation, absent/false contact, or changed frame identifier starts a new measured span. Reacquisition can use a different anchor. Never change the frame identifier every sample to hide slip; the module cannot establish the truth of a caller's capture data.

Coordinates must be finite numbers within +/-1e9. Booleans are not numbers. Unknown keys are rejected. The CLI rejects duplicate JSON object keys and NaN/Infinity constants, accepts regular files only, and reads at most 8 MiB. Engine/version/capture provenance belongs in a separate capture record; the schema deliberately does not accept arbitrary opaque metadata.

## What the metrics mean

Distances are divided by `rig_scale`; rates also divide by elapsed seconds. A scale of one meter means a residual of 0.01 is one centimeter. With a character height used as the scale, the same number means 1% of that height. Callers must record their scale convention alongside the capture.

Position residual compares effector and target at each observation. Quaternion residual is the shortest rotational geodesic in degrees; q and -q represent the same rotation. Step displacement, speed, velocity change and acceleration measure the effector in the supplied position frame. They are world-relative only if world-space positions were supplied. They cannot by themselves separate actor motion from support motion.

Contact residual compares the support-local position with its fixed anchor. Drift compares each later observation with the first observed contact position in the current continuous span. Slip speed uses adjacent support-local positions and the actual timestamp interval. One measured contact sample has a residual but cannot measure drift or slip speed. Missing contact geometry produces null metrics, not zero.

Velocity uses each actual adjacent time interval. Acceleration compares consecutive interval velocities divided by the separation between those intervals' midpoints, so unequal sampling intervals are handled explicitly. Angular speed also uses the actual interval, and no angular rate is bridged across a missing quaternion observation.

Angular displacement follows the shortest arc between sampled orientations. Sparse observations can hide a rotation greater than 180 degrees or a complete revolution; the module cannot recover motion that was not captured. Sampling coverage and engine provenance remain separate requirements.

Each metric reports `samples`, `mean`, `rms`, `p95` (nearest rank), and `max`. Statistics weight observations equally; they are not time-weighted integrals. Missing metrics have `samples: 0` and null numeric fields. The report always includes `engine_capture_verified: false` and `quality_proven: false`.

## Synthetic example 1: translating platform, planted foot

```json
{
  "schema_version": 1,
  "rig_scale": 1.0,
  "chains": [
    {
      "name": "left_foot",
      "samples": [
        {
          "t": 0.0,
          "effector": [0.0, 0.0, 0.0],
          "target": [0.0, 0.0, 0.0],
          "contact": true,
          "contact_frame": "platform_A_local",
          "contact_position": [0.0, 0.0, 0.0],
          "contact_anchor": [0.0, 0.0, 0.0]
        },
        {
          "t": 1.0,
          "effector": [1.0, 0.0, 0.0],
          "target": [1.0, 0.0, 0.0],
          "contact": true,
          "contact_frame": "platform_A_local",
          "contact_position": [0.0, 0.0, 0.0],
          "contact_anchor": [0.0, 0.0, 0.0]
        }
      ]
    }
  ]
}
```

Expected: positional residual 0; supplied-frame speed 1 rig unit/second; contact residual, drift and slip speed 0; orientation and acceleration unmeasured. This distinction prevents a correctly planted foot on a moving platform from being counted as sliding solely because it moves through world space.

## Synthetic example 2: irregular sampling of quadratic motion

With `rig_scale: 1`, times `[0, 1, 3]` and effector x positions `[0, 1, 9]`, interval speeds are `[1, 4]`. Velocity midpoints are at `[0.5, 2]`, so estimated acceleration is `(4-1)/(2-0.5) = 2` rig units/second squared. An assumed fixed frame rate would give a different and incorrect diagnostic for this trace.

## Synthetic example 3: contact reacquisition

| Time | Contact | Support-local position x | Anchor x | Interpretation |
|---:|---|---:|---:|---|
| 0 | true | 0 | 0 | First measured span starts |
| 1 | true | 0.1 | 0 | Drift 0.1 |
| 2 | false | omitted | omitted | Contact ends |
| 3 | true | 100 | 100 | New span starts, new anchor permitted |
| 4 | true | 100.2 | 100 | Drift 0.2 in the new span |

Expected: two measured spans and maximum within-span drift approximately 0.2. There is no 99.9-unit contact slip measurement across the swing/reacquisition gap. If time 2 instead says `contact: true` but omits all support observations, coverage is missing and the measured spans are likewise separate; the module cannot establish what happened during the gap.

## Validation completed in this environment

`benchmarks/verify_ik_trace_synthetic.py` ran 41 synthetic check groups successfully, including normalized positional error, nulls for missing observations, unequal timestamps, analytic acceleration, quaternion equivalence and angular rates, moving-platform coordinates, contact reacquisition, malformed input, numeric bounds, duplicate JSON keys and the byte-limited CLI. The script does not modify repository tests or evaluation fixtures. The independently authored `benchmarks/verify_ik_trace.py` contains 34 unittest methods. Both suites were rerun successfully on the final module. Their coverage overlaps; do not add the counts as unique cases. The independent script includes 25 seeded translation/scaling trials.

The independent `research/ik_independent_review.py` passed 34 unittest methods, including 25 seeded coordinate translation/scaling trials. Its report is `research/ik_review.md`. It also verified that a microsecond interval at a high timestamp is accepted within the stated ULP tolerance, a half-microsecond interval is rejected, and a FIFO input is rejected immediately.

No engine frame capture, real avatar, Roblox multiplayer session, Blender rig, packaged Windows executable or sealed evaluation was tested. These results establish only the exercised mathematical/schema behaviors of this new diagnostic module.

## Reproduce the committed developer checks

```sh
python benchmarks/verify_ik_trace.py -v
python benchmarks/verify_ik_trace_synthetic.py
python -m star.ik_trace_quality docs/research/examples/ik-moving-platform.synthetic.json
```

The example is deliberately synthetic. The checks are isolated developer validation of this diagnostic; they do not replace protected repository graders or activate a runtime feature.
