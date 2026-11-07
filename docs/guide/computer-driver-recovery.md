# Computer driver recovery and optional outcome waits
**Status:** Opt-in (off by default; a developer tool).

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
